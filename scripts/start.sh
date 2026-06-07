#!/bin/sh
set -eu

BGUTIL_PROVIDER_PORT="${BGUTIL_PROVIDER_PORT:-4416}"
BGUTIL_PROVIDER_URL="${YOUTUBE_POT_BGUTIL_BASE_URL:-http://127.0.0.1:${BGUTIL_PROVIDER_PORT}}"
BGUTIL_PROVIDER_HOME="${YOUTUBE_POT_BGUTIL_SCRIPT_SERVER_HOME:-}"

if [ -n "$BGUTIL_PROVIDER_HOME" ] && [ -d "$BGUTIL_PROVIDER_HOME/node_modules" ]; then
    (
        cd "$BGUTIL_PROVIDER_HOME/node_modules"
        exec deno run --allow-env --allow-net --allow-ffi=. --allow-read=. ../src/main.ts --port "$BGUTIL_PROVIDER_PORT"
    ) &

    ready_attempts=0
    until curl -fsS "$BGUTIL_PROVIDER_URL/ping" >/dev/null 2>&1; do
        ready_attempts=$((ready_attempts + 1))
        if [ "$ready_attempts" -ge 40 ]; then
            echo "bgutil PO-token provider did not become ready; continuing without HTTP provider" >&2
            break
        fi
        sleep 0.5
    done
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
