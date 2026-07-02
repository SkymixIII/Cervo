"""Routes fichiers & diagnostic (03 §5).

POST /api/media            — enregistre une source (chemin monté, confiné)
POST /api/media/{id}/analyze  — diagnostic structurel
GET  /api/media/{id}/diagnostic
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from .. import envelope as env
from ..config import Config
from ..pipeline.analyze import analyze
from ..security import confine, PathForbidden, MediaFileNotFound
from ..store import media_registry
from .deps import get_cfg

router = APIRouter(prefix="/api/media", tags=["media"])


class RegisterMedia(BaseModel):
    path: str


@router.post("")
def register_media(body: RegisterMedia, cfg: Config = Depends(get_cfg)):
    try:
        safe = confine(body.path, cfg.media_root)
    except PathForbidden as e:
        return env.err(env.PATH_FORBIDDEN, str(e),
                       "Placez le fichier sous la racine média montée.", status_code=403)
    except MediaFileNotFound:
        return env.err(env.FILE_NOT_FOUND, "Fichier introuvable ou illisible.",
                       "Vérifiez le chemin (confiné à la racine média).", status_code=404)
    rec = media_registry.register_media(cfg, safe, kind="source")
    return env.ok({"source_id": rec["id"], "size": rec["size"], "cache_hash": rec["cache_hash"]},
                  status_code=201)


@router.post("/{media_id}/analyze")
def analyze_media(media_id: str, cfg: Config = Depends(get_cfg)):
    rec = media_registry.get_media(cfg, media_id)
    if rec is None:
        return env.err(env.NOT_FOUND, "Média inconnu.", status_code=404)
    diag = analyze(cfg.ffprobe, rec["path"])
    media_registry.set_diagnostic(cfg, media_id, diag)
    return env.ok(diag)


@router.get("/{media_id}/diagnostic")
def get_diagnostic(media_id: str, cfg: Config = Depends(get_cfg)):
    rec = media_registry.get_media(cfg, media_id)
    if rec is None:
        return env.err(env.NOT_FOUND, "Média inconnu.", status_code=404)
    if not rec.get("diagnostic"):
        return env.err(env.NOT_FOUND, "Diagnostic non calculé.",
                       "Appelez d'abord POST /api/media/{id}/analyze.", status_code=409)
    return env.ok(rec["diagnostic"])
