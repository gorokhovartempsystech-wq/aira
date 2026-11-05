"""Create/import and exact saved-copy export through production client modules."""

import subprocess

import pytest
from test_docx_client_transport import ROOT, node


@pytest.mark.parametrize(
    "case",
    [
        "unsafe_revision",
        "cancel_save",
        "wrong_revision",
        "transport_copy_kind",
        "transport_revision",
        "create",
        "import_copy",
        "metadata",
        "invalid_input",
        "save_first",
        "save_retry",
        "download_retry",
        "wrong_copy",
        "cancel",
        "transport_create",
        "transport_binary",
        "transport_hash",
        "transport_media",
        "transport_limit",
        "transport_foreign",
        "transport_timeout",
        "workspace_guard",
    ],
)
def test_docx_file_clients(case):
    run = subprocess.run(
        [node(), str(ROOT / "tests/acceptance/docx_client_files_cases.mjs"), str(ROOT), case],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == "ok " + case + "\n"


def test_owned_create_import_edit_and_confirmed_exports(tmp_path):
    import base64
    import json
    import sys
    from xml.etree import ElementTree

    if sys.platform != "darwin":
        pytest.skip("owned macOS composition")
    from test_desktop_composition import activate, running
    from test_desktop_server import http_for
    from test_desktop_word_review import word_config
    from test_docx_visible_word import parts, source

    cfg = word_config(tmp_path)
    originals = [source(case) for case in ("plain", "merged_table")]
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        activate(http)
        connection = desktop.connection()
        job = dict(
            root=str(ROOT),
            origin=connection.origin,
            token=connection.session_token.hex(),
            sources=[base64.b64encode(raw).decode() for raw in originals],
        )
        run = subprocess.run(
            [node(), str(ROOT / "tests/acceptance/docx_client_files_owned.mjs")],
            cwd=ROOT,
            input=json.dumps(job),
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert job["token"] not in run.stdout + run.stderr, "child exposed capability"
        assert run.returncode == 0, run.stderr
        exports = json.loads(run.stdout)
        assert len(exports) == 3
        for i, item in enumerate(exports):
            raw = base64.b64decode(item["data"])
            after = parts(raw)
            text = "".join(ElementTree.fromstring(after["word/document.xml"]).itertext())
            assert text.count("Экспорт 🧪 ") == 1
            assert item["filename"] == item["document_id"] + ".docx"
            assert http.get("/docx-documents/" + item["document_id"] + "/content").content == raw
            if i:
                before = parts(originals[i - 1])
                assert before.keys() == after.keys()
                assert all(before[k] == after[k] for k in before if k != "word/document.xml")
