"""Closed, bounded private bootstrap and status frames."""

import base64
import json
import unicodedata
from pathlib import Path

from ._models import CommandError, require

BOOTSTRAP_LIMIT = 16384
OUTPUT_LIMIT = 65536
STATUS_LIMIT = 100000
ENVIRONMENT = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C", "TZ": "UTC"}


def text(value, limit=4096):
    require(type(value) is str)
    try:
        require(len(value.encode("utf-8")) <= limit)
    except UnicodeError:
        raise CommandError("validation_error") from None
    require(not any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in value))
    return value


def absolute(value):
    require(isinstance(value, Path) and value.is_absolute() and ".." not in value.parts)
    return text(str(value))


def bootstrap(executable, arguments, cwd, capture):
    require(type(arguments) is tuple and len(arguments) <= 128)
    require(type(capture) is bool)
    value = dict(
        version=1,
        argv=[absolute(executable), *(text(v) for v in arguments)],
        cwd=absolute(cwd),
        capture=capture,
    )
    encoded = frame(value)
    require(len(encoded) <= BOOTSTRAP_LIMIT)
    return encoded


def frame(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"


def pairs(values):
    result = {}
    for key, value in values:
        require(key not in result, "protocol_error")
        result[key] = value
    return result


def invalid_constant(value):
    raise CommandError("protocol_error")


def parse(raw):
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise CommandError("protocol_error") from None


def read_bootstrap(raw):
    require(type(raw) is bytes and len(raw) <= BOOTSTRAP_LIMIT, "protocol_error")
    value = parse(raw)
    require(
        type(value) is dict and set(value) == {"version", "argv", "cwd", "capture"},
        "protocol_error",
    )
    require(type(value["version"]) is int and value["version"] == 1, "protocol_error")
    argv = value["argv"]
    require(type(argv) is list and 1 <= len(argv) <= 129, "protocol_error")
    try:
        checked = bootstrap(Path(argv[0]), tuple(argv[1:]), Path(value["cwd"]), value["capture"])
        require(len(checked) <= BOOTSTRAP_LIMIT, "protocol_error")
    except (CommandError, TypeError, ValueError):
        raise CommandError("protocol_error") from None
    return value


class StatusReader:
    def __init__(self):
        self.buffer = bytearray()
        self.total = 0
        self.started = False
        self.result = None

    def feed(self, data):
        self.total += len(data)
        require(self.total <= STATUS_LIMIT, "protocol_error")
        self.buffer.extend(data)
        while b"\n" in self.buffer:
            raw, _, remainder = self.buffer.partition(b"\n")
            self.buffer = bytearray(remainder)
            value = parse(bytes(raw))
            if value == {"event": "started"} and not self.started and self.result is None:
                self.started = True
                continue
            require(type(value) is dict and self.result is None, "protocol_error")
            require(
                set(value) == {"event", "returncode", "error_code", "stdout", "uncertain"},
                "protocol_error",
            )
            require(
                value["event"] == "finished" and type(value["uncertain"]) is bool, "protocol_error"
            )
            code, error = value["returncode"], value["error_code"]
            require(
                (type(code) is int and -255 <= code <= 255)
                or (code is None and value["uncertain"]),
                "protocol_error",
            )
            require(
                error is None
                or (
                    type(error) is str
                    and error
                    in ("output_limit", "process_unavailable", "cleanup_unknown", "protocol_error")
                ),
                "protocol_error",
            )
            require(self.started or (value["uncertain"] and code is None), "protocol_error")
            output = value["stdout"]
            require(type(output) is str and len(output) <= 87384, "protocol_error")
            try:
                decoded = base64.b64decode(output, validate=True)
            except (ValueError, TypeError):
                raise CommandError("protocol_error") from None
            require(len(decoded) <= OUTPUT_LIMIT, "protocol_error")
            require(base64.b64encode(decoded).decode("ascii") == output, "protocol_error")
            require(error != "output_limit" or not decoded, "protocol_error")
            self.result = code, decoded, error, value["uncertain"]

    def finish(self, *, cancelled):
        require(not self.buffer, "protocol_error")
        require(self.result is not None or (cancelled and not self.started), "protocol_error")
