"""Job Manager (03 §4) — file in-process (ProcessPoolExecutor) + état SQLite.

Arbitrage MIN-5 : pas de Redis en V1. Le worker est un **module appelable**
(`run_job_worker`), découplé du process HTTP → DockerManager pourra le déplacer
sans changer le contrat. La communication inter-process passe par SQLite
(état/progression) : l'API écrit `cancel_requested`, le worker publie `child_pid`
et la progression ; l'endpoint SSE lit ces lignes.

Non-négociable d : l'annulation tue le GROUPE du sous-process média via `child_pid`
(runner.kill_pid_group), pas via `ProcessPoolExecutor.cancel()`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ..config import Config
from ..db import connect
from ..pipeline import cache, pipeline as pl
from ..pipeline.runner import Canceled, ToolFailed, kill_pid_group
from ..methods import base as methods
from . import media_registry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- Création / lecture -----------------------------------------------------

def reap_orphan_jobs(db_path: str) -> int:
    """Nettoyage au démarrage (BLOQ-b-1) : marque `failed` les jobs restés
    `queued`/`running` après un redémarrage dur (leur worker n'a pas survécu au
    ProcessPool). Retourne le nombre de jobs nettoyés. Va de pair avec
    `cache.reap_stale_locks`.
    """
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE jobs SET status='failed', step='orphaned', error_code='JOB_FAILED', "
            "error_message='Job interrompu par un redémarrage de l''application.', "
            "child_pid=NULL, finished_at=? WHERE status IN ('queued','running')",
            (_now(),),
        )
        return cur.rowcount or 0
    finally:
        conn.close()


def create_job(cfg: Config, *, source_id: str, method_id: str, media_scope: str,
               slice_kind: str, reference_id: str | None, parent_job_id: str | None = None,
               gop_mode: str = "auto") -> dict:
    jid = "job_" + uuid.uuid4().hex[:12]
    conn = connect(cfg.db_path)
    try:
        conn.execute(
            "INSERT INTO jobs(id, source_id, reference_id, method_id, media_scope, slice_kind, "
            "gop_mode, status, step, percent, parent_job_id, created_at) "
            "VALUES(?,?,?,?,?,?,?, 'queued', 'queued', 0, ?, ?)",
            (jid, source_id, reference_id, method_id, media_scope, slice_kind, gop_mode,
             parent_job_id, _now()),
        )
    finally:
        conn.close()
    return get_job(cfg, jid)


def get_job(cfg: Config, job_id: str) -> dict | None:
    conn = connect(cfg.db_path)
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def _update(db_path: str, job_id: str, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    conn = connect(db_path)
    try:
        conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))
    finally:
        conn.close()


def request_cancel(cfg: Config, job_id: str) -> bool:
    """Marque l'annulation et tue le sous-process média en cours (non-négociable d)."""
    job = get_job(cfg, job_id)
    if job is None:
        return False
    if job["status"] in ("succeeded", "failed", "canceled"):
        return False
    _update(cfg.db_path, job_id, cancel_requested=1)
    child_pid = job.get("child_pid")
    if child_pid:
        kill_pid_group(int(child_pid))  # kill du GROUPE ffmpeg/untrunc, pas du worker
    return True


# ---- Soumission au pool -----------------------------------------------------

def submit(cfg: Config, pool, job_id: str):
    """Soumet le job au ProcessPoolExecutor. `run_job_worker` est picklable."""
    fut = pool.submit(run_job_worker, job_id, cfg.to_dict())
    fut.add_done_callback(lambda f: _on_future_done(cfg.db_path, job_id, f))
    return fut


def _on_future_done(db_path: str, job_id: str, fut) -> None:
    # Filet de sécurité : si le worker a crashé sans écrire de statut terminal.
    exc = fut.exception()
    if exc is not None:
        conn = connect(db_path)
        try:
            row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row and row["status"] in ("queued", "running"):
                conn.execute(
                    "UPDATE jobs SET status='failed', step='crashed', error_code='JOB_FAILED', "
                    "error_message=?, child_pid=NULL, finished_at=? WHERE id=?",
                    (f"Worker crashé: {exc}", _now(), job_id),
                )
        finally:
            conn.close()


# ---- Exécution (process worker) --------------------------------------------

def run_job_worker(job_id: str, cfg_dict: dict) -> None:
    """Point d'entrée exécuté DANS un process du pool (spawn → repart à froid)."""
    cfg = Config.from_dict(cfg_dict)
    methods.load_builtin_methods()  # registre à repeupler dans ce process
    db_path = cfg.db_path

    job = get_job(cfg, job_id)
    if job is None:
        return
    if job.get("cancel_requested"):
        _update(db_path, job_id, status="canceled", step="canceled", finished_at=_now())
        return

    source = media_registry.get_media(cfg, job["source_id"])
    reference = media_registry.get_media(cfg, job["reference_id"]) if job["reference_id"] else None
    if source is None:
        _update(db_path, job_id, status="failed", step="error", error_code="FILE_NOT_FOUND",
                error_message="Source introuvable dans le registre.", finished_at=_now())
        return

    reference_hash = reference["cache_hash"] if reference else "noref"

    _update(db_path, job_id, status="running", started_at=_now(), step="probe", percent=0)

    # Callbacks inter-process (via SQLite).
    def is_canceled() -> bool:
        row = get_job(cfg, job_id)
        return bool(row and row.get("cancel_requested"))

    def on_child_pid(pid):
        _update(db_path, job_id, child_pid=pid)

    last = {"step": None, "pct": -1}

    def on_step(step: str, pct: float):
        ip = int(pct)
        if step != last["step"] or ip != last["pct"]:
            last["step"], last["pct"] = step, ip
            _update(db_path, job_id, step=step, percent=max(0, min(100, ip)))

    try:
        result = pl.run_recovery(
            cfg=cfg,
            db_path=db_path,
            job_id=job_id,
            method_id=job["method_id"],
            source_path=source["path"],
            source_hash=source["cache_hash"],
            reference_path=reference["path"] if reference else None,
            reference_hash=reference_hash,
            media_scope=job["media_scope"],
            slice_kind=job["slice_kind"],
            diagnostic=source.get("diagnostic"),
            options={"gop_mode": job.get("gop_mode") or "auto"},
            is_canceled=is_canceled,
            on_child_pid=on_child_pid,
            on_step=on_step,
        )
        _update(
            db_path, job_id,
            status="succeeded", step="done", percent=100, child_pid=None,
            cache_key=cache.cache_key(source["cache_hash"], result.method_id, reference_hash,
                                      result.variant),
            repair_cache_hit=1 if result.repair_cache_hit else 0,
            artifact_path=result.artifact_path, preview_path=result.preview_path,
            finished_at=_now(),
        )
    except Canceled:
        _update(db_path, job_id, status="canceled", step="canceled", child_pid=None,
                error_code="CANCELED", error_message="Job annulé.", finished_at=_now())
    except pl.RecoveryError as e:
        _update(db_path, job_id, status="failed", step="error", child_pid=None,
                error_code=e.code, error_message=e.message, error_hint=e.hint, finished_at=_now())
    except ToolFailed as e:
        _update(db_path, job_id, status="failed", step="error", child_pid=None,
                error_code="JOB_FAILED", error_message=str(e)[:1000],
                error_hint="Consultez les logs de l'outil (untrunc/ffmpeg).", finished_at=_now())
    except Exception as e:  # filet
        _update(db_path, job_id, status="failed", step="error", child_pid=None,
                error_code="JOB_FAILED", error_message=f"{type(e).__name__}: {e}"[:1000],
                finished_at=_now())
