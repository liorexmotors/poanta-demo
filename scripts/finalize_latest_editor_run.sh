#!/usr/bin/env bash
set -euo pipefail

ROOT="/root/.openclaw/workspace/projects/poanta-demo"
RUNS_DIR="$ROOT/tmp/editor-runs"
cd "$ROOT"

latest=""
while IFS= read -r -d '' candidate; do
  [[ -f "$candidate/run.json" ]] || continue
  [[ -f "$candidate/.applied" ]] && continue
  latest="$candidate"
  break
done < <(find "$RUNS_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\0' 2>/dev/null | sort -zr -n | cut -z -d' ' -f2-)

if [[ -z "$latest" ]]; then
  echo "No un-applied editor run found."
  exit 0
fi

expected=$(python3 - "$latest" <<'PY'
import json, sys
from pathlib import Path
run=Path(sys.argv[1])
meta=json.loads((run/'run.json').read_text())
print(len(meta.get('batches', [])))
PY
)
actual=$(find "$latest" -maxdepth 1 -name 'batch_*_results.json' | wc -l | tr -d ' ')
if [[ "$actual" != "$expected" ]]; then
  echo "Editor run not ready: $actual/$expected result files in $latest"
  exit 2
fi

python3 scripts/pointa_editor_pipeline.py qa --run-dir "$latest"
python3 scripts/pointa_editor_pipeline.py apply --run-dir "$latest"
./scripts/deploy_current_feed.sh

touch "$latest/.applied"
echo "Applied editor run: $latest"
