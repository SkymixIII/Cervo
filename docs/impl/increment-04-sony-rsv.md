# Incrément 4 — Méthode `sony-rsv-rebuild` (récupération Sony `.rsv` XAVC-I) DANS L'APP

> Auteur : **Builder**. Porte le **PoC du Spike 02** (`docs/spike/spike-02-mxf.md`,
> `docs/spike/poc-rsv/`) en **méthode `RecoveryMethod` intégrée**, utilisable de bout
> en bout via l'API/UI. Périmètre : **vidéo + audio (4 canaux PCM)** — livrés et validés.
> Statut : ✅ **TERMINÉ — validé end-to-end à travers l'app** (POST media → analyze →
> reference → job → MP4 réparé → preview qui décode **vidéo + audio**).
>
> **MAJ audio** : l'audio **4 canaux PCM s24be** est désormais extrait, désentrelacé et
> muxé (sync A/V verrouillée sur l'horloge vidéo). Correction au passage d'un drop de la
> frame vidéo précédant chaque chunk audio (voir §2/§5).

---

## 0. Rappel du problème (Spike 02)
Le `.rsv` du PXW-Z200 n'est **ni MP4 ni MXF** : c'est un **conteneur de récupération
propriétaire Sony** (clés KLV privées `06 0e 2b 34 02 53 01 01 0c 02`, blocs à pas
constant **11264 o**) écrit **pendant** l'enregistrement. Il contient l'essence
**XAVC-I (H.264 High 4:2:2 Intra, 3840×2160, 25p, 10-bit)** + PCM, mais **aucun
outil sur étagère ne le lit** (ffmpeg/bmx le rejettent). La finalisation en MP4
n'a jamais eu lieu (interruption). Voir Spike 02.

## 1. Ce qui est livré
| # | Livrable | Fichier |
|---|----------|---------|
| 1 | **Plugin `sony-rsv-rebuild`** (RecoveryMethod) | `backend/app/methods/sony_rsv_rebuild.py` |
| 2 | **Détection `.rsv` Sony** (clé KLV privée, sans ftyp/moov) | `backend/app/pipeline/atoms.py` (`is_sony_rsv`) |
| 3 | **Diagnostic `container='sony-rsv'`** + routage | `backend/app/pipeline/analyze.py` |
| 4 | **Enregistrement du plugin** | `backend/app/methods/base.py` (`load_builtin_methods`) |
| 5 | **UI** : badges + note `.rsv` dans le diagnostic | `frontend/src/components/DiagnosticCard.tsx`, `frontend/src/api/types.ts` |
| 6 | **Test unitaire framing** (de-chunk, drop frame partielle, audio) | `backend/tests/test_sony_rsv.py` |

## 2. Architecture de la méthode (`repair`)
Porte le PoC en **streaming borné en mémoire** (le fichier va jusqu'à ~70 Go — on ne
charge **jamais** tout en RAM), **vidéo + audio en UN seul passage** :

```
source .rsv ─[blocs 4 Mo]→ _dechunk (retire clusters KLV Sony) → essence contiguë
   ├─ _walk_frame → access units H.264 (AUD+SEI+slices) → video.h264 (Annex-B, + SPS/PPS réf)
   └─ chunks PCM (entre GOP) → audio.pcm (4ch s24be, longueur verrouillée sur la vidéo)
                                        │
                         ffmpeg mux (vidéo + audio) → repaired.mp4
```

Décisions clés :
- **Framing Sony décodé (Spike 02 §9.1)** : SPS/PPS en records `[u32 len][00][u32 len+4][02 01][NAL]` ;
  essence image (SEI + slices) en **avcC 4 octets** `[u32 len][NAL]`. Frontière de frame = **AUD** (`00 00 00 02 09`).
- **AUDIO (nouveau)** : entre les GOP vidéo, l'essence contient des **chunks PCM s24be
  4 canaux entrelacés** (sans en-tête de longueur), suivis de **padding** (zéros) avant
  l'AUD suivant. On les **désentrelace** en gardant seulement le PCM réel, dont la longueur
  est **verrouillée sur l'horloge vidéo** : `frames_depuis_dernier_chunk × (rate/fps) × 4 × 3`
  octets. → **sync A/V garantie sans dérive**, padding jeté. Chunk délimité par le **prochain
  AUD vidéo validé** (`_find_next_frame_start` rejette les faux AUD dans le PCM silencieux).
- **Correction drop de frame** : une frame vidéo terminée par un chunk audio renvoie le
  statut `audio` (au lieu de `bad`) → la frame qui **précède chaque chunk audio n'est plus
  droppée** (bug latent de l'Incrément 4 vidéo-seule).
- **SPS/PPS depuis la référence** (byte-identiques — Spike 02) : `h264_mp4toannexb -frames:v 1`
  (lit **une seule frame**, pas les 30 Go). fps via `ffprobe r_frame_rate` ; layout audio = 4ch/48 kHz (format Sony fixe).
- **Deux temporaires puis mux** : `video.h264` + `audio.pcm` écrits en streaming, puis **un
  seul ffmpeg** mux `-c copy`. (Choix : **1 lecture** de la source — ménage le disque USB
  original ; coût disque interne transitoire ~2× la source, supprimé après publication.)
- **All-Intra ⇒** chaque frame indépendante : carve déterministe, robuste à la troncature.
- **Drop de la dernière frame partielle** : `_walk_frame` ne rend une frame que **terminée
  par l'AUD suivant** → frame amorcée sans AUD final (bord troncature) **jamais** émise.
- **Annulation (non-négociable d)** : PID ffmpeg publié (`on_child_pid`) + `is_canceled()`
  sondé à chaque bloc (passage streaming) et pendant le mux → kill du groupe + `Canceled`.
- **Progression** : `on_progress` — 0→90 % (streaming), 92→100 % (mux).
- **Périmètre média** : l'artefact réparé contient **toujours vidéo + audio** ; `scope`
  (`audio`/`video`/`both`) est appliqué **en aval** par le slice `-c copy` (`-map`).
- **Cache/pipeline inchangé** : `repair()` retourne `tmp_dir/repaired.mp4`, publié
  atomiquement par `cache.get_or_repair` (BLOQ-3). Coût = **O(fichier), payé une fois, caché**.

## 3. Routage (diagnostic → méthode)
- `is_sony_rsv(path)` : clé KLV Sony présente dans les **4 premiers Mo** ET pas de `ftyp` → `container='sony-rsv'`,
  `codec.video='h264'`, `family='xavc-i'`, `recoverable=true`, `recommendation='reference_required'`.
- `sony-rsv-rebuild.can_handle` → **applicable, confidence 0.9** si `container=='sony-rsv'`.
- `untrunc-moov.can_handle` → **non applicable** (retourne « conteneur non MP4 ») : pas de collision.
- `resolve_method_id('auto', diag)` → `sony-rsv-rebuild`.

## 4. Preuve d'intégration end-to-end (à travers l'app, port 8080)
Fixtures (aucun fichier de 70 Go déplacé) : segment **300 Mo** de `C4934.RSV` copié en
lecture seule + **référence courte ~2 s** extraite de `C4935.MP4`, tous deux sous la racine média.

| Étape | Appel | Résultat |
|---|---|---|
| Enregistrement source | `POST /api/media {path:C4934_test.rsv}` | `source_id`, size 314 572 800 |
| Analyse | `POST /api/media/{id}/analyze` | **`container=sony-rsv`**, codec `xavc-i/h264`, `recommendation=reference_required` |
| Méthodes applicables | `GET /api/methods/applicable?source=…` | **`sony-rsv-rebuild`** (HAUTE, `requires_reference=true`) — seule |
| Référence | `POST /api/references {path:C4935_ref.mp4}` | `reference_id` |
| Job | `POST /api/jobs {method:sony-rsv-rebuild, scope:both, slice:1min, reference}` | `succeeded` |
| Preview | `GET /api/jobs/{id}/preview` | **MP4 : vidéo h264 3840×2160 `yuv422p10le` (17,0 s) + audio `pcm_s24be` 48 kHz 4 canaux (16,8 s)** |
| Décodage | `ffmpeg -i preview -f null -` | **0 erreur de décodeur** (vidéo **et** audio) |
| Audio réel | analyse waveform | peak 22768 / moyenne 232 / 8 % passages par zéro → **vrai signal audio** (ni silence, ni bruit) |
| Sync A/V | durées par piste | vidéo 17,04 s / audio 16,80 s — **verrou frame-par-frame, pas de dérive** (≈0,2 s de queue = bord du segment 300 Mo) |
| Visuel | frame extraite | **image réelle cohérente** (terrain de sport, cheerleaders, maillot « CROUZE… ») |

→ **La vidéo ET l'audio récupérés depuis le `.rsv` corrompu SE LISENT dans l'app.**
L'utilisateur pourra lancer la récupération du **fichier 70 Go complet** depuis l'UI.

## 5. Limites & prochains incréments
- **Pistes audio** : les 4 canaux sont muxés en **une piste 4 canaux** (fidèle à l'essence).
  Un découpage en 4 pistes mono (comme la finalisation MP4 native) est possible plus tard si besoin.
- **Disque interne** : le passage écrit `video.h264` (~taille source) + `audio.pcm` puis mux →
  pic transitoire ~2× la source (supprimé après publication). Sur un rush 70 Go, prévoir l'espace
  de travail ; optimisable (mux via FIFO) si nécessaire.
- **DTS/PTS** : `-r <fps>` + `+genpts` donnent un timing régulier ; avertissement muxer
  cosmétique résiduel possible (sans impact décodage, cf. Spike 01/02).
- **Profil caméra** : framing (vidéo **et** cadence audio) validé sur PXW-Z200 (ce firmware).
  À paramétrer par **profil caméra** avant d'élargir à d'autres modèles Sony.
- **Durée estimée** : `null` au diagnostic (pas d'index avant reconstruction) — connue après repair.

## 6. Nommage
Méthode nommée **`sony-rsv-rebuild`** partout (l'ancienne roadmap `mxf-rebuild` de
`docs/architecture/04` était une hypothèse « réparation MXF » **invalidée** par le
Spike 02 : ce n'est pas du MXF). Aucun plugin `mxf-rebuild` n'existait en code. La
correction des libellés `mxf-rebuild` dans `03`/`04` reste à faire côté **Architect**
(cf. Spike 02 §6).
