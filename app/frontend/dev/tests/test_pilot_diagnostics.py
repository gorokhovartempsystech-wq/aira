import asyncio
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("aira_host", Path(__file__).parents[2] / "aira_host.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


def test_operation_result_logs_duration_without_document_body(monkeypatch):
    lines = []
    monkeypatch.setattr(host, "diag", lines.append)

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"text":"secret requirement"}'})

    async def ignore(*args):
        pass

    async def run():
        middleware = host.DiagnosticLog(app)
        await middleware({"type": "http", "method": "POST", "path": "/docx-documents/id/save"}, ignore, ignore)
        await middleware({"type": "http", "method": "POST", "path": "/docx-documents/id/working-content"}, ignore, ignore)

    asyncio.run(run())
    assert len(lines) == 1
    assert "POST /docx-documents/id/save -> 200" in lines[0]
    assert "duration_ms=" in lines[0]
    assert "secret" not in lines[0]
