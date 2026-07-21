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
if [[ -f breaking_feed.json ]]; then
  cp breaking_feed.json dist/breaking_feed.json
fi
if [[ -d assets/poenta-image-bank ]]; then
  mkdir -p dist/assets
  rm -rf dist/assets/poenta-image-bank
  cp -a assets/poenta-image-bank dist/assets/poenta-image-bank
fi
# The main feed changes on every promotion, so its static WhatsApp/OpenGraph
# pages must be regenerated in the same release artifact. Otherwise new share
# URLs fall through to the marketing homepage.
rm -rf dist/share
python3 scripts/generate_share_pages.py --feed feed.json --out dist
python3 - <<'PY'
import json
import importlib.util
from pathlib import Path

feed = json.loads(Path("feed.json").read_text(encoding="utf-8"))
manifest = json.loads(Path("dist/share/articles.json").read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("share_pages", "scripts/generate_share_pages.py")
share_pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(share_pages)
expected_ids = {share_pages.share_id(item) for item in feed.get("items", []) if isinstance(item, dict)}
share_rows = manifest.get("items") or []
missing = [row.get("shareId") for row in share_rows if not (Path("dist/share") / str(row.get("shareId")) / "index.html").is_file()]
manifest_ids = {str(row.get("shareId")) for row in share_rows}
if manifest_ids != expected_ids or missing:
    raise SystemExit(f"share-page gate failed: expected={len(expected_ids)} manifest={len(manifest_ids)} missing={missing[:5]}")
print(f"Share-page gate passed: {len(share_rows)} pages")
PY
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

if [[ "${FEED_B_SKIP_GIT:-0}" != "1" ]]; then
git fetch origin main gh-pages

rm -rf "$MAIN_WORKTREE"
git worktree add "$MAIN_WORKTREE" origin/main
for p in feed.json feed_b.json breaking_feed.json .feed-b-state.json .feed-b-seen.json scripts/poenta_image_bank.py scripts/promote_feed_b_live.py scripts/promote_feed_b_live_simple.py scripts/deploy_feed_b_live_simple.sh scripts/generate_share_pages.py scripts/update_breaking_feed.py tests/test_share_pages.py assets/poenta-image-bank; do
  if [[ -e "$ROOT/$p" ]]; then
    mkdir -p "$MAIN_WORKTREE/$(dirname "$p")"
    rm -rf "$MAIN_WORKTREE/$p"
    cp -a "$ROOT/$p" "$MAIN_WORKTREE/$p"
  fi
done
cd "$MAIN_WORKTREE"
if [[ -n "$(git status --porcelain)" ]]; then
  git config user.name "poanta-feed-bot"
  git config user.email "poanta-feed-bot@users.noreply.github.com"
  git add feed.json feed_b.json breaking_feed.json .feed-b-state.json .feed-b-seen.json scripts/poenta_image_bank.py scripts/promote_feed_b_live.py scripts/promote_feed_b_live_simple.py scripts/deploy_feed_b_live_simple.sh scripts/generate_share_pages.py scripts/update_breaking_feed.py tests/test_share_pages.py assets/poenta-image-bank
  git commit -m "Deploy Feed B live snapshot"
  git pull --rebase origin main
  git push origin HEAD:main
fi

cd "$ROOT"
rm -rf "$GH_WORKTREE"
git worktree add --detach "$GH_WORKTREE" origin/gh-pages
for p in feed.json feed_b.json breaking_feed.json assets/poenta-image-bank; do
  rm -rf "$GH_WORKTREE/$p"
  mkdir -p "$GH_WORKTREE/$(dirname "$p")"
  cp -a "$ROOT/$p" "$GH_WORKTREE/$p"
done
rm -rf "$GH_WORKTREE/share"
cp -a "$ROOT/dist/share" "$GH_WORKTREE/share"
if [[ -d "$ROOT/feed-b" ]]; then
  rm -rf "$GH_WORKTREE/feed-b"
  cp -a "$ROOT/feed-b" "$GH_WORKTREE/feed-b"
fi
cd "$GH_WORKTREE"
if [[ -n "$(git status --porcelain)" ]]; then
  git config user.name "poanta-feed-bot"
  git config user.email "poanta-feed-bot@users.noreply.github.com"
  git add feed.json feed_b.json breaking_feed.json feed-b share assets/poenta-image-bank
  git commit -m "Deploy Feed B live snapshot"
  git pull --rebase origin gh-pages
  git push origin HEAD:gh-pages
fi
else
  echo "FEED_B_SKIP_GIT=1; skipped Git main/gh-pages snapshot push" >&2
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
