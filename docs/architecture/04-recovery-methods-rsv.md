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

### 3.1 `untrunc-moov` — Reconstruction du `moov` via référence *(méthode phare V1)*
- **display_name** : « Reconstruction via fichier de référence sain »
- **requires_reference** : **true**
- **capabilities** : `containers: [mp4]`, `codecs: [xavc-s / h264]`, `tracks: [video, audio]`
- **Principe** : untrunc lit la structure `moov` d'une référence saine (même caméra/réglages) et reconstruit l'index du fichier abîmé sans réencoder le `mdat`.
- **Prérequis / validation** : référence fournie **et** compatible (même codec/profil/résolution/fps). Le `check` compat bloque si H.265 vs H.264, résolution différente, etc.
- **can_handle** : `applicable=true, confidence≈0.9` si `container=mp4 && codec=h264 && moov manquant && référence compatible`. `confidence` chute sans référence.
- **Sortie** : MP4 lisible, tranché selon `slice_spec`.
- **Limite connue** : **ne pas** proposer pour H.265/XAVC-HS (retour `applicable=false, reason="codec H.265 non supporté"`).

### 3.2 `ffmpeg-remux` — Remux / réparation best-effort *(sans référence)*
- **display_name** : « Réparation directe (sans référence) »
- **requires_reference** : **false**
- **capabilities** : `containers: [mp4]`, `codecs: [h264, h265]` (best-effort), `tracks: [video, audio]`
- **Principe** : tente un **remux**/récupération via ffmpeg (lecture tolérante aux erreurs, reconstruction partielle du flux, extraction des GOP décodables). Ne reconstruit pas un `moov` complet mais peut **sauver de l'audio** ou une partie de la vidéo quand aucune référence n'est disponible.
- **can_handle** : `applicable=true, confidence≈0.4–0.6` — fallback utile, notamment pour **récupérer le son seul** ou obtenir un aperçu partiel. Plus faible confiance que untrunc-moov.
- **Usage typique** : périmètre **« son seul »**, ou premier essai rapide sans référence, ou quand untrunc échoue.

### 3.3 `moov-rebuild-ref` — Reconstruction d'index générique via référence *(extension/robustesse)*
- **display_name** : « Reconstruction d'index avancée (référence) »
- **requires_reference** : **true**
- **capabilities** : `containers: [mp4]`, `codecs: [h264 (+ h265 expérimental)]`
- **Principe** : variante/complément d'untrunc-moov visant les cas où untrunc bute — reconstruction de la `sample table` (stco/stsz/stts/stss) à partir de la référence + scan du `mdat`. Point d'extension pour tenter le **H.265** (statut **expérimental**, `confidence` basse tant que non validé sur échantillons réels).
- **can_handle** : `confidence≈0.5` H.264 ; `≈0.3` H.265 (expérimental, marqué comme tel dans l'UI).

### 3.4 (Roadmap) `mxf-rebuild` — Réparation conteneur MXF *(V1.1, hors périmètre code V1)*
- **capabilities** : `containers: [mxf]`, `codecs: [xavc-i, xavc-l]`
- Reconstruction des partitions/Index Table KLV. **Déclaré mais non implémenté en V1** ; sert à valider que l'architecture pluggable absorbe MXF **sans refonte**.

---

## 4. Tableau de décision (diagnostic → méthode)

| Conteneur | Codec | Référence dispo | Méthode Auto (1er choix) | Alternatives |
|-----------|-------|-----------------|--------------------------|--------------|
| MP4 | H.264 (XAVC-S) | oui | `untrunc-moov` (0.9) | `moov-rebuild-ref`, `ffmpeg-remux` |
| MP4 | H.264 (XAVC-S) | non | `ffmpeg-remux` (0.5) | (proposer de fournir une référence → untrunc) |
| MP4 | H.265 (XAVC-HS) | oui | `moov-rebuild-ref` *(expérimental 0.3)* | `ffmpeg-remux` (son seul) |
| MP4 | H.265 (XAVC-HS) | non | `ffmpeg-remux` (0.4, best-effort) | outil tiers (hors app) |
| MXF | XAVC-I / L | oui/non | `mxf-rebuild` *(à venir)* | message honnête + son via `ffmpeg-remux` si possible |

Ce tableau alimente directement :
- le **mode Auto** du backend (tri par confiance),
- la **modale « Méthodes alternatives »** de l'UI (`02` §M1),
- les **messages `hint`** en cas d'échec (`03` §6).

---

## 5. Points de vigilance pour CounterPower / Builder

1. **Ne jamais réencoder le `mdat`** dans untrunc-moov : la valeur = préserver les frames d'origine. Réencodage = uniquement si l'utilisateur exporte dans un autre format, jamais pour la réparation.
2. **Validation de compatibilité référence↔source** est un prérequis dur (bloquant) avant lancement — éviter les faux espoirs.
3. **H.265/XAVC-HS = piège connu** : untrunc échoue. Le comportement doit être explicite (griser + reason), pas un crash.
4. **MXF ≠ MP4** : ne pas router un MXF vers untrunc. Détection conteneur fiable dès l'analyse.
5. **Preview par tranche** : bornée à la source, stream-copy prioritaire, cache par `(source, méthode, scope, slice)` — c'est ce qui rend l'itération viable (`03` §3).
6. **Licences des outils** (untrunc GPL, ffmpeg LGPL/GPL selon build) : à vérifier pour l'empaquetage Docker (rôle DockerManager).

---

## 6. Résumé du livrable 04
- Hypothèse du brief **validée** : `.rsv` = XAVC interrompu, `mdat` présent / `moov` manquant, réparable par reconstruction `moov` via référence (untrunc).
- **Nuance clé** : untrunc **échoue sur H.265/XAVC-HS** → la modularité des méthodes est indispensable.
- **Codecs** : XAVC-S (H.264/MP4, cible V1), XAVC-HS (H.265/MP4, à traiter à part), XAVC-I & XAVC-L (H.264/MXF, roadmap V1.1).
- **Conteneurs** : MP4 (atomes, terrain d'untrunc) vs MXF (KLV/partitions, méthode dédiée).
- **3 méthodes V1** spécifiées (`untrunc-moov`, `ffmpeg-remux`, `moov-rebuild-ref`) + 1 roadmap (`mxf-rebuild`), toutes derrière l'interface `RecoveryMethod`.
