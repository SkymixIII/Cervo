"""Plugin `ffmpeg-remux` — STUB résiduel (hors périmètre actif de l'incrément 1).

⚠️ Le Spike 01 §3.4 a **INVALIDÉ** ce fallback pour le cas central : sur un fichier
réellement SANS `moov`, ffmpeg n'ouvre rien (ni vidéo ni audio). Il est donc
rétrogradé au seul cas résiduel « moov partiel/corrompu mais présent » — non
implémenté dans cet incrément. Ce stub existe pour :
  1. démontrer que le registre de plugins accueille une 2e méthode sans toucher au cœur,
  2. déclarer honnêtement `can_handle = NON applicable sans moov`.

Sera étoffé dans un incrément ultérieur (arbitrage #2, séquence §3).
"""
from __future__ import annotations

from pathlib import Path

from .base import Applicability, RepairContext, register


class FfmpegRemux:
    id = "ffmpeg-remux"
    display_name = "Réparation directe (sans référence) — résiduel"
    requires_reference = False

    def capabilities(self) -> dict:
        return {"containers": ["mp4"], "codecs": ["h264", "h265"], "tracks": ["video", "audio"]}

    def can_handle(self, diagnostic: dict, options: dict) -> Applicability:
        atoms = diagnostic.get("atoms", {})
        if not atoms.get("moov"):
            # Spike 01 §3.4 : sans moov, ffmpeg seul ne récupère RIEN.
            return Applicability(False, 0.0,
                                 "Sans `moov`, ffmpeg ne peut rien démuxer (Spike 01). Fournir une référence → untrunc-moov.")
        return Applicability(False, 0.0, "Cas résiduel (moov partiel) non implémenté dans cet incrément.")

    def repair(self, ctx: RepairContext) -> Path:
        raise NotImplementedError("ffmpeg-remux résiduel non implémenté (incrément 1).")


register(FfmpegRemux())
