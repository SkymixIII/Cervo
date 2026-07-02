# MediaNotFound — Backend / moteur (Incrément 1)

Backend Python 3.12 + FastAPI + SQLite + file in-process (`ProcessPoolExecutor`).
Implémente le pipeline validé par le Spike 01 : **analyze → repair (untrunc, UNE
fois, caché) → slice `-c copy`**. Voir `docs/impl/increment-01.md`.

> Périmètre : **moteur/API uniquement** (pas de frontend). Méthode : `untrunc-moov`.

## Prérequis
- `ffmpeg` / `ffprobe` locaux (probe + slice ; toute version récente convient).
- Image Docker `untrunc` (méthode phare). Build depuis `anthwlock/untrunc` :
  ```
  git clone --depth 1 https://github.com/anthwlock/untrunc && cd untrunc
  docker build -t untrunc .
  ```
  (contrainte ffmpeg ≤ 8.0 dans l'image untrunc — cf. Spike 01 / arbitrage #2 §8.5).

## Installation
```
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Configuration (variables d'environnement)
| Var | Défaut | Rôle |
|-----|--------|------|
| `APP_MEDIA_ROOT` | `data/media` | racine confinée des sources/références (non-négociable e) |
| `APP_WORK_ROOT` | `data/work` | artefacts réparés (cache) + tranches + temporaires |
| `APP_DB_PATH` | `data/app.db` | SQLite (métadonnées + état jobs) |
| `APP_WORKERS` | `2` | taille du pool de process |
| `APP_FFMPEG` / `APP_FFPROBE` | `ffmpeg` / `ffprobe` | binaires média |
| `APP_UNTRUNC_CMD` | `untrunc` | commande untrunc (binaire ou wrapper docker) |

Pour untrunc via Docker, pointer vers le wrapper (monte les racines à l'identique) :
```
export APP_UNTRUNC_CMD="$(git rev-parse --show-toplevel)/scripts/untrunc-docker.sh"
```

## Lancer l'API (localhost only, aucune auth — V1)
```
cd backend
APP_UNTRUNC_CMD=... .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```
OpenAPI auto : `http://127.0.0.1:8000/docs`.

## Tests
```
cd backend
# 1) preuve d'annulation propre (non-négociable d)
.venv/bin/python -m tests.test_cancel
# 2) end-to-end : repair réel puis CACHE HIT (nécessite l'image docker untrunc)
export APP_UNTRUNC_CMD="$(cd .. && pwd)/scripts/untrunc-docker.sh"
.venv/bin/python -m tests.e2e
```
