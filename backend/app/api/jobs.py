"""Routes jobs (03 §4-5).

POST /api/jobs               — crée un job (source, méthode, scope, slice, référence?)
GET  /api/jobs/{id}          — état + progression + résultat
GET  /api/jobs/{id}/events   — flux SSE de progression
POST /api/jobs/{id}/cancel   — annulation (kill du sous-process média)
POST /api/jobs/{id}/extend   — étend à l'intégrale (réutilise l'artefact réparé caché)
GET  /api/jobs/{id}/preview  — sert la tranche (Range supporté)
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .. import envelope as env
from ..config import Config
from ..methods import base as methods
from ..store import job_manager, media_registry
from .deps import get_cfg, get_pool

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

VALID_SCOPES = {"audio", "video", "both"}
VALID_SLICES = {"1min", "5min", "full"}
VALID_GOP_MODES = {"auto", "all-intra", "long-gop"}


class SliceSpec(BaseModel):
    kind: str = "1min"


class CreateJob(BaseModel):
    source_id: str
    method_id: str = "auto"
    media_scope: str = "both"
    slice: SliceSpec = SliceSpec()
    reference_id: str | None = None
    gop_mode: str = "auto"      # sony-rsv : 'auto' | 'all-intra' | 'long-gop'


def _job_public(job: dict) -> dict:
    """Projection API d'un job (masque les champs internes type child_pid)."""
    out = {
        "job_id": job["id"],
        "status": job["status"],
        "method_id": job["method_id"],
        "media_scope": job["media_scope"],
        "slice_kind": job["slice_kind"],
        "gop_mode": job.get("gop_mode") or "auto",
        "progress": {"step": job.get("step"), "percent": job.get("percent") or 0},
        "repair_cache_hit": bool(job.get("repair_cache_hit")),
        "parent_job_id": job.get("parent_job_id"),
    }
    if job["status"] == "failed" and job.get("error_code"):
        out["error"] = {"code": job["error_code"], "message": job.get("error_message"),
                        "hint": job.get("error_hint")}
    if job["status"] == "succeeded":
        out["result"] = {"has_preview": bool(job.get("preview_path"))}
    return out


@router.post("")
def create_job(body: CreateJob, request: Request, cfg: Config = Depends(get_cfg)):
    if body.media_scope not in VALID_SCOPES:
        return env.err(env.VALIDATION_ERROR, f"media_scope invalide: {body.media_scope}")
    if body.slice.kind not in VALID_SLICES:
        return env.err(env.VALIDATION_ERROR, f"slice.kind invalide: {body.slice.kind}")
    if body.gop_mode not in VALID_GOP_MODES:
        return env.err(env.VALIDATION_ERROR, f"gop_mode invalide: {body.gop_mode}")

    source = media_registry.get_media(cfg, body.source_id)
    if source is None:
        return env.err(env.NOT_FOUND, "Source inconnue.", status_code=404)
    if body.reference_id and media_registry.get_media(cfg, body.reference_id) is None:
        return env.err(env.NOT_FOUND, "Référence inconnue.", status_code=404)

    # Validation précoce si le diagnostic est disponible (sinon le worker s'en charge).
    diag = source.get("diagnostic")
    if diag:
        resolved = methods.resolve_method_id(body.method_id, diag)
        if resolved is None:
            return env.err(env.CODEC_UNSUPPORTED_BY_METHOD,
                           "Aucune méthode applicable à ce fichier.",
                           "Vérifiez le conteneur/codec, ou fournissez une référence.")
        m = methods.get(resolved)
        if m and m.requires_reference and not body.reference_id:
            return env.err(env.REFERENCE_REQUIRED,
                           f"La méthode {resolved} requiert un fichier de référence.",
                           "Enregistrez une référence saine (POST /api/references) et repassez son id.")

    job = job_manager.create_job(
        cfg, source_id=body.source_id, method_id=body.method_id,
        media_scope=body.media_scope, slice_kind=body.slice.kind,
        reference_id=body.reference_id, gop_mode=body.gop_mode,
    )
    job_manager.submit(cfg, get_pool(request), job["id"])
    return env.ok({"job_id": job["id"], "status": "queued"}, status_code=202)


@router.get("/{job_id}")
def get_job(job_id: str, cfg: Config = Depends(get_cfg)):
    job = job_manager.get_job(cfg, job_id)
    if job is None:
        return env.err(env.NOT_FOUND, "Job inconnu.", status_code=404)
    return env.ok(_job_public(job))


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, cfg: Config = Depends(get_cfg)):
    ok = job_manager.request_cancel(cfg, job_id)
    if not ok:
        return env.err(env.VALIDATION_ERROR, "Job introuvable ou déjà terminé.", status_code=409)
    return env.ok({"job_id": job_id, "canceling": True})


@router.post("/{job_id}/extend")
def extend_job(job_id: str, request: Request, cfg: Config = Depends(get_cfg)):
    parent = job_manager.get_job(cfg, job_id)
    if parent is None:
        return env.err(env.NOT_FOUND, "Job parent inconnu.", status_code=404)
    # Job enfant en intégrale : réutilise l'artefact réparé en cache (repair sauté).
    child = job_manager.create_job(
        cfg, source_id=parent["source_id"], method_id=parent["method_id"],
        media_scope=parent["media_scope"], slice_kind="full",
        reference_id=parent["reference_id"], parent_job_id=job_id,
        gop_mode=parent.get("gop_mode") or "auto",
    )
    job_manager.submit(cfg, get_pool(request), child["id"])
    return env.ok({"job_id": child["id"], "status": "queued", "parent_job_id": job_id},
                  status_code=202)


@router.get("/{job_id}/preview")
def preview(job_id: str, cfg: Config = Depends(get_cfg)):
    job = job_manager.get_job(cfg, job_id)
    if job is None:
        return env.err(env.NOT_FOUND, "Job inconnu.", status_code=404)
    if job["status"] != "succeeded" or not job.get("preview_path"):
        return env.err(env.NOT_FOUND, "Aperçu non disponible (job non terminé).",
                       "Attendez le statut 'succeeded'.", status_code=409)
    # FileResponse gère les requêtes Range (streaming du lecteur HTML5).
    return FileResponse(job["preview_path"], media_type="video/mp4",
                        filename=f"{job_id}_{job['slice_kind']}.mp4")


@router.get("/{job_id}/events")
async def events(job_id: str, request: Request, cfg: Config = Depends(get_cfg)):
    """Flux SSE : lit l'état du job en base et pousse les changements (03 §4.3)."""

    async def gen():
        last = None
        terminal = {"succeeded", "failed", "canceled"}
        while True:
            if await request.is_disconnected():
                break
            job = job_manager.get_job(cfg, job_id)
            if job is None:
                yield _sse("error", {"message": "job inconnu"})
                break
            snapshot = (job["status"], job.get("step"), job.get("percent"))
            if snapshot != last:
                last = snapshot
                yield _sse("progress", {
                    "job_id": job_id,
                    "status": job["status"],
                    "step": job.get("step"),
                    "percent": job.get("percent") or 0,
                    "repair_cache_hit": bool(job.get("repair_cache_hit")),
                })
            if job["status"] in terminal:
                yield _sse("done", _job_public(job))
                break
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
