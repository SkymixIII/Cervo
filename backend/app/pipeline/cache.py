"""Cache de l'artefact « source réparée » (BLOQ-3) + non-négociables a & b.

Pilier du produit : le `repair` untrunc est O(taille fichier), payé UNE fois, puis
mis en cache et réutilisé par toutes les tranches / `extend`. Ce module garantit :

(a) **Écriture atomique** : untrunc écrit dans un dossier temporaire → validation
    ffprobe (décodable) → `os.replace` atomique vers le chemin canonique. Le cache
    n'est « disponible » que lorsque le fichier canonique existe (donc jamais un
    artefact partiel).
(b) **Registre "repair en cours"** : table `repair_locks`. Le 1er job d'une clé
    devient *owner* et lance untrunc ; tout autre job sur la même clé s'*attache*
    (poll) au lieu de lancer un second untrunc.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..db import connect


def cache_key(source_hash: str, method_id: str, reference_hash: str, variant: str = "") -> str:
    base = f"{source_hash}:{method_id}:{reference_hash}"
    return f"{base}:{variant}" if variant else base


def artifact_path(work_root: str, source_hash: str, method_id: str, reference_hash: str,
                  variant: str = "") -> Path:
    # `variant` distingue des sorties de repair issues d'options différentes (ex. mode
    # GOP de sony-rsv) : sans lui, deux modes se recouvriraient dans le cache.
    base = Path(work_root) / "repaired" / source_hash / method_id / reference_hash
    if variant:
        base = base / variant
    return base / "repaired.mp4"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_decodable(ffprobe_bin: str, path: str) -> bool:
    """L'artefact réparé est-il lisible (moov reconstruit, au moins 1 stream) ?"""
    try:
        p = subprocess.run(
            [ffprobe_bin, "-v", "error", "-print_format", "json", "-show_streams", path],
            capture_output=True, text=True, timeout=120,
        )
        if p.returncode != 0:
            return False
        import json
        data = json.loads(p.stdout or "{}")
        return len(data.get("streams", [])) > 0
    except Exception:
        return False


# ---- Registre de verrous (non-négociable b) --------------------------------

def _try_acquire(db_path: str, key: str, job_id: str) -> str:
    """Tente de devenir owner du repair. Retourne 'owner' | 'attached'.

    Nettoie les verrous morts ('failed') pour permettre une reprise.
    """
    conn = connect(db_path)
    try:
        while True:
            try:
                conn.execute(
                    "INSERT INTO repair_locks(cache_key, status, owner_job_id, updated_at) "
                    "VALUES(?, 'in_progress', ?, ?)",
                    (key, job_id, _now()),
                )
                return "owner"
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT status FROM repair_locks WHERE cache_key=?", (key,)
                ).fetchone()
                if row is None:
                    continue  # course : la ligne a disparu, on retente l'insert
                if row["status"] == "failed":
                    # verrou mort → on le retire et on retente de l'acquérir
                    conn.execute("DELETE FROM repair_locks WHERE cache_key=? AND status='failed'", (key,))
                    continue
                return "attached"
    finally:
        conn.close()


def _set_lock(db_path: str, key: str, status: str, artifact: str | None = None) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            "UPDATE repair_locks SET status=?, artifact_path=?, updated_at=? WHERE cache_key=?",
            (status, artifact, _now(), key),
        )
    finally:
        conn.close()


def _lock_info(db_path: str, key: str) -> tuple[str, str] | None:
    """Retourne (status, owner_job_id) du verrou, ou None s'il n'existe pas."""
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, owner_job_id FROM repair_locks WHERE cache_key=?", (key,)
        ).fetchone()
        return (row["status"], row["owner_job_id"]) if row else None
    finally:
        conn.close()


def _owner_alive(db_path: str, owner_job_id: str | None) -> bool:
    """Le job propriétaire du verrou est-il encore vivant (queued/running) ?

    Couvre l'OOM-kill SANS redémarrage (BLOQ-b-1) : quand un worker est tué, le
    done-callback du pool marque son job `failed` en base → l'owner n'est plus
    « alive » → tout job attaché récupère le verrou au lieu de boucler à l'infini.
    """
    if not owner_job_id or owner_job_id == "?":
        return False
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT status FROM jobs WHERE id=?", (owner_job_id,)).fetchone()
    finally:
        conn.close()
    return bool(row and row["status"] in ("queued", "running"))


def reap_stale_locks(db_path: str) -> int:
    """Nettoyage au démarrage (BLOQ-b-1a).

    Au boot de l'app, aucun process worker n'a survécu (le seul ProcessPoolExecutor
    vit dans le conteneur `app`). Donc tout verrou resté `in_progress` est
    forcément orphelin → on le passe en `failed` pour permettre une reprise.
    Retourne le nombre de verrous nettoyés.
    """
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE repair_locks SET status='failed', updated_at=? WHERE status='in_progress'",
            (_now(),),
        )
        return cur.rowcount or 0
    finally:
        conn.close()


# ---- Point d'entrée : cache hit / repair / attente --------------------------

def get_or_repair(
    *,
    db_path: str,
    work_root: str,
    ffprobe_bin: str,
    source_hash: str,
    method_id: str,
    reference_hash: str,
    do_repair: Callable[[Path], Path],
    is_canceled: Callable[[], bool],
    owner_job_id: str,
    on_wait: Callable[[], None] | None = None,
    variant: str = "",
) -> tuple[Path, bool]:
    """Retourne `(chemin_artefact, cache_hit)`.

    `do_repair(tmp_dir)` doit produire un MP4 réparé et retourner son chemin (dans
    `tmp_dir`). Il n'est appelé que pour l'owner et jamais en cas de cache hit.
    `owner_job_id` = le vrai id du job (MAJ-code-1), stocké dans le verrou et utilisé
    pour la détection de staleness (BLOQ-b-1).
    """
    key = cache_key(source_hash, method_id, reference_hash, variant)
    canonical = artifact_path(work_root, source_hash, method_id, reference_hash, variant)

    # Cache hit direct : l'existence du fichier canonique est garantie atomique.
    if canonical.exists():
        return canonical, True

    while True:
        role = _try_acquire(db_path, key, owner_job_id)
        if role == "owner":
            tmp_dir = Path(work_root) / ".tmp" / uuid.uuid4().hex
            tmp_dir.mkdir(parents=True, exist_ok=True)
            try:
                produced = do_repair(tmp_dir)   # lance untrunc (peut lever Canceled/ToolFailed)
                if not validate_decodable(ffprobe_bin, str(produced)):
                    raise RuntimeError("Artefact réparé non décodable (validation ffprobe échouée).")
                canonical.parent.mkdir(parents=True, exist_ok=True)
                # (a) publication ATOMIQUE : même système de fichiers (work_root) → os.replace atomique
                os.replace(str(produced), str(canonical))
                _set_lock(db_path, key, "done", str(canonical))
                return canonical, False
            except Exception:
                # Libère le verrou pour permettre une reprise par un autre job.
                _set_lock(db_path, key, "failed")
                raise
            finally:
                _cleanup(tmp_dir)
        else:
            # (b) attaché : on attend la fin du repair de l'owner — MAIS avec
            # détection de verrou mort (BLOQ-b-1) pour ne jamais boucler à l'infini.
            reclaimed = False
            while True:
                if is_canceled():
                    from .runner import Canceled
                    raise Canceled()
                if canonical.exists():
                    return canonical, True
                info = _lock_info(db_path, key)
                if info is None or info[0] == "failed":
                    break  # owner a échoué/disparu → on retente d'acquérir
                st, owner = info
                if st == "done":
                    # marqué done mais artefact absent (course/incohérence) → on reprend.
                    _set_lock(db_path, key, "failed")
                    break
                # st == 'in_progress' : l'owner est-il encore vivant ?
                if not _owner_alive(db_path, owner):
                    # Verrou MORT (owner OOM-killé / crashé / orphelin) → on le
                    # neutralise et on retente d'acquérir plutôt que d'attendre à l'infini.
                    _set_lock(db_path, key, "failed")
                    reclaimed = True
                    break
                if on_wait:
                    on_wait()
                time.sleep(0.2)
            if reclaimed:
                continue  # boucle externe : _try_acquire nettoiera le 'failed' et acquerra


def _cleanup(tmp_dir: Path) -> None:
    try:
        for p in tmp_dir.glob("**/*"):
            if p.is_file():
                p.unlink(missing_ok=True)
        tmp_dir.rmdir()
    except Exception:
        pass
