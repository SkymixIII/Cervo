#!/usr/bin/env bash
# Wrapper untrunc encapsulé (Spike 01 + arbitrage #2 §8.5).
#
# Permet à l'app d'appeler untrunc sans binaire local : délègue à l'image Docker
# `untrunc` (base Ubuntu + ffmpeg <= 8.0, cf. Spike 01). Astuce clé : on monte les
# racines média/travail À L'IDENTIQUE (host path == container path) pour que les
# chemins ABSOLUS passés par l'app fonctionnent tels quels dans le conteneur.
#
# DockerManager formalisera le packaging (untrunc embarqué dans l'image `app`) ;
# ce wrapper garde le code agnostique en attendant. Pointez-y via :
#   export APP_UNTRUNC_CMD="/chemin/scripts/untrunc-docker.sh"
set -euo pipefail

mounts=()
[ -n "${APP_MEDIA_ROOT:-}" ] && mounts+=(-v "$APP_MEDIA_ROOT:$APP_MEDIA_ROOT")
[ -n "${APP_WORK_ROOT:-}" ]  && mounts+=(-v "$APP_WORK_ROOT:$APP_WORK_ROOT")

# ⚠️ Garde-fou "montage partagé" (post-review) : si Docker ne partage PAS le chemin
# hôte (ex. /var/folders sur macOS, ou un dossier hors File Sharing de Docker
# Desktop), le bind-mount monte un dossier VIDE et untrunc échoue par un obscur
# « No such file or directory ». On détecte ça (racine média visible mais vide) et on
# renvoie un message clair (exit 3) AVANT de lancer untrunc. `$APP_MEDIA_ROOT`
# contient toujours au moins la source + la référence au moment de l'appel.
guard="${APP_MEDIA_ROOT:-}"

exec docker run --rm --user "$(id -u):$(id -g)" "${mounts[@]}" \
  --entrypoint /bin/sh untrunc -c '
    d="$1"; shift
    if [ -n "$d" ] && [ -z "$(ls -A "$d" 2>/dev/null)" ]; then
      echo "untrunc-docker: le chemin monte \"$d\" est INVISIBLE/VIDE dans le conteneur." >&2
      echo "  -> Docker ne partage probablement pas ce chemin. Placez les medias sous" >&2
      echo "     un chemin partage par Docker (ex. /private/tmp, \$HOME) ou ajoutez-le" >&2
      echo "     au File Sharing de Docker Desktop." >&2
      exit 3
    fi
    exec /bin/untrunc "$@"
  ' _ "$guard" "$@"
