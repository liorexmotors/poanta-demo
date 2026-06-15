#!/usr/bin/env bash
set -euo pipefail

ROOT="/root/.openclaw/workspace/projects/poanta-demo"
LOCK="/tmp/poanta-fast-sync.lock"
MAIN_WORKTREE="/tmp/poanta-main-fast-sync"
WORKTREE="/tmp/poanta-gh-pages-fast-sync"
ASKPASS=""

cleanup() {
  if [[ -n "${ASKPASS:-}" && -f "$ASKPASS" ]]; then rm -f "$ASKPASS"; fi
  if [[ -d "$MAIN_WORKTREE" ]]; then
    git -C "$ROOT" worktree remove "$MAIN_WORKTREE" --force >/dev/null 2>&1 || true
    rm -rf "$MAIN_WORKTREE" >/dev/null 2>&1 || true
  fi
  if [[ -d "$WORKTREE" ]]; then
    git -C "$ROOT" worktree remove "$WORKTREE" --force >/dev/null 2>&1 || true
    rm -rf "$WORKTREE" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "Poanta FAST sync already running; skipping."
  exit 0
fi

cd "$ROOT"

ASKPASS=$(mktemp)
cat > "$ASKPASS" <<'SH'
#!/bin/sh
case "$1" in
  *Username*) echo x-access-token ;;
  *Password*) cat /root/.openclaw/workspace/memory/.secrets/github.key ;;
  *) echo ;;
esac
SH
chmod 700 "$ASKPASS"
export GIT_ASKPASS="$ASKPASS"
export GIT_TERMINAL_PROMPT=0

if [[ -f feed.json ]]; then cp feed.json /tmp/poanta-fast-sync-before.json; fi
python3 scripts/update_feed.py --sync-profile fast
# Keep the separate breaking-news rail fresh as part of the same FAST cadence.
# It is not covered by update_feed.py, so without this it can silently go stale
# while the main feed keeps publishing.
python3 scripts/update_breaking_feed.py
python3 - <<'PY'
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
before = Path('/tmp/poanta-fast-sync-before.json')
feed_path = Path('feed.json')
if before.exists() and feed_path.exists():
    old = json.loads(before.read_text(encoding='utf-8'))
    new = json.loads(feed_path.read_text(encoding='utf-8'))
    existing = {it.get('sourceUrl') for it in new.get('items', [])}
    now = datetime.now(timezone(timedelta(hours=3)))
    keep = []
    for it in old.get('items', []):
        if it.get('sourceUrl') in existing:
            continue
        if it.get('editorStatus') not in {'rescue-manual-pass', 'rescue-editor-pass'}:
            continue
        try:
            published = datetime.fromisoformat(str(it.get('publishedAt')).replace('Z', '+00:00'))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone(timedelta(hours=3)))
            published = published.astimezone(timezone(timedelta(hours=3)))
        except Exception:
            continue
        if now - published <= timedelta(hours=6):
            keep.append(it)
    if keep:
        new['items'].extend(keep)
        new['items'].sort(key=lambda x: x.get('publishedAt') or '', reverse=True)
        rr = dict(new.get('rescueRetention') or {})
        rr.update({'preservedRecentRescueCards': len(keep), 'updatedAt': now.isoformat(timespec='seconds')})
        new['rescueRetention'] = rr
        feed_path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
PY
python3 scripts/pointa_quality_gate.py --report pointa_quality_report.md
# P0 guard: FAST is only successful if the candidate feed is visibly fresh.
# Never record a publication event or return OK for a stale/thin feed.
python3 scripts/pointa_publication_health_gate.py --mode candidate --feed feed.json --out tmp/fast_candidate_health_gate.json
python3 scripts/pointa_publication_events.py record --gatekeeper fast-sync --run-id "${POANTA_RUN_ID:-fast-sync}" || true
python3 scripts/pointa_quality_auditor.py || true
python3 scripts/pointa_timing_auditor.py || true
npm run build

git fetch origin main
rm -rf "$MAIN_WORKTREE"
git worktree add --detach "$MAIN_WORKTREE" origin/main
cp feed.json "$MAIN_WORKTREE/feed.json"
cp breaking_feed.json "$MAIN_WORKTREE/breaking_feed.json"
cp .poanta-state.json "$MAIN_WORKTREE/.poanta-state.json"
cp .poanta-seen.json "$MAIN_WORKTREE/.poanta-seen.json"
cp pointa_quality_report.md "$MAIN_WORKTREE/pointa_quality_report.md"
cd "$MAIN_WORKTREE"
if ! git diff --quiet -- feed.json breaking_feed.json .poanta-state.json .poanta-seen.json pointa_quality_report.md; then
  git config user.name "poanta-feed-bot"
  git config user.email "poanta-feed-bot@users.noreply.github.com"
  git add feed.json breaking_feed.json .poanta-state.json .poanta-seen.json pointa_quality_report.md
  git commit -m "Auto-refresh Poanta FAST feed"
  git push origin HEAD:main
fi
cd "$ROOT"

git fetch origin gh-pages
rm -rf "$WORKTREE"
git worktree add "$WORKTREE" origin/gh-pages
cp feed.json "$WORKTREE/feed.json"
cp breaking_feed.json "$WORKTREE/breaking_feed.json"
cd "$WORKTREE"
if ! git diff --quiet -- feed.json breaking_feed.json; then
  git config user.name "poanta-feed-bot"
  git config user.email "poanta-feed-bot@users.noreply.github.com"
  git add feed.json breaking_feed.json
  git commit -m "Deploy refreshed Poanta FAST feed"
  git push origin HEAD:gh-pages
fi

echo "Poanta FAST sync complete."
