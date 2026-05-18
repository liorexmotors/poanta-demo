#!/usr/bin/env bash
set -euo pipefail

ROOT="/root/.openclaw/workspace/projects/poanta-demo"
SECRET="/root/.openclaw/workspace/memory/.secrets/github.key"
WORKTREE="/tmp/poanta-gh-pages-auto"
ASKPASS=""

cleanup() {
  if [[ -n "${ASKPASS:-}" && -f "$ASKPASS" ]]; then rm -f "$ASKPASS"; fi
}
trap cleanup EXIT

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

git fetch origin main gh-pages
git checkout main
git pull --ff-only origin main

python3 scripts/update_feed.py
npm run build

if ! git diff --quiet feed.json .poanta-state.json .poanta-seen.json; then
  git config user.name "poanta-feed-bot"
  git config user.email "poanta-feed-bot@users.noreply.github.com"
  git add feed.json .poanta-state.json .poanta-seen.json
  git commit -m "Auto-update Poanta feed snapshot"
  git push origin main
fi

rm -rf "$WORKTREE"
git worktree add "$WORKTREE" origin/gh-pages
rsync -a --delete --exclude .git dist/ "$WORKTREE/"
cd "$WORKTREE"
if ! git diff --quiet; then
  git config user.name "poanta-feed-bot"
  git config user.email "poanta-feed-bot@users.noreply.github.com"
  git add -A
  git commit -m "Deploy auto-updated Poanta feed snapshot"
  git push origin HEAD:gh-pages
fi

cd "$ROOT"
git worktree remove "$WORKTREE" --force >/dev/null 2>&1 || true
