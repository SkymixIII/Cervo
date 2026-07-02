# Review critique — Architecture MediaNotFound (livraison Architecte, round 1)

> Auteur : CounterPower. Portée : `docs/PROJECT_BRIEF.md` + `docs/architecture/01-ux-flows.md`, `02-ui-screens.md`, `03-backend-architecture.md`, `04-recovery-methods-rsv.md`.
> Posture : adversariale, pas de validation par défaut. Chaque point bloquant doit être résolu ou explicitement arbitré par Master avant que Builder ne code dessus.

---

## Verdict global

Le travail est **structurellement solide et bien documenté**, mais repose sur **une hypothèse centrale non vérifiée en pratique** (le comportement réel d'`untrunc`) qui, si elle est fausse, **fait s'effondrer la proposition de valeur du produit** (« preview 1 min rapide avant intégrale »). Il y a aussi une **incohérence interne non résolue** entre `03` et `04` sur le coût du repair, plusieurs **trous d'intégration** entre les livrables UX/UI/backend, et un **risque produit** sur la disponibilité réelle du fichier de référence pour l'utilisateur cible. Je recommande de **ne pas lancer le développement complet du pipeline avant un spike de validation technique** (voir Recommandations, R0).

---

## Points forts

- Séparation des responsabilités entre les 4 documents claire et navigable ; peu de redondance inutile.
- L'interface `RecoveryMethod` (`03` §2.1 : `can_handle`/`prepare`/`run`/`capabilities`) est un bon contrat d'extensibilité — c'est exactement le genre d'abstraction qui justifie son existence ici (plusieurs méthodes concrètes déjà prévues, formats futurs annoncés).
- Ton UX honnête sur les cas d'échec (« pas de fausse promesse », `01` §3, `04` §5.2) — cohérent avec la persona stressée définie en `01` §0. C'est une qualité produit réelle, pas un vœu pieux : ça se retrouve concrètement dans le design du `hint` contractuel de l'enveloppe API (`03` §6).
- Reconnaissance explicite et sourcée de la limite H.265/XAVC-HS d'untrunc, et de la divergence MP4 (atomes) vs MXF (KLV/partitions) — signe que la recherche n'est pas restée superficielle sur le sujet le plus piégeux du domaine.
- Historique des tentatives avec dédup des méthodes déjà essayées (`01` §4, `02` C1) répond bien au besoin réel (ne pas refaire deux fois la même chose sous stress).
- Découpage Docker api (léger) / worker (lourd, ffmpeg+untrunc) est une séparation de bon sens pour isoler et scaler la partie CPU-intensive.

---

## Problèmes BLOQUANTS

### BLOQ-1 — L'hypothèse `.rsv` est déclarée « CONFIRMÉE » sur des sources de seconde main, jamais testée en réel
`04` §1.3 cite exclusivement des pages marketing d'outils de récupération payants (4DDiG, Wondershare Repairit, aeroquartet, fix.video) + une issue GitHub. Aucune de ces sources n'est une documentation technique primaire Sony, et les sites d'outils commerciaux ont un biais structurel : ils décrivent le problème en des termes qui vendent leur solution, pas nécessairement en des termes techniquement exacts. Le document affiche pourtant un verdict « HYPOTHÈSE CONFIRMÉE » avec un niveau de certitude que les sources ne justifient pas.
**Risque** : toute l'architecture (pipeline, interface `RecoveryMethod`, modèle de coût preview) est bâtie sur cette hypothèse sans qu'un seul fichier `.rsv` réel (ou un `.mp4` tronqué synthétiquement) n'ait été passé dans `untrunc` pour vérifier que ça fonctionne effectivement.
**Recommandation** : downgrade le statut en « hypothèse plausible, forte présomption » et exiger un spike technique avant d'investir dans la construction du pipeline complet (voir R0).

### BLOQ-2 — Contradiction non résolue sur le coût du `repair` : partiel ou intégral ?
`03` §3.2 affirme : *« pour untrunc-moov, il suffit de reconstruire la portion de la table d'échantillons couvrant la tranche »* — et fonde là-dessus la promesse centrale du produit (*« le coût du traitement doit être proportionnel à la tranche demandée »*, `03` §3.1, et le *« Preview d'abord »* de `01` §0).

C'est très probablement **faux dans les faits** : `untrunc` reconstruit le `moov` en comparant la structure d'un fichier de référence *complet* au `mdat` corrompu — ce n'est pas un outil conçu pour produire une table d'échantillons partielle à la demande. Rien dans `04` (qui documente spécifiquement le comportement d'untrunc) ne vient étayer cette affirmation de reconstruction partielle ; elle apparaît uniquement dans `03`, sans référence croisée. **C'est une incohérence entre livrables** : `04` (l'expert du sujet) ne dit jamais que le repair est partiel, `03` (l'archi système) le suppose pour que son modèle de coût tienne.

**Conséquence si l'hypothèse `03` est fausse** : reconstruire le `moov` coûte le même temps quel que soit le slice demandé (1 min ou intégrale) → le pilier UX n°1 du produit (*« on ne recompile jamais tout un rush pour découvrir que la méthode ne marche pas »*, `01` §0) ne tient plus pour un rush de 40 min en 4K. L'utilisateur attend le même temps pour un test 1 min que pour l'intégrale.

**Recommandation** : trancher explicitement, avant tout code pipeline, si le repair est O(taille fichier) ou O(slice). Si O(fichier), la promesse doit être reformulée honnêtement (« le repair prend le même temps, mais on ne paie l'encodage/export que sur la tranche ») et le design du pipeline + les textes UX (`01` §0, `03` §3.1) doivent être corrigés en conséquence plutôt que de vendre une promesse de coût qu'on ne peut pas tenir.

### BLOQ-3 — Pas de cache de l'artefact « repair » réutilisable entre slices, alors que c'est la seule chose qui rendrait la promesse d'itération rapide vraie
Le `Result Store` (`03` §1, §3.2) cache uniquement la **sortie finale** indexée par `(source_hash, method_id, media_scope, slice)`. Le pipeline (`03` §2.2) exécute `probe → repair → slice-encode → validate → publish` à chaque job. Rien n'indique qu'un `repair` déjà effectué pour le slice « 1min » soit réutilisé quand l'utilisateur clique ensuite sur l'onglet « 5min » ou « Intégrale » (`02` B1 `SliceTabs`) — chaque clic sur un nouvel onglet crée un nouveau job (`03` §5 `POST /api/jobs`), qui repart de `probe→repair`.

Si BLOQ-2 confirme que `repair` est coûteux et indépendant du slice, alors **chaque changement de tranche refait le travail le plus cher**, ce qui est exactement ce que le produit prétend éviter (`01` §5, la « boucle d'itération résumée » vendue comme *« peu coûteuse en calcul »*).

**Recommandation** : introduire explicitement un niveau de cache intermédiaire — un artefact « source réparée » (post-`repair`, pré-`slice-encode`) indexé par `(source_hash, method_id)` seul, réutilisé par tous les slice-encodes et par l'endpoint `extend`. Ça doit être écrit dans `03` avant que Builder ne code le pipeline, sinon il codera la version naïve qui re-répare à chaque fois.

### BLOQ-4 — La méthode phare dépend d'un fichier de référence que la persona cible n'a probablement pas sous la main
`04` §3.1 fait d'`untrunc-moov` (référence obligatoire, confidence 0.9) la méthode prioritaire. Mais la persona (`01` §0) est un utilisateur qui « vient de perdre un rush » — carte défaillante, coupure batterie, crash pendant le tournage. Rien ne garantit qu'il dispose d'un **autre clip sain de la même caméra avec les mêmes réglages exacts** — c'est même statistiquement le scénario défavorable le plus fréquent (premier clip du tournage, réglages changés en cours de session, carte entièrement corrompue donc pas d'autre clip sur cette carte). Le fallback sans référence (`ffmpeg-remux`, confidence 0.4–0.6, best-effort, ne restaure pas forcément la vidéo complète) est nettement plus faible.

**Risque produit** : pour une part significative des cas d'usage réels, la méthode « recommandée » du mode Auto ne sera simplement pas disponible, et l'utilisateur atterrit sur un fallback dégradé — sans que ce risque soit assumé nulle part dans les docs (aucune mention de fréquence attendue, aucun plan B produit type « suggérer d'autres emplacements où chercher une référence : cloud backup, autre carte, clip précédent du même shoot »).

**Recommandation** : Master/Architect doivent trancher consciemment ce risque produit (accepté tel quel, ou UX à enrichir pour aider l'utilisateur à *trouver* une référence — ex. scanner d'autres fichiers du même dossier/carte pour proposer automatiquement des candidats compatibles).

---

## Problèmes MAJEURS

### MAJ-1 — Path traversal / lecture arbitraire de fichiers via `POST /api/media`
L'utilisateur saisit un **chemin** de fichier (`01` §[1], `02` A1). Rien dans `03` (API Gateway : *« validation, auth locale, routing »*) ne mentionne un confinement à une racine de volume autorisée. Même en usage « local de confiance », le brief autorise l'exposition LAN (`01` §0 : *« LAN / localhost »*). Sans sandboxing explicite du chemin à la racine du volume Docker monté, l'API accepte de facto la lecture de n'importe quel fichier lisible par le conteneur.
**Recommandation** : imposer et documenter un confinement strict (resolve + vérif que le chemin final reste sous la racine `media` montée) avant que Builder n'implémente `POST /api/media`.

### MAJ-2 — « Auth locale » mentionnée une fois, jamais spécifiée
`03` §1 (tableau des services) mentionne *« auth locale »* comme responsabilité de l'API Gateway, mais aucun mécanisme n'est décrit nulle part (pas de modèle de session, pas de route, pas de champ dans l'enveloppe de réponse). Vu l'exposition LAN annoncée en `01`, c'est un trou, pas un détail.
**Recommandation** : soit expliciter que la V1 n'a **aucune auth** (acceptable si strictement localhost, mais alors dire explicitement que l'exposition LAN est hors périmètre V1), soit spécifier le mécanisme minimal (ex. token statique en variable d'env).

### MAJ-3 — Upload navigateur non dimensionné pour des rushs de plusieurs dizaines de Go
Les rushs 4K XAVC-HS (a1, FX6) peuvent facilement dépasser 20-30 Go. `02` A1 présente « upload » comme option équivalente au « chemin monté », sans mention de chunked/resumable upload, ni de limite de taille, ni de timeout. Un upload HTTP classique (input file + POST) sur un fichier de cette taille est fragile (timeout proxy, perte de connexion = tout à refaire).
**Recommandation** : soit restreindre clairement l'upload navigateur à des tailles raisonnables et pousser le chemin monté comme voie principale pour les gros rushs, soit spécifier un upload chunké/resumable dès la V1 si l'upload doit rester une voie sérieuse.

### MAJ-4 — Politique de rétention/disque non définie au-delà de « configurable »
`03` §7 : *« Nettoyage : politique de rétention configurable »* — aucune valeur par défaut, aucun garde-fou. Avec du cache multiplié par `(source × méthode × scope × slice)` et des sorties intégrales conservées, un usage normal (plusieurs méthodes essayées sur plusieurs rushs 4K) peut remplir un disque local rapidement.
**Recommandation** : fixer une politique par défaut concrète pour la V1 (ex. TTL sur les previews non intégrales, alerte si volume < seuil) plutôt que de laisser « configurable » comme non-réponse.

### MAJ-5 — Incohérence `02` ↔ `04` : le `DiagnosticCard` est câblé pour du MP4 (moov/mdat), pas pour du MXF
`02` A2 spécifie les badges du diagnostic en dur : *« mdat détecté ✅, moov manquant ⚠️, conteneur MP4/MXF »* — mais `04` §2.2 explique que MXF n'a **ni `moov` ni `mdat`** (structure KLV, Header/Body/Footer Partitions, Index Table). Si un fichier MXF est chargé, le composant tel que spécifié en `02` afficherait un vocabulaire qui ne s'applique pas à ce conteneur.
**Recommandation** : `02` doit prévoir une variante du `DiagnosticCard` pour MXF (ou un mapping conteneur→vocabulaire) avant que Builder ne code un composant qui suppose implicitement MP4 partout.

### MAJ-6 — Vérification de compatibilité référence↔source trop naïve pour la promesse « pas de faux espoir »
`04` §5.2 pose en principe que la validation de compatibilité doit éviter les faux espoirs. Mais `01` §[5] et `04` §3.1 ne vérifient que codec/profil/résolution/fps. Le fonctionnement réel d'`untrunc` est réputé sensible à des paramètres plus fins (version firmware/encodeur, structure de GOP, bitrate mode) — deux fichiers « compatibles » selon ces 4 champs peuvent quand même faire échouer untrunc. Un badge `✓ compatible` qui s'avère ensuite faux est pire, du point de vue utilisateur stressé, qu'une absence de vérification honnêtement affichée comme « best guess ».
**Recommandation** : soit renforcer la vérification, soit — plus réaliste pour la V1 — afficher le badge comme une estimation (« probablement compatible ») et non une garantie binaire.

### MAJ-7 — `moov-rebuild-ref` (H.265 expérimental) est un projet de rétro-ingénierie à part entière, injecté dans le périmètre V1 sans que les deux méthodes plus simples aient été validées
`04` §3.3 propose d'écrire, en V1, une reconstruction maison de la sample table (`stco/stsz/stts/stss`) pour tenter le H.265 là où untrunc échoue. C'est un travail substantiel et risqué (format propriétaire, pas d'outil de référence existant qui fonctionne), empilé au-dessus de deux méthodes (`untrunc-moov`, `ffmpeg-remux`) elles-mêmes non encore prouvées en pratique (cf BLOQ-1).
**Recommandation** : sortir `moov-rebuild-ref` du périmètre de code V1 (comme `mxf-rebuild` l'est déjà, `04` §3.4) — le déclarer en roadmap, pas en développement immédiat. Concentrer le budget V1 sur la validation réelle d'`untrunc-moov` + `ffmpeg-remux`.

### MAJ-8 — Pas d'écriture atomique garantie pour les sorties → risque de servir un fichier partiel après annulation/crash
`03` §4.3 décrit l'annulation comme un « arrêt propre du sous-process », mais ne précise pas que la sortie doit être écrite dans un fichier temporaire puis renommée atomiquement à la fin. Si `untrunc`/`ffmpeg` est tué en cours d'écriture et que le `Result Store` traite le fichier présent sur disque comme la sortie du job, un job `canceled`/`failed` pourrait laisser un fichier corrompu potentiellement servi par erreur (ex. cache incohérent si la logique de dédup vérifie juste la présence du fichier plutôt que le statut `succeeded`).
**Recommandation** : imposer explicitement le pattern temp-file + rename atomique dans `03`, et que le Result Store n'indexe un fichier comme disponible qu'après un statut `succeeded` confirmé.

### MAJ-9 — Chaînon UX manquant : comment le front sait-il s'il faut afficher `ReferenceFileInput` en mode Auto ?
`02` A3 affiche `ReferenceFileInput` conditionnellement « si la méthode requiert une référence », mais en mode Auto (par défaut, `03` §5 : `method_id: "auto"`), la méthode concrète n'est résolue que **côté serveur au moment du job**. Le front doit donc interroger `GET /api/methods/applicable?source={id}` pour connaître par avance la méthode la plus probable et décider d'afficher le champ référence — ce chaînage n'est décrit nulle part explicitement entre `01`/`02`/`03`.
**Recommandation** : ajouter une ligne explicite dans `01` étape [5] ou `03` précisant que le front appelle `/api/methods/applicable` dès le diagnostic pour piloter l'affichage conditionnel, avant que Builder n'improvise ce détail.

### MAJ-10 — Scores de confiance présentés avec une précision non justifiée
`04` (0.9, 0.5, 0.4–0.6, 0.3…) affiche des chiffres à une décimale sans méthodologie de calibration (pas de jeu de test, pas de mesure). Present comme une réponse ferme dans une table de décision (`04` §4), ça donne une fausse impression de rigueur qui pourrait guider des décisions produit (tri du mode Auto, UI) sur des bases arbitraires.
**Recommandation** : soit documenter que ce sont des estimations qualitatives (haute/moyenne/basse) à ce stade, soit prévoir de les recalibrer après les premiers tests réels (cf R0).

---

## Problèmes MINEURS

- **MIN-1** — Calcul de `source_hash` (`03` §3.2, §4.3) non spécifié pour de gros fichiers : un hash intégral SHA-256 sur 30 Go coûte du temps I/O à chaque enregistrement. Suggestion : hash partiel (taille + échantillons début/fin) pour la V1.
- **MIN-2** — Aucun avertissement de coût (temps/espace disque) avant de lancer l'extension à l'intégrale (`01` §[9]) sur un rush long — juste un bouton. Un simple texte d'estimation serait cohérent avec la posture « pas de fausse promesse ».
- **MIN-3** — Taxonomie d'erreurs (`03` §6) trop générique : pas de code dédié pour un crash de l'outil (`untrunc`/`ffmpeg` segfault) ni pour un manque d'espace disque — tout tombe dans `JOB_FAILED` générique, ce qui affaiblit le `hint` contractuel que le doc lui-même érige en principe.
- **MIN-4** — Le SSE (`03` §4.3, §8.1) nécessite une config nginx spécifique (`proxy_buffering off`) si le service `web` proxy l'API — non mentionné, DockerManager risque de le découvrir en prod.
- **MIN-5** — Stack Redis + RQ/Celery pour un outil V1 mono-utilisateur local mérite d'être challengée : une file de jobs en process (ex. `ProcessPoolExecutor` + table SQLite) éliminerait un service Docker entier (Redis) et un broker à opérer, pour une charge V1 qui reste un seul poste local. Le choix actuel n'est pas absurde (utile si scaling futur), mais il est présenté comme acquis sans peser le compromis simplicité vs scalabilité anticipée.
- **MIN-6** — La citation précise « issue untrunc #211 » (`04` §1.3) doit être revérifiée avant d'être reprise dans un support utilisateur ou une PR — je ne peux pas la valider depuis cette review.
- **MIN-7** — Mécanisme de découverte de plugins (`03` §2.1 : *« déclaration statique + point d'extension »*) trop vague pour Builder : préciser le mécanisme concret (entry points Python, registre par décorateur, fichier de config) avant l'implémentation.
- **MIN-8** — Pas clair si `GET /api/jobs/{id}/preview` peut streamer une sortie partielle pendant que le job tourne encore, ou seulement après `succeeded`. À clarifier pour éviter une divergence d'interprétation front/back.

---

## Récapitulatif des incohérences entre livrables

| Incohérence | Documents concernés |
|---|---|
| Coût du `repair` : « partiel » selon `03`, jamais confirmé (voire contredit implicitement) par `04` | `03` §3.2 vs `04` |
| Vocabulaire diagnostic MP4 (`moov`/`mdat`) câblé en dur dans l'UI alors que MXF a une structure différente | `02` A2 vs `04` §2.2 |
| Affichage conditionnel du champ référence dépend d'une résolution de méthode qui n'existe que côté serveur en mode Auto | `01` [5] / `02` A3 vs `03` §5 |
| `moov-rebuild-ref` traité comme développement V1 dans `04` alors que sa complexité le rapproche plus du statut roadmap donné à `mxf-rebuild` | `04` §3.3 vs §3.4 |

---

## Recommandations concrètes pour le Builder (ordre d'exécution suggéré)

**R0 — Spike de validation AVANT tout code d'infrastructure (bloquant, à faire en premier)**
Avant de coder API/Job Manager/Worker Pool/plugins : prendre (ou générer synthétiquement, en tronquant le `moov` d'un MP4 XAVC-S existant) un fichier `.rsv`-like + une référence saine, lancer `untrunc` en CLI brut, et mesurer :
1. Est-ce que ça marche du tout sur un cas réel/synthétique proche de XAVC-S ?
2. Le temps de `repair` est-il proportionnel à la taille du `mdat` traité, ou au slice visé ? (répond à BLOQ-2)
3. Peut-on extraire une tranche courte en `-c copy` après repair sans réencoder ? (valide le pipeline `03` §3)

Ne pas construire le pipeline modulaire complet tant que ce spike n'a pas confirmé les hypothèses de coût — sinon on architecture une promesse produit qu'on ne sait pas tenir.

**R1** — Trancher et documenter explicitement le modèle de coût du `repair` (BLOQ-2) et introduire le cache d'artefact « source réparée » réutilisable entre slices (BLOQ-3) dans `03` avant d'implémenter le `Job Manager`.

**R2** — Sortir `moov-rebuild-ref` du périmètre de code V1 (MAJ-7) ; se concentrer sur `untrunc-moov` + `ffmpeg-remux`.

**R3** — Spécifier le confinement des chemins (`MAJ-1`) et la politique d'auth V1 (`MAJ-2`) avant d'exposer `POST /api/media` au-delà de localhost.

**R4** — Ajouter la variante MXF du `DiagnosticCard` (MAJ-5) ou explicitement limiter le composant à MP4 pour la V1 et le documenter comme tel.

**R5** — Spécifier le pattern temp-file + rename atomique pour toute sortie de job (MAJ-8), et clarifier le chaînage front `/api/methods/applicable` → affichage conditionnel de la référence (MAJ-9).

**R6** — Traiter les points mineurs (MIN-1 à MIN-8) au fil de l'implémentation, sans bloquer le démarrage.

---

**REVIEW TERMINÉE**
