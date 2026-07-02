"""Hash de cache NON intégral (non-négociable c).

Un SHA-256 intégral sur un rush de 30-80 Go coûterait des minutes à chaque
enregistrement → un « cache hit » deviendrait aussi cher que le repair. On calcule
donc une empreinte O(1) vis-à-vis de la taille : `taille + N échantillons` répartis
sur le fichier. Calculé UNE fois à l'enregistrement (`POST /api/media` /
`/api/references`) et stocké dans le Media Registry.

Compromis assumé : ce n'est pas une empreinte cryptographique de tout le contenu ;
deux fichiers identiques sur taille + échantillons seraient considérés égaux. Pour
notre usage (clé de cache d'un artefact réparé, poste local mono-utilisateur) c'est
suffisant et volontairement rapide.
"""
from __future__ import annotations

import hashlib
import os


def cache_hash(path: str, sample_count: int = 4, sample_bytes: int = 1 << 20) -> str:
    size = os.path.getsize(path)
    h = hashlib.sha256()
    h.update(str(size).encode())
    h.update(b"|")

    with open(path, "rb") as f:
        if size <= sample_count * sample_bytes:
            # Petit fichier : on lit tout, c'est déjà bon marché.
            h.update(f.read())
        else:
            # N échantillons répartis uniformément (début, milieux, fin).
            step = size // sample_count
            for i in range(sample_count):
                off = min(i * step, max(0, size - sample_bytes))
                f.seek(off)
                h.update(f.read(sample_bytes))
            # Toujours inclure la toute fin (souvent là où un .rsv diffère).
            f.seek(max(0, size - sample_bytes))
            h.update(f.read(sample_bytes))

    return h.hexdigest()[:32]
