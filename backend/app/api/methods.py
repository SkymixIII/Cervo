"""Routes méthodes de récupération (03 §5).

GET /api/methods                       — liste des plugins + capacités
GET /api/methods/applicable?source={id} — méthodes applicables (triées) + requires_reference (MAJ-9)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import envelope as env
from ..config import Config
from ..confidence import label
from ..methods import base as methods
from ..store import media_registry
from .deps import get_cfg

router = APIRouter(prefix="/api/methods", tags=["methods"])


@router.get("")
def list_methods():
    data = [
        {
            "id": m.id,
            "display_name": m.display_name,
            "requires_reference": m.requires_reference,
            "capabilities": m.capabilities(),
        }
        for m in methods.all_methods()
    ]
    return env.ok(data)


@router.get("/applicable")
def applicable_methods(source: str, cfg: Config = Depends(get_cfg)):
    rec = media_registry.get_media(cfg, source)
    if rec is None:
        return env.err(env.NOT_FOUND, "Source inconnue.", status_code=404)
    diag = rec.get("diagnostic")
    if not diag:
        return env.err(env.NOT_FOUND, "Diagnostic non calculé.",
                       "Appelez d'abord POST /api/media/{id}/analyze.", status_code=409)

    ranked = methods.applicable(diag)
    data = [
        {
            "id": m.id,
            "display_name": m.display_name,
            "requires_reference": m.requires_reference,
            "confidence": app.confidence,             # float 0..1 interne (MAJ-14)
            "confidence_label": label(app.confidence),  # mappé à la présentation
            "reason": app.reason,
        }
        for m, app in ranked
    ]
    # requires_reference de la 1re méthode → pilote l'affichage conditionnel (MAJ-9)
    top_requires_reference = data[0]["requires_reference"] if data else None
    return env.ok({"methods": data, "requires_reference": top_requires_reference})
