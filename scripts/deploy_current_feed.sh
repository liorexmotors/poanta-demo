#!/usr/bin/env bash
set -euo pipefail

ROOT="/root/.openclaw/workspace/projects/poanta-demo"
WORKTREE="/tmp/poanta-gh-pages-auto"
ASKPASS=""

cleanup() {
  if [[ -n "${ASKPASS:-}" && -f "$ASKPASS" ]]; then rm -f "$ASKPASS"; fi
  if [[ -d "$WORKTREE" ]]; then git -C "$ROOT" worktree remove "$WORKTREE" --force >/dev/null 2>&1 || true; fi
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
python3 scripts/pointa_quality_gate.py --report pointa_quality_report.md
# P0 guard: do not publish or report success if the candidate feed still looks
# stale/thin to a user. This is deliberately before recording publication
# events so a failed candidate cannot fake timing freshness.
python3 scripts/pointa_publication_health_gate.py --mode candidate --feed feed.json --out tmp/deploy_candidate_health_gate.json
# P0 rollback guard: a stale local/main artifact must never overwrite a fresher
# Cloudflare/GitHub/public feed. The state file preserves the freshest known
# successful deploy so a future production alias rollback is detected even if the
# current custom domain has already fallen back.
python3 scripts/pointa_publish_rollback_guard.py --candidate feed.json --out tmp/deploy_rollback_guard.json
# P0 guard: the quality auditor catches cross-card/source-policy failures that
# the per-card quality gate may miss. Its CLI can print "fail" while exiting 0,
# so gate on the JSON status explicitly before recording or publishing.
python3 scripts/pointa_quality_auditor.py --json > tmp/deploy_quality_auditor.json
python3 - <<'PY'
import json, sys
report = json.load(open('tmp/deploy_quality_auditor.json', encoding='utf-8'))
status = report.get('status')
errors = report.get('errors') or []
warnings = report.get('warnings') or []
print(f"Pointa quality auditor: {status} · errors={len(errors)} · warnings={len(warnings)}")
if status != 'ok' or errors:
    for issue in errors[:5]:
        print(f"BLOCKER {issue.get('code')}: {issue.get('headline') or issue.get('message')}", file=sys.stderr)
    sys.exit(1)
PY
python3 scripts/pointa_publication_events.py record --gatekeeper deploy-current --run-id "${POANTA_RUN_ID:-deploy-current}" || true
# Timing warnings/errors are operational signals for follow-up rescue, not a
# candidate-content correctness gate for this deploy path.
python3 scripts/pointa_timing_auditor.py || true
npm run build
# Guard again after build so dist/feed.json cannot diverge from the candidate
# that passed pre-build checks.
python3 scripts/pointa_publish_rollback_guard.py --candidate dist/feed.json --out tmp/deploy_dist_rollback_guard.json

# Sync the current feed snapshot back to origin/main using an isolated worktree.
# This avoids non-fast-forward failures caused by a dirty long-lived operator
# checkout and prevents Cloudflare's Git-connected pipeline from rebuilding an
# older feed over the direct deployment.
MAIN_WORKTREE="/tmp/poanta-main-auto"
rm -rf "$MAIN_WORKTREE"
git worktree add "$MAIN_WORKTREE" origin/main
mkdir -p "$MAIN_WORKTREE/tmp"
for p in feed.json .poanta-state.json .poanta-seen.json pointa_quality_report.md; do
  if [[ -e "$ROOT/$p" ]]; then cp -a "$ROOT/$p" "$MAIN_WORKTREE/$p"; fi
done
cd "$MAIN_WORKTREE"
if [[ -n "$(git status --porcelain)" ]]; then
  git config user.name "poanta-feed-bot"
  git config user.email "poanta-feed-bot@users.noreply.github.com"
  git add feed.json .poanta-state.json .poanta-seen.json pointa_quality_report.md
  git commit -m "Auto-update Poanta feed snapshot"
  git pull --rebase origin main
  git push origin HEAD:main
fi
cd "$ROOT"
git worktree remove "$MAIN_WORKTREE" --force >/dev/null 2>&1 || true

rm -rf "$WORKTREE"
git worktree add --detach "$WORKTREE" origin/gh-pages
rsync -a --delete --exclude .git dist/ "$WORKTREE/"
cd "$WORKTREE"
if [[ -n "$(git status --porcelain)" ]]; then
  git config user.name "poanta-feed-bot"
  git config user.email "poanta-feed-bot@users.noreply.github.com"
  git add -A
  git commit -m "Deploy auto-updated Poanta feed snapshot"
  git pull --rebase origin gh-pages
  git push origin HEAD:gh-pages
fi

cd "$ROOT"
# If Cloudflare credentials are available, publish the verified artifact directly
# as production too. This makes production fresh immediately while main/gh-pages
# are already synced to prevent the next Git-connected build from rolling back.
if [[ -z "${CLOUDFLARE_API_TOKEN:-}" && -f /root/.hermes/secrets/cloudflare/poenta_api_token.txt ]]; then
  export CLOUDFLARE_API_TOKEN="$(cat /root/.hermes/secrets/cloudflare/poenta_api_token.txt)"
fi
if [[ -n "${CLOUDFLARE_API_TOKEN:-}" ]]; then
  npx wrangler pages deploy dist --project-name poanta-demo --branch main
else
  echo "CLOUDFLARE_API_TOKEN not available; skipped Cloudflare direct deploy after Git sync" >&2
fi
python3 scripts/pointa_publish_rollback_guard.py --candidate dist/feed.json --write-state --out tmp/deploy_final_rollback_guard.json
