"""Media Registry (03 §1) — fichiers source & références + diagnostic.

Le `cache_hash` non-intégral (non-négociable c) est calculé UNE fois ici, à
l'enregistrement, et stocké. Il sert de composant de la clé de cache d'artefact
réparé (`source_hash` / `reference_hash`).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from ..db import connect
from ..hashing import cache_hash


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def register_media(cfg, path: str, kind: str) -> dict:
    assert kind in ("source", "reference")
    mid = ("src_" if kind == "source" else "ref_") + uuid.uuid4().hex[:12]
    size = os.path.getsize(path)
    h = cache_hash(path, cfg.hash_sample_count, cfg.hash_sample_bytes)
    conn = connect(cfg.db_path)
    try:
        conn.execute(
            "INSERT INTO media(id, kind, path, size, cache_hash, diagnostic, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (mid, kind, path, size, h, None, _now()),
        )
    finally:
        conn.close()
    return {"id": mid, "kind": kind, "path": path, "size": size, "cache_hash": h}


def get_media(cfg, media_id: str) -> dict | None:
    conn = connect(cfg.db_path)
    try:
        row = conn.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    d = dict(row)
    if d.get("diagnostic"):
        d["diagnostic"] = json.loads(d["diagnostic"])
    return d


def set_diagnostic(cfg, media_id: str, diagnostic: dict) -> None:
    conn = connect(cfg.db_path)
    try:
        conn.execute("UPDATE media SET diagnostic=? WHERE id=?",
                     (json.dumps(diagnostic), media_id))
    finally:
        conn.close()
