"""Extraction de tranche par `ffmpeg -c copy` (03 §3.3) — O(tranche), quasi gratuit.

Sur l'artefact réparé (MP4 complet), extraire [start, +durée] en COPIE de flux :
pas de réencodage (Spike 01 : ~0,2 s, ~25× plus rapide qu'un réencodage). Le
périmètre média (audio/vidéo/both) est appliqué par `-map`, toujours en copie.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .runner import run_tool

# Durées des tranches (03 §3.4). `full` = pas de borne de durée.
SLICE_DURATIONS = {"1min": 60, "5min": 300, "full": None}


def slice_output_path(work_root: str, source_hash: str, method_id: str,
                      reference_hash: str, scope: str, slice_kind: str) -> Path:
    return (Path(work_root) / "slices" / source_hash / method_id / reference_hash
            / scope / f"{slice_kind}.mp4")


def build_slice_argv(ffmpeg_bin: str, src: str, dst: str, scope: str, slice_kind: str) -> list[str]:
    argv = [ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error"]
    duration = SLICE_DURATIONS.get(slice_kind)
    # -ss avant -i : seek rapide ; start=0 en V1 (03 §3.4).
    argv += ["-ss", "0", "-i", src]
    if duration is not None:
        argv += ["-t", str(duration)]
    # Périmètre média via -map (toujours en copie de flux).
    if scope == "audio":
        argv += ["-map", "0:a?", "-vn"]
    elif scope == "video":
        argv += ["-map", "0:v?", "-an"]
    else:  # both
        argv += ["-map", "0:v?", "-map", "0:a?"]
    argv += ["-c", "copy", "-movflags", "+faststart", dst]
    return argv


def extract_slice(
    *,
    ffmpeg_bin: str,
    artifact: str,
    work_root: str,
    source_hash: str,
    method_id: str,
    reference_hash: str,
    scope: str,
    slice_kind: str,
    is_canceled: Callable[[], bool],
    on_child_pid: Callable[[int | None], None],
) -> Path:
    dst = slice_output_path(work_root, source_hash, method_id, reference_hash, scope, slice_kind)
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Cache de tranche (2e niveau, 03 §3.3) : déjà extraite → resservie.
    if dst.exists():
        return dst
    tmp = dst.with_suffix(".partial.mp4")
    argv = build_slice_argv(ffmpeg_bin, artifact, str(tmp), scope, slice_kind)
    run_tool(argv, is_canceled=is_canceled, on_child_pid=on_child_pid)
    import os
    os.replace(str(tmp), str(dst))  # même dossier → atomique
    return dst
