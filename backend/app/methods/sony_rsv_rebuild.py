"""Plugin `sony-rsv-rebuild` — reconstruction d'un `.rsv` Sony via référence.

Validé par le **Spike 02** (docs/spike/spike-02-mxf.md + docs/spike/poc-rsv/) :
le `.rsv` du PXW-Z200 n'est **ni MP4 ni MXF** — c'est un conteneur de récupération
**propriétaire Sony** (blocs KLV privés à pas 11264 o) contenant l'essence
**XAVC-I (H.264 All-Intra 4:2:2 10-bit)** + **PCM 24-bit**, écrite AVANT finalisation.
Aucun outil sur étagère ne le lit (ffmpeg/bmx le rejettent).

Structure décodée (Spike 02 + Incrément 4/audio) :
- **Vidéo** : NAL H.264 framés **avcC** `[u32 len][NAL]` — access units `AUD+SEI+slices`.
  SPS/PPS pris dans la **référence** (byte-identiques). Frontière de frame = AUD.
- **Audio** : chunks **PCM s24be 4 canaux entrelacés** insérés entre les GOP vidéo,
  sans en-tête de longueur → délimités par l'AUD vidéo suivant (validé).

Reconstruction (streaming, mémoire bornée — le fichier va jusqu'à ~70 Go) :
  1. **de-chunk** du framing Sony (retire les clusters KLV) ;
  2. **carve** vidéo (frames) + **collecte** audio (chunks) en UN SEUL passage ;
  3. écrit un **Annex-B vidéo** (SPS/PPS de la référence + slices) et un **PCM audio**
     dans des fichiers temporaires (jamais tout en RAM) ;
  4. **mux** ffmpeg → MP4 (vidéo + audio) avec fps/timescale de la référence.

L'artefact réparé contient **toujours vidéo + audio** ; le périmètre média
(`audio`/`video`/`both`) est appliqué en aval par le slice `-c copy` (`-map`).
La **dernière frame partielle** (bord de la troncature) n'est jamais émise.
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
NAL_AFTER_AUD = {1, 5, 6}                                 # 1er NAL après AUD dans une vraie frame
MAX_NAL = 8 << 20                                         # garde-fou taille NAL
READ_CHUNK = 4 << 20                                      # lecture source par blocs
TRIM_AT = 32 << 20                                        # compaction du buffer essence

# Audio : 4 canaux PCM s24be entrelacés (échantillon-frame = 4 × 3 octets).
# Format FIXE du conteneur Sony (Spike 02, confirmé par la référence). Les chunks
# audio sont insérés entre les GOP puis complétés par du PADDING (zéros) avant l'AUD
# suivant → on ne garde QUE le PCM réel, en verrouillant sa longueur sur l'horloge
# vidéo (frames × échantillons/frame) : sync A/V garantie, padding jeté.
AUDIO_RATE = 48000
AUDIO_CH = 4
AUDIO_BYTES_PER_SF = AUDIO_CH * 3


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
            "tracks": ["video", "audio"],     # audio PCM 4 canaux (Incrément 4/audio)
        }

    def can_handle(self, diagnostic: dict, options: dict) -> Applicability:
        if diagnostic.get("container") != "sony-rsv":
            return Applicability(False, 0.0, "Conteneur non `.rsv` Sony (méthode dédiée XAVC-I).")
        return Applicability(
            True, 0.9,
            "Fichier de récupération Sony `.rsv` (XAVC-I / H.264 All-Intra + PCM) — référence "
            "requise pour les paramètres SPS/PPS (byte-identiques, Spike 02).",
        )

    # -- repair : de-chunk streaming -> carve vidéo + collecte audio -> mux --
    def repair(self, ctx: RepairContext) -> Path:
        if not ctx.reference_path:
            raise ValueError("sony-rsv-rebuild requiert un fichier de référence.")

        ffmpeg = getattr(ctx.cfg, "ffmpeg", "ffmpeg")
        ffprobe = getattr(ctx.cfg, "ffprobe", "ffprobe")

        sps, pps, fps = _reference_params(ffmpeg, ffprobe, ctx.reference_path, ctx.tmp_dir)
        if not sps or not pps:
            raise RuntimeError("Impossible d'extraire SPS/PPS de la référence (H.264 attendu).")
        # Octets audio par frame vidéo = (rate / fps) × canaux × 3, verrou de sync A/V.
        num, den = (int(x) for x in fps.split("/"))
        samples_per_frame = round(AUDIO_RATE * den / num) if num else 1920
        frame_audio_bytes = samples_per_frame * AUDIO_BYTES_PER_SF

        video_h264 = ctx.tmp_dir / "video.h264"
        audio_pcm = ctx.tmp_dir / "audio.pcm"
        out_path = ctx.tmp_dir / "repaired.mp4"

        # 1) passage streaming unique : sépare vidéo (Annex-B) et audio (PCM brut).
        frames, audio_bytes = self._stream_carve(ctx, sps, pps, video_h264, audio_pcm,
                                                 frame_audio_bytes)
        if frames == 0:
            raise RuntimeError("Aucune frame reconstruite depuis le `.rsv` (framing inattendu ?).")

        # 2) mux ffmpeg : vidéo + audio (si présent).
        argv = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-fflags", "+genpts", "-r", fps, "-f", "h264", "-i", str(video_h264),
        ]
        has_audio = audio_bytes >= AUDIO_BYTES_PER_SF
        if has_audio:
            argv += ["-f", "s24be", "-ar", str(AUDIO_RATE), "-ac", str(AUDIO_CH), "-i", str(audio_pcm),
                     "-map", "0:v:0", "-map", "1:a:0"]
        else:
            argv += ["-map", "0:v:0"]
        argv += ["-c", "copy", "-video_track_timescale", "25000",
                 "-movflags", "+faststart", str(out_path)]

        ctx.on_progress(92.0)
        _run_subprocess(argv, ctx, ctx.tmp_dir / "ffmpeg.log")

        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError("Le mux ffmpeg n'a produit aucun MP4.")
        # temporaires volumineux : libérer tout de suite (l'artefact est publié à part).
        video_h264.unlink(missing_ok=True)
        audio_pcm.unlink(missing_ok=True)
        ctx.on_progress(100.0)
        return out_path

    def _stream_carve(self, ctx: RepairContext, sps, pps, video_h264: Path, audio_pcm: Path,
                      frame_audio_bytes: int):
        """Lit la source par blocs, de-chunke, sépare vidéo/audio. UN passage.

        Retourne (nb_frames, nb_octets_audio). La dernière frame partielle est droppée.
        Corrige aussi le drop de la frame qui précède chaque chunk audio (Incrément 4) :
        une frame terminée par de l'audio (record non-NAL) est bien émise.

        **Sync audio** : chaque chunk audio est tronqué à `frames_depuis_dernier_chunk ×
        frame_audio_bytes` (le PCM réel est en tête, le padding en queue) → la durée
        audio suit exactement l'horloge vidéo.
        """
        ess = bytearray()
        cursor = 0
        pending_audio = -1          # offset de début d'un chunk audio en attente de fin, ou -1
        carry = b""
        read_bytes = 0
        frames = 0
        frames_since_audio = 0      # frames émises depuis le dernier chunk audio (verrou sync)
        audio_bytes = 0
        header_written = False

        def flush_audio(chunk: bytes) -> int:
            nonlocal frames_since_audio
            want = frames_since_audio * frame_audio_bytes
            take = min(want, len(chunk) - (len(chunk) % AUDIO_BYTES_PER_SF))
            if take > 0:
                fa.write(chunk[:take])
            # complète en silence si le PCM réel manque (garde la sync stricte)
            if take < want:
                fa.write(b"\x00" * (want - take))
                take = want
            frames_since_audio = 0
            return take

        total = max(1, os.path.getsize(ctx.source_path))
        fv = open(video_h264, "wb")
        fa = open(audio_pcm, "wb")

        def emit_video(nals, first):
            buf = bytearray()
            for n in [n for t, n in nals if t == 9][:1]:   # AUD (un seul)
                buf += START + n
            if first:                                       # SPS/PPS avant la 1re frame
                for n in (*sps, *pps):
                    buf += START + n
            for t, n in nals:                               # SEI + slices
                if t in (6, 5, 1):
                    buf += START + n
            fv.write(buf)

        try:
            with open(ctx.source_path, "rb") as f:
                while True:
                    if ctx.is_canceled():
                        raise Canceled()
                    data = f.read(READ_CHUNK)
                    ended = not data
                    read_bytes += len(data)
                    essence, carry = _dechunk(carry + data, ended)
                    ess += essence

                    while True:
                        # (a) on cherche la fin d'un chunk audio commencé.
                        if pending_audio >= 0:
                            end = _find_next_frame_start(ess, max(pending_audio, cursor), ended)
                            if end == -2:            # need more data
                                break
                            if end == -1:            # plus aucune frame : audio de queue
                                audio_bytes += flush_audio(ess[pending_audio:])
                                pending_audio = -1
                                cursor = len(ess)
                                break
                            audio_bytes += flush_audio(ess[pending_audio:end])
                            pending_audio = -1
                            cursor = end
                            continue

                        # (b) frame vidéo suivante.
                        a = ess.find(AVCC_AUD, cursor)
                        if a < 0:
                            cursor = max(cursor, len(ess) - 4)
                            break
                        nals, nextpos, status = _walk_frame(ess, a, ended)
                        if status == "need_more":
                            cursor = a
                            break
                        if status == "bad":
                            cursor = a + 5
                            continue
                        # frame complète (terminée par AUD ou par audio) → émise.
                        emit_video(nals, first=not header_written)
                        header_written = True
                        frames += 1
                        frames_since_audio += 1
                        if status == "audio":
                            pending_audio = nextpos    # le chunk audio démarre ici
                        else:
                            cursor = nextpos           # AUD suivant
                        continue

                    # compaction du buffer (seulement quand pas au milieu d'un chunk audio).
                    if pending_audio < 0 and cursor > TRIM_AT:
                        del ess[:cursor]
                        cursor = 0

                    ctx.on_progress(min(90.0, read_bytes / total * 90.0))
                    if ended:
                        break
        finally:
            fv.close()
            fa.close()
        return frames, audio_bytes


def _dechunk(buf: bytes, ended: bool):
    """Retire les clusters KLV Sony ; retourne (essence, carry_non_résolu).

    Sans état : si les 11 octets == clé Sony → paquet KLV (sauté via sa longueur BER) ;
    sinon → essence jusqu'à la prochaine clé Sony. Tout paquet/clé incomplet en fin de
    buffer est renvoyé en `carry`.
    """
    out = bytearray()
    i = 0
    n = len(buf)
    while i < n:
        if buf[i:i + 11] == SONY_KLV_KEY:
            if i + 16 > n:
                break
            ln, hl = _ber_len(buf, i + 16)
            if ln is None:
                break
            end = i + 16 + hl + ln
            if end > n:
                if ended:
                    i = n
                break
            i = end
            continue
        j = buf.find(SONY_KLV_KEY, i)
        if j < 0:
            if ended:
                out += buf[i:]
                i = n
            else:
                keep = max(i, n - 15)
                out += buf[i:keep]
                i = keep
            break
        out += buf[i:j]
        i = j
    return bytes(out), buf[i:]


def _walk_frame(ess: bytearray, a: int, ended: bool):
    """Parse un access unit avcC (`[u32 len][NAL]`) à partir d'un AUD en `a`.

    Retourne (nals, nextpos, status) avec status ∈ {complete, audio, need_more, bad} :
    - complete : frame terminée par l'**AUD suivant** (`nextpos` = son offset) ;
    - audio    : frame terminée par un **record non-NAL** (= début d'un chunk audio),
                 `nextpos` = offset de l'audio → la frame est émise (pas de drop) ;
    - need_more : buffer insuffisant (lire plus), sauf si `ended` ;
    - bad      : faux AUD / frame non terminée → droppée (drop dernière frame partielle).
    """
    pos = a
    nals: list[tuple[int, bytes]] = []
    N = len(ess)
    while True:
        if pos + 4 > N:
            return (None, pos, "bad" if ended else "need_more")
        L = struct.unpack(">I", ess[pos:pos + 4])[0]
        b0 = ess[pos + 4] if pos + 4 < N else 0
        is_nal = (1 <= L <= MAX_NAL) and (b0 & 0x80) == 0 and (b0 & 0x1f) in VCL_TYPES
        if not is_nal:
            # record non-vidéo → audio (ou junk) : la frame courante se termine ici.
            return (nals, pos, "audio") if _has_slice(nals) else (None, pos, "bad")
        t = b0 & 0x1f
        if t == 9 and nals:
            return (nals, pos, "complete") if _has_slice(nals) else (None, pos, "bad")
        if pos + 4 + L > N:
            return (None, pos, "bad" if ended else "need_more")
        nals.append((t, bytes(ess[pos + 4:pos + 4 + L])))
        pos += 4 + L


def _valid_frame_start(ess: bytearray, c: int, ended: bool) -> int:
    """1 si un vrai début de frame est en `c`, 0 sinon, -2 si buffer insuffisant.

    Un vrai AUD vidéo est suivi d'un NAL SEI/slice framé avcC — contrôle qui rejette
    les faux `00 00 00 02 09` pouvant apparaître dans le PCM (silence).
    """
    N = len(ess)
    if c + 6 > N:
        return -2 if not ended else 0
    if ess[c:c + 4] != b"\x00\x00\x00\x02" or (ess[c + 4] & 0x1f) != 9:
        return 0
    p = c + 6
    if p + 5 > N:
        return -2 if not ended else 0
    L = struct.unpack(">I", ess[p:p + 4])[0]
    b0 = ess[p + 4]
    if not (1 <= L <= MAX_NAL) or (b0 & 0x80) != 0 or (b0 & 0x1f) not in NAL_AFTER_AUD:
        return 0
    return 1


def _find_next_frame_start(ess: bytearray, frm: int, ended: bool) -> int:
    """Prochain **vrai** début de frame ≥ `frm`. Retourne offset, -1 (aucun, ended) ou -2 (need more)."""
    pos = frm
    while True:
        a = ess.find(AVCC_AUD, pos)
        if a < 0:
            return -1 if ended else -2
        v = _valid_frame_start(ess, a, ended)
        if v == 1:
            return a
        if v == -2:
            return -2
        pos = a + 5


def _has_slice(nals) -> bool:
    return any(t in (1, 5) for t, _ in nals)


# --- Référence : SPS/PPS + fps + layout audio ------------------------------

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
    return sps[:1], pps[:8], _reference_fps(ffprobe, ref_path)


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
            if int(den) != 0 and int(num):
                return val
    except Exception:
        pass
    return "25"


def _run_subprocess(argv, ctx: RepairContext, log_path: Path) -> None:
    """Lance ffmpeg (mux) avec publication du PID + annulation (non-négociable d)."""
    log = open(log_path, "wb")
    proc = subprocess.Popen(argv, stdout=log, stderr=log, start_new_session=True)
    ctx.on_child_pid(proc.pid)
    try:
        while proc.poll() is None:
            if ctx.is_canceled():
                _kill(proc)
                raise Canceled()
            time.sleep(0.1)
        rc = proc.returncode
        if rc != 0:
            raise ToolFailed(argv, rc, _tail(log_path))
    finally:
        ctx.on_child_pid(None)
        log.close()
        if proc.poll() is None:
            _kill(proc)


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
