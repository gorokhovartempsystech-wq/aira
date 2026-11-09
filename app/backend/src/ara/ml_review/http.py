"""Loopback DOCX model jobs. One child at a time; no import-time model loading."""

import base64
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from ara.docx_documents import get_docx


class StartReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: str = Field(pattern=r"^[1-9][0-9]{0,18}$")


def install_model_review(app, runtime, models):
    models = str(Path(models).resolve(strict=True))
    if not (Path(models) / "manifest.json").is_file():
        raise ValueError("Model manifest is missing")
    lock = threading.Lock()
    jobs = {}

    def guard(request):
        from urllib.parse import urlsplit

        host = urlsplit("http://" + request.headers.get("host", "")).hostname
        origin = request.headers.get("origin")
        if host not in ("127.0.0.1", "localhost", "[::1]", "::1", "testserver"):
            raise HTTPException(403, "Local access only")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Origin mismatch")

    def execute(job, saved):
        proc = None
        try:
            args = {
                "models": models,
                "data": base64.b64encode(saved.current_data).decode(),
                "document_id": str(saved.document_id),
                "revision": saved.storage_revision,
                "seconds": 290,
            }
            with lock:
                if job["status"] == "cancelled":
                    return
                proc = subprocess.Popen(
                    [sys.executable, "-m", "ara.ml_review.child"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=os.environ.copy(),
                )
                job["process"] = proc
            out, _ = proc.communicate(json.dumps(args), timeout=300)
            result = json.loads(out)
            if proc.returncode:
                allowed = {
                    "unsupported_document",
                    "empty_document",
                    "invalid_reply",
                    "review_limit_exceeded",
                    "review_failed",
                }
                with lock:
                    if job["status"] != "cancelled":
                        code = result.get("error", "review_failed")
                        job.update(
                            status="failed", error=code if code in allowed else "review_failed"
                        )
                return
            with lock:
                if job["status"] == "cancelled":
                    return
                # Recheck access before publishing. Result always names its saved revision.
                get_docx(runtime, document_id=saved.document_id)
                with runtime.engine.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO local_model_reviews "
                            "(id,document_id,revision,source_sha256,result) "
                            "VALUES (:id,:doc,:rev,:sha,CAST(:result AS jsonb))"
                        ),
                        {
                            "id": UUID(job["id"]),
                            "doc": saved.document_id,
                            "rev": saved.storage_revision,
                            "sha": saved.current_sha256,
                            "result": json.dumps(result, ensure_ascii=False),
                        },
                    )
                job["status"] = "succeeded"
                job["result"] = result
        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
                proc.communicate()
            with lock:
                if job["status"] != "cancelled":
                    job.update(status="failed", error="timeout")
        except Exception:
            with lock:
                if job["status"] != "cancelled":
                    job.update(status="failed", error="review_failed")
        finally:
            with lock:
                job.pop("process", None)

    def shutdown():
        with lock:
            for job in jobs.values():
                if job["status"] == "running":
                    job["status"] = "cancelled"
                    if "process" in job:
                        job["process"].terminate()

    app.state.shutdown_local_model = shutdown

    @app.post("/docx-documents/{document_id}/model-reviews", status_code=202)
    def start(document_id: UUID, body: StartReview, request: Request):
        guard(request)
        saved = get_docx(runtime, document_id=document_id)
        if saved.storage_revision != int(body.expected_revision):
            raise HTTPException(409, "Document changed; reload before review")
        with lock:
            if any(j["status"] == "running" or "process" in j for j in jobs.values()):
                raise HTTPException(409, "Another model review is running")
            # Completed results are in PostgreSQL; keep only current process bookkeeping.
            jobs.clear()
            identity = str(uuid4())
            job = {
                "id": identity,
                "document_id": str(document_id),
                "revision": str(saved.storage_revision),
                "status": "running",
            }
            jobs[identity] = job
        threading.Thread(target=execute, args=(job, saved), daemon=True).start()
        return {"id": identity, "status": "running"}

    @app.get("/docx-documents/{document_id}/model-reviews/{review_id}")
    def poll(document_id: UUID, review_id: UUID, request: Request):
        guard(request)
        current = get_docx(runtime, document_id=document_id)
        with lock:
            job = jobs.get(str(review_id))
            if job and job["document_id"] == str(document_id):
                return {k: v for k, v in job.items() if k != "process"} | {
                    "outdated": job["revision"] != str(current.storage_revision)
                }
        with runtime.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT revision,result FROM local_model_reviews "
                    "WHERE id=:id AND document_id=:doc"
                ),
                {"id": review_id, "doc": document_id},
            ).first()
        if row is None:
            raise HTTPException(404, "Review not found")
        return {
            "id": str(review_id),
            "status": "succeeded",
            "revision": str(row.revision),
            "result": row.result,
            "outdated": row.revision != current.storage_revision,
        }

    @app.delete("/docx-documents/{document_id}/model-reviews/{review_id}")
    def cancel(document_id: UUID, review_id: UUID, request: Request):
        guard(request)
        get_docx(runtime, document_id=document_id)
        with lock:
            job = jobs.get(str(review_id))
            if not job or job["document_id"] != str(document_id):
                raise HTTPException(404, "Active review not found")
            if job["status"] == "running":
                job["status"] = "cancelled"
                if "process" in job:
                    job["process"].terminate()
            return {"status": job["status"]}
