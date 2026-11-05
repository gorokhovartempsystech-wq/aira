"""Immutable installation metadata; no filesystem or execution authority."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

_MESSAGES = {
    "validation_error": "Invalid installation input",
    "package_unavailable": "Installation files are unavailable",
    "package_invalid": "Installation structure is invalid",
    "package_mismatch": "Installation content does not match the expected package",
    "unsupported_target": "Installation target does not match this launch profile",
    "fixture_not_allowed": "Fixture installation requires explicit permission",
}


class PackageError(Exception):
    def __init__(self, code="package_invalid"):
        self.code = code if type(code) is str and code in _MESSAGES else "package_invalid"
        self.message = _MESSAGES[self.code]
        super().__init__(self.message)


def require(value, code="package_invalid"):
    if not value:
        raise PackageError(code) from None


@dataclass(frozen=True)
class FileRecord:
    path: str = field(repr=False)
    size: int
    sha256: str = field(repr=False)
    executable: bool


@dataclass(frozen=True)
class InstallationManifest:
    version: str
    target: str
    kind: str
    sha256: str = field(repr=False)
    files: tuple[FileRecord, ...] = field(repr=False)
    entrypoints: Mapping[str, str | None] = field(repr=False)
    model_manifest_sha256: str | None = field(repr=False)
    total_bytes: int


@dataclass(frozen=True)
class VerifiedInstallation:
    root: Path = field(repr=False)
    manifest: InstallationManifest

    def role_path(self, role):
        require(type(role) is str and role in self.manifest.entrypoints, "validation_error")
        path = self.manifest.entrypoints[role]
        require(path is not None, "validation_error")
        return self.root.joinpath(*path.split("/"))
