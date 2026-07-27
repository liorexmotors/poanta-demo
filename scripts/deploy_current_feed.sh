#!/usr/bin/env bash
set -euo pipefail

ROOT="/root/.openclaw/workspace/projects/poanta-demo"
WORKTREE="/tmp/poanta-gh-pages-auto"
ASKPASS=""

cleanup() {
  if [[ -n "${ASKPASS:-}" && -f "$ASKPASS" ]]; then rm -f "$ASKPASS"; fi
  if [[ -d "$WORKTREE" ]]; then git -C "$ROOT" worktree remove "$WORKTREE" --force >/dev/null 2>&1 || true; fi
  git -C "$ROOT" worktree remove /tmp/poanta-main-auto --force >/dev/null 2>&1 || true
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
python3 scripts/apply_poenta_logo_to_live_images.py
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
python3 - <<'PY'
import json
from pathlib import Path

feed_path = Path("feed.json")
feed = json.loads(feed_path.read_text(encoding="utf-8"))
changed = 0
category_class = {
    "ביטחון": "security",
    "כלכלה": "money",
    "צרכנות": "money",
    "טכנולוגיה": "tech",
    "רכב": "real",
    "בריאות": "real",
    "תרבות": "real",
    "רכילות": "real",
    "ספורט": "real",
    "נדל״ן": "real",
    "מזג אוויר": "real",
}
for item in feed.get("items", []):
    if not isinstance(item, dict):
        continue
    expected_class = category_class.get(str(item.get("category") or ""), "")
    if item.get("categoryClass", "") != expected_class:
        item["categoryClass"] = expected_class
        changed += 1
    if "takeaway" in item:
        item.pop("takeaway", None)
        changed += 1
if changed:
    feed_path.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Normalized {changed} public feed metadata fields before deploy.")
PY
# P0 guard: the quality auditor catches cross-card/source-policy failures that
# the per-card quality gate may miss. Its CLI can print "fail" while exiting 0,
# so gate on the JSON status explicitly before recording or publishing.
python3 scripts/pointa_quality_auditor.py --feed feed.json --json > tmp/deploy_quality_auditor.json
python3 - <<'PY'
import json
report = json.load(open('tmp/deploy_quality_auditor.json', encoding='utf-8'))
status = report.get('status')
errors = report.get('errors') or []
warnings = report.get('warnings') or []
print(f"Pointa quality auditor: {status} · errors={len(errors)} · warnings={len(warnings)}")
PY
# An individual bad article must never stop publication of the valid feed.
# Quarantine every auditor error that maps to a concrete feed URL, then audit
# the remaining candidate again. Only an unresolved/system-level error blocks.
python3 scripts/pointa_quarantine_failed_items.py \
  --feed feed.json \
  --report tmp/deploy_quality_auditor.json \
  --quarantine pointa_quarantine.json
python3 scripts/pointa_quality_auditor.py --feed feed.json --json > tmp/deploy_quality_auditor_after_quarantine.json
python3 - <<'PY'
import json, sys
report = json.load(open('tmp/deploy_quality_auditor_after_quarantine.json', encoding='utf-8'))
errors = report.get('errors') or []
print(f"Pointa quality auditor after quarantine: {report.get('status')} · errors={len(errors)}")
if report.get('status') != 'ok' or errors:
    for issue in errors[:5]:
        print(f"SYSTEM BLOCKER {issue.get('code')}: {issue.get('headline') or issue.get('message')}", file=sys.stderr)
    sys.exit(1)
PY
python3 scripts/pointa_publication_events.py record --gatekeeper deploy-current --run-id "${POANTA_RUN_ID:-deploy-current}" || true
python3 scripts/pointa_quality_auditor.py --feed feed.json --json > tmp/deploy_quality_auditor_after_record.json
python3 - <<'PY'
import json
report = json.load(open('tmp/deploy_quality_auditor_after_record.json', encoding='utf-8'))
status = report.get('status')
errors = report.get('errors') or []
warnings = report.get('warnings') or []
print(f"Pointa quality auditor after event record: {status} · errors={len(errors)} · warnings={len(warnings)}")
PY
python3 scripts/pointa_quarantine_failed_items.py \
  --feed feed.json \
  --report tmp/deploy_quality_auditor_after_record.json \
  --quarantine pointa_quarantine.json
python3 scripts/pointa_quality_auditor.py --feed feed.json --json > tmp/deploy_quality_auditor_final.json
python3 - <<'PY'
import json, sys
report = json.load(open('tmp/deploy_quality_auditor_final.json', encoding='utf-8'))
errors = report.get('errors') or []
print(f"Pointa final quality auditor: {report.get('status')} · errors={len(errors)}")
if report.get('status') != 'ok' or errors:
    for issue in errors[:5]:
        print(f"SYSTEM BLOCKER {issue.get('code')}: {issue.get('headline') or issue.get('message')}", file=sys.stderr)
    sys.exit(1)
PY
# Timing warnings/errors are operational signals for follow-up rescue, not a
# candidate-content correctness gate for this deploy path.
python3 scripts/pointa_timing_auditor.py || true
npm run build
# Reconcile branding again after the build. A concurrent editor/pilot worker can
# append newly assigned images while the build is running; branding the final
# feed/dist snapshot here prevents those cards from reaching production without
# the Poenta mark.
python3 scripts/apply_poenta_logo_to_live_images.py
# The feed and the image bank can be updated by separate workers. Reconcile the
# built snapshot after the build so feed.json can never be deployed before a
# local image file it references. Missing assets fall back to a Poenta domain
# image; the article itself remains publishable.
python3 scripts/ensure_dist_feed_images.py --dist dist
# Guard again after build so dist/feed.json cannot diverge from the candidate
# that passed pre-build checks.
python3 scripts/pointa_publish_rollback_guard.py --candidate dist/feed.json --out tmp/deploy_dist_rollback_guard.json

# Sync the current feed snapshot back to origin/main using an isolated worktree.
# This avoids non-fast-forward failures caused by a dirty long-lived operator
# checkout and prevents Cloudflare's Git-connected pipeline from rebuilding an
# older feed over the direct deployment.
MAIN_WORKTREE="/tmp/poanta-main-auto"
git worktree remove "$MAIN_WORKTREE" --force >/dev/null 2>&1 || true
rm -rf "$MAIN_WORKTREE"
git worktree add "$MAIN_WORKTREE" origin/main
mkdir -p "$MAIN_WORKTREE/tmp"
for p in feed.json feed_a_side.json feed_a_breaking.json breaking_feed.json package.json scripts/apply_poenta_logo_to_live_images.py scripts/deploy_current_feed.sh scripts/fast_sync_and_deploy_feed.sh scripts/finalize_latest_editor_run.sh scripts/pointa_editor_pipeline.py scripts/pointa_main_feed_no_breaking_guard.py scripts/pointa_quarantine_failed_items.py scripts/poenta_image_bank.py scripts/poenta_v5_feed_images.py scripts/promote_feed_b_live.py scripts/audit_poenta_v5_image_trial.py tests/test_nonblocking_feed_quarantine.py .poanta-state.json .poanta-seen.json pointa_quality_report.md; do
  if [[ -e "$ROOT/$p" ]]; then cp -a "$ROOT/$p" "$MAIN_WORKTREE/$p"; fi
done
if [[ -d "$ROOT/feed-a" ]]; then
  rm -rf "$MAIN_WORKTREE/feed-a"
  cp -a "$ROOT/feed-a" "$MAIN_WORKTREE/feed-a"
fi
if [[ -d "$ROOT/assets/feed-defaults" ]]; then
  mkdir -p "$MAIN_WORKTREE/assets"
  rm -rf "$MAIN_WORKTREE/assets/feed-defaults"
  cp -a "$ROOT/assets/feed-defaults" "$MAIN_WORKTREE/assets/feed-defaults"
fi
if [[ -d "$ROOT/assets/poenta-image-bank-v5" ]]; then
  mkdir -p "$MAIN_WORKTREE/assets"
  rm -rf "$MAIN_WORKTREE/assets/poenta-image-bank-v5"
  cp -a "$ROOT/assets/poenta-image-bank-v5" "$MAIN_WORKTREE/assets/poenta-image-bank-v5"
fi
if [[ -d "$ROOT/assets/poenta-domain-defaults" ]]; then
  mkdir -p "$MAIN_WORKTREE/assets"
  rm -rf "$MAIN_WORKTREE/assets/poenta-domain-defaults"
  cp -a "$ROOT/assets/poenta-domain-defaults" "$MAIN_WORKTREE/assets/poenta-domain-defaults"
fi
cd "$MAIN_WORKTREE"
if [[ -n "$(git status --porcelain)" ]]; then
  git config user.name "poanta-feed-bot"
  git config user.email "poanta-feed-bot@users.noreply.github.com"
  git add feed.json feed_a_side.json feed_a_breaking.json breaking_feed.json package.json scripts/apply_poenta_logo_to_live_images.py scripts/deploy_current_feed.sh scripts/fast_sync_and_deploy_feed.sh scripts/finalize_latest_editor_run.sh scripts/pointa_editor_pipeline.py scripts/pointa_main_feed_no_breaking_guard.py scripts/pointa_quarantine_failed_items.py scripts/poenta_image_bank.py scripts/poenta_v5_feed_images.py scripts/promote_feed_b_live.py scripts/audit_poenta_v5_image_trial.py tests/test_nonblocking_feed_quarantine.py .poanta-state.json .poanta-seen.json pointa_quality_report.md
  git add feed-a || true
  git add assets/feed-defaults || true
  git add assets/poenta-image-bank-v5 || true
  git add assets/poenta-domain-defaults || true
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
