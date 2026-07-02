# Implémentation — INCRÉMENT 1 (backend / moteur)

> Auteur : **Builder**. Suite à `master-arbitration-02.md` (GO CONDITIONNEL).
> Périmètre : **backend/moteur seul, pas de frontend.** Méthode V1 : `untrunc-moov`.
> Statut : **INCRÉMENT 1 TERMINÉ** — prêt pour review CounterPower.

---

## 0. TL;DR

Pipeline validé par le Spike 01, implémenté et **prouvé de bout en bout par un test
automatisé reproductible** :

- **1er job (tranche 1 min)** = repair réel via untrunc → `repair_cache_hit=false` (0,62 s sur fixture).
- **2e job (tranche 5 min, autre tranche)** = **CACHE HIT** → repair **sauté** → `repair_cache_hit=true` (**0,21 s**).
- **`extend` (intégrale)** = réutilise l'artefact réparé caché (repair sauté).

Les **5 non-négociables** de l'arbitrage #2 sont codés, dont l'annulation propre
**prouvée par un test déterministe** (kill du groupe subprocess en 0,57 s).

**Résultats des tests** : `tests/test_cancel.py` ✅ · `tests/e2e.py` **19/19 ✅ (exit 0)**.

---

## 1. Ce qui est fait

### 1.1 Scaffold (mission §1)
Projet `backend/` — Python 3.12 / FastAPI / SQLite / `ProcessPoolExecutor`, structure :

```
backend/app/
  main.py            API Gateway (FastAPI) + lifespan (init DB, pool, plugins)
  config.py          Config (env APP_*), picklable pour les workers
  envelope.py        enveloppe { data, error, meta } + codes d'erreur (03 §6)
  security.py        confinement des chemins (non-négociable e)
  hashing.py         hash de cache NON intégral (non-négociable c)
  confidence.py      mapping float 0..1 -> label qualitatif (MAJ-14)
  db.py              SQLite (WAL) : media, jobs, repair_locks
  api/               media.py · references.py · methods.py · jobs.py · deps.py
  pipeline/          atoms.py · analyze.py · runner.py · cache.py · slice.py · pipeline.py
  methods/           base.py (interface+registre) · untrunc_moov.py · ffmpeg_remux.py (stub)
  store/             media_registry.py · job_manager.py
tests/               gen_fixtures.py · e2e.py · test_cancel.py
scripts/untrunc-docker.sh   wrapper untrunc encapsulé (docker, chemins à l'identique)
```
(~1 900 LOC hors tests.)

### 1.2 Pipeline validé par le spike (mission §2)
`pipeline/pipeline.py` orchestre exactement le modèle du Spike 01 (03 §2.2) :

```
probe (ffprobe + parseur d'atomes) 
  → repair UNE FOIS (untrunc, O(fichier)) → CACHE artefact "source réparée"
  → slice-copy (ffmpeg -c copy, O(tranche)) → validate (ffprobe) → publish
```
- **probe** : `analyze.py` combine le **parseur d'atomes** (`atoms.py`, marche sans
  `moov`) + **ffprobe** (codec/durée quand lisible). Sur un `.rsv` sans moov,
  ffprobe échoue → codec `unknown`, `recommendation: reference_required`.
- **repair** : délégué au plugin, passé au **cache** (voir §1.4).
- **slice-copy** : `slice.py`, `-c copy` + `-map` selon le périmètre média
  (audio/vidéo/both), jamais de réencodage. Cache de tranche 2ᵉ niveau (03 §3.3).

### 1.3 Interface plugin + `untrunc-moov` (mission §3)
- `methods/base.py` : contrat `RecoveryMethod` (`id`, `display_name`,
  `requires_reference`, `capabilities`, `can_handle → Applicability{applicable,
  confidence:float, reason}`, `repair`) + **registre** (`register`/`applicable`/
  `resolve_method_id('auto')`). Découpage : le plugin fait le **repair** ; slice/
  validate/publish sont **génériques**.
- `methods/untrunc_moov.py` : **encapsule entièrement untrunc** (mission → pour que
  DockerManager formalise le packaging). Points clés :
  - exécutable piloté par `cfg.untrunc_cmd` (binaire local **ou** wrapper docker) ;
  - **ordre d'arguments corrigé** : options (`-n`, `-dst`, `-rsv-ben`) **avant** les
    fichiers positionnels — vérifié empiriquement (sinon untrunc affiche l'usage et échoue) ;
  - **référence en 1er argument** (Spike 01) ; option Sony **`-rsv-ben`** activable ;
  - `can_handle` : `0.9` si MP4+H.264+moov manquant ; `0.6` si codec indéterminé ;
    **non applicable** si H.265/XAVC-HS (piège connu 04 §1.2) ou moov présent.
- `methods/ffmpeg_remux.py` : **stub** honnête. `can_handle` retourne **non
  applicable sans moov** (Spike 01 §3.4 : ffmpeg ne récupère rien sans moov). Sert
  à prouver que le registre accueille une 2ᵉ méthode **sans toucher au cœur**.
- **`moov-rebuild-ref` NON implémenté** (MAJ-7, hors V1). ✅

### 1.4 API REST minimale (mission §4)
Toutes réponses en enveloppe `{data,error,meta}`. Endpoints livrés :

| Endpoint | Statut |
|---|---|
| `POST /api/media` | ✅ enregistre une source confinée, calcule le hash de cache |
| `POST /api/media/{id}/analyze` | ✅ diagnostic (atomes/codec/conteneur/durée/pistes) |
| `GET /api/media/{id}/diagnostic` | ✅ |
| `POST /api/references` | ✅ |
| `POST /api/jobs` | ✅ crée un job (validation précoce référence/méthode) |
| `GET /api/jobs/{id}` | ✅ état + progression + résultat |
| `GET /api/jobs/{id}/events` | ✅ **SSE** (poll DB → events `progress`/`done`) |
| `GET /api/jobs/{id}/preview` | ✅ `FileResponse` avec **Range** (lecteur HTML5) |
| **Bonus** `POST /api/jobs/{id}/cancel` | ✅ (non-négociable d) |
| **Bonus** `POST /api/jobs/{id}/extend` | ✅ intégrale, réutilise le cache |
| **Bonus** `GET /api/methods`, `GET /api/methods/applicable` | ✅ (chaînage MAJ-9) |
| **Bonus** `POST /api/references/{id}/check` | ✅ compat estimative (MAJ-6) |

### 1.5 Les 5 NON-NÉGOCIABLES (mission §5)

| # | Exigence | Implémentation | Preuve |
|---|----------|----------------|--------|
| **a** | Écriture **atomique** de l'artefact | `cache.py` : untrunc → dossier temp `work/.tmp/<uuid>` → `validate_decodable` (ffprobe) → `os.replace` atomique vers le chemin canonique. Le cache n'est « disponible » que si le fichier canonique existe. | e2e : preview décodable ; artefact réutilisé |
| **b** | Verrou **"repair en cours"** par clé | table `repair_locks(cache_key PK)` : le 1er job devient *owner* (INSERT), tout autre job **s'attache** (poll jusqu'à `done`) au lieu de lancer un 2ᵉ untrunc. Nettoyage des verrous morts (`failed`) → reprise. | cache-hit e2e ; logique d'attache codée |
| **c** | Hash de cache **NON intégral** | `hashing.py` : `taille + N échantillons` répartis, calculé **une fois** à `POST /api/media`/`/references`, stocké. O(1) vs taille (jamais de SHA-256 sur 30-80 Go). | `cache_hash` en base |
| **d** | **Annulation propre** via `subprocess.Popen` | `runner.py` : `Popen(start_new_session=True)` → `os.killpg` (SIGTERM→SIGKILL). PID publié en base → l'API tue le **groupe** du sous-process média (pas `ProcessPoolExecutor.cancel`). **Lecture non bloquante (select)** pour sonder l'annulation même si l'outil est silencieux. | **`test_cancel.py` ✅** : kill en 0,57 s, enfant confirmé mort |
| **e** | **Confinement des chemins + pas d'auth** | `security.py` : `resolve()` + `relative_to(media_root)` (robuste aux symlinks/`..`). V1 = localhost only, aucune auth. `403 PATH_FORBIDDEN` hors racine. | code + tests d'intégration |

### 1.6 `confidence` float→label (mission §6, MAJ-14)
`can_handle()` retourne un **float 0..1 interne** ; `confidence.py` le mappe en label
(`NULLE/BASSE/MOYENNE/HAUTE`) **à la présentation** (exposé par `/api/methods/applicable`
et `/references/{id}/check`). Le moteur ne raisonne jamais sur le label.

### 1.7 File in-process (arbitrage MIN-5)
`store/job_manager.py` : jobs soumis à un `ProcessPoolExecutor`, état/progression en
SQLite (communication inter-process), **pas de Redis**. Le worker est un **module
appelable** (`run_job_worker`), découplé du process HTTP → DockerManager pourra le
déplacer sans changer le contrat.

---

## 2. Comment tester (reproductible)

Prérequis : `ffmpeg`/`ffprobe` locaux + image Docker `untrunc` (cf. `backend/README.md`).

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# (d) annulation propre — déterministe, sans docker
.venv/bin/python -m tests.test_cancel

# end-to-end : génère un MP4 H.264 synthétique, tronque le moov, prouve repair + CACHE HIT
export APP_UNTRUNC_CMD="$(cd .. && pwd)/scripts/untrunc-docker.sh"
.venv/bin/python -m tests.e2e
```

`tests/e2e.py` (repris de la génération synthétique du Spike 01) enchaîne : POST media
→ analyze → POST reference → methods/applicable → **job1 (1min, repair réel)** →
preview décodable → **job2 (5min, CACHE HIT)** → SSE → extend. Sortie attendue :
`TOUS LES TESTS PASSENT ✅` (19/19, exit 0).

### Résultats obtenus (cette machine)
```
[PASS] diagnostic: mdat présent / moov absent / recoverable / reference_required
[PASS] applicable: untrunc-moov en tête ; requires_reference=True (MAJ-9)
[PASS] job1 succeeded ; repair_cache_hit=False (repair réel)   durée=0.62s
[PASS] preview job1 décodable (ffprobe)
[PASS] job2 succeeded ; repair_cache_hit=True (REPAIR SAUTÉ)    durée=0.21s
[PASS] SSE: events reçus ; extend: succeeded + cache hit
test_cancel : annulation en 0.57s, enfant pid bien tué ✅
```

---

## 3. Écarts / décisions prises pendant le code (à noter en review)

1. **Ordre des arguments untrunc** : options **avant** les fichiers (découvert en
   test ; `-dst` après les positionnels fait échouer untrunc). Documenté dans le plugin.
2. **`ffmpeg-remux` = stub non fonctionnel** (conforme à l'invalidation Spike 01
   §3.4). Il ne fait qu'exister dans le registre et déclarer `can_handle=NON`.
3. **Diagnostic d'un fichier sans moov** : ffprobe ne peut pas donner le codec →
   `codec.video=null`, `family=unknown`. `untrunc-moov.can_handle` reste applicable
   (0.6) car le codec réel sera confirmé par la référence. Le badge de compat
   (`/references/check`) est **estimatif** (MAJ-6), jamais une garantie binaire.
4. **Cache déterministe = pièges de test** : l'artefact réparé persiste entre runs
   (hash déterministe) ; `e2e.py` nettoie `work_root` au démarrage pour garantir un
   « repair réel » au 1er job. (C'est la **preuve** que le cache survit aux redémarrages.)
5. **Wrapper untrunc docker** (`scripts/untrunc-docker.sh`) : monte `APP_MEDIA_ROOT`
   et `APP_WORK_ROOT` **à l'identique** (host==container) pour que les chemins absolus
   passent tels quels. Choix transitoire : DockerManager embarquera untrunc dans
   l'image `app` (le code reste agnostique via `APP_UNTRUNC_CMD`).
6. **`options.rsv_ben`** est câblé dans le plugin mais **non exposé** par l'API dans
   cet incrément (le schéma `jobs` ne porte pas d'options méthode). À exposer si un
   incrément suivant en a besoin sur de vrais `.rsv`.

---

## 4. Ce qui reste (hors périmètre incrément 1)

- **Frontend** (lecteur + SliceTabs + options + diagnostic) — incrément suivant.
- **`ffmpeg-remux` résiduel** (cas « moov partiel/corrompu présent ») — à étoffer.
- **Feedback/verdict + historique** (`POST /api/jobs/{id}/verdict`,
  `GET /api/media/{id}/attempts`, `logs`, `download`) — endpoints non livrés ici.
- **Rétention/nettoyage disque** (MAJ-4) — non implémenté (politique à définir).
- **Robustesse sur vrai `.rsv` Sony** + mode `-rsv-ben` sans référence — dépend
  d'un échantillon réel (input utilisateur en attente) ; mini-spikes tracés.
- **Packaging Docker** (app+worker, ffmpeg ≤ 8.0, untrunc embarqué) — rôle DockerManager.
- **Tests** : suite volontairement ciblée (e2e + annulation). Pas de couverture
  unitaire exhaustive par module à ce stade.

---

**INCRÉMENT 1 TERMINÉ.** En attente de review CounterPower avant le frontend.
