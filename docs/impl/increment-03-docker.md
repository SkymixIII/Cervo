# Implémentation — INCRÉMENT 3 (packaging Docker)

> Auteur : **DockerManager**. Suite aux incréments 1 (backend) et 2 (frontend),
> tous deux **TERMINÉS**. Périmètre : **packaging/conteneurisation seule**, pas
> de changement fonctionnel côté backend/frontend.
> Statut : **INCRÉMENT 3 TERMINÉ** — `docker compose up` lance tout, UI sur un
> seul port hôte, untrunc+ffmpeg embarqués (pas de docker-in-docker), preuve
> de bout en bout (repair réel + cache-hit) exécutée **dans le conteneur**.

---

## 0. TL;DR

```
docker compose up
```

→ ouvrir **http://localhost:8080**. Un seul port hôte, une seule commande.

Déposer les fichiers à récupérer (source abîmée + référence saine) dans le
dossier `./media` du dépôt (créé, vide, suivi par `.gitkeep`) : ils sont visibles
dans l'UI sous le chemin **`/media/...`** — exactement le placeholder du champ
de saisie (`FileInput.tsx`, ex. `/media/rush_corrompu.rsv`).

`untrunc` **et** `ffmpeg`/`ffprobe` sont **embarqués dans l'image `app`**
(binaire natif, `apt` sur Ubuntu 22.04) : `scripts/untrunc-docker.sh` (wrapper
docker-in-docker transitoire de l'incrément 1) **n'est plus utilisé au runtime**
— conservé dans le dépôt pour référence/dev local hors Docker, mais l'image ne
le monte ni ne l'exécute.

---

## 1. Topologie retenue

**`web` (nginx) + `app` (FastAPI + untrunc + ffmpeg) via `docker compose`**,
plutôt qu'un mono-conteneur — arbitrage explicite (cf. `master-arbitration-02.md`
MAJ-15 : « DockerManager tranchera au packaging »).

| Option | Pour | Contre |
|---|---|---|
| **web+app (retenue)** | 2 images simples et standards (nginx officiel, image Python) ; build/logs/debug séparés ; conforme à la préférence d'architecture (API/worker découplés du process HTTP, `03 §1.7`) | 2 process au lieu d'un |
| mono-conteneur (supervisord) | 1 seul conteneur | supervisor à intégrer/maintenir ; mélange nginx+uvicorn+untrunc dans une seule image, plus dur à déboguer ; aucun gain réel pour un usage mono-utilisateur local |

**Compromis assumé** (explicite, dans l'esprit de MAJ-15) : deux conteneurs,
mais **une seule commande** (`docker compose up`) et **un seul port hôte**
(`web`) — ce qui est l'exigence produit réelle. `app` n'a **aucun port publié**
(`ports:` absent de son service) : il n'est joignable que via le réseau interne
compose (`web` → `http://app:8000`), pour (a) forcer un point d'entrée unique
et (b) éviter tout conflit avec un `uvicorn`/`vite` de dev déjà lancé sur
8000/5173 côté hôte.

---

## 2. Image `app` (`backend/Dockerfile`) — untrunc + ffmpeg embarqués

Build multi-stage, **sans docker-in-docker** :

1. **Stage `untrunc-build`** (`ubuntu:22.04`) : reproduit la recette
   *officielle* `anthwlock/untrunc` (celle déjà utilisée et validée par le
   Spike 01 et les tests de l'incrément 1 — `git clone` + `docker build`, ici
   inlinée) : `apt install libavformat-dev libavcodec-dev libavutil-dev g++
   make git`, `make FF_VER=shared`. Lie untrunc **dynamiquement** contre le
   ffmpeg **système** d'Ubuntu 22.04 (**4.4.2**), qui respecte la contrainte
   Spike 01 (« ffmpeg > 8.1 casse la struct interne `FFCodec` »).
2. **Stage `runtime`** (**même base `ubuntu:22.04`**, volontairement — garantit
   l'ABI des libs partagées entre le binaire untrunc et le ffmpeg/ffprobe du
   reste du pipeline) : Python 3.12 via **deadsnakes PPA** (Ubuntu 22.04 n'a
   nativement que 3.10) + `ffmpeg` (paquet système, **même version 4.4.2** que
   celle liée dans untrunc) + le binaire `untrunc` copié depuis le stage 1.

```
APP_UNTRUNC_CMD=untrunc     # binaire embarqué, plus de wrapper docker
APP_FFMPEG=ffmpeg / APP_FFPROBE=ffprobe   # système, même build que untrunc
APP_MEDIA_ROOT=/media       # bind mount utilisateur (§4)
APP_WORK_ROOT=/data/work    # volume nommé persistant
APP_DB_PATH=/data/app.db    # volume nommé persistant
```

`-rsv-ben` (mode Sony RSV natif, Spike 01) reste câblé côté plugin
(`methods/untrunc_moov.py`, `options={"rsv_ben": True}`) — inchangé, disponible
dès que ce binaire embarqué est appelé avec cette option.

**Taille de l'image** : ~886 MB (Ubuntu 22.04 + ffmpeg complet + toolchain de
build untrunc consommée dans le stage jeté). Non optimisé pour la taille
(mono-utilisateur local, pas de contrainte de distribution) — pourrait être
réduit (image `-slim`/Alpine, purge des paquets `-dev`) dans un incrément
ultérieur si la taille devient un problème.

**Utilisateur** : le conteneur tourne en **root** (compromis assumé, comme le
non-négociable « V1 localhost only, aucune auth » déjà acté §1.5 de
l'incrément 1). Root simplifie l'écriture sur le bind mount `./media` quel que
soit l'UID du host, sans configuration supplémentaire pour un usage local
mono-utilisateur. À revisiter si le produit s'ouvre à un usage multi-utilisateur/
exposé réseau (hors V1).

---

## 3. Image `web` (`frontend/Dockerfile` + `nginx.conf`)

Build multi-stage : `node:22-alpine` → `npm ci && npm run build` (`dist/`) →
servi par `nginx:1.27-alpine`. `nginx.conf` :
- `location /api/` → `proxy_pass http://app:8000/api/` (réseau interne compose,
  résolution DNS par nom de service) ;
- `proxy_buffering off` + `proxy_read_timeout 3600s` : **SSE**
  (`/api/jobs/{id}/events`) et **preview vidéo Range** (`/api/jobs/{id}/preview`)
  traversent un reverse proxy sans buffering — le backend envoie déjà
  `X-Accel-Buffering: no` (`jobs.py`), renforcé ici ;
- `location /` → `try_files $uri /index.html` (SPA).

---

## 4. Données : volumes et bind mount

| Chemin conteneur | Type | Rôle |
|---|---|---|
| `/media` | **bind mount** `./media` (hôte, surchargeable via `MNF_MEDIA_DIR`) | Racine confinée (non-négociable e) où l'utilisateur dépose ses fichiers source + référence. Alignée sur le placeholder UI (`/media/...`). |
| `/data` | **volume nommé** `mnf_data` | `work/` (artefacts réparés cachés, `03` BLOQ-3) + `app.db` (SQLite). Persiste entre `docker compose down`/`up` (pas entre `down -v`). |

Le port hôte est configurable (`MNF_PORT`, défaut `8080`) précisément parce
que des serveurs de dev tournent déjà sur 8000/5173 côté hôte pendant ce tour.

---

## 5. `.dockerignore`, healthcheck, restart, reproductibilité

- **`.dockerignore`** (`backend/`, `frontend/`) : exclut `.venv/`,
  `__pycache__/`, `data/`, `*.db*`, `node_modules/`, `dist/`, `.vite/`.
- **Healthcheck** : `app` interroge `GET /api/health` en Python (pas de
  dépendance `curl` supplémentaire) ; `web` interroge `/` via `wget --spider`
  (busybox, déjà présent dans `nginx:alpine`). `web` démarre après `app`
  **healthy** (`depends_on: condition: service_healthy`).
- **`restart: unless-stopped`** sur les deux services.
- **Build reproductible** : versions figées (`fastapi==0.115.*`,
  `uvicorn==0.32.*`, `pydantic==2.*` du `requirements.txt` existant ; images de
  base `ubuntu:22.04`, `node:22-alpine`, `nginx:1.27-alpine` taguées). Le
  `untrunc` construit dépend de `master` sur `anthwlock/untrunc` (`ARG
  UNTRUNC_REF`, surchageable pour figer un commit précis si besoin de
  reproductibilité stricte dans le temps).

---

## 6. Preuve de bout en bout (exécutée dans ce tour)

```
docker compose build        # ~2 min (untrunc + ffmpeg + python3.12 deadsnakes)
docker compose up -d
docker compose ps           # app: healthy · web: healthy
curl http://localhost:8080/            # 200, index.html (SPA)
curl http://localhost:8080/api/health  # {"data":{"status":"ok"},...} via proxy nginx -> app
```

**Binaires embarqués confirmés dans le conteneur `app`** (pas de docker-in-docker) :
```
$ docker compose exec app which untrunc ffmpeg ffprobe python
/usr/local/bin/untrunc  /usr/bin/ffmpeg  /usr/bin/ffprobe  /opt/venv/bin/python
$ docker compose exec app untrunc -V
version 'v1-a87f33a' using ffmpeg '4.4.2-0ubuntu0.22.04.1' Lavc58.134.100
```

**Suite `tests/e2e.py` du dépôt, réexécutée telle quelle DANS le conteneur**
(réutilise `tests/gen_fixtures.py` : génère un MP4 H.264 synthétique, tronque
le `moov`, prouve repair réel puis cache-hit — cf. incrément 1 §2) :
```
$ docker compose exec app python -m tests.e2e
...
[PASS] job1 succeeded ; repair_cache_hit=False (repair réel)      0.21s
[PASS] preview job1 décodable (ffprobe)
[PASS] job2 succeeded ; repair_cache_hit=True (REPAIR SAUTÉ)       0.21s
[PASS] SSE: events reçus
[PASS] extend: succeeded + cache hit
TOUS LES TESTS PASSENT ✅  (19/19)
```

**`tests/test_cancel.py`** (non-négociable d, annulation propre) rejouée dans
le même conteneur :
```
$ docker compose exec app python -m tests.test_cancel
[PASS] annulation en 0.57s, enfant pid=214 bien tué
test_cancel OK ✅
```

**Bind mount utilisateur** vérifié (fichier déposé côté hôte dans `./media`,
visible sous `/media` dans le conteneur) :
```
$ echo test > media/hello.txt && docker compose exec app ls /media
.gitkeep  hello.txt
```

Ce que ceci prouve : l'image `app` seule, sans aucun accès au démon Docker de
l'hôte, réalise un repair untrunc réel + cache-hit + annulation propre — le
pipeline complet de l'incrément 1 fonctionne à l'identique une fois untrunc
embarqué (vs. le wrapper `scripts/untrunc-docker.sh` utilisé pendant le
développement).

---

## 7. Ce qui reste / limites connues

- **Taille image `app` non optimisée** (~886 MB) — acceptable en usage local,
  optimisable plus tard (multi-stage plus agressif, purge `-dev`, base plus
  légère).
- **Root dans le conteneur `app`** (compromis assumé §2) — à revisiter hors V1
  localhost-only.
- **`UNTRUNC_REF=master`** par défaut (non figé sur un commit/tag) — à figer si
  une reproductibilité stricte dans le temps devient un besoin produit.
- **Pas de TLS/auth** (inchangé depuis l'incrément 1 — V1 localhost only).
- **`scripts/untrunc-docker.sh`** conservé dans le dépôt (utile en dev local
  hors Docker complet, cf. `backend/README.md`) mais **non référencé** par
  l'image ni par `docker-compose.yml`.

---

**CONTENEURISATION TERMINÉE.** `docker compose up` → UI sur
`http://localhost:8080` (port unique) ; untrunc+ffmpeg embarqués (pas de
docker-in-docker) ; preuve de bout en bout (repair réel + cache-hit +
annulation) exécutée et vérifiée **dans le conteneur**.
