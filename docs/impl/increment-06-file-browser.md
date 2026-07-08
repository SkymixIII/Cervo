# Incrément 6 — Navigateur de fichiers confiné (`/api/browse` + `FileBrowser`)

> Auteur : **Builder**. Permet de **choisir un `.rsv`** (ou tout média récupérable) en
> **parcourant les disques montés** sous la racine média, au lieu de taper un chemin.
> Statut : ✅ **TERMINÉ — validé end-to-end** (browse → choisir → analyze, port 8077).

---

## 0. Besoin

Jusqu'ici la seule façon de désigner une source était de **taper un chemin** dans le
champ texte. Peu ergonomique et source d'erreurs. On ajoute un **navigateur** intégré,
**strictement confiné** à la racine média (`APP_MEDIA_ROOT`) — même barrière de sécurité
que les autres routes (non-négociable e : localhost, aucune auth, seule protection =
le confinement des chemins).

> En Docker, `DockerManager` monte les disques utilisateur **sous** la racine média.
> Le navigateur ne raisonne donc qu'en **chemins relatifs à `APP_MEDIA_ROOT`** — aucune
> notion de disque système exposée.

---

## 1. Backend — `GET /api/browse?path=<relpath>`

Fichiers : `backend/app/api/browse.py` (nouveau), `backend/app/security.py`,
`backend/app/main.py`.

### Confinement (`security.confine_dir`)

Nouvelle fonction sœur de `confine`, pour un **dossier** au lieu d'un fichier. Même
logique éprouvée : `Path.resolve()` (résout les symlinks) puis `resolved.relative_to(root)`
— **pas** de comparaison de préfixe de chaîne. Un chemin vide → la racine elle-même.

- hors racine (via `..` **ou** symlink sortant) → `PathForbidden` → **403**
- dossier absent / illisible / pas un dossier → `MediaFileNotFound` → **404**
- exige `R_OK | X_OK` (lecture + traversée) pour lister.

### Réponse (enveloppe `{data,error,meta}`)

```json
{ "cwd": "rushes_jour1",           // relatif à la racine ('' = racine)
  "parent": "",                    // relatif, null si on est à la racine
  "entries": [
    { "name": "broken.rsv", "type": "file", "size": 14985013, "ext": "rsv", "is_media": true },
    { "name": "full.mp4",   "type": "file", "size": 15002168, "ext": "mp4", "is_media": true }
  ] }
```

- **Tri** : dossiers d'abord, puis **fichiers récupérables** (`is_media`), puis les autres —
  alphabétique (insensible à la casse) dans chaque groupe. → « marque **ET** priorise ».
- `is_media` = extension ∈ `{.rsv .mp4 .mov .mxf .mts .m2ts}`.
- **Lecture seule** : `os.scandir` uniquement, jamais d'écriture ; les entrées illisibles
  (permission, lien cassé) sont ignorées sans planter.
- `size` = octets pour les fichiers, `null` pour les dossiers ; `ext` sans point, minuscule.

---

## 2. Frontend — composant `FileBrowser`

Fichiers : `frontend/src/components/FileBrowser.tsx` (nouveau),
`FileInput.tsx`, `App.tsx`, `hooks/useRecovery.ts`, `api/client.ts`, `api/types.ts`,
`styles.css`.

- **Bouton `Parcourir…`** ajouté à `FileInput` (prop optionnelle `onBrowse`) à côté du champ.
- **Modale** : liste dossiers/fichiers, `..` pour remonter, clic dossier pour descendre,
  fil d'Ariane (`cwd`), tailles lisibles (`o/Ko/Mo/Go`), fichiers média **surlignés**
  (icône 🎬 + accent), fermeture par `Échap` / clic hors modale / `✕`.
- **`Choisir`** sur un fichier → remplit le champ source (chemin **relatif** à la racine)
  **puis lance l'analyse**.
- **Saisie manuelle conservée** en fallback (le champ texte reste pleinement utilisable).

### Détail d'implémentation notable

`useRecovery.analyze` lisait `ref.current.sourcePath` : impossible d'enchaîner
`setSourcePath(x)` puis `analyze()` dans le même tick (l'état n'est pas encore propagé).
Refactor : cœur **paramétré par le chemin** `runAnalyze(path)` qui écrit `sourcePath`
**et** analyse. Deux points d'entrée :
- `analyze()` = `runAnalyze(ref.current.sourcePath)` (bouton/Entrée — signature `() => void`
  inchangée, sûre même si l'event est passé à `onClick`) ;
- `pickSource(relpath)` = `runAnalyze(relpath)` (sélection depuis le navigateur).

---

## 3. Tests & validation

**Unitaires** — `backend/tests/test_browse.py` (5 cas, appel direct de la route) :
listing + tri (dossiers → média → autres), flags `is_media/ext/size`, cas racine
(`parent=null`) et sous-dossier (`parent=""`), **confinement** `../..` → 403,
**symlink sortant** → 403, dossier absent → 404. Tous **PASS**.

**End-to-end réel** (uvicorn + arborescence temporaire avec fixtures `gen_fixtures`) :

| Étape | Résultat |
|---|---|
| `GET /api/browse?path=` | racine, `parent=null`, dossier avant fichier ✅ |
| `GET /api/browse?path=rushes_jour1` | 3 média triés, `parent=""` ✅ |
| `GET /api/browse?path=../..` | **403 PATH_FORBIDDEN** ✅ |
| `GET /api/browse?path=nope` | **404 FILE_NOT_FOUND** ✅ |
| `POST /api/media {path:"rushes_jour1/broken.rsv"}` → `analyze` | `recoverable:true` ✅ |

**Typecheck** front (`tsc --noEmit`) : ✅ sans erreur.
