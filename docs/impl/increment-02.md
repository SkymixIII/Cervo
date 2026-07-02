# Implémentation — INCRÉMENT 2 (frontend)

> Auteur : **Builder**. Suite à l'incrément 1 (backend fini/testé/poussé sur `lois/builder`).
> Périmètre : **frontend seul**, flux cœur récupération + preview sur les **endpoints
> existants**. Stack : React + TypeScript + Vite.
> Statut : **INCRÉMENT 2 TERMINÉ** — typecheck + build verts, intégration proxy vérifiée.

---

## 0. TL;DR

SPA `frontend/` (React 18 + TS strict + Vite 6) branchée sur l'API de l'incrément 1
via un **proxy `/api`**. Le flux `01-ux-flows.md` est implémenté de la saisie du
fichier abîmé jusqu'à la preview par tranche + extension à l'intégrale, avec l'**UX
honnête** du Spike 01 (réparation = même temps quelle que soit la tranche ; previews
**après** repair instantanées).

- `npm run typecheck` ✅ · `npm run build` ✅ (`tsc --noEmit && vite build` → `dist/`).
- **Smoke d'intégration à travers le proxy Vite** (5173 → 8000) ✅ : `POST /api/media`,
  `analyze`, `methods/applicable`, `references/check`, `POST /api/jobs`, **SSE**
  (`event: progress` reçu), `job succeeded`, **preview Range 206**. Prouve que le proxy
  forwarde bien `/api` **y compris le streaming SSE**.

---

## 1. Ce qui est fait (mission incrément 2)

### 1.1 Scaffold
`frontend/` — Vite + React + TS **strict** (`noUnusedLocals`/`noUnusedParameters`),
proxy `/api` → `http://127.0.0.1:8000` (surchargeable `VITE_API_TARGET`).

### 1.2 Client API typé (enveloppe `{data,error,meta}`)
`src/api/types.ts` + `src/api/client.ts` : toutes les routes utilisées par le flux,
avec `ApiException` porteuse de `code`/`message`/**`hint`** (le hint alimente l'UX).
Couvre : `media`, `analyze`, `diagnostic`, `references`, `references/check`,
`methods`, `methods/applicable`, `jobs`, `jobs/{id}`, `events` (SSE), `preview`
(Range), `extend`, `cancel`.

### 1.3 Composants (02 v2)
| Composant | Rôle | Points de conformité |
|---|---|---|
| `FileInput` | saisie chemin source/référence | 01 §1 |
| `DiagnosticCard` | résultat analyse | **variantes MP4 ET MXF** (MAJ-5) ; jamais moov/mdat sur MXF ; ligne « référence nécessaire » |
| `MediaScopeSelector` | son / vidéo / les deux | grise une piste seulement si **positivement absente** |
| `SliceSelector` | 1 / 5 / intégrale | **note honnête** : la tranche ne réduit pas le temps de repair |
| `ReferenceFileInput` | référence conditionnelle | **affiché via `methods/applicable.requires_reference`** (MAJ-9) ; badge **« ≈ probablement compatible »** (MAJ-6) |
| `MethodSelector` | Auto + méthodes applicables | confiance en **label** (présentation, MAJ-14) |
| `StatusPanel` | progression SSE | **libellés distincts** repair (long, barre ambre) / extraction (instantané, barre verte) / **cache-hit** « source déjà réparée » ; bouton **Annuler** |
| `VideoPlayer` + `SliceTabs` | lecture preview | `<video>`/`<audio>` sur `/preview` (**Range**) ; bascule de tranche = job **cache-hit** ; « son seul » → **waveform + `<audio>`** |
| `ErrorBanner` | erreurs honnêtes | message + **hint** + **« Essayer une autre méthode »** |

### 1.4 Orchestration du flux
`hooks/useRecovery.ts` (machine à états `idle → analyzing → analyzed →
running → done/failed`, + `unrecoverable`) : analyze → applicable →
référence conditionnelle → options → lancement → suivi SSE → preview → bascule de
tranche (réutilise le job déjà généré, sinon cache-hit) → **extend** (intégrale, sans
second repair). `hooks/jobTracker.ts` : SSE avec **repli automatique en polling** si
EventSource échoue.

### 1.5 Layout 3 zones (02 §1)
A (source & options) · B (lecteur & statut) · C (**principe/aide** — l'historique de la
zone C est **hors périmètre**, endpoints absents).

## 2. UX honnête (01 §0) — traduite dans l'UI
- **SliceSelector** : « la réparation prend le même temps quelle que soit la tranche ;
  1 min sert à contrôler le rendu, l'affichage est instantané ».
- **StatusPanel** : distingue visuellement repair (long) vs extraction (instantané), et
  affiche « source déjà réparée » quand `repair_cache_hit`.
- **VideoPlayer** : « Récupérer l'intégralité » précise « réutilise l'artefact déjà
  réparé — aucune seconde réparation ».
- **Zone C** : rappelle que **changer de méthode** relance une réparation (seul point coûteux).

## 3. Vérifications exécutées
```
cd frontend && npm install
npm run typecheck   # ✅
npm run build       # ✅ -> dist/ (index + assets)
```
Smoke d'intégration (uvicorn + vite dev + fixtures synthétiques, appels via le proxy
5173) : **9/9 PASS**, dont SSE et preview Range. (Script de vérif non commité — dans le
scratchpad de session.)

## 4. Décisions / limites (à noter)
1. **Zone C = principe**, pas l'historique des tentatives (endpoint `/attempts` absent).
   Verdict/feedback (`VerdictBar`), download/logs (`ResultActions`, `LogModal`) : **non
   implémentés** (hors périmètre, endpoints backend absents).
2. **MXF** : `DiagnosticCard` a la variante prête (MAJ-5), mais le backend de l'incrément 1
   ne **détecte pas encore** MXF (`container` = `mp4`/`unknown`). La variante s'activera
   dès que l'analyse backend émettra `container: "mxf"`. Aucune supposition MP4 sur MXF.
3. **Cache-hit en direct** : `repair_cache_hit` n'est fiable qu'au statut `succeeded`
   (contrat backend). Pendant l'exécution, l'UI s'appuie sur l'**étape** (`repair` vs
   `slice-copy`) pour les libellés ; le libellé « source déjà réparée » s'affiche au done.
4. **Bascule de tranche** : chaque tranche est un `POST /api/jobs` distinct (le backend
   n'expose pas d'extraction de tranche hors job) ; le **repair est sauté** (cache-hit),
   donc la bascule reste quasi instantanée. Les tranches déjà générées sont mémorisées
   côté client pour un ré-affichage immédiat.
5. **Sécurité** : conforme « V1 localhost only, pas d'auth / pas de CORS » ; le front est
   servi en même origine (proxy). À revisiter si exposition LAN (hors V1).

## 5. Ce qui reste (incréments suivants)
- Verdict humain + historique des tentatives (dépend de nouveaux endpoints backend).
- `ffmpeg-remux` résiduel, méthodes alternatives en modale enrichie.
- Upload navigateur (V1 = chemin monté prioritaire), détection/UX MXF réelle.
- Packaging Docker du front (nginx) — rôle DockerManager.

---

**INCRÉMENT 2 TERMINÉ.** typecheck + build verts, intégration proxy (SSE + Range) prouvée.
