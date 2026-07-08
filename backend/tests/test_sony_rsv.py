"""Tests unitaires du framing Sony `.rsv` (Incrément 4, dérivé du Spike 02).

Vérifie sur une essence SYNTHÉTIQUE (pas besoin du vrai fichier 70 Go) :
- `_dechunk` retire bien les clusters KLV Sony et reconstitue l'essence ;
- `_walk_frame` ne rend une frame que si elle est **terminée par l'AUD suivant**
  → la **dernière frame partielle est droppée** (exigence Incrément 4).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.methods.sony_rsv_rebuild import (  # noqa: E402
    SONY_KLV_KEY, _dechunk, _walk_frame, _find_next_frame_start, AVCC_AUD,
)


def _avcc(nal: bytes) -> bytes:
    return struct.pack(">I", len(nal)) + nal


def _frame(slice_type: int = 5, slice_len: int = 4000) -> bytes:
    aud = _avcc(bytes([0x09, 0x10]))
    sei = _avcc(bytes([0x06]) + b"\x00" * 12)
    sl = _avcc(bytes([0x20 | slice_type]) + b"\x11" * slice_len)  # nal_ref_idc + type
    return aud + sei + sl


def _sony_cluster() -> bytes:
    # clé Sony (16 o) + BER court + valeur arbitraire, ×2 paquets
    def pkt(val: bytes) -> bytes:
        key = SONY_KLV_KEY + b"\x01\x01\x00\x00\x00"  # complète la clé à 16 o
        return key[:16] + bytes([len(val)]) + val
    return pkt(b"\xaa" * 20) + pkt(b"\xbb" * 40)


def test_dechunk_strips_sony_clusters() -> None:
    essence = _frame() + _frame()
    # intercale un cluster Sony au milieu de l'essence
    mid = len(essence) // 2
    raw = essence[:mid] + _sony_cluster() + essence[mid:]
    out, carry = _dechunk(raw, ended=True)
    assert carry == b""
    assert SONY_KLV_KEY not in out
    assert out == essence, "l'essence de-chunkée doit être identique sans les clusters"


def test_walk_frame_drops_last_partial() -> None:
    # 2 frames complètes + 1 frame partielle (AUD + slice mais AUCUN AUD suivant)
    ess = bytearray(_frame() + _frame() + _frame())
    frames = []
    cursor = 0
    while True:
        a = ess.find(AVCC_AUD, cursor)
        if a < 0:
            break
        nals, nextpos, status = _walk_frame(ess, a, ended=True)
        if status == "complete":
            frames.append(nals)
            cursor = nextpos
        elif status == "bad":
            cursor = a + 5
        else:
            break
    # Seules les 2 premières frames (terminées par l'AUD suivant) sont rendues ;
    # la 3e (non terminée) est droppée.
    assert len(frames) == 2, f"attendu 2 frames complètes, obtenu {len(frames)}"
    for nals in frames:
        assert any(t in (1, 5) for t, _ in nals), "chaque frame doit porter des slices"


def test_frame_before_audio_not_dropped() -> None:
    # frame vidéo suivie d'un chunk AUDIO (record non-NAL) : la frame doit être
    # rendue avec status 'audio' (régression : elle était droppée en Incrément 4).
    audio = b"\xff\xff\xed\x00\x00\x3b" * 2000            # PCM-like (u32 tête = grande valeur)
    ess = bytearray(_frame() + audio + _frame())
    nals, nextpos, status = _walk_frame(ess, 0, ended=False)
    assert status == "audio", f"attendu 'audio', obtenu {status}"
    assert any(t in (1, 5) for t, _ in nals), "la frame avant l'audio doit être conservée"
    # nextpos pointe le début de l'audio ; le prochain vrai AUD est APRÈS l'audio.
    real = _find_next_frame_start(ess, nextpos, ended=True)
    assert real == len(_frame()) + len(audio), "l'audio doit être délimité par l'AUD vidéo suivant"


def test_find_next_frame_start_skips_false_aud_in_pcm() -> None:
    # un faux AUD (00 00 00 02 09) dans du PCM ne doit pas être pris pour une frame.
    false_aud = b"\x00\x00\x00\x02\x09" + b"\x00" * 40    # pas de NAL SEI/slice derrière
    ess = bytearray(false_aud + _frame())
    pos = _find_next_frame_start(ess, 0, ended=True)
    assert pos == len(false_aud), "le faux AUD dans le PCM doit être ignoré"


if __name__ == "__main__":
    test_dechunk_strips_sony_clusters()
    test_walk_frame_drops_last_partial()
    test_frame_before_audio_not_dropped()
    test_find_next_frame_start_skips_false_aud_in_pcm()
    print("[PASS] framing Sony .rsv : de-chunk + drop frame partielle + audio (délim + anti-drop)")
