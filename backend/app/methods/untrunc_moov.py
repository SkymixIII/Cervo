"""Plugin `untrunc-moov` — reconstruction du `moov` via référence (méthode phare V1).

Validé par le Spike 01 sur MP4 H.264 (XAVC-S nominal). Encapsule ENTIÈREMENT
l'appel à untrunc pour que DockerManager formalise le packaging plus tard :
- l'exécutable est piloté par `cfg.untrunc_cmd` (binaire local `untrunc`, ou un
  wrapper docker — cf. `scripts/untrunc-docker.sh`) ;
- contrainte **ffmpeg ≤ 8.0** dans l'image untrunc (struct `FFCodec` cassée au-delà) ;
- option Sony native **`-rsv-ben`** activable via `options={"rsv_ben": True}`.

Usage untrunc (Spike 01) : `untrunc <reference_saine> <fichier_casse>` — la
référence est le **1er** argument. Sortie : `<casse>_fixed.mp4` dans `-dst`.
"""
from __future__ import annotations

from pathlib import Path

from .base import Applicability, RepairContext, register
from ..pipeline.runner import run_tool


class UntruncMoov:
    id = "untrunc-moov"
    display_name = "Reconstruction via fichier de référence sain"
    requires_reference = True

    def capabilities(self) -> dict:
        return {
            "containers": ["mp4"],
            "codecs": ["h264"],          # XAVC-S ; H.265/XAVC-HS explicitement exclu
            "tracks": ["video", "audio"],
        }

    def can_handle(self, diagnostic: dict, options: dict) -> Applicability:
        container = diagnostic.get("container")
        atoms = diagnostic.get("atoms", {})
        codec = (diagnostic.get("codec") or {}).get("video")

        if container != "mp4":
            return Applicability(False, 0.0, "Conteneur non MP4 (untrunc cible l'ISO-BMFF/MP4).")
        if not atoms.get("mdat"):
            return Applicability(False, 0.0, "Aucune donnée `mdat` : rien à reconstruire.")
        if atoms.get("moov"):
            return Applicability(False, 0.0, "Le `moov` est présent : fichier a priori déjà lisible.")
        if codec in ("hevc", "h265"):
            # Piège connu (04 §1.2) : untrunc échoue sur H.265/XAVC-HS.
            return Applicability(False, 0.0, "Codec H.265/XAVC-HS non supporté par untrunc.")

        if codec == "h264":
            return Applicability(True, 0.9, "MP4 H.264 (XAVC-S), moov manquant — cas nominal untrunc.")
        # Codec inconnu (ffprobe illisible sans moov) : plausible mais à confirmer via référence.
        return Applicability(True, 0.6, "MP4 avec moov manquant, codec indéterminé (référence requise).")

    def repair(self, ctx: RepairContext) -> Path:
        if not ctx.reference_path:
            raise ValueError("untrunc-moov requiert un fichier de référence.")

        # ⚠️ untrunc exige les OPTIONS avant les fichiers positionnels (vérifié :
        # `-dst` placé après les fichiers fait afficher l'usage et échoue).
        argv = list(getattr(ctx.cfg, "untrunc_argv0"))
        argv += ["-n"]                                  # non interactif
        argv += ["-dst", str(ctx.tmp_dir)]              # sortie dans le tmp (rename atomique ensuite)
        if ctx.options.get("rsv_ben"):
            argv += ["-rsv-ben"]                        # mode Sony RSV natif
        argv += [ctx.reference_path, ctx.source_path]   # référence en 1er (Spike 01)

        ctx.on_progress(1.0)
        run_tool(
            argv,
            is_canceled=ctx.is_canceled,
            on_child_pid=ctx.on_child_pid,
            on_progress=ctx.on_progress,
        )

        produced = self._find_output(ctx.tmp_dir)
        if produced is None:
            raise RuntimeError("untrunc n'a produit aucun fichier réparé.")
        return produced

    @staticmethod
    def _find_output(tmp_dir: Path) -> Path | None:
        # untrunc nomme la sortie `<input>_fixed.mp4` ; on prend le plus gros .mp4 produit.
        candidates = sorted(
            (p for p in tmp_dir.glob("*.mp4") if p.is_file()),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        return candidates[0] if candidates else None


register(UntruncMoov())
