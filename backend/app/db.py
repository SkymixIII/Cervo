"""Accès SQLite partagé (métadonnées, état des jobs, verrous de repair).

SQLite en mode WAL : lecteurs concurrents + un writer, suffisant pour un poste
local. La même base est ouverte par le process API ET par les process worker du
`ProcessPoolExecutor` (via un fichier sur volume partagé), d'où `busy_timeout`.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,           -- 'source' | 'reference'
    path         TEXT NOT NULL,
    size         INTEGER NOT NULL,
    cache_hash   TEXT NOT NULL,
    diagnostic   TEXT,                    -- JSON (sources, après analyze)
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id               TEXT PRIMARY KEY,
    source_id        TEXT NOT NULL,
    reference_id     TEXT,
    method_id        TEXT NOT NULL,
    media_scope      TEXT NOT NULL,       -- 'audio' | 'video' | 'both'
    slice_kind       TEXT NOT NULL,       -- '1min' | '5min' | 'full'
    gop_mode         TEXT DEFAULT 'auto', -- 'auto' | 'all-intra' | 'long-gop' (sony-rsv)
    status           TEXT NOT NULL,       -- queued|running|succeeded|failed|canceled
    step             TEXT,
    percent          INTEGER DEFAULT 0,
    cache_key        TEXT,
    repair_cache_hit INTEGER DEFAULT 0,
    artifact_path    TEXT,
    preview_path     TEXT,
    child_pid        INTEGER,
    cancel_requested INTEGER DEFAULT 0,
    parent_job_id    TEXT,
    error_code       TEXT,
    error_message    TEXT,
    error_hint       TEXT,
    logs_ref         TEXT,
    created_at       TEXT NOT NULL,
    started_at       TEXT,
    finished_at      TEXT
);

-- Registre "repair en cours" (non-négociable b) : une clé de cache en cours de
-- réparation possède ici une ligne. Un 2e job sur la même clé s'y ATTACHE au lieu
-- de lancer un second untrunc.
CREATE TABLE IF NOT EXISTS repair_locks (
    cache_key     TEXT PRIMARY KEY,
    status        TEXT NOT NULL,          -- 'in_progress' | 'done' | 'failed'
    owner_job_id  TEXT NOT NULL,
    artifact_path TEXT,
    updated_at    TEXT NOT NULL
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Migrations idempotentes pour les bases existantes (CREATE IF NOT EXISTS ne
    rajoute pas les colonnes ajoutées après coup)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    if "gop_mode" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN gop_mode TEXT DEFAULT 'auto'")


@contextmanager
def cursor(db_path: str):
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()
