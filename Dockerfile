ARG YOUTUBE_PO_TOKEN_PROVIDER_VERSION=1.3.1

FROM node:25-bookworm-slim AS bgutil-provider

ARG YOUTUBE_PO_TOKEN_PROVIDER_VERSION

WORKDIR /provider

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && curl -fsSL "https://github.com/Brainicism/bgutil-ytdlp-pot-provider/archive/refs/tags/${YOUTUBE_PO_TOKEN_PROVIDER_VERSION}.zip" -o /tmp/bgutil-ytdlp-pot-provider.zip \
    && unzip -q /tmp/bgutil-ytdlp-pot-provider.zip -d /tmp \
    && mv "/tmp/bgutil-ytdlp-pot-provider-${YOUTUBE_PO_TOKEN_PROVIDER_VERSION}/server" /provider/server \
    && cd /provider/server \
    && npm ci --omit=dev --no-audit --no-fund \
    && rm -rf /var/lib/apt/lists/* /tmp/bgutil-ytdlp-pot-provider.zip /tmp/bgutil-ytdlp-pot-provider-${YOUTUBE_PO_TOKEN_PROVIDER_VERSION}

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG DENO_VERSION=2.6.9
ARG YT_DLP_PACKAGE_SPEC="yt-dlp[default,curl-cffi] @ https://github.com/yt-dlp/yt-dlp/archive/acf8ab7.tar.gz"
ARG YOUTUBE_PO_TOKEN_PROVIDER_HOME=/opt/bgutil-ytdlp-pot-provider
ARG YT_DLP_PLUGIN_PACKAGE_SPECS="bgutil-ytdlp-pot-provider==1.3.1"
ARG YOUTUBE_PO_TOKEN_PROVIDER_VERSION

ENV REELVAULT_YT_DLP_PACKAGE_SPEC="${YT_DLP_PACKAGE_SPEC}" \
    REELVAULT_YT_DLP_PLUGIN_PACKAGE_SPECS="${YT_DLP_PLUGIN_PACKAGE_SPECS}" \
    REELVAULT_YOUTUBE_PO_TOKEN_PROVIDER_VERSION="${YOUTUBE_PO_TOKEN_PROVIDER_VERSION}" \
    DENO_DIR=/opt/deno-cache \
    DENO_NO_PROMPT=1 \
    DENO_NO_UPDATE_CHECK=1 \
    BGUTIL_PROVIDER_HOME="${YOUTUBE_PO_TOKEN_PROVIDER_HOME}/server" \
    YOUTUBE_FETCH_POT_POLICY=always \
    YOUTUBE_POT_BGUTIL_BASE_URL="http://127.0.0.1:4416"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl \
    && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh -s v${DENO_VERSION} \
    && rm -rf /var/lib/apt/lists/*

COPY --from=bgutil-provider /provider/server ${YOUTUBE_PO_TOKEN_PROVIDER_HOME}/server

RUN cd "${YOUTUBE_PO_TOKEN_PROVIDER_HOME}/server" \
    && deno cache --frozen src/main.ts

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && if [ -n "$YT_DLP_PACKAGE_SPEC" ]; then pip install --upgrade "$YT_DLP_PACKAGE_SPEC"; fi \
    && if [ -n "$YT_DLP_PLUGIN_PACKAGE_SPECS" ]; then pip install $YT_DLP_PLUGIN_PACKAGE_SPECS; fi \
    && python -m yt_dlp --version

COPY app ./app
COPY scripts ./scripts

RUN useradd --create-home --shell /bin/bash reelvault \
    && mkdir -p /tmp/reelvault \
    && chown -R reelvault:reelvault /app /tmp/reelvault /opt/bgutil-ytdlp-pot-provider /opt/deno-cache

USER reelvault

EXPOSE 8000

CMD ["sh", "/app/scripts/start.sh"]
