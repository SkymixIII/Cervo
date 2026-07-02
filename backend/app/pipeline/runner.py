"""Exécution de sous-process média avec ANNULATION propre (non-négociable d).

On lance ffmpeg/untrunc via `subprocess.Popen(start_new_session=True)` → l'enfant
est chef de son propre groupe de process. L'annulation tue le GROUPE (SIGTERM puis
SIGKILL) via son PID, ce qui couvre les éventuels petits-enfants. On NE compte PAS
sur `ProcessPoolExecutor.cancel()` (qui ne peut pas interrompre un job déjà démarré
ni tuer le binaire média).

Le PID de l'enfant est publié via `on_child_pid` (persisté en base par le worker)
pour que l'API puisse demander le kill depuis un AUTRE process. Le flag d'annulation
partagé (`is_canceled`) est sondé en boucle : c'est le worker qui déclenche le kill.
"""
from __future__ import annotations

import os
import re
import select
import signal
import subprocess
import time
from typing import Callable


class Canceled(Exception):
    pass


class ToolFailed(Exception):
    def __init__(self, cmd: list[str], returncode: int, tail: str):
        self.cmd = cmd
        self.returncode = returncode
        self.tail = tail
        super().__init__(f"{cmd[0]} a échoué (code {returncode}): {tail[-500:]}")


_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def run_tool(
    argv: list[str],
    *,
    is_canceled: Callable[[], bool],
    on_child_pid: Callable[[int | None], None],
    on_progress: Callable[[float], None] | None = None,
    poll_interval: float = 0.1,
) -> str:
    """Exécute `argv`, retourne la sortie (stdout+stderr concaténés).

    - `is_canceled()` sondé en continu → SIGTERM/SIGKILL du groupe si vrai.
    - `on_child_pid(pid)` appelé au démarrage (puis `None` à la fin) pour publier
      le handle vers la base (permet un kill inter-process depuis l'API).
    - `on_progress(pct)` reçoit les pourcentages détectés dans la sortie de l'outil
      (untrunc et ffmpeg en émettent).
    """
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,   # nouveau groupe → kill de groupe possible
        bufsize=0,                # binaire, non tamponné (lecture via os.read)
    )
    on_child_pid(proc.pid)
    fd = proc.stdout.fileno()          # type: ignore[union-attr]
    chunks: list[bytes] = []
    pending = b""                      # ligne partielle en cours
    try:
        # Lecture NON bloquante (select) : indispensable pour sonder l'annulation
        # même quand l'outil est SILENCIEUX (ex. untrunc en plein scan) — sinon un
        # readline() bloquant empêcherait tout kill (non-négociable d).
        while True:
            if is_canceled():
                _kill_group(proc)
                raise Canceled()
            r, _, _ = select.select([fd], [], [], poll_interval)
            if r:
                data = os.read(fd, 65536)
                if data == b"":  # EOF
                    break
                chunks.append(data)
                pending += data
                if on_progress:
                    # untrunc/ffmpeg poussent la progression avec des '\r'.
                    parts = re.split(rb"[\r\n]", pending)
                    pending = parts.pop()
                    for line in parts:
                        m = _PCT.search(line.decode("latin1", "replace"))
                        if m:
                            try:
                                on_progress(float(m.group(1)))
                            except ValueError:
                                pass
            elif proc.poll() is not None:
                break
        rc = proc.wait()
        out = b"".join(chunks).decode("latin1", "replace")
        if rc != 0:
            raise ToolFailed(argv, rc, out)
        return out
    finally:
        on_child_pid(None)
        if proc.poll() is None:
            _kill_group(proc)


def _kill_group(proc: subprocess.Popen, grace: float = 3.0) -> None:
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.time() + grace
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def kill_pid_group(pid: int) -> None:
    """Tue le groupe d'un PID connu (appelé par l'API pour annuler à distance)."""
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, PermissionError):
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        time.sleep(0.2)
        try:
            os.killpg(pgid, 0)  # existe encore ?
        except ProcessLookupError:
            return
