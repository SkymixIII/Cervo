# Spike 01 — Validation `untrunc` : coût du repair O(fichier) vs O(tranche)

> Auteur : **Builder**. Réponse à **R0** (master-arbitration-01.md) et **BLOQ-2** (architecture-review-01.md).
> Objectif : trancher la question n°1 **AVANT** de coder le pipeline modulaire — est-ce que le repair `untrunc` coûte O(taille fichier) ou O(tranche visée) ?
> Statut : **SPIKE TERMINÉ.**

---

## 0. TL;DR (conclusion pour Master / Architect / CounterPower)

| Question du spike | Réponse mesurée |
|---|---|
| untrunc reconstruit-il un MP4 lisible à partir d'un fichier tronqué (moov absent) ? | ✅ **OUI**, sur MP4 H.264 (XAVC-S nominal). Fichier réparé **décodé intégralement** sans erreur. |
| Le temps de repair dépend-il de la **taille du fichier** ou de la **tranche** ? | ⛔ **O(taille fichier)**, strictement linéaire. **untrunc n'a AUCUNE notion de tranche.** Il rescanne tout le `mdat` pour reconstruire le `moov` complet. |
| Peut-on extraire une tranche 1 min en `ffmpeg -c copy` après repair ? | ✅ **OUI**, ~0,2 s, sans réencodage. O(tranche). |
| Le fallback `ffmpeg-remux` **sans référence** récupère-t-il le son ? | ⛔ **NON.** Sur un fichier réellement sans `moov`, ffmpeg seul **n'ouvre rien** (ni vidéo ni audio), quelles que soient les options. |

**Verdict de faisabilité : FAISABLE pour le cas nominal V1 (XAVC-S / H.264 / MP4), à condition de corriger le modèle de coût.**
La promesse « preview 1 min rapide *parce que le repair est proportionnel à la tranche* » (`03` §3.1) est **fausse** et doit être reformulée. Le repair est un coût **plein, payé une seule fois** ; ce sont les tranches **après** repair qui sont quasi gratuites. → Valide directement la reco **BLOQ-3** (cacher l'artefact « source réparée »).

---

## 1. Environnement & outillage

- **Machine** : macOS (Darwin 25.1), 10 cœurs. ffmpeg **8.0.1** local.
- **untrunc** : pas de formule Homebrew (`brew search untrunc` → rien). Construit via le **Dockerfile officiel** de [`anthwlock/untrunc`](https://github.com/anthwlock/untrunc) sur base **Ubuntu 22.04 + ffmpeg 4.x système**.
  - ⚠️ Choix délibéré du build Docker : le README untrunc avertit que **ffmpeg > 8.1 casse la struct interne `FFCodec`** (comportement indéfini). Mon ffmpeg local 8.0.1 est en zone à risque → l'image Docker isole une lib ffmpeg compatible. **À retenir pour DockerManager : figer la version ffmpeg dans l'image untrunc.**
- **Bonne surprise dans les sources untrunc** :
  - présence de `src/rsv.cpp` (support RSV dédié) ;
  - option CLI **`-rsv-ben` — « RSV file recovery (Sony recording-in-progress files) »** (support Sony `.rsv` explicite) ;
  - README mentionne « supports GoPro and Sony XAVC videos ».
- **Usage untrunc** : `untrunc [options] <ok.mp4> [corrupt.mp4]` → **la référence saine est le 1er argument**, le fichier cassé le 2ᵉ. Sortie = `<corrupt>_fixed.mp4`.

## 2. Génération synthétique du cas de test

Faute de vrai `.rsv` Sony sous la main (cf. « en attente d'input utilisateur » de l'arbitrage), cas **synthétique fidèle au profil `.rsv`** :

1. **Fichiers sains** générés avec ffmpeg : `testsrc2` 1920×1080@30, **H.264 (libx264) ~20 Mbit/s** + piste audio AAC (sine). Réglages encodeur **identiques**, seule la **durée varie** (60 / 120 / 240 / 480 s) pour mesurer le scaling.
2. **Référence saine** : clip 30 s, mêmes réglages exacts (codec/profil/résolution/fps) → référence compatible.
3. **Copie « corrompue » façon `.rsv`** : layout réel observé = `ftyp + free + mdat + moov` (moov **en fin de fichier**, écrit à la finalisation). On **tronque le fichier au début de l'atome `moov`** → il reste **`ftyp + free + mdat`**, exactement le profil d'un enregistrement interrompu avant finalisation.
4. **Vérif** que le fichier tronqué est bien illisible : `ffprobe broken_60.rsv` → **`moov atom not found` / Invalid data** ✅ (symptôme `.rsv` exact).

| Fichier | Durée | Taille | Atomes après troncature |
|---|---|---|---|
| `reference.mp4` | 30 s | 75 MB | (sain, sert de référence) |
| `broken_60.rsv` | 60 s | 151 MB | `ftyp`, `free`, `mdat` (moov supprimé) |
| `broken_120.rsv` | 120 s | 302 MB | idem |
| `broken_240.rsv` | 240 s | 604 MB | idem |
| `broken_480.rsv` | 480 s | 1208 MB | idem |

## 3. Mesures

### 3.1 — Le repair reconstruit-il un MP4 lisible ? → OUI

`untrunc reference.mp4 broken_60.rsv` produit `broken_60.rsv_fixed.mp4` :
- untrunc log : `Found 4385 packets ( mp4a: 2585 avc1: 1800 avc1-keyframes: 8 )`, `Duration avc1: 60000 ms`, `Duration mp4a: 60023 ms` → **pistes vidéo + audio reconstruites**.
- `ffprobe` du fichier réparé : `h264 1920×1080 + aac`, `duration=60.02 s`, taille ≈ mdat d'origine.
- **Décodage réel** (`ffmpeg -i fixed.mp4 -f null -`) : **exit 0, décodage intégral**. Seuls 2 avertissements cosmétiques de DTS non-monotone sur les toutes dernières frames (pinaillage muxer, **pas** un échec de décodage).
- ✅ Idem pour 120 / 240 / 480 s : tous réparés, tous décodables, **vidéo + audio préservés, sans réencodage** (le `mdat` d'origine est conservé, seul l'index est reconstruit).

### 3.2 — Le temps de repair : O(fichier) vs O(tranche) → **O(fichier), linéaire**

Overhead de démarrage du conteneur mesuré à part (`untrunc -V`) = **0,18 s** (constant, soustrait ci-dessous). Wall-clock, meilleur de 2 passes, données en cache OS :

| Durée | Taille fichier | Traitement pur (wall − overhead) | Ratio taille | Ratio temps |
|---|---:|---:|---:|---:|
| 60 s | 151 MB | **0,18 s** | ×1 | ×1 |
| 120 s | 302 MB | **0,28 s** | ×2 | ×1,6 |
| 240 s | 604 MB | **0,57 s** | ×4 | ×3,2 |
| 480 s | 1208 MB | **1,13 s** | ×8 | ×6,3 |

**Doubler la taille double le temps** (240→480 : 0,57→1,13 = ×1,98 ; 120→240 : ×2,04). Débit ≈ **~1 GB/s** ici (⚠️ données en **cache RAM** — voir §5). Le premier point est bruité car proche du plancher d'overhead.

**Point décisif** : untrunc **n'expose aucun paramètre de tranche**. Il reconstruit le `moov` **complet** en scannant l'**intégralité** du `mdat` pour retrouver tous les packets/keyframes. Il est **impossible** de lui faire produire une sample-table partielle « juste pour la 1re minute ». Donc :

> **Le coût du repair est identique que l'utilisateur veuille 1 min ou l'intégrale.** → **BLOQ-2 tranché : O(fichier).** L'affirmation `03` §3.2 (« il suffit de reconstruire la portion de la table d'échantillons couvrant la tranche ») est **fausse** pour untrunc.

### 3.3 — Extraction d'une tranche 1 min après repair → O(tranche), quasi gratuit

Sur `broken_240.rsv_fixed.mp4` :

| Opération | Temps | Réencodage |
|---|---:|---|
| `ffmpeg -ss 60 -t 60 -c copy` (stream-copy) | **0,21 s** | ❌ non |
| `ffmpeg -ss 60 -t 60 -c:v libx264 -c:a aac` (réencode) | **5,25 s** | ✅ oui |

La tranche `-c copy` est **décodée sans erreur** (exit 0). → **le `-c copy` post-repair est ~25× plus rapide que le réencodage et scale avec la tranche, pas le fichier.** ✅ Valide le pipeline `03` §3 côté *slice-encode*, **à condition que le repair soit déjà fait**.

### 3.4 — `ffmpeg-remux` best-effort **sans référence** → ÉCHEC TOTAL

Sur `broken_60.rsv` (sans `moov`), toutes variantes testées :

- `ffmpeg -i broken.rsv -c copy` → **`moov atom not found` / Invalid data**, aucune sortie.
- `-vn -c:a copy` (son seul) → **même échec**, **aucun audio récupéré**.
- `-err_detect ignore_err -analyzeduration 200M -probesize 200M` → même échec.
- `-f mov` forcé → même échec.

> **ffmpeg seul ne peut RIEN démuxer sans `moov`** : il n'a aucun index pour localiser/interpréter les samples du `mdat`. La méthode `ffmpeg-remux` « sans référence » de `04` §3.2 (confidence 0,4–0,6, censée « sauver le son ») **ne fonctionne pas** sur un fichier réellement sans moov — telle que décrite, elle est **invalidée**.

---

## 4. Conséquences pour l'architecture (réponses aux points de review)

### 4.1 BLOQ-2 — Modèle de coût : **TRANCHÉ = O(fichier)**
Reformuler honnêtement la promesse produit (`01` §0, `03` §3.1) :
- ❌ « le repair est proportionnel à la tranche demandée » → **faux**.
- ✅ Formulation correcte : **« Le repair coûte le même temps quelle que soit la tranche (proportionnel à la taille du fichier) et n'est payé qu'une seule fois. Ensuite, chaque preview/tranche est quasi gratuite (stream-copy). »**

### 4.2 BLOQ-3 — Cache de l'artefact « source réparée » : **VALIDÉ, et c'est le pilier**
Le spike prouve la bonne granularité de cache :
- **repair une seule fois** → produire un **MP4 réparé complet** (artefact intermédiaire), indexé par **`(source_hash, method_id, reference_hash)`** ;
- **toutes les tranches** (1 min / 5 min / intégrale) et l'endpoint `extend` = **`-c copy` sur cet artefact** (~0,2 s).

Pipeline corrigé : `probe → repair(ONCE, O(fichier), caché) → slice-copy(O(tranche)) → publish`. **Sans ce cache, chaque changement d'onglet de tranche re-paie le repair intégral** — exactement l'anti-pattern signalé en BLOQ-3. **À écrire dans `03` avant que je code le Job Manager.**

### 4.3 BLOQ-4 renforcé — le « sans référence » est bien plus faible qu'annoncé
Le spike montre que **sans moov reconstruit, on ne récupère rien** (même pas le son) avec ffmpeg. Or reconstruire le moov via untrunc **exige une référence** (1er argument obligatoire). Donc :
- pas de référence compatible ⇒ pas de récupération fiable du tout (le fallback « son seul via ffmpeg-remux » ne tient pas).
- ⇒ **la disponibilité d'une référence est encore plus critique** que ne le supposait la review. Priorité à l'UX d'aide à *trouver* une référence (scan du même dossier/carte), déjà retenue par Master.
- ⚠️ **À explorer avant d'enterrer le « sans référence »** : untrunc a une logique interne (`-rsv-ben`, `-sm search mdat`, connaissance du codec) qui pourrait reconstruire **sans** référence externe, ou avec une référence « générique » du même modèle de caméra. **Non testé ici** (usage nominal = avec référence). À spiker si le produit veut couvrir le cas « aucune référence ».

### 4.4 MAJ-7 confirmé — périmètre V1
Le cas nominal **XAVC-S / H.264 / MP4 marche bien et simplement** avec untrunc + `-c copy`. Concentrer la V1 dessus. **H.265/XAVC-HS non testé** (untrunc réputé échouer, cf. `04` §1.2) → confirmer que `moov-rebuild-ref` reste hors code V1.

### 4.5 MIN-5 (Redis vs in-process) — indice
Le repair est **court en absolu** (< 2 s même sur 1,2 GB en cache ; borné par l'I/O disque sinon). Sur un poste **mono-utilisateur local**, une file **in-process (ProcessPool + SQLite)** semble largement suffisante ; Redis+RQ paraît surdimensionné. À confirmer par Architect, mais le spike ne révèle aucun besoin de broker distribué.

---

## 5. Limites / honnêteté sur ce spike (à ne pas surinterpréter)

- **Débit ~1 GB/s = optimiste** : mes fichiers tenaient en **cache RAM**. Sur un vrai rush **4K de 30–80 GB** lu depuis carte SD / HDD / réseau, le repair est **borné par la lecture disque du fichier entier** (ex. 80 GB @ 200 MB/s ≈ **~7 min**), **toujours O(fichier)**, jamais O(tranche). Le message produit doit assumer que **le 1er repair d'un gros rush peut prendre plusieurs minutes**.
- **Cas synthétique, pas un vrai `.rsv` Sony** : troncature d'un `moov` complet + `mdat` complet. Un vrai enregistrement interrompu peut avoir un **dernier GOP partiellement écrit** / octets de queue. untrunc a des options pour ça (`-s`, `-sm`, 1674 warnings « cachés » observés = il tolère des anomalies), mais **la robustesse réelle sur un vrai `.rsv` n'est pas prouvée**. → **Re-tester dès qu'un vrai `.rsv` + référence caméra sont fournis** (input utilisateur en attente).
- **Codec testé = H.264 uniquement** (cible V1). H.265/XAVC-HS et MXF **non couverts**.
- **Référence « parfaite »** (mêmes réglages exacts). La sensibilité d'untrunc à une référence légèrement différente (firmware, GOP, bitrate mode — cf. MAJ-6) **n'est pas mesurée**.

---

## 6. Recommandation d'exécution (Builder → Master/Architect)

1. **Architect** : corriger `03` §3.1/§3.2 (modèle de coût O(fichier)) + ajouter le **cache d'artefact réparé** `(source_hash, method_id, reference_hash)` (BLOQ-3) ; corriger le texte UX `01` §0 ; requalifier `ffmpeg-remux sans référence` (`04` §3.2) en « très faible / probablement inopérant sans moov » (§3.4 ci-dessus).
2. **DockerManager** : figer la version ffmpeg dans l'image untrunc (risque struct `FFCodec` ffmpeg > 8.1) ; noter le support natif `-rsv-ben`.
3. **Builder (moi)** : une fois `03` mis à jour + re-review CounterPower du delta, coder le pipeline V1 = `untrunc-moov (repair once + cache)` + `slice via -c copy`, sur ces bases **maintenant validées**.
4. **Optionnel** : mini-spike « untrunc sans référence externe » (`-rsv-ben` seul) pour statuer sur le cas « aucune référence disponible ».

**Je ne code PAS le pipeline modulaire tant que le delta archi (BLOQ-2/BLOQ-3) n'est pas intégré par Architect et re-reviewé.**

---

## Annexe — Reproductibilité

Build untrunc : `docker build -t untrunc .` depuis `github.com/anthwlock/untrunc`.
Génération sain : `ffmpeg -f lavfi -i testsrc2=size=1920x1080:rate=30:duration=<D> -f lavfi -i sine=frequency=440:duration=<D> -c:v libx264 -preset veryfast -b:v 20M -maxrate 24M -bufsize 48M -pix_fmt yuv420p -c:a aac out.mp4`
Troncature `.rsv` : parser les atomes top-level, `os.truncate(fichier, offset_moov)`.
Repair : `docker run --rm -v <data>:/mnt untrunc -n /mnt/reference.mp4 /mnt/broken.rsv` → `broken.rsv_fixed.mp4`.
Tranche : `ffmpeg -ss 60 -i broken.rsv_fixed.mp4 -t 60 -c copy slice.mp4`.

**SPIKE TERMINÉ.**
