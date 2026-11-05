"""Private bootstrap and status channel acceptance without launching a database."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_desktop_postgres_process as base
from test_desktop_postgres_process import api, command, done

owned = base.owned

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native Darwin bootstrap")


@pytest.mark.parametrize("payload,returncode", [(b'{"version":1', 0), (b"{invalid}\n", 75)])
def test_partial_or_invalid_bootstrap_never_launches_a_command(owned, payload, returncode):
    owner, root = owned
    entry = Path(api().__file__).with_name("_guardian_entry.py")
    slot = owner.reserve_slot()
    process = subprocess.Popen(
        [sys.executable, "-I", "-B", str(entry), str(slot.fileno())],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        pass_fds=(slot.fileno(),),
        close_fds=True,
        start_new_session=True,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C", "TZ": "UTC"},
    )
    output, error = process.communicate(payload, timeout=5)
    assert process.returncode == returncode
    assert not output and not error
    assert owner.release_slot(slot)


def test_malformed_status_fails_but_still_reaps_and_releases(owned, monkeypatch):
    owner, root = owned
    entry = root / "synthetic_bad_status.py"
    entry.write_text("import os,sys\nos.write(1,b'bad status\\n')\nsys.stdin.buffer.read()\n")
    original = subprocess.Popen

    def corrupt(arguments, **kwargs):
        values = list(arguments)
        assert values[1:3] == ["-I", "-B"]
        values[3] = str(entry)
        return original(values, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", corrupt)
    job = command(owner, root)
    job.start()
    assert done(job).phase == "failed"
    assert job.view().error_code == "protocol_error"
    assert job.shutdown(0)
    slot = owner.reserve_slot()
    assert owner.release_slot(slot)


def test_constructor_does_not_open_or_spawn(owned, monkeypatch):
    owner, root = owned

    def forbidden(*args, **kwargs):
        raise AssertionError("Constructor performed I/O")

    module = api()
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    value = module.OwnedCommand(owner, Path(sys.executable), (), cwd=root)
    assert value.view().phase == "new"
    assert value.shutdown(0)
