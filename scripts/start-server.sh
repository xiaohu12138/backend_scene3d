#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON="${SCENE3D_PYTHON:-$ROOT/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then echo "Set SCENE3D_PYTHON to this service's Python 3.11+ interpreter" >&2; exit 1; fi
cd "$ROOT"
mkdir -p .local
if [ -f .local/api.pid ] && kill -0 "$(cat .local/api.pid)" 2>/dev/null; then
  PID="$(cat .local/api.pid)"
  if tr '\0' ' ' < "/proc/$PID/cmdline" | grep -q 'backend_scene3d.api:create_app'; then
    echo "backend_scene3d already running: $PID"; exit 0
  fi
  echo "PID file belongs to a different process; no action taken" >&2; exit 1
fi
if "$PYTHON" -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',8013)); s.close(); raise SystemExit(0 if r==0 else 1)"; then
  echo "Port 8013 is already in use; no process stopped" >&2; exit 1
fi
nohup "$PYTHON" -m uvicorn backend_scene3d.api:create_app --factory --host 127.0.0.1 --port 8013 > .local/api.log 2>&1 < /dev/null &
echo "$!" > .local/api.pid
echo "backend_scene3d started: $(cat .local/api.pid) (127.0.0.1:8013)"
