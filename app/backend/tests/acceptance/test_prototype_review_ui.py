"""Render actual PR29 drawer logic with a small DOM fixture, not native UI."""

import subprocess
from pathlib import Path

from test_docx_client_transport import node


def test_prototype_review_counts_filters_empty_state_and_quote_navigation():
    here = Path(__file__).resolve().parent
    frontend = here.parents[2] / "frontend" / "static" / "js"
    result = subprocess.run(
        [node(), "--experimental-vm-modules", str(here / "prototype_review_ui.mjs"), str(frontend)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok prototype review UI\n"
