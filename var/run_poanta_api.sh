#!/usr/bin/env bash
set -euo pipefail
cd /root/.openclaw/workspace/projects/poanta-demo
export POANTA_SQLITE_PATH=/root/.openclaw/workspace/projects/poanta-demo/var/poanta_feedback.sqlite3
exec /root/.openclaw/workspace/projects/poanta-demo/.venv-api/bin/uvicorn services.api.app.main:app --host 127.0.0.1 --port 8017
