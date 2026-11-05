"""User-authorized E2 writer attribute rights; unchanged old acceptance stays required."""

import ctypes as c
import importlib
import sys

import pytest


def part(name):
    return importlib.import_module("ara.docx_analysis_worker.windows." + name)


@pytest.mark.parametrize("synchronous", [False, True])
def test_writer_can_query_attributes_without_reading_payload(synchronous):
    calls = []

    class Kernel:
        def CreateFileW(self, *args):
            calls.append(args)
            return 99

    io = object.__new__(part("_io_abi").IO)
    io.kernel = Kernel()
    handle = io.client(r"\\.\pipe\synthetic", synchronous)
    name, access, share, security, disposition, flags, template = calls[0]
    assert handle.value == 99 and name == r"\\.\pipe\synthetic"
    assert access == 0x40000080
    assert access & 1 == 0  # FILE_READ_DATA never requested.
    assert (share, security, disposition, template) == (0, None, 3, None)
    assert flags == (0 if synchronous else 0x40000000)


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows pipe attribute rights pending")
@pytest.mark.parametrize("synchronous", [False, True])
def test_native_pipe_info_on_both_ends_and_duplicate(synchronous):
    api = part("_process_abi").ProcessAPI()
    clock = part("_clock").WindowsClock()
    pair = part("_pipes").create_pipe_pair(
        deadline_ns=clock.now_ns() + 2_000_000_000, clock=clock, synchronous_writer=synchronous
    )
    duplicate = api.duplicate_rights(pair.writer.handle())
    try:
        for handle, expected in [
            (pair.reader.handle(), 1),
            (pair.writer.handle(), 0),
            (duplicate.value, 0),
        ]:
            flags = c.c_uint32()
            api.require(api.kernel.GetNamedPipeInfo(handle, c.byref(flags), None, None, None))
            assert flags.value == expected
    finally:
        duplicate.close()
        assert pair.close()
