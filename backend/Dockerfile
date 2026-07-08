# syntax=docker/dockerfile:1
#
# Image `app` — API FastAPI + moteur de récupération, avec untrunc, ffmpeg ET
# MP4Box (GPAC) EMBARQUÉS (pas de docker-in-docker : `scripts/untrunc-docker.sh`
# était transitoire, cf. backend/README.md et docs/impl/increment-01.md §3.5).
#
# Stage 1 reproduit la recette officielle anthwlock/untrunc (FF_VER=shared) :
# untrunc est lié dynamiquement contre le ffmpeg SYSTÈME d'Ubuntu 22.04
# (~4.4.x), qui respecte la contrainte "ffmpeg <= 8.0" du Spike 01 (au-delà de
# 8.1, la struct interne FFCodec change et casse untrunc). Le stage 2
# (runtime) reste sur la MÊME base Ubuntu 22.04 pour garantir l'ABI des libs
# partagées (libavformat/libavcodec/libavutil) entre le binaire untrunc et le
# ffmpeg/ffprobe utilisés par le reste du pipeline (probe + slice -c copy).
#
# `gpac` (paquet APT, fournit `MP4Box`) est ajouté au stage runtime pour le
# réordonnancement Long-GOP de `sony-rsv-rebuild` (incrément 5) : MP4Box ne
# touche pas au binaire H.264 (pas de réencodage), donc aucune contrainte
# d'ABI/version particulière ne le lie à untrunc/ffmpeg — le paquet Ubuntu
# 22.04 (GPAC ~2.0) suffit.
#
# ⚠️ DEUX ffmpeg distincts dans l'image, VOLONTAIREMENT :
# 1. `ffmpeg` APT (Ubuntu 22.04, 4.4.2) — fournit les .so runtime
#    (libavformat58/libavcodec58/libavutil56) dont le binaire `untrunc`
#    dépend DYNAMIQUEMENT (lié au build contre ces mêmes libs, stage 1).
#    Ne PAS toucher/remplacer ce paquet : c'est le seul rôle qui lui reste.
# 2. `ffmpeg`/`ffprobe` RÉCENTS (build statique BtbN, n7.1, stage
#    `ffmpeg-recent` ci-dessous) — utilisés par `APP_FFMPEG`/`APP_FFPROBE`
#    pour TOUT le pipeline (probe, slice, mux `sony-rsv-rebuild`). Requis
#    car ffmpeg 4.4.2 ne sait PAS écrire de piste PCM (`pcm_s24be`) dans un
#    conteneur MP4 (tag `ipcm`/`fpcm`, ISOBMFF Amendment 2 — supporté par
#    ffmpeg seulement depuis ~7.1) : `sony-rsv-rebuild` (mode long-gop
#    ET all-intra, audio) échoue avec ffmpeg 4.4.2 en sortie MP4
#    (« Could not find tag for codec pcm_s24be in stream » /
#    « incorrect codec parameters »), constaté en conteneur (cf.
#    `docs/impl/increment-07-docker-repackaging.md`).
#    Binaire STATIQUE (pas de .so partagée) → AUCUN couplage ABI avec
#    untrunc, donc aucun conflit avec la contrainte "ffmpeg <= 8.0" ci-dessus
#    (qui ne s'applique qu'au ffmpeg APT utilisé pour LIER untrunc).

# ---------------------------------------------------------------------------
# Stage 1 : build untrunc depuis les sources (anthwlock/untrunc)
# ---------------------------------------------------------------------------
FROM ubuntu:22.04 AS untrunc-build

RUN apt-get update && apt-get install -y --no-install-recommends \
        libavformat-dev libavcodec-dev libavutil-dev g++ make git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG UNTRUNC_REF=master
RUN git clone --depth 1 --branch "${UNTRUNC_REF}" \
        https://github.com/anthwlock/untrunc /untrunc-src
WORKDIR /untrunc-src
RUN make FF_VER=shared && strip untrunc

# ---------------------------------------------------------------------------
# Stage ffmpeg-recent : ffmpeg/ffprobe STATIQUES récents (BtbN/FFmpeg-Builds,
# n7.1, GPL) — pour le pipeline applicatif (PAS pour untrunc, cf. note §0).
# ---------------------------------------------------------------------------
FROM ubuntu:22.04 AS ffmpeg-recent

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl xz-utils \
    && rm -rf /var/lib/apt/lists/*

ARG TARGETARCH
RUN case "${TARGETARCH}" in \
        amd64) FF_ARCH=linux64 ;; \
        arm64) FF_ARCH=linuxarm64 ;; \
        *) echo "Architecture non supportée pour le ffmpeg statique: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL -o /tmp/ffmpeg.tar.xz \
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n7.1-latest-${FF_ARCH}-gpl-7.1.tar.xz" \
    && mkdir -p /opt/ffmpeg-recent \
    && tar -xJf /tmp/ffmpeg.tar.xz -C /opt/ffmpeg-recent --strip-components=1 \
    && rm /tmp/ffmpeg.tar.xz

# ---------------------------------------------------------------------------
# Stage 2 : runtime — Ubuntu 22.04 + Python 3.12 (deadsnakes) + ffmpeg APT
#           (libs pour untrunc) + ffmpeg/ffprobe récents (pipeline) + MP4Box
#           (gpac) + binaire untrunc embarqué.
# ---------------------------------------------------------------------------
FROM ubuntu:22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"

# Python 3.12 via deadsnakes (Ubuntu 22.04 embarque nativement Python 3.10) +
# ffmpeg (paquet système — fournit UNIQUEMENT les .so dont untrunc dépend,
# cf. note §0 ; son ffmpeg/ffprobe CLI ne sont plus utilisés par l'app) +
# gpac (MP4Box, mode long-gop).
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates gnupg \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv \
        ffmpeg \
        gpac \
    && python3.12 -m venv /opt/venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=untrunc-build /untrunc-src/untrunc /usr/local/bin/untrunc
RUN chmod +x /usr/local/bin/untrunc

# ffmpeg/ffprobe récents (statiques) utilisés par toute l'app (APP_FFMPEG/
# APP_FFPROBE ci-dessous) : chemin dédié /usr/local/lib/ffmpeg-recent, jamais
# nommés `ffmpeg`/`ffprobe` seuls sur le PATH, pour ne jamais pouvoir être
# confondus avec le ffmpeg APT (dont seules les .so servent, cf. note §0).
COPY --from=ffmpeg-recent /opt/ffmpeg-recent/bin/ffmpeg /usr/local/lib/ffmpeg-recent/ffmpeg
COPY --from=ffmpeg-recent /opt/ffmpeg-recent/bin/ffprobe /usr/local/lib/ffmpeg-recent/ffprobe
RUN chmod +x /usr/local/lib/ffmpeg-recent/ffmpeg /usr/local/lib/ffmpeg-recent/ffprobe

WORKDIR /app/backend

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests

# APP_UNTRUNC_CMD pointe directement sur le binaire embarqué (plus de wrapper
# docker). Support Sony -rsv-ben natif (cf. methods/untrunc_moov.py).
# APP_FFMPEG/APP_FFPROBE pointent sur le build récent (n7.1) — requis pour
# l'audio PCM (`ipcm`) de `sony-rsv-rebuild`, cf. note §0. MP4Box (gpac) est
# sur le PATH via le paquet apt -> APP_MP4BOX=MP4Box suffit.
ENV APP_UNTRUNC_CMD=untrunc \
    APP_FFMPEG=/usr/local/lib/ffmpeg-recent/ffmpeg \
    APP_FFPROBE=/usr/local/lib/ffmpeg-recent/ffprobe \
    APP_MP4BOX=MP4Box \
    APP_MEDIA_ROOT=/media \
    APP_WORK_ROOT=/data/work \
    APP_DB_PATH=/data/app.db \
    APP_WORKERS=2

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
