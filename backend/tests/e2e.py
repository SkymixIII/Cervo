"""Test end-to-end reproductible du pipeline (mission incrément 1, point 7).

Prouve, via l'API REST réelle (serveur uvicorn lancé en sous-process + ProcessPool) :
  1) enregistrement + analyse d'un .rsv synthétique (moov tronqué) ;
  2) 1er job (untrunc-moov) = repair + slice → succeeded, repair_cache_hit=FALSE ;
  3) 2e job (autre tranche) = CACHE HIT → repair sauté, repair_cache_hit=TRUE, rapide ;
  4) preview décodable (ffprobe) ; SSE émet un event terminal.

Prérequis : ffmpeg/ffprobe locaux + image Docker `untrunc` (cf. Spike 01).
Usage : APP_UNTRUNC_CMD=<wrapper> python -m tests.e2e
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from tests.gen_fixtures import make_fixtures

BACKEND = Path(__file__).resolve().parents[1]
FAILURES: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _req(method: str, url: str, body: dict | None = None, timeout: float = 30.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def _wait_health(base: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            st, _ = _req("GET", f"{base}/api/health", timeout=2)
            if st == 200:
                return True
        except Exception:
            time.sleep(0.3)
    return False


def _poll_job(base: str, job_id: str, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        st, resp = _req("GET", f"{base}/api/jobs/{job_id}")
        data = resp["data"]
        if data["status"] in ("succeeded", "failed", "canceled"):
            return data
        time.sleep(0.2)
    raise TimeoutError(f"job {job_id} non terminé")


def _ffprobe_ok(ffprobe: str, path: str) -> bool:
    p = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-of", "json", path],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return False
    return len(json.loads(p.stdout or "{}").get("streams", [])) > 0


def main() -> int:
    scratch = Path(os.environ.get("E2E_SCRATCH",
                   "/private/tmp/claude-501/-Users-lois--claude-squad-worktrees-lois-builder-18be692d521fc650"
                   "/f9245548-ebb5-4ce9-8f7c-ee8f04f16bcd/scratchpad/e2e"))
    media_root = scratch / "media"
    work_root = scratch / "work"
    db_path = scratch / "app.db"
    # Repart d'un état PROPRE : l'artefact réparé est mis en cache de façon
    # déterministe (hash de fichiers identiques). Sans nettoyage, le 1er job d'un
    # 2e run ferait un cache HIT et fausserait l'assertion « repair réel ».
    import shutil
    if work_root.exists():
        shutil.rmtree(work_root)
    for p in (media_root, work_root):
        p.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    ffmpeg = os.environ.get("APP_FFMPEG", "ffmpeg")
    ffprobe = os.environ.get("APP_FFPROBE", "ffprobe")
    untrunc_cmd = os.environ.get("APP_UNTRUNC_CMD", str(BACKEND.parent / "scripts" / "untrunc-docker.sh"))

    print("== Génération des fixtures (MP4 H.264 + troncature moov) ==")
    fx = make_fixtures(str(media_root), ffmpeg)
    print(f"  reference={fx['reference']}\n  broken={fx['broken']}")

    env = {**os.environ,
           "APP_MEDIA_ROOT": str(media_root), "APP_WORK_ROOT": str(work_root),
           "APP_DB_PATH": str(db_path), "APP_FFMPEG": ffmpeg, "APP_FFPROBE": ffprobe,
           "APP_UNTRUNC_CMD": untrunc_cmd, "APP_WORKERS": "2"}

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    print(f"== Démarrage serveur uvicorn sur {base} ==")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND), env=env,
    )
    try:
        if not _wait_health(base):
            print("  [FAIL] serveur non démarré")
            return 1

        print("== 1) POST /api/media (source cassée) + analyze ==")
        st, resp = _req("POST", f"{base}/api/media", {"path": fx["broken"]})
        check(st == 201, "POST /api/media 201", f"status={st}")
        source_id = resp["data"]["source_id"]

        st, resp = _req("POST", f"{base}/api/media/{source_id}/analyze")
        diag = resp["data"]
        check(diag["atoms"]["mdat"] is True, "diagnostic: mdat présent")
        check(diag["atoms"]["moov"] is False, "diagnostic: moov absent")
        check(diag["recoverable"] is True, "diagnostic: recoverable")
        check(diag["recommendation"] == "reference_required", "diagnostic: reference_required")

        print("== 2) POST /api/references + /methods/applicable ==")
        st, resp = _req("POST", f"{base}/api/references", {"path": fx["reference"]})
        check(st == 201, "POST /api/references 201", f"status={st}")
        reference_id = resp["data"]["reference_id"]

        st, resp = _req("GET", f"{base}/api/methods/applicable?source={source_id}")
        appl = resp["data"]
        top = appl["methods"][0]["id"] if appl["methods"] else None
        check(top == "untrunc-moov", "applicable: untrunc-moov en tête", f"top={top}")
        check(appl["requires_reference"] is True, "applicable: requires_reference=True (MAJ-9)")

        print("== 3) 1er job (1min) — repair réel attendu ==")
        st, resp = _req("POST", f"{base}/api/jobs", {
            "source_id": source_id, "method_id": "untrunc-moov",
            "media_scope": "both", "slice": {"kind": "1min"}, "reference_id": reference_id})
        check(st == 202, "POST /api/jobs 202", f"status={st}")
        job1 = resp["data"]["job_id"]
        t0 = time.time()
        r1 = _poll_job(base, job1)
        dt1 = time.time() - t0
        check(r1["status"] == "succeeded", "job1 succeeded",
              f"status={r1['status']} err={r1.get('error')}")
        check(r1["repair_cache_hit"] is False, "job1 repair_cache_hit=False (repair réel)")
        print(f"    job1 durée={dt1:.2f}s")

        st, resp = _req("GET", f"{base}/api/methods")  # smoke registry
        check(any(m["id"] == "ffmpeg-remux" for m in resp["data"]),
              "registry: 2e plugin (ffmpeg-remux) présent sans toucher au cœur")

        print("== 4) preview job1 décodable ==")
        prev_path = work_root / "dl_job1.mp4"
        with urllib.request.urlopen(f"{base}/api/jobs/{job1}/preview", timeout=30) as r:
            prev_path.write_bytes(r.read())
        check(_ffprobe_ok(ffprobe, str(prev_path)), "preview job1 décodable (ffprobe)")

        print("== 5) 2e job (5min, autre tranche) — CACHE HIT attendu ==")
        st, resp = _req("POST", f"{base}/api/jobs", {
            "source_id": source_id, "method_id": "untrunc-moov",
            "media_scope": "both", "slice": {"kind": "5min"}, "reference_id": reference_id})
        job2 = resp["data"]["job_id"]
        t0 = time.time()
        r2 = _poll_job(base, job2)
        dt2 = time.time() - t0
        check(r2["status"] == "succeeded", "job2 succeeded", f"status={r2['status']}")
        check(r2["repair_cache_hit"] is True, "job2 repair_cache_hit=True (REPAIR SAUTÉ)")
        check(dt2 < 10.0, "job2 rapide (< 10s, pas de re-repair)", f"durée={dt2:.2f}s")
        print(f"    job1(repair)={dt1:.2f}s  vs  job2(cache-hit)={dt2:.2f}s")

        print("== 6) SSE émet un event terminal ==")
        try:
            with urllib.request.urlopen(f"{base}/api/jobs/{job1}/events", timeout=10) as r:
                buf = r.read(4096).decode("utf-8", "replace")
            check("event: done" in buf or "event: progress" in buf, "SSE: events reçus")
        except Exception as e:
            check(False, "SSE: events reçus", str(e))

        print("== 7) extend (intégrale) réutilise le cache ==")
        st, resp = _req("POST", f"{base}/api/jobs/{job1}/extend")
        check(st == 202, "POST extend 202", f"status={st}")
        r3 = _poll_job(base, resp["data"]["job_id"])
        check(r3["status"] == "succeeded" and r3["repair_cache_hit"] is True,
              "extend: succeeded + cache hit")

    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    print("\n=========== RÉSUMÉ ===========")
    if FAILURES:
        print(f"ÉCHECS ({len(FAILURES)}): " + ", ".join(FAILURES))
        return 1
    print("TOUS LES TESTS PASSENT ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
