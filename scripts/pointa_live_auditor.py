#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Continuous live auditor for Poanta/Pointa.

This is "המבקר": it checks the actual public feed on a fixed schedule,
independently of whether a publish just happened. That way it catches both bad
publishes and missing/stuck publishes. It is intentionally conservative:
warnings are useful; failures mean the feed should be reviewed or fixed before
the next automatic publish cycle keeps reinforcing the issue.
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
    "נטען ש",
    "גורם איראני:",
    "גורמים בארה״ב:",
    "גורמים אמריקנים:",
    "מקור ב",
]
GENERIC_TAKEAWAY_FRAGMENTS = [
    "אי־ודאות ביטחונית שוחקת את הציבור",
    "ההשפעה המעשית",
    "זו אזהרת היערכות",
    "כדאי לעקוב",
    "האירוע מדגיש",
    "הסיפור מדגים",
    "הסיפור מציג",
]

FOREIGN_SOURCE_NAMES = {
    "bbc",
    "cnn",
    "sky news",
    "reuters",
    "ap",
    "associated press",
    "guardian",
    "nyt",
    "new york times",
    "axios",
    "politico",
    "bloomberg",
    "al jazeera",
}

IMPORTANT_SOURCE_MAX_AGE_MIN = {
    "הארץ": 120,
    "ynet": 90,
    "וואלה": 90,
    "מעריב": 120,
    "גלובס": 180,
    "ישראל היום": 180,
    "דה מרקר": 240,
}

DUPLICATE_STOPWORDS = set(
    "של על את עם זה זו הוא היא הם הן כי אשר אבל או אם גם יותר פחות לתוך מתוך "
    "אחרי לפני כדי כמו בין לפי ללא מול תחת מעל כל כבר עוד אותו אותה אותם אותן "
    "יש אין היה היתה היו יהיה תהיה להיות מה למה איך מי לא כן "
    "in the a an and or of to for with on at from by is are was were be as that this"
    .split()
)


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


def duplicate_words(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z0-9\u0590-\u05ff]+", (text or "").lower().replace("׳", "").replace("\"", ""))
    return {w for w in words if len(w) > 2 and w not in DUPLICATE_STOPWORDS}


def story_words(item: dict[str, Any]) -> set[str]:
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context"])
    return set(list(duplicate_words(text))[:48])


def word_overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, min(len(a), len(b)))


def topic_for_item(item: dict[str, Any]) -> str:
    category = str(item.get("category") or "חדשות")
    if category == "תחבורה":
        return "רכב"
    if category == "חדשות":
        return "פוליטיקה"
    if category == "עולם":
        return "ביטחון"
    return category


def is_hebrew_source(item: dict[str, Any]) -> bool:
    if canonical_source_label(item) in FOREIGN_SOURCE_NAMES:
        return False
    source = str(item.get("source") or item.get("sourceLogo") or "")
    return bool(re.search(r"[\u0590-\u05ff]", source))


def detail_score(item: dict[str, Any]) -> int:
    return len(" ".join(str(item.get(k) or "") for k in ["context", "takeaway", "originalTitle", "headline"])) + (24 if item.get("imageUrl") else 0)


def preferred_duplicate_item(a: tuple[int, dict[str, Any]], b: tuple[int, dict[str, Any]]) -> tuple[int, dict[str, Any]]:
    _, ai = a
    _, bi = b
    ah, bh = is_hebrew_source(ai), is_hebrew_source(bi)
    if ah != bh:
        return a if ah else b
    ad, bd = detail_score(ai), detail_score(bi)
    if abs(ad - bd) > 20:
        return a if ad > bd else b
    adt = parse_dt(str(ai.get("publishedAt") or "")) or datetime.min.replace(tzinfo=TZ)
    bdt = parse_dt(str(bi.get("publishedAt") or "")) or datetime.min.replace(tzinfo=TZ)
    return a if adt >= bdt else b


def likely_duplicate_story(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if str(a.get("sourceUrl") or "") == str(b.get("sourceUrl") or ""):
        return False
    if str(a.get("source") or "") == str(b.get("source") or ""):
        return False
    if topic_for_item(a) != topic_for_item(b):
        return False
    if word_overlap(story_words(a), story_words(b)) >= 0.62:
        return True
    at = " ".join(sorted(duplicate_words(str(a.get("originalTitle") or a.get("headline") or ""))))
    bt = " ".join(sorted(duplicate_words(str(b.get("originalTitle") or b.get("headline") or ""))))
    return len(at) > 20 and len(bt) > 20 and (at in bt or bt in at)


def duplicate_story_findings(feed: dict[str, Any], scan_limit: int) -> list[Finding]:
    items = list(enumerate(feed.get("items") or []))[:scan_limit]
    findings: list[Finding] = []
    used: set[int] = set()
    for i, item in items:
        if i in used:
            continue
        cluster = [(i, item)]
        for j, other in items:
            if j <= i or j in used:
                continue
            if likely_duplicate_story(item, other):
                cluster.append((j, other))
        if len(cluster) < 2:
            continue
        keep = cluster[0]
        for candidate in cluster[1:]:
            keep = preferred_duplicate_item(keep, candidate)
        used.update(idx for idx, _ in cluster)
        dropped = [f"#{idx} {it.get('source','')} — {it.get('headline','')}" for idx, it in cluster if idx != keep[0]]
        findings.append(Finding(
            "warning",
            "duplicate_story_cluster",
            "Similar live-feed stories from different sources. Recommended keep: "
            f"#{keep[0]} {keep[1].get('source','')} — {keep[1].get('headline','')}. "
            f"Filter out: {'; '.join(dropped)}",
            keep[0],
            keep[1].get("headline", ""),
            keep[1].get("source", ""),
            keep[1].get("sourceUrl", ""),
        ))
    return findings


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


def canonical_hebrew_source_label(item: dict[str, Any]) -> str:
    s_raw = str(item.get("sourceLogo") or item.get("source") or "")
    s = s_raw.lower()
    if "הארץ" in s_raw or "haaretz" in s:
        return "הארץ"
    if "דה מרקר" in s_raw or "themarker" in s:
        return "דה מרקר"
    if "ynet" in s:
        return "ynet"
    if "וואלה" in s_raw or "walla" in s:
        return "וואלה"
    if "מעריב" in s_raw or "maariv" in s:
        return "מעריב"
    if "גלובס" in s_raw or "globes" in s:
        return "גלובס"
    if "ישראל היום" in s_raw or "israel hayom" in s:
        return "ישראל היום"
    return ""


def canonical_source_label(item: dict[str, Any]) -> str:
    s = str(item.get("sourceLogo") or item.get("source") or "").lower()
    if "bbc" in s:
        return "bbc"
    if "cnn" in s:
        return "cnn"
    if "sky" in s:
        return "sky news"
    if "reuters" in s:
        return "reuters"
    if "associated press" in s or re.search(r"\bap\b", s):
        return "ap"
    if "guardian" in s:
        return "guardian"
    if "new york times" in s or "nyt" in s:
        return "nyt"
    if "axios" in s:
        return "axios"
    if "politico" in s:
        return "politico"
    if "bloomberg" in s:
        return "bloomberg"
    if "jazeera" in s:
        return "al jazeera"
    return s


def latest_matching_item(items: list[dict[str, Any]], predicate) -> tuple[int, dict[str, Any], datetime] | None:
    best: tuple[int, dict[str, Any], datetime] | None = None
    for idx, item in enumerate(items):
        d = parse_dt(str(item.get("publishedAt") or ""))
        if not d or not predicate(item):
            continue
        if best is None or d > best[2]:
            best = (idx, item, d)
    return best


def audit(feed: dict[str, Any], raw_feed: dict[str, Any] | None, *, max_update_age_min: int, max_top_age_hours: int, max_foreign_age_min: int, top_limit: int, recent_window_min: int, min_recent_items: int, min_recent_sources: int, no_new_warning_min: int, no_new_error_min: int) -> list[Finding]:
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
    elif now.hour >= 6:
        top_age = now - first_dt
        active_news_hours = 6 <= now.hour < 23
        if active_news_hours and top_age > timedelta(minutes=no_new_error_min):
            findings.append(Finding(
                "error",
                "no_new_top_item_sla",
                f"No new top feed item for more than {no_new_error_min}m: latest is {first_dt.isoformat()} ({top_age} old). Treat as operational problem; do not lower editorial standards, trigger collection/editor/QA/deploy rescue.",
                0,
                items[0].get("headline", ""),
                items[0].get("source", ""),
                items[0].get("sourceUrl", ""),
            ))
        elif active_news_hours and top_age > timedelta(minutes=no_new_warning_min):
            findings.append(Finding(
                "warning",
                "no_new_top_item_warning",
                f"No new top feed item for more than {no_new_warning_min}m: latest is {first_dt.isoformat()} ({top_age} old). Warning only; if it reaches {no_new_error_min}m, treat as operational problem.",
                0,
                items[0].get("headline", ""),
                items[0].get("source", ""),
                items[0].get("sourceUrl", ""),
            ))
        if top_age > timedelta(hours=max_top_age_hours):
            findings.append(Finding("error", "stale_top_item", f"Top item is too old for live feed: {first_dt.isoformat()}", 0, items[0].get("headline", ""), items[0].get("source", ""), items[0].get("sourceUrl", "")))

    top = items[0]
    for source_name, max_age_min in IMPORTANT_SOURCE_MAX_AGE_MIN.items():
        latest_source = latest_matching_item(items, lambda item, source_name=source_name: canonical_hebrew_source_label(item) == source_name)
        if latest_source:
            idx, item, dt = latest_source
            source_age = now - dt
            if now.hour >= 6 and source_age > timedelta(minutes=max_age_min):
                findings.append(Finding(
                    "warning",
                    "stale_important_source_view",
                    f"Latest {source_name} item is older than {max_age_min}m: {dt.isoformat()} ({source_age} old). The overall feed may look fresh while this source view is stale. Alert only; no automatic feed change.",
                    idx,
                    item.get("headline", ""),
                    item.get("source", ""),
                    item.get("sourceUrl", ""),
                ))
        else:
            findings.append(Finding("warning", "missing_important_source_items", f"No {source_name} items found in the live feed; source view may look empty"))

    latest_foreign = latest_matching_item(items, lambda item: canonical_source_label(item) in FOREIGN_SOURCE_NAMES)
    if latest_foreign:
        idx, item, dt = latest_foreign
        foreign_age = now - dt
        if now.hour >= 6 and foreign_age > timedelta(minutes=max_foreign_age_min):
            findings.append(Finding(
                "warning",
                "stale_foreign_source_view",
                f"Latest foreign-source item is older than {max_foreign_age_min}m: {dt.isoformat()} ({foreign_age} old). Overall feed may still look fresh, but the world/source view can look stuck. Alert only; this does not block or modify the feed by itself.",
                idx,
                item.get("headline", ""),
                item.get("source", ""),
                item.get("sourceUrl", ""),
            ))
    else:
        findings.append(Finding("warning", "missing_foreign_source_items", "No foreign-source items found in the live feed; world/source view may look empty"))

    if str(top.get("category") or "") == "מזג אוויר" or "מזג" in str(top.get("headline") or ""):
        findings.append(Finding("error", "weather_on_top", "Weather is the top live item; this usually means fresh news did not publish", 0, top.get("headline", ""), top.get("source", ""), top.get("sourceUrl", "")))

    fresh_count = 0
    recent_count = 0
    recent_sources: set[str] = set()
    for item in items[:top_limit]:
        d = parse_dt(str(item.get("publishedAt") or ""))
        if d and now - d <= timedelta(hours=max_top_age_hours):
            fresh_count += 1
        if d and now - d <= timedelta(minutes=recent_window_min):
            recent_count += 1
            label = canonical_hebrew_source_label(item) or canonical_source_label(item) or str(item.get("source") or "")
            if label:
                recent_sources.add(label)
    if now.hour >= 6 and fresh_count < 3:
        findings.append(Finding("error", "too_few_fresh_top_items", f"Only {fresh_count} of top {top_limit} items are fresh within {max_top_age_hours}h"))
    if now.hour >= 6 and recent_count < min_recent_items:
        findings.append(Finding(
            "error",
            "too_few_recent_items_sla",
            f"Quantity SLA failed: only {recent_count} of top {top_limit} items are newer than {recent_window_min}m; minimum is {min_recent_items}. Quality must stay strict, but low volume must trigger rescue/source expansion.",
        ))
    if now.hour >= 6 and len(recent_sources) < min_recent_sources:
        findings.append(Finding(
            "error",
            "too_few_recent_sources_sla",
            f"Quantity SLA failed: only {len(recent_sources)} distinct recent source groups in top {top_limit} within {recent_window_min}m; minimum is {min_recent_sources}. Feed may look narrow even if items are fresh.",
        ))

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
    findings.extend(duplicate_story_findings(feed, max(top_limit * 4, 40)))

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
    ap.add_argument("--max-top-age-hours", type=int, default=2)
    ap.add_argument("--max-foreign-age-min", type=int, default=60)
    ap.add_argument("--recent-window-min", type=int, default=60, help="Quantity SLA window for fresh visible volume")
    ap.add_argument("--min-recent-items", type=int, default=5, help="Minimum top items newer than recent-window-min")
    ap.add_argument("--min-recent-sources", type=int, default=3, help="Minimum distinct recent source groups in the top slice")
    ap.add_argument("--no-new-warning-min", type=int, default=15, help="Warning threshold for no new top item during active news hours")
    ap.add_argument("--no-new-error-min", type=int, default=30, help="Error threshold for no new top item during active news hours")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    live = fetch_json(args.url)
    raw = None
    try:
        raw = fetch_json(args.raw_url)
    except Exception:
        raw = None
    findings = audit(live, raw, max_update_age_min=args.max_update_age_min, max_top_age_hours=args.max_top_age_hours, max_foreign_age_min=args.max_foreign_age_min, top_limit=args.top, recent_window_min=args.recent_window_min, min_recent_items=args.min_recent_items, min_recent_sources=args.min_recent_sources, no_new_warning_min=args.no_new_warning_min, no_new_error_min=args.no_new_error_min)
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
