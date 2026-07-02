"""Routes fichiers de référence (03 §5).

POST /api/references                        — enregistre une référence saine (confinée)
POST /api/references/{id}/check?source={id} — compat estimative référence↔source (MAJ-6)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import envelope as env
from ..config import Config
from ..confidence import label
from ..security import confine, PathForbidden, MediaFileNotFound
from ..store import media_registry
from .deps import get_cfg

router = APIRouter(prefix="/api/references", tags=["references"])


class RegisterReference(BaseModel):
    path: str


@router.post("")
def register_reference(body: RegisterReference, cfg: Config = Depends(get_cfg)):
    try:
        safe = confine(body.path, cfg.media_root)
    except PathForbidden as e:
        return env.err(env.PATH_FORBIDDEN, str(e),
                       "Placez la référence sous la racine média montée.", status_code=403)
    except MediaFileNotFound:
        return env.err(env.FILE_NOT_FOUND, "Référence introuvable ou illisible.", status_code=404)
    rec = media_registry.register_media(cfg, safe, kind="reference")
    return env.ok({"reference_id": rec["id"], "size": rec["size"], "cache_hash": rec["cache_hash"]},
                  status_code=201)


@router.post("/{reference_id}/check")
def check_compat(reference_id: str, source: str, cfg: Config = Depends(get_cfg)):
    """Compat estimative (MAJ-6) : codec identique ⇒ « probablement compatible ».

    Volontairement présenté comme une ESTIMATION, pas une garantie binaire.
    """
    ref = media_registry.get_media(cfg, reference_id)
    src = media_registry.get_media(cfg, source)
    if ref is None or src is None:
        return env.err(env.NOT_FOUND, "Référence ou source inconnue.", status_code=404)

    # La référence doit être lisible pour comparer son codec ; la source peut être cassée.
    from ..pipeline.analyze import analyze
    ref_diag = analyze(cfg.ffprobe, ref["path"])
    src_diag = src.get("diagnostic") or analyze(cfg.ffprobe, src["path"])

    ref_codec = (ref_diag.get("codec") or {}).get("video")
    src_codec = (src_diag.get("codec") or {}).get("video")

    if src_codec and ref_codec and src_codec != ref_codec:
        conf = 0.0
        note = f"Codecs différents (source={src_codec} / référence={ref_codec})."
    elif ref_codec == "h264":
        conf = 0.7 if not src_codec else 0.85
        note = "Référence H.264 compatible untrunc-moov (estimation)."
    else:
        conf = 0.4
        note = "Compatibilité indéterminée (estimation)."

    return env.ok({
        "compatible_estimate": conf > 0.0,
        "confidence": conf,
        "confidence_label": label(conf),
        "note": note,
        "reference_codec": ref_codec,
        "source_codec": src_codec,
    })
