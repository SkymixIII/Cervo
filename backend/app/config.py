"""Configuration centrale de l'application.

Toutes les valeurs sont pilotables par variables d'environnement (préfixe `APP_`)
pour rester conteneurisable (DockerManager). La `Config` est un dataclass
*picklable* : elle est passée telle quelle aux processus worker du
`ProcessPoolExecutor` (via `to_dict`/`from_dict`), sans dépendance à FastAPI.
"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, asdict
from pathlib import Path


def _default_root() -> Path:
    # backend/app/config.py -> racine repo = parents[2]
    return Path(__file__).resolve().parents[2] / "data"


@dataclass(frozen=True)
class Config:
    # Racine des médias utilisateur (sources + références). Tout chemin fourni
    # par l'API DOIT être confiné sous cette racine (non-négociable e).
    media_root: str
    # Racine de travail : artefacts réparés (cache) + tranches + temporaires.
    work_root: str
    # Fichier SQLite (métadonnées + état des jobs).
    db_path: str
    # Taille du pool de process worker.
    workers: int
    # Binaires média. ffmpeg/ffprobe locaux (>= n'importe quelle version pour
    # probe/slice) ; untrunc encapsulé (peut être un wrapper docker) — voir
    # methods/untrunc_moov.py. `untrunc_cmd` est une ligne shell (shlex).
    ffmpeg: str
    ffprobe: str
    untrunc_cmd: str
    # Paramètres du hash de cache non-intégral (non-négociable c).
    hash_sample_count: int
    hash_sample_bytes: int

    @staticmethod
    def from_env() -> "Config":
        root = _default_root()
        media_root = os.environ.get("APP_MEDIA_ROOT", str(root / "media"))
        work_root = os.environ.get("APP_WORK_ROOT", str(root / "work"))
        db_path = os.environ.get("APP_DB_PATH", str(root / "app.db"))
        cfg = Config(
            media_root=str(Path(media_root).resolve()),
            work_root=str(Path(work_root).resolve()),
            db_path=str(Path(db_path).resolve()),
            workers=int(os.environ.get("APP_WORKERS", "2")),
            ffmpeg=os.environ.get("APP_FFMPEG", "ffmpeg"),
            ffprobe=os.environ.get("APP_FFPROBE", "ffprobe"),
            untrunc_cmd=os.environ.get("APP_UNTRUNC_CMD", "untrunc"),
            hash_sample_count=int(os.environ.get("APP_HASH_SAMPLES", "4")),
            hash_sample_bytes=int(os.environ.get("APP_HASH_SAMPLE_BYTES", str(1 << 20))),
        )
        return cfg

    def ensure_dirs(self) -> None:
        for p in (self.media_root, self.work_root, str(Path(self.db_path).parent)):
            Path(p).mkdir(parents=True, exist_ok=True)

    @property
    def untrunc_argv0(self) -> list[str]:
        return shlex.split(self.untrunc_cmd)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Config":
        return Config(**d)
