"""One production-client workflow through two owned licensed host lifetimes."""

import base64
import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree

import pytest
from test_docx_client_transport import ROOT, node


def test_complete_docx_workflow(tmp_path):
    script = ROOT / "tests/acceptance/docx_client_workflow_owned.mjs"
    assert script.is_file(), "whole-workflow Node driver is missing"
    if sys.platform != "darwin":
        pytest.skip("owned macOS workflow; Windows-native gate remains open")
    from test_desktop_composition import activate, license_phase, running
    from test_desktop_server import http_for
    from test_desktop_word_review import word_config
    from test_docx_visible_word import parts, source

    cfg = word_config(tmp_path)
    originals = [source(case) for case in ("plain", "merged_table")]

    def invoke(connection, mode, state=None):
        job = dict(
            root=str(ROOT),
            origin=connection.origin,
            token=connection.session_token.hex(),
            mode=mode,
            state=state,
            sources=[base64.b64encode(raw).decode() for raw in originals],
        )
        run = subprocess.run(
            [node(), str(script)],
            cwd=ROOT,
            input=json.dumps(job),
            capture_output=True,
            text=True,
            timeout=240,
        )
        assert job["token"] not in run.stdout + run.stderr, "child exposed capability"
        assert run.returncode == 0, run.stderr
        return json.loads(run.stdout)

    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        activate(http)
        state = invoke(desktop.connection(), "draft")
        assert len(state["documents"]) == 3 and state["fixture"]
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        license_phase(http, "active")
        result = invoke(desktop.connection(), "finish", state)
        assert result["fixture"] and result["reopened"] == 3
        assert len(result["exports"]) == 3
        for index, exported in enumerate(result["exports"]):
            data = base64.b64decode(exported["data"], validate=True)
            assert sha256(data).hexdigest() == exported["sha256"]
            after = parts(data)
            content = "".join(ElementTree.fromstring(after["word/document.xml"]).itertext())
            assert content.count("Сценарий 🧪 ") == 1
            assert content.count("Финал ") == 1
            assert content.count("Черновик ") == (1 if index == 0 else 0)
            assert (
                http.get("/docx-documents/" + exported["documentId"] + "/content").content == data
            )
            if index:
                before = parts(originals[index - 1])
                assert before.keys() == after.keys()
                assert all(before[k] == after[k] for k in before if k != "word/document.xml")
    assert [r.operation for r in cfg.transport.requests] == ["activate", "check"]
    output = os.getenv("AIRA_WORKFLOW_OUTPUT")
    if output:
        directory = Path(output).resolve()
        assert directory.is_relative_to((ROOT / ".runtime/aira-workflow-demo").resolve())
        assert directory.is_dir()
        files = []
        for name, exported in zip(("new", "plain", "table"), result["exports"], strict=True):
            filename = name + ".docx"
            (directory / filename).write_bytes(base64.b64decode(exported["data"]))
            files.append(dict(file=filename, sha256=exported["sha256"]))
        report = dict(
            status="passed",
            fixture=True,
            licence_transport="synthetic",
            native_platform="macOS",
            host_lifetimes=2,
            documents=3,
            reopened=3,
            autosave_delay_ms=120000,
            autosave_clock="advanced in test; real HTTP checkpoint",
            steps=[
                "create/import",
                "edit/undo/redo",
                "tabs/autosave",
                "save/check/hide",
                "close/restart/license-check",
                "recover/persisted-hides",
                "recheck/manual-edit",
                "confirmed-export",
                "reimport/reopen",
            ],
            files=files,
            visual_word_verified=False,
            real_model_verified=False,
        )
        (directory / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
