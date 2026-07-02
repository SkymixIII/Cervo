# Arbitrage Master — suite review archi #1

> Décision de **Master** (orchestrateur) après la review critique de CounterPower (`architecture-review-01.md`). Fait foi pour toute la squad.

## Décision : ON PIVOTE VERS UN SPIKE DE VALIDATION AVANT DE CODER LE PIPELINE

La review a raison sur le fond : l'architecture est solide mais bâtie sur une hypothèse (`untrunc` + coût du repair proportionnel à la tranche) **jamais vérifiée en pratique**. On ne construit pas le pipeline modulaire complet tant que cette hypothèse n'est pas testée.

## Arbitrage point par point

| Réf | Sujet | Décision Master |
|-----|-------|-----------------|
| **BLOQ-1** | Hypothèse `.rsv` non testée | ✅ **Accepté** — statut rétrogradé à « présomption forte ». Spike obligatoire (R0). |
| **BLOQ-2** | Coût repair O(fichier) vs O(tranche) | ✅ **À trancher par le spike.** C'est LA question n°1. Le Builder doit la mesurer avant tout. |
| **BLOQ-3** | Cache de l'artefact « source réparée » | ✅ **Accepté** — si le repair est O(fichier), on introduit un cache d'artefact réparé indexé par `(source_hash, method_id)`, réutilisé par tous les slice-encodes. À intégrer dans `03` après le spike. |
| **BLOQ-4** | Fichier de référence souvent indisponible | ⏳ **Décision produit différée** (post-spike + input user). Piste retenue par défaut : enrichir l'UX pour aider à *trouver* une référence (scanner le même dossier/carte pour proposer des candidats compatibles) plutôt que subir le fallback dégradé. |
| **MAJ-7** | `moov-rebuild-ref` (H.265 exp.) dans V1 | ✅ **Sorti du périmètre code V1** (comme `mxf-rebuild`). V1 = `untrunc-moov` + `ffmpeg-remux` uniquement. |
| **MAJ-1/2** | Path traversal + auth | ✅ **Accepté** — confinement strict à la racine du volume obligatoire ; V1 = **localhost only, pas d'auth** (exposition LAN hors périmètre V1, à documenter). |
| **MAJ-3** | Upload gros rushs | ✅ Voie principale V1 = **chemin monté** ; upload navigateur limité/déconseillé pour les gros fichiers. |
| **MAJ-5/8/9** | MXF DiagnosticCard, écriture atomique, chaînage `/methods/applicable` | ✅ Accepté — à corriger dans `01/02/03` au tour de révision archi post-spike. |
| **MAJ-4/6/10, MIN-*** | Rétention, compat référence, scores de confiance, etc. | ✅ Accepté — traités au fil de l'implémentation, non bloquants pour démarrer le spike. |
| **MIN-5** | Redis+RQ peut-être too much pour V1 mono-poste | 🔎 **À reconsidérer** après spike : si charge V1 = 1 poste local, une file in-process (ProcessPool + SQLite) pourrait supprimer Redis. Le spike éclairera. |

## Séquence décidée
1. **Builder → SPIKE** (R0) : valider untrunc sur un cas réel/synthétique, mesurer le modèle de coût, tester l'extraction de tranche en `-c copy`. **← ÉTAPE COURANTE**
2. **Architect** met à jour `03` (modèle de coût, cache artefact réparé) + corrige incohérences MAJ-5/9 selon résultats du spike.
3. **CounterPower** re-review du delta.
4. **Builder** implémente le pipeline V1 (`untrunc-moov` + `ffmpeg-remux`) sur des bases validées.
5. **DockerManager** conteneurise.

## En attente d'input utilisateur
- Disponibilité d'un **vrai fichier `.rsv` Sony corrompu** et/ou d'un **clip XAVC-S sain de référence** → augmenterait fortement la fidélité du spike. À défaut, spike synthétique (troncature du `moov` d'un MP4 généré).
