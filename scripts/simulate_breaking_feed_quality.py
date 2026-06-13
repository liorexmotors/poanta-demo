#!/usr/bin/env python3
"""Create a read-only TT RR simulation report for Poanta breaking flashes.

This script never mutates breaking_feed.json. It reads the current breaking feed,
computes freshness/dedupe/source-health metrics, creates a conservative simulated
ordering, and writes a public JSON endpoint for the open Aliza page.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BREAKING = ROOT / "breaking_feed.json"
DEFAULT_PUBLIC_OUT = ROOT / "tt_rr_breaking_simulation_feed.json"

URGENT_TERMS = [
    "אזעק", "ירי", "טיל", "כטב", "פיגוע", "הרוג", "נפצע", "נפגע", "חוסל", "תקיפה",
    "איראן", "חיזבאללה", "חמאס", "צה״ל", "צה\"ל", "משטרה", "בית המשפט", "נתניהו",
]
LOW_VALUE_TERMS = ["ספורט", "רכילות", "סלב", "כוכב", "ביקיני", "שמלה", "ריאליטי"]
SOURCE_TIERS = {
    "ynet": 7,
    "N12": 8,
    "וואלה": 6,
    "מעריב": 6,
    "הארץ": 6,
    "ישראל היום": 5,
    "גלובס": 6,
    "רוטר": 2,
    "Jerusalem Post": 4,
}


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def age_minutes(item: dict[str, Any], now: datetime) -> int | None:
    dt = parse_dt(item.get("publishedAt") or item.get("published_at"))
    if not dt:
        return None
    return max(0, int((now.astimezone(dt.tzinfo) - dt).total_seconds() // 60))


def canonical_source(name: Any) -> str:
    source = str(name or "")
    low = source.lower()
    if "ynet" in low:
        return "ynet"
    if "mako" in low or "n12" in source:
        return "N12"
    if "rotter" in low or "רוטר" in source:
        return "רוטר"
    if "jerusalem post" in low or "jpost" in low:
        return "Jerusalem Post"
    for token in ["וואלה", "מעריב", "הארץ", "גלובס", "ישראל היום"]:
        if token in source:
            return token
    return source.split(" - ")[0].strip() or "מקור"


def item_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(k) or "") for k in ("category", "source", "headline", "originalTitle", "context", "takeaway"))


def story_key(item: dict[str, Any]) -> str:
    text = item_text(item).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^\w\u0590-\u05ff]+", " ", text)
    words = [w for w in text.split() if len(w) > 2]
    stop = {"של", "על", "את", "עם", "לאחר", "בשל", "הוא", "היא", "היו", "עוד", "דיווח"}
    words = [w for w in words if w not in stop]
    return " ".join(words[:10]) or str(item.get("headline") or "")[:60]


def is_urgent(item: dict[str, Any]) -> bool:
    text = item_text(item)
    return any(term in text for term in URGENT_TERMS)


def is_low_value(item: dict[str, Any]) -> bool:
    text = item_text(item)
    return any(term in text for term in LOW_VALUE_TERMS)


def score_item(item: dict[str, Any], now: datetime, source_counts: Counter[str], story_counts: Counter[str]) -> float:
    age = age_minutes(item, now)
    src = canonical_source(item.get("source"))
    value = 0.0
    if age is None:
        value -= 1000
    elif age <= 10:
        value += 140 - age
    elif age <= 60:
        value += 120 - age * 0.9
    elif age <= 180:
        value += 65 - (age - 60) * 0.45
    else:
        value -= min(200, (age - 180) * 0.55)
    value += SOURCE_TIERS.get(src, 0)
    if is_urgent(item):
        value += 18
    if is_low_value(item):
        value -= 22
    value -= max(0, source_counts[src] - 1) * 16
    value -= max(0, story_counts[story_key(item)] - 1) * 30
    return value


def simulate_order(items: list[dict[str, Any]], now: datetime, limit: int) -> list[dict[str, Any]]:
    pool = list(items[:limit])
    selected: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    story_counts: Counter[str] = Counter()
    while pool:
        best = max(pool, key=lambda item: score_item(item, now, source_counts, story_counts))
        pool.remove(best)
        selected.append(best)
        source_counts[canonical_source(best.get("source"))] += 1
        story_counts[story_key(best)] += 1
    return selected


def metric_block(items: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    top = items[:20]
    ages = [age_minutes(it, now) for it in top]
    sources = [canonical_source(it.get("source")) for it in top]
    stories = [story_key(it) for it in top]
    source_counts = Counter(sources)
    story_counts = Counter(stories)
    dominant = source_counts.most_common(1)[0] if source_counts else ("—", 0)
    return {
        "count": len(items),
        "top20Under10": sum(1 for a in ages if a is not None and a <= 10),
        "top20Under30": sum(1 for a in ages if a is not None and a <= 30),
        "top20Under60": sum(1 for a in ages if a is not None and a <= 60),
        "topItemAgeMinutes": ages[0] if ages else None,
        "oldestTop20AgeMinutes": max([a for a in ages if a is not None], default=None),
        "urgentTop20": sum(1 for it in top if is_urgent(it)),
        "lowValueTop20": sum(1 for it in top if is_low_value(it)),
        "uniqueSourcesTop20": len(set(sources)),
        "dominantSource": {"name": dominant[0], "count": dominant[1]},
        "duplicateStoryGroupsTop20": sum(1 for _, c in story_counts.items() if c > 1),
        "topSources": [{"name": k, "count": v} for k, v in source_counts.most_common(8)],
    }


def health_score(metrics: dict[str, Any]) -> int:
    score = 0
    score += min(35, int(metrics.get("top20Under30", 0)) * 3)
    score += min(20, int(metrics.get("urgentTop20", 0)) * 2)
    score += min(15, int(metrics.get("uniqueSourcesTop20", 0)))
    score += max(0, 15 - int(metrics.get("lowValueTop20", 0)) * 3)
    score += max(0, 15 - int(metrics.get("duplicateStoryGroupsTop20", 0)) * 5)
    top_age = metrics.get("topItemAgeMinutes")
    if top_age is None:
        score -= 15
    elif top_age > 30:
        score -= 15
    elif top_age > 10:
        score -= 5
    return max(0, min(100, score))


def top_cards(items: list[dict[str, Any]], before_index: dict[str, int], now: datetime, limit: int = 30) -> list[dict[str, Any]]:
    cards = []
    for idx, item in enumerate(items[:limit], start=1):
        key = item.get("id") or item.get("sourceUrl") or item.get("headline")
        before_rank = before_index.get(str(key))
        cards.append({
            "rank": idx,
            "beforeRank": before_rank,
            "delta": None if before_rank is None else before_rank - idx,
            "id": item.get("id"),
            "headline": item.get("headline") or item.get("originalTitle") or "",
            "source": item.get("source"),
            "canonicalSource": canonical_source(item.get("source")),
            "sourceUrl": item.get("sourceUrl") or item.get("url"),
            "publishedAt": item.get("publishedAt") or item.get("published_at"),
            "ageMinutes": age_minutes(item, now),
            "urgent": is_urgent(item),
            "lowValue": is_low_value(item),
            "storyKey": story_key(item),
        })
    return cards


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--breaking", default=str(DEFAULT_BREAKING))
    ap.add_argument("--public-out", default=str(DEFAULT_PUBLIC_OUT))
    ap.add_argument("--limit", type=int, default=80)
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    source = Path(args.breaking)
    raw = json.loads(source.read_text(encoding="utf-8"))
    items = raw.get("items") if isinstance(raw, dict) else raw
    items = list(items or [])
    simulated = simulate_order(items, now, args.limit)
    before = metric_block(items, now)
    after = metric_block(simulated, now)
    before_health = health_score(before)
    after_health = health_score(after)
    before_index = {str(item.get("id") or item.get("sourceUrl") or item.get("headline")): i for i, item in enumerate(items, start=1)}
    report = {
        "generatedAt": now.isoformat(),
        "mode": "tt_rr_breaking_simulation_only_readonly",
        "sourceFile": "breaking_feed.json",
        "accessPurpose": "open_readonly_aliza_tt_rr_breaking_simulation",
        "operatorInstruction": "Use only this TT RR breaking simulation feed for flash review. Do not inspect, judge, or act on the regular breaking feed for this experiment. This page and JSON are read-only and never publish to breaking_feed.json.",
        "hebrewInstruction": "עליזה: במבזקים לעבוד רק על פיד סימולציית המבזקים של TT RR. לא לעבור יותר על המבזקים הרגילים לצורך הניסוי הזה. לקרוא, להשוות ולדווח רק מהסימולציה — בלי פרסום ובלי שינוי breaking_feed.json.",
        "rules": [
            "read-only: לא משנה את breaking_feed.json",
            "רעננות חזקה מאוד: מבזק ישן נענש בדירוג",
            "אירוע דומה ממספר מקורות צריך להופיע כקבוצה/סיפור אחד ולא כהצפה",
            "מגבלת השתלטות מקור אחד על Top 20",
            "העדפה למבזקי חירום/ביטחון/מדיניות/משפט על פני תוכן רך",
        ],
        "before": before,
        "after": after,
        "beforeHealthScore": before_health,
        "afterHealthScore": after_health,
        "delta": {
            "healthScore": after_health - before_health,
            "top20Under30": after["top20Under30"] - before["top20Under30"],
            "urgentTop20": after["urgentTop20"] - before["urgentTop20"],
            "lowValueTop20": after["lowValueTop20"] - before["lowValueTop20"],
            "duplicateStoryGroupsTop20": after["duplicateStoryGroupsTop20"] - before["duplicateStoryGroupsTop20"],
            "uniqueSourcesTop20": after["uniqueSourcesTop20"] - before["uniqueSourcesTop20"],
        },
        "top30After": top_cards(simulated, before_index, now, 30),
        "top30Before": top_cards(items, before_index, now, 30),
    }
    out = Path(args.public_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"publicOut": str(out), "before": before, "after": after, "delta": report["delta"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
