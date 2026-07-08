"""Tests du navigateur de fichiers confiné (incrément 06).

Vérifie sur une arborescence temporaire :
- listing d'un dossier (tri dossiers → média → autres, flags is_media/ext/size) ;
- cas racine (parent=None) et sous-dossier (parent renseigné) ;
- CONFINEMENT : `../..` et un symlink sortant → refus 403 ;
- dossier absent → 404.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.browse import browse  # noqa: E402
from app.config import Config  # noqa: E402


def _cfg(root: Path) -> Config:
    return Config(
        media_root=str(root.resolve()), work_root=str(root), db_path=str(root / "x.db"),
        workers=1, ffmpeg="ffmpeg", ffprobe="ffprobe", untrunc_cmd="untrunc", mp4box="MP4Box",
        hash_sample_count=1, hash_sample_bytes=1024,
    )


def _call(cfg: Config, path: str) -> tuple[int, dict]:
    resp = browse(path=path, cfg=cfg)
    return resp.status_code, json.loads(resp.body)


def _make_tree(root: Path) -> None:
    (root / "sub").mkdir()
    (root / "aaa_dir").mkdir()
    (root / "clip.rsv").write_bytes(b"\x00" * 10)
    (root / "notes.txt").write_text("hello")
    (root / "movie.mp4").write_bytes(b"\x00" * 20)
    (root / "sub" / "inner.mov").write_bytes(b"\x00" * 5)


def test_browse_root_lists_and_sorts(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    st, body = _call(_cfg(tmp_path), "")
    assert st == 200
    data = body["data"]
    assert data["cwd"] == ""
    assert data["parent"] is None
    names = [e["name"] for e in data["entries"]]
    # dossiers d'abord (alpha), puis fichiers média (alpha), puis autres.
    assert names == ["aaa_dir", "sub", "clip.rsv", "movie.mp4", "notes.txt"], names
    by_name = {e["name"]: e for e in data["entries"]}
    assert by_name["clip.rsv"]["is_media"] is True
    assert by_name["clip.rsv"]["ext"] == "rsv"
    assert by_name["clip.rsv"]["size"] == 10
    assert by_name["notes.txt"]["is_media"] is False
    assert by_name["sub"]["type"] == "dir"
    assert by_name["sub"]["size"] is None


def test_browse_subdir_has_parent(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    st, body = _call(_cfg(tmp_path), "sub")
    assert st == 200
    assert body["data"]["cwd"] == "sub"
    assert body["data"]["parent"] == ""  # remonte à la racine
    assert [e["name"] for e in body["data"]["entries"]] == ["inner.mov"]


def test_browse_rejects_traversal(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    _make_tree(root)
    cfg = _cfg(root)
    st, body = _call(cfg, "../..")
    assert st == 403, body
    assert body["error"]["code"] == "PATH_FORBIDDEN"


def test_browse_rejects_escaping_symlink(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "leak.txt").write_text("nope")
    link = root / "escape"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        return  # symlinks indisponibles (ex. Windows) → test sauté
    cfg = _cfg(root)
    st, body = _call(cfg, "escape")
    assert st == 403, body
    assert body["error"]["code"] == "PATH_FORBIDDEN"


def test_browse_missing_dir_404(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    st, body = _call(_cfg(tmp_path), "nope_dir")
    assert st == 404, body
    assert body["error"]["code"] == "FILE_NOT_FOUND"


if __name__ == "__main__":
    import tempfile

    for fn in (test_browse_root_lists_and_sorts, test_browse_subdir_has_parent,
               test_browse_rejects_traversal, test_browse_rejects_escaping_symlink,
               test_browse_missing_dir_404):
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
        print(f"  [PASS] {fn.__name__}")
    print("[PASS] navigateur de fichiers confiné (browse)")
