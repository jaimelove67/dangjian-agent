#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
PYTHON_BIN="${PARTY_PYTHON:-python}"
if [[ -z "${PARTY_PYTHON:-}" && -x .venv/bin/python ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
fi
[[ -d frontend/node_modules ]] || { echo "Run npm ci in frontend first."; exit 1; }
backend_pid=""
frontend_pid=""
cleanup() {
  [[ -z "$frontend_pid" ]] || kill "$frontend_pid" 2>/dev/null || true
  [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 &
backend_pid=$!
ready=false
for ((attempt=0; attempt<20; attempt++)); do
  if curl -fsS http://127.0.0.1:8000/api/v1/health/live >/dev/null; then ready=true; break; fi
  sleep 1
done
[[ "$ready" == true ]] || { echo "Backend failed to start."; exit 1; }
(cd frontend && exec npm run dev -- --host 127.0.0.1 --port 5666 --strictPort) &
frontend_pid=$!
echo "Frontend: http://127.0.0.1:5666"
echo "Readiness: http://127.0.0.1:8000/api/v1/health/ready"
wait -n "$backend_pid" "$frontend_pid"
