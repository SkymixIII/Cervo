"""Parseur d'atomes/boxes MP4 top-level (ISO-BMFF).

Fonctionne SANS `moov` (contrairement à ffprobe qui échoue « moov atom not found »
sur un .rsv). C'est ce qui permet de diagnostiquer un fichier corrompu : présence
de `ftyp` / `mdat` / `moov`. Repris du parseur du Spike 01.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass
class Atom:
    type: str
    offset: int
    size: int


def parse_top_level(path: str, max_atoms: int = 100000) -> list[Atom]:
    import os

    size = os.path.getsize(path)
    out: list[Atom] = []
    off = 0
    with open(path, "rb") as f:
        while off < size and len(out) < max_atoms:
            f.seek(off)
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            n = struct.unpack(">I", hdr[:4])[0]
            try:
                typ = hdr[4:8].decode("latin1")
            except Exception:
                break
            real = n
            if n == 1:  # taille 64 bits étendue
                ext = f.read(8)
                if len(ext) < 8:
                    break
                real = struct.unpack(">Q", ext)[0]
            elif n == 0:  # jusqu'à la fin du fichier
                real = size - off
            if real <= 0:
                break
            out.append(Atom(typ, off, real))
            off += real
    return out


def atom_presence(path: str) -> dict:
    """Retourne {ftyp, mdat, moov: bool} + le brand ftyp si lisible."""
    atoms = parse_top_level(path)
    types = {a.type for a in atoms}
    brand = None
    for a in atoms:
        if a.type == "ftyp":
            with open(path, "rb") as f:
                f.seek(a.offset + 8)
                brand = f.read(4).decode("latin1", "replace").strip()
            break
    return {
        "ftyp": "ftyp" in types,
        "mdat": "mdat" in types,
        "moov": "moov" in types,
        "brand": brand,
    }


# Clé KLV **propriétaire Sony** identifiée par le Spike 02 (registre privé
# `06 0e 2b 34 02 53 01 01 0c 02` — noter `0c 02` là où un MXF conforme aurait
# `0d 01`). Sa présence, SANS `ftyp`/`moov`, signe un fichier de récupération
# `.rsv` Sony (essence XAVC-I brute, pré-finalisation). Voir docs/spike/spike-02-mxf.md.
SONY_RSV_KLV_KEY = bytes.fromhex("060e2b34025301010c0201")


def is_sony_rsv(path: str, scan_bytes: int = 4 << 20) -> bool:
    """Détecte un `.rsv` Sony : clé KLV privée Sony présente dans l'en-tête ET
    aucun atome ISO-BMFF (`ftyp`). Ne lit que le début du fichier (borné)."""
    try:
        with open(path, "rb") as f:
            head = f.read(scan_bytes)
    except OSError:
        return False
    if SONY_RSV_KLV_KEY not in head:
        return False
    # Un vrai MP4/MXF finalisé ne doit pas être classé .rsv : exiger l'absence de ftyp.
    return not head[4:8] == b"ftyp"
