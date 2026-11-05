"""Pinned installation inventory; explicit read-only verification, never execution."""

from ._files import verify_installation
from ._manifest import parse_manifest
from ._models import FileRecord, InstallationManifest, PackageError, VerifiedInstallation

__all__ = [
    "FileRecord",
    "InstallationManifest",
    "PackageError",
    "VerifiedInstallation",
    "parse_manifest",
    "verify_installation",
]
