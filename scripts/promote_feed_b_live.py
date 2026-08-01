#!/usr/bin/env python3
"""Incrementally promote QA-clean items into the live feed.json.

Every approved source item that is still inside the retention window and is
missing from the live feed is eligible for validation. Bad items are discarded
individually; the already-live, known-good feed is retained.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    from poenta_image_bank import apply_image_bank_to_item
except Exception:  # pragma: no cover - live promotion must stay usable without the optional bank
    apply_image_bank_to_item = None
try:
    from poenta_v5_feed_images import apply_to_new_item as apply_v5_image_to_new_item
    from poenta_v5_feed_images import build_catalog as build_v5_image_catalog
except Exception:  # pragma: no cover - image enrichment must never block publishing
    apply_v5_image_to_new_item = None
    build_v5_image_catalog = None


ROOT = Path(__file__).resolve().parents[1]
FEED_B = ROOT / "feed_b.json"
LIVE_FEED = ROOT / "feed.json"
TMP_CANDIDATE = ROOT / "tmp" / "feed-b-live-auto-candidate.json"
QUALITY_REPORT = ROOT / "tmp" / "feed-b-live-auto-quality.md"
PROMOTION_QUARANTINE = ROOT / "pointa_promotion_quarantine.json"
# Kept only so old operational tooling can detect and archive the former pilot
# marker. V5 is now the permanent production mechanism and must not be disabled
# by the retired pilot audit.
V5_DISABLE_MARKER = ROOT / ".poenta-v5-image-disabled"
V5_TRIAL_ID = "pilot-20260727-v2"
V5_TRIAL_LIMIT = 100


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def item_url(item: dict[str, Any]) -> str:
    return str(item.get("url") or item.get("sourceUrl") or item.get("link") or "").strip()


def item_title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("headline") or "").strip()


def item_summary(item: dict[str, Any]) -> str:
    return str(item.get("summary") or item.get("subtitle") or item.get("context") or "").strip()


def item_fingerprint(item: dict[str, Any]) -> str:
    payload = {
        key: item.get(key)
        for key in ("sourceUrl", "url", "publishedAt", "updatedAt", "headline", "title", "summary", "context", "takeaway", "category")
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def active_quarantine_entries(path: Path | None = None) -> dict[str, dict[str, Any]]:
    path = path or PROMOTION_QUARANTINE
    payload = load_json(path, {})
    rows = payload.get("items", []) if isinstance(payload, dict) else []
    return {
        str(row.get("url") or ""): row
        for row in rows
        if isinstance(row, dict) and str(row.get("url") or "")
    }


def quarantine_matches(item: dict[str, Any], entries: dict[str, dict[str, Any]]) -> bool:
    row = entries.get(item_url(item))
    return bool(row and row.get("fingerprint") == item_fingerprint(item))


def persist_promotion_quarantine(
    rejected: list[dict[str, Any]],
    reason: str,
    path: Path | None = None,
) -> int:
    path = path or PROMOTION_QUARANTINE
    if not rejected:
        return 0
    entries = active_quarantine_entries(path)
    now = datetime.now(timezone.utc).isoformat()
    for item in rejected:
        url = item_url(item)
        if not url:
            continue
        entries[url] = {
            "url": url,
            "fingerprint": item_fingerprint(item),
            "status": "rejected_by_public_qa",
            "reason": reason,
            "rejectedAt": now,
            "headline": item_title(item),
            "source": item.get("source") or "",
        }
    write_json(path, {
        "schemaVersion": 1,
        "updatedAt": now,
        "policy": "Skip unchanged public-QA rejects; retry automatically after editorial content changes.",
        "items": sorted(entries.values(), key=lambda row: str(row.get("rejectedAt") or "")),
    })
    return len(rejected)


def candidate_payload(
    source: dict[str, Any],
    items: list[dict[str, Any]],
    limit: int,
    live: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone(timedelta(hours=3))).isoformat(timespec="seconds")
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    live_items = [item for item in (live or {}).get("items", []) if isinstance(item, dict)]
    live_by_url = {item_url(item): item for item in live_items if item_url(item)}
    # V5 is the permanent image mechanism. Trial tracking only labels the
    # remaining sample cards; reaching the sample limit must not disable V5.
    v5_enabled = (
        os.environ.get("POENTA_V5_IMAGE_BANK_ENABLED", "1") != "0"
        and apply_v5_image_to_new_item is not None
        and build_v5_image_catalog is not None
    )
    trial_tracking_enabled = os.environ.get("POENTA_V5_IMAGE_TRIAL_ENABLED", "1") == "1"
    trial_applied = sum(1 for item in live_items if item.get("poentaImageTrialId") == V5_TRIAL_ID)
    try:
        v5_catalog = build_v5_image_catalog() if v5_enabled else []
    except Exception:
        v5_catalog = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item_url(item)
        title = item_title(item)
        summary = item_summary(item)
        if not url or url in seen or len(title) < 12 or len(summary) < 30:
            continue
        fixed = dict(item)
        fixed["url"] = url
        if "title" not in fixed and title:
            fixed["title"] = title
        if "summary" not in fixed and summary:
            fixed["summary"] = summary
        # Common Feed B boundary repair: Iran/Lebanon/Gaza/security-adjacent
        # foreign items belong in the security/world bridge, not generic politics.
        text = f"{title} {summary} {fixed.get('source') or ''}"
        if fixed.get("category") in {"פוליטיקה", "חדשות", "משפט"} and re.search(
            r"איראן|חיזבאללה|חמאס|עזה|סוריה|לבנון|תימן|חות|הורמוז|דמשק", text
        ):
            fixed["category"] = "ביטחון"
        if not str(fixed.get("imageUrl") or "").strip():
            fixed["imageUrl"] = default_image_url(fixed)
            fixed["imageFallbackKind"] = default_image_kind(fixed)
        existing = live_by_url.get(url)
        if existing is not None:
            # Editorial updates may replace text, but historical image fields
            # are immutable under the V5 trial.
            for key, value in existing.items():
                if key == "imageUrl" or key.startswith("image") or key.startswith("poentaImage"):
                    fixed[key] = value
        elif v5_enabled:
            try:
                fixed, image_info = apply_v5_image_to_new_item(fixed, live_items, v5_catalog)
                fixed["poentaImageAssignmentStatus"] = image_info.get("status")
                if trial_tracking_enabled and trial_applied < V5_TRIAL_LIMIT:
                    fixed["poentaImageTrialId"] = V5_TRIAL_ID
                    trial_applied += 1
            except Exception:
                # A last-resort local Poenta image keeps publication independent
                # of every optional V5 subsystem.
                fixed["imageUrl"] = default_image_url(fixed)
                fixed["imageFallbackKind"] = default_image_kind(fixed)
                fixed["poentaImageAssignmentStatus"] = "v5_error_local_fallback"
                if trial_tracking_enabled and trial_applied < V5_TRIAL_LIMIT:
                    fixed["poentaImageTrialId"] = V5_TRIAL_ID
                    trial_applied += 1
        elif os.environ.get("POENTA_IMAGE_BANK_ENABLED", "1") != "0" and apply_image_bank_to_item:
            fixed, _image_bank_info = apply_image_bank_to_item(fixed)
        selected.append(fixed)
        seen.add(url)
        if limit > 0 and len(selected) >= limit:
            break
    return {
        "updatedAt": source.get("updatedAt") or source.get("generatedAt") or now,
        "mode": "feed-b-live",
        "source": "Poenta Feed B promoted to live feed.json",
        "promotedAt": now,
        "items": selected,
        "errors": [],
        "previousFeedA": {
            "sideFeed": "feed_a_side.json",
            "sideBreakingFeed": "feed_a_breaking.json",
            "feedACronDisabled": "cb735adc-5eea-4987-aec5-6b518bc02cf2",
        },
        "rollback": {
            "restoreCommand": "cp feed_a_side.json feed.json && bash scripts/deploy_current_feed.sh",
            "note": "breaking_feed.json is managed separately and is not replaced by Feed B.",
        },
    }


def default_image_kind(item: dict[str, Any]) -> str:
    blob = " ".join(
        str(item.get(key) or "")
        for key in ("category", "categoryClass", "source", "sourceLogo", "title", "headline")
    ).lower()
    if "מזג" in blob:
        return "weather"
    if any(term in blob for term in ("ביטחון", "צבא", "חמאס", "איראן", "חיזבאללה", "עזה")):
        return "security"
    if any(term in blob for term in ("פוליט", "ממשלה", "כנסת", "בג״ץ", "בג\"ץ")):
        return "politics"
    if any(term in blob for term in ("כלכלה", "בורסה", "עסקים", "נדל")):
        return "economy"
    if any(term in blob for term in ("טכנולוג", "הייטק", "ai")):
        return "tech"
    if "ספורט" in blob:
        return "sports"
    if any(term in blob for term in ("תרבות", "בידור", "רכילות")):
        return "culture"
    if any(term in blob for term in ("עולם", "global", "jazeera", "bbc", "reuters", "france24")):
        return "world"
    if any(term in blob for term in ("מקומי", "עירוני", "רכב", "תחבורה")):
        return "local"
    return "news"


def default_image_url(item: dict[str, Any]) -> str:
    return f"https://poanta-demo.pages.dev/assets/feed-defaults/{default_image_kind(item)}.png"


def run_json(cmd: list[str]) -> tuple[int, dict[str, Any]]:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    try:
        data = json.loads(proc.stdout)
    except Exception:
        data = {"stdout": proc.stdout, "stderr": proc.stderr}
    return proc.returncode, data


def run_text(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    return proc.returncode, proc.stdout + proc.stderr


def quality_error_urls(report_path: Path) -> set[str]:
    if not report_path.exists():
        return set()
    urls: set[str] = set()
    in_error = False
    for line in report_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("### ERROR"):
            in_error = True
            continue
        if line.startswith("### "):
            in_error = False
        if in_error and line.startswith("- URL: "):
            urls.add(line.removeprefix("- URL: ").strip())
    return urls


def issue_url(issue: dict[str, Any]) -> str:
    nested = issue.get("item")
    if isinstance(nested, dict):
        nested_url = item_url(nested) or str(nested.get("sourceUrl") or "").strip()
        if nested_url:
            return nested_url
    return item_url(issue) or str(issue.get("sourceUrl") or "").strip()


def validate(path: Path) -> tuple[bool, set[str], str]:
    remove: set[str] = set()
    code, no_breaking = run_json(
        [sys.executable, "scripts/pointa_main_feed_no_breaking_guard.py", "--feed", str(path), "--json"]
    )
    if code != 0 or no_breaking.get("status") != "ok":
        for leak in no_breaking.get("leaks") or []:
            if leak.get("url"):
                remove.add(str(leak["url"]))

    code, live = run_json([sys.executable, "scripts/pointa_live_auditor.py", "--feed-file", str(path), "--json"])
    if code != 0 or live.get("errors"):
        for issue in live.get("errors") or []:
            if issue.get("code") in {
                "stale_updated_at",
                "no_new_top_item_sla",
                "too_few_recent_items_sla",
                "too_few_recent_sources_sla",
                "stale_top_item",
            }:
                continue
            if issue.get("url"):
                remove.add(str(issue["url"]))

    code, quality = run_text(
        [sys.executable, "scripts/pointa_quality_gate.py", "--feed", str(path), "--report", str(QUALITY_REPORT)]
    )
    if code != 0:
        remove |= quality_error_urls(QUALITY_REPORT)

    code, auditor = run_json([sys.executable, "scripts/pointa_quality_auditor.py", "--feed", str(path), "--json"])
    auditor_errors = auditor.get("errors") or []
    if code != 0 or auditor.get("status") != "ok" or auditor_errors:
        for issue in auditor_errors:
            if issue.get("url"):
                remove.add(str(issue["url"]))

    code, health = run_json(
        [
            sys.executable,
            "scripts/pointa_publication_health_gate.py",
            "--mode",
            "candidate",
            "--feed",
            str(path),
            "--json",
        ]
    )
    if code != 0 or health.get("blockers"):
        for issue in health.get("blockers") or []:
            url = issue_url(issue)
            if url:
                remove.add(url)
        if remove:
            return False, remove, f"health gate needs pruning: {len(remove)} urls"
        return False, remove, f"health gate failed: {health}"
    if remove:
        return False, remove, f"candidate needs pruning: {len(remove)} urls"
    return True, set(), quality.strip()


def validate_new_package(path: Path) -> tuple[bool, set[str], str]:
    """Run item-level editorial guards without applying whole-feed SLA gates."""
    remove: set[str] = set()
    code, no_breaking = run_json(
        [sys.executable, "scripts/pointa_main_feed_no_breaking_guard.py", "--feed", str(path), "--json"]
    )
    if code != 0 or no_breaking.get("status") != "ok":
        for leak in no_breaking.get("leaks") or []:
            if leak.get("url"):
                remove.add(str(leak["url"]))

    code, quality = run_text(
        [sys.executable, "scripts/pointa_quality_gate.py", "--feed", str(path), "--report", str(QUALITY_REPORT)]
    )
    if code != 0:
        remove |= quality_error_urls(QUALITY_REPORT)

    code, auditor = run_json([sys.executable, "scripts/pointa_quality_auditor.py", "--feed", str(path), "--json"])
    if code != 0 or auditor.get("status") != "ok" or auditor.get("errors"):
        for issue in auditor.get("errors") or []:
            url = issue_url(issue)
            if url:
                remove.add(url)

    if remove:
        return False, remove, f"new package needs pruning: {len(remove)} urls"
    return True, set(), quality.strip()


def newest_live_time(live: dict[str, Any]) -> datetime | None:
    # Feed-level timestamps describe when the file was written, not when every
    # approved article became available. Using them as an article cutoff caused
    # delayed AI approvals with older publishedAt values to be skipped forever.
    times = []
    for item in live.get("items") or []:
        if isinstance(item, dict):
            times.extend((parse_dt(item.get("updatedAt")), parse_dt(item.get("publishedAt"))))
    valid = [value for value in times if value is not None]
    return max(valid) if valid else None


def incremental_items(live: dict[str, Any], source: dict[str, Any], *, now_dt: datetime | None = None) -> list[dict[str, Any]]:
    now_dt = now_dt or datetime.now(timezone(timedelta(hours=3)))
    cutoff = now_dt - timedelta(days=7)
    live_by_url = {
        item_url(item): item
        for item in live.get("items") or []
        if isinstance(item, dict) and item_url(item)
    }
    selected: list[dict[str, Any]] = []
    quarantine = active_quarantine_entries()
    for item in source.get("items") or []:
        if not isinstance(item, dict):
            continue
        url = item_url(item)
        item_time = parse_dt(item.get("updatedAt") or item.get("publishedAt"))
        if not url or item_time is None or item_time < cutoff:
            continue
        if quarantine_matches(item, quarantine):
            continue
        existing = live_by_url.get(url)
        if existing is None:
            selected.append(item)
            continue
        if str(item.get("feedBStatus") or "").lower() == "update":
            existing_time = parse_dt(existing.get("updatedAt") or existing.get("publishedAt"))
            if existing_time is None or item_time > existing_time:
                selected.append(item)
    return selected


def merge_incremental(live: dict[str, Any], source: dict[str, Any], new_items: list[dict[str, Any]]) -> dict[str, Any]:
    now_dt = datetime.now(timezone(timedelta(hours=3)))
    now = now_dt.isoformat(timespec="seconds")
    by_url = {item_url(item): dict(item) for item in live.get("items") or [] if isinstance(item, dict) and item_url(item)}
    for item in new_items:
        url = item_url(item)
        fixed = dict(item)
        existing = by_url.get(url)
        if existing is not None:
            for key, value in existing.items():
                if key == "imageUrl" or key.startswith("image") or key.startswith("poentaImage"):
                    fixed[key] = value
        by_url[url] = fixed
    cutoff = now_dt - timedelta(days=7)
    merged = []
    for item in by_url.values():
        published = parse_dt(item.get("publishedAt") or item.get("updatedAt"))
        if published is None or published >= cutoff:
            merged.append(item)
    merged.sort(key=lambda item: str(item.get("publishedAt") or item.get("updatedAt") or ""), reverse=True)
    for index, item in enumerate(merged):
        item["displayRank"] = index
        item["feedBPackage"] = index // 10 + 1
    payload = dict(live)
    payload.update({
        "updatedAt": now,
        "promotedAt": now,
        "mode": "feed-b-live-incremental",
        "source": "Poenta main feed incremental publish",
        "items": merged,
        "errors": [],
    })
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="Maximum items to promote; 0 means all eligible 7-day Feed B items")
    ap.add_argument("--min-items", type=int, default=20)
    ap.add_argument("--out", default=str(LIVE_FEED))
    args = ap.parse_args()

    source = load_json(FEED_B, {})
    live = load_json(LIVE_FEED, {})
    items = source.get("items") or []
    if not isinstance(items, list):
        raise SystemExit("feed_b.json has no items array")

    if not isinstance(live.get("items"), list) or not live.get("items"):
        raise SystemExit("live feed.json is missing or empty; refusing incremental promotion")

    incremental = incremental_items(live, source)

    if not incremental:
        print(json.dumps({"ok": True, "reason": "no-new-live-items", "items": len(live.get("items") or [])}, ensure_ascii=False, indent=2))
        return 0

    blocked: set[str] = set()
    quarantined: list[dict[str, Any]] = []
    report: dict[str, Any] = {}
    for attempt in range(1, len(incremental) + 2):
        usable = [item for item in incremental if item_url(item) not in blocked]
        payload = candidate_payload(source, usable, args.limit, live)
        count = len(payload.get("items") or [])
        if count == 0:
            persist_promotion_quarantine(quarantined, "public QA rejected unchanged promotion candidate")
            print(json.dumps({
                "ok": True,
                "reason": "all-new-items-quarantined",
                "newCandidates": len(incremental),
                "quarantined": len(quarantined),
                "items": len(live.get("items") or []),
            }, ensure_ascii=False, indent=2))
            return 0
        write_json(TMP_CANDIDATE, payload)
        ok, remove, message = validate_new_package(TMP_CANDIDATE)
        report = {"attempt": attempt, "newCandidates": len(incremental), "accepted": count, "ok": ok, "message": message, "pruned": len(blocked)}
        if ok:
            merged = merge_incremental(live, source, payload.get("items") or [])
            if len(merged.get("items") or []) < args.min_items:
                raise SystemExit("merged live candidate is unexpectedly small")
            write_json(Path(args.out), merged)
            persist_promotion_quarantine(quarantined, "public QA rejected unchanged promotion candidate")
            write_json(ROOT / "tmp" / "feed-b-live-auto-promotion.json", report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if not remove:
            write_json(ROOT / "tmp" / "feed-b-live-auto-promotion.json", report)
            raise SystemExit(message)
        newly_removed = remove - blocked
        quarantined.extend(item for item in incremental if item_url(item) in newly_removed)
        blocked |= remove

    write_json(ROOT / "tmp" / "feed-b-live-auto-promotion.json", report)
    raise SystemExit("incremental live promotion failed to converge")


if __name__ == "__main__":
    raise SystemExit(main())
