"""Workspace owns exact open/close intents, without silently dropping tabs."""

import subprocess

import pytest
from test_docx_client_transport import ROOT, node


@pytest.mark.parametrize(
    "case",
    [
        "open",
        "recover",
        "open_retry",
        "close_retry",
        "close_unproven",
        "checkpoint_failure",
        "busy",
        "foreign",
        "pending",
        "preview_close",
        "guard",
        "connected",
    ],
)
def test_workspace_client(case):
    run = subprocess.run(
        [node(), str(ROOT / "tests/acceptance/docx_client_workspace_cases.mjs"), str(ROOT), case],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == "ok " + case + "\n"


def test_owned_tabs_lost_open_close_restart_recovery_and_saved_review(tmp_path):
    import json
    import sys
    from xml.etree import ElementTree

    if sys.platform != "darwin":
        pytest.skip("owned macOS composition")
    from test_desktop_composition import activate, license_phase, running
    from test_desktop_server import http_for
    from test_desktop_structured_review import imported
    from test_desktop_word_review import word_config
    from test_docx_editor_http import root
    from test_docx_visible_word import parts, source

    cfg = word_config(tmp_path)
    records = []

    def invoke(connection, mode):
        job = dict(
            root=str(ROOT),
            origin=connection.origin,
            token=connection.session_token.hex(),
            mode=mode,
            documents=[str(item.document_id) for item, _ in records],
        )
        run = subprocess.run(
            [node(), str(ROOT / "tests/acceptance/docx_client_workspace_owned.mjs")],
            cwd=ROOT,
            input=json.dumps(job),
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert job["token"] not in run.stdout + run.stderr, "child exposed capability"
        assert run.returncode == 0, run.stderr
        return json.loads(run.stdout)

    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        activate(http)
        for case in ("plain", "merged_table"):
            raw = source(case)
            records.append((imported(http, raw), raw))
        invoke(desktop.connection(), "draft")
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        license_phase(http, "active")
        result = invoke(desktop.connection(), "recover")
        assert len(result["saved"]) == 2
        for i, (item, raw) in enumerate(records):
            before, after = parts(raw), parts(http.get(root(item) + "/content").content)
            assert before.keys() == after.keys()
            assert all(before[k] == after[k] for k in before if k != "word/document.xml")
            text = "".join(ElementTree.fromstring(after["word/document.xml"]).itertext())
            assert text.count("Вкладка 🧪 ") == 1
            assert text.count("Черновик ") == (1 if i == 0 else 0)
    assert [r.operation for r in cfg.transport.requests] == ["activate", "check"]
