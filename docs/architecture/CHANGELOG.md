# Changelog architecture — MediaNotFound

## v2 — Intégration du Spike 01 (`docs/spike/spike-01-untrunc.md`) + review CounterPower

> Mise à jour Architecte suite au spike Builder tranchant BLOQ-2/BLOQ-3, et traitement des points MAJ-5, MAJ-9, MIN-5. Aucun code — `.md` uniquement.

### Modèle de coût (BLOQ-2) — le changement structurant
- **Correction majeure** : le repair untrunc est **O(taille du fichier), PAS O(tranche)**. L'ancienne promesse « preview 1 min rapide car on ne traite qu'1 min » était **fausse** et a été supprimée partout.
- Nouveau modèle : **repair plein payé UNE fois → mis en cache → tranches quasi gratuites en `-c copy` (~0,2 s)**.

### Cache de l'artefact « source réparée » (BLOQ-3) — nouveau pilier
- Ajout explicite d'un **artefact réparé** indexé par **`(source_hash, method_id, reference_hash)`**, réutilisé par **toutes les tranches ET `extend`** (jamais de second repair).
- Pipeline corrigé : `probe → repair(ONCE, cache) → slice-copy(O(tranche)) → publish`.

### Fichier par fichier

**`01-ux-flows.md`**
- §0 : promesse UX reformulée honnêtement (repair = même temps quelle que soit la tranche, plusieurs minutes possibles sur gros rush 4K ; ce sont les previews **après** repair qui sont instantanées). Nouveau principe : « Réparer une fois, prévisualiser autant qu'on veut ».
- §[4] : libellé de tranche corrigé (sert à contrôler le rendu, pas à réduire le temps de repair).
- §[5] : **référence quasi obligatoire** (sans elle, ffmpeg ne récupère rien, pas même le son) ; aide à *trouver* une référence ; chaînage `/api/methods/applicable` (MAJ-9) ; badge « probablement compatible » (MAJ-6).
- §[7] : libellés de progression (Réparation 1× / Extraction copie ; saut si cache).
- §[9] : extension à l'intégrale **réutilise l'artefact réparé** (aucun second repair).
- §5 : boucle d'itération + nuance de coût (changer de méthode = nouvelle réparation).

**`02-ui-screens.md`**
- A2 `DiagnosticCard` : **variante MXF** ajoutée (mapping conteneur→vocabulaire ; MXF = KLV/partitions, pas moov/mdat) — **MAJ-5**.
- A3 `ReferenceFileInput` : affichage piloté par `GET /api/methods/applicable` (**MAJ-9**) ; badge estimatif (MAJ-6) ; requis quand la méthode l'exige.
- B1 `SliceTabs` : bascule instantanée post-repair (extraction `-c copy`, pas de re-repair).
- B2 `StatusPanel` : libellés d'étape alignés (repair long vs extraction instantanée, saut si cache).

**`03-backend-architecture.md`**
- §1 : `Result Store` redéfini autour de l'artefact réparé.
- §2.2 : pipeline + encart modèle de coût O(fichier) ; repair caché.
- §3 : réécrit — §3.1 principe corrigé, **§3.2 cache d'artefact `(source_hash, method_id, reference_hash)`** (pilier BLOQ-3), §3.3 slice-copy `-c copy`.
- §4.3 : dédup à deux niveaux (repair caché / tranche cachée).
- §5 : note MAJ-9 (chaînage `/api/methods/applicable` + `requires_reference`) ; `extend` réutilise le cache.
- §6 : payload diagnostic `recommendation: reference_required`.
- §7 : arborescence stockage avec artefact réparé + rétention prioritaire.
- §8 : **arbitrage MIN-5** → file **in-process (`ProcessPoolExecutor` + SQLite)**, **Redis+RQ écarté en V1** (surdimensionné pour poste local mono-utilisateur ; seuil de bascule documenté §8.4). Compose passé à 2 services (`app`+`web`). Contrainte **ffmpeg ≤ 8.0** + `-rsv-ben` ajoutée (§8.5).

**`04-recovery-methods-rsv.md`**
- §3.1 `untrunc-moov` : **validé Spike 01** ; `-rsv-ben` ; modèle de coût O(fichier)+cache ; ffmpeg ≤ 8.0 ; compat = estimation ; réserve d'honnêteté (cas synthétique H.264).
- §3.2 `ffmpeg-remux` sans référence : **INVALIDÉ** (Spike 01 §3.4 — ne récupère rien sans moov, pas même le son) ; rétrogradé au seul cas résiduel « moov partiel/corrompu ».
- §3.3 : confiances qualitatives (MAJ-10).
- §3.5 (nouveau) : politique « référence quasi obligatoire ».
- §3.6 (nouveau) : piste untrunc sans référence externe (`-rsv-ben`/`-sm search mdat`) — à spiker, hors V1.
- §4 : tableau de décision refondu (confiances qualitatives ; « sans référence = NULLE » ; MXF « à venir »).
- §5 : points de vigilance mis à jour (coût/cache, référence, ffmpeg ≤ 8.0, `-rsv-ben`).
- §6 : résumé aligné.

### Points de review traités
- **BLOQ-2** (coût O(fichier)) ✅ · **BLOQ-3** (cache artefact réparé) ✅
- **MAJ-5** (variante MXF DiagnosticCard) ✅ · **MAJ-6** (compat = estimation) ✅ · **MAJ-9** (chaînage `/api/methods/applicable`) ✅ · **MAJ-10** (confiances qualitatives) ✅
- **MIN-5** (in-process vs Redis) ✅ arbitré en faveur de l'in-process

### Restant / à spiker (non bloquant)
- Robustesse untrunc sur **vrai `.rsv` Sony** (spike sur cas synthétique H.264 seulement).
- Mode « sans référence externe » (`-rsv-ben`) — mini-spike dédié.
- H.265/XAVC-HS et MXF : hors code V1.
