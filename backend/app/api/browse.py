"""Navigateur de fichiers read-only sous la racine média (incrément 06).

GET /api/browse?path=<relpath> — liste le contenu d'un dossier SOUS la racine
média confinée (`APP_MEDIA_ROOT`). Strictement confiné comme les autres routes
(resolve + appartenance, symlinks compris) : impossible de sortir de la racine,
même via `..` ou un lien symbolique. AUCUNE écriture (lecture seule).

En Docker, les disques utilisateur sont montés sous la racine média
(DockerManager s'en charge) → on ne raisonne qu'en chemins relatifs à
`APP_MEDIA_ROOT`.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends

from .. import envelope as env
from ..config import Config
from ..security import confine_dir, PathForbidden, MediaFileNotFound
from .deps import get_cfg

router = APIRouter(prefix="/api/browse", tags=["browse"])

# Extensions de fichiers récupérables (sources potentielles) — priorisées/marquées.
MEDIA_EXTS = {".rsv", ".mp4", ".mov", ".mxf", ".mts", ".m2ts"}


def _relpath(abs_path: str, root: str) -> str:
    """Chemin relatif à la racine média ; '' pour la racine elle-même."""
    rel = os.path.relpath(abs_path, root)
    return "" if rel == "." else rel


@router.get("")
def browse(path: str = "", cfg: Config = Depends(get_cfg)):
    root = str(Path(cfg.media_root).resolve())
    try:
        safe = confine_dir(path, cfg.media_root)
    except PathForbidden as e:
        return env.err(env.PATH_FORBIDDEN, str(e),
                       "Restez sous la racine média montée.", status_code=403)
    except MediaFileNotFound:
        return env.err(env.FILE_NOT_FOUND, "Dossier introuvable ou illisible.",
                       "Vérifiez le chemin (confiné à la racine média).", status_code=404)

    entries: list[dict] = []
    with os.scandir(safe) as it:
        for e in it:
            try:
                is_dir = e.is_dir()
            except OSError:
                continue  # entrée illisible (permission/lien cassé) → ignorée
            if is_dir:
                entries.append({"name": e.name, "type": "dir", "size": None,
                                "ext": None, "is_media": False})
            else:
                ext = os.path.splitext(e.name)[1].lower()
                try:
                    size = e.stat().st_size
                except OSError:
                    size = None
                entries.append({"name": e.name, "type": "file", "size": size,
                                "ext": ext.lstrip("."), "is_media": ext in MEDIA_EXTS})

    # Tri : dossiers d'abord, puis fichiers récupérables, puis autres — alphabétique.
    def _key(x: dict) -> tuple:
        group = 0 if x["type"] == "dir" else (1 if x["is_media"] else 2)
        return (group, x["name"].lower())

    entries.sort(key=_key)

    cwd = _relpath(safe, root)
    parent = None if safe == root else _relpath(str(Path(safe).parent), root)
    return env.ok({"cwd": cwd, "parent": parent, "entries": entries})
