#!/bin/sh
set -eu

BGUTIL_PROVIDER_PORT="${BGUTIL_PROVIDER_PORT:-4416}"
BGUTIL_PROVIDER_URL="${YOUTUBE_POT_BGUTIL_BASE_URL:-http://127.0.0.1:${BGUTIL_PROVIDER_PORT}}"
BGUTIL_PROVIDER_HOME="${BGUTIL_PROVIDER_HOME:-${YOUTUBE_POT_BGUTIL_SCRIPT_SERVER_HOME:-}}"
BGUTIL_PROVIDER_REQUIRED="${BGUTIL_PROVIDER_REQUIRED:-}"

if [ -z "$BGUTIL_PROVIDER_REQUIRED" ]; then
    if [ -n "${YOUTUBE_POT_BGUTIL_BASE_URL:-}" ] || [ -n "$BGUTIL_PROVIDER_HOME" ]; then
        BGUTIL_PROVIDER_REQUIRED=true
    else
        BGUTIL_PROVIDER_REQUIRED=false
    fi
fi

if [ -n "$BGUTIL_PROVIDER_HOME" ] && [ -f "$BGUTIL_PROVIDER_HOME/src/main.ts" ]; then
    (
        cd "$BGUTIL_PROVIDER_HOME"
        exec deno run \
            --allow-env \
            --allow-net \
            --allow-ffi="$BGUTIL_PROVIDER_HOME/node_modules" \
            --allow-read="$BGUTIL_PROVIDER_HOME/node_modules" \
            src/main.ts \
            --port "$BGUTIL_PROVIDER_PORT"
    ) &

    ready_attempts=0
    until curl -fsS "$BGUTIL_PROVIDER_URL/ping" >/dev/null 2>&1; do
        ready_attempts=$((ready_attempts + 1))
        if [ "$ready_attempts" -ge 40 ]; then
            if [ "$BGUTIL_PROVIDER_REQUIRED" = "true" ]; then
                echo "bgutil PO-token provider did not become ready; startup cannot continue" >&2
                exit 1
            fi
            echo "bgutil PO-token provider did not become ready; continuing without HTTP provider" >&2
            break
        fi
        sleep 0.5
    done
else
    if [ "$BGUTIL_PROVIDER_REQUIRED" = "true" ]; then
        echo "bgutil PO-token provider files not found; startup cannot continue" >&2
        exit 1
    fi
    echo "bgutil PO-token provider files not found; continuing without HTTP provider" >&2
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
