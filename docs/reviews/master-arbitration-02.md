# Arbitrage Master #2 — suite re-review (round 2)

> Décision de **Master** après la re-review CounterPower (`architecture-review-02.md`, verdict 🟡 GO CONDITIONNEL). Fait foi pour la squad.

## Décision : GO pour l'implémentation V1, avec conditions non négociables

Le modèle de coût/cache est validé par mesure réelle (spike). On **démarre le code**. Pas de 3e tour de doc archi avant de coder — les corrections restantes sont soit des décisions déjà prises (Builder les applique directement), soit des détails d'implémentation.

## Conditions NON NÉGOCIABLES (à coder dès la 1re version du Result Store / cache)

1. **Écriture atomique de l'artefact réparé** (BLOQ-5 / MAJ-8) — écrire dans un chemin temporaire, `validate` (ffprobe décodable), PUIS `rename` atomique vers le chemin canonique. Le cache n'indexe un triplet `(source_hash, method_id, reference_hash)` comme disponible **qu'après** ce rename. Sans ça = corruption silencieuse du cache partagé. **Bloquant.**
2. **Verrou / registre "repair en cours"** par clé de cache (MAJ-12) — un 2e job sur une clé déjà en réparation **s'attache** au repair en cours, ne lance pas un second process.
3. **Hash de cache NON intégral** (MAJ-11) — `source_hash`/`reference_hash` = taille + hash de N échantillons répartis, calculé **une fois à l'enregistrement** (`POST /api/media`), stocké dans le Media Registry. Jamais un SHA-256 intégral sur un rush de 30-80 Go (sinon un cache-hit coûterait des minutes).
4. **Annulation propre** (MIN-9) — gérer les handles `subprocess.Popen` par job pour killer ffmpeg/untrunc ; ne pas compter sur `ProcessPoolExecutor.cancel()`.
5. **Confinement des chemins + pas d'auth V1** (MAJ-1/2) — resolve + vérif que le chemin reste sous la racine du volume `media`. V1 = localhost only, aucune auth. À appliquer même si `03` ne le dit pas encore littéralement.

## Points tranchés par Master

- **MAJ-14 (type de `confidence`)** → **TRANCHÉ** : `can_handle()` retourne un `confidence: float 0..1` interne (calculé par chaque plugin) ; c'est la **couche de présentation** qui le mappe vers un label qualitatif (HAUTE/MOYENNE/BASSE/NULLE) pour l'UI et le tableau de décision. Le contrat `RecoveryMethod` de `03` §2.1 reste en float. À refléter dans les docs plus tard.
- **MAJ-7 (`moov-rebuild-ref`)** → **RE-CONFIRMÉ hors périmètre code V1** (déjà tranché en arbitrage #1, perdu par l'Architect). V1 = `untrunc-moov` + `ffmpeg-remux` résiduel uniquement. Builder ne l'implémente pas.
- **MAJ-15 (fusion API+worker)** → séparation **`app` (API) + `worker`** sans Redis (ProcessPool+SQLite via volume partagé) **préférée** pour garder l'isolation ; à défaut, mono-conteneur assumé explicitement. DockerManager tranchera au packaging ; le code doit rester agnostique (worker = module appelable, pas couplé au process HTTP).

## Réconciliation doc (non bloquant, en parallèle/après)
Les gaps purement documentaires (MAJ-7 tag dans `04`, MAJ-8/11/12/14 dans `03`, MIN-10/11 honnêteté de `04` §1.2/§3.2) seront patchés par l'Architect **sans bloquer** le Builder. Le code fait foi via cet arbitrage + `architecture-review-02.md`.

## Séquence
1. **Builder → Implémentation V1 INCRÉMENT 1** = backend/moteur seul (scaffold + pipeline validé + méthode untrunc + API minimale), avec les 5 non-négociables. **STOP + rapport** en fin d'incrément pour review avant le frontend. ← ÉTAPE COURANTE
2. Review Builder (CounterPower) sur le code de l'incrément 1.
3. Incréments suivants : frontend (lecteur + tranches + options), méthode `ffmpeg-remux` résiduelle, feedback/historique.
4. DockerManager : packaging (ffmpeg ≤ 8.0, `-rsv-ben`, app/worker).
