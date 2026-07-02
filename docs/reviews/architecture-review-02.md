# Re-review critique — Architecture MediaNotFound v2 (round 2, post-spike)

> Auteur : CounterPower. Portée : delta `docs/architecture/CHANGELOG.md` (v2) + relecture intégrale des 4 docs `01`-`04`, croisés avec `docs/reviews/architecture-review-01.md`, `docs/reviews/master-arbitration-01.md`, `docs/spike/spike-01-untrunc.md`.
> Posture : toujours adversariale. Le fait que le Spike 01 confirme la direction ne veut pas dire que tout le delta est propre — je cherche spécifiquement les régressions et incohérences introduites par la correction elle-même.

---

## Verdict global (résumé)

**Le point dur (BLOQ-2/BLOQ-3) est réellement résolu et cohérent sur les 4 livrables — c'est un vrai bon travail, adossé à une mesure concrète, pas à une nouvelle affirmation non testée.** Le fallback sans référence est honnêtement enterré. Les points MAJ-5/6/9/10 sont majoritairement traités.

Mais le round 2 introduit **son propre lot de trous**, plus deux **régressions de gouvernance** : deux décisions explicitement arbitrées par Master (**MAJ-7**, **MAJ-8**) n'ont **pas** été appliquées dans ce v2, alors qu'elles étaient listées comme « à corriger dans ce tour ». Le nouveau modèle de cache, en devenant le pilier central de l'architecture, **amplifie** l'impact de l'absence d'écriture atomique (MAJ-8) : un artefact de repair corrompu par un crash/annulation n'empoisonne plus un seul job, il empoisonne **toutes** les tranches et l'`extend` de ce fichier, silencieusement, jusqu'à purge manuelle. C'est le finding le plus sérieux de ce round.

**Voir verdict détaillé en fin de document.**

---

## 1. Statut de chaque point de la review-01

| Réf | Sujet | Statut | Note |
|---|---|---|---|
| BLOQ-1 | Hypothèse `.rsv` sourcée sur du marketing | **PARTIEL** | Le Spike 01 apporte enfin une preuve technique réelle (même si sur cas synthétique H.264). Mais `04` §1.2 garde son verdict *« HYPOTHÈSE CONFIRMÉE »* **mot pour mot depuis la v1**, sans renvoyer au spike ni à sa réserve — incohérence avec §3.1/§6 qui, eux, sont honnêtes (« cas synthétique, à re-tester sur un vrai `.rsv` »). Voir MIN-10 (nouveau). |
| BLOQ-2 | Coût repair O(fichier) vs O(tranche) | ✅ **RESOLU** | Tranché par mesure (spike), reformulé de façon cohérente dans `01`, `02`, `03`, `04`. Voir §2 ci-dessous. |
| BLOQ-3 | Cache artefact réparé | ✅ **RESOLU (le mécanisme)**, mais voir **BLOQ-5 (nouveau)** | Le design du cache est cohérent et bien documenté. Ce qui manque : l'écriture atomique de l'artefact caché (MAJ-8, jamais traité) — critique vu que l'artefact est maintenant partagé par tout. |
| BLOQ-4 | Référence souvent indisponible | ✅ **RESOLU (niveau produit)** | Politique « quasi obligatoire » assumée (`04` §3.5, `01` §[5]), direction Master (aider à *trouver* une référence) bien reflétée. |
| MAJ-1 | Path traversal | **NON RESOLU (docs)** | Décidé verbalement par Master (confinement obligatoire) mais rien d'écrit dans `03`. Pas bloquant pour démarrer si Builder applique la décision Master directement, mais la doc reste incomplète. |
| MAJ-2 | Auth locale non spécifiée | **NON RESOLU (docs)** | Idem — Master a tranché (V1 = localhost only, pas d'auth), mais `03` §1 dit toujours juste « auth locale » sans rien de plus. |
| MAJ-3 | Upload gros fichiers | **NON RESOLU (docs)** | `01` §[1] inchangé mot pour mot ; aucune trace écrite de « chemin monté = voie principale, upload déconseillé pour gros rushs » décidé par Master. |
| MAJ-4 | Rétention/disque | **NON RESOLU**, mais **accepté non-bloquant par Master** | Toujours « configurable » sans valeur par défaut. OK pour démarrer, à traiter en implémentation. |
| MAJ-5 | Variante MXF `DiagnosticCard` | ✅ **RESOLU** | `02` A2 a maintenant un mapping conteneur→vocabulaire explicite. Bon travail, correctement sourcé sur `04` §2.2. |
| MAJ-6 | Compat référence = estimation | ✅ **RESOLU** | « Probablement compatible » partout (`01`, `02`, `04`), plus de ✓ binaire garanti. |
| MAJ-7 | `moov-rebuild-ref` hors périmètre V1 | ❌ **NON RESOLU — décision Master ignorée** | Voir §4 ci-dessous. Absent de la liste « points traités » du CHANGELOG ; toujours listé sous « Méthodes V1 » en `04` §6. |
| MAJ-8 | Écriture atomique des sorties | ❌ **NON RESOLU — décision Master ignorée** | Voir BLOQ-5 ci-dessous. Impact amplifié par le nouveau design de cache. |
| MAJ-9 | Chaînage `/api/methods/applicable` | ✅ **RESOLU** | Bien câblé dans `01` §[5], `02` A3, `03` §5 — description cohérente sur les 3 livrables. |
| MAJ-10 | Scores de confiance qualitatifs | **PARTIEL** | Les tableaux produit (`04` §3, §4) sont bien passés en qualitatif. Mais `03` §2.1 (le contrat technique `RecoveryMethod.can_handle()`) garde `confidence: 0..1` en `float` **non touché** → contradiction interface vs doc produit. Voir MAJ-14 (nouveau). |
| MIN-1 | Calcul `source_hash` sur gros fichiers | **NON RESOLU — importance réévaluée à la hausse** | Voir MAJ-11 (nouveau) : ce n'est plus un détail mineur maintenant que tout le mécanisme de cache-hit en dépend. |
| MIN-2 | Pas d'avertissement de coût avant extension intégrale | ✅ **RESOLU PAR CONSTRUCTION** | Le problème a disparu : `extend` réutilise l'artefact caché et devient quasi instantané (`01` §[9]) — il n'y a plus rien à avertir. |
| MIN-3 | Taxonomie d'erreurs générique | **NON RESOLU** | Inchangé, `JOB_FAILED` toujours fourre-tout. Non bloquant. |
| MIN-4 | Config nginx SSE | **NON RESOLU** | Non traité, moins pertinent avec le compose à 2 services mais toujours à vérifier pour DockerManager. |
| MIN-5 | Redis+RQ vs in-process | ✅ **RESOLU** | Arbitré et réécrit proprement (`03` §8.1/§8.2/§8.4). Voir MAJ-15 (nouveau) pour un effet de bord non discuté. |
| MIN-6 | Vérifier la citation issue untrunc #211 | **NON RESOLU** | Toujours non vérifiée indépendamment. Faible priorité. |
| MIN-7 | Mécanisme de découverte de plugins trop vague | **NON RESOLU** | Texte inchangé (`03` §2.1). |
| MIN-8 | Streaming preview pendant job en cours ? | **NON RESOLU** | Toujours ambigu. |

---

## 2. BLOQ-2 / BLOQ-3 — vérification de cohérence demandée

**Verdict : cohérents entre les 4 livrables, plus aucune promesse « proportionnel à la tranche » résiduelle.**

- `01` §0 : reformulation complète et honnête (« Réparer une fois, prévisualiser autant qu'on veut »), avertissement explicite de ne pas promettre l'inverse.
- `02` B1/B2 : `SliceTabs` et `StatusPanel` décrivent tous deux le comportement cache-hit vs cache-miss, avec des libellés distincts (« Réparation… » vs « Source déjà réparée — extraction… »).
- `03` §2.2/§3.1/§3.2/§4.3/§7 : modèle de coût, clé de cache `(source_hash, method_id, reference_hash)`, dédup à deux niveaux, arborescence de stockage — tout est réécrit de façon mutuellement cohérente et cite explicitement le spike.
- `04` §3.1/§5/§6 : le modèle de coût et la clé de cache sont répétés à l'identique, aucune divergence de formulation.

Je n'ai trouvé **aucune** occurrence résiduelle de l'ancienne promesse « le preview 1 min est rapide parce qu'on ne traite qu'1 min » dans les 4 documents. C'est un nettoyage complet et sérieux du delta.

Cela dit, le mécanisme de cache lui-même a des trous **nouveaux** que je détaille en §5 (BLOQ-5, MAJ-11, MAJ-12) — la cohérence documentaire est bonne, mais « cohérent » ne veut pas dire « complet ».

---

## 3. `ffmpeg-remux` sans référence — requalification

**Verdict : correctement invalidé et assumé.**

- `04` §3.2 : statut clairement basculé de « fallback utile (confidence 0.4–0.6) » à « très faible / probablement inopérant », avec les résultats de mesure du spike cités en détail (toutes les variantes CLI testées, toutes échouent). Cantonné au cas résiduel « moov partiel/corrompu ».
- `04` §3.5 (nouveau) : politique « référence quasi obligatoire » énoncée noir sur blanc comme conséquence directe.
- `01` §[5] : réécrit en cohérence, bandeau d'alerte en tête de section, disparition de la promesse « best-effort sans référence ».
- `02` A3 : le champ référence est maintenant traité comme quasi-requis, avec aide à la recherche.
- `04` §4 (tableau de décision) : ligne « MP4/H.264/sans référence → NULLE ⛔ » explicite, plus de méthode Auto proposée dans ce cas.

Un seul relent : `04` §3.2 dit *« can_handle : applicable=false (ou confidence ≈ 0.05, quasi nul) »* — un chiffre numérique resurgit alors que le document affirme par ailleurs ne plus donner de scores fermes (§4 : « Aucun score numérique ferme à ce stade »). Contradiction mineure interne, à nettoyer (voir MIN-11).

La piste « sans référence externe » (`-rsv-ben`/`-sm search mdat`) est correctement cantonnée à « hors code V1, à spiker séparément » (`04` §3.6) — bon réflexe, pas de sur-promesse sur une piste non testée.

---

## 4. MAJ-5/6/9/10 et MIN-5 — vérification détaillée

- **MAJ-5 (variante MXF)** : ✅ traité proprement, mapping conteneur→vocabulaire clair en `02` A2, cohérent avec `04` §2.2.
- **MAJ-6 (compat = estimation)** : ✅ traité, cohérent sur `01`/`02`/`04`.
- **MAJ-9 (chaînage `/api/methods/applicable`)** : ✅ traité, et le point que je soulevais en review-01 (« le front ne doit pas improviser cette logique ») est repris texto dans `01` §[5] et `03` §5 — bonne boucle de feedback.
- **MAJ-10 (confiances qualitatives)** : **PARTIEL**. Les tableaux et le texte narratif de `04` sont bien passés en HAUTE/MOYENNE/BASSE/NULLE. Mais le **contrat d'interface** `RecoveryMethod` dans `03` §2.1 déclare toujours `confidence: 0..1` (float) sans note de correspondance vers les labels qualitatifs de `04`. Builder va devoir deviner : est-ce que `can_handle()` retourne un float que l'UI/backend convertit ensuite en label, ou un enum directement ? Les deux docs se contredisent sur le type de la donnée à la source. **C'est un vrai trou d'intégration, pas juste un oubli cosmétique** — c'est exactement le genre d'incohérence entre livrables que review-01 demandait d'éliminer, et une nouvelle est apparue à sa place.
- **MIN-5 (in-process vs Redis)** : ✅ arbitrage clair et bien justifié (`03` §8.4), au regard des mesures du spike (jobs courts, pas de multi-utilisateur). Voir cependant MAJ-15 : un effet de bord non discuté (fusion API+worker dans un seul conteneur `app`).

---

## 5. NOUVEAUX PROBLÈMES introduits par le delta v2

### BLOQ-5 (nouveau) — Pas d'écriture atomique de l'artefact réparé : le cache peut être empoisonné silencieusement
C'est **exactement MAJ-8** de la review-01, mais son impact change de nature avec le nouveau design de cache (BLOQ-3). En v1, un job annulé/crashé en cours d'écriture ne pouvait corrompre que **sa propre sortie**. En v2, l'artefact réparé est **la ressource partagée** dont dépendent : les 3 tranches (1/5/full), l'`extend`, et toute relance de la même conf (`03` §3.2 : *« Réutilisé par TOUT »*).

Si `repair` est tué (annulation utilisateur, OOM, crash du sous-process untrunc) pendant l'écriture de `/<work>/{source_hash}/{method}/{reference_hash}/repaired.mp4`, et que rien ne garantit un pattern temp-file + rename atomique, alors :
- soit le fichier partiel reste au chemin canonique et un job ultérieur (qui vérifie juste « le fichier existe-t-il à cette clé de cache ? ») le traite comme un **cache hit valide** → sert une vidéo tronquée/corrompue, silencieusement, pour **toutes** les tranches et l'intégrale, sans jamais retenter le repair ;
- soit il faut une logique de nettoyage/retry qui n'est décrite nulle part dans `03`.

**C'est un bug de correction de données (pas juste une question de robustesse cosmétique), amplifié directement par l'architecture de cache que ce round 2 vient d'introduire.** Master avait explicitement classé MAJ-8 dans les points « à corriger dans `01/02/03` au tour de révision archi post-spike » (`master-arbitration-01.md`) — ce n'est pas fait, et ce n'est même pas mentionné dans le CHANGELOG v2.

**Recommandation** : imposer dans `03` §3.2/§7 le pattern « écrire dans un chemin temporaire, renommer atomiquement vers le chemin canonique seulement après un `validate` réussi » ; le Result Store ne doit indexer un triplet `(source_hash, method_id, reference_hash)` comme disponible qu'après ce rename. C'est un ajout de quelques lignes à la doc — pas besoin d'un nouveau spike, mais **Builder ne doit pas coder le cache sans ça**, sous peine de devoir tout refaire après coup.

### MAJ-11 (nouveau, ex-MIN-1 réévalué) — Coût de calcul du `source_hash`/`reference_hash` non spécifié, alors qu'il conditionne maintenant la promesse « cache hit instantané »
En review-01, ce point (MIN-1) était mineur : un hash lent sur un gros fichier ralentissait juste l'enregistrement initial. **Ce n'est plus mineur.** Le nouveau pilier BLOQ-3 promet explicitement (`01` §7, `02` B2) que si la source a déjà été réparée, l'étape « Réparation » est **sautée** et la tranche apparaît en ~0,2 s. Mais pour savoir *si* elle a déjà été réparée, il faut d'abord calculer `source_hash` (et `reference_hash`) pour interroger le cache — et si ce hash est un SHA-256 intégral sur un rush de 30-80 Go, ce calcul est lui-même **O(fichier)**, potentiellement plusieurs minutes (le spike lui-même mesure ~1 GB/s en cache RAM, moins sur disque réel).

**Conséquence concrète** : sur un rush volumineux, même un **cache hit** pourrait coûter plusieurs minutes (le temps de hasher) avant de révéler qu'il n'y avait rien à refaire — ce qui contredit directement la promesse « source déjà réparée → extraction en ~0,2 s » de `01` §7 / `02` B2. Aucun des 4 documents ne précise à quel moment le hash est calculé (à l'enregistrement du fichier ? à chaque création de job ?) ni sa méthode (hash intégral vs hash partiel taille+échantillons).

**Recommandation** : spécifier dans `03` un hash **non intégral** pour la clé de cache (ex. taille + hash de N échantillons répartis dans le fichier), calculé **une fois à l'enregistrement** (`POST /api/media`) et mis en cache lui-même dans le Media Registry — pas recalculé à chaque `POST /api/jobs`.

### MAJ-12 (nouveau) — Pas de verrou / suivi d'« in-flight » sur la clé de cache : risque de double repair concurrent
Le nouveau modèle fait dépendre plusieurs jobs potentiellement simultanés (1 min, 5 min, intégrale — via les `SliceTabs`, ou un `extend` lancé vite après) de la **même** clé de cache `(source_hash, method_id, reference_hash)`. Rien dans `03` §4.3 (dédup) ne couvre le cas où **deux jobs référençant la même clé sont créés avant que le premier `repair` ne soit terminé** — la dédup décrite ne gère que le cas « déjà `succeeded` », pas « en cours ».

Avec le choix in-process `ProcessPoolExecutor` (MIN-5), sans verrou explicite, un double-clic rapide sur deux onglets `SliceTabs` avant la fin du premier repair pourrait déclencher **deux process workers indépendants qui repairent la même source en parallèle**, écrivant potentiellement vers le même chemin de sortie simultanément (aggravant BLOQ-5) et gaspillant du CPU/IO pour rien.

**Recommandation** : ajouter un registre d'« in-flight repairs » (par clé de cache) dans `03` §4.3 — un second job ciblant une clé déjà en cours de réparation doit **s'attacher** au job de repair existant (même `job_id` de repair sous-jacent, ou statut « en attente du repair en cours ») plutôt que d'en lancer un second.

### MAJ-13 (nouveau) — MAJ-7 (sortie de `moov-rebuild-ref` du périmètre V1) : décision Master non appliquée
Master a tranché sans ambiguïté (`master-arbitration-01.md`, ligne MAJ-7) : *« Sorti du périmètre code V1 (comme mxf-rebuild). V1 = untrunc-moov + ffmpeg-remux uniquement. »*

Dans `04` v2 :
- §3.3 décrit toujours `moov-rebuild-ref` sans aucune mention « hors périmètre V1 », contrairement à §3.4 (`mxf-rebuild`) qui porte explicitement le tag *« (V1.1, hors périmètre code V1) »*.
- §6 (résumé) liste toujours *« Méthodes V1 : untrunc-moov (phare, validée) ; ffmpeg-remux (rétrogradée...) ; moov-rebuild-ref (extension) ; mxf-rebuild (roadmap) »* — `moov-rebuild-ref` reste catégorisé comme faisant partie du périmètre V1, seul `mxf-rebuild` est étiqueté roadmap.
- Le CHANGELOG v2 ne mentionne **pas** MAJ-7 dans sa liste de « points de review traités », alors que Master l'avait explicitement rangé dans le lot à corriger.

**C'est une décision d'arbitrage qui a été perdue en route entre Master et Architect.** Ce n'est pas un désaccord technique — Master a tranché, l'Architect ne l'a simplement pas reporté dans les fichiers. Peu coûteux à corriger (ajouter le tag et déplacer la ligne du résumé), mais révélateur : si un round de correction en oublie deux (MAJ-7 et MAJ-8) sur onze items, ça vaut le coup de vérifier qu'aucun autre arbitrage Master n'a été silencieusement laissé de côté avant de considérer la doc comme stable.

### MAJ-14 (nouveau, détail de MAJ-10) — Type de `confidence` incohérent entre `03` (contrat technique) et `04` (doc produit)
Voir §4 ci-dessus. `03` §2.1 : `Applicability -> { applicable: bool, confidence: 0..1, reason: string }` (float) — jamais retouché. `04` : confiances désormais purement qualitatives (HAUTE/MOYENNE/BASSE/NULLE), avec la phrase explicite *« Aucun score numérique ferme à ce stade »*.

**Recommandation** : trancher dans `03` — soit `confidence` reste un float interne (calculé par chaque plugin) et c'est la **couche de présentation** qui le mappe vers un label qualitatif pour l'UI/le tableau de décision (le plus probable, et le plus simple à coder), soit le contrat change de type. Il faut que `03` le dise explicitement, sinon Builder tranchera arbitrairement et créera une nouvelle source d'incohérence avec `04`.

### MAJ-15 (nouveau) — Fusion API + worker dans un seul conteneur `app` : perte d'isolation non discutée en tant que telle
L'arbitrage MIN-5 porte sur *Redis vs in-process*, mais son application concrète (`03` §8.2) va plus loin : elle **fusionne aussi** le service API léger et le worker ffmpeg/untrunc lourd dans un seul conteneur `app` — deux services distincts en v1 (`api` + `worker`), réduits à un seul. C'était pourtant un point fort explicitement salué en review-01 (isolation, blast-radius, scaling indépendant du worker CPU-intensif).

Ce sont **deux décisions différentes** : (a) abandonner Redis comme broker distribué, (b) fusionner API et worker dans le même processus/conteneur. On peut abandonner Redis **sans** fusionner les conteneurs — un `ProcessPoolExecutor` + SQLite peut très bien tourner dans un conteneur `worker` séparé de l'API, communiquant via la base SQLite partagée sur le volume, sans broker. La doc ne discute pas ce choix comme un arbitrage à part ; il est absorbé silencieusement dans MIN-5.

**Conséquence concrète pour la V1** : si `untrunc`/`ffmpeg` fait fuiter de la mémoire ou crashe sur un gros rush, ça peut dégrader/killer le même processus qui sert l'API HTTP et le SSE de progression pour d'autres jobs en cours — pas catastrophique pour un outil mono-utilisateur local, mais ce n'est pas neutre, et ce n'est pas la conséquence que MIN-5 annonçait résoudre.

**Recommandation** : ce n'est pas forcément une mauvaise décision pour une V1 volontairement simple — mais elle doit être **assumée explicitement** dans `03` §8.2/§8.4 comme un compromis choisi (avec la option « `app` + `worker` séparés sans Redis » citée comme alternative tracée), pas comme un sous-produit non commenté de l'abandon de Redis.

---

## Problèmes mineurs (nouveaux)

- **MIN-9** — `ProcessPoolExecutor` (stdlib Python) ne permet pas d'annuler une tâche déjà démarrée via son API standard (`Future.cancel()` échoue silencieusement si le worker a déjà commencé). `03` §8.4 promet pourtant l'annulation par « kill du sous-process ffmpeg/untrunc » — c'est faisable, mais ça demande de gérer soi-même les handles `subprocess.Popen` par job en dehors de l'API native du pool, ce que la doc ne précise pas. Piège d'implémentation à anticiper pour Builder.
- **MIN-10** — `04` §1.2 garde le titre *« Verdict : HYPOTHÈSE CONFIRMÉE »* inchangé depuis la v1 (sourcé sur du contenu marketing), alors que §3.1/§6 du même document, réécrits post-spike, sont bien plus mesurés (« validé sur cas synthétique... à re-tester sur un vrai `.rsv` »). Un lecteur qui s'arrête à §1.2 repart avec une confiance mal calibrée. À aligner : §1.2 devrait renvoyer explicitement au Spike 01 et reprendre la même réserve.
- **MIN-11** — `04` §3.2 fait resurgir un score numérique (« confidence ≈ 0.05 ») dans un paragraphe censé illustrer le passage aux confiances qualitatives (MAJ-10). Contradiction interne mineure à `04` lui-même.
- **MIN-12** — Aucune règle écrite sur l'interaction entre la politique de rétention (encore non spécifiée, MAJ-4) et un artefact réparé **en cours de lecture** par un job de slice-copy — un nettoyage disque mal synchronisé pourrait supprimer un artefact pendant qu'un `-c copy` le lit. Mineur pour une V1 mono-utilisateur, mais à noter pour l'implémentation de la politique de rétention.
- **MIN-13** — `01` §5 avertit bien que *changer de méthode* redéclenche une réparation complète, mais ne dit rien explicitement sur le cas où l'utilisateur **change juste la référence** en gardant la même méthode (ex. après un échec, il fournit une référence différente) — ce cas déclenche aussi un repair complet (nouvelle clé de cache), et mérite le même avertissement UX explicite que le changement de méthode.

---

## 6. Recommandations pour le Builder (ordre d'exécution)

1. **Avant de coder le Result Store / cache** : implémenter le pattern temp-file + rename atomique pour l'artefact réparé (BLOQ-5/MAJ-8) — non négociable, c'est un bug de corruption silencieuse sinon.
2. **En même temps** : ajouter un verrou / registre « repair en cours » par clé de cache `(source_hash, method_id, reference_hash)` pour éviter les doubles repairs concurrents (MAJ-12).
3. **Avant de calculer les clés de cache** : choisir explicitement une stratégie de hash non intégrale (taille + échantillons) pour `source_hash`/`reference_hash`, calculée une fois à l'enregistrement, pas à chaque job (MAJ-11) — sinon la promesse « cache hit instantané » ne tient pas sur les gros rushs.
4. **Scope V1** : ne pas implémenter `moov-rebuild-ref` (confirmé par Master, MAJ-7) — considérer `04` §3.3 comme roadmap malgré la formulation actuelle du document.
5. **Contrat `RecoveryMethod`** : demander à l'Architect de trancher le type de `confidence` (float interne mappé vs enum direct) avant de coder l'interface plugin (MAJ-14) — sinon Builder devine et re-divergence garantie avec `04`.
6. **Annulation de job** : prévoir explicitement la gestion des handles `subprocess.Popen` pour un kill propre, ne pas compter sur `ProcessPoolExecutor.cancel()` seul (MIN-9).
7. **Path confinement + posture auth V1** : appliquer directement les décisions Master (MAJ-1/2, confinement à la racine du volume, pas d'auth en V1 localhost-only) même si `03` n'a pas encore été mis à jour littéralement — ne pas attendre un 3e tour de doc pour ça.
8. Le reste (MAJ-4, MIN-3/4/6/7/8/12/13) : non bloquant, à traiter au fil de l'implémentation comme déjà arbitré par Master.

---

## VERDICT

# 🟡 GO CONDITIONNEL

Le Builder **peut démarrer l'implémentation du pipeline V1** (`untrunc-moov` + cache d'artefact réparé + `ffmpeg-remux` résiduel). La question qui justifiait de bloquer le round précédent — est-ce que le modèle de coût/cache tient la route ? — **est tranchée par une mesure réelle**, pas par une nouvelle affirmation non vérifiée. C'est un vrai déblocage.

Ce n'est **pas** un GO inconditionnel, pour deux raisons :

1. **BLOQ-5 (écriture atomique manquante)** doit être traité *dans le code du Builder dès la première version du Result Store* — ce n'est pas négociable, ni un « à améliorer plus tard » : sans ça, le mécanisme de cache que ce round 2 vient de valider peut silencieusement servir des sorties corrompues, indéfiniment, à toutes les tranches d'un fichier. Ça n'exige pas de retour à l'Architect — c'est un ajout mécanique que le Builder peut porter lui-même en implémentant §3.2/§7 de `03`.
2. **MAJ-7 et MAJ-8 ont révélé que des décisions Master peuvent se perdre entre l'arbitrage et l'implémentation.** Avant de considérer l'architecture comme stable, je recommande à Master de vérifier qu'aucun autre point de `master-arbitration-01.md` n'a été silencieusement oublié — je n'ai trouvé que ces deux-là, mais je n'ai pas de vue sur d'éventuels échanges hors docs.

Aucun des points restants (MAJ-1/2/3 non écrits, MAJ-11/12/14, MIN-*) ne justifie un 3e tour de review architecture avant de coder — ce sont soit des décisions déjà prises par Master que Builder peut appliquer directement, soit des détails d'implémentation que Builder doit trancher en codant (avec, pour MAJ-14, une clarification rapide à demander à l'Architect en parallèle, pas un blocage).

**RE-REVIEW TERMINÉE**
