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

exec docker run --rm --user "$(id -u):$(id -g)" "${mounts[@]}" untrunc "$@"
