"""Real filesystem persistence and shell save state; synthetic bytes only."""

import subprocess

import pytest
from test_docx_client_transport import ROOT, node


@pytest.mark.parametrize(
    "case",
    [
        "roundtrip",
        "changed",
        "missing",
        "exists",
        "symlink",
        "hardlink",
        "invalid",
        "write_fault",
        "sync_fault",
        "rename_fault",
        "late_change",
        "uncertain",
        "cancel",
        "retry",
        "concurrent",
        "revision",
    ],
)
def test_native_docx_file(case):
    result = subprocess.run(
        [node(), str(ROOT / "tests/acceptance/native_docx_file_cases.mjs"), str(ROOT), case],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok " + case + "\n"
