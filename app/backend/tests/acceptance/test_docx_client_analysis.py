"""Saved-version analysis coordination runs the actual ECMAScript modules."""

import subprocess

import pytest
from test_docx_client_transport import ROOT, node


@pytest.mark.parametrize(
    "case",
    [
        "save",
        "save_retry",
        "admission_retry",
        "double",
        "foreign",
        "stop",
        "dispose",
        "old_retry",
        "transport",
        "source_mismatch",
        "poll_retry",
        "callback_timer",
        "late_stop",
    ],
)
def test_analysis_client(case):
    run = subprocess.run(
        [node(), str(ROOT / "tests/acceptance/docx_client_analysis_cases.mjs"), str(ROOT), case],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == "ok " + case + "\n"


def test_real_fetch_saved_word_analysis_replay_stop_and_old_retry(tmp_path):
    import json
    import sys

    if sys.platform != "darwin":
        pytest.skip("owned macOS composition")
    from test_desktop_composition import activate, running
    from test_desktop_server import http_for
    from test_desktop_structured_review import imported
    from test_desktop_word_review import word_config
    from test_docx_editor_http import opened, root
    from test_docx_visible_word import parts, source

    cfg = word_config(tmp_path)
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        activate(http)
        for case in ("plain", "merged_table"):
            raw = source(case)
            item = imported(http, raw)
            view, _ = opened(http, item)
            connection = desktop.connection()
            job = dict(
                root=str(ROOT),
                origin=connection.origin,
                token=connection.session_token.hex(),
                view=view,
            )
            run = subprocess.run(
                [node(), str(ROOT / "tests/acceptance/docx_client_analysis_owned.mjs")],
                cwd=ROOT,
                input=json.dumps(job),
                capture_output=True,
                text=True,
                timeout=180,
            )
            assert job["token"] not in run.stdout + run.stderr, "child exposed capability"
            assert run.returncode == 0, run.stderr
            value = json.loads(run.stdout)
            result = http.get(root(item) + "/analysis-runs/" + value["first"]["run_id"] + "/result")
            assert result.status_code == 200
            assert result.json()["result"]["findings"][0]["primary"]["quote"].startswith(
                "Проверка клиента 🧪 "
            )
            before, after = parts(raw), parts(http.get(root(item) + "/content").content)
            assert before.keys() == after.keys()
            assert all(before[k] == after[k] for k in before if k != "word/document.xml")
