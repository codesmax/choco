#!/usr/bin/env bash
export PYTHONUTF8=1

SCRIPTPATH=$(dirname $(realpath $0))
REPO_ROOT=$(realpath "$SCRIPTPATH/..")
source "$REPO_ROOT/.venv/bin/activate"
cd "$REPO_ROOT"

if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    source "$REPO_ROOT/.env"
    set +a
fi

HOST="${CHOCO_WEB_HOST:-127.0.0.1}"
PORT="${CHOCO_WEB_PORT:-8000}"

SSL_ARGS=()
if [[ -n "${CHOCO_WEB_SSL_CERT:-}" && -n "${CHOCO_WEB_SSL_KEY:-}" ]]; then
    SSL_ARGS+=(--ssl-certfile "$CHOCO_WEB_SSL_CERT" --ssl-keyfile "$CHOCO_WEB_SSL_KEY")
    echo "Starting chocoweb on https://${HOST}:${PORT}"
else
    echo "Starting chocoweb on http://${HOST}:${PORT}"
fi

uvicorn chocoweb.server:app --host "$HOST" --port "$PORT" --reload "${SSL_ARGS[@]}"
