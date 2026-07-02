# 02 — UI Screens & Components (MediaNotFound)

> Livrable Architecte. Décrit **écrans, composants et états** de l'interface web. S'appuie sur les parcours de `01-ux-flows.md`. N'impose pas de framework CSS précis (voir stack en `03`), mais fixe la structure et le comportement.

## 0. Principes UI

- **Single-page app** à zones fixes : l'utilisateur ne « change pas de page », il progresse dans un flux à l'intérieur d'un layout stable → réduit la charge mentale en situation de stress.
- **Layout 3 zones** : (A) colonne gauche = source & options, (B) centre = lecteur/preview & statut, (C) droite = historique des tentatives.
- **Progressive disclosure** : le vocabulaire technique (moov, untrunc, MXF) est masqué par défaut, accessible via un toggle **« Mode avancé »**.
- **États toujours explicites** : chaque zone a des états `vide / chargement / prêt / erreur` clairement rendus.
- **Responsive** : sur petit écran, les 3 colonnes se replient en onglets (Source / Lecteur / Historique).

---

## 1. Carte des écrans / vues

L'app est essentiellement **un écran principal** (« Workbench ») avec des **panneaux** et des **modales** contextuelles.

```
┌───────────────────────────────────────────────────────────────────────┐
│  TopBar : logo MediaNotFound · [Mode avancé ⌄] · état serveur/worker    │
├──────────────┬─────────────────────────────────────┬───────────────────┤
│  (A) SOURCE  │        (B) LECTEUR / STATUT          │  (C) HISTORIQUE   │
│  & OPTIONS   │                                      │  DES TENTATIVES   │
│              │                                      │                   │
│  - Fichier   │   ┌───────────────────────────────┐  │  ▸ Tentative #3   │
│  - Diagnostic│   │        Lecteur vidéo          │  │  ▸ Tentative #2   │
│  - Périmètre │   │   [ selecteur 1m | 5m | full ]│  │  ▸ Tentative #1   │
│  - Tranche   │   └───────────────────────────────┘  │                   │
│  - Référence │   Zone statut/progression            │  (source courante)│
│  - Méthode   │   [██████░░░░ 62%] Reconstruction…   │                   │
│  - [Lancer]  │   Verdict : (Oui ✓ / Non ✗)          │                   │
└──────────────┴─────────────────────────────────────┴───────────────────┘
```

Vues secondaires : **Modale « Méthodes alternatives »**, **Modale « Log technique »**, **Écran vide/onboarding** (premier lancement, aucun fichier).

---

## 2. Zone A — Source & Options de récupération

### A1. Panneau « Fichier source »
- **Composant `FileInput`** : champ chemin + bouton parcourir + zone drag&drop d'upload.
- Bouton **« Analyser »**.
- États : vide / en analyse (spinner) / analysé (résumé) / erreur (chemin invalide).

### A2. Panneau « Diagnostic » (sortie de l'analyse)
- **Composant `DiagnosticCard`** (lecture seule) :
  - Badges d'état : `mdat détecté ✅`, `moov manquant ⚠️`, conteneur (`MP4`/`MXF`), codec présumé (`XAVC-S`…).
  - Métadonnées : durée estimée, taille, résolution/fps si détectés.
  - Ligne de **recommandation** (ex. « Fournir un fichier de référence conseillé »).
- Mode avancé : dump structurel repliable (liste des atomes/boxes trouvés).

### A3. Panneau « Options de récupération »
- **`MediaScopeSelector`** — segmented control 3 options : **Son seul / Vidéo seule / Les deux**. Options indisponibles grisées + tooltip.
- **`SliceSelector`** — segmented control 3 options : **1 min / 5 min / Intégrale**. Défaut = 1 min. Note pédagogique sous le contrôle.
- **`ReferenceFileInput`** — même composant que A1, **affiché conditionnellement** (si méthode requiert une référence). Affiche un badge compatibilité `✓ compatible` / `✗ incompatible (codec différent)` après validation backend.
- **`MethodSelector`** — dropdown/cartes : **Auto (recommandée)** par défaut ; en mode avancé, liste des méthodes pluggables applicables avec prérequis.

### A4. Barre d'action
- **`LaunchButton`** « Lancer la récupération » — désactivé tant que les prérequis ne sont pas réunis (fichier analysé, référence valide si requise).
- Récapitulatif compact au survol/au-dessus du bouton (fichier · périmètre · tranche · méthode).

---

## 3. Zone B — Lecteur & Statut

### B1. `VideoPlayer` (lecteur intégré)
- Lecteur HTML5 standard (vidéo + audio), affiche la **tranche récupérée** courante.
- **`SliceTabs`** intégrés au lecteur : onglets **1 min | 5 min | Intégrale**.
  - Cliquer sur un onglet **charge la sortie correspondante SI elle existe déjà** ; sinon propose de **lancer** la récupération de cette tranche (réutilise le flux [4]→[6]).
  - Visuellement : onglet plein = tranche disponible ; onglet estompé + icône = à générer.
- Contrôles : play/pause, seek, volume, plein écran, piste audio (si son seul/les deux).
- État « son seul » : le lecteur affiche une **waveform / placeholder audio** au lieu de l'image.
- États : vide (aucune preview) / chargement / prêt / erreur de lecture.

### B2. `StatusPanel` (statut & progression)
- **`ProgressBar`** + libellé d'étape lisible : `En file → Analyse → Reconstruction → Encodage tranche → Terminé`.
- **`Elapsed/ ETA`** si disponible.
- **`StepLog`** : timeline des étapes franchies (icônes ✓), avec bouton **« Voir le log technique »** → modale (mode avancé).
- Bouton **`Cancel`** pendant l'exécution.
- États : idle / running / success / failed / canceled — chacun avec couleur + icône distinctes.

### B3. `VerdictBar` (feedback humain)
- Apparaît après un **succès technique** sur une tranche.
- Question : « Cette récupération est-elle satisfaisante ? » + boutons **`Oui ✓`** / **`Non ✗`**.
- Chips optionnels de qualification : `image OK` `son OK` `saccadé` `artefacts` `son absent`.
- Après « Oui » → révèle **`ExtendButton`** « Récupérer l'intégralité » (si la tranche n'était pas déjà l'intégrale).
- Après « Non » → ouvre la **modale Méthodes alternatives** (M1).

### B4. `ResultActions`
- En cas de résultat validé/intégrale : **`Download` / chemin de sortie**, **`OpenInPlayer`**, **`CopyPath`**.

---

## 4. Zone C — Historique des tentatives

### C1. `AttemptHistoryList`
- Liste chronologique (plus récent en haut) des tentatives **pour le fichier source courant**.
- **`AttemptCard`** par item :
  - Numéro + horodatage.
  - Méthode utilisée (badge).
  - Périmètre média + tranche (icônes).
  - Statut technique (succès/échec/annulé) + verdict humain (✓/✗/—).
  - Résumé qualité (chips).
  - Actions : **`Rejouer`** (re-préremplit les options), **`Étendre à l'intégrale`** (si tranche validée), **`Voir log`**.
- Les méthodes **déjà tentées** sont marquées → évite les doublons.
- Filtre/tri léger : par statut, par méthode.
- État vide : « Aucune tentative pour ce fichier. »

---

## 5. Modales & vues secondaires

### M1. Modale « Méthodes alternatives »
- Déclenchée par échec ou verdict négatif.
- **`MethodCard`** par méthode pluggable applicable :
  - Nom simple + 1 ligne de description.
  - Prérequis : `référence requise ? oui/non`, codec/conteneur supportés.
  - Indicateur de pertinence pour ce diagnostic (ex. « Recommandé pour XAVC-S/MP4 »).
  - Badge « déjà essayée » le cas échéant.
  - Bouton **`Choisir cette méthode`** → retour au flux avec options pré-remplies (tranche remise à 1 min).
- Méthodes non applicables : listées grisées avec la raison (« codec H.265 non supporté par cette méthode »).

### M2. Modale « Log technique »
- Sortie brute (ffmpeg / outil de réparation), copiable, filtrable par niveau.
- Réservée au mode avancé.

### M3. Écran d'accueil / vide
- Affiché au premier lancement (aucun fichier).
- Zone drag&drop centrale + explication courte du principe « preview d'abord ».
- Lien vers la doc/formats supportés.

---

## 6. Inventaire des composants (récap)

| Composant | Zone | Rôle |
|-----------|------|------|
| `FileInput` | A1 | Saisie/upload du fichier abîmé |
| `DiagnosticCard` | A2 | Résultat de l'analyse structurelle |
| `MediaScopeSelector` | A3 | Son / Vidéo / Les deux |
| `SliceSelector` | A3 | 1 min / 5 min / Intégrale |
| `ReferenceFileInput` | A3 | Fichier de référence (conditionnel) + compat |
| `MethodSelector` | A3 | Choix méthode (Auto / avancé) |
| `LaunchButton` | A4 | Démarre le job |
| `VideoPlayer` + `SliceTabs` | B1 | Lecture preview + bascule de tranche |
| `StatusPanel` (`ProgressBar`,`StepLog`,`Cancel`) | B2 | Suivi du job |
| `VerdictBar` (+`ExtendButton`) | B3 | Feedback humain succès/échec |
| `ResultActions` | B4 | Téléchargement / export |
| `AttemptHistoryList` / `AttemptCard` | C1 | Historique des tentatives |
| `MethodCard` (modale) | M1 | Choix de méthode alternative |
| `LogModal` | M2 | Log technique brut |
| `EmptyState` | M3 | Onboarding |

---

## 7. États globaux de l'écran principal

| État app | A | B | C |
|----------|---|---|---|
| Aucun fichier | EmptyState | vide | vide |
| Fichier en analyse | spinner | vide | vide |
| Analysé, prêt à lancer | options actives | vide/placeholder | historique (si existant) |
| Job en cours | figé (récap) | ProgressBar active | tentative « en cours » |
| Succès tranche | options | Player + VerdictBar | +1 tentative (succès) |
| Échec | options | erreur + CTA alternatives | +1 tentative (échec) |
| Intégrale exportée | options | Player + ResultActions | tentative « intégrale ✓ » |

Ces états doivent être **pilotés par le statut du job** renvoyé par l'API (voir `03-backend-architecture.md`, section jobs & formats de réponse).
