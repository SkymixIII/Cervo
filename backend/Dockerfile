# syntax=docker/dockerfile:1
#
# Image `app` — API FastAPI + moteur de récupération, avec untrunc ET ffmpeg
# EMBARQUÉS (pas de docker-in-docker : `scripts/untrunc-docker.sh` était
# transitoire, cf. backend/README.md et docs/impl/increment-01.md §3.5).
#
# Stage 1 reproduit la recette officielle anthwlock/untrunc (FF_VER=shared) :
# untrunc est lié dynamiquement contre le ffmpeg SYSTÈME d'Ubuntu 22.04
# (~4.4.x), qui respecte la contrainte "ffmpeg <= 8.0" du Spike 01 (au-delà de
# 8.1, la struct interne FFCodec change et casse untrunc). Le stage 2
# (runtime) reste sur la MÊME base Ubuntu 22.04 pour garantir l'ABI des libs
# partagées (libavformat/libavcodec/libavutil) entre le binaire untrunc et le
# ffmpeg/ffprobe utilisés par le reste du pipeline (probe + slice -c copy).

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
# Stage 2 : runtime — Ubuntu 22.04 + Python 3.12 (deadsnakes) + ffmpeg/ffprobe
#           + binaire untrunc embarqué.
# ---------------------------------------------------------------------------
FROM ubuntu:22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"

# Python 3.12 via deadsnakes (Ubuntu 22.04 embarque nativement Python 3.10) +
# ffmpeg/ffprobe (même paquet système que celui utilisé pour build untrunc
# ci-dessus -> ABI garantie identique).
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates gnupg \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv \
        ffmpeg \
    && python3.12 -m venv /opt/venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=untrunc-build /untrunc-src/untrunc /usr/local/bin/untrunc
RUN chmod +x /usr/local/bin/untrunc

WORKDIR /app/backend

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests

# APP_UNTRUNC_CMD pointe directement sur le binaire embarqué (plus de wrapper
# docker). Support Sony -rsv-ben natif (cf. methods/untrunc_moov.py).
ENV APP_UNTRUNC_CMD=untrunc \
    APP_FFMPEG=ffmpeg \
    APP_FFPROBE=ffprobe \
    APP_MEDIA_ROOT=/media \
    APP_WORK_ROOT=/data/work \
    APP_DB_PATH=/data/app.db \
    APP_WORKERS=2

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
