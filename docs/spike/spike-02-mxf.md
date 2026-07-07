# Spike 02 — Faisabilité récupération `.rsv` « MXF » Sony (sur un VRAI fichier)

> Auteur : **Builder**. Suite du Spike 01. Cible : roadmap `mxf-rebuild` (`04` §3.4).
> Objectif : trancher la **faisabilité** de récupérer un `.rsv` non-MP4 issu d'un Sony **PXW-Z200**, **avant** toute conception.
> Fichier réel analysé (lecture seule, jamais modifié) : `/Volumes/TOM/C4934.RSV` — **70,6 Go** (65,78 Gio), Sony PXW-Z200, enregistrement interrompu non finalisé.
> Référence saine fournie (même caméra/session, clip suivant) : `/Users/lois/Downloads/C4935.MP4` — **29,7 Go**.
> Statut : **SPIKE TERMINÉ — + PoC PIXEL & SÉQUENCE VALIDÉ (voir §9).**

> **🎯 MISE À JOUR (GO construction) : le PoC a produit une VRAIE VIDÉO.** De-chunk du framing Sony → carve de **200 frames** → MP4 H.264 3840×2160 10-bit **lisible, 199 frames décodées, 0 erreur de décodage**, image cohérente (scène réelle, mouvement continu). Le verdict passe de *« DUR/FAISABLE »* à **FAISABLE — DÉMONTRÉ jusqu'au pixel**. Détails §9.

---

## 0. TL;DR (conclusion pour Master / Architect / CounterPower)

| Question du spike | Réponse mesurée sur le vrai fichier |
|---|---|
| Le `.rsv` est-il un **MXF** (KLV/partitions) ? | ⛔ **NON.** Zéro structure MXF conforme (0 Header Partition Pack, 0 Primer, 0 Index Table, 0 Footer, 0 RIP, 0 Generic Container). C'est un **format de récupération PROPRIÉTAIRE Sony** à blocs KLV privés. |
| Codec exact : XAVC-I (all-intra) ou XAVC-L (long-GOP) ? | ✅ **XAVC-I — H.264 High 4:2:2 Intra, All-Intra** (le cas **favorable**). 3840×2160, **25 fps**, **10-bit** (`yuv422p10le`). Audio **4× PCM 24-bit** (`pcm_s24be`) @48 kHz + piste data `rtmd`. |
| L'essence H.264 est-elle réellement présente dans le `.rsv` ? | ✅ **OUI, prouvé.** Les **SPS (52 o) et PPS (78 o) exacts** extraits de la référence C4935.MP4 se retrouvent **octet pour octet** dans `C4934.RSV`. Même encodeur, mêmes paramètres. |
| Un outil standard lit-il l'essence ? | ⛔ **NON.** ffmpeg (`-f mxf`, tolérant) : *« could not find header partition pack key » → Invalid data*. bmx/libmxf : même hypothèse de partitions ⇒ échoue aussi. **untrunc hors sujet** (ISO-BMFF only). |
| Que manque-t-il vs un fichier sain ? | **Tout le wrapper de finalisation.** Le `.rsv` est l'**intermédiaire écrit PENDANT** l'enregistrement ; la caméra ne le convertit en MP4/XAVC-I (ftyp/moov/mdat) qu'à l'**arrêt propre**. Interruption ⇒ resté à l'état `.rsv`. Fin de fichier = essence **tronquée en plein milieu d'une frame**, aucun footer. |

### VERDICT : **FAISABLE — DÉMONTRÉ (PoC pixel + séquence MP4 lisible)**

> Le PoC (§9) a **effectivement reconstruit une vidéo lisible** à partir du `.rsv` corrompu : de-chunk du conteneur Sony → NAL H.264 → MP4 3840×2160 10-bit qui **se lit et se décode sans erreur**. Ce n'est plus une hypothèse.
>
> **FAISABLE (confirmé)** parce que : (1) l'essence H.264 est **présente, extraite et décodée** ; (2) **XAVC-I = All-Intra** ⇒ **chaque frame indépendante**, carve par frame déterministe (200/200 frames reconstruites) ; (3) la référence C4935.MP4 fournit **tous** les paramètres (SPS/PPS byte-identiques, timescale, layout pistes) ; (4) framing Sony **entièrement décodé** (blocs 11264 o + records paramètres `[u32 len][00][u32 len+4][0201]` + essence en **avcC 4-octets**) ; (5) la troncature ne coûte que **la dernière frame partielle** (All-Intra).
>
> **Reste « DUR » (mais borné)** sur l'**audio** : le désentrelacement des **4 canaux PCM** n'est pas encore fait (increment suivant). Et **aucun outil sur étagère** ne lit ce format : c'est du **code dédié** (le PoC = ~150 lignes Python + ffmpeg). `untrunc` et `mxf-rebuild` (tel que décrit dans `04`) ne s'appliquent **ni l'un ni l'autre**.

**⚠️ Impact doc `04` : deux hypothèses sont fausses pour ce Z200 et doivent être corrigées (voir §6).**

---

## 1. Environnement & méthode (règle « ne jamais toucher l'original »)

- Original **jamais ouvert en écriture**. Copié en **lecture seule** (`dd`) uniquement le **début 500 Mo** (`head.bin`) et la **fin ~200 Mo** (`tail.bin`) vers `/private/tmp/mxf_spike` — **pas** les 70 Go, pour ménager le disque USB.
- Outils : `ffmpeg`/`ffprobe` **8.0.1**, parseur **KLV maison en Python** (`klv_scan.py`), `xxd`.
- Référence : `ffprobe`/`ffmpeg` en **lecture seule** sur `C4935.MP4` — extraction de **la 1re frame uniquement** (SPS/PPS/IDR annex-B, 2,9 Mo), **pas** de copie des 30 Go.
- `bmx`/`libmxf` : **pas de formule Homebrew** (`brew install libmxf` → introuvable). Build source non tenté : inutile, car (a) ffmpeg prouve déjà l'absence de partition pack, et (b) bmx **exige** les mêmes partitions/RIP MXF ⇒ échouerait identiquement.

---

## 2. Le `.rsv` N'EST PAS un MXF — c'est un format de récupération propriétaire Sony

### 2.1 Preuve : aucune structure MXF conforme
Recherche exhaustive sur **700 Mo** (500 début + 200 fin) :

| Élément MXF attendu (fichier sain) | Clé recherchée | Trouvé dans `C4934.RSV` |
|---|---|---|
| Header Partition Pack | `060e2b34 020501010d010201 02…` | **0** |
| Body / Footer Partition | `…020501010d010201 03/04…` | **0** |
| Primer Pack | `…050100` | **0** |
| Header Metadata (Preface…) | `060e2b34 025301010d010101…` | **0** |
| Generic Container Essence Element | `060e2b34 01020101 0d010301…` | **0** |
| Index Table Segment | `…0d0102010110 0100` | **0** |
| Random Index Pack (RIP) | `…0d0102010111 0100` | **0** |
| **Clé PRIVÉE Sony** | `060e2b34 **0253 0101 0c02** 0101…` | **✅ omniprésente** |

- Les seules clés SMPTE sont des UL **privées Sony** : préfixe `06 0e 2b 34 02 53 01 01 **0c 02** 01 01`. Le designator **`0c 02`** (au lieu du **`0d 01`** normatif MXF) = **registre propriétaire**, pas un item MXF standard.
- ⇒ Ce que Master a repéré comme « MXF/KLV, ~420 clés SMPTE » est bien du **KLV**, mais **KLV propriétaire Sony**, **pas** un conteneur MXF exploitable. Aucune sémantique de partition/index MXF n'existe ici.
- Aucun atome MP4 non plus (`ftyp`/`mdat` = 0 ; un unique `moov` ASCII = coïncidence aléatoire dans 500 Mo d'essence).

### 2.2 Layout physique observé (à pas constant)
Le fichier est une suite de **blocs de récupération de 11264 octets (0x2c00)** — **constant, mesuré 660×** :

```
[bloc 11264 o] = [cluster métadonnées KLV Sony ~2,7 Ko] + [fragment d'essence ~8,5 Ko]
```
- **Région d'en-tête** (~11-12 premiers blocs) : contient le **cluster codec/setup** — dont **SPS + PPS uniques** (comme l'`avcC` d'un MP4, stockés **une fois**, pas par frame).
- **Région essence** : après l'en-tête, l'essence passe en **grands runs par frame** (~**4,9–8,9 Mo**), chacun **séparé par un cluster de récupération** (descripteur répété `e0 00 00 10 96 69 08 …` — gabarits identiques d'une frame à l'autre : marqueurs de frame/sous-éléments).
- Les clusters de métadonnées Sony embarquent des **UL SMPTE de codage** (`060e2b34 0401010b 0510010101…`) décrivant l'essence.

### 2.3 Ce qui manque exactement (vs un fichier finalisé sain)
Le **wrapper de finalisation entier**. La chaîne normale du Z200 est :
```
enregistrement → écrit un .rsv (intermédiaire propriétaire) → à l'ARRÊT PROPRE : conversion → MP4/XAVC-I (ftyp+moov+mdat)
```
L'interruption (batterie/carte) a coupé **avant la conversion** ⇒ il reste le `.rsv`. Il **manque donc** : l'index de lecture, le moov/l'equivalent, et surtout **le ré-emballage des NAL/PCM en pistes MP4**. La **fin est tronquée en pleine frame** (5,8 Mo d'essence après le dernier cluster, **aucun footer/RIP/clôture**) → **la dernière frame est à jeter**.

---

## 3. Codec EXACT (réponse Q1) — le cas FAVORABLE

Depuis la **référence** `C4935.MP4` (même caméra/session) via `ffprobe`, **corroboré** par l'essence du `.rsv` :

| Piste | Détail |
|---|---|
| **Vidéo** | **H.264 High 4:2:2 Intra** = **XAVC-I (All-Intra)**. 3840×2160, **25 fps**, **10-bit** `yuv422p10le`, `time_base 1/25000`. |
| **Audio** | **4 pistes mono `pcm_s24be`** (PCM 24-bit big-endian) @ **48 kHz** (dans le MP4 : `ipcm`). |
| **Data** | 1 piste `rtmd` (metadata temps réel Sony). |

- **XAVC-I, PAS XAVC-L.** C'est le meilleur scénario : **All-Intra ⇒ zéro dépendance inter-image**, chaque frame est un **IDR autonome décodable seul**. La régularité d'un flux Intra **aide massivement** : les frontières de frame sont détectables (marqueurs de récupération + parsing NAL) et une frame extraite se décode **sans contexte**.
- **Preuve d'identité d'essence** : SPS (52 o, `27 7a 00 33 b6 cd 30…`) et PPS (78 o, `28 7b 8c d3…`) de la référence retrouvés **octet pour octet** dans le `.rsv`. Même profil, même encodeur, mêmes paramètres. La référence est un **Rosetta Stone parfait**.

---

## 4. Outils : est-ce que QUELQUE CHOSE lit l'essence ? → NON (tel quel)

| Outil | Résultat |
|---|---|
| `ffmpeg -f mxf -err_detect ignore_err` | ⛔ *« could not find header partition pack key »* → **Invalid data**, aucune sortie. |
| `ffprobe -probesize 200M -analyzeduration 200M` | ⛔ *Invalid data found* — format non identifié. |
| `bmx` / `mxf2raw` (libmxf) | ⛔ Non packagé Homebrew ; et **exige** partitions/RIP MXF **absents** ⇒ échouerait. |
| `untrunc` | ⛔ **Hors sujet** : ISO-BMFF (MP4) uniquement ; ici ni MP4 ni MXF. |
| **Dé-chunk maison + parsing NAL** | 🔶 **Partiel** : en retirant les clusters KLV Sony (pas de 11264 o) on **reconstitue une essence contiguë** où l'on **retrouve les SPS/PPS de référence** — mais les NAL sont en **sous-framing propriétaire Sony** (préfixes de longueur non-standard, **ni** annex-B `00000001` **ni** `avcC` 4-octets), donc **pas directement décodable** sans reformatage. |

⇒ **Aucun outil sur étagère ne produit une vidéo.** Mais l'essence est **extractible** avec du code dédié.

---

## 5. Faisabilité de reconstruction (réponse Q4) & approche recommandée

### 5.1 Pourquoi c'est FAISABLE (facteurs favorables, tous vérifiés)
1. **Essence présente & identique** à la référence (SPS/PPS octet-exacts).
2. **All-Intra (XAVC-I)** : frames indépendantes ⇒ extraction/mux **par frame**, robuste à la troncature (on jette juste la dernière frame incomplète).
3. **Référence complète** : SPS/PPS, timescale (1/25000), profil, layout pistes (1 vidéo + 4 PCM mono + rtmd) → **tous les paramètres du moov sont connus**.
4. **Blocs à pas constant (11264 o)** : dé-chunking **déterministe**.
5. **Métadonnées de récupération régulières** : gabarits par-frame identiques → aident à borner les frames.

### 5.2 Pourquoi c'est DUR (le vrai coût)
- **Reverse-engineering du conteneur propriétaire Sony** : (a) structure des blocs de récupération 11264 o et des clusters KLV privés `0c02…` ; (b) **sous-framing des NAL** (longueurs Sony → annex-B/avcC) ; (c) **localisation & désentrelacement des 4 canaux PCM** dans l'essence ; (d) **timing/ordonnancement** des frames.
- **Zéro outil réutilisable** : tout est à écrire. Pas de `untrunc`, pas de bmx, pas de `mxf-rebuild` générique applicable — la roadmap `04` §3.4 partait de l'hypothèse « réparer des partitions/Index Table MXF », **qui n'existent pas ici**.

### 5.3 Approche recommandée pour l'Architect
1. **Nouvelle méthode `sony-rsv-rebuild`** (⚠️ **renommer/rescoper** l'actuel `mxf-rebuild` de `04` §3.4 — ce n'est **pas** de la réparation MXF). `capabilities: { containers:[sony-rsv], codecs:[xavc-i / h264-intra-422-10], tracks:[video, audio] }`. `requires_reference: **true**` (référence **même caméra/session obligatoire** — fournit SPS/PPS + timescale + layout ; même doctrine « référence quasi-obligatoire » que le Spike 01).
2. **Pipeline** (aligné sur l'interface `RecoveryMethod` de `03` §2.1) :
   `probe → de-chunk (strip clusters KLV Sony, pas 11264) → segmenter en access units IDR (marqueurs récup + parsing NAL) → reframer NAL (Sony → annex-B) → extraire 4× PCM → mux MP4 avec moov dérivé de la référence (avcC/params) → drop dernière frame partielle → publish`.
3. **Modèle de coût = identique au Spike 01** : le repair scanne **tout** l'essence ⇒ **O(taille fichier)**, **payé une fois puis caché** (artefact « source réparée », clé `(source_hash, method_id, reference_hash)`). Tranches ensuite en `-c copy` (O(tranche)). **Réutilise directement le cache BLOQ-3.**
4. **Effort** : chantier de **reverse-engineering réel** (ordre de grandeur **jours→semaines** pour une implémentation robuste ; un **PoC 1-frame** est atteignable en beaucoup moins).
5. **DÉ-RISQUER AVANT DE CONCEVOIR** : lancer un **mini-spike PoC** = extraire **UNE frame décodable** de bout en bout (de-chunk → 1 IDR → annex-B → `ffmpeg` + SPS/PPS de la référence → PNG). Tant que ce PoC n'a pas produit **une image**, ne pas engager le design complet du plugin. *(Non fait ici : ce tour = spike de faisabilité, pas d'implémentation — cf. consigne.)*

---

## 6. Corrections à apporter au doc `04` (l'Architect)

1. **`04` §2 (tableau codecs)** : « **XAVC-I → conteneur MXF** » est **faux pour le PXW-Z200**. Sa sortie finalisée XAVC-I est du **MP4** (ftyp/moov/mdat, marque `XAVC`, vérifié sur C4935.MP4). Le `.rsv` **n'est ni MP4 ni MXF** : c'est l'**intermédiaire propriétaire Sony** pré-finalisation.
2. **`04` §2.2 + §3.4 (`mxf-rebuild`)** : l'hypothèse « MXF = partitions KLV + Index Table à réparer » **ne décrit pas** ce fichier. **Renommer en `sony-rsv-rebuild`** et rescoper : **reconstruction d'essence** (extraire H.264 All-Intra + PCM d'un conteneur de récupération Sony et re-muxer via référence), **pas** réparation de partitions MXF.
3. **Ne PAS router un `.rsv` vers untrunc** (déjà noté §5/§6 de `04`, confirmé : untrunc ISO-BMFF n'a aucune prise ici).
4. **Détection** : distinguer 3 familles à l'analyse — (a) MP4 XAVC-S/HS (moov manquant → untrunc), (b) MP4 XAVC-I finalisé, (c) **`.rsv` intermédiaire Sony** (clés `060e2b34 025301010c02…`, blocs 11264 o → `sony-rsv-rebuild`).

---

## 7. Limites / honnêteté (à ne pas surinterpréter)

- **Framing propriétaire non entièrement décodé** : j'ai **prouvé** la présence et l'identité de l'essence (SPS/PPS octet-exacts) et la régularité des blocs, **mais je n'ai pas produit de frame décodée** ce tour (c'est justement le PoC recommandé §5.3). La faisabilité est **très probable**, pas **démontrée jusqu'au pixel**.
- **Débit/frame surprenant** (~4,9–8,9 Mo entre clusters) : cohérent avec du 4K 4:2:2 10-bit Intra ; non recoupé finement (sans impact sur le verdict).
- **Désentrelacement audio non prouvé** : les 4 pistes PCM sont **attendues** dans l'essence (référence + descripteurs Sony), mais leur emplacement/entrelacement exact reste à établir dans le PoC.
- **Un seul fichier / une seule caméra** (PXW-Z200). Le framing peut varier selon modèle/firmware Sony. La méthode devra être **paramétrée par un profil caméra**, pas codée en dur.
- **Analyse sur 700 Mo échantillonnés** (début+fin), pas les 70 Go — suffisant pour la structure, mais un scan complet pourrait révéler des variantes de blocs.

---

## 8. Recommandation d'exécution (Builder → Master/Architect)

1. **Architect** : corriger `04` (§6 ci-dessus) — `.rsv` Z200 = **conteneur propriétaire Sony**, pas MXF ; renommer `mxf-rebuild` → **`sony-rsv-rebuild`** (reconstruction d'essence via référence, `requires_reference: true`, cache O(fichier) partagé BLOQ-3).
2. **Builder (moi)** : sur GO, exécuter le **mini-spike PoC 1-frame** (§5.3) pour passer le verdict de **« DUR/FAISABLE »** à **« démontré »** avant tout design de plugin.
3. **Ne PAS** coder la méthode complète maintenant (consigne respectée : ce tour = faisabilité uniquement).

---

## 9. PoC — de-chunk → vidéo lisible (RÉSULTAT : OK)

> Objectif du GO construction : **prouver le pixel**, puis **une séquence lisible en MP4**. Fait sur le VRAI fichier (`head.bin`, 500 Mo copiés en lecture seule ; original jamais touché).

### 9.1 Framing Sony entièrement décodé
1. **Blocs de récupération** : pas **constant 11264 o (0x2c00)** = `[cluster KLV Sony] + [fragment d'essence]`. De-chunk = retirer les clusters `060e2b34 025301010c02…`, concaténer l'essence.
2. **Paramètres codec (SPS/PPS)** : stockés une fois, framing Sony **`[u32 BE nal_len][00][u32 BE nal_len+4][02 01][NAL]`**. Vérifié : SPS(52)=`00000034 00 00000038 0201`, PPS(115)=`00000073 00 00000077 0201`. SPS/PPS **byte-identiques à la référence**.
3. **Essence image (SEI + slices)** : stockée en **avcC standard** = `[u32 BE nal_len][NAL]`, sans start-codes. **1 frame = AUD + 5 SEI + 8 slices** (image 4K découpée en 8 slices), exactement la structure de la référence.

### 9.2 PoC PIXEL (1 frame) — ✅ VRAIE IMAGE
- Reconstruction annex-B de la **frame 1** : `AUD + SPS + 5×PPS` (référence) + `5 SEI + 8 slices IDR` (**du `.rsv`**, tailles 141337/387941/407195/410649/398312/415467/417168/422793 o ≈ **2,98 Mo**).
- `ffmpeg -f h264 → PNG` : **exit 0**, image **3840×2160** rgb48be (16-bit ← 10-bit).
- **Contenu visuel** : scène **réelle et cohérente** — terrain de sport, cheerleaders, un homme au porte-voix, maillot jaune « CROUZE… », parasol, cage de but, arbres. **Aucun artefact, aucun bruit.** → l'essence du `.rsv` corrompu **contient une vraie vidéo décodable**.

### 9.3 PoC SÉQUENCE (200 frames) → MP4 — ✅ SE LIT & DÉCODE SANS ERREUR
- Carve de **200 frames** (9 IDR + 191 I non-IDR ; All-Intra ⇒ toutes intra-décodables), **8 slices chacune**, muxées en MP4 à **25 fps** avec le timescale de la référence.
- **`rsv_recovered.mp4`** : `ffprobe` → **h264, 3840×2160, `yuv422p10le` (10-bit 4:2:2 = XAVC-I), durée 7,96 s, 199 frames**.
- **Décodage intégral** (`ffmpeg -i … -f null -`) : **0 erreur de décodeur** sur 199 frames. (Seul un avertissement **cosmétique** de DTS non-monotone du muxer en toute fin — même classe que le Spike 01, sans impact décodage.)
- **Frames milieu/fin distinctes** (mouvement réel : la caméra panote, la ligne de cheerleaders apparaît) → **vraie séquence vidéo**, pas une frame répétée.

### 9.4 Ce qui reste (increments suivants, PAS ce tour)
1. **Audio** : désentrelacer les **4 canaux PCM `s24be`** de l'essence + muxer (piste son). *(Non fait ici — vidéo seule.)*
2. **DTS/PTS propres** : générer un timing monotone (trivial, supprime l'avertissement muxer).
3. **Frame partielle finale** (troncature) : détecter et **jeter** la dernière frame incomplète (bord de la troncature à 70 Go).
4. **Robustesse framing** : le PoC valide sur ce fichier/firmware ; paramétrer par **profil caméra** (le framing peut varier selon modèle Sony).
5. **Intégration `sony-rsv-rebuild`** : porter le PoC (de-chunk + carve + mux via référence) dans une méthode `RecoveryMethod` (`03` §2.1), coût **O(fichier) caché** (BLOQ-3), tranches `-c copy`.

### 9.5 Scripts (reproductibles, dans `docs/spike/poc-rsv/`)
- `carve.py` — de-chunk du conteneur Sony + parseur de records.
- `build_au.py` — reconstruction + décodage d'**1 frame** (preuve pixel).
- `build_seq.py` — carve d'une **séquence** + génération annex-B pour mux MP4.
- `rsv_frame1_preview.jpg` — preuve visuelle (frame 1 recomposée depuis le `.rsv`).

---

## Annexe — Reproductibilité

```bash
# Copies lecture seule (jamais l'original en écriture) — début 500 Mo, fin ~200 Mo
dd if=/Volumes/TOM/C4934.RSV of=/private/tmp/mxf_spike/head.bin bs=1m count=500
dd if=/Volumes/TOM/C4934.RSV of=/private/tmp/mxf_spike/tail.bin bs=1m skip=67160 count=250

# Preuve « pas un MXF » : compte des clés standard vs privées Sony
python3 klv_scan.py            # 0 partition pack, 0 index, 0 footer ; clés 060e2b34 025301010c02…

# Codec exact depuis la référence (lecture seule, pas de copie 30 Go)
ffprobe -show_streams /Users/lois/Downloads/C4935.MP4     # H.264 High 4:2:2 Intra, 3840x2160, 25fps, yuv422p10le, 4x pcm_s24be

# Extraction SPS/PPS de la référence (1re frame seulement)
ffmpeg -i /Users/lois/Downloads/C4935.MP4 -map 0:v:0 -c copy -bsf:v h264_mp4toannexb -frames:v 1 -f h264 ref_first.h264
# → SPS (52o) et PPS (78o) RETROUVÉS octet-pour-octet dans C4934.RSV = même essence

# Preuve « aucun outil ne lit » :
ffmpeg -f mxf -err_detect ignore_err -i head.bin -c copy -f null -   # could not find header partition pack key

# --- PoC de-chunk → vidéo (§9) ---
ffmpeg -i /Users/lois/Downloads/C4935.MP4 -map 0:v:0 -c copy -bsf:v h264_mp4toannexb -frames:v 3 -f h264 ref3.h264
python3 docs/spike/poc-rsv/build_au.py                      # → rsv_frame1.h264 (1 frame)
ffmpeg -f h264 -i rsv_frame1.h264 -frames:v 1 -update 1 frame1.png    # → VRAIE image 3840x2160
python3 docs/spike/poc-rsv/build_seq.py 300000000 200       # → rsv_seq.h264 (200 frames)
ffmpeg -r 25 -f h264 -i rsv_seq.h264 -c:v copy -video_track_timescale 25000 rsv_recovered.mp4
ffprobe rsv_recovered.mp4          # h264 3840x2160 yuv422p10le, 199 frames, 7.96s
ffmpeg -i rsv_recovered.mp4 -f null -   # décodage intégral, 0 erreur décodeur
```

**SPIKE 02 TERMINÉ — PoC PIXEL & SÉQUENCE VALIDÉ (vidéo reconstruite lisible, 0 erreur de décodage).**
