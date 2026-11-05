"""Independent activation identity storage tests; only synthetic public state."""

import importlib
import json
import os
import stat
from pathlib import Path
from uuid import uuid4

import pytest
from test_licensing_policy import DEVICE, OTHER


def api():
    return importlib.import_module("ara.licensing.client")


def reject(code, call):
    with pytest.raises(api().ClientError) as caught:
        call()
    assert caught.value.code == code
    assert "SYNTHETIC_PRIVATE" not in str(caught.value)
    assert "SYNTHETIC_PRIVATE" not in repr(caught.value)


def identity():
    return api().ActivationIdentity(uuid4(), DEVICE)


def test_missing_store_and_factory_are_inert(tmp_path):
    root = tmp_path / "new"
    store = api().ActivationStore(root)
    assert not root.exists()
    assert store.load() is None
    assert not root.exists()


def test_save_reopen_exact_public_state_and_private_mode(tmp_path):
    root = tmp_path / "new"
    first = identity()
    api().ActivationStore(root).save(first)
    assert api().ActivationStore(root).load() == first
    file = root / "license-activation.json"
    assert json.loads(file.read_bytes()) == {
        "schema_version": "aira-license-activation/1",
        "license_id": str(first.license_id),
        "device_id": DEVICE,
    }
    if os.name == "posix":
        assert stat.S_IMODE(file.stat().st_mode) == 0o600
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
    second = api().ActivationIdentity(uuid4(), OTHER)
    api().ActivationStore(root).save(second)
    assert api().ActivationStore(root).load() == second
    assert sorted(p.name for p in root.iterdir()) == [file.name]


@pytest.mark.parametrize("path", [Path("relative"), Path("/a/../b"), "SYNTHETIC_PRIVATE"])
def test_invalid_root(path):
    reject("validation_error", lambda: api().ActivationStore(path))


@pytest.mark.parametrize(
    "data",
    [b"", b"{}", b"null", b"[]", b"\xff", b"x" * 1025, b'{"x":1,"x":2}'],
)
def test_corrupt_state_not_reset_but_explicit_save_can_replace(tmp_path, data):
    store = api().ActivationStore(tmp_path)
    file = tmp_path / "license-activation.json"
    file.write_bytes(data)
    reject("activation_store_error", store.load)
    assert file.read_bytes() == data
    value = identity()
    store.save(value)
    assert store.load() == value


def test_json_duplicate_unknown_and_wrong_types_rejected(tmp_path):
    store = api().ActivationStore(tmp_path)
    store.save(identity())
    file = tmp_path / "license-activation.json"
    baseline = file.read_bytes()
    for mutation in (
        baseline[:-1] + b',"device_id":"' + DEVICE.encode() + b'"}',
        baseline[:-1] + b',"offline":true}',
        baseline.replace(DEVICE.encode(), b"not-a-device"),
        baseline.replace(b'"aira-license-activation/1"', b"true"),
    ):
        file.write_bytes(mutation)
        reject("activation_store_error", store.load)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "fifo"])
def test_unsafe_file_is_not_read_or_overwritten(tmp_path, kind):
    if kind == "fifo" and os.name != "posix":
        pytest.skip("POSIX FIFO boundary")
    other = tmp_path / "outside"
    other.write_bytes(b"preserved")
    root = tmp_path / "root"
    root.mkdir()
    file = root / "license-activation.json"
    if kind == "symlink":
        file.symlink_to(other)
    elif kind == "hardlink":
        os.link(other, file)
    elif kind == "directory":
        file.mkdir()
    else:
        os.mkfifo(file)
    store = api().ActivationStore(root)
    reject("activation_store_error", store.load)
    reject("activation_store_error", lambda: store.save(identity()))
    assert other.read_bytes() == b"preserved"


def test_linked_root_rejected(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    root = tmp_path / "root"
    root.symlink_to(target, target_is_directory=True)
    store = api().ActivationStore(root)
    reject("activation_store_error", store.load)
    reject("activation_store_error", lambda: store.save(identity()))
    assert list(target.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner/mode checks")
def test_writable_by_others_root_rejected(tmp_path):
    tmp_path.chmod(0o777)
    store = api().ActivationStore(tmp_path)
    reject("activation_store_error", store.load)
    reject("activation_store_error", lambda: store.save(identity()))


@pytest.mark.parametrize("stage", ["write", "fsync", "replace", "replace_ack", "dir_fsync"])
def test_atomic_failure_preserves_old_or_whole_new_identity(tmp_path, monkeypatch, stage):
    if os.name != "posix":
        pytest.skip("POSIX fault seams; Windows native gate separate")
    store = api().ActivationStore(tmp_path)
    first, second = identity(), identity()
    store.save(first)
    old = (tmp_path / "license-activation.json").read_bytes()
    original = getattr(
        os, "replace" if stage.startswith("replace") else "fsync" if "fsync" in stage else "write"
    )

    def broken(*args, **kwargs):
        if stage == "write":
            original(args[0], args[1][:5])
        elif stage == "replace_ack":
            original(*args, **kwargs)
        elif stage == "dir_fsync" and not stat.S_ISDIR(os.fstat(args[0]).st_mode):
            return original(*args, **kwargs)
        raise OSError("SYNTHETIC_PRIVATE")

    name = "replace" if stage.startswith("replace") else "fsync" if "fsync" in stage else "write"
    with monkeypatch.context() as patch:
        patch.setattr(os, name, broken)
        reject("activation_store_error", lambda: store.save(second))
    assert store.load() == (second if stage in {"replace_ack", "dir_fsync"} else first)
    if stage not in {"replace_ack", "dir_fsync"}:
        assert (tmp_path / "license-activation.json").read_bytes() == old
    assert len(list(tmp_path.iterdir())) == 1


def test_invalid_identity_does_not_touch_disk(tmp_path):
    store = api().ActivationStore(tmp_path / "missing")
    for value in [None, object(), api().ActivationIdentity(uuid4(), "bad")]:
        reject("validation_error", lambda: store.save(value))
    assert not (tmp_path / "missing").exists()
