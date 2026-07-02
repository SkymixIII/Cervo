"""Preuve déterministe du non-négociable (d) : annulation propre du sous-process.

`run_tool` lance un process (ici `sleep 30`) dans son propre groupe ; dès que le
flag d'annulation passe à True, il doit TUER le groupe (SIGTERM/SIGKILL) et lever
`Canceled` — sans attendre la fin naturelle. On vérifie aussi que le PID publié
n'existe plus après coup.
"""
from __future__ import annotations

import os
import signal
import time

from app.pipeline.runner import run_tool, Canceled


def test_cancel_kills_child_group() -> None:
    captured = {"pid": None}
    start = time.time()
    canceled_at = start + 0.5

    def is_canceled() -> bool:
        return time.time() >= canceled_at

    def on_child_pid(pid):
        if pid is not None:
            captured["pid"] = pid

    raised = False
    try:
        run_tool(["sleep", "30"], is_canceled=is_canceled, on_child_pid=on_child_pid)
    except Canceled:
        raised = True
    elapsed = time.time() - start

    assert raised, "Canceled aurait dû être levé"
    assert elapsed < 5.0, f"annulation trop lente ({elapsed:.2f}s) — devrait tuer ~immédiatement"
    assert captured["pid"] is not None

    # Le process enfant ne doit plus exister.
    alive = True
    try:
        os.kill(captured["pid"], 0)
    except ProcessLookupError:
        alive = False
    assert not alive, f"le process enfant {captured['pid']} tourne encore"
    print(f"[PASS] annulation en {elapsed:.2f}s, enfant pid={captured['pid']} bien tué")


if __name__ == "__main__":
    test_cancel_kills_child_group()
    print("test_cancel OK ✅")
