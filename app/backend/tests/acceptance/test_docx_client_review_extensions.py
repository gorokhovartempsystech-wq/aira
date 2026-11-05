import subprocess

from test_docx_client_transport import ROOT, node


def test_review_extension_protocol():
    result = subprocess.run(
        [node(), str(ROOT / "tests/acceptance/docx_client_review_extensions.mjs"), str(ROOT)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok extensions\n"
