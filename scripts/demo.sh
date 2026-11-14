#!/usr/bin/env bash
# Prende la API (modelo en memoria) y la página. Un solo proceso de la API.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "${DEMO_AWAKE:-}" ]] && command -v caffeinate >/dev/null 2>&1; then
  exec env DEMO_AWAKE=1 caffeinate -dims "$0" "$@"
fi

MODEL="${FRAGRANTICA_MODEL:-$ROOT/recommendation-system/artifacts/serving.joblib}"
DATA="${FRAGRANTICA_DATA:-$ROOT/scraper/data/final}"
API_PORT="${PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"

if [[ ! -f "$MODEL" ]]; then
  echo "Falta $MODEL" >&2
  echo "Corré: cd recommendation-system && uv run python main.py export-serving" >&2
  exit 1
fi

export FRAGRANTICA_MODEL="$MODEL"
export FRAGRANTICA_DATA="$DATA"
export PORT="$API_PORT"
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:${WEB_PORT},http://127.0.0.1:${WEB_PORT}}"

if lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "El puerto ${API_PORT} ya está en uso. La API no se va a duplicar." >&2
  exit 1
fi
if lsof -nP -iTCP:"$WEB_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "El puerto ${WEB_PORT} ya está en uso. La página no se va a duplicar." >&2
  exit 1
fi

cleanup() {
  local pid
  for pid in "${API_PID:-}" "${WEB_PID:-}"; do
    if [[ -n "$pid" ]]; then
      kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT
trap 'cleanup; exit 0' INT TERM

set -m
cd "$ROOT/serving"
uv run fragrantica-serve &
API_PID=$!

cd "$ROOT/web"
npm run dev -- --host 127.0.0.1 --port "$WEB_PORT" --strictPort &
WEB_PID=$!

echo "Cargando catálogo y modelo."
ready=0
for _ in $(seq 1 180); do
  if ! kill -0 "$API_PID" 2>/dev/null || ! kill -0 "$WEB_PID" 2>/dev/null; then
    echo "La API o la página se cerraron antes de quedar listas." >&2
    exit 1
  fi
  if curl -sf "http://127.0.0.1:${API_PORT}/health" | grep -q '"ready":true' \
    && curl -sf -o /dev/null "http://127.0.0.1:${WEB_PORT}/"; then
    ready=1
    break
  fi
  sleep 1
done

if [[ "$ready" -ne 1 ]]; then
  echo "La demo no respondió en 3 minutos." >&2
  exit 1
fi

echo "API: http://127.0.0.1:${API_PORT}"
echo "Web: http://127.0.0.1:${WEB_PORT}"
echo "Ctrl+C apaga las dos."

while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
  sleep 1
done
echo "La API o la página se cerraron." >&2
exit 1
