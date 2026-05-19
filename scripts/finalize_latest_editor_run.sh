#!/usr/bin/env bash
set -euo pipefail

ROOT="/root/.openclaw/workspace/projects/poanta-demo"
RUNS_DIR="$ROOT/tmp/editor-runs"
cd "$ROOT"

ready=""
pending_count=0
while IFS= read -r -d '' candidate; do
  [[ -f "$candidate/run.json" ]] || continue
  [[ -f "$candidate/.applied" ]] && continue
  expected=$(python3 - "$candidate" <<'PY'
import json, sys
from pathlib import Path
run=Path(sys.argv[1])
meta=json.loads((run/'run.json').read_text())
print(len(meta.get('batches', [])))
PY
)
  actual=$(find "$candidate" -maxdepth 1 -name 'batch_*_results.json' | wc -l | tr -d ' ')
  if [[ "$actual" == "$expected" ]]; then
    ready="$candidate"
    break
  fi
  pending_count=$((pending_count + 1))
  echo "Editor run not ready: $actual/$expected result files in $candidate"
done < <(find "$RUNS_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\0' 2>/dev/null | sort -zr -n | cut -z -d' ' -f2-)

if [[ -z "$ready" ]]; then
  if [[ "$pending_count" -gt 0 ]]; then
    echo "No complete un-applied editor run found yet; $pending_count run(s) still pending."
    exit 2
  fi
  echo "No un-applied editor run found."
  exit 0
fi

python3 scripts/pointa_editor_pipeline.py qa --run-dir "$ready" --auto-reject-failed
python3 scripts/pointa_editor_pipeline.py apply --run-dir "$ready"
./scripts/deploy_current_feed.sh

touch "$ready/.applied"
echo "Applied editor run: $ready"
