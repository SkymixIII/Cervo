"""Interface plugin `RecoveryMethod` + registre (03 §2.1).

Chaque méthode de récupération est un plugin interchangeable. Le cœur (pipeline,
jobs, API) ne connaît que ce contrat. Ajouter une méthode = enregistrer un plugin,
sans toucher au pipeline.

Découpage : la méthode est responsable de l'étape **repair** (produire l'artefact
« source réparée »). Les étapes **slice-copy / validate / publish** sont génériques
(voir `pipeline/`) car identiques quelle que soit la méthode qui a produit le MP4.

`confidence` est un **float 0..1 interne** (MAJ-14, tranché arbitrage #2) ; la
couche de présentation le mappe vers un label qualitatif (voir `confidence.py`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


@dataclass
class Applicability:
    applicable: bool
    confidence: float          # 0..1 interne
    reason: str = ""


@dataclass
class RepairContext:
    source_path: str
    reference_path: str | None
    cfg: object                                  # app.config.Config
    tmp_dir: Path                                # untrunc écrit ici (puis rename atomique)
    is_canceled: Callable[[], bool]
    on_child_pid: Callable[[int | None], None]
    on_progress: Callable[[float], None] = lambda pct: None
    options: dict = field(default_factory=dict)  # ex: {"rsv_ben": True}


class RecoveryMethod(Protocol):
    id: str
    display_name: str
    requires_reference: bool

    def capabilities(self) -> dict: ...
    def can_handle(self, diagnostic: dict, options: dict) -> Applicability: ...
    def repair(self, ctx: RepairContext) -> Path: ...


# ---- Registre --------------------------------------------------------------

_REGISTRY: dict[str, RecoveryMethod] = {}


def register(method: RecoveryMethod) -> RecoveryMethod:
    _REGISTRY[method.id] = method
    return method


def get(method_id: str) -> RecoveryMethod | None:
    return _REGISTRY.get(method_id)


def all_methods() -> list[RecoveryMethod]:
    return list(_REGISTRY.values())


def applicable(diagnostic: dict, options: dict | None = None) -> list[tuple[RecoveryMethod, Applicability]]:
    """Méthodes applicables au diagnostic, triées par confiance décroissante.

    Alimente le mode Auto (03 §5) et le chaînage front `/api/methods/applicable`.
    """
    options = options or {}
    scored: list[tuple[RecoveryMethod, Applicability]] = []
    for m in _REGISTRY.values():
        app = m.can_handle(diagnostic, options)
        if app.applicable:
            scored.append((m, app))
    scored.sort(key=lambda t: t[1].confidence, reverse=True)
    return scored


def resolve_method_id(method_id: str, diagnostic: dict, options: dict | None = None) -> str | None:
    """Résout 'auto' vers le plugin concret le plus probable (03 §4.2)."""
    if method_id and method_id != "auto":
        return method_id if method_id in _REGISTRY else None
    ranked = applicable(diagnostic, options)
    return ranked[0][0].id if ranked else None


def load_builtin_methods() -> None:
    """Enregistre les plugins de la V1. Import différé = point d'extension simple."""
    from . import untrunc_moov  # noqa: F401  (s'auto-enregistre à l'import)
    from . import ffmpeg_remux  # noqa: F401
