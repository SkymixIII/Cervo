# 01 — UX Flows (MediaNotFound)

> Livrable Architecte. Décrit les **parcours utilisateur** de bout en bout. Ne décrit pas les écrans en détail (voir `02-ui-screens.md`) ni l'implémentation (voir `03-backend-architecture.md`).

## 0. Persona & contexte d'usage

- **Utilisateur type** : vidéaste / monteur / opérateur qui vient de « perdre » un rush Sony (fichier `.rsv` illisible après coupure batterie, retrait carte, crash).
- **État émotionnel** : stressé, veut savoir **vite** si la vidéo est récupérable, sans re-traiter 40 min de rush à chaque essai.
- **Compétence technique** : variable. L'UX ne doit **jamais** exiger de connaître « moov atom », « untrunc » ou « MXF ». Ces notions restent internes, exposées seulement en libellés simples et en mode « avancé ».
- **Environnement** : app web servie par un conteneur Docker **local** (LAN / localhost). Les fichiers sont sur le même hôte ou un partage monté.

### Principe UX directeur
> **« Preview d'abord, intégrale ensuite. »** On ne recompile jamais tout un rush pour découvrir que la méthode ne marche pas. On valide sur une **tranche courte (1 min)**, puis on étend.

---

## 1. Vue d'ensemble du parcours (happy path)

```
[1] Saisie fichier abîmé
        │
        ▼
[2] Analyse automatique (détection format/codec/conteneur, diagnostic)
        │
        ▼
[3] Choix du périmètre média : son seul / vidéo seule / les deux
        │
        ▼
[4] Choix de la tranche : 1 min / 5 min / intégrale
        │
        ▼
[5] (Optionnel/conditionnel) Fournir un fichier de référence sain
        │
        ▼
[6] Lancement de la tentative de récupération (job)
        │
        ▼
[7] Feedback progression temps réel (statut, %, logs simplifiés)
        │
        ├── Succès technique → [8a] Preview lecteur + verdict utilisateur (ça marche ?)
        │        │
        │        ├── Utilisateur : « ça marche » → [9] Étendre à l'intégrale / Export
        │        └── Utilisateur : « ça ne marche pas » → [10] Relance méthode alternative
        │
        └── Échec technique → [8b] Diagnostic d'échec + [10] Relance méthode alternative
```

Le point clé : les étapes **[6]→[8]** tournent d'abord sur la **tranche 1 min** choisie en [4]. L'extension à l'intégrale ([9]) n'est proposée **qu'après** validation humaine.

---

## 2. Étapes détaillées

### [1] Saisie du fichier abîmé
- L'utilisateur renseigne un **chemin** (fichier monté dans le conteneur) ou **uploade** un fichier via l'interface.
- Champ unique + bouton « Analyser ».
- Validation immédiate : le fichier existe-t-il ? extension attendue (`.rsv`, `.mp4`, `.mxf`) ? taille non nulle ?
- **Erreurs traitées** : chemin introuvable, permissions, fichier vide, format non supporté (message clair + suggestion).

### [2] Analyse automatique (diagnostic)
- Déclenchée sans action supplémentaire dès la saisie validée.
- Le backend inspecte la structure : conteneur détecté (MP4/MXF), présence/absence des atomes clés (`ftyp`, `mdat`, `moov`), codec présumé (XAVC-S / HS / I / L), durée estimée à partir du `mdat`.
- **Résultat affiché à l'utilisateur (langage simple)** :
  - ✅ « Données vidéo/audio détectées » (mdat présent)
  - ⚠️ « Index de lecture manquant » (moov absent → cas nominal `.rsv`)
  - Codec / format reconnu, durée estimée, taille.
  - **Recommandation** : « Un fichier de référence sain de la même caméra améliorera fortement les chances. » (si méthode le requiert)
- Si le diagnostic indique un cas **non récupérable connu** (ex. `mdat` absent/tronqué à zéro), on le dit franchement dès ici.

### [3] Choix du périmètre média
- 3 options exclusives : **Son seul** / **Vidéo seule** / **Les deux** (défaut).
- Sert à cibler les pistes à reconstruire → plus rapide si l'utilisateur ne veut que l'audio (ex. sauver une interview).
- Si le diagnostic n'a détecté qu'une seule piste, les options impossibles sont grisées avec explication.

### [4] Choix de la tranche
- 3 options exclusives : **1 min** / **5 min** / **Intégrale**.
- **Défaut = 1 min** (aligné sur le principe directeur : itérer vite).
- Libellé pédagogique : « Testez sur 1 min avant de lancer l'intégrale — c'est bien plus rapide. »
- La tranche = les **N premières minutes** du média récupérable (offset 0 par défaut ; un offset de départ est une évolution possible mais hors périmètre V1).

### [5] Fichier de référence (conditionnel)
- Affiché **uniquement** si la méthode de récupération sélectionnée en a besoin (cas untrunc / reconstruction moov).
- Même UX de saisie qu'en [1] (chemin ou upload).
- Aide contextuelle : « Une vidéo **saine**, tournée avec la **même caméra et les mêmes réglages** (codec, résolution, framerate). Pas besoin qu'elle ait la même durée. »
- Le backend **valide la compatibilité** référence↔abîmé (même codec/conteneur/profil) et alerte si incompatible **avant** de lancer.
- Si aucune méthode nécessitant une référence n'est retenue (méthode auto « best-effort » sans référence), l'étape est sautée.

### [6] Lancement de la tentative
- Bouton « Lancer la récupération ».
- Récapitulatif avant lancement : fichier, périmètre média, tranche, méthode choisie, référence (si fournie).
- Crée un **job** côté backend (voir `03`). L'UI bascule en mode suivi.
- La **méthode** peut être choisie explicitement (mode avancé) ou laissée en **« Auto (recommandée) »** : le backend sélectionne la 1re méthode applicable selon le diagnostic.

### [7] Feedback de progression (temps réel)
- Barre de progression + statut lisible : `En file` → `Analyse` → `Reconstruction` → `Encodage tranche` → `Terminé`.
- Journal simplifié (étapes franchies), avec accès à un **log technique détaillé** repliable (mode avancé).
- Estimation de temps restant si disponible.
- Action **Annuler** possible à tout moment (le job s'arrête proprement).

### [8a] Succès technique → verdict utilisateur
- La tranche récupérée est chargée dans le **lecteur intégré** (voir `02`).
- L'utilisateur **visionne** et **écoute** la tranche.
- Question explicite : **« Cette récupération est-elle satisfaisante ? »** → boutons **« Oui, ça marche »** / **« Non, ça ne marche pas »**.
- Ce verdict humain est enregistré dans l'**historique des tentatives** et sert à piloter la suite.
- Nuances possibles (chips optionnels) : « image OK / son absent », « image saccadée », « artefacts » → alimente le choix de la méthode alternative.

### [8b] Échec technique
- Le job échoue (méthode inapplicable, référence incompatible, données trop endommagées).
- Message clair **orienté action** : ce qui a échoué + **quoi tenter ensuite** (autre méthode, fournir/changer la référence, réduire le périmètre à « son seul »).
- On propose directement **[10] Relance avec méthode alternative**.

### [9] Extension à l'intégrale / Export
- Proposé après un verdict **« ça marche »** sur une tranche courte.
- Bouton **« Récupérer l'intégralité »** : relance la **même méthode + mêmes réglages validés**, mais sur la durée **intégrale**.
- À la fin : **téléchargement** du fichier réparé (ou chemin de sortie sur le volume monté) + récapitulatif (durée, pistes, méthode utilisée).
- La preview 1 min ayant validé l'approche, l'intégrale a une très forte probabilité de réussir → pas de recompilation « à l'aveugle ».

### [10] Relance avec méthode alternative
- Accessible depuis un échec **[8b]** ou un verdict négatif **[8a]**.
- L'UI présente les **autres méthodes de récupération** applicables (architecture pluggable — voir `03`/`04`), triées par pertinence selon le diagnostic et l'historique.
- Chaque méthode = carte avec : nom simple, prérequis (référence ? oui/non), taux de réussite indicatif pour ce type de fichier.
- L'utilisateur choisit → retour en **[4]/[5]/[6]** avec les réglages pré-remplis (on repart en général sur **1 min** pour re-valider vite).
- Chaque relance = **nouvelle entrée d'historique** liée au même fichier source → l'utilisateur voit ce qu'il a déjà essayé.

---

## 3. Parcours d'échec & cas limites

| Cas | Détection | Réaction UX |
|-----|-----------|-------------|
| Chemin/upload invalide | [1] | Message + correction immédiate, pas de job créé |
| Format non supporté | [2] | Diagnostic honnête, pas de fausse promesse |
| `mdat` absent / vide | [2] | « Fichier non récupérable » expliqué, pas de job |
| Codec sans méthode dispo (ex. XAVC-HS et seule méthode = untrunc H.264) | [2]/[6] | Méthode grisée + explication ; proposer méthodes alternatives ou « à venir » |
| Référence incompatible | [5]/[6] | Blocage avant lancement + demande d'une autre référence |
| Job échoue en cours | [7]→[8b] | Diagnostic + relance méthode alternative |
| Verdict humain négatif | [8a] | Historisé + méthode alternative |
| Annulation | [7] | Job stoppé proprement, état « annulé » dans l'historique |

---

## 4. Historique des tentatives (transversal)

- Chaque fichier source possède une **liste chronologique de tentatives**.
- Une tentative = { méthode, périmètre média, tranche, référence utilisée, statut technique, verdict humain, durée, sortie }.
- Objectifs UX :
  1. **Ne pas retenter deux fois la même chose** (méthodes déjà essayées marquées).
  2. **Comparer** les résultats (ex. méthode A = image saccadée, méthode B = OK).
  3. **Reprendre** une tentative réussie sur tranche pour l'étendre à l'intégrale.
- Consultable depuis l'écran principal (panneau latéral ou onglet — voir `02`).

---

## 5. Boucle d'itération résumée (le cœur du produit)

```
Choisir méthode ─▶ Tester sur 1 min ─▶ Visionner ─▶ Verdict
      ▲                                                  │
      │                                                  ▼
      └──── « ça ne marche pas » ◀──────────────  « ça marche » ─▶ Étendre à l'intégrale ─▶ Export
        (méthode alternative,
         historique mis à jour)
```

Cette boucle courte, peu coûteuse en calcul, est la **valeur centrale** de MediaNotFound face aux outils « tout ou rien ».
