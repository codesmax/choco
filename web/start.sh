#!/usr/bin/env bash
export PYTHONUTF8=1

SCRIPTPATH=$(dirname $(realpath $0))
REPO_ROOT=$(realpath "$SCRIPTPATH/..")
source "$REPO_ROOT/.venv/bin/activate"
cd "$REPO_ROOT"

HOST="${CHOCO_WEB_HOST:-127.0.0.1}"
PORT="${CHOCO_WEB_PORT:-8000}"

echo "Starting chocoweb on http://${HOST}:${PORT}"
uvicorn chocoweb.server:app --host "$HOST" --port "$PORT" --reload
