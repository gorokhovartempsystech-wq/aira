"""Ambiguous top launch and closed metadata never release a live runtime claim."""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native desktop binding")


@pytest.mark.parametrize("failure", ["constructor", "before_start", "after_start"])
def test_unknown_top_thread_start_quarantines_without_native_io(tmp_path, failure):
    script = r"""
import threading
from pathlib import Path
from test_desktop_composition import api, config
cfg = config(Path(__import__('sys').argv[1]))
first = api().FixtureDesktop(cfg)
original = threading.Thread.start
failure = __import__('sys').argv[2]
def broken(thread):
    if failure == 'after_start':
        original(thread)
    raise OSError('SYNTHETIC_PRIVATE')
def construct(*args, **kwargs):
    raise OSError('SYNTHETIC_PRIVATE')
if failure == 'constructor':
    threading.Thread = construct
else:
    threading.Thread.start = broken
first.start()
assert first.view().phase == 'failed'
assert first.view().error_code == 'cleanup_unknown'
assert first.view().resources_pending
assert not first.shutdown(0.05)
assert first.connection() is None and not cfg.home.exists()
second = api().FixtureDesktop(cfg)
try:
    second.start()
except api().DesktopError as exc:
    assert exc.code == 'desktop_busy'
else:
    raise AssertionError('Lost ambiguous top runtime claim')
"""
    response = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path.resolve()), failure],
        env={"PYTHONPATH": str(Path.cwd() / "src") + ":" + str(Path.cwd() / "tests/acceptance")},
        capture_output=True,
        timeout=10,
    )
    assert response.returncode == 0, response.stderr.decode()
