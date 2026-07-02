# 04 — Recovery Methods & Validation du format Sony `.rsv`

> Livrable Architecte. **Recherche et validation** de l'hypothèse technique du brief, puis spécification des **méthodes de récupération pluggables** de la V1. S'articule avec l'interface `RecoveryMethod` de `03-backend-architecture.md`.

## 1. Validation de l'hypothèse (recherche)

### 1.1 Question posée par le brief
> Un `.rsv` Sony est-il un enregistrement XAVC interrompu contenant les données brutes (`mdat`) mais dont l'index/metadata (`moov`) est absent/incomplet, réparable par reconstruction de l'atome `moov` via un fichier de référence sain (approche `untrunc`) ?

### 1.2 Verdict : **HYPOTHÈSE CONFIRMÉE** (avec une nuance importante sur les codecs)

**Ce qui est confirmé par la recherche :**

- Un `.rsv` est un **fichier d'enregistrement Sony non finalisé** ("recovery" file), généré quand la caméra (ex. Sony FX3, FX30, a7 III) est **interrompue** pendant l'écriture (coupure batterie, retrait carte à chaud, crash carte, arrêt inattendu).
- Le fichier **contient bien les données audio/vidéo valides** (payload `mdat`), mais **il manque la structure de conteneur MP4 finale — l'atome `moov`** — que la caméra n'écrit qu'**à la fin** de l'enregistrement lors de la finalisation. Sans `moov`, aucun lecteur ne sait décoder le flux → fichier « illisible ».
- La **réparation classique reconstruit le `moov`** en lisant la structure (paramètres codec, layout des pistes, tables d'échantillons) depuis une **vidéo de référence saine tournée avec la même caméra et les mêmes réglages** — c'est exactement le fonctionnement d'**`untrunc`** (`anthwlock/untrunc`, dérivé de `ponchio/untrunc`).
- Cette approche **ne réencode pas** les données média : elle **reconstruit uniquement l'index** → les frames d'origine sont préservées.
- La référence **n'a pas besoin d'avoir la même durée/contenu**, mais **doit** partager codec + réglages. Sans référence compatible, la reconstruction du `moov` n'est pas fiable.
- **Sony ne fournit pas d'outil officiel** de récupération `.rsv` ; l'encodage/métadonnées propriétaires restent fermés → l'écosystème repose sur untrunc et des outils tiers (4DDiG, Wondershare Repairit, fix.video, aeroquartet Treasured, etc.).

**⚠️ Nuance critique découverte (impacte l'architecture) :**

- **untrunc fonctionne bien pour le XAVC en H.264/AVC** (XAVC-S sur FX3/FX30/a7 III).
- **untrunc échoue sur XAVC-HS (4K H.265/HEVC)** — cas explicitement rapporté ([issue untrunc #211]). Le codec HEVC n'est pas correctement géré par untrunc.
- **Conséquence archi** : la modularité des méthodes n'est **pas un luxe mais une nécessité**. Selon le codec détecté, la méthode applicable diffère ; l'UI doit griser untrunc pour du H.265 et proposer une alternative (outil tiers / méthode future / best-effort remux).

### 1.3 Sources
- [How to Repair RSV Files (Tenorshare 4DDiG)](https://4ddig.tenorshare.com/video-error/repair-rsv-file.html)
- [Sony RSV File Repair (Wondershare Repairit)](https://repairit.wondershare.com/sony-rsv-file-repair.html)
- [untrunc — issue #211 : « Works on Sony RSV except for XAVC HS » (H.265)](https://github.com/anthwlock/untrunc/issues/211)
- [Repair damaged Sony XAVC files (fix.video)](https://fix.video/blog/repair-damaged-sony-xavc-files/)
- [Recover RSV files / XAVC (aeroquartet Treasured)](https://aeroquartet.com/treasured/xavc.en.html)
- [RSV file format technical (rsv.repair)](https://rsv.repair/docs/rsv-format/)
- [untrunc (anthwlock) — reconstruction moov via référence](https://github.com/anthwlock/untrunc)
- [Moov Atom Not Found — explication (HandyRecovery)](https://www.handyrecovery.com/moov-atom-not-found/)

---

## 2. Codecs Sony XAVC concernés & conteneurs (MP4 vs MXF)

Le brief demande de **lister les codecs XAVC et de préciser MP4 vs MXF**. Synthèse :

| Format XAVC | Codec vidéo | Compression | Conteneur | Usage typique | untrunc/moov-rebuild ? |
|-------------|-------------|-------------|-----------|----------------|------------------------|
| **XAVC-S** | H.264 / AVC | Long-GOP | **MP4** | Grand public / hybrides (a7 III, FX3, FX30, a7S III en S) | ✅ **Bien supporté** (cas nominal `.rsv`) |
| **XAVC-HS** | **H.265 / HEVC** | Long-GOP | **MP4** | 4K/8K haute efficacité (a7S III, a1, FX3/FX6 en HS) | ⚠️ **untrunc échoue** → méthode alternative requise |
| **XAVC-I** (Intra) | H.264 / AVC | **All-Intra** (I-frames only) | **MXF** | Pro / broadcast (FX6, FX9, Venice, caméras cinéma) | 🔶 Reconstruction possible mais **MXF ≠ MP4/moov** : structure différente (voir §2.2) |
| **XAVC-L** (Long) | H.264 / AVC | Long-GOP | **MXF** | Pro Long-GOP | 🔶 Idem MXF |
| **XAVC** (générique/S-I hybrides récents) | H.264/H.265 selon variante | variable | MP4 ou MXF | selon caméra | selon codec/conteneur |

### 2.1 MP4 (cas prioritaire V1)
- Structure en **atomes/boxes** : `ftyp`, `mdat` (données), `moov` (index/metadata). Le `.rsv` = `ftyp` + `mdat` présents, **`moov` manquant/incomplet**.
- C'est **le terrain de jeu d'untrunc** : reconstruction du `moov` à partir d'une référence MP4 saine du même profil.
- **Cible prioritaire de la V1 : XAVC-S (H.264) en MP4** — le cas le mieux documenté et le plus résolu.

### 2.2 MXF (à traiter avec prudence)
- MXF n'utilise **pas** d'atome `moov` : c'est un conteneur **KLV** (Key-Length-Value) avec **Header/Body/Footer Partitions** et une **Index Table**. Une interruption laisse souvent une **Footer Partition / Index manquante**.
- La logique reste analogue (« l'index de lecture manque ») mais **les outils diffèrent** : untrunc (orienté ISO-BMFF/MP4) n'est **pas** l'outil adapté. Il faut une méthode dédiée MXF (réparation de partitions/index KLV, ou outils pro).
- **Décision archi** : MXF est **hors périmètre de la méthode untrunc-moov**. Prévoir un **plugin séparé** (`mxf-rebuild`, potentiellement V1.1) déclarant `containers: [mxf]`. En V1, un fichier MXF est **détecté** et l'UI indique honnêtement que la méthode adaptée est « à venir » plutôt que d'échouer silencieusement.

---

## 3. Méthodes de récupération pluggables (spéc V1)

Chaque méthode implémente l'interface `RecoveryMethod` (`03` §2.1). Ordre de préférence en **mode Auto** piloté par `can_handle().confidence`.

### 3.1 `untrunc-moov` — Reconstruction du `moov` via référence *(méthode phare V1 — ✅ validée Spike 01)*
- **display_name** : « Reconstruction via fichier de référence sain »
- **requires_reference** : **true**
- **capabilities** : `containers: [mp4]`, `codecs: [xavc-s / h264]`, `tracks: [video, audio]`
- **Statut Spike 01** : ✅ **validé** sur cas MP4/H.264 façon `.rsv` (moov tronqué) — fichier réparé **décodé intégralement**, **vidéo + audio** reconstruits, **`mdat` d'origine préservé** (pas de réencodage). Durées 60→480 s toutes réparées.
- **Principe** : untrunc lit la structure `moov` d'une référence saine (même caméra/réglages) et reconstruit l'index du fichier abîmé. **Invocation** : `untrunc <reference_saine.mp4> <fichier.rsv>` (référence = **1er argument**), sortie `<fichier>_fixed.mp4`.
- **Support Sony natif** : untrunc embarque **`src/rsv.cpp`** et l'option **`-rsv-ben` — « RSV file recovery (Sony recording-in-progress files) »** → à activer pour les `.rsv`.
- **⚠️ Modèle de coût (Spike 01, décisif)** : le repair est **O(taille du fichier)**, **PAS** O(tranche) — untrunc rescanne **tout** le `mdat` pour reconstruire le `moov` **complet**, sans notion de tranche. Coût **plein, payé une seule fois**, puis **mis en cache** comme artefact « source réparée » indexé `(source_hash, method_id, reference_hash)` (cf. `03` §3.2). Toutes les tranches + `extend` en dérivent par `-c copy` (~0,2 s). Sur un gros rush 4K lu depuis carte/HDD, ce repair unique peut prendre **plusieurs minutes** (borné par l'I/O du fichier entier).
- **Contrainte outillage (DockerManager)** : **figer ffmpeg ≤ 8.0** dans l'image untrunc — au-delà de 8.1, la struct interne `FFCodec` est cassée (untrunc instable). Build via le Dockerfile officiel `anthwlock/untrunc`.
- **Prérequis / validation** : référence fournie **et compatible** — affichée comme **estimation « probablement compatible »** (codec/profil/résolution/fps), pas un ✓ garanti (MAJ-6 ; untrunc reste sensible à firmware/GOP/bitrate mode). Bloquer clairement si H.265 vs H.264 ou conteneur différent.
- **can_handle** : **confiance qualitative HAUTE** si `container=mp4 && codec=h264 && moov absent && référence probablement compatible`. **Non applicable sans référence** (le repair l'exige). *(Les scores numériques du tableau §4 sont des estimations qualitatives à recalibrer sur données réelles — MAJ-10.)*
- **Sortie** : MP4 réparé complet (artefact caché) → tranche via `-c copy` selon `slice_spec`.
- **Limite connue** : **ne pas** proposer pour H.265/XAVC-HS (retour `applicable=false, reason="codec H.265 non supporté par untrunc"`).
- **Réserve d'honnêteté (Spike 01 §5)** : validé sur cas **synthétique** (troncature d'un moov) en H.264 uniquement, référence « parfaite », fichiers en cache RAM. **À re-tester sur un vrai `.rsv` Sony + référence caméra réelle** dès disponibilité.

### 3.2 `ffmpeg-remux` — best-effort SANS référence — ⛔ **INVALIDÉ par le Spike 01 sur fichier sans `moov`**
> **Résultat mesuré (Spike 01 §3.4)** : sur un fichier réellement privé de `moov`, **ffmpeg seul ne démuxe RIEN** — ni vidéo, **ni même le son**. Toutes les variantes échouent (`-c copy`, `-vn -c:a copy`, `-err_detect ignore_err`, `-analyzeduration/-probesize` gonflés, `-f mov` forcé) → `moov atom not found` / Invalid data, **aucune** sortie. ffmpeg n'a aucun index pour localiser les samples du `mdat`.

- **display_name** : « Réparation directe sans référence » ⚠️ **très faible / probablement inopérant**
- **requires_reference** : false
- **capabilities** : `containers: [mp4]`, `codecs: [h264, h265]`, `tracks: [—]`
- **Statut** : **la promesse initiale (« sauver le son seul sans référence », confidence 0.4–0.6) est retirée.** Sur un `.rsv` typique (moov absent), cette méthode **ne récupère rien**.
- **can_handle** : `applicable=false` (ou `confidence ≈ 0.05`, quasi nul) dès que le diagnostic indique `moov` absent. Ne l'exposer **que** dans le cas résiduel où un `moov` **partiel/présent mais corrompu** est détecté (là, un remux peut avoir un sens) — pas le cas nominal `.rsv`.
- **Conséquence : la référence devient quasi obligatoire** (voir §3.5 et `01` §[5]). Sans référence compatible ⇒ **pas de récupération fiable du tout**. → L'effort produit se déplace vers **l'aide à trouver une référence** (scan du même dossier/carte), et non vers un fallback sans référence qui n'existe pas.
- **Piste non enterrée (à spiker séparément)** : le support **natif Sony d'untrunc** (`-rsv-ben`) et son mode `-sm search mdat` pourraient reconstruire **sans référence externe** en s'appuyant sur la connaissance interne du codec — **non testé** par le Spike 01 (usage nominal = avec référence). Voir §3.6.

### 3.3 `moov-rebuild-ref` — Reconstruction d'index générique via référence *(extension/robustesse)*
- **display_name** : « Reconstruction d'index avancée (référence) »
- **requires_reference** : **true**
- **capabilities** : `containers: [mp4]`, `codecs: [h264 (+ h265 expérimental)]`
- **Principe** : variante/complément d'untrunc-moov visant les cas où untrunc bute — reconstruction de la `sample table` (stco/stsz/stts/stss) à partir de la référence + scan du `mdat`. Point d'extension pour tenter le **H.265** (statut **expérimental**, `confidence` basse tant que non validé sur échantillons réels).
- **can_handle** : confiance **MOYENNE** H.264 ; **BASSE / expérimentale** H.265 (marqué « expérimental » dans l'UI ; scores à recalibrer sur données réelles — MAJ-10).

### 3.4 (Roadmap) `mxf-rebuild` — Réparation conteneur MXF *(V1.1, hors périmètre code V1)*
- **capabilities** : `containers: [mxf]`, `codecs: [xavc-i, xavc-l]`
- Reconstruction des partitions/Index Table KLV. **Déclaré mais non implémenté en V1** ; sert à valider que l'architecture pluggable absorbe MXF **sans refonte**.

### 3.5 Politique « référence » — quasi obligatoire (conséquence du Spike 01)
- Le Spike 01 (§3.4) prouve que **sans `moov` reconstruit, aucune récupération n'est possible** (ffmpeg seul n'ouvre rien). Or reconstruire le `moov` **exige une référence**.
- **Règle produit** : une **référence compatible est la condition de la V1**. En son absence, l'app ne promet **pas** de récupération best-effort (elle n'existe pas) ; elle **oriente vers la recherche d'une référence**.
- **Impact UX (voir `01` §[5])** : aide active à trouver une référence (même dossier/carte/caméra), badge « probablement compatible » (estimation, pas garantie — MAJ-6), et affichage conditionnel piloté par `GET /api/methods/applicable` dès le diagnostic (MAJ-9).

### 3.6 Piste « sans référence externe » — à spiker (non tranché)
- untrunc possède une logique interne (**`-rsv-ben`**, mode **`-sm search mdat`**, connaissance du codec) qui **pourrait** reconstruire un `.rsv` **sans** référence externe, ou avec une référence « générique » du même modèle de caméra. **Non testé** par le Spike 01.
- **Statut : hypothèse ouverte, hors code V1.** Un mini-spike dédié est requis avant d'exposer un quelconque mode « aucune référence ». Ne pas le promettre à l'utilisateur tant que non validé.

---

## 4. Tableau de décision (diagnostic → méthode)

> Les niveaux de confiance sont **qualitatifs** (HAUTE / MOYENNE / BASSE / NULLE) — à recalibrer sur données réelles (MAJ-10). Aucun score numérique ferme à ce stade.

| Conteneur | Codec | Référence compatible | Méthode Auto (1er choix) | Confiance | Alternatives / note |
|-----------|-------|----------------------|--------------------------|-----------|---------------------|
| MP4 | H.264 (XAVC-S) | **oui** | `untrunc-moov` | **HAUTE** ✅ (validé Spike 01) | `moov-rebuild-ref` |
| MP4 | H.264 (XAVC-S) | **non** | — *(aucune méthode fiable)* | **NULLE** ⛔ | Bloquer + **aider à trouver une référence**. `ffmpeg-remux` sans réf **ne marche pas** (Spike 01). |
| MP4 | H.265 (XAVC-HS) | oui | `moov-rebuild-ref` *(expérimental)* | **BASSE** 🔶 | untrunc réputé échouer en H.265 ; marquer « expérimental » dans l'UI. |
| MP4 | H.265 (XAVC-HS) | non | — | **NULLE** ⛔ | Référence requise + méthode H.265 non prouvée. Outil tiers hors app. |
| MXF | XAVC-I / L | oui/non | `mxf-rebuild` *(à venir)* | **N/A** (roadmap) | Message honnête « format MXF : méthode à venir ». Ne **pas** router vers untrunc. |
| MP4 | tout, **`moov` partiel/corrompu** (pas absent) | — | `ffmpeg-remux` (cas résiduel) | BASSE | Seul cas où un remux ffmpeg peut avoir un sens (index partiel présent). |

Ce tableau alimente directement :
- le **mode Auto** du backend (tri par confiance),
- la **modale « Méthodes alternatives »** de l'UI (`02` §M1),
- les **messages `hint`** en cas d'échec (`03` §6).

---

## 5. Points de vigilance pour CounterPower / Builder

1. **Ne jamais réencoder le `mdat`** dans untrunc-moov : la valeur = préserver les frames d'origine. Réencodage = uniquement si l'utilisateur exporte dans un autre format, jamais pour la réparation.
2. **Repair = O(fichier), payé UNE fois puis caché** (Spike 01). Indexer l'artefact réparé par `(source_hash, method_id, reference_hash)` ; toutes les tranches + `extend` en dérivent en `-c copy`. **Ne jamais re-réparer** à chaque changement de tranche (`03` §3.2).
3. **Sans référence, aucune récupération** (Spike 01 §3.4) : ffmpeg seul n'ouvre rien sans `moov`, pas même l'audio. Traiter la référence comme quasi obligatoire, aider à la trouver.
4. **Compatibilité référence↔source = estimation, pas garantie** (MAJ-6) : afficher « probablement compatible », bloquer les incompatibilités dures (codec/conteneur), mais ne pas promettre un ✓ que le firmware/GOP peut démentir.
5. **H.265/XAVC-HS = piège connu** : untrunc échoue. Comportement explicite (griser + reason), pas un crash.
6. **MXF ≠ MP4** : ne pas router un MXF vers untrunc. Détection conteneur fiable dès l'analyse.
7. **ffmpeg ≤ 8.0 figé** dans l'image untrunc (struct `FFCodec` cassée au-delà de 8.1) + activer **`-rsv-ben`** pour les `.rsv` Sony (DockerManager).
8. **Licences des outils** (untrunc GPL, ffmpeg LGPL/GPL selon build) : à vérifier pour l'empaquetage Docker (rôle DockerManager).

---

## 6. Résumé du livrable 04
- Hypothèse du brief **validée** (recherche + **Spike 01**) : `.rsv` = XAVC interrompu, `mdat` présent / `moov` manquant, réparable par reconstruction `moov` via référence (untrunc) — **cas H.264/MP4 confirmé décodable**.
- **Modèle de coût corrigé** : repair **O(fichier), payé une fois puis caché** ; tranches quasi gratuites en `-c copy`. **Pas** de repair proportionnel à la tranche.
- **Référence quasi obligatoire** : sans elle, ffmpeg ne récupère **rien** (pas même le son) → `ffmpeg-remux` sans référence **invalidé** ; effort produit reporté sur l'aide à trouver une référence.
- **Nuance codec** : untrunc **échoue sur H.265/XAVC-HS** → modularité indispensable. `moov-rebuild-ref` H.265 = expérimental.
- **Codecs** : XAVC-S (H.264/MP4, cible V1 ✅), XAVC-HS (H.265/MP4, à traiter à part), XAVC-I & XAVC-L (H.264/MXF, roadmap V1.1).
- **Conteneurs** : MP4 (atomes, terrain d'untrunc) vs MXF (KLV/partitions, méthode dédiée).
- **Outillage** : untrunc `-rsv-ben` (support Sony natif) + **ffmpeg ≤ 8.0** figé (contrainte DockerManager).
- **Méthodes V1** : `untrunc-moov` (phare, validée) ; `ffmpeg-remux` **rétrogradée** (cas résiduel `moov` partiel uniquement) ; `moov-rebuild-ref` (extension) ; `mxf-rebuild` (roadmap). Toutes derrière l'interface `RecoveryMethod`.
