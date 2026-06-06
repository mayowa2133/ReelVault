FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG DENO_VERSION=2.3.6
ARG YT_DLP_PACKAGE_SPEC=""
ARG YT_DLP_PLUGIN_PACKAGE_SPECS=""

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl unzip \
    && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh -s v${DENO_VERSION} \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && if [ -n "$YT_DLP_PACKAGE_SPEC" ]; then pip install --upgrade $YT_DLP_PACKAGE_SPEC; fi \
    && if [ -n "$YT_DLP_PLUGIN_PACKAGE_SPECS" ]; then pip install $YT_DLP_PLUGIN_PACKAGE_SPECS; fi \
    && python -m yt_dlp --version

COPY app ./app
COPY scripts ./scripts

RUN useradd --create-home --shell /bin/bash reelvault \
    && mkdir -p /tmp/reelvault \
    && chown -R reelvault:reelvault /app /tmp/reelvault

USER reelvault

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
