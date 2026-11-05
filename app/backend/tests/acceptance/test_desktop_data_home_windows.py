"""Windows ABI/ownership fixtures on Mac; native NTFS release remains separate."""

import ctypes as c
from contextlib import contextmanager
from pathlib import PureWindowsPath
from types import SimpleNamespace
from uuid import UUID

import pytest

from ara.desktop.data_home import HomeError
from ara.desktop.data_home import _windows as windows
from ara.docx_analysis_worker.windows._paths import FileInfo
from ara.docx_analysis_worker.windows._security import Security

SID = "S-1-5-21-123"
ROOT = PureWindowsPath("C:/Users/Example/AIRA")


class Function:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


@pytest.mark.parametrize("failure", [False, True])
def test_known_folder_uses_current_user_guid_and_frees_allocation(monkeypatch, failure):
    buffer = c.create_unicode_buffer("C:\\Users\\Example\\AppData\\Local")
    freed = []

    def get(identifier, flags, token, result):
        assert c.string_at(identifier, 16) == UUID("f1b32785-6fba-4fcf-9d55-7b8e7f157091").bytes_le
        assert flags == 0 and token is None
        c.cast(result, c.POINTER(c.c_void_p)).contents.value = c.addressof(buffer)
        return -1 if failure else 0

    shell = SimpleNamespace(SHGetKnownFolderPath=Function(get))
    ole = SimpleNamespace(CoTaskMemFree=Function(lambda pointer: freed.append(pointer)))

    def library(name):
        return {"shell32.dll": shell, "ole32.dll": ole}[name]

    monkeypatch.setattr(windows, "library", library)
    if failure:
        with pytest.raises(HomeError) as caught:
            windows.known_folder()
        assert caught.value.code == "home_unavailable"
    else:
        assert windows.known_folder() == buffer.value
    assert freed == [c.addressof(buffer)]
    assert c.sizeof(windows.GUID) == 16


class Native:
    def __init__(self):
        self.files = {}
        self.handles = {}
        self.calls = []
        self.next_handle = 100
        self.error = 0
        self.reads = 0
        self.attributes = 0
        self.descriptors = []
        self.kernel = SimpleNamespace(
            **{
                name: Function(callback)
                for name, callback in {
                    "CreateDirectoryW": self.directory,
                    "CreateFileW": self.create,
                    "ReadFile": self.read,
                    "WriteFile": self.write,
                    "FlushFileBuffers": self.flush,
                    "MoveFileExW": self.move,
                    "DeleteFileW": self.delete,
                }.items()
            }
        )

    def directory(self, path, sa):
        assert sa._obj.bInheritHandle == 0 and sa._obj.lpSecurityDescriptor
        self.calls.append(("directory", path))
        return 1

    def create(self, path, access, share, sa, disposition, flags, template):
        self.calls.append(("create", path, access, share, disposition, flags))
        if disposition == 1:
            assert sa._obj.bInheritHandle == 0 and sa._obj.lpSecurityDescriptor
            if path in self.files:
                self.error = 80
                return 2**64 - 1
            self.files[path] = bytearray()
        elif path not in self.files:
            self.error = 2
            return 2**64 - 1
        self.next_handle += 1
        self.handles[self.next_handle] = [path, 0]
        return self.next_handle

    def read(self, handle, buffer, size, count, overlapped):
        assert overlapped is None and size <= 1025
        self.reads += 1
        path, offset = self.handles[handle]
        value = bytes(self.files[path][offset : offset + size])
        c.memmove(buffer, value, len(value))
        count._obj.value = len(value)
        self.handles[handle][1] += len(value)
        return 1

    def write(self, handle, buffer, size, count, overlapped):
        assert overlapped is None
        path, offset = self.handles[handle]
        self.files[path][offset : offset + size] = c.string_at(buffer, size)
        self.handles[handle][1] += size
        count._obj.value = size
        return 1

    def flush(self, handle):
        assert handle in self.handles
        self.calls.append(("flush", self.handles[handle][0]))
        return 1

    def move(self, source, target, flags):
        assert not self.handles
        self.calls.append(("move", source, target, flags))
        if target in self.files:
            self.error = 183
            return 0
        self.files[target] = self.files.pop(source)
        return 1

    def delete(self, path):
        del self.files[path]
        return 1

    def close(self, handle):
        del self.handles[handle]

    def inspect(self, handle):
        path, _ = self.handles[handle.value]
        acl = Security(
            SID, True, tuple((0, 0, 0x1F01FF, sid) for sid in (SID, "S-1-5-18", "S-1-5-32-544"))
        )
        return FileInfo((7, b"a" * 16), self.attributes, len(self.files[path]), 1, False, path, acl)


@pytest.fixture
def filesystem(monkeypatch):
    native = Native()
    fs = windows.Filesystem(ROOT)
    fs.fs = SimpleNamespace(
        native=native, inspect=native.inspect, same_name=lambda a, b: a.lower() == b.lower()
    )
    fs.sid, fs.key = SID, (7, b"r" * 16)
    monkeypatch.setattr(fs, "recheck", lambda: None)
    monkeypatch.setattr(windows.c, "get_last_error", lambda: native.error, raising=False)

    @contextmanager
    def private(native_arg, sid, directory=False):
        assert native_arg is native and sid == SID
        native.descriptors.append(directory)
        yield windows.SECURITY_ATTRIBUTES(c.sizeof(windows.SECURITY_ATTRIBUTES), 123, False)

    monkeypatch.setattr(windows, "descriptor", private)
    fs.bind()
    return fs, native


def test_windows_private_new_file_and_exclusive_write_through_publication(filesystem):
    fs, native = filesystem
    raw = b'{"schema_version":"aira-data-home/1","installation_id":"synthetic"}'
    fs._mkdir(str(ROOT))
    fs.write_pending(raw)
    assert fs.read(".identity.pending") == raw
    fs.publish_pending(raw)
    assert fs.read("identity.json") == raw
    assert str(ROOT / ".identity.pending") not in native.files
    assert not native.handles
    created = next(c for c in native.calls if c[0] == "create" and c[4] == 1)
    assert created[2:] == (0xC0020080, 0, 1, 0x80200000)
    assert next(c for c in native.calls if c[0] == "move")[3] == 8
    assert native.descriptors == [True, False]
    assert len([c for c in native.calls if c[0] == "flush"]) >= 3


def test_windows_existing_final_is_never_replaced(filesystem):
    fs, native = filesystem
    fs.write_pending(b"candidate")
    native.files[str(ROOT / "identity.json")] = bytearray(b"preserve")
    with pytest.raises(HomeError) as caught:
        fs.publish_pending(b"candidate")
    assert caught.value.code == "home_unavailable"
    assert bytes(native.files[str(ROOT / "identity.json")]) == b"preserve"
    assert bytes(native.files[str(ROOT / ".identity.pending")]) == b"candidate"
    assert not native.handles


def test_windows_reparse_file_not_read_and_handle_closed(filesystem):
    fs, native = filesystem
    native.files[str(ROOT / "identity.json")] = bytearray(b"not-read")
    native.attributes = 0x400
    with pytest.raises(HomeError) as caught:
        fs.read("identity.json")
    assert caught.value.code == "home_recovery_required"
    assert native.reads == 0 and not native.handles


def test_windows_owner_inspection_uses_metadata_only_shared_handle(filesystem):
    fs, native = filesystem
    native.files[str(ROOT / "runtime.owner")] = bytearray()
    fs.inspect_owner()
    call = next(c for c in native.calls if c[0] == "create")
    assert call[2:] == (0x20080, 7, 3, 0x200000)
    assert native.reads == 0 and not native.handles


def test_native_windows_home_lifetime(tmp_path):
    import sys

    if sys.platform != "win32":
        pytest.skip("Native Windows NTFS data-home release gate")
    from ara.desktop.data_home import open_home

    root = tmp_path / "native-home"
    first = open_home(root)
    try:
        identity = first.identity()
        with pytest.raises(HomeError) as caught:
            open_home(root)
        assert caught.value.code == "home_busy"
    finally:
        assert first.close()
    second = open_home(root)
    try:
        assert second.identity() == identity
    finally:
        assert second.close()
