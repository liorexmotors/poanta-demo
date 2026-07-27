#!/usr/bin/env bash
set -euo pipefail

ROOT="/root/.openclaw/workspace/projects/poanta-demo"
cd "$ROOT"

if [[ -f .poenta-v5-image-disabled ]]; then
  mv .poenta-v5-image-disabled tmp/poenta-v5-image-disabled.previous
fi

echo "Poenta V5 image trial enabled for at most 100 newly inserted feed items."
