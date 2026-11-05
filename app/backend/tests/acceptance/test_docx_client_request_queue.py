"""Shared host lane serializes multiple actor clients without swallowing failures."""

import subprocess

import pytest
from test_docx_client_transport import ROOT, node


@pytest.mark.parametrize("case", ["fifo", "failure", "bound"])
def test_host_request_queue(case):
    run = subprocess.run(
        [
            node(),
            str(ROOT / "tests/acceptance/docx_client_request_queue_cases.mjs"),
            str(ROOT),
            case,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == "ok " + case + "\n"
