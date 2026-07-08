"""Analysis Service (03 §1) — diagnostic structurel, ne modifie rien.

Deux sources d'information complémentaires :
- **parseur d'atomes** (`atoms.py`) : marche même sans `moov` → détecte
  conteneur MP4 + présence ftyp/mdat/moov (le cœur du diagnostic .rsv).
- **ffprobe** : donne codec/durée/pistes QUAND le fichier est lisible. Sur un
  fichier sans `moov`, ffprobe échoue (Spike 01 §3.4) → codec "unknown", la
  récupération repose alors sur la référence (`recommendation: reference_required`).
"""
from __future__ import annotations

import json
import subprocess

from .atoms import atom_presence, is_sony_rsv


def _ffprobe(ffprobe_bin: str, path: str) -> dict | None:
    try:
        p = subprocess.run(
            [ffprobe_bin, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=120,
        )
        if p.returncode != 0 or not p.stdout.strip():
            return None
        return json.loads(p.stdout)
    except Exception:
        return None


def _codec_family(video_codec: str | None) -> str:
    if video_codec == "h264":
        return "xavc-s"       # H.264/MP4 = profil XAVC-S nominal V1
    if video_codec in ("hevc", "h265"):
        return "xavc-hs"      # H.265/MP4 = untrunc échoue (hors V1)
    return "unknown"


def analyze(ffprobe_bin: str, path: str) -> dict:
    atoms = atom_presence(path)

    # --- Cas .rsv Sony (Spike 02) : conteneur de récupération propriétaire Sony,
    #     PAS un MP4/MXF. ffprobe n'y voit rien ; on diagnostique par la clé KLV
    #     Sony. Essence = XAVC-I (H.264 All-Intra) ; réparable via référence par
    #     la méthode `sony-rsv-rebuild`. ---
    if not atoms["ftyp"] and is_sony_rsv(path):
        return {
            "container": "sony-rsv",
            "atoms": {"ftyp": False, "mdat": True, "moov": False},
            "brand": "XAVC",
            "codec": {"family": "xavc-i", "video": "h264", "audio": "pcm_s24be"},
            "estimated_duration_s": None,   # inconnu sans index (borné par la référence)
            "tracks": [{"type": "video", "codec": "h264"}, {"type": "audio", "codec": "pcm_s24be"}],
            "recoverable": True,
            "recommendation": "reference_required",  # SPS/PPS + params viennent de la référence
            "probe_readable": False,
        }

    container = "mp4" if atoms["ftyp"] else "unknown"

    probe = _ffprobe(ffprobe_bin, path)
    video_codec = audio_codec = None
    duration = None
    tracks: list[dict] = []
    if probe:
        for s in probe.get("streams", []):
            t = s.get("codec_type")
            if t == "video" and video_codec is None:
                video_codec = s.get("codec_name")
                tracks.append({"type": "video", "codec": video_codec,
                               "width": s.get("width"), "height": s.get("height")})
            elif t == "audio" and audio_codec is None:
                audio_codec = s.get("codec_name")
                tracks.append({"type": "audio", "codec": audio_codec})
        fmt = probe.get("format", {})
        if fmt.get("duration"):
            try:
                duration = float(fmt["duration"])
            except ValueError:
                duration = None

    moov_ok = atoms["moov"]
    mdat_ok = atoms["mdat"]
    # Récupérable = données présentes (mdat) mais index absent/incomplet (moov).
    recoverable = bool(mdat_ok and not moov_ok)

    recommendation = None
    if recoverable:
        recommendation = "reference_required"  # sans réf compatible : non fiable (Spike 01)

    return {
        "container": container,
        "atoms": {"ftyp": atoms["ftyp"], "mdat": mdat_ok, "moov": moov_ok},
        "brand": atoms["brand"],
        "codec": {
            "family": _codec_family(video_codec),
            "video": video_codec,
            "audio": audio_codec,
        },
        "estimated_duration_s": duration,
        "tracks": tracks,
        "recoverable": recoverable,
        "recommendation": recommendation,
        "probe_readable": probe is not None,
    }
