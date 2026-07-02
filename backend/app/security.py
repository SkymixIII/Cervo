"""Confinement des chemins sous la racine du volume média (non-négociable e).

V1 = localhost only, AUCUNE auth. La seule barrière est le confinement strict :
tout chemin fourni par l'utilisateur est résolu (realpath, symlinks compris) et
doit rester sous `media_root`. Sinon → refus (path traversal / lecture arbitraire).
"""
from __future__ import annotations

import os
from pathlib import Path


class PathForbidden(Exception):
    """Le chemin sort de la racine média autorisée."""


class MediaFileNotFound(Exception):
    """Le chemin est confiné mais n'existe pas / n'est pas un fichier."""


def confine(user_path: str, media_root: str) -> str:
    """Résout `user_path` et garantit qu'il reste sous `media_root`.

    Accepte un chemin absolu ou relatif à la racine média. Retourne le chemin
    absolu résolu. Lève `PathForbidden` si hors racine, `MediaFileNotFound` si
    absent.
    """
    root = Path(media_root).resolve()
    p = Path(user_path)
    if not p.is_absolute():
        p = root / p
    resolved = p.resolve()

    # Vérif d'appartenance robuste (pas de comparaison de préfixe de chaîne).
    try:
        resolved.relative_to(root)
    except ValueError:
        raise PathForbidden(
            f"Chemin hors de la racine média autorisée ({root})."
        )

    if not resolved.is_file():
        raise MediaFileNotFound(str(resolved))
    if not os.access(resolved, os.R_OK):
        raise MediaFileNotFound(str(resolved))
    return str(resolved)
