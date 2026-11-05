"""Single owner of all C1A transitions; callbacks and I/O run only on fixed lanes."""

import time
from uuid import uuid4

from ara.documents.runtime import DocumentRuntime
from ara.docx_analysis_runs import _lifecycle as old

from . import _admission, _attempt, _recovery, database, ledger
from ._exit_authority import ExitIssuer


class Coordinator:
    def __init__(self, supervisor):
        self.s = supervisor
        self.owner = self.fence = None
        self.startup = "owner"
        self.epoch = uuid4()
        self.last = 0
        self.storage_broken = False
        self.recover_at = 0
        self.reaper_at = 0
        self.disposed = set()
        self.owner_closed = False
        self.closing_threads = False
        self.issuer = None

    def runtime(self, lane="control"):
        return DocumentRuntime(
            engine=getattr(self.s._engines, lane),
            user_id=self.s._user_id,
            project_id=self.s._project_id,
            mode="local",
        )

    def entries(self):
        with self.s._lock:
            return tuple(self.s._entries.values())

    def sample(self):
        try:
            now = self.s._platform.clock()
            if type(now) is not int or not self.last <= now < 2**63:
                raise ValueError()
            self.last = now
        except Exception:
            self.s._clock_fault = True
        return self.last

    def block(self, code):
        with self.s._lock:
            self.s._phase, self.s._error, self.s._quarantine = "blocked", code, True
        for e in self.entries():
            if e.reason is None and e.intent is None:
                e.intent = "protocol"

    def storage_fault(self):
        self.storage_broken = True
        with self.s._lock:
            if not self.s._quarantine:
                self.s._phase, self.s._error = "blocked", "storage_unavailable"
        for e in self.entries():
            if e.intent is None:
                e.intent = "storage"

    def submit(self, lane, tag, fn, entry=None):
        worker = self.s._lanes[lane]
        if worker.busy or lane in self.s._pending:
            return False
        generation = entry.generation if entry is not None else self.epoch
        with self.s._lock:
            self.s._pending[lane] = tag, entry, generation
        try:
            worker.submit(generation, fn)
        except Exception:
            self.block("internal_error")
            return False
        return True

    def retry(self, entry):
        entry.retry_at = time.monotonic() + entry.backoff
        entry.backoff = min(2, entry.backoff * 2)

    def busy(self, entry, *lanes):
        return any(
            (item := self.s._pending.get(name)) is not None and item[1] is entry for name in lanes
        )

    def remove(self, entry):
        entry.snapshot = entry.view()
        entry.discard_payloads()
        with self.s._lock:
            self.s._entries.pop((entry.command.document_id, entry.key), None)
            if self.s._active is entry:
                self.s._active = None

    def snapshots(self):
        for e in self.entries():
            view = e.view()
            with self.s._lock:
                e.snapshot = view

    def tick(self):
        now = self.sample()
        for e in self.entries():
            if e.dispatcher is not None:
                if e.intent:
                    e.dispatcher.request_stop(e.intent)
                view = e.dispatcher.step().control
                if view.stop_requested and e.reason is None:
                    e.reason = view.stop_reason
            elif e.reason is None:
                if self.s._clock_fault:
                    e.reason = "clock"
                elif now >= e.deadline:
                    e.reason = "deadline"
                elif e.intent:
                    e.reason = e.intent
            if e.reason and not e.terminal and e.phase == "active":
                e.phase = "settling"

    def results(self):
        for name, lane in self.s._lanes.items():
            cell = lane.take()
            if cell is None:
                continue
            with self.s._lock:
                item = self.s._pending.pop(name, None)
            if item is None or item[2] != cell.generation:
                self.block("recovery_required")
                continue
            tag, e, _ = item
            if tag == "reap":
                if cell.error:
                    self.storage_fault()
            elif tag in ("admit", "lookup"):
                _admission.result(self, tag, e, cell)
            elif e is not None:
                _attempt.result(self, tag, e, cell)
            else:
                self.startup_result(tag, cell)

    def startup_result(self, tag, cell):
        if cell.error:
            self.block("recovery_required")
            self.startup = "blocked"
            return
        value = cell.value
        if tag == "owner":
            self.owner, self.startup = value, "check"
        elif tag == "check":
            self.fence = value
            if (
                value.phase not in ("clean", "drained")
                or value.installation_id != self.s._installation_id
            ):
                self.block("recovery_required")
                self.startup = "blocked"
            else:
                self.startup = "take"
        elif tag == "take":
            self.fence, self.startup = value, "retire"
        elif tag == "retire":
            if value:
                self.startup = "restore" if self.fence.phase == "drained" else "probe"
            else:
                self.recover_at = time.monotonic() + 0.25
        elif tag == "restore":
            if value.summary.status not in old.TERMINAL:
                self.startup = "retire"
            else:
                self.startup = "probe"
        elif tag == "probe":
            if value is not True:
                self.block("recovery_required")
                self.startup = "blocked"
            elif self.fence.phase == "drained":
                self.startup = "clear_old"
            else:
                self.startup = "ready"
        elif tag == "clear_old":
            self.fence, self.startup = value, "ready"
        elif tag == "close_owner":
            self.owner_closed = True
        elif tag.startswith("dispose_"):
            self.disposed.add(tag.removeprefix("dispose_"))
        if self.startup == "ready" and not self.s._shutdown and not self.s._quarantine:
            with self.s._lock:
                self.s._phase = "ready"

    def drive_startup(self):
        engine = self.s._engines.control
        if self.startup == "owner":
            self.submit("lifecycle", "owner", lambda: self.s._platform.acquire_owner(self.s._root))
        elif self.startup == "check":

            def check():
                database.check_database(engine)
                return ledger.read_fence(engine)

            self.submit("control", "check", check)
        elif self.startup == "take":
            self.submit(
                "control",
                "take",
                lambda: ledger.take_ownership(
                    engine, owner=self.s._owner_binding, expected_revision=self.fence.revision
                ),
            )
        elif self.startup == "retire" and time.monotonic() >= self.recover_at:
            self.submit("control", "retire", lambda: _recovery.retire(engine))
        elif self.startup == "restore":
            from ._queries import restore_closed

            self.submit(
                "publication",
                "restore",
                lambda: restore_closed(self.s._engines.publication, self.fence.binding),
            )
        elif self.startup == "probe":

            def probe():
                slot = self.s._platform.reserve_slot(self.owner)
                return self.s._platform.release_slot(self.owner, slot)

            self.submit("lifecycle", "probe", probe)
        elif self.startup == "clear_old":
            self.submit(
                "control",
                "clear_old",
                lambda: ledger.clear_drained(
                    engine, binding=self.fence.binding, expected_revision=self.fence.revision
                ),
            )

    def cleanup(self):
        if self.entries() or self.s._pending:
            return False
        if not self.owner_closed and self.owner is not None:
            self.submit(
                "lifecycle", "close_owner", lambda: self.s._platform.close_owner(self.owner)
            )
            return False
        for name in ("admission", "control", "publication"):
            if name not in self.disposed:
                self.submit(name, "dispose_" + name, getattr(self.s._engines, name).dispose)
        if len(self.disposed) != 3:
            return False
        for lane in self.s._lanes.values():
            lane.close()
        if any(lane.thread.is_alive() for lane in self.s._lanes.values()):
            return False
        with self.s._lock:
            self.s._phase = "closed"
        return True

    def run(self):
        while not self.s._start_ack.wait(0.005):
            if self.s._start_failed:
                return
        while not all(lane.ready.is_set() for lane in self.s._lanes.values()):
            self.s._wake.wait(0.005)
        self.issuer = ExitIssuer(self.s._owner_binding, self.s._project_id, self.s._user_id)
        try:
            while True:
                self.s._wake.clear()
                self.tick()
                self.results()
                self.tick()
                if self.startup not in ("ready", "blocked"):
                    self.drive_startup()
                elif self.startup == "ready":
                    _admission.drive(self)
                    _attempt.drive(self)
                    if time.monotonic() >= self.reaper_at and not self.s._shutdown:
                        if self.submit(
                            "control",
                            "reap",
                            lambda: old.reap_expired(self.s._engines.control, limit=32),
                        ):
                            self.reaper_at = time.monotonic() + 1
                    if (
                        self.storage_broken
                        and not self.entries()
                        and not self.s._pending
                        and self.fence.phase == "clean"
                        and not self.s._quarantine
                    ):
                        self.storage_broken = False
                        with self.s._lock:
                            self.s._phase, self.s._error = "ready", None
                if self.s._shutdown and self.cleanup():
                    return
                self.snapshots()
                self.s._wake.wait(0.005 if self.s._active is not None or self.s._pending else 0.05)
        except BaseException:
            self.block("internal_error")
        finally:
            if self.s._phase == "closed":
                self.s._finished.set()
