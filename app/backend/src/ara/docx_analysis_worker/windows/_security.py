"""Bounded binary SID/ACL decoding and explicit canonical private descriptors."""

import ctypes as c
from contextlib import contextmanager
from dataclasses import dataclass

from ._abi import HANDLE, SECURITY_ATTRIBUTES
from ._errors import WindowsRuntimeError


@dataclass(frozen=True, slots=True)
class Security:
    owner: str
    protected: bool
    aces: tuple


def sid_at(data, offset, end=None):
    end = len(data) if end is None else end
    if not 0 <= offset <= end - 8 or data[offset] != 1:
        raise WindowsRuntimeError("runtime_unavailable")
    count = data[offset + 1]
    if count > 15 or offset + 8 + count * 4 > end:
        raise WindowsRuntimeError("runtime_unavailable")
    authority = int.from_bytes(data[offset + 2 : offset + 8], "big")
    parts = [
        int.from_bytes(data[n : n + 4], "little")
        for n in range(offset + 8, offset + 8 + count * 4, 4)
    ]
    return "S-1-" + "-".join(str(v) for v in [authority, *parts])


def decode_security(data):
    if type(data) is not bytes or not 20 <= len(data) <= 65536 or data[0] != 1:
        raise WindowsRuntimeError("runtime_unavailable")
    control = int.from_bytes(data[2:4], "little")
    owner_offset = int.from_bytes(data[4:8], "little")
    acl_offset = int.from_bytes(data[16:20], "little")
    if not control & 0x8000 or not control & 4 or owner_offset < 20 or acl_offset < 20:
        raise WindowsRuntimeError("runtime_unavailable")
    owner = sid_at(data, owner_offset)
    if acl_offset + 8 > len(data):
        raise WindowsRuntimeError("runtime_unavailable")
    acl = data[acl_offset:]
    length, count = int.from_bytes(acl[2:4], "little"), int.from_bytes(acl[4:6], "little")
    if acl[0] not in (2, 4) or not 8 <= length <= len(acl) or count > 2048:
        raise WindowsRuntimeError("runtime_unavailable")
    pos, aces = 8, []
    for _ in range(count):
        if pos + 4 > length:
            raise WindowsRuntimeError("runtime_unavailable")
        kind, flags = acl[pos : pos + 2]
        size = int.from_bytes(acl[pos + 2 : pos + 4], "little")
        if size < 4 or pos + size > length:
            raise WindowsRuntimeError("runtime_unavailable")
        if kind == 0:
            if size < 16:
                raise WindowsRuntimeError("runtime_unavailable")
            sid = sid_at(acl, pos + 8, pos + size)
            sid_size = 8 + 4 * acl[pos + 9]
            if size != 8 + sid_size:
                raise WindowsRuntimeError("runtime_unavailable")
            aces.append((kind, flags, int.from_bytes(acl[pos + 4 : pos + 8], "little"), sid))
        else:
            aces.append((kind, flags, 0, ""))
        pos += size
    return Security(owner, bool(control & 0x1000), tuple(aces))


def require_private(security, sid, directory):
    expected = {(0, 3 if directory else 0, 0x1F01FF, s) for s in (sid, "S-1-5-18", "S-1-5-32-544")}
    if (
        type(security) is not Security
        or security.owner != sid
        or not security.protected
        or len(security.aces) != 3
        or set(security.aces) != expected
    ):
        raise WindowsRuntimeError("runtime_unavailable")


def read_security(native, value):
    descriptor = HANDLE()
    try:
        result = native.security.GetSecurityInfo(
            value, 1, 5, None, None, None, None, c.byref(descriptor)
        )
        if result or not descriptor.value:
            raise WindowsRuntimeError("runtime_unavailable")
        length = native.security.GetSecurityDescriptorLength(descriptor)
        if not 20 <= length <= 65536:
            raise WindowsRuntimeError("runtime_unavailable")
        return decode_security(c.string_at(descriptor, length))
    finally:
        if descriptor.value:
            native.free(descriptor.value)


@contextmanager
def descriptor(native, sid, directory=False):
    if not sid.startswith("S-1-") or any(ch not in "S-0123456789" for ch in sid):
        raise WindowsRuntimeError("runtime_unavailable")
    flags = "OICI" if directory else ""
    text = f"O:{sid}D:P(A;{flags};FA;;;{sid})(A;{flags};FA;;;SY)(A;{flags};FA;;;BA)"
    result = HANDLE()
    try:
        if not native.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            text, 1, c.byref(result), None
        ):
            raise WindowsRuntimeError("runtime_unavailable")
        if not result.value:
            raise WindowsRuntimeError("runtime_unavailable")
        yield SECURITY_ATTRIBUTES(c.sizeof(SECURITY_ATTRIBUTES), result.value, False)
    finally:
        if result.value:
            native.free(result.value)
