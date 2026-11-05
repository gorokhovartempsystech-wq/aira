"""Lazy native hardware UUID reads. Public output is a domain-separated digest."""

import ctypes as c
import sys
from uuid import UUID

from .. import device_fingerprint
from ._models import require, safe

_CAP = 1024 * 1024
_CODE = "device_unavailable"


def _uuid(value):
    parsed = UUID(value)
    require(parsed.int not in (0, 2**128 - 1), _CODE)
    return str(parsed)


@safe(_CODE)
def parse_smbios_uuid(data):
    require(type(data) is bytes and 8 <= len(data) <= _CAP, _CODE)
    require((data[1], data[2]) >= (2, 6), _CODE)
    require(int.from_bytes(data[4:8], "little") == len(data) - 8, _CODE)
    pos, result, ended = 8, None, False
    while pos < len(data):
        require(pos + 4 <= len(data), _CODE)
        kind, size = data[pos], data[pos + 1]
        require(size >= 4 and pos + size <= len(data), _CODE)
        end = data.find(b"\0\0", pos + size)
        require(end != -1, _CODE)
        if kind == 1:
            require(result is None and size >= 24, _CODE)
            result = _uuid(str(UUID(bytes_le=data[pos + 8 : pos + 24])))
        if kind == 127:
            ended = True
            break
        pos = end + 2
    require(ended and result is not None, _CODE)
    return result


def _signature(library, name, restype, *args):
    function = getattr(library, name)
    function.restype = restype
    function.argtypes = list(args)
    return function


@safe(_CODE)
def _windows_uuid():
    library = c.WinDLL("kernel32", use_last_error=True)
    read = _signature(
        library,
        "GetSystemFirmwareTable",
        c.c_uint32,
        c.c_uint32,
        c.c_uint32,
        c.c_void_p,
        c.c_uint32,
    )
    provider = int.from_bytes(b"RSMB", "big")
    size = read(provider, 0, None, 0)
    require(8 <= size <= _CAP, _CODE)
    buffer = c.create_string_buffer(size)
    require(read(provider, 0, buffer, size) == size, _CODE)
    return parse_smbios_uuid(buffer.raw)


@safe(_CODE)
def _mac_uuid():
    io = c.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
    cf = c.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    matching = _signature(io, "IOServiceMatching", c.c_void_p, c.c_char_p)
    get_service = _signature(io, "IOServiceGetMatchingService", c.c_uint32, c.c_uint32, c.c_void_p)
    release_service = _signature(io, "IOObjectRelease", c.c_int32, c.c_uint32)
    create_key = _signature(
        cf, "CFStringCreateWithCString", c.c_void_p, c.c_void_p, c.c_char_p, c.c_uint32
    )
    get_value = _signature(
        io,
        "IORegistryEntryCreateCFProperty",
        c.c_void_p,
        c.c_uint32,
        c.c_void_p,
        c.c_void_p,
        c.c_uint32,
    )
    type_id = _signature(cf, "CFGetTypeID", c.c_ulong, c.c_void_p)
    string_type = _signature(cf, "CFStringGetTypeID", c.c_ulong)
    get_text = _signature(
        cf, "CFStringGetCString", c.c_ubyte, c.c_void_p, c.POINTER(c.c_char), c.c_long, c.c_uint32
    )
    release_cf = _signature(cf, "CFRelease", None, c.c_void_p)
    service = key = value = None
    try:
        dictionary = matching(b"IOPlatformExpertDevice")
        require(dictionary, _CODE)
        # The native call consumes the matching dictionary even when no service exists.
        service = get_service(0, dictionary)
        require(service, _CODE)
        key = create_key(None, b"IOPlatformUUID", 0x08000100)
        require(key, _CODE)
        value = get_value(service, key, None, 0)
        require(value and type_id(value) == string_type(), _CODE)
        buffer = c.create_string_buffer(64)
        require(get_text(value, buffer, 64, 0x08000100), _CODE)
        return _uuid(buffer.value.decode("ascii"))
    finally:
        try:
            if value:
                release_cf(value)
        finally:
            try:
                if key:
                    release_cf(key)
            finally:
                if service:
                    release_service(service)


@safe(_CODE)
def read_device_id():
    require(sys.platform in {"darwin", "win32"}, _CODE)
    platform, value = (
        ("macos", _mac_uuid()) if sys.platform == "darwin" else ("windows", _windows_uuid())
    )
    return device_fingerprint(platform, value)
