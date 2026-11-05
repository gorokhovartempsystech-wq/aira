"""Bound JSON before parsing, reject duplicates, stream trusted output encoding."""

import json
from hashlib import sha256

from ara.docx_analysis.visible_main._canonical import tokens

from ._models import ReviewError, budget, require


def encode(value, maximum):
    output = bytearray()
    for token in tokens(value):
        raw = token.encode("utf-8")
        budget(len(output) + len(raw), maximum)
        output.extend(raw)
    return bytes(output)


def fingerprint(value, maximum):
    return sha256(encode(value, maximum)).hexdigest()


def duplicate_safe(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def constant(value):
    raise ReviewError("invalid_reply")


def decode(raw, limits):
    require(type(raw) is bytes, "invalid_input")
    budget(len(raw), limits.max_reply_bytes)
    try:
        decoded = raw.decode("utf-8")
        inside = escaped = False
        depth = 0
        for c in decoded:
            if inside:
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == '"':
                    inside = False
            elif c == '"':
                inside = True
            elif c in "[{":
                depth += 1
                budget(depth, limits.max_json_depth)
            elif c in "]}":
                depth -= 1
        return json.loads(decoded, object_pairs_hook=duplicate_safe, parse_constant=constant)
    except ReviewError:
        raise
    except (UnicodeError, ValueError, RecursionError, OverflowError):
        raise ReviewError("invalid_reply") from None
