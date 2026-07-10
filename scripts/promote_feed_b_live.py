#!/usr/bin/env python3
"""Promote a QA-clean Feed B package into the live feed.json.

This is intentionally fail-closed: if Feed B cannot produce a clean candidate,
the current live feed is left untouched.
"""

from __future__ import annotations

import argparse
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


ROOT = Path(__file__).resolve().parents[1]
FEED_B = ROOT / "feed_b.json"
LIVE_FEED = ROOT / "feed.json"
TMP_CANDIDATE = ROOT / "tmp" / "feed-b-live-auto-candidate.json"
QUALITY_REPORT = ROOT / "tmp" / "feed-b-live-auto-quality.md"


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def item_url(item: dict[str, Any]) -> str:
    return str(item.get("url") or item.get("sourceUrl") or item.get("link") or "").strip()


def item_title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("headline") or "").strip()


def item_summary(item: dict[str, Any]) -> str:
    return str(item.get("summary") or item.get("subtitle") or item.get("context") or "").strip()


def candidate_payload(source: dict[str, Any], items: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    now = datetime.now(timezone(timedelta(hours=3))).isoformat(timespec="seconds")
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
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
        if os.environ.get("POENTA_IMAGE_BANK_ENABLED", "1") != "0" and apply_image_bank_to_item:
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="Maximum items to promote; 0 means all eligible 7-day Feed B items")
    ap.add_argument("--min-items", type=int, default=20)
    ap.add_argument("--out", default=str(LIVE_FEED))
    args = ap.parse_args()

    source = load_json(FEED_B, {})
    items = source.get("items") or []
    if not isinstance(items, list):
        raise SystemExit("feed_b.json has no items array")

    blocked: set[str] = set()
    report: dict[str, Any] = {}
    for attempt in range(1, 8):
        usable = [item for item in items if item_url(item) not in blocked]
        payload = candidate_payload(source, usable, args.limit)
        count = len(payload.get("items") or [])
        if count < args.min_items:
            raise SystemExit(f"Feed B live candidate too small after pruning: {count}")
        write_json(TMP_CANDIDATE, payload)
        ok, remove, message = validate(TMP_CANDIDATE)
        report = {"attempt": attempt, "items": count, "ok": ok, "message": message, "pruned": len(blocked)}
        if ok:
            write_json(Path(args.out), payload)
            write_json(ROOT / "tmp" / "feed-b-live-auto-promotion.json", report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if not remove:
            write_json(ROOT / "tmp" / "feed-b-live-auto-promotion.json", report)
            raise SystemExit(message)
        blocked |= remove

    write_json(ROOT / "tmp" / "feed-b-live-auto-promotion.json", report)
    raise SystemExit("Feed B live promotion failed after pruning attempts")


if __name__ == "__main__":
    raise SystemExit(main())
