#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Post-publish live auditor for Poanta/Pointa.

This is "המבקר": it checks the actual public feed after publication, not just
local build artifacts. It is intentionally conservative: warnings are useful,
failures mean the feed should be reviewed or fixed before the next automatic
publish cycle keeps reinforcing the issue.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

try:
    from pointa_quality_gate import validate_item  # type: ignore
except Exception:  # pragma: no cover
    validate_item = None

LIVE_FEED_URL = "https://liorexmotors.github.io/poanta-demo/feed.json"
RAW_GHPAGES_URL = "https://raw.githubusercontent.com/liorexmotors/poanta-demo/gh-pages/feed.json"
TZ = timezone(timedelta(hours=3))

BAD_HEADLINE_FRAGMENTS = [
    "בריאיון שקיים",
    "הכתבה עוסקת",
    "הכתב מתאר",
    "פורסם כי",
    "דווח כי",
    "מקור ב",
]
GENERIC_TAKEAWAY_FRAGMENTS = [
    "אי־ודאות ביטחונית שוחקת את הציבור",
    "ההשפעה המעשית",
    "זו אזהרת היערכות",
    "כדאי לעקוב",
    "האירוע מדגיש",
    "הסיפור מדגים",
]


@dataclass
class Finding:
    severity: str  # error|warning
    code: str
    message: str
    item: int | None = None
    headline: str = ""
    source: str = ""
    url: str = ""


def fetch_json(url: str) -> dict[str, Any]:
    req = Request(
        url + ("&" if "?" in url else "?") + f"auditor={int(datetime.now().timestamp() * 1000)}",
        headers={
            "User-Agent": "PointaLiveAuditor/1.0",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_dt(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=TZ)
        return d.astimezone(TZ)
    except Exception:
        return None


def norm_words(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z0-9\u0590-\u05ff]+", (text or "").lower())
    return {w for w in words if len(w) > 2}


def too_close(a: str, b: str) -> bool:
    aw = norm_words(a)
    bw = norm_words(b)
    if not aw or not bw:
        return False
    return len(aw & bw) / max(1, min(len(aw), len(bw))) >= 0.72


def quality_findings(feed: dict[str, Any], top_limit: int) -> list[Finding]:
    findings: list[Finding] = []
    if validate_item is None:
        findings.append(Finding("warning", "quality_gate_unavailable", "Could not import pointa_quality_gate.validate_item"))
        return findings
    for idx, item in enumerate(feed.get("items", [])[:top_limit]):
        issues: list[dict[str, Any]] = []
        try:
            validate_item(item, idx, issues)
        except Exception as exc:
            findings.append(Finding("error", "quality_exception", str(exc), idx, item.get("headline", ""), item.get("source", ""), item.get("sourceUrl", "")))
            continue
        for issue in issues:
            if issue.get("severity") == "error":
                findings.append(Finding(
                    "error",
                    str(issue.get("code") or "quality_error"),
                    str(issue.get("message") or "Quality Gate error"),
                    idx,
                    item.get("headline", ""),
                    item.get("source", ""),
                    item.get("sourceUrl", ""),
                ))
    return findings


def audit(feed: dict[str, Any], raw_feed: dict[str, Any] | None, *, max_update_age_min: int, max_top_age_hours: int, top_limit: int) -> list[Finding]:
    findings: list[Finding] = []
    now = datetime.now(TZ)
    items = feed.get("items") or []
    if not isinstance(items, list) or not items:
        return [Finding("error", "empty_feed", "Live feed has no items")]

    updated = parse_dt(str(feed.get("updatedAt") or ""))
    if not updated:
        findings.append(Finding("error", "missing_updated_at", "Live feed has no valid updatedAt"))
    else:
        age = now - updated
        if age > timedelta(minutes=max_update_age_min):
            findings.append(Finding("error", "stale_updated_at", f"Live updatedAt is stale: {updated.isoformat()} ({age} old)"))

    first_dt = parse_dt(str(items[0].get("publishedAt") or ""))
    if not first_dt:
        findings.append(Finding("error", "top_missing_published_at", "Top item has no valid publishedAt", 0, items[0].get("headline", ""), items[0].get("source", ""), items[0].get("sourceUrl", "")))
    elif now.hour >= 6 and now - first_dt > timedelta(hours=max_top_age_hours):
        findings.append(Finding("error", "stale_top_item", f"Top item is too old for live feed: {first_dt.isoformat()}", 0, items[0].get("headline", ""), items[0].get("source", ""), items[0].get("sourceUrl", "")))

    top = items[0]
    if str(top.get("category") or "") == "מזג אוויר" or "מזג" in str(top.get("headline") or ""):
        findings.append(Finding("error", "weather_on_top", "Weather is the top live item; this usually means fresh news did not publish", 0, top.get("headline", ""), top.get("source", ""), top.get("sourceUrl", "")))

    fresh_count = 0
    for item in items[:top_limit]:
        d = parse_dt(str(item.get("publishedAt") or ""))
        if d and now - d <= timedelta(hours=max_top_age_hours):
            fresh_count += 1
    if now.hour >= 6 and fresh_count < 3:
        findings.append(Finding("error", "too_few_fresh_top_items", f"Only {fresh_count} of top {top_limit} items are fresh within {max_top_age_hours}h"))

    for idx, item in enumerate(items[:top_limit]):
        headline = str(item.get("headline") or "")
        original = str(item.get("originalTitle") or "")
        context = str(item.get("context") or "")
        takeaway = str(item.get("takeaway") or "")
        if any(fragment in headline for fragment in BAD_HEADLINE_FRAGMENTS):
            findings.append(Finding("error", "summary_fragment_headline", "Headline looks like a summary/source fragment, not a Pointa event headline", idx, headline, item.get("source", ""), item.get("sourceUrl", "")))
        if original and too_close(headline, original):
            findings.append(Finding("error", "headline_too_close_to_source", "Headline is too close to original source title", idx, headline, item.get("source", ""), item.get("sourceUrl", "")))
        if context and too_close(headline, context):
            findings.append(Finding("warning", "headline_duplicates_summary", "Headline is too close to the summary", idx, headline, item.get("source", ""), item.get("sourceUrl", "")))
        if any(fragment in takeaway for fragment in GENERIC_TAKEAWAY_FRAGMENTS):
            findings.append(Finding("error", "generic_takeaway_regression", "Takeaway matches a known generic/regression pattern", idx, headline, item.get("source", ""), item.get("sourceUrl", "")))

    findings.extend(quality_findings(feed, top_limit))

    if raw_feed:
        if raw_feed.get("updatedAt") != feed.get("updatedAt"):
            findings.append(Finding("warning", "live_raw_mismatch", f"GitHub Pages and raw gh-pages differ: live={feed.get('updatedAt')} raw={raw_feed.get('updatedAt')}"))

    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit the public Poanta feed after publish")
    ap.add_argument("--url", default=LIVE_FEED_URL)
    ap.add_argument("--raw-url", default=RAW_GHPAGES_URL)
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--max-update-age-min", type=int, default=25)
    ap.add_argument("--max-top-age-hours", type=int, default=4)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    live = fetch_json(args.url)
    raw = None
    try:
        raw = fetch_json(args.raw_url)
    except Exception:
        raw = None
    findings = audit(live, raw, max_update_age_min=args.max_update_age_min, max_top_age_hours=args.max_top_age_hours, top_limit=args.top)
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    result = {
        "status": "fail" if errors else "ok",
        "checkedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "url": args.url,
        "updatedAt": live.get("updatedAt"),
        "items": len(live.get("items") or []),
        "top": [
            {
                "publishedAt": item.get("publishedAt"),
                "source": item.get("source"),
                "headline": item.get("headline"),
                "takeaway": item.get("takeaway"),
                "url": item.get("sourceUrl"),
            }
            for item in (live.get("items") or [])[: args.top]
        ],
        "errors": [asdict(f) for f in errors],
        "warnings": [asdict(f) for f in warnings],
    }
    out_dir = ROOT / "tmp"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "pointa_live_auditor_last.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Pointa live auditor: {result['status']} · updatedAt={result['updatedAt']} · items={result['items']}")
        for f in errors + warnings[:8]:
            loc = f" item {f.item}" if f.item is not None else ""
            print(f"- {f.severity.upper()} {f.code}{loc}: {f.message}")
            if f.headline:
                print(f"  headline: {f.headline}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
