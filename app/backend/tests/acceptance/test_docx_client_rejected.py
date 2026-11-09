"""D03-20A: confirmed refusal releases document ownership; uncertain work does not."""

import subprocess

import pytest
from test_docx_client_transport import ROOT, node


@pytest.mark.parametrize(
    "case", ["rejected", "workspace", "uncertain", "bound_run", "late_poll", "late_poll_error"]
)
def test_rejected_analysis_client(case):
    result = subprocess.run(
        [node(), str(ROOT / "tests/acceptance/docx_client_rejected_cases.mjs"), str(ROOT), case],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok " + case + "\n"
