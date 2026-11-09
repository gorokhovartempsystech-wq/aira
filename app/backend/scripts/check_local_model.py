"""Explicit smoke test of the running local API, using synthetic text only."""

import time
from uuid import uuid4

import httpx


def main():
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=20) as client:
        identity = str(uuid4())
        content = "Система должна быстро обрабатывать заявку клиента."

        def save(text, revision):
            r = client.post(
                "/editor/documents",
                json={
                    "document_id": identity,
                    "expected_revision": revision,
                    "title": "Сквозной тест ML",
                    "text": text,
                },
            )
            r.raise_for_status()
            return r.json()

        def start(revision):
            r = client.post(
                f"/docx-documents/{identity}/model-reviews", json={"expected_revision": revision}
            )
            r.raise_for_status()
            return r.json()["id"]

        def read(job):
            r = client.get(f"/docx-documents/{identity}/model-reviews/{job}")
            r.raise_for_status()
            return r.json()

        def wait(job):
            until = time.monotonic() + 60
            while time.monotonic() < until:
                result = read(job)
                if result["status"] != "running":
                    return result
                time.sleep(0.1)
            raise AssertionError("Model did not finish in 60 seconds")

        save(content, None)
        first = start("1")
        result = wait(first)
        assert result["status"] == "succeeded", result.get("error")
        assert result["result"]["result"]["provenance"]["execution_kind"] == "local_model"
        assert any(
            f["primary"]["quote"] == "быстро" for f in result["result"]["result"]["findings"]
        )
        save("Система должна обрабатывать заявку клиента не дольше 2 секунд.", "1")
        assert read(first)["outdated"] is True
        second = wait(start("2"))
        assert second["status"] == "succeeded"
        assert second["result"]["result"]["no_findings"] is True
        download = client.get(f"/docx-documents/{identity}/content")
        assert download.status_code == 200 and download.content.startswith(b"PK")
        job = start("2")
        stopped = client.delete(f"/docx-documents/{identity}/model-reviews/{job}")
        assert stopped.status_code == 200
        assert wait(job)["status"] == "cancelled"
        # Exercise the same import endpoint used by the file input in /editor.
        identity = str(uuid4())
        save(
            "Сумма заявки ALPHA должна составлять не более 500 рублей.\n"
            "Сумма заявки ALPHA должна составлять не менее 600 рублей.",
            None,
        )
        source = client.get(f"/docx-documents/{identity}/content")
        source.raise_for_status()
        identity = str(uuid4())
        imported = client.post(
            f"/docx-documents/{identity}/import?title=ML%20import%20smoke",
            headers={
                "Content-Type": "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            },
            content=source.content,
        )
        imported.raise_for_status()
        checked = wait(start(str(imported.json()["storage_revision"])))
        assert checked["status"] == "succeeded", checked.get("error")
        assert any(
            finding["type"] == "contradiction"
            for finding in checked["result"]["result"]["findings"]
        )
        assert client.get(f"/docx-documents/{identity}/content").content == source.content
        print(
            "PASS: real model, evidence, save/recheck, stale result, cancellation, "
            "DOCX import with contradiction and byte-identical download"
        )


if __name__ == "__main__":
    main()
