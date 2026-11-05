"""Synthetic firmware/native allocation tests; real identity never printed."""

import ctypes
import importlib
import re
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest
from test_licensing_client_store import api, reject

SYNTHETIC_UUID = UUID("00112233-4455-6677-8899-aabbccddeeff")


def firmware(*, value=SYNTHETIC_UUID, version=(3, 1), duplicate=False, end=True):
    item = b"\x01\x1b\x01\x00" + b"\x00" * 4 + value.bytes_le + b"\x00" * 3 + b"\x00\x00"
    body = item + (item if duplicate else b"") + (b"\x7f\x04\xff\xff\x00\x00" if end else b"")
    return bytes((0, *version, 0)) + len(body).to_bytes(4, "little") + body


def test_smbios_little_endian_uuid_and_end_marker():
    assert api().parse_smbios_uuid(firmware()) == str(SYNTHETIC_UUID)
    data = firmware() + b"padding after end"
    data = data[:4] + (len(data) - 8).to_bytes(4, "little") + data[8:]
    assert api().parse_smbios_uuid(data) == str(SYNTHETIC_UUID)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"x" * (1024 * 1024 + 1),
        firmware(version=(2, 5)),
        firmware(value=UUID(int=0)),
        firmware(value=UUID(int=2**128 - 1)),
        firmware(duplicate=True),
        firmware(end=False),
        firmware()[:-1],
        firmware()[:9] + b"\x03" + firmware()[10:],
        firmware()[:4] + b"\xff" * 4 + firmware()[8:],
    ],
)
def test_invalid_smbios_is_not_identity(data):
    reject("device_unavailable", lambda: api().parse_smbios_uuid(data))


def test_all_firmware_truncations_fail():
    data = firmware()
    for i in range(len(data)):
        reject("device_unavailable", lambda: api().parse_smbios_uuid(data[:i]))


class Function:
    def __init__(self, run):
        self.run = run

    def __call__(self, *args):
        return self.run(*args)


@pytest.mark.parametrize("failure", [None, "matching", "service", "key", "value", "type", "text"])
def test_macos_allocations_are_released(monkeypatch, failure):
    m = importlib.import_module("ara.licensing.client._identity")
    released, consumed = [], []
    io, cf = type("Library", (), {})(), type("Library", (), {})()
    io.IOServiceMatching = Function(lambda _: 0 if failure == "matching" else 11)

    def service(port, matching):
        assert port == 0 and matching == 11
        consumed.append(matching)
        return 0 if failure == "service" else 12

    io.IOServiceGetMatchingService = Function(service)
    io.IOObjectRelease = Function(lambda obj: released.append(obj) or 0)
    io.IORegistryEntryCreateCFProperty = Function(lambda *_: 0 if failure == "value" else 14)
    cf.CFStringCreateWithCString = Function(lambda *_: 0 if failure == "key" else 13)
    cf.CFGetTypeID = Function(lambda _: 2 if failure == "type" else 1)
    cf.CFStringGetTypeID = Function(lambda: 1)
    cf.CFRelease = Function(lambda obj: released.append(obj))

    def string(value, buffer, size, encoding):
        assert value == 14 and size == 64 and encoding == 0x08000100
        ctypes.memmove(buffer, str(SYNTHETIC_UUID).upper().encode() + b"\0", 37)
        return 0 if failure == "text" else 1

    cf.CFStringGetCString = Function(string)
    monkeypatch.setattr(ctypes, "CDLL", lambda path: io if "IOKit" in path else cf)
    if failure:
        reject("device_unavailable", m._mac_uuid)
    else:
        assert m._mac_uuid() == str(SYNTHETIC_UUID)
    assert consumed == ([] if failure == "matching" else [11])
    expected = [] if failure in {"matching", "service"} else [12]
    if failure not in {"matching", "service", "key"}:
        expected += [13]
    if failure not in {"matching", "service", "key", "value"}:
        expected += [14]
    assert sorted(released) == sorted(expected)


def test_windows_firmware_query_size_and_abi(monkeypatch):
    m = importlib.import_module("ara.licensing.client._identity")
    data, calls = firmware(), []

    def read(provider, table, buffer, size):
        assert provider == int.from_bytes(b"RSMB", "big") and table == 0
        calls.append(size)
        if buffer is not None:
            ctypes.memmove(buffer, data, len(data))
        return len(data)

    lib = type("Library", (), {"GetSystemFirmwareTable": Function(read)})()
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: lib, raising=False)
    assert m._windows_uuid() == str(SYNTHETIC_UUID)
    assert calls == [0, len(data)]


@pytest.mark.skipif(sys.platform not in {"darwin", "win32"}, reason="Native supported OS only")
def test_native_identity_stable_no_raw_uuid_output():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from ara.licensing.client import read_device_id; "
            "a=read_device_id(); b=read_device_id(); "
            "assert a==b and a.startswith('dv1-') and len(a)==68; print('native-ok')",
        ],
        cwd=Path(__file__).resolve().parents[2] / "src",
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0
    assert result.stdout == b"native-ok\n" and result.stderr == b""


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native identity release gate")
def test_windows_native_identity():
    assert re.fullmatch(r"dv1-[a-f0-9]{64}", api().read_device_id())
