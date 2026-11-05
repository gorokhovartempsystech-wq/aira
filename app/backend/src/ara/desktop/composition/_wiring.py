"""Single owner of the issued components; dependencies outlive every accepted write."""

import time

from ara.app import create_app
from ara.desktop.data_home import open_home
from ara.desktop.database import bind_database
from ara.desktop.postgres_cluster import ClusterRuntime
from ara.desktop.postgres_schema import SchemaPreparation
from ara.desktop.postgres_upgrade import UpgradePreparation
from ara.desktop.server import LoopbackServer
from ara.docx_analysis_worker.macos import DarwinClock
from ara.docx_analysis_worker.supervisor.review_fixture import create_review_fixture_supervisor
from ara.licensing.client import ActivationStore, LicenseClient

from ._models import DesktopError, Stopped, require

STARTUP_NS = 900_000_000_000


class Session:
    def __init__(self, owner):
        self.owner, self.config = owner, owner._config
        self.home = self.cluster = self.upgrade = self.schema = self.source = None
        self.supervisor = self.client = self.server = self.app = None
        self.unknown = False
        self.clock, self.begin, self.last = DarwinClock(), None, None

    def check(self):
        if self.owner._stop.is_set():
            raise Stopped()
        try:
            now = self.clock.now_ns()
            require(type(now) is int and 0 <= now < 2**63, "clock_unavailable")
            require(self.last is None or self.last <= now, "clock_unavailable")
            self.last = now
            if self.begin is None:
                self.begin = now
            require(now - self.begin <= STARTUP_NS, "startup_timeout")
        except DesktopError:
            raise
        except BaseException:
            raise DesktopError("clock_unavailable") from None

    def stage(self, name):
        self.check()
        self.owner._stage_at(name)

    def wait(self, component, phases=("ready",), *, settled=False):
        component.start()
        while True:
            self.check()
            view = component.view()
            if view.phase in phases and (not settled or not view.resources_pending):
                self.check()
                return
            require(view.phase not in ("failed", "closed", "blocked"), "startup_failed")
            self.owner._stop.wait(0.01)

    def start(self):
        cfg = self.config
        mode = cfg.analysis_mode
        require(
            type(mode) is str
            and mode
            in (
                "legacy_fixture",
                "structured_fixture",
                "outline_fixture",
                "style_lists_fixture",
                "word_fixture",
            )
        )
        self.stage("home")
        self.unknown = True  # Failed factory may retain an unreturned native Home record.
        self.home = open_home(cfg.home)
        self.unknown = False
        self.stage("postgres")
        self.cluster = ClusterRuntime(self.home, cfg.postgres)
        self.wait(self.cluster)
        self.stage("upgrade")
        self.upgrade = UpgradePreparation(
            self.home,
            self.cluster,
            migrations=cfg.migrations,
            tools=cfg.upgrade,
            **(
                {}
                if cfg.schema_revision == "0013_docx_review_preferences"
                else {"target_revision": cfg.schema_revision}
            ),
        )
        self.wait(self.upgrade, ("ready", "not_needed"), settled=True)
        self.upgrade.result()
        self.stage("schema")
        self.schema = SchemaPreparation(
            self.home,
            self.cluster,
            migrations=cfg.migrations,
            **(
                {}
                if cfg.schema_revision == "0013_docx_review_preferences"
                else {"revision": cfg.schema_revision}
            ),
        )
        self.wait(self.schema, settled=True)
        self.stage("database")
        self.source = bind_database(self.home, self.cluster, schema=self.schema)
        runtime = self.source.document_runtime()
        self.stage("analysis")
        identity = self.home.identity()
        factory = create_review_fixture_supervisor
        if mode == "structured_fixture":
            from ara.docx_analysis_worker.supervisor.structured_fixture import (
                create_structured_fixture_supervisor,
            )

            factory = create_structured_fixture_supervisor
        elif mode == "outline_fixture":
            from ara.docx_analysis_worker.supervisor.outline_fixture import (
                create_outline_fixture_supervisor,
            )

            factory = create_outline_fixture_supervisor
        elif mode == "style_lists_fixture":
            from ara.docx_analysis_worker.supervisor.style_lists_fixture import (
                create_style_list_fixture_supervisor,
            )

            factory = create_style_list_fixture_supervisor
        elif mode == "word_fixture":
            from ara.docx_analysis_worker.supervisor.word_fixture import (
                create_word_fixture_supervisor,
            )

            factory = create_word_fixture_supervisor
        self.supervisor = factory(
            settings=self.source.settings(),
            user_id=identity.user_id,
            project_id=identity.project_id,
            installation_id=identity.installation_id,
            root=self.home.path("analysis"),
        )
        self.wait(self.supervisor)
        self.stage("http")
        self.client = LicenseClient(
            cfg.license_origin,
            ActivationStore(self.home.path("license")),
            device_provider=cfg.device_provider,
            clock=cfg.clock,
            transport=cfg.transport,
        )
        self.app = create_app(
            document_runtime=runtime,
            analysis_supervisor=self.supervisor,
            table_editor=mode == "word_fixture",
        )
        self.server = LoopbackServer(self.app, self.client)
        self.wait(self.server)
        self.check()

    def healthy(self):
        return all(
            component.view().phase == "ready"
            for component in (self.cluster, self.source, self.supervisor, self.server)
        )

    def connection(self):
        return self.server.connection() if self.server is not None else None

    def drain(self, component):
        if component is None:
            return True
        while not component.shutdown(timeout=0.1):
            view = component.view() if hasattr(component, "view") else None
            if getattr(view, "error_code", None) == "cleanup_unknown":
                return False
            if getattr(view, "recovery_required", False):
                return False
            if hasattr(view, "clean_shutdown") and not view.resources_pending:
                return False
            # Shutdown may return immediately while waiting on another owned worker.
            time.sleep(0.05)
        return True

    def close(self):
        if self.unknown:
            return False
        try:
            # Do not let a later stage destroy dependencies of an unfinished earlier one.
            for component in (
                self.server,
                self.client,
                self.supervisor,
                self.schema,
                self.upgrade,
                self.source,
                self.cluster,
            ):
                if not self.drain(component):
                    return False
            return self.home is None or self.home.close()
        except BaseException:
            return False
