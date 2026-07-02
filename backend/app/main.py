"""Point d'entrée FastAPI (API Gateway, 03 §1).

V1 = localhost only, AUCUNE auth (non-négociable e). Lancement typique :
    uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import Config
from .db import init_db
from .methods import base as methods
from .api import media, references, methods as methods_api, jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = Config.from_env()
    cfg.ensure_dirs()
    init_db(cfg.db_path)
    methods.load_builtin_methods()
    pool = ProcessPoolExecutor(max_workers=cfg.workers)
    app.state.cfg = cfg
    app.state.pool = pool
    try:
        yield
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="MediaNotFound — API", version="0.1.0", lifespan=lifespan)

app.include_router(media.router)
app.include_router(references.router)
app.include_router(methods_api.router)
app.include_router(jobs.router)


@app.get("/api/health")
def health():
    return {"data": {"status": "ok"}, "error": None, "meta": {}}
