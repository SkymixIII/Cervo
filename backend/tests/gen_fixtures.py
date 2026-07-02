"""Génère les fixtures synthétiques du Spike 01 : réf saine + source tronquée (.rsv-like).

MP4 H.264 (XAVC-S nominal) + audio AAC. La « corruption » = suppression de l'atome
`moov` (troncature au début du moov) → il reste `ftyp+mdat`, profil d'un enregistrement
Sony interrompu avant finalisation.
"""
from __future__ import annotations

import os
import struct
import subprocess
import sys
from pathlib import Path


def _ffmpeg_gen(ffmpeg: str, dur: int, out: str, bitrate: str = "8M") -> None:
    subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={dur}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
         "-c:v", "libx264", "-preset", "veryfast", "-b:v", bitrate,
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", out],
        check=True,
    )


def _moov_offset(path: str) -> int:
    size = os.path.getsize(path)
    off = 0
    with open(path, "rb") as f:
        while off < size:
            f.seek(off)
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            n = struct.unpack(">I", hdr[:4])[0]
            typ = hdr[4:8].decode("latin1", "replace")
            real = n if n > 1 else (struct.unpack(">Q", f.read(8))[0] if n == 1 else size - off)
            if typ == "moov":
                return off
            if real <= 0:
                break
            off += real
    raise RuntimeError("Aucun atome moov trouvé (impossible de fabriquer le cas .rsv).")


def make_fixtures(media_root: str, ffmpeg: str = "ffmpeg") -> dict:
    root = Path(media_root)
    root.mkdir(parents=True, exist_ok=True)
    reference = root / "reference.mp4"
    full = root / "full.mp4"
    broken = root / "broken.rsv"

    _ffmpeg_gen(ffmpeg, 5, str(reference))     # référence saine courte
    _ffmpeg_gen(ffmpeg, 15, str(full))         # « rush » sain
    # copie -> troncature du moov
    broken.write_bytes(full.read_bytes())
    os.truncate(str(broken), _moov_offset(str(full)))

    return {"reference": str(reference), "full": str(full), "broken": str(broken)}


if __name__ == "__main__":
    mr = sys.argv[1] if len(sys.argv) > 1 else "./data/media"
    ff = os.environ.get("APP_FFMPEG", "ffmpeg")
    print(make_fixtures(mr, ff))
