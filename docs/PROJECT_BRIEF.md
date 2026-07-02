# MediaNotFound — Brief projet

> Source de vérité maintenue par **Master** (orchestrateur de la squad). Toute instance doit lire ce fichier avant de travailler.

## Concept
Application **web** (interface tournant sur un **serveur Docker en local**) qui analyse des fichiers vidéo corrompus issus de caméras et tente de **récupérer la vidéo et le son**. Elle analyse les patterns/structure du fichier et essaie de le réparer.

## Périmètre V1 (prioritaire)
Récupération des fichiers vidéo **Sony corrompus au format `.rsv`** — tous les codecs Sony / XAVC.

### Notes techniques (hypothèses à VALIDER par l'Architecte via recherche)
- Un `.rsv` Sony est généralement un enregistrement **XAVC interrompu** (coupure batterie, crash carte, retrait à chaud). Le fichier contient les données audio/vidéo brutes (atome `mdat`) mais l'**index/metadata (atome `moov`) est absent ou incomplet**, rendant le fichier illisible.
- Piste de récupération classique : **reconstruire l'atome `moov`** à partir d'un **fichier de référence sain** issu de la même caméra/réglages (approche type `untrunc`, analyse de structure MP4/MXF, `ffmpeg`).
- ⚠️ À confirmer : liste exacte des codecs Sony concernés (XAVC-S, XAVC-HS, XAVC-I…), conteneurs (MP4 vs MXF), et si un fichier de référence est requis.

## Fonctionnalités
1. **Entrée** : champ pour renseigner un **lien / chemin** vers le fichier abîmé.
2. **Options de récupération** : `son seul` / `vidéo seule` / `les deux`.
3. **Prévisualisation par tranches** : `1 min` / `5 min` / `intégrale` — pour **accélérer le process** et ne pas recompiler toute la vidéo depuis le début.
4. **Lecteur vidéo** intégré avec sélecteur de tranche (1 min / 5 min / full).
5. **Feedback post-tentative** : l'utilisateur indique si la récupération a **fonctionné ou non**.
6. **Méthodes alternatives** : si échec, relancer avec **une autre méthode de récupération** → architecture modulaire de "méthodes de récupération" **pluggables**.

## Contraintes
- Interface **web**.
- Tourne **en local sur un serveur Docker** (portable, conteneurisé).
- Architecture pensée pour être **extensible** à d'autres marques/formats après la V1 Sony `.rsv`.

## Stack
- **Non imposée** par l'utilisateur → à proposer par l'Architecte. Contraintes implicites : conteneurisable Docker, traitement vidéo lourd côté backend (probablement `ffmpeg` + outils de réparation de conteneur MP4/MXF).

## Rôles de la squad
| Instance | Rôle |
|----------|------|
| **Master** | Orchestration, brief, coordination, points d'étape |
| **Architect** | Conçoit UX/UI/archi backend → écrit des `.md`, ne code pas |
| **CounterPower** | Contre-pouvoir : review critique archi puis code |
| **Builder** | Implémente le code, applique les reviews |
| **DockerManager** | Conteneurise l'appli (Docker, portabilité) |

## Workflow
Architect (archi .md) → CounterPower (review archi) → Builder (code) → CounterPower (review code) → DockerManager (conteneurisation).
