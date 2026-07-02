# 03 — Backend Architecture (MediaNotFound)

> Livrable Architecte. Décrit les **services, l'API REST, le pipeline modulaire de récupération, le mécanisme de preview par tranche, la gestion des jobs et les formats de réponse**. Contient aussi la **proposition de stack** (contrainte : conteneurisable Docker, traitement vidéo lourd backend). Ne contient pas de code d'implémentation.

## 0. Objectifs & contraintes d'architecture

1. **Modularité des méthodes de récupération** : chaque méthode (untrunc, ffmpeg-remux, reconstruction moov via référence, …) est un **plugin** interchangeable derrière une interface commune. Ajouter une méthode ou un format (autre marque après la V1 Sony) ne doit **pas** toucher le cœur.
2. **Preview par tranche sans recompiler l'intégrale** : traiter les N premières minutes doit être **borné** en temps/CPU, indépendamment de la durée totale du rush.
3. **Jobs longs & lourds** : le traitement vidéo (ffmpeg, réparation conteneur) est asynchrone, hors du cycle requête/réponse HTTP, avec suivi de progression.
4. **Conteneurisable & portable** : tout tourne dans Docker, en local, sans dépendance cloud. Volumes montés pour les fichiers média.
5. **Extensible** : formats, codecs, marques ajoutables via déclaration de plugins + capacités (`capabilities`).

---

## 1. Vue d'ensemble des services

```
┌──────────────┐      REST/JSON + WS/SSE      ┌───────────────────────────┐
│   Frontend   │ ◀──────────────────────────▶ │        API Gateway         │
│   (web SPA)  │                              │  (HTTP, validation, auth   │
└──────────────┘                              │   locale, routing)         │
                                              └────────────┬──────────────┘
                                                           │
             ┌──────────────────────┬────────────────────┼─────────────────────┐
             ▼                      ▼                     ▼                     ▼
    ┌─────────────────┐   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
    │  Analysis Svc   │   │   Job Manager    │  │  Media Registry  │  │   Result Store   │
    │  (diagnostic:   │   │  (queue, état,   │  │  (fichiers src,  │  │  (sorties, previews│
    │  atomes,codec)  │   │   progression)   │  │   références)    │  │   par tranche)    │
    └─────────────────┘   └────────┬─────────┘  └──────────────────┘  └──────────────────┘
                                   │ dispatch
                                   ▼
                        ┌───────────────────────┐
                        │     Worker Pool       │
                        │  (exécute les jobs)   │
                        └───────────┬───────────┘
                                    │ appelle
                                    ▼
                        ┌───────────────────────────────────────────┐
                        │        Recovery Pipeline (modulaire)       │
                        │  ┌────────────────────────────────────┐   │
                        │  │   RecoveryMethod plugins registry   │   │
                        │  │  · untrunc-moov  · ffmpeg-remux     │   │
                        │  │  · moov-rebuild-ref · (futurs...)   │   │
                        │  └────────────────────────────────────┘   │
                        │  Étapes: probe → repair → slice-encode     │
                        └───────────────────────────────────────────┘
                                    │ utilise
                                    ▼
                        ffmpeg / ffprobe / untrunc / outils réparation
```

### Rôle des services

| Service | Responsabilité |
|---------|----------------|
| **API Gateway** | Expose l'API REST, valide les entrées, ouvre les canaux de progression (SSE/WebSocket), sert éventuellement le frontend statique. |
| **Analysis Service** | Diagnostic structurel d'un fichier : détection conteneur (MP4/MXF), présence des atomes (`ftyp`/`mdat`/`moov`), codec (XAVC-S/HS/I/L), durée estimée, pistes. Ne modifie rien. |
| **Job Manager** | Crée/suit/annule les jobs, gère la file, persiste l'état et la progression, émet les events de progression. |
| **Worker Pool** | Processus/threads worker qui consomment la file et exécutent le pipeline de récupération (tâches CPU/IO lourdes). |
| **Recovery Pipeline** | Orchestration des étapes `probe → repair → slice-encode` en déléguant à la **méthode** (plugin) choisie. |
| **Media Registry** | Référentiel des fichiers source, références, métadonnées de diagnostic (indexés par hash/chemin). |
| **Result Store** | Stocke les sorties par tranche (1 min / 5 min / intégrale) + logs, réutilisables (cache preview). |

---

## 2. Pipeline de récupération MODULAIRE

### 2.1 Contrat d'une méthode (`RecoveryMethod` — interface plugin)

Chaque méthode implémente une interface commune. Pseudo-contrat (langage-agnostique) :

```
interface RecoveryMethod:
    id: string                      # ex: "untrunc-moov"
    display_name: string            # ex: "Reconstruction via fichier de référence"
    requires_reference: bool        # a-t-elle besoin d'un fichier sain ?

    capabilities() -> Capabilities  # conteneurs & codecs supportés, pistes (audio/vidéo)

    can_handle(diagnostic, options) -> Applicability
        # -> { applicable: bool, confidence: 0..1, reason: string }

    prepare(context) -> PreparedPlan
        # valide prérequis (référence compatible, outils dispo)

    run(context, slice_spec, progress_cb) -> RecoveryResult
        # exécute la récupération sur la tranche demandée,
        # émet la progression via progress_cb,
        # renvoie chemin(s) de sortie + métadonnées + logs
```

- `Capabilities` : `{ containers: [mp4, mxf], codecs: [xavc-s(h264), ...], tracks: [video, audio] }`.
- `Applicability` permet au **mode Auto** de classer les méthodes (tri par `confidence`) et à l'UI de griser les inapplicables avec une `reason`.
- **Découverte des plugins** : registre chargé au démarrage (déclaration statique + point d'extension). Ajouter une méthode = déposer un plugin + l'enregistrer, **sans modifier** le pipeline.

### 2.2 Étapes standard du pipeline

```
[probe] ──▶ [repair] ──▶ [slice-encode] ──▶ [validate] ──▶ [publish]
```

1. **probe** — (re)confirme le diagnostic, extrait les paramètres nécessaires à la méthode (offsets `mdat`, params codec, layout des pistes). Peut réutiliser la sortie de l'Analysis Service.
2. **repair** — cœur de la méthode : reconstruit l'index/`moov` (via référence pour untrunc-moov) ou remuxe, produisant un **flux/fichier lisible** ou une **table d'échantillons** exploitable.
3. **slice-encode** — matérialise la **tranche demandée** (voir §3) : extrait les N premières minutes en réutilisant au maximum les flux (copy) sans réencoder si possible.
4. **validate** — vérifie que la sortie est décodable (ffprobe), durée cohérente, pistes présentes selon le périmètre média.
5. **publish** — enregistre la sortie dans le Result Store (indexée par `source × méthode × périmètre × tranche`) + logs, et notifie le Job Manager.

Le **périmètre média** (son seul / vidéo seule / les deux) est passé en `options` et appliqué au **mapping des pistes** lors du `slice-encode` (sélection des streams à conserver).

---

## 3. Mécanisme de PREVIEW par tranche (sans recompiler l'intégrale)

### 3.1 Principe
Le coût du traitement doit être **proportionnel à la tranche demandée**, pas à la durée totale du rush. On ne reconstruit/encode que ce qui est nécessaire aux N premières minutes.

### 3.2 Techniques
- **Bornage temporel à la source** : le `slice-encode` limite la sortie à `[0, N min]` (`-t`/durée) et, quand la méthode le permet, **borne aussi la lecture d'entrée** pour ne pas décoder au-delà.
- **Stream copy prioritaire** : si la reconstruction produit un conteneur lisible avec le même codec, la tranche est extraite en **copie de flux** (`-c copy`) → quasi instantané, pas de réencodage.
- **Reconstruction d'index partielle** : pour untrunc-moov, il suffit de reconstruire la portion de la table d'échantillons couvrant la tranche + garantir un point de départ décodable (démarrer sur un keyframe / début de GOP).
- **Cache de previews** : `Result Store` indexe chaque sortie par `(source_hash, method_id, media_scope, slice)`. Rebasculer sur une tranche déjà générée = **service instantané depuis le cache** (les `SliceTabs` de l'UI s'appuient dessus).
- **Escalade 1 → 5 → intégrale** : l'extension réutilise les paramètres validés ; seule la **durée cible** change. La preview 1 min sert de garantie avant d'engager le coût de l'intégrale.

### 3.3 Modèle `slice_spec`
```
slice_spec = { kind: "1min" | "5min" | "full", start: 0, duration_s: 60 | 300 | null }
```
`start` est à 0 en V1 (offset configurable = évolution future).

---

## 4. Gestion des JOBS

### 4.1 Cycle de vie
```
queued ─▶ running ─▶ succeeded
   │          │
   │          ├─▶ failed
   └──────────┴─▶ canceled
```

### 4.2 Modèle Job
```
Job {
  id: uuid
  source_id: ref -> Media Registry
  reference_id: ref? (si méthode le requiert)
  method_id: string ("auto" résolu vers un plugin concret)
  media_scope: "audio" | "video" | "both"
  slice_spec: {...}
  status: queued|running|succeeded|failed|canceled
  progress: { step: string, percent: 0..100, eta_s?: number }
  result: RecoveryResult?      # sortie, previews, métadonnées
  error?: { code, message, hint }   # hint = action suggérée pour l'UX
  logs_ref: id                 # log technique détaillé (Result Store)
  created_at, started_at, finished_at
  parent_job_id?: uuid         # lien "étendre à l'intégrale" / relance
}
```

### 4.3 File & workers
- File FIFO avec priorité simple (previews courtes prioritaires sur intégrales longues, optionnel).
- **Concurrence bornée** (nb de workers = fonction des CPU dispo, configurable) car ffmpeg est CPU-intensif.
- **Annulation** : signal au worker → arrêt propre du sous-process (ffmpeg/untrunc) + statut `canceled`.
- **Idempotence / dédup** : un job identique `(source, method, scope, slice)` déjà `succeeded` renvoie le résultat caché sans relancer.
- **Progression** : le worker émet des events (`step`, `percent`) → Job Manager → poussés au frontend via **SSE** (ou WebSocket). Fallback **polling** `GET /jobs/{id}`.

---

## 5. API REST (contrat)

Toutes les réponses JSON suivent une **enveloppe commune** (§6).

### Fichiers & diagnostic
| Méthode | Route | Rôle |
|---------|-------|------|
| `POST` | `/api/media` | Enregistre un fichier source (chemin monté ou upload) → `source_id` |
| `POST` | `/api/media/{id}/analyze` | Lance le diagnostic structurel |
| `GET`  | `/api/media/{id}/diagnostic` | Récupère le diagnostic (atomes, codec, conteneur, durée, pistes) |
| `POST` | `/api/references` | Enregistre un fichier de référence sain → `reference_id` |
| `POST` | `/api/references/{id}/check?source={id}` | Valide la compatibilité référence↔source |

### Méthodes de récupération (plugins)
| Méthode | Route | Rôle |
|---------|-------|------|
| `GET` | `/api/methods` | Liste les méthodes pluggables + capacités |
| `GET` | `/api/methods/applicable?source={id}` | Méthodes applicables au diagnostic (triées par confiance) |

### Jobs
| Méthode | Route | Rôle |
|---------|-------|------|
| `POST` | `/api/jobs` | Crée un job de récupération (body: source, méthode, scope, slice, référence?) |
| `GET`  | `/api/jobs/{id}` | État + progression + résultat |
| `GET`  | `/api/jobs/{id}/events` | Flux **SSE** de progression temps réel |
| `POST` | `/api/jobs/{id}/cancel` | Annule le job |
| `POST` | `/api/jobs/{id}/extend` | Relance la même conf en **intégrale** (crée un job enfant) |
| `POST` | `/api/jobs/{id}/verdict` | Enregistre le verdict humain (`ok`/`ko` + qualifs) |

### Résultats & historique
| Méthode | Route | Rôle |
|---------|-------|------|
| `GET` | `/api/jobs/{id}/preview` | Sert la tranche récupérée (streaming, `Range` supporté) |
| `GET` | `/api/jobs/{id}/download` | Télécharge la sortie |
| `GET` | `/api/media/{id}/attempts` | Historique des tentatives du fichier source |
| `GET` | `/api/jobs/{id}/logs` | Log technique brut |

### Exemple — création d'un job
```http
POST /api/jobs
{
  "source_id": "src_abc",
  "method_id": "auto",              // ou "untrunc-moov"
  "media_scope": "both",
  "slice": { "kind": "1min" },
  "reference_id": "ref_xyz"          // requis si la méthode l'exige
}
→ 202 Accepted
{ "data": { "job_id": "job_123", "status": "queued" }, "error": null, "meta": {...} }
```

---

## 6. Format des réponses (enveloppe commune)

```json
{
  "data": { /* payload spécifique ou null */ },
  "error": {
    "code": "REFERENCE_INCOMPATIBLE",
    "message": "Le fichier de référence utilise un codec différent (H.265 vs H.264).",
    "hint": "Fournissez une référence tournée avec les mêmes réglages, ou essayez la méthode X."
  } ,
  "meta": { "request_id": "…", "timestamp": "…" }
}
```
- `error` = `null` en succès ; `data` = `null` en erreur.
- **`hint`** est **contractuel** : il alimente directement les messages orientés-action de l'UX ([8b]/[10] du flow).
- Codes d'erreur normalisés : `FILE_NOT_FOUND`, `UNSUPPORTED_FORMAT`, `MDAT_MISSING`, `CODEC_UNSUPPORTED_BY_METHOD`, `REFERENCE_REQUIRED`, `REFERENCE_INCOMPATIBLE`, `JOB_FAILED`, `CANCELED`.

### Payload diagnostic (exemple)
```json
{
  "container": "mp4",
  "atoms": { "ftyp": true, "mdat": true, "moov": false },
  "codec": { "family": "xavc-s", "video": "h264", "audio": "lpcm" },
  "estimated_duration_s": 2412,
  "tracks": [ {"type":"video","...":"..."}, {"type":"audio"} ],
  "recoverable": true,
  "recommendation": "reference_advised"
}
```

### Payload progression (SSE event)
```
event: progress
data: {"job_id":"job_123","step":"slice-encode","percent":62,"eta_s":18}
```

---

## 7. Stockage & données

- **Media Registry / Result Store** : métadonnées légères en base (SQLite suffit en local, PostgreSQL si besoin de robustesse) ; **fichiers média sur volume Docker monté** (jamais en base).
- Arborescence sorties : `/<work>/{source_hash}/{method}/{scope}/{slice}.mp4` + `logs/`.
- Nettoyage : politique de rétention configurable (previews jetables, sorties intégrales conservées).

---

## 8. Proposition de STACK technique

> Contraintes : conteneurisable Docker, traitement vidéo lourd backend, extensible.

### 8.1 Choix recommandé (et pourquoi)

| Couche | Choix recommandé | Justification |
|--------|------------------|---------------|
| **Traitement média** | **ffmpeg / ffprobe** + **untrunc** (`anthwlock/untrunc`) + libs conteneur MP4/MXF | Standards de fait ; untrunc = reconstruction moov via référence (cf. `04`). Outils CLI faciles à conteneuriser. |
| **Langage backend** | **Python 3.12** | Écosystème média mature, orchestration de sous-process ffmpeg simple, prototypage rapide, large communauté ; adapté à une V1. |
| **Framework API** | **FastAPI** | Async natif (SSE/WebSocket), validation (Pydantic) alignée avec l'enveloppe JSON, OpenAPI auto-généré. |
| **Jobs asynchrones** | **Celery + Redis** (ou **RQ + Redis** pour rester léger) | Découple les jobs lourds du cycle HTTP, workers scalables, annulation supportée. RQ suffit pour la V1 locale ; Celery si montée en charge. |
| **Progression temps réel** | **SSE** (via FastAPI) + fallback polling | Simple, unidirectionnel (serveur→client), suffisant pour barre de progression ; WebSocket en option. |
| **Base de métadonnées** | **SQLite** (V1 local) → PostgreSQL si besoin | Zéro admin en local, fichier unique dans le volume ; migration Postgres possible. |
| **Frontend** | **React + TypeScript** (Vite) | Lecteur HTML5, état de job réactif, composants de `02` ; TS pour la robustesse du contrat API. |
| **Lecteur** | `<video>` HTML5 + support **Range requests** côté API | Streaming des previews sans télécharger tout le fichier. |
| **Conteneurisation** | **Docker** multi-services via **docker-compose** | Portable, local. |

### 8.2 Découpage conteneurs (docker-compose)
```
services:
  api        # FastAPI (gateway + analysis + job manager API)
  worker     # Worker(s) média : ffmpeg + untrunc + pipeline (image "lourde")
  redis      # broker/queue + cache progression
  web        # frontend statique (build React) servi par nginx (ou par api)
volumes:
  media:     # fichiers source, références, sorties (monté par api + worker)
  db:        # SQLite / données
```
- L'image **worker** embarque ffmpeg + untrunc compilé → c'est là que vit le traitement lourd, isolé et scalable (`--scale worker=N`).
- L'image **api** reste légère (pas de binaire média requis pour router/valider).
- **DockerManager** (rôle squad) finalisera Dockerfiles/compose ; ici on fixe le **découpage** et les **frontières**.

### 8.3 Alternatives envisagées (non retenues, tracées)
- **Node.js/Express** backend : viable, bon pour SSE, mais Python garde l'avantage sur l'outillage média/scripting ffmpeg. → gardé en alternative.
- **Go** worker : excellent pour perf/concurrence et binaire unique, mais surcoût de dev en V1 ; envisageable pour un worker haute perf plus tard.
- **Celery vs RQ** : RQ recommandé pour démarrer (simplicité), Celery si besoins avancés (retries, routing, scheduling).

---

## 9. Extensibilité (au-delà de la V1 Sony `.rsv`)

- Nouveaux **formats/marques** = nouveaux **détecteurs** (Analysis Service) + nouvelles **méthodes** (plugins) déclarant leurs `capabilities`. Le cœur (jobs, API, preview, UI) ne change pas.
- Le **mode Auto** exploite `can_handle().confidence` → intègre automatiquement les nouvelles méthodes dans le classement.
- Les **codes d'erreur** et l'**enveloppe** sont stables → le frontend n'a pas à changer pour supporter un nouveau format.

Voir `04-recovery-methods-rsv.md` pour la spécification détaillée des méthodes de la V1 (untrunc-moov, ffmpeg-remux, moov-rebuild-ref) et la validation de l'hypothèse `.rsv`.
