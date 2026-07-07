"""Plugin `sony-rsv-rebuild` — reconstruction d'un `.rsv` Sony via référence.

Validé par le **Spike 02** (docs/spike/spike-02-mxf.md + docs/spike/poc-rsv/) :
le `.rsv` du PXW-Z200 n'est **ni MP4 ni MXF** — c'est un conteneur de récupération
**propriétaire Sony** (blocs KLV privés à pas 11264 o) contenant l'essence
**XAVC-I (H.264 All-Intra 4:2:2 10-bit)** + PCM, écrite AVANT finalisation. Aucun
outil sur étagère ne le lit (ffmpeg/bmx le rejettent).

Cette méthode **porte le PoC** en production :
  1. **de-chunk** du framing Sony (retire les clusters KLV, reconstitue l'essence) ;
  2. **carve** des access units H.264 (AUD + SEI + slices, framés en avcC 4 octets) ;
  3. **SPS/PPS** pris dans la **référence** saine (byte-identiques — Spike 02 §9.1) ;
  4. **mux** en MP4 lisible (fps/timescale de la référence).

⚠️ **Streaming, mémoire bornée** : le fichier va jusqu'à ~70 Go. On lit par blocs,
on ne charge JAMAIS tout en RAM, et on **pipe** l'Annex-B directement dans le
`stdin` de ffmpeg (pas de gros fichier intermédiaire). La **dernière frame
partielle** (bord de la troncature) n'est jamais émise (drop).

TODO(audio) : désentrelacement des **4 canaux PCM s24be** + mux piste son. Cet
incrément livre la **vidéo** de bout en bout ; l'audio est un incrément suivant.
"""
from __future__ import annotations

import os
import re
import signal
import struct
import subprocess
import time
from pathlib import Path

from .base import Applicability, RepairContext, register
from ..pipeline.runner import Canceled, ToolFailed

# --- Framing Sony (constantes du Spike 02) ---------------------------------
SONY_KLV_KEY = bytes.fromhex("060e2b34025301010c0201")   # clé KLV privée Sony (11 o)
AVCC_AUD = b"\x00\x00\x00\x02\x09"                        # AUD framé avcC (marqueur de frame)
START = b"\x00\x00\x00\x01"                               # start code Annex-B
VCL_TYPES = {1, 5, 6, 9, 12}                              # NAL types attendus dans l'essence
MAX_NAL = 8 << 20                                         # garde-fou taille NAL
READ_CHUNK = 4 << 20                                      # lecture source par blocs
TRIM_AT = 16 << 20                                        # compaction du buffer essence


def _ber_len(buf: bytes, off: int):
    """Décode une longueur BER à `off`. Retourne (valeur, octets_consommés) ou (None,None)."""
    if off >= len(buf):
        return None, None
    b0 = buf[off]
    if b0 < 0x80:
        return b0, 1
    n = b0 & 0x7f
    if n == 0 or off + 1 + n > len(buf):
        return None, None
    return int.from_bytes(buf[off + 1:off + 1 + n], "big"), 1 + n


class SonyRsvRebuild:
    id = "sony-rsv-rebuild"
    display_name = "Reconstruction Sony .rsv (XAVC-I) via référence"
    requires_reference = True

    def capabilities(self) -> dict:
        return {
            "containers": ["sony-rsv"],
            "codecs": ["h264", "xavc-i"],
            "tracks": ["video"],          # audio PCM = incrément suivant (TODO)
        }

    def can_handle(self, diagnostic: dict, options: dict) -> Applicability:
        if diagnostic.get("container") != "sony-rsv":
            return Applicability(False, 0.0, "Conteneur non `.rsv` Sony (méthode dédiée XAVC-I).")
        # Détecté comme .rsv Sony + essence présente : cas nominal validé (Spike 02).
        return Applicability(
            True, 0.9,
            "Fichier de récupération Sony `.rsv` (XAVC-I / H.264 All-Intra) — référence requise "
            "pour les paramètres SPS/PPS (byte-identiques, Spike 02).",
        )

    # -- repair : de-chunk streaming -> carve -> pipe Annex-B dans ffmpeg -----
    def repair(self, ctx: RepairContext) -> Path:
        if not ctx.reference_path:
            raise ValueError("sony-rsv-rebuild requiert un fichier de référence.")

        ffmpeg = getattr(ctx.cfg, "ffmpeg", "ffmpeg")
        ffprobe = getattr(ctx.cfg, "ffprobe", "ffprobe")

        sps, pps, fps = _reference_params(ffmpeg, ffprobe, ctx.reference_path, ctx.tmp_dir)
        if not sps or not pps:
            raise RuntimeError("Impossible d'extraire SPS/PPS de la référence (H.264 attendu).")

        out_path = ctx.tmp_dir / "repaired.mp4"
        log = open(ctx.tmp_dir / "ffmpeg.log", "wb")
        # ffmpeg lit l'Annex-B depuis stdin, mux en MP4 (fps/timescale de la référence).
        argv = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-fflags", "+genpts", "-r", fps, "-f", "h264", "-i", "pipe:0",
            "-c:v", "copy", "-video_track_timescale", "25000",
            "-movflags", "+faststart", str(out_path),
        ]
        proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=log, stderr=log,
            start_new_session=True,
        )
        ctx.on_child_pid(proc.pid)

        total = max(1, os.path.getsize(ctx.source_path))
        frames = 0
        try:
            frames = self._stream_carve(
                ctx, proc, sps, pps, total,
            )
            proc.stdin.close()
            rc = proc.wait()
            if rc != 0:
                tail = _tail(ctx.tmp_dir / "ffmpeg.log")
                raise ToolFailed(argv, rc, tail)
        except Canceled:
            _kill(proc)
            raise
        finally:
            ctx.on_child_pid(None)
            log.close()
            if proc.poll() is None:
                _kill(proc)

        if frames == 0 or not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError("Aucune frame reconstruite depuis le `.rsv` (framing inattendu ?).")
        ctx.on_progress(100.0)
        return out_path

    def _stream_carve(self, ctx: RepairContext, proc, sps, pps, total) -> int:
        """Lit la source par blocs, de-chunke, carve les frames, pipe l'Annex-B.
        Retourne le nombre de frames émises. La dernière frame partielle est droppée.
        """
        ess = bytearray()      # essence de-chunkée en attente de parsing
        cursor = 0             # index de la prochaine frame à chercher
        carry = b""            # octets bruts non résolus (de-chunk)
        read_bytes = 0
        frames = 0
        header_written = False

        def write(nals, first: bool):
            buf = bytearray()
            for n in [n for t, n in nals if t == 9][:1]:   # AUD (un seul)
                buf += START + n
            if first:                                       # SPS/PPS avant la 1re frame
                for n in (*sps, *pps):
                    buf += START + n
            for t, n in nals:                               # SEI + slices
                if t in (6, 5, 1):
                    buf += START + n
            try:
                proc.stdin.write(buf)
            except BrokenPipeError:
                raise ToolFailed(["ffmpeg"], proc.poll() or -1, _tail(ctx.tmp_dir / "ffmpeg.log"))

        with open(ctx.source_path, "rb") as f:
            while True:
                if ctx.is_canceled():
                    raise Canceled()
                data = f.read(READ_CHUNK)
                ended = not data
                read_bytes += len(data)
                essence, carry = _dechunk(carry + data, ended)
                ess += essence

                # Extraire toutes les frames complètes disponibles.
                while True:
                    a = ess.find(AVCC_AUD, cursor)
                    if a < 0:
                        cursor = max(cursor, len(ess) - 4)  # garder un chevauchement
                        break
                    nals, nextpos, status = _walk_frame(ess, a, ended)
                    if status == "need_more":
                        cursor = a
                        break
                    if status == "bad":
                        cursor = a + 5
                        continue
                    # complete : frame pleine, nextpos = début de l'AUD suivant
                    write(nals, first=not header_written)
                    header_written = True
                    frames += 1
                    cursor = nextpos

                # Compaction du buffer pour rester borné en mémoire.
                if cursor > TRIM_AT:
                    del ess[:cursor]
                    cursor = 0

                ctx.on_progress(min(99.0, read_bytes / total * 100.0))
                if ended:
                    break
        # NB : une frame commencée mais non suivie d'un AUD (troncature) reste dans
        # `ess` et n'est JAMAIS écrite → dernière frame partielle droppée.
        return frames


def _dechunk(buf: bytes, ended: bool):
    """Retire les clusters KLV Sony ; retourne (essence, carry_non_résolu).

    Sans état : à chaque position, si les 11 octets == clé Sony → paquet KLV (on
    le saute via sa longueur BER) ; sinon → essence jusqu'à la prochaine clé Sony.
    On garde en `carry` toute clé/paquet incomplet en fin de buffer.
    """
    out = bytearray()
    i = 0
    n = len(buf)
    while i < n:
        if buf[i:i + 11] == SONY_KLV_KEY:
            # paquet KLV : clé(16) + BER + valeur — on le saute entièrement.
            if i + 16 > n:
                break  # clé partielle → carry
            ln, hl = _ber_len(buf, i + 16)
            if ln is None:
                break  # longueur BER incomplète → carry
            end = i + 16 + hl + ln
            if end > n:
                if ended:
                    i = n     # paquet tronqué en fin de fichier : on l'abandonne
                break         # valeur incomplète → carry
            i = end
            continue
        # essence : émettre jusqu'à la prochaine clé Sony.
        j = buf.find(SONY_KLV_KEY, i)
        if j < 0:
            if ended:
                out += buf[i:]
                i = n
            else:
                # garder les 15 derniers octets (clé Sony potentiellement à cheval)
                keep = max(i, n - 15)
                out += buf[i:keep]
                i = keep
            break
        out += buf[i:j]
        i = j
    return bytes(out), buf[i:]


def _walk_frame(ess: bytearray, a: int, ended: bool):
    """Parse un access unit avcC (`[u32 len][NAL]`) à partir d'un AUD en `a`.

    Retourne (nals, nextpos, status) avec status ∈ {complete, need_more, bad}.
    - complete : frame pleine **terminée par l'AUD suivant** (`nextpos` = son offset).
      C'est le SEUL terminateur fiable → garantit qu'on n'émet que des frames entières.
    - need_more : buffer insuffisant pour décider (lire plus) — sauf si `ended`.
    - bad : faux AUD, ou frame non terminée (dernière frame tronquée) → **droppée**.

    Conséquence voulue (drop de la dernière frame partielle) : une frame commencée
    mais dont l'AUD suivant n'apparaît pas avant EOF n'est **jamais** émise.
    """
    pos = a
    nals: list[tuple[int, bytes]] = []
    N = len(ess)
    while True:
        if pos + 4 > N:
            return (None, pos, "bad" if ended else "need_more")
        L = struct.unpack(">I", ess[pos:pos + 4])[0]
        if not (1 <= L <= MAX_NAL):
            return (None, pos, "bad")            # pas un record avcC valide
        t = ess[pos + 4] & 0x1f
        if (ess[pos + 4] & 0x80) != 0:
            return (None, pos, "bad")            # forbidden_zero_bit → faux AUD
        if t == 9 and nals:
            # AUD suivant atteint : frame précédente complète si elle porte des slices.
            return (nals, pos, "complete") if _has_slice(nals) else (None, pos, "bad")
        if t not in VCL_TYPES:
            return (None, pos, "bad")
        if pos + 4 + L > N:
            return (None, pos, "bad" if ended else "need_more")
        nals.append((t, bytes(ess[pos + 4:pos + 4 + L])))
        pos += 4 + L


def _has_slice(nals) -> bool:
    return any(t in (1, 5) for t, _ in nals)


# --- Référence : SPS/PPS + fps ---------------------------------------------

def _reference_params(ffmpeg: str, ffprobe: str, ref_path: str, tmp_dir: Path):
    """Extrait SPS + PPS (Annex-B, 1re frame) et le fps de la référence saine."""
    ref_h264 = tmp_dir / "_ref.h264"
    subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", ref_path,
         "-map", "0:v:0", "-c", "copy", "-bsf:v", "h264_mp4toannexb",
         "-frames:v", "1", "-f", "h264", str(ref_h264)],
        check=False, capture_output=True, timeout=180,
    )
    sps: list[bytes] = []
    pps: list[bytes] = []
    if ref_h264.exists():
        d = ref_h264.read_bytes()
        starts = [m.start() for m in re.finditer(b"\x00\x00\x01", d)]
        for i, s in enumerate(starts):
            p = s + 3
            e = starts[i + 1] if i + 1 < len(starts) else len(d)
            payload = d[p:e]
            while payload and payload[-1] == 0:
                payload = payload[:-1]
            if not payload:
                continue
            t = payload[0] & 0x1f
            if t == 7:
                sps.append(payload)
            elif t == 8:
                pps.append(payload)
        ref_h264.unlink(missing_ok=True)
    fps = _reference_fps(ffprobe, ref_path)
    return sps[:1], pps[:8], fps


def _reference_fps(ffprobe: str, ref_path: str) -> str:
    try:
        p = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", ref_path],
            capture_output=True, text=True, timeout=60,
        )
        val = (p.stdout or "").strip()
        if re.fullmatch(r"\d+/\d+", val):
            num, den = val.split("/")
            if int(den) != 0:
                return val if int(num) else "25"
    except Exception:
        pass
    return "25"


def _tail(path: Path, n: int = 2000) -> str:
    try:
        return path.read_bytes()[-n:].decode("latin1", "replace")
    except OSError:
        return ""


def _kill(proc, grace: float = 2.0) -> None:
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        deadline = time.time() + grace
        while time.time() < deadline:
            if proc.poll() is not None:
                return
            time.sleep(0.05)


register(SonyRsvRebuild())
