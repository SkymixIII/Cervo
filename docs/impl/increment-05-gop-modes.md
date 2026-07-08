# Incrément 5 — FIX saccade Long-GOP + mode GOP sélectionnable (`sony-rsv-rebuild`)

> Auteur : **Builder**. Corrige la **saccade** du `.rsv` Sony récupéré et ajoute un
> **choix de mode GOP** (`auto` / `all-intra` / `long-gop`) de bout en bout (API + UI).
> Statut : ✅ **TERMINÉ — validé end-to-end à travers l'app** (les 3 modes, port 8080).

---

## 0. Le vrai problème (diagnostic Master)

Le `.rsv` du PXW-Z200 n'est **pas All-Intra** comme le supposait le Spike 02 : c'est du
**Long-GOP (XAVC-L)**. Mesuré sur l'essence et sur la **référence saine** `C4935.MP4` :

| Fait mesuré | Valeur |
|---|---|
| `has_b_frames` (référence + récupéré) | **1** |
| Profil H.264 | **High 4:2:2** (≠ « …Intra ») |
| Pattern GOP (ordre d'affichage) | `B B I B B P B B P B B P B B I …` |
| Répartition (segment 300 Mo) | **36 I / 107 P / 284 B** (427 frames) |

La récupération de l'Incrément 4 **carve** correctement les slices (elles sont bonnes),
mais le **mux** cassait le **timing des B-frames** :

- l'essence H.264 est stockée en **ordre de décodage** (`I B B P …`) ;
- le mux `ffmpeg -r fps -f h264 -c copy` **fige `PTS = DTS` en ordre de décodage** →
  les images s'affichent **dans l'ordre de décodage** au lieu de l'ordre d'affichage
  ⇒ **saccade** ; DTS troués / non-monotones (`… B 0.00, B 0.04, B 0.12 [saut 0.08] …`).
- L'avertissement muxer *« non monotonically increasing DTS »* vu à l'Incrément 4
  **n'était donc PAS cosmétique** — c'était la saccade.

La **référence saine** a, elle, `PTS ≠ DTS` (offsets de composition `ctts`) : DTS
uniforme monotone en ordre de décodage + PTS en ordre d'affichage.

## 1. La correction — réordonner les B-frames SANS réencoder (MP4Box)

Réencoder est **exclu** (dégraderait le 10-bit 4:2:2). La reconstruction des
`PTS/DTS` corrects depuis un **H.264 Annex-B brut** (sans timestamps) n'est **pas**
faisable en `ffmpeg -c copy` : le démuxeur brut sort `PTS = DTS` en ordre de décodage
et `-c copy` ne peut pas réordonner.

**Solution : MP4Box (GPAC)** — à l'import d'un H.264 brut, il calcule les **offsets de
composition (`ctts`) depuis le POC** des slices → `PTS` réordonné (affichage) + `DTS`
uniforme monotone (décodage), **sans toucher aux slices** (lossless).

```
video.h264 (Annex-B, ordre décodage)
   │  MP4Box -quiet -add video.h264:fps=25 -new video_reordered.mp4   ← réordonne B (ctts/POC)
   ▼
video_reordered.mp4 (PTS≠DTS, DTS monotone)   +   audio.pcm (4ch s24be)
   │  ffmpeg -i video_reordered.mp4 -f s24be … -i audio.pcm -map -c copy   ← garde les timestamps
   ▼
repaired.mp4 (vidéo réordonnée + audio, fluide)
```

Preuve (segment 300 Mo, sortie MP4Box) — **identique à la référence** :

```
MP4Box : "OpenGOP detected", "stream CTS offset: 2 frames", 144 IDR
packets (affichage) : dts 0.080 pts -0.040 (K) | dts 0.000 pts 0.000 | dts 0.040 pts 0.040 | dts 0.200 pts 0.080 …
```

### 1.a Démarrage sur la 1re intra (drop des orphelines)
Le carve n'émet le flux qu'à partir de la **1re frame intra** (`_frame_slice_kind == "I"`,
IDR ou I) : toute **B/P orpheline de tête** (qui référencerait une ancre absente) est
droppée. Sur ce fichier, le flux démarre déjà sur l'**IDR** (rien n'est droppé), mais la
garde est en place pour les bords de carve.

### 1.b Sync audio
Inchangée (verrou frame-par-frame de l'Incrément 4) : l'audio PCM est muxé en `-c copy`
sur la vidéo **déjà réordonnée**, en conservant ses timestamps.

## 2. Mode GOP sélectionnable (`auto` / `all-intra` / `long-gop`)

- **`auto` (défaut)** : détecte depuis l'essence via le **`slice_type`** des slice headers.
  Présence de **P/B** ⇒ `long-gop` ; sinon ⇒ `all-intra`. (NAL type 5 = IDR ⇒ I sans
  parsing ; type 1 ⇒ Exp-Golomb `first_mb_in_slice`, `slice_type`, `%5` → I/P/B.)
- **`long-gop`** : chemin MP4Box + ffmpeg (ci-dessus).
- **`all-intra`** : chemin ffmpeg direct (`-r fps -f h264 -c copy`) — chaque frame est une
  I autonome, `PTS = DTS` **correct**, pas de réordonnancement.

Le mode voyage : **API** (`POST /api/jobs {gop_mode}`) → job (colonne `jobs.gop_mode`) →
`options["gop_mode"]` → `RepairContext.options` → méthode. **`extend`** propage le mode du
parent. **Frontend** : sélecteur *Structure GOP* (Auto / Long-GOP / All-Intra), visible
uniquement pour les `.rsv` Sony, à côté du périmètre média.

### 2.a Cache : le mode fait partie de la clé
Un mode GOP différent = un artefact de repair différent. Le mode est ajouté comme
**`variant`** à la clé/chemin de cache (repair **et** tranche) :
`repaired/<src>/<method>/<ref>/<gop_mode>/repaired.mp4`. Deux modes ne se recouvrent
donc **jamais** dans le cache. (Seules les méthodes déclarant `gop_modes` dans leurs
`capabilities` reçoivent un `variant` → untrunc reste inchangé.)

## 3. Preuve end-to-end (à travers l'app, port 8080)

Fixtures (aucun fichier de 70 Go déplacé) : `C4934_test.rsv` (300 Mo, lecture seule) +
référence `C4935_ref.mp4` sous la racine média. `POST /api/media → analyze → references
→ jobs {gop_mode} → preview`, un job **par mode**.

| Mode | frames | DTS (ordre décodage) | 1er paquet | `PTS≠DTS` (réordre B) | décodage |
|---|---|---|---|---|---|
| **auto** (→ long-gop détecté) | 427 | **uniforme 0.04, monotone, [-0.04 … 17.0], 0 trou** | **I (K)** | **oui** | **0 erreur** |
| **long-gop** (forcé) | 427 | **uniforme 0.04, monotone, 0 trou** | **I (K)** | **oui** | **0 erreur** |
| **all-intra** (forcé, mauvais mode ici) | 427 | figé PTS=DTS | I | non | *warning DTS* (attendu) |

- `auto` **détecte long-gop** correctement (P/B présents).
- Streams : `h264` (yuv422p10le) + `pcm_s24be` **4 canaux** 48 kHz.
- Contenu réel confirmé : image 4K cohérente + **audio réel** (peak ≈ **−3 dB**,
  mean ≈ −34 dB — pas du silence).
- `gop_mode=bogus` → **400 `VALIDATION_ERROR`**.
- Cache : dossiers `auto/`, `long-gop/`, `all-intra/` **séparés** (repair + slices).
- Forcer `all-intra` sur ce flux Long-GOP **reproduit la saccade** (PTS=DTS) : c'est le
  mode inadapté au contenu, ce qui **justifie** l'existence du mode Long-GOP.

## 4. Dépendance : GPAC / MP4Box (⚠️ DockerManager)

- Nouveau binaire requis : **MP4Box** (paquet **`gpac`**). Configurable via
  `APP_MP4BOX` (défaut `MP4Box`), exposé dans `Config.mp4box`.
- **DockerManager** : **ajouter `gpac` à l'image** de l'`app`/worker (les process du
  `ProcessPoolExecutor` doivent trouver `MP4Box` sur le `PATH`). Installé en local via
  `brew install gpac`.
- Utilisé **uniquement** en mode `long-gop` (le mode `all-intra` n'appelle que ffmpeg).

## 5. Fichiers touchés

| Zone | Fichier | Changement |
|---|---|---|
| Méthode | `backend/app/methods/sony_rsv_rebuild.py` | détection `slice_type`, démarrage sur intra, split `_mux_all_intra` / `_mux_long_gop` (MP4Box) |
| Config | `backend/app/config.py` | `mp4box` (`APP_MP4BOX`) |
| API | `backend/app/api/jobs.py` | `gop_mode` (validation, création, `extend`, projection) |
| Jobs | `backend/app/store/job_manager.py` | colonne `gop_mode` → `options` ; clé cache avec `variant` |
| DB | `backend/app/db.py` | colonne `jobs.gop_mode` + **migration idempotente** |
| Cache | `backend/app/pipeline/{pipeline,cache,slice}.py` | dimension `variant` (repair + tranche) |
| Tests | `backend/tests/test_sony_rsv.py` | détection `slice_type` / `_frame_slice_kind` |
| Frontend | `App.tsx`, `Selectors.tsx`, `hooks/useRecovery.ts`, `api/{types,client}.ts`, `labels.ts` | sélecteur *Structure GOP* + plomberie |

## 6. Limites & suites

- **Coût disque/temps Long-GOP** : le mux fait 2 passes O(fichier) supplémentaires
  (MP4Box import + ffmpeg audio) ; pic disque transitoire ~2× la source (temporaires
  supprimés après publication, artefact caché). Optimisable (FIFO) si besoin sur 70 Go.
- **`all-intra` forcé sur du Long-GOP** = saccade assumée (choix explicite utilisateur).
- **Profil caméra** : validé PXW-Z200 (ce firmware). Le framing/cadence restent à
  paramétrer par **profil caméra** avant d'élargir à d'autres modèles Sony.
- Master relancera la **récupération 70 Go complète** (mode `auto`) après ce fix.
