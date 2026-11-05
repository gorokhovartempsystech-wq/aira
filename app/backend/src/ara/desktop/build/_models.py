"""Closed build arguments and content-safe results; imports do no runtime work."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from ara.desktop.installation import VerifiedInstallation
from ara.desktop.installation._manifest import ROLES, TARGETS, _path

_MESSAGES = {
    "validation_error": "Invalid payload build input",
    "source_unavailable": "Staged files are unavailable",
    "source_invalid": "Staged payload structure is invalid",
    "source_changed": "Staged files changed or could not be revalidated",
    "destination_exists": "Build destination already exists",
    "destination_unavailable": "Build destination is unavailable",
    "build_failed": "Payload assembly did not complete",
}


class BuildError(Exception):
    def __init__(self, code="build_failed"):
        self.code = code if type(code) is str and code in _MESSAGES else "build_failed"
        self.message = _MESSAGES[self.code]
        super().__init__(self.message)


def require(value, code="validation_error"):
    if not value:
        raise BuildError(code) from None


@dataclass(frozen=True)
class BuildReceipt:
    installation: VerifiedInstallation = field(repr=False)
    manifest_bytes: bytes = field(repr=False)
    manifest_sha256: str


def arguments(source, destination, version, target, kind, entrypoints, extra_executables):
    try:
        require(
            all(
                isinstance(p, Path) and p.is_absolute() and ".." not in p.parts
                for p in (source, destination)
            )
            and bool(destination.name)
        )
        require(type(version) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", version))
        require(type(target) is str and target in TARGETS)
        require(type(kind) is str and kind in ("production", "fixture"))
        require(type(entrypoints) is dict and all(type(k) is str for k in entrypoints))
        require(set(entrypoints) == ROLES)
        roles = dict(entrypoints)
        for role, value in roles.items():
            if role == "model_manifest" and kind == "fixture":
                require(value is None)
            else:
                _path(value)
        require(type(extra_executables) is tuple and len(extra_executables) <= 32768)
        for path in extra_executables:
            _path(path)
        require(len(set(extra_executables)) == len(extra_executables))
        return dict(version=version, target=target, kind=kind, entrypoints=roles), extra_executables
    except BuildError:
        raise
    except Exception:
        raise BuildError("validation_error") from None
