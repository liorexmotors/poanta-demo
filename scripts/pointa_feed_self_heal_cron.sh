#!/usr/bin/env bash
set -euo pipefail

ROOT="/root/.openclaw/workspace/projects/poanta-demo"
LOCK="/tmp/pointa-feed-self-heal-cron.lock"
LOG_DIR="$ROOT/tmp"
LOG_FILE="$LOG_DIR/pointa_feed_self_heal_cron.log"
STATUS_FILE="$LOG_DIR/pointa_feed_self_heal_cron_status.json"

mkdir -p "$LOG_DIR"

exec 9>"$LOCK"
if ! flock -n 9; then
  printf '{"ts":"%s","status":"skip","reason":"locked"}\n' "$(date --iso-8601=seconds)" > "$STATUS_FILE"
  exit 0
fi

cd "$ROOT"

START_TS="$(date --iso-8601=seconds)"
RUN_ID="self-heal-$(date +%Y%m%dT%H%M%S%z)"
TMP_LOG="$(mktemp)"
trap 'rm -f "$TMP_LOG"' EXIT

set +e
{
  echo "===== pointa_feed_self_heal_cron start $START_TS run=$RUN_ID ====="
  timeout 1200 /usr/bin/python3 scripts/pointa_silent_freshness_sentinel.py --repair
  rc=$?
  echo "===== pointa_feed_self_heal_cron end $(date --iso-8601=seconds) rc=$rc ====="
} >"$TMP_LOG" 2>&1
set -e
cat "$TMP_LOG" >> "$LOG_FILE"
tail -400 "$LOG_FILE" > "$LOG_FILE.tmp"
mv "$LOG_FILE.tmp" "$LOG_FILE"

/usr/bin/python3 - "$STATUS_FILE" "$START_TS" "$RUN_ID" "$rc" "$TMP_LOG" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_file = Path(sys.argv[1])
started_at = sys.argv[2]
run_id = sys.argv[3]
rc = int(sys.argv[4])
log_path = Path(sys.argv[5])
tail = log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
status_file.write_text(
    json.dumps(
        {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "startedAt": started_at,
            "runId": run_id,
            "status": "ok" if rc == 0 else "fail",
            "exit": rc,
            "tail": tail,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY

exit "$rc"
