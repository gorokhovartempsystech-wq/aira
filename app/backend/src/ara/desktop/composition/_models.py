"""Explicit fixture configuration; paths are metadata, not installer attestations."""

import math
from dataclasses import dataclass, field
from pathlib import Path

from ara.desktop.postgres_cluster import PgTools
from ara.desktop.postgres_cluster._models import checked_path
from ara.desktop.postgres_upgrade import UpgradeTools
from ara.licensing.client import HttpsTransport

CODES = frozenset(
    "validation_error invalid_handle desktop_busy platform_unavailable startup_failed "
    "startup_timeout clock_unavailable runtime_failed cleanup_unknown".split()
)


class DesktopError(Exception):
    def __init__(self, code="startup_failed"):
        self.code = code if type(code) is str and code in CODES else "startup_failed"
        super().__init__("Local fixture desktop: " + self.code)


def require(value, code="validation_error"):
    if not value:
        raise DesktopError(code) from None


def budget(timeout):
    require(type(timeout) in (int, float) and 0 <= timeout <= 5 and math.isfinite(timeout))


class Stopped(Exception):
    pass


@dataclass(frozen=True)
class FixtureConfig:
    home: Path = field(repr=False)
    postgres: PgTools = field(repr=False)
    upgrade: UpgradeTools = field(repr=False)
    migrations: Path = field(repr=False)
    license_origin: str = field(repr=False)
    device_provider: object = field(default=None, repr=False)
    clock: object = field(default=None, repr=False)
    transport: object = field(default=None, repr=False)
    analysis_mode: str = "legacy_fixture"

    def __post_init__(self):
        try:
            require(
                type(self.analysis_mode) is str
                and self.analysis_mode
                in (
                    "legacy_fixture",
                    "structured_fixture",
                    "outline_fixture",
                    "style_lists_fixture",
                    "word_fixture",
                )
            )
            checked_path(self.home)
            checked_path(self.migrations)
            require(bool(self.home.name))
            require(type(self.postgres) is PgTools and type(self.upgrade) is UpgradeTools)
            require(self.postgres.postgres.parent == self.upgrade.dump.parent)
            HttpsTransport(self.license_origin)
            require(self.device_provider is None or callable(self.device_provider))
        except Exception:
            raise DesktopError("validation_error") from None


@dataclass(frozen=True)
class DesktopView:
    phase: str
    stage: str | None
    error_code: str | None
    resources_pending: bool
    fixture: bool = True
