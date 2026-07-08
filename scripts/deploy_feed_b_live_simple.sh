#!/usr/bin/env bash
set -euo pipefail

ROOT="/root/.openclaw/workspace/projects/poanta-demo"
GH_WORKTREE="/tmp/poanta-gh-pages-feed-b-live"
MAIN_WORKTREE="/tmp/poanta-main-feed-b-live"
ASKPASS=""

cleanup() {
  if [[ -n "${ASKPASS:-}" && -f "$ASKPASS" ]]; then rm -f "$ASKPASS"; fi
  git -C "$ROOT" worktree remove "$GH_WORKTREE" --force >/dev/null 2>&1 || true
  git -C "$ROOT" worktree remove "$MAIN_WORKTREE" --force >/dev/null 2>&1 || true
}
trap cleanup EXIT

cd "$ROOT"

python3 scripts/promote_feed_b_live.py --limit "${FEED_B_LIVE_LIMIT:-0}" --min-items "${FEED_B_LIVE_MIN_ITEMS:-20}"

mkdir -p dist
cp feed.json dist/feed.json
cp feed_b.json dist/feed_b.json
if [[ -d feed-b ]]; then
  rm -rf dist/feed-b
  cp -a feed-b dist/feed-b
fi

ASKPASS="$(mktemp)"
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

rm -rf "$MAIN_WORKTREE"
git worktree add "$MAIN_WORKTREE" origin/main
for p in feed.json feed_b.json .feed-b-state.json .feed-b-seen.json scripts/promote_feed_b_live.py scripts/promote_feed_b_live_simple.py scripts/deploy_feed_b_live_simple.sh; do
  if [[ -e "$ROOT/$p" ]]; then
    mkdir -p "$MAIN_WORKTREE/$(dirname "$p")"
    cp -a "$ROOT/$p" "$MAIN_WORKTREE/$p"
  fi
done
cd "$MAIN_WORKTREE"
if [[ -n "$(git status --porcelain)" ]]; then
  git config user.name "poanta-feed-bot"
  git config user.email "poanta-feed-bot@users.noreply.github.com"
  git add feed.json feed_b.json .feed-b-state.json .feed-b-seen.json scripts/promote_feed_b_live.py scripts/promote_feed_b_live_simple.py scripts/deploy_feed_b_live_simple.sh
  git commit -m "Deploy Feed B live snapshot"
  git pull --rebase origin main
  git push origin HEAD:main
fi

cd "$ROOT"
rm -rf "$GH_WORKTREE"
git worktree add --detach "$GH_WORKTREE" origin/gh-pages
for p in feed.json feed_b.json; do
  cp -a "$ROOT/$p" "$GH_WORKTREE/$p"
done
if [[ -d "$ROOT/feed-b" ]]; then
  rm -rf "$GH_WORKTREE/feed-b"
  cp -a "$ROOT/feed-b" "$GH_WORKTREE/feed-b"
fi
cd "$GH_WORKTREE"
if [[ -n "$(git status --porcelain)" ]]; then
  git config user.name "poanta-feed-bot"
  git config user.email "poanta-feed-bot@users.noreply.github.com"
  git add feed.json feed_b.json feed-b
  git commit -m "Deploy Feed B live snapshot"
  git pull --rebase origin gh-pages
  git push origin HEAD:gh-pages
fi

cd "$ROOT"
if [[ -z "${CLOUDFLARE_API_TOKEN:-}" && -f /root/.hermes/secrets/cloudflare/poenta_api_token.txt ]]; then
  export CLOUDFLARE_API_TOKEN="$(cat /root/.hermes/secrets/cloudflare/poenta_api_token.txt)"
fi
if [[ -n "${CLOUDFLARE_API_TOKEN:-}" ]]; then
  npx wrangler pages deploy dist --project-name poanta-demo --branch main
else
  echo "CLOUDFLARE_API_TOKEN not available; skipped Cloudflare direct deploy" >&2
fi
