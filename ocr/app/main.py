"""The OCR container's HTTP face. No database, no tenant, no secret: an image in, cells out.

One photo is read at a time -- the server has 4 CPUs and the ERP beside it -- so
requests queue on a lock rather than running side by side.
"""
from __future__ import annotations

import threading

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.engine import Engine
from app.pipeline import TEMPLATES, read

app = FastAPI(title="Sonalim OCR")
_lock = threading.Lock()
_engine: Engine | None = None


def _read(data: bytes, form_hint: str | None) -> dict:
    global _engine
    with _lock:
        if _engine is None:
            _engine = Engine()
        return read(_engine, TEMPLATES, data, form_hint)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/read")
async def read_photo(request: Request, form_hint: str | None = None) -> dict:
    data = await request.body()
    if not data:
        raise HTTPException(400, "empty body")
    return await run_in_threadpool(_read, data, form_hint)
