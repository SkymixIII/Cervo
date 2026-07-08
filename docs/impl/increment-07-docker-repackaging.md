# Incrément 7 — Repackaging Docker (MP4Box, disques utilisateur, work root externe)

> Auteur : **DockerManager**. Mise à jour du packaging Docker (incrément 3) pour suivre
> le code applicatif actuel (`sony-rsv-rebuild`, navigateur de fichiers) et couvrir un
> vrai poste utilisateur : parcourir ses disques depuis l'UI, écrire les artefacts de
> repair sur un disque externe (le disque interne est trop petit), et une dépendance
> binaire supplémentaire (MP4Box/GPAC, incrément 5).
> Statut : ✅ **TERMINÉ — validé end-to-end dans le conteneur**, y compris **un bug
> bloquant découvert et corrigé pendant ce tour** (§4).

---

## 0. TL;DR

```
docker compose up
```

→ ouvrir **http://localhost:8080** (port unique, configurable via `MNF_PORT`).

Depuis l'UI, bouton **« Parcourir… »** : les disques montés sous `/media` sont listés
(`Volumes/` = disques externes macOS dont `TOM`, `home/` = `$HOME`). Choisir un `.rsv`,
lancer la récupération.

**Nouveau ce tour** : `gpac` (MP4Box) embarqué, disques utilisateur montés en lecture
seule, dossier de travail (`APP_WORK_ROOT`) déplaçable sur un disque externe, **et un
fix critique** — l'image contient désormais **deux ffmpeg** (§4) car le ffmpeg système
Ubuntu 22.04 (4.4.2, requis pour l'ABI d'`untrunc`) ne sait pas écrire de PCM 24-bit
dans un conteneur MP4.

---

## 1. Disques utilisateur — navigateur de fichiers (`/api/browse`, incrément 06)

`APP_MEDIA_ROOT=/media` (fixé dans `backend/Dockerfile`). `docker-compose.yml` monte
**sous** cette racine :

| Host | Conteneur | Mode | Contenu |
|---|---|---|---|
| `${MNF_VOLUMES_DIR:-/Volumes}` | `/media/Volumes` | **ro** | disques externes macOS (dont `TOM`) |
| `${HOME}` | `/media/home` | **ro** | dossier utilisateur |

Lecture seule : le navigateur (`GET /api/browse`) ne fait **que lister/lire** —
confirmé (`touch` dans le conteneur → `Read-only file system`, testé sur les deux
mounts). L'UI affiche donc `Volumes/` et `home/` à la racine, exactement le layout que
`/api/browse` restitue (confinement `security.confine_dir`, inchangé).

### ⚠️ macOS + Docker Desktop : partage de fichiers `/Volumes`

`/Volumes` n'est **pas** partagé par défaut. Sans partage activé, le mount démarre
(pas d'erreur) mais reste **vide** côté conteneur.

**Procédure** : Docker Desktop → **Settings → Resources → File Sharing** → **+** →
ajouter `/Volumes` (ou le point de montage exact du disque, ex. `/Volumes/TOM`) →
**Apply & restart**.

**Test de vérification** (à refaire après tout changement de partage) :
```
docker compose exec app ls -la /media/Volumes
```
Doit lister vos disques externes montés (pas juste vide/`Macintosh HD`). **Vérifié ce
tour** : après ajout du partage, `TOM` apparaît et est listable/lisible
(`ls /media/Volumes/TOM` → contenu réel du disque, dont le `.rsv` de 70 Go du Spike 02).

`$HOME` est partagé par défaut par Docker Desktop (pas d'action requise).

---

## 2. Dossier de travail externe (`APP_WORK_ROOT`)

La récupération écrit un artefact réparé caché **≈2× la taille de la source** (jusqu'à
~140 Go pour 70 Go, cf. Spike 02/incrément 5 §6) + les tranches. Le disque interne peut
être trop petit.

`docker-compose.yml` :
```yaml
- ${MNF_WORK_DIR:-/Volumes/TOM/mnf_work}:/work
environment:
  APP_WORK_ROOT: /work
```

- **Lecture-écriture** (contrairement aux mounts média §1) : c'est là que vivent les
  artefacts réparés + tranches + temporaires (`ctx.tmp_dir`).
- **Configurable** via `MNF_WORK_DIR` — le défaut (`/Volumes/TOM/mnf_work`) est
  **spécifique à ce poste** (le disque externe `TOM` du Spike 02). **Changez cette
  variable** (ou exportez `MNF_WORK_DIR=...` avant `docker compose up`) si votre disque
  de travail a un autre nom/chemin, ou si `TOM` n'est pas monté — sinon Docker créera
  (ou échouera à créer, selon le partage Docker Desktop) un chemin qui n'existe pas.
- Le dossier hôte est créé s'il n'existe pas encore (`mkdir -p` fait avant le premier
  `docker compose up`, cf. §6 — Docker ne le crée pas toujours de façon fiable côté
  macOS/virtiofs).
- La base SQLite (`APP_DB_PATH=/data/app.db`, petite) reste sur le **volume nommé**
  `mnf_data` (disque interne, persiste entre `down`/`up`, pas entre `down -v`) — pas de
  raison de la déplacer sur l'externe.

---

## 3. MP4Box (GPAC) — mode Long-GOP de `sony-rsv-rebuild`

Ajouté au stage runtime (`backend/Dockerfile`) : paquet APT `gpac` (Ubuntu 22.04,
GPAC 2.0). `APP_MP4BOX=MP4Box` (déjà supporté par `Config`, incrément 5) — sur le
`PATH`, aucune configuration supplémentaire.

```
$ docker compose exec app which MP4Box
/usr/bin/MP4Box
$ docker compose exec app MP4Box -version
MP4Box - GPAC version 2.0-rev2.0.0+dfsg1-2
```

Aucune contrainte d'ABI/version : MP4Box réordonnance les B-frames (`ctts` via POC)
sans toucher au binaire H.264 — pas de couplage avec untrunc/ffmpeg.

---

## 4. ⚠️ Bug bloquant découvert + corrigé : deux `ffmpeg` dans l'image

### 4.1 Le problème (constaté en testant un vrai job dans le conteneur, §6)

Premier test end-to-end (`gop_mode=auto`, `media_scope=both`, fixture réelle) :
**échec** à 96 % —
```
ffmpeg a échoué (code 1): [mp4 @ ...] Could not find tag for codec pcm_s24be in
stream #1, codec not currently supported in container
Could not write header for output file #0 (incorrect codec parameters ?)
```

**Cause identifiée** : `sony-rsv-rebuild` (`_mux_all_intra` et `_mux_long_gop`) muxe
l'audio 4× PCM 24-bit (`pcm_s24be`) directement dans un conteneur **MP4** en `-c copy`
(sans réencoder — correct, c'est le format natif Sony). Or le **ffmpeg système Ubuntu
22.04 embarqué (4.4.2)** ne sait **pas** écrire le tag `ipcm`/`fpcm` (PCM non compressé
dans ISOBMFF, Amendment 2) dans le muxer **`mp4`** strict — ce support n'existe dans
ffmpeg que depuis **~7.1**. (Le muxer `mov`, plus permissif, accepte bien le tag legacy
`in24` même en 4.4.2 — testé, mais ce n'est **pas** la sortie voulue : on veut un vrai
`.mp4` avec le tag `ipcm` standard, identique à la sortie native Sony.)

Cette version 4.4.2 est **volontairement pinnée** dans l'image (incrément 3) pour
garantir l'ABI des libs partagées (`libavformat.so.58` etc.) dont dépend le binaire
`untrunc` compilé au stage 1 (`FF_VER=shared`, lié dynamiquement contre ces libs).
**En dev natif macOS (Homebrew, ffmpeg 8.0.1, cf. Spike 02), ce bug n'apparaît pas** —
d'où le fait qu'il soit passé inaperçu jusqu'à ce tour de conteneurisation.

### 4.2 Le fix — deux `ffmpeg` distincts, séparation stricte des rôles

```
┌─────────────────────────────────────────────────────────────┐
│ ffmpeg APT (Ubuntu 22.04, 4.4.2)  → /usr/bin/ffmpeg           │
│   Rôle UNIQUE : fournir les .so runtime (libavformat58,       │
│   libavcodec58, libavutil56) dont untrunc dépend au chargement│
│   dynamique. Son binaire ffmpeg/ffprobe CLI n'est PLUS invoqué│
│   par l'app.                                                  │
├─────────────────────────────────────────────────────────────┤
│ ffmpeg RÉCENT statique (BtbN/FFmpeg-Builds, n7.1, GPL)         │
│   → /usr/local/lib/ffmpeg-recent/{ffmpeg,ffprobe}              │
│   APP_FFMPEG / APP_FFPROBE pointent ICI. Utilisé pour TOUT le │
│   pipeline (probe, slice -c copy, mux sony-rsv-rebuild).      │
│   Binaire STATIQUE (aucune .so partagée) → zéro couplage ABI  │
│   avec untrunc, donc aucun conflit avec la contrainte          │
│   "ffmpeg <= 8.0" (qui ne concerne QUE le ffmpeg utilisé pour  │
│   LIER untrunc, stage 1 — inchangé).                          │
└─────────────────────────────────────────────────────────────┘
```

Nouveau stage `ffmpeg-recent` dans `backend/Dockerfile` : télécharge le build statique
GPL **n7.1** (pinné, pas `master-latest`, pour la reproductibilité) depuis
`BtbN/FFmpeg-Builds`, sélection d'architecture via `TARGETARCH` (`linux64`/`linuxarm64`
— couvre Apple Silicon **et** Intel/amd64). Binaires copiés dans le stage runtime sous
un chemin dédié (`/usr/local/lib/ffmpeg-recent/`, jamais nommés `ffmpeg`/`ffprobe` seuls
sur le `PATH`) pour ne jamais pouvoir être confondus avec le ffmpeg APT.

`untrunc` (`APP_UNTRUNC_CMD=untrunc`) est **inchangé** : il ne consulte pas
`APP_FFMPEG`, continue de charger ses `.so` via le linker dynamique standard (fournies
par le paquet APT `ffmpeg`, toujours installé pour cette seule raison).

### 4.3 Preuve (re-test après fix)

```
$ docker compose exec app /usr/local/lib/ffmpeg-recent/ffmpeg -version | head -1
ffmpeg version n7.1.5-1-g7d0e842004-20260708 ...
$ docker compose exec app untrunc -V
version 'v1-a87f33a' using ffmpeg '4.4.2-0ubuntu0.22.04.1' Lavc58.134.100   # inchangé
```

Job relancé (`gop_mode=auto`, `media_scope=both`, même fixture) : **succeeded**, preview
vérifiée (`ffprobe`) :
```
codec_name=h264   width=3840  height=2160                    # vidéo
codec_name=pcm_s24be   sample_rate=48000   channels=4         # audio, 4 canaux PCM
```
Décodage intégral (`ffmpeg -i preview.mp4 -f null -`) : **425 frames, 0 erreur**.

---

## 5. Un seul port hôte — inchangé (incrément 3)

Topologie `web` (nginx, seul port publié) + `app` (backend, réseau interne compose
uniquement) inchangée depuis l'incrément 3 — voir `docs/impl/increment-03-docker.md`
§1 pour l'arbitrage complet. `frontend/Dockerfile`, `nginx.conf`, les deux
`.dockerignore` ont été **recréés à l'identique** (supprimés du répertoire de travail
avant ce tour, contenu retrouvé via `git show HEAD:...` et reconstitué).

---

## 6. Preuve de bout en bout (exécutée ce tour)

```
docker compose build       # untrunc (stage 1) + ffmpeg-recent (nouveau stage) + runtime
docker compose up -d
docker compose ps          # app: healthy · web: healthy
curl http://localhost:8080/            # 200 (SPA)
curl http://localhost:8080/api/health  # {"data":{"status":"ok"}} via proxy nginx -> app
```

**Disques utilisateur** :
```
$ docker compose exec app ls /media
Volumes  home
$ docker compose exec app ls /media/Volumes         # AVEC partage Docker Desktop activé
Macintosh HD  TOM
$ docker compose exec app ls /media/Volumes/TOM | head -5
C4934.RSV  CalculScientifique  JdH  ...              # le vrai fichier 70 Go du Spike 02
$ curl -sS http://localhost:8080/api/browse?path=Volumes   # via l'API, identique
```
**Lecture seule confirmée** : `touch` sur `/media/Volumes/...` et `/media/home/...` →
`Read-only file system`.

**Binaires embarqués** :
```
$ docker compose exec app sh -c "which untrunc ffmpeg ffprobe MP4Box python"
/usr/local/bin/untrunc  /usr/bin/ffmpeg  /usr/bin/ffprobe  /usr/bin/MP4Box  /opt/venv/bin/python
```
(`ffmpeg`/`ffprobe` APT listés par `which` sont ceux dont seules les `.so` servent —
l'app utilise `/usr/local/lib/ffmpeg-recent/*` via `APP_FFMPEG`/`APP_FFPROBE`, §4.)

**Récupération réelle, à travers le conteneur, fixture 300 Mo** (segment du vrai
`C4934.RSV`, référence = vraie `C4935.MP4` — les deux via les mounts §1, **aucune
copie du fichier 70 Go**) :
```
POST /api/media {path: home/.../backend/data/fixtures/C4934_test.rsv}
  → analyze → {container: sony-rsv, codec: xavc-i, recoverable: true}
POST /api/references {path: home/Downloads/C4935.MP4}
POST /api/jobs {source_id, reference_id, method_id: auto, media_scope: both,
                slice: {kind: 1min}, gop_mode: auto}
  → [1er essai, AVANT fix §4] failed (JOB_FAILED, pcm_s24be/mp4)
  → [après fix §4]            succeeded, has_preview: true
GET /api/jobs/{id}/preview → h264 3840x2160 + pcm_s24be×4@48kHz, 425 frames, 0 erreur décodeur
```

**I/O sur le vrai fichier 70 Go via le bind mount `/Volumes`** (lecture séquentielle,
2 Go, offset 40 Go pour limiter le biais de cache) :
```
Conteneur (via /media/Volumes/TOM) : 992 MB/s
Hôte natif (via /Volumes/TOM directement) : 972 MB/s
```
**Quasi aucun surcoût mesuré** du bind mount sur cette machine — voir §7 pour les
réserves (disque externe rapide, pas représentatif de tout matériel).

---

## 7. Honnêteté sur la perf des bind-mounts macOS (à ne pas surinterpréter)

- Le disque externe utilisé pour la mesure (`TOM`) est **rapide** (~1 GB/s en lecture
  séquentielle, probablement SSD/Thunderbolt) : le bind mount Docker Desktop
  (virtiofs) n'a montré **aucun ralentissement significatif** dans ce test précis.
  **Ceci n'est PAS une garantie générale** : un disque USB/HDD plus lent, ou un accès
  **aléatoire** (vs. séquentiel testé ici) donnerait des résultats différents — la
  récupération `sony-rsv-rebuild` fait un scan quasi-séquentiel de l'essence, donc le
  cas testé est représentatif du **pattern d'accès réel**, mais pas de tout matériel.
- **Non testé** : le débit en **écriture** sur `/work` (le poste de travail réel, sur
  `TOM`, encaisse l'essentiel de l'I/O d'un job de repair complet — artefact ≈2× la
  source). À mesurer lors du **prochain run réel 70 Go** (cf. incrément 5 §6, "Master
  relancera la récupération 70 Go complète").
- **Le mode dev natif (hors Docker, `uvicorn` direct, cf. `backend/README.md`) reste
  une option valide** pour le plus gros job si le bind mount virtiofs s'avère être un
  goulot d'étranglement en conditions réelles (I/O soutenue sur des dizaines de Go,
  pas juste 2 Go de test) — pas de round-trip supplémentaire dans ce cas (accès disque
  direct, sans couche de virtualisation Docker Desktop).

---

## 8. Fichiers touchés

| Fichier | Changement |
|---|---|
| `backend/Dockerfile` | recréé (supprimé avant ce tour) + `gpac` + nouveau stage `ffmpeg-recent` (ffmpeg/ffprobe statiques n7.1) + `APP_FFMPEG`/`APP_FFPROBE` repointés |
| `backend/.dockerignore` | recréé à l'identique |
| `frontend/Dockerfile`, `frontend/nginx.conf`, `frontend/.dockerignore` | recréés à l'identique |
| `docker-compose.yml` | mounts `/Volumes`→`/media/Volumes:ro`, `$HOME`→`/media/home:ro` ; `MNF_WORK_DIR`→`/work` (`APP_WORK_ROOT`) ; suppression du mount `./media` (superseded) |
| `.gitignore` | `/data/` (racine data/ par défaut hors Docker) ; commentaire `/media/*` mis à jour |
| `backend/data/fixtures/C4934_test.rsv` | fixture de test (300 Mo, segment du vrai `.rsv`) — **gitignoré** (`backend/.gitignore` : `data/`) |

---

## 9. Ce qui reste / limites connues

- **`MNF_WORK_DIR` par défaut spécifique à ce poste** (`/Volumes/TOM/mnf_work`) — à
  changer via variable d'env sur toute autre machine.
- **`MNF_VOLUMES_DIR`/partage Docker Desktop** : dépendance à une étape **manuelle**
  (Settings → File Sharing) non automatisable depuis `docker compose` — documentée
  §1, mais un nouvel utilisateur doit la faire une fois.
- **I/O écriture sur `/work` non mesurée** à l'échelle réelle (§7) — à faire lors du
  run 70 Go complet.
- **`ffmpeg-recent` non pinné à un digest** (tag `latest` de la release GitHub BtbN,
  filtré sur `n7.1` mais le fichier `.tar.xz` peut être republié) — acceptable pour un
  usage local mono-utilisateur, à figer (checksum, ou mirror local) si une
  reproductibilité stricte devient un besoin.
- Limites héritées de l'incrément 3 (image `app` non optimisée en taille, root dans le
  conteneur, pas de TLS/auth — V1 localhost only) : inchangées.

---

**REPACKAGING DOCKER TERMINÉ.** `docker compose up` → UI sur `http://localhost:8080`
(port unique) ; disques utilisateur (`/Volumes`, `$HOME`) montés en lecture seule sous
`/media` (navigateur de fichiers fonctionnel, testé sur le vrai disque `TOM`) ; dossier
de travail déplaçable sur disque externe (`MNF_WORK_DIR`/`APP_WORK_ROOT`) ; MP4Box/GPAC
embarqué ; **bug bloquant ffmpeg 4.4.2/PCM-MP4 découvert et corrigé** (second ffmpeg
statique n7.1, aucun couplage ABI avec untrunc) ; récupération réelle (vidéo + audio 4
canaux, 425 frames, 0 erreur) validée de bout en bout **dans le conteneur**.
