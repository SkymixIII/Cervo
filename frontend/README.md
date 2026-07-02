# MediaNotFound — Frontend (Incrément 2)

SPA **React + TypeScript + Vite**. Flux cœur **récupération + preview** sur les
endpoints existants du backend (incrément 1). V1 = **localhost only**, aucune auth,
aucun CORS (le front est servi sur la même origine via le proxy `/api`).

> Hors périmètre (endpoints backend absents) : verdict/feedback, historique
> (`/attempts`), download/logs. La zone C affiche le **principe** au lieu de l'historique.

## Prérequis
- Node ≥ 18 (testé Node 25).
- Le **backend** doit tourner (voir `../backend/README.md`) : `uvicorn app.main:app --host 127.0.0.1 --port 8000`, avec ffmpeg/ffprobe + image Docker `untrunc` (`APP_UNTRUNC_CMD`).

## Lancer en développement
Deux process : l'API (uvicorn) **et** le serveur de dev Vite (qui proxifie `/api`).

```bash
# 1) Backend (terminal A) — depuis backend/
export APP_UNTRUNC_CMD="$(git rev-parse --show-toplevel)/scripts/untrunc-docker.sh"
export APP_MEDIA_ROOT=/chemin/vers/media   # racine confinée des fichiers
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2) Frontend (terminal B) — depuis frontend/
npm install
npm run dev            # http://127.0.0.1:5173  (proxy /api -> 127.0.0.1:8000)
```
La cible du proxy est surchargeable : `VITE_API_TARGET=http://autre:8000 npm run dev`.

## Vérifications (CI)
```bash
npm run typecheck      # tsc --noEmit
npm run build          # tsc --noEmit && vite build  -> dist/
```

## Parcours couvert (01/02 v2)
1. Saisie du **chemin** du fichier abîmé → **Analyser** (`POST /api/media` + `/analyze`).
2. **DiagnosticCard** — variantes **MP4** (mdat/moov) **et MXF** (essence/partitions, MAJ-5).
3. **Options** : périmètre (son/vidéo/les deux), tranche (1/5/intégrale, note honnête).
4. **ReferenceFileInput** conditionnel via `GET /api/methods/applicable`
   (`requires_reference`, MAJ-9) + badge **« ≈ probablement compatible »** (MAJ-6, via
   `POST /api/references/{id}/check`).
5. **MethodSelector** : Auto (recommandée) + méthodes applicables (confiance).
6. **Lancer** → **StatusPanel** (progression **SSE**, libellés **distincts**
   réparation-longue / extraction-instantanée / **« source déjà réparée »** + Annuler).
7. **VideoPlayer** + **SliceTabs** (1/5/intégrale) : `<video>` sur `/api/jobs/{id}/preview`
   (Range) ; « son seul » → waveform + `<audio>`. Bascule de tranche = nouveau job
   **cache-hit** (repair sauté).
8. **Récupérer l'intégralité** (`POST /api/jobs/{id}/extend`, réutilise l'artefact réparé).
9. **Erreurs honnêtes** (message + hint contractuel) + **« Essayer une autre méthode »**.

## Structure
```
src/
  api/{types,client}.ts     contrat API typé + enveloppe {data,error,meta}
  hooks/useRecovery.ts      machine à états du flux
  hooks/jobTracker.ts       suivi job SSE + fallback polling
  labels.ts                 libellés UX honnêtes (repair vs extraction vs cache)
  components/               FileInput, DiagnosticCard, Selectors, ReferenceFileInput,
                            StatusPanel, VideoPlayer(+SliceTabs), ErrorBanner
  App.tsx                   layout 3 zones (A source/options · B lecteur/statut · C principe)
```
