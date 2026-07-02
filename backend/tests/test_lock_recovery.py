"""Régression BLOQ-b-1 : récupération d'un verrou `repair_locks` MORT.

Reproduit le trou signalé en review : un verrou resté `in_progress` alors que son
owner est mort (SIGKILL/OOM/crash dur, ou redémarrage) ne doit PLUS geler à l'infini
les réparations de la clé. On prouve les deux mécanismes de récupération :

  A. **Nettoyage au boot** (`cache.reap_stale_locks`) : tout `in_progress` → `failed`.
  B. **Détection de staleness sans redémarrage** : owner dont le job est terminal
     (ex. `failed` posé par le done-callback du pool après OOM) → l'attaché récupère
     le verrou au lieu de boucler, et le repair aboutit (avec garde anti-deadlock).
  C. **Cas sain concurrent** (régression inverse) : 2 appels simultanés sur la même
     clé ⇒ EXACTEMENT un seul repair réel, l'autre s'attache proprement.

Sans dépendance ffprobe : `validate_decodable` est neutralisé (le sujet du test est
le cycle de vie du verrou, pas le décodage).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app import db as dbmod
from app.pipeline import cache


def _setup(tmp_path: Path):
    db_path = str(tmp_path / "t.db")
    dbmod.init_db(db_path)
    work_root = str(tmp_path / "work")
    Path(work_root).mkdir(parents=True, exist_ok=True)
    # Neutralise la validation ffprobe (hors sujet ici).
    cache.validate_decodable = lambda *a, **k: True  # type: ignore
    return db_path, work_root


def _insert_lock(db_path: str, key: str, status: str, owner: str) -> None:
    conn = dbmod.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO repair_locks(cache_key, status, owner_job_id, updated_at) VALUES(?,?,?,?)",
            (key, status, owner, datetime.now(timezone.utc).isoformat()),
        )
    finally:
        conn.close()


def _insert_job(db_path: str, job_id: str, status: str) -> None:
    conn = dbmod.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO jobs(id, source_id, method_id, media_scope, slice_kind, status, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (job_id, "src_x", "untrunc-moov", "both", "1min", status,
             datetime.now(timezone.utc).isoformat()),
        )
    finally:
        conn.close()


def _make_do_repair(counter: list, delay: float = 0.0):
    lock = threading.Lock()

    def do_repair(tmp_dir: Path) -> Path:
        with lock:
            counter[0] += 1
        if delay:
            time.sleep(delay)
        out = tmp_dir / "repaired.mp4"
        out.write_bytes(b"FAKE_MP4_ARTIFACT")
        return out

    return do_repair


def _lock_status(db_path: str, key: str) -> str | None:
    info = cache._lock_info(db_path, key)
    return info[0] if info else None


def test_A_boot_cleanup(tmp_path: Path) -> None:
    db_path, work_root = _setup(tmp_path)
    key = cache.cache_key("sA", "untrunc-moov", "rA")
    _insert_lock(db_path, key, "in_progress", "job_dead")  # orphelin (owner jamais en base)

    reaped = cache.reap_stale_locks(db_path)
    assert reaped == 1, "reap_stale_locks aurait dû nettoyer 1 verrou"
    assert _lock_status(db_path, key) == "failed"

    counter = [0]
    art, hit = cache.get_or_repair(
        db_path=db_path, work_root=work_root, ffprobe_bin="ffprobe",
        source_hash="sA", method_id="untrunc-moov", reference_hash="rA",
        do_repair=_make_do_repair(counter), is_canceled=lambda: False, owner_job_id="job_new",
    )
    assert hit is False and Path(art).exists() and counter[0] == 1
    print("[PASS] A — nettoyage au boot : le repair reprend après verrou orphelin")


def test_B_owner_dead_no_restart(tmp_path: Path) -> None:
    db_path, work_root = _setup(tmp_path)
    key = cache.cache_key("sB", "untrunc-moov", "rB")
    _insert_job(db_path, "job_owner_oom", "failed")      # owner tué → job posé 'failed'
    _insert_lock(db_path, key, "in_progress", "job_owner_oom")  # verrou resté in_progress

    counter = [0]
    result: dict = {}

    def worker():
        result["out"] = cache.get_or_repair(
            db_path=db_path, work_root=work_root, ffprobe_bin="ffprobe",
            source_hash="sB", method_id="untrunc-moov", reference_hash="rB",
            do_repair=_make_do_repair(counter), is_canceled=lambda: False, owner_job_id="job_live",
        )

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=10)
    assert not t.is_alive(), "DEADLOCK : get_or_repair bloqué sur un verrou mort (régression BLOQ-b-1)"
    art, hit = result["out"]
    assert hit is False and Path(art).exists() and counter[0] == 1
    print("[PASS] B — staleness sans redémarrage : verrou mort récupéré, pas de deadlock")


def test_C_healthy_concurrency(tmp_path: Path) -> None:
    db_path, work_root = _setup(tmp_path)
    # Deux owners potentiels, tous deux 'running' (le vainqueur de la course reste vivant).
    _insert_job(db_path, "jobA", "running")
    _insert_job(db_path, "jobB", "running")
    counter = [0]
    do_repair = _make_do_repair(counter, delay=0.4)
    outs: dict = {}

    def worker(name, owner):
        outs[name] = cache.get_or_repair(
            db_path=db_path, work_root=work_root, ffprobe_bin="ffprobe",
            source_hash="sC", method_id="untrunc-moov", reference_hash="rC",
            do_repair=do_repair, is_canceled=lambda: False, owner_job_id=owner,
        )

    ta = threading.Thread(target=worker, args=("A", "jobA"))
    tb = threading.Thread(target=worker, args=("B", "jobB"))
    ta.start(); tb.start(); ta.join(timeout=15); tb.join(timeout=15)
    assert not ta.is_alive() and not tb.is_alive()
    assert counter[0] == 1, f"repair exécuté {counter[0]}x (attendu 1 : l'autre doit s'attacher)"
    hits = sorted([outs["A"][1], outs["B"][1]])
    assert hits == [False, True], f"attendu un owner + un attaché, obtenu {hits}"
    print("[PASS] C — concurrence saine : 1 seul repair réel, l'autre attaché")


if __name__ == "__main__":
    import tempfile
    for fn in (test_A_boot_cleanup, test_B_owner_dead_no_restart, test_C_healthy_concurrency):
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
    print("test_lock_recovery OK ✅")
