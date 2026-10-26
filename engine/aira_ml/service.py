"""HTTP-сервис для backend Никиты: заменяет fixture.

    .venv/bin/uvicorn aira_ml.service:app --port 8090
"""
from __future__ import annotations

import os
from functools import lru_cache

from fastapi import FastAPI, HTTPException

from .analyze import Analyzer
from .schema import AnalyzeRequest, AnalyzeResponse

app = FastAPI(title="AIRA ML", version="0.1.0")


@lru_cache(maxsize=1)
def analyzer():
    return Analyzer(selector=os.getenv("AIRA_SELECTOR", "structured"))


@app.get("/health")
def health():
    return {"status": "ok", "model_version": analyzer().model_version}


@app.post("/v1/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest):
    try:
        return analyzer().analyze(req)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
