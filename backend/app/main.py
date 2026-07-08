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
from .pipeline import cache
from .store import job_manager
from .api import media, references, methods as methods_api, jobs, browse


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = Config.from_env()
    cfg.ensure_dirs()
    init_db(cfg.db_path)
    methods.load_builtin_methods()
    # BLOQ-b-1a : au boot, aucun worker n'a survécu → on nettoie les verrous de
    # repair et les jobs restés « en cours » (sinon deadlock permanent du verrou).
    reaped_locks = cache.reap_stale_locks(cfg.db_path)
    reaped_jobs = job_manager.reap_orphan_jobs(cfg.db_path)
    if reaped_locks or reaped_jobs:
        print(f"[boot] nettoyage orphelins: {reaped_locks} verrou(x), {reaped_jobs} job(s)")
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
app.include_router(browse.router)


@app.get("/api/health")
def health():
    return {"data": {"status": "ok"}, "error": None, "meta": {}}
