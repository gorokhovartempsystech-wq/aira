"""Explicit password verification and detached operator settings."""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from ara.licensing.server._models import ServerError


class AdminError(ServerError):
    def __init__(self, status, code):
        self.status, self.code = status, code
        Exception.__init__(self, code)


def need(condition, status=422, code="invalid_input"):
    if not condition:
        raise AdminError(status, code)


def password_hash(password, salt=None):
    need(type(password) is str and 16 <= len(password) <= 256)
    salt = secrets.token_bytes(16) if salt is None else salt
    need(type(salt) is bytes and len(salt) == 16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, maxmem=67108864)
    return "scr1$" + salt.hex() + "$" + digest.hex()


def verify_password(password, stored):
    if type(password) is not str or not 1 <= len(password) <= 256:
        return False
    _, salt, expected = stored.split("$")
    actual = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1, maxmem=67108864
    ).hex()
    return hmac.compare_digest(actual, expected)


@dataclass(frozen=True)
class Settings:
    origin: str
    username: str
    password: str = field(repr=False)
    secret: bytes = field(repr=False)

    def __post_init__(self):
        parsed = urlsplit(self.origin)
        need(
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and parsed.path == ""
            and not parsed.query
            and not parsed.fragment
        )
        need(re.fullmatch(r"[a-z][a-z0-9._-]{0,31}", self.username) is not None)
        need(re.fullmatch(r"scr1\$[0-9a-f]{32}\$[0-9a-f]{128}", self.password) is not None)
        need(type(self.secret) is bytes and len(self.secret) == 32)

    def mac(self, domain, value):
        return hmac.new(
            self.secret, domain.encode() + b"\0" + value.encode(), hashlib.sha256
        ).hexdigest()

    @property
    def revision(self):
        return self.mac("credentials", self.username + "\0" + self.password)


def load_settings(values):
    return Settings(
        values["AIRA_LICENSE_ADMIN_ORIGIN"],
        values["AIRA_LICENSE_ADMIN_USERNAME"],
        values["AIRA_LICENSE_ADMIN_PASSWORD_HASH"],
        bytes.fromhex(values["AIRA_LICENSE_ADMIN_SESSION_KEY"]),
    )
