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
| **Result Store** | Stocke l'**artefact « source réparée »** (clé `(source_hash, method_id, reference_hash)` — payé une fois, cf. §3.2) **et** les tranches dérivées (1/5/intégrale) + logs. Cœur du cache qui rend les previews instantanées. |

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

> **⚠️ Modèle de coût — validé par le Spike 01 (`docs/spike/spike-01-untrunc.md`).**
> Le `repair` (untrunc) coûte **O(taille du fichier)**, **PAS** O(tranche) : untrunc n'a **aucune notion de tranche**, il rescanne l'intégralité du `mdat` pour reconstruire le `moov` **complet**. Ce coût est **plein, payé une seule fois**, puis **mis en cache** (artefact « source réparée »). Ensuite, **chaque tranche** est un simple `ffmpeg -c copy` **quasi gratuit** (~0,2 s, O(tranche)).

```
[probe] ──▶ [repair (UNE FOIS, O(fichier), → CACHE)] ──▶ [slice-copy (O(tranche))] ──▶ [validate] ──▶ [publish]
                     │                                          ▲
                     └── artefact "source réparée" ─────────────┘  (réutilisé par toutes les tranches + extend)
```

1. **probe** — (re)confirme le diagnostic, extrait les paramètres nécessaires à la méthode (offsets `mdat`, params codec, layout des pistes). Peut réutiliser la sortie de l'Analysis Service.
2. **repair (UNE FOIS, caché)** — cœur de la méthode : reconstruit le `moov` **complet** (untrunc, via référence) en scannant **tout** le `mdat`, produisant un **MP4 réparé intégral** = l'**artefact « source réparée »**. **Coût plein O(fichier), payé une seule fois** ; le résultat est stocké et **indexé par `(source_hash, method_id, reference_hash)`** (voir §3.2). Si l'artefact existe déjà en cache pour ce triplet → **étape sautée** (cache hit).
3. **slice-copy** — matérialise la **tranche demandée** (voir §3) **par `ffmpeg -c copy` sur l'artefact réparé** : extrait `[start, +durée]` sans réencodage. **O(tranche), quasi gratuit.** Le réencodage n'a lieu **que** si l'utilisateur demande explicitement un autre format d'export.
4. **validate** — vérifie que la sortie est décodable (ffprobe), durée cohérente, pistes présentes selon le périmètre média.
5. **publish** — enregistre la tranche dans le Result Store (indexée par `source × méthode × référence × périmètre × tranche`) + logs, et notifie le Job Manager.

Le **périmètre média** (son seul / vidéo seule / les deux) est passé en `options` et appliqué au **mapping des pistes** lors du `slice-copy` (sélection des streams à conserver via `-map`), toujours en copie de flux.

---

## 3. Mécanisme de PREVIEW par tranche (le repair est payé UNE fois, les tranches sont gratuites)

### 3.1 Principe (corrigé — Spike 01)
> **Le coût n'est PAS proportionnel à la tranche.** Le `repair` untrunc coûte **O(taille du fichier)** (rescan intégral du `mdat`, reconstruction du `moov` complet) — identique que l'utilisateur vise 1 min ou l'intégrale. **Mais** ce coût est **payé une seule fois** et **mis en cache** sous forme d'un **artefact « source réparée »** (MP4 complet, index reconstruit, `mdat` d'origine préservé). **Ensuite**, produire n'importe quelle tranche (1 min / 5 min / intégrale) = un `ffmpeg -c copy` sur cet artefact → **~0,2 s, O(tranche), sans réencodage** (mesuré : ~25× plus rapide qu'un réencodage).

Le bénéfice « preview rapide » vient donc **du cache de l'artefact réparé**, pas d'un repair partiel (qui est impossible avec untrunc). C'est le **pilier BLOQ-3**.

### 3.2 Cache de l'artefact « source réparée » (pilier — BLOQ-3)
- **Clé de cache : `(source_hash, method_id, reference_hash)`.** Ce triplet identifie de façon déterministe le résultat du repair (même source + même méthode + même référence ⇒ même artefact réparé).
- L'artefact = **MP4 réparé intégral**, stocké dans le Result Store (fichier sur volume monté, métadonnées en base).
- **Réutilisé par TOUT** : les 3 tranches (1 min / 5 min / intégrale), l'endpoint `extend`, et toute relance de la même conf. Aucune de ces opérations ne re-paie le repair — elles font toutes un `-c copy` sur l'artefact caché.
- **Cache hit** : si le triplet existe déjà, l'étape `repair` est **sautée** ; le job passe directement en `slice-copy` (statut de progression « source déjà réparée — extraction de la tranche »).
- **⚠️ Anti-pattern évité** : sans ce cache, chaque changement d'onglet de tranche (`SliceTabs`) ou chaque `extend` re-lancerait un repair O(fichier) complet — plusieurs minutes sur un gros rush. Le cache est **obligatoire**, pas une optimisation.

### 3.3 Extraction de tranche (slice-copy)
- **Stream copy exclusif** : la tranche est extraite en **copie de flux** (`-c copy`) depuis l'artefact réparé → quasi instantané, pas de réencodage. `[start, +durée]` bornés (`-ss` / `-t`).
- **Périmètre média** appliqué par `-map` (garder audio / vidéo / les deux), toujours en copie.
- **Cache de tranches** (2ᵉ niveau, optionnel) : le Result Store peut aussi indexer les tranches par `(…, media_scope, slice)` pour resservir une tranche déjà extraite instantanément ; mais même sans, la ré-extraction reste ~0,2 s.
- **Escalade 1 → 5 → intégrale / `extend`** : ne change que la **durée cible** du `-c copy` sur le **même artefact réparé** déjà en cache. La preview 1 min sert de garantie avant d'exposer l'intégrale — **l'intégrale ne re-paie jamais le repair**.

### 3.4 Modèle `slice_spec`
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
- **Idempotence / dédup à deux niveaux** : (1) **repair** — si l'artefact réparé `(source_hash, method_id, reference_hash)` existe (§3.2), l'étape repair est **sautée** (le coûteux) ; (2) **tranche** — un job `(…, scope, slice)` déjà `succeeded` renvoie la tranche cachée. Un changement de tranche/scope ne re-paie **jamais** le repair.
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
| `GET` | `/api/methods/applicable?source={id}` | Méthodes applicables au diagnostic (triées par confiance) + **`requires_reference`** de la 1re méthode |

> **Chaînage front (MAJ-9)** : le front appelle `/api/methods/applicable` **dès le diagnostic**, y compris en mode Auto, pour lire `requires_reference` de la méthode la plus probable et **piloter l'affichage conditionnel** de `ReferenceFileInput` (`02` A3) — la réponse expose donc explicitement ce champ, pas seulement au moment du job.

### Jobs
| Méthode | Route | Rôle |
|---------|-------|------|
| `POST` | `/api/jobs` | Crée un job de récupération (body: source, méthode, scope, slice, référence?) |
| `GET`  | `/api/jobs/{id}` | État + progression + résultat |
| `GET`  | `/api/jobs/{id}/events` | Flux **SSE** de progression temps réel |
| `POST` | `/api/jobs/{id}/cancel` | Annule le job |
| `POST` | `/api/jobs/{id}/extend` | Étend en **intégrale** (job enfant) — **réutilise l'artefact réparé en cache** (`repair` sauté), simple `-c copy` |
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
  "recommendation": "reference_required"   // sans référence compatible : récupération non fiable (Spike 01)
}
```

### Payload progression (SSE event)
```
event: progress
data: {"job_id":"job_123","step":"slice-encode","percent":62,"eta_s":18}
```

---

## 7. Stockage & données

- **Media Registry / Result Store** : métadonnées légères en base (SQLite) ; **fichiers média sur volume Docker monté** (jamais en base).
- **Artefact « source réparée » (clé de voûte du cache, BLOQ-3)** : `/<work>/{source_hash}/{method}/{reference_hash}/repaired.mp4` — produit **une seule fois** par le `repair`, réutilisé par toutes les tranches et par `extend`.
- Arborescence tranches (dérivées de l'artefact, en `-c copy`) : `/<work>/{source_hash}/{method}/{reference_hash}/slices/{scope}/{slice}.mp4` + `logs/`.
- **Rétention** : l'**artefact réparé** est le plus coûteux à recalculer → conservé en priorité (c'est lui qui évite de re-payer le repair O(fichier)) ; les tranches dérivées sont jetables (régénérables en ~0,2 s). Politique configurable.

---

## 8. Proposition de STACK technique

> Contraintes : conteneurisable Docker, traitement vidéo lourd backend, extensible.

### 8.1 Choix recommandé (et pourquoi)

| Couche | Choix recommandé | Justification |
|--------|------------------|---------------|
| **Traitement média** | **ffmpeg / ffprobe** + **untrunc** (`anthwlock/untrunc`) + libs conteneur MP4/MXF | Standards de fait ; untrunc = reconstruction moov via référence (cf. `04`). Outils CLI faciles à conteneuriser. |
| **Langage backend** | **Python 3.12** | Écosystème média mature, orchestration de sous-process ffmpeg simple, prototypage rapide, large communauté ; adapté à une V1. |
| **Framework API** | **FastAPI** | Async natif (SSE/WebSocket), validation (Pydantic) alignée avec l'enveloppe JSON, OpenAPI auto-généré. |
| **Jobs asynchrones** | **File in-process : `ProcessPoolExecutor` + état en SQLite** (Redis/RQ écarté en V1) | **Arbitrage MIN-5** (voir §8.4). Poste **local mono-utilisateur**, jobs courts et peu nombreux → un broker distribué (Redis) est **surdimensionné**. Un pool de process suffit pour paralléliser ffmpeg/untrunc et supporter l'annulation ; l'état/progression vit dans SQLite. **Un service Docker en moins.** Redis+RQ reste la porte de sortie si multi-utilisateur/scaling (§8.4). |
| **Progression temps réel** | **SSE** (via FastAPI) + fallback polling | Simple, unidirectionnel (serveur→client), suffisant pour barre de progression ; WebSocket en option. |
| **Base de métadonnées** | **SQLite** (V1 local) → PostgreSQL si besoin | Zéro admin en local, fichier unique dans le volume ; sert aussi de **magasin d'état des jobs** (couplé au ProcessPool). Migration Postgres possible. |
| **Frontend** | **React + TypeScript** (Vite) | Lecteur HTML5, état de job réactif, composants de `02` ; TS pour la robustesse du contrat API. |
| **Lecteur** | `<video>` HTML5 + support **Range requests** côté API | Streaming des previews sans télécharger tout le fichier. |
| **Conteneurisation** | **Docker** multi-services via **docker-compose** | Portable, local. |

### 8.2 Découpage conteneurs (docker-compose)
```
services:
  app        # FastAPI + ProcessPool worker embarqué : ffmpeg + untrunc + pipeline
             # (image "lourde" : embarque les binaires média ; sert aussi l'API + SSE)
  web        # frontend statique (build React) servi par nginx (ou directement par app)
volumes:
  media:     # fichiers source, références, artefact réparé, tranches (monté par app)
  db:        # SQLite (métadonnées + état des jobs)
```
- **Pas de service Redis en V1** (cf. §8.4) : la file de jobs est **in-process** dans le conteneur `app` via `ProcessPoolExecutor`, l'état persiste en SQLite. **Deux services au lieu de quatre.**
- L'image `app` embarque **ffmpeg (version figée, cf. §8.5) + untrunc compilé** → traitement lourd isolé.
- **Contrainte ffmpeg (Spike 01 / DockerManager)** : figer **ffmpeg ≤ 8.0** dans l'image untrunc — untrunc avertit que **ffmpeg > 8.1 casse la struct interne `FFCodec`** (comportement indéfini). Ne pas laisser flotter la version (voir §8.5).
- **DockerManager** (rôle squad) finalisera Dockerfiles/compose ; ici on fixe le **découpage** et les **frontières**.
- **Note scaling** : si l'on doit un jour paralléliser sur plusieurs conteneurs, on ré-externalise le worker + réintroduit un broker (§8.4). Le contrat API et le pipeline ne changent pas.

### 8.3 Alternatives envisagées (non retenues, tracées)
- **Node.js/Express** backend : viable, bon pour SSE, mais Python garde l'avantage sur l'outillage média/scripting ffmpeg. → gardé en alternative.
- **Go** worker : excellent pour perf/concurrence et binaire unique, mais surcoût de dev en V1 ; envisageable pour un worker haute perf plus tard.

### 8.4 Arbitrage MIN-5 — file in-process vs Redis+RQ
- **Décision : file in-process (`ProcessPoolExecutor` + SQLite) pour la V1.**
- **Pourquoi** : le contexte est un **poste local mono-utilisateur** ; le Spike 01 montre que les jobs sont **courts en absolu** (repair borné par l'I/O du fichier, tranches ~0,2 s) et peu concurrents. Un **broker distribué (Redis) + RQ/Celery** apporterait un service Docker supplémentaire, un point d'exploitation et une complexité **sans bénéfice** à cette échelle.
- **Ce qu'on garde quand même** : découplage du cycle HTTP (le worker tourne hors requête), annulation (kill du sous-process ffmpeg/untrunc), progression persistée (SQLite → SSE).
- **Seuil de bascule vers Redis+RQ** : multi-utilisateur simultané, besoin de workers sur plusieurs machines/conteneurs, ou files longues avec retries/routing avancés. La frontière `RecoveryMethod`/API rend cette bascule **non-bloquante** (§9).

### 8.5 Contrainte outillage média (pour DockerManager)
- **ffmpeg ≤ 8.0** figé dans l'image untrunc (au-delà de 8.1, struct `FFCodec` cassée → untrunc instable). Build untrunc via le **Dockerfile officiel `anthwlock/untrunc`** (Ubuntu + ffmpeg compatible), comme dans le Spike 01.
- **Support Sony natif** : untrunc expose l'option **`-rsv-ben` — « RSV file recovery (Sony recording-in-progress files) »** et un `src/rsv.cpp` dédié → à exploiter par la méthode `untrunc-moov` (voir `04`).
- Usage untrunc : `untrunc <reference_saine.mp4> <fichier_casse.rsv>` (la **référence est le 1er argument**), sortie `<casse>_fixed.mp4`.

---

## 9. Extensibilité (au-delà de la V1 Sony `.rsv`)

- Nouveaux **formats/marques** = nouveaux **détecteurs** (Analysis Service) + nouvelles **méthodes** (plugins) déclarant leurs `capabilities`. Le cœur (jobs, API, preview, UI) ne change pas.
- Le **mode Auto** exploite `can_handle().confidence` → intègre automatiquement les nouvelles méthodes dans le classement.
- Les **codes d'erreur** et l'**enveloppe** sont stables → le frontend n'a pas à changer pour supporter un nouveau format.

Voir `04-recovery-methods-rsv.md` pour la spécification détaillée des méthodes de la V1 (untrunc-moov, ffmpeg-remux, moov-rebuild-ref) et la validation de l'hypothèse `.rsv`.
