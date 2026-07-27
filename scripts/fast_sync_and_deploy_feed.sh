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

export POINTA_ALLOW_LOCAL_FALLBACK="${POINTA_ALLOW_LOCAL_FALLBACK:-0}"

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
        for item in new.get('items', []):
            if isinstance(item, dict):
                item.pop('takeaway', None)
        feed_path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
PY
# Bridge RSS collection to publishable Pointa cards before deployment. Keep the
# editor bridge available for real freshness/quality rescue, but do not force a
# full editor run on every FAST cycle just because thin candidates exist.
BRIDGE_ARGS=()
if python3 - <<'PY'
import json
import sys
from pathlib import Path

report_path = Path("feed_a_fast_sync_report.json")
try:
    report = json.loads(report_path.read_text(encoding="utf-8"))
except Exception:
    sys.exit(1)

needs_editor = (
    int(report.get("editorRoutedCandidates") or 0)
    + int(report.get("qaRejectedCandidates") or 0)
    + int(report.get("shortAfterEnrich") or 0)
)
if needs_editor <= 0:
    sys.exit(1)
print(f"FAST editor bridge: {needs_editor} candidates need full-card creation before deploy.")
PY
then
  if [[ "${POINTA_FAST_FORCE_EDITOR_ON_ROUTED:-0}" == "1" ]]; then
    BRIDGE_ARGS=(--force)
  else
    echo "FAST editor bridge: routed candidates exist; rescue autopilot will run only if candidate health asks for it."
  fi
fi
BRIDGE_STATUS=0
RUN_RESCUE_BRIDGE=1
if [[ "${#BRIDGE_ARGS[@]}" -eq 0 ]]; then
  if python3 - <<'PY'
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

threshold = int(os.environ.get("POINTA_FAST_RESCUE_TOP_AGE_MIN", "45"))
feed_path = Path("feed.json")
try:
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    top = (feed.get("items") or [])[0]
    published = datetime.fromisoformat(str(top.get("publishedAt") or "").replace("Z", "+00:00"))
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone(timedelta(hours=3)))
    age_min = (datetime.now(timezone(timedelta(hours=3))) - published.astimezone(timezone(timedelta(hours=3)))).total_seconds() / 60
except Exception:
    sys.exit(1)
if age_min < threshold:
    print(f"FAST editor bridge: top item age {age_min:.1f}m is below rescue threshold {threshold}m; skipping full editor bridge.")
    sys.exit(0)
sys.exit(1)
PY
  then
    RUN_RESCUE_BRIDGE=0
  fi
fi
if [[ "$RUN_RESCUE_BRIDGE" -eq 1 ]]; then
  python3 scripts/pointa_feed_rescue_autopilot.py "${BRIDGE_ARGS[@]}" --limit "${POINTA_FAST_RESCUE_LIMIT:-9}" --batch-size "${POINTA_FAST_RESCUE_BATCH_SIZE:-3}" --oversample-factor "${POINTA_FAST_RESCUE_OVERSAMPLE:-4}" --min-pass "${POINTA_FAST_RESCUE_MIN_PASS:-1}" --require-freshness --json || BRIDGE_STATUS=$?
fi
export POINTA_FAST_BRIDGE_STATUS="$BRIDGE_STATUS"
if [[ "$BRIDGE_STATUS" -ne 0 ]]; then
  echo "FAST editor bridge failed with status $BRIDGE_STATUS; candidate health gate will decide whether publication is allowed." >&2
fi
python3 - <<'PY'
import json
from pathlib import Path

feed_path = Path("feed.json")
if feed_path.exists():
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
        print(f"Normalized {changed} public feed metadata fields after rescue bridge.")
PY
python3 scripts/pointa_quality_gate.py --report pointa_quality_report.md
# P0 guard: FAST is only successful if the candidate feed is safe and current.
# Thin fresh volume stays a warning so the feed does not get stuck.
python3 scripts/pointa_publication_health_gate.py --mode candidate --feed feed.json --out tmp/fast_candidate_health_gate.json
FAST_HEALTH_STATUS=0
python3 - <<'PY' || FAST_HEALTH_STATUS=$?
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=3))
report_path = Path("tmp/fast_candidate_health_gate.json")
sync_path = Path("feed_a_fast_sync_report.json")
bridge_path = Path("tmp/pointa_feed_rescue_autopilot_last.json")
incident_path = Path("tmp/fast_sync_root_cause_blocker.json")
incident_history_dir = Path("tmp/fast_sync_root_causes")

report = json.loads(report_path.read_text(encoding="utf-8"))
hard_stale_min = int(os.environ.get("POINTA_FAST_HARD_STALE_MIN", "45"))
try:
    sync = json.loads(sync_path.read_text(encoding="utf-8"))
except Exception:
    sync = {}
try:
    bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
except Exception:
    bridge = {}

hard_freshness_codes = {
    "no_new_top_item_sla",
    "stale_top_item",
}
errors = report.get("liveErrors") or []
blocked = []
top_age_min = None
try:
    top_published = (report.get("top") or [{}])[0].get("publishedAt")
    top_dt = datetime.fromisoformat(str(top_published or "").replace("Z", "+00:00"))
    if top_dt.tzinfo is None:
        top_dt = top_dt.replace(tzinfo=TZ)
    top_age_min = (datetime.now(TZ) - top_dt.astimezone(TZ)).total_seconds() / 60
except Exception:
    top_age_min = None
for err in errors:
    if err.get("code") not in hard_freshness_codes:
        continue
    if top_age_min is not None and top_age_min < hard_stale_min:
        print(f"FAST freshness warning below hard stale threshold: top age {top_age_min:.1f}m < {hard_stale_min}m")
        continue
    blocked.append(err)
if blocked:
    bridge_qa = bridge.get("qa") if isinstance(bridge.get("qa"), dict) else {}
    for err in blocked:
        print(f"FAST freshness blocker: {err.get('code')}: {err.get('message')}")
    fresh_candidates_exist = int(sync.get("validCandidates") or 0) > 0 or int(sync.get("editorRoutedCandidates") or 0) > 0
    editor_produced_safe_cards = int(bridge_qa.get("pass") or 0) > 0
    reason = (
        "fresh_candidates_exist_but_main_feed_candidate_still_stale"
        if fresh_candidates_exist
        else "fast_sync_candidate_still_stale_after_collection"
    )
    stamp = datetime.now(TZ).strftime("%Y%m%dT%H%M%S%z")
    incident = {
        "status": "blocked",
        "blockedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "reason": reason,
        "rule": "FAST may not publish or report success when liveStatus/freshness fails. If fresh candidates exist, self-heal must create a QA-clean fresh main feed before deploy; otherwise this RCA blocks publication.",
        "freshCandidatesExist": fresh_candidates_exist,
        "editorProducedSafeCards": editor_produced_safe_cards,
        "bridgeStatus": int(os.environ.get("POINTA_FAST_BRIDGE_STATUS") or 0),
        "syncReport": {
            "updatedAt": sync.get("updatedAt"),
            "rawCandidates": sync.get("rawCandidates"),
            "validCandidates": sync.get("validCandidates"),
            "selectedCandidates": sync.get("selectedCandidates"),
            "publishedItems": sync.get("publishedItems"),
            "editorRoutedCandidates": sync.get("editorRoutedCandidates"),
            "qaRejectedCandidates": sync.get("qaRejectedCandidates"),
            "shortAfterEnrich": sync.get("shortAfterEnrich"),
            "articleEnrichAttempts": sync.get("articleEnrichAttempts"),
            "articleEnrichSkippedBudget": sync.get("articleEnrichSkippedBudget"),
        },
        "editorBridge": {
            "status": bridge.get("status"),
            "reason": bridge.get("reason"),
            "runId": bridge.get("runId"),
            "runDir": bridge.get("runDir"),
            "editor": bridge.get("editor"),
            "qa": bridge.get("qa"),
            "recentTop12Before": bridge.get("recentTop12Before"),
            "recentTop12After": bridge.get("recentTop12After"),
        },
        "freshnessBlockers": blocked,
        "healthReport": str(report_path),
    }
    incident_history_dir.mkdir(parents=True, exist_ok=True)
    history_path = incident_history_dir / f"fast_sync_root_cause_blocker_{stamp}.json"
    incident_path.write_text(json.dumps(incident, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    history_path.write_text(json.dumps(incident, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"FAST sync blocked; root-cause report written to {incident_path} and {history_path}")
    sys.exit(42)
PY
if [[ "$FAST_HEALTH_STATUS" -eq 42 ]]; then
  echo "Poanta FAST sync skipped publication: freshness SLA not met; will retry next run."
  exit 0
elif [[ "$FAST_HEALTH_STATUS" -ne 0 ]]; then
  exit "$FAST_HEALTH_STATUS"
fi
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
mkdir -p "$MAIN_WORKTREE/assets"
rm -rf "$MAIN_WORKTREE/assets/poenta-image-bank-v5"
cp -a assets/poenta-image-bank-v5 "$MAIN_WORKTREE/assets/poenta-image-bank-v5"
cd "$MAIN_WORKTREE"
if [[ -n "$(git status --porcelain -- feed.json breaking_feed.json .poanta-state.json .poanta-seen.json pointa_quality_report.md assets/poenta-image-bank-v5)" ]]; then
  git config user.name "poanta-feed-bot"
  git config user.email "poanta-feed-bot@users.noreply.github.com"
  git add feed.json breaking_feed.json .poanta-state.json .poanta-seen.json pointa_quality_report.md assets/poenta-image-bank-v5
  git commit -m "Auto-refresh Poanta FAST feed"
  git push origin HEAD:main
fi
cd "$ROOT"

git fetch origin gh-pages
rm -rf "$WORKTREE"
git worktree add "$WORKTREE" origin/gh-pages
cp feed.json "$WORKTREE/feed.json"
cp breaking_feed.json "$WORKTREE/breaking_feed.json"
mkdir -p "$WORKTREE/assets"
rm -rf "$WORKTREE/assets/poenta-image-bank-v5"
cp -a assets/poenta-image-bank-v5 "$WORKTREE/assets/poenta-image-bank-v5"
cd "$WORKTREE"
if [[ -n "$(git status --porcelain -- feed.json breaking_feed.json assets/poenta-image-bank-v5)" ]]; then
  git config user.name "poanta-feed-bot"
  git config user.email "poanta-feed-bot@users.noreply.github.com"
  git add feed.json breaking_feed.json assets/poenta-image-bank-v5
  git commit -m "Deploy refreshed Poanta FAST feed"
  git push origin HEAD:gh-pages
fi

cd "$ROOT"
# Publish the same verified dist artifact directly to Cloudflare when credentials
# are available. GitHub main/gh-pages remain the durable source snapshots, but
# direct deploy prevents the public feed from staying stale while the
# Git-connected Cloudflare build catches up.
if [[ -z "${CLOUDFLARE_API_TOKEN:-}" && -f /root/.hermes/secrets/cloudflare/poenta_api_token.txt ]]; then
  export CLOUDFLARE_API_TOKEN="$(cat /root/.hermes/secrets/cloudflare/poenta_api_token.txt)"
fi
if [[ -n "${CLOUDFLARE_API_TOKEN:-}" ]]; then
  npx wrangler pages deploy dist --project-name poanta-demo --branch main
else
  echo "CLOUDFLARE_API_TOKEN not available; skipped Cloudflare direct deploy after Git sync" >&2
fi

echo "Poanta FAST sync complete."
