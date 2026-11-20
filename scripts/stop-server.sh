#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [ ! -f "$ROOT/.local/api.pid" ]; then echo "No managed Scene3D process"; exit 0; fi
PID="$(cat "$ROOT/.local/api.pid")"
if ! kill -0 "$PID" 2>/dev/null; then echo "Scene3D already stopped"; exit 0; fi
if ! tr '\0' ' ' < "/proc/$PID/cmdline" | grep -q 'backend_scene3d.api:create_app'; then
  echo "PID belongs to a different process; no action taken" >&2; exit 1
fi
kill -TERM "$PID"
echo "Graceful shutdown requested; active calculations finish before exit."
