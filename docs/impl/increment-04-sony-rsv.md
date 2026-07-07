# Incrément 4 — Méthode `sony-rsv-rebuild` (récupération Sony `.rsv` XAVC-I) DANS L'APP

> Auteur : **Builder**. Porte le **PoC du Spike 02** (`docs/spike/spike-02-mxf.md`,
> `docs/spike/poc-rsv/`) en **méthode `RecoveryMethod` intégrée**, utilisable de bout
> en bout via l'API/UI. Périmètre : **vidéo obligatoire (livrée)** ; **audio best-effort (TODO)**.
> Statut : ✅ **TERMINÉ — validé end-to-end à travers l'app** (POST media → analyze →
> reference → job → MP4 réparé → preview qui décode une vraie vidéo).

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
| 6 | **Test unitaire framing** (de-chunk + drop dernière frame partielle) | `backend/tests/test_sony_rsv.py` |

## 2. Architecture de la méthode (`repair`)
Porte le PoC en **streaming borné en mémoire** (le fichier va jusqu'à ~70 Go — on ne
charge **jamais** tout en RAM) :

```
source .rsv ──[lecture par blocs 4 Mo]──▶ _dechunk (retire clusters KLV Sony)
   ──▶ essence contiguë ──▶ _walk_frame (carve access units avcC : AUD+SEI+slices)
   ──▶ Annex-B (SPS/PPS de la référence + slices du .rsv) ──[pipe stdin]──▶ ffmpeg ──▶ repaired.mp4
```

Décisions clés :
- **Framing Sony décodé (Spike 02 §9.1)** : SPS/PPS en records `[u32 len][00][u32 len+4][02 01][NAL]` ;
  essence image (SEI + slices) en **avcC 4 octets** `[u32 len][NAL]`. Frontière de frame = **AUD** (`00 00 00 02 09`).
- **SPS/PPS depuis la référence** (byte-identiques — Spike 02) : `ffmpeg -bsf:v h264_mp4toannexb -frames:v 1`
  sur `ctx.reference_path` (lit **une seule frame**, pas les 30 Go). fps lu via `ffprobe r_frame_rate`.
- **Pas de gros fichier intermédiaire** : l'Annex-B est **pipé dans `stdin` de ffmpeg** ; seul le MP4 final touche le disque.
- **All-Intra ⇒** chaque frame indépendante : carve par frame déterministe, robuste à la troncature.
- **Drop de la dernière frame partielle** : `_walk_frame` ne rend une frame que
  **terminée par l'AUD suivant** → une frame amorcée sans AUD final (bord de la
  troncature) n'est **jamais** émise. (Testé : `test_walk_frame_drops_last_partial`.)
- **Annulation (non-négociable d)** : `ctx.on_child_pid(ffmpeg.pid)` publié pour kill
  inter-process ; `ctx.is_canceled()` sondé à chaque bloc → kill du groupe ffmpeg + `Canceled`.
- **Progression** : `ctx.on_progress(bytes_lus / taille * 100)`.
- **Intégration cache/pipeline inchangée** : `repair()` retourne `tmp_dir/repaired.mp4`,
  publié atomiquement par `cache.get_or_repair` (BLOQ-3) ; les tranches (`-c copy`) et
  `extend` en dérivent sans re-réparer. Coût repair = **O(fichier), payé une fois, caché**.

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
| Job | `POST /api/jobs {method:sony-rsv-rebuild, scope:video, slice:1min, reference}` | `succeeded` |
| Preview | `GET /api/jobs/{id}/preview` | **MP4 h264 3840×2160 `yuv422p10le`, 392 frames, 15,6 s** |
| Décodage | `ffmpeg -i preview -f null -` | **0 erreur de décodeur** |
| Visuel | frame extraite | **image réelle cohérente** (terrain de sport, cheerleaders, maillot « CROUZE… ») |

→ **La vidéo récupérée depuis le `.rsv` corrompu SE LIT dans l'app.** L'utilisateur
pourra lancer la récupération du **fichier 70 Go complet** lui-même depuis l'UI.

## 5. Limites & prochains incréments
- **AUDIO (TODO)** : désentrelacement des **4 canaux PCM `s24be`** de l'essence + mux
  piste son. Non livré ici (périmètre : vidéo obligatoire, audio best-effort). `scope=audio`
  produira une sortie vide tant que l'audio n'est pas porté ; `scope=video`/`both` = vidéo OK.
- **DTS/PTS** : `-r <fps>` sur l'entrée pipe donne un timing régulier ; un avertissement
  muxer cosmétique résiduel possible (sans impact décodage, cf. Spike 01/02).
- **Profil caméra** : framing validé sur PXW-Z200 (ce firmware). À paramétrer par
  **profil caméra** avant d'élargir à d'autres modèles Sony (le framing peut varier).
- **Durée estimée** : `null` au diagnostic (pas d'index avant reconstruction) — connue après repair.

## 6. Nommage
Méthode nommée **`sony-rsv-rebuild`** partout (l'ancienne roadmap `mxf-rebuild` de
`docs/architecture/04` était une hypothèse « réparation MXF » **invalidée** par le
Spike 02 : ce n'est pas du MXF). Aucun plugin `mxf-rebuild` n'existait en code. La
correction des libellés `mxf-rebuild` dans `03`/`04` reste à faire côté **Architect**
(cf. Spike 02 §6).
