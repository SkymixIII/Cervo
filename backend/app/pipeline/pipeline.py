"""Orchestration du pipeline (03 §2.2) : probe → repair(cache) → slice-copy → validate → publish.

Le repair est délégué au **plugin** choisi et passé au **cache** (`get_or_repair`)
qui applique les non-négociables a (écriture atomique) et b (verrou "repair en cours").
Le slice-copy est générique.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..methods import base as methods
from ..methods.base import RepairContext
from . import cache, slice as slicing
from .analyze import analyze


@dataclass
class PipelineResult:
    artifact_path: str
    preview_path: str
    repair_cache_hit: bool
    method_id: str


def run_recovery(
    *,
    cfg,
    db_path: str,
    method_id: str,
    source_path: str,
    source_hash: str,
    reference_path: str | None,
    reference_hash: str,
    media_scope: str,
    slice_kind: str,
    diagnostic: dict | None,
    options: dict,
    is_canceled: Callable[[], bool],
    on_child_pid: Callable[[int | None], None],
    on_step: Callable[[str, float], None],
) -> PipelineResult:
    # 1) probe — réutilise le diagnostic si fourni, sinon (re)calcule.
    on_step("probe", 0.0)
    diag = diagnostic or analyze(cfg.ffprobe, source_path)

    # Résolution 'auto' -> plugin concret.
    resolved_id = methods.resolve_method_id(method_id, diag, options)
    if resolved_id is None:
        raise RecoveryError("CODEC_UNSUPPORTED_BY_METHOD",
                            "Aucune méthode applicable à ce diagnostic.",
                            "Vérifiez le conteneur/codec ou fournissez une référence.")
    method = methods.get(resolved_id)
    if method is None:
        raise RecoveryError("VALIDATION_ERROR", f"Méthode inconnue: {resolved_id}", None)

    if method.requires_reference and not reference_path:
        raise RecoveryError("REFERENCE_REQUIRED",
                            f"La méthode {resolved_id} requiert un fichier de référence.",
                            "Fournissez une référence saine tournée avec les mêmes réglages.")

    # 2) repair (UNE FOIS, caché) — non-négociables a & b via cache.get_or_repair.
    on_step("repair", 0.0)

    def do_repair(tmp_dir: Path) -> Path:
        ctx = RepairContext(
            source_path=source_path,
            reference_path=reference_path,
            cfg=cfg,
            tmp_dir=tmp_dir,
            is_canceled=is_canceled,
            on_child_pid=on_child_pid,
            on_progress=lambda pct: on_step("repair", pct),
            options=options,
        )
        return method.repair(ctx)

    artifact, cache_hit = cache.get_or_repair(
        db_path=db_path,
        work_root=cfg.work_root,
        ffprobe_bin=cfg.ffprobe,
        source_hash=source_hash,
        method_id=resolved_id,
        reference_hash=reference_hash,
        do_repair=do_repair,
        is_canceled=is_canceled,
        on_wait=lambda: on_step("repair-attached", 50.0),
    )
    on_step("repair", 100.0)

    # 3) slice-copy (O(tranche)) + 4) validate + 5) publish
    on_step("slice-copy", 0.0)
    preview = slicing.extract_slice(
        ffmpeg_bin=cfg.ffmpeg,
        artifact=str(artifact),
        work_root=cfg.work_root,
        source_hash=source_hash,
        method_id=resolved_id,
        reference_hash=reference_hash,
        scope=media_scope,
        slice_kind=slice_kind,
        is_canceled=is_canceled,
        on_child_pid=on_child_pid,
    )
    on_step("validate", 50.0)
    if not cache.validate_decodable(cfg.ffprobe, str(preview)):
        raise RecoveryError("JOB_FAILED", "La tranche extraite n'est pas décodable.", None)
    on_step("publish", 100.0)

    return PipelineResult(
        artifact_path=str(artifact),
        preview_path=str(preview),
        repair_cache_hit=cache_hit,
        method_id=resolved_id,
    )


class RecoveryError(Exception):
    def __init__(self, code: str, message: str, hint: str | None):
        self.code = code
        self.message = message
        self.hint = hint
        super().__init__(message)
