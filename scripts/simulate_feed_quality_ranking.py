#!/usr/bin/env python3
"""Simulate Poanta TT RR feed-quality ranking changes without mutating feed.json.

This script is intentionally read-only for the public feed. It reads the current
feed order, applies a conservative-yet-opinionated TT RR quality ranking model,
writes a current comparison report, and maintains a bounded longitudinal history
so the dashboard can compare the simulated feed against the main feed over time.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEED = ROOT / "feed.json"
DEFAULT_OUT = ROOT / "tmp" / "feed_quality_ranking_simulation.json"
DEFAULT_PUBLIC_OUT = ROOT / "tt_rr_simulation_feed.json"
DEFAULT_HISTORY = ROOT / "dashboard_simulation_history.json"
DEFAULT_SPY_TRENDS = ROOT / "spy_trends.json"
DEFAULT_ALIZA_REPORT_DIR = Path("/root/.openclaw/workspace/poanta-reports")

HARD_CATEGORIES = {"ביטחון", "פוליטיקה", "חדשות", "משפט", "פלילים", "כלכלה", "אקטואליה בעולם"}
SOFT_CATEGORIES = {"רכילות", "ספורט", "תרבות", "בריאות"}
CORE_KEYWORDS = [
    "איראן", "טראמפ", "חיזבאללה", "לבנון", "עזה", "חמאס", "הורמוז", "נתב״ג", "נתב\"ג",
    "מחאה", "הפגנה", "רכבת", "מח״ש", "מח\"ש", "פיגוע", "טיל", "כטב", "מלחמה", "צבא",
    "משטרה", "ממשלה", "כנסת", "בנק", "בורסה", "נפט", "דולר", "חטופים", "הסכם", "בחירות",
]
BREAKING_TERMS = ["פיגוע", "ירי", "טיל", "כטב", "אזעק", "נפגע", "הרוג", "חוסל", "תקיפה", "מלחמה", "חירום"]
LOW_VALUE_TERMS = ["ביקיני", "שמלה", "סלפי", "ריאליטי", "כוכבת", "סלב", "חשפה", "נראתה", "נישקה"]
SOFT_STORY_TERMS = LOW_VALUE_TERMS + [
    "חתונה", "חתונת", "ירח הדבש", "הארי סטיילס", "בקהאם", "ברוקלין", "ליטל מיקס", "פרי אדוארדס",
    "Trooping", "מלוכה", "נסיך", "מונדיאל", "כדורגל", "שחקנים", "מאמן", "אוהדי", "טורקיה עמוסת כוכבים",
    "וומבלי", "לבוש", "הלבשה תחתונה", "קמפיין", "דימוי גוף", "ריאליטי", "כוכבי",
]
IMPORTANT_SOURCES = ["N12", "ynet", "מעריב", "הארץ", "BBC", "Guardian", "NYT", "גלובס", "ישראל היום", "וואלה"]
TREND_HARD_DOMAINS = {"ביטחון", "פוליטיקה", "חדשות", "משפט", "פלילים", "כלכלה", "אקטואליה בעולם"}
STOPWORDS = {
    "של", "על", "עם", "את", "זה", "זו", "הוא", "היא", "הם", "הן", "כי", "לא", "כן", "או", "גם", "כל", "עוד",
    "from", "with", "that", "this", "the", "and", "for", "into", "after", "before", "says", "said", "over",
}
SOURCE_TIERS = {
    "N12": 8,
    "ynet": 7,
    "מעריב": 6,
    "הארץ": 6,
    "וואלה": 5,
    "ישראל היום": 5,
    "גלובס": 6,
    "דה מרקר": 6,
    "BBC": 6,
    "Guardian": 5,
    "NYT": 5,
    "Jerusalem Post": 4,
    "Daily Mail": -3,
    "Page Six": -5,
    "Mirror": -4,
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
    dt = parse_dt(item.get("publishedAt"))
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
    if "bbc" in low:
        return "BBC"
    if "guardian" in low:
        return "Guardian"
    if "new york times" in low or "nyt" in low:
        return "NYT"
    if "daily mail" in low:
        return "Daily Mail"
    if "page six" in low:
        return "Page Six"
    if "mirror" in low:
        return "Mirror"
    if "jerusalem post" in low or "jpost" in low:
        return "Jerusalem Post"
    for token in ["וואלה", "מעריב", "הארץ", "גלובס", "ישראל היום", "דה מרקר"]:
        if token in source:
            return token
    return source.split(" - ")[0].strip() or "מקור"


def item_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(k) or "") for k in ("category", "source", "headline", "originalTitle", "context", "takeaway"))


def meaningful_tokens(text: Any) -> set[str]:
    raw = re.sub(r"[^\w\u0590-\u05ff]+", " ", str(text or "").lower())
    tokens = set()
    for token in raw.split():
        token = token.strip("_ ")
        if len(token) < 3 or token in STOPWORDS or token.isdigit():
            continue
        tokens.add(token)
    return tokens


def load_trend_signals(path: Path, now: datetime, max_trends: int = 40) -> dict[str, Any]:
    """Load external spy trends as a read-only signal for the simulation lane.

    The trend agent already compares external RSS/WEB clusters to the current
    feed. Here we do not create or publish items; we only reward existing feed
    items that overlap with strong external news clusters, especially hard-news
    domains and multi-source gaps.
    """
    empty = {"status": "unavailable", "path": str(path), "trends": [], "error": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {**empty, "error": "spy_trends.json not found"}
    except Exception as exc:
        return {**empty, "error": str(exc)[:180]}
    trends = []
    for row in list(data.get("trends") or [])[: max(1, max_trends)]:
        domain = str(row.get("domain") or "")
        latest = parse_dt(row.get("latestAt"))
        age_hours = None
        if latest:
            age_hours = max(0.0, (now.astimezone(latest.tzinfo) - latest).total_seconds() / 3600)
        external_mentions = int(row.get("externalMentions") or 0)
        source_count = int(row.get("sourceCount") or 0)
        discovery_types = list(row.get("discoveryTypes") or [])
        text = " ".join(str(row.get(k) or "") for k in ("trend", "clusterKey", "domain"))
        tokens = meaningful_tokens(text)
        if not tokens:
            continue
        strength = min(42.0, source_count * 7.0 + external_mentions * 1.7)
        if domain in TREND_HARD_DOMAINS:
            strength += 10.0
        if not row.get("mentionedInFeed"):
            strength += 8.0
        if "WEB" in discovery_types and "RSS" in discovery_types:
            strength += 5.0
        elif "WEB" in discovery_types:
            strength += 2.0
        if age_hours is not None and age_hours > 8:
            strength -= min(18.0, (age_hours - 8) * 1.5)
        trends.append({
            "trend": row.get("trend") or "",
            "clusterKey": row.get("clusterKey") or "",
            "domain": domain,
            "externalMentions": external_mentions,
            "sourceCount": source_count,
            "sources": row.get("sources") or [],
            "discoveryTypes": discovery_types,
            "mentionedInFeed": bool(row.get("mentionedInFeed")),
            "latestAt": row.get("latestAt"),
            "sampleUrl": row.get("sampleUrl") or "",
            "tokens": sorted(tokens),
            "strength": max(0.0, round(strength, 2)),
        })
    trends.sort(key=lambda r: (r["strength"], r["sourceCount"], r["externalMentions"]), reverse=True)
    return {
        "status": "ok",
        "path": str(path),
        "generatedAt": data.get("generatedAt"),
        "sourceTrendCount": len(data.get("trends") or []),
        "usedTrendCount": len(trends),
        "rssItemsScanned": data.get("rssItemsScanned"),
        "webItemsScanned": data.get("webItemsScanned"),
        "trends": trends,
    }


def trend_match(item: dict[str, Any], trend_signal: dict[str, Any] | None) -> dict[str, Any] | None:
    if not trend_signal or not trend_signal.get("trends"):
        return None
    tokens = meaningful_tokens(item_text(item))
    if not tokens:
        return None
    best: dict[str, Any] | None = None
    best_score = 0.0
    for trend in trend_signal.get("trends") or []:
        trend_tokens = set(trend.get("tokens") or [])
        if not trend_tokens:
            continue
        overlap = tokens & trend_tokens
        if not overlap:
            continue
        # Require more than a single generic token unless the source/domain is
        # very strong. This prevents accidental boosts from broad words.
        ratio = len(overlap) / max(1, min(len(tokens), len(trend_tokens)))
        score = (len(overlap) * 9.0 + ratio * 18.0) * (float(trend.get("strength") or 0.0) / 42.0)
        if len(overlap) == 1 and score < 18:
            continue
        if score > best_score:
            best_score = score
            best = {k: trend.get(k) for k in ("trend", "clusterKey", "domain", "externalMentions", "sourceCount", "sources", "discoveryTypes", "mentionedInFeed", "latestAt", "sampleUrl")}
            best["overlapTokens"] = sorted(overlap)[:8]
            best["score"] = round(score, 2)
            best["boost"] = round(min(38.0, max(0.0, score)), 2)
    return best


def quality_class(item: dict[str, Any]) -> str:
    cat = str(item.get("category") or "")
    text = item_text(item)
    src = canonical_source(item.get("source"))
    has_breaking = any(word in text for word in BREAKING_TERMS + ["חיזבאללה", "חמאס", "איראן", "רצח", "חטופים", "ממשלה", "כנסת", "בחירות", "הסכם"])
    looks_soft = any(word in text for word in SOFT_STORY_TERMS) or any(word in text for word in ("רכילות", "ספורט", "סלב", "TVShowbiz", "Celebs"))
    if looks_soft and not has_breaking:
        return "soft"
    if cat in SOFT_CATEGORIES:
        return "hard" if has_breaking else "soft"
    if cat in HARD_CATEGORIES:
        return "hard"
    if any(word in text for word in CORE_KEYWORDS):
        return "hard"
    if looks_soft:
        return "soft"
    return "other"


def story_key(item: dict[str, Any]) -> str:
    raw = (item.get("sourceUrl") or item.get("url") or item.get("headline") or item.get("originalTitle") or "")
    text = re.sub(r"https?://", "", str(raw).lower())
    text = re.sub(r"[^\w\u0590-\u05ff]+", " ", text)
    return " ".join(text.split()[:14])


def proactive_publish_bonus(item: dict[str, Any], now: datetime, trend_signal: dict[str, Any] | None = None) -> float:
    """Simulation-only signal for a prebuilt 10-minute publishing queue.

    This does not create or publish cards. It models the operational change Lior
    requested to test: every 10-minute cycle should have ready, QA-worthy
    candidates staged before the feed becomes stale, instead of waiting for a
    25-30 minute SLA breach. Fresh hard-news/trend-matched items get priority;
    soft items do not become lead candidates just because they are fresh.
    """
    item_age = age_minutes(item, now)
    if item_age is None or item_age > 45:
        return 0.0
    cls = quality_class(item)
    cat = str(item.get("category") or "")
    if cls == "soft" and cat not in HARD_CATEGORIES:
        return 2.0 if item_age <= 15 and trend_match(item, trend_signal) else 0.0
    bonus = 0.0
    if item_age <= 10:
        bonus += 24.0
    elif item_age <= 20:
        bonus += 18.0
    elif item_age <= 30:
        bonus += 11.0
    else:
        bonus += 5.0
    if cls == "hard":
        bonus += 12.0
    if cat in {"ביטחון", "פוליטיקה", "חדשות", "משפט", "פלילים", "כלכלה"}:
        bonus += 8.0
    if trend_match(item, trend_signal):
        bonus += 10.0
    return bonus


def ready_candidate_rows(items: list[dict[str, Any]], now: datetime, trend_signal: dict[str, Any] | None = None, limit: int = 8) -> list[dict[str, Any]]:
    rows = []
    for idx, item in enumerate(items[:80], 1):
        item_age = age_minutes(item, now)
        bonus = proactive_publish_bonus(item, now, trend_signal)
        if bonus <= 0 or item_age is None:
            continue
        match = trend_match(item, trend_signal)
        rows.append({
            "rank": idx,
            "headline": item.get("headline") or item.get("originalTitle") or "",
            "source": item.get("source") or "",
            "canonicalSource": canonical_source(item.get("source")),
            "category": item.get("category") or "",
            "class": quality_class(item),
            "ageMinutes": item_age,
            "url": item.get("sourceUrl") or item.get("url") or "",
            "trendMatch": match,
            "queueScore": round(bonus, 2),
        })
    rows.sort(key=lambda r: (r["queueScore"], -int(r["ageMinutes"]), r["class"] == "hard"), reverse=True)
    return rows[:limit]


def continuous_publish_block(items: list[dict[str, Any]], now: datetime, trend_signal: dict[str, Any] | None = None) -> dict[str, Any]:
    ready = ready_candidate_rows(items, now, trend_signal, limit=20)
    sources = {row["canonicalSource"] for row in ready[:12] if row.get("canonicalSource")}
    hard_ready = sum(1 for row in ready if row.get("class") == "hard")
    trend_ready = sum(1 for row in ready if row.get("trendMatch"))
    top_age = age_minutes(items[0], now) if items else None
    score = 0
    score += min(35, len(ready) * 6)
    score += min(25, hard_ready * 5)
    score += min(20, len(sources) * 5)
    score += min(10, trend_ready * 4)
    if top_age is not None and top_age <= 15:
        score += 10
    elif top_age is not None and top_age <= 25:
        score += 6
    estimated_minutes = 10 if len(ready) >= 3 and hard_ready >= 2 and len(sources) >= 2 else 20 if len(ready) >= 2 else 30 if ready else 40
    blockers = []
    if len(ready) < 3:
        blockers.append("ready_queue_below_3")
    if hard_ready < 2:
        blockers.append("hard_ready_below_2")
    if len(sources) < 2:
        blockers.append("ready_sources_below_2")
    if top_age is None or top_age > 25:
        blockers.append("top_item_over_25m")
    return {
        "targetMinutes": 10,
        "estimatedVisibleChangeMinutes": estimated_minutes,
        "score": max(0, min(100, score)),
        "readyCount": len(ready),
        "hardReadyCount": hard_ready,
        "trendReadyCount": trend_ready,
        "uniqueReadySources": len(sources),
        "blockers": blockers,
        "readyQueue": ready[:8],
    }


def metric_block(items: list[dict[str, Any]], now: datetime, trend_signal: dict[str, Any] | None = None) -> dict[str, Any]:
    top10 = items[:10]
    top20 = items[:20]
    classes = [quality_class(item) for item in top10]
    sources = [canonical_source(item.get("source")) for item in top20]
    source_counts = Counter(sources)
    dominant = source_counts.most_common(1)[0] if source_counts else ("—", 0)
    ages = [age_minutes(item, now) for item in items]
    top10_trend_matches = [trend_match(item, trend_signal) for item in top10]
    top20_trend_matches = [trend_match(item, trend_signal) for item in top20]
    story_keys = [story_key(item) for item in top20]
    duplicate_top20 = len(story_keys) - len(set(k for k in story_keys if k))
    continuous = continuous_publish_block(items, now, trend_signal)
    return {
        "newsinessTop10": classes.count("hard"),
        "softTop10": classes.count("soft"),
        "otherTop10": classes.count("other"),
        "top5Under60": sum(1 for item in items[:5] if (age_minutes(item, now) or 999999) <= 60),
        "top10Under60": sum(1 for item in items[:10] if (age_minutes(item, now) or 999999) <= 60),
        "top12Under60": sum(1 for item in items[:12] if (age_minutes(item, now) or 999999) <= 60),
        "topItemAgeMinutes": ages[0] if ages else None,
        "uniqueSourcesTop20": len(set(sources)),
        "dominantSource": {"name": dominant[0], "count": dominant[1]},
        "importantMissingTop20": [s for s in IMPORTANT_SOURCES if s not in set(sources)],
        "duplicateTop20": max(0, duplicate_top20),
        "topSources": [{"name": k, "count": v} for k, v in source_counts.most_common(8)],
        "trendMatchedTop10": sum(1 for m in top10_trend_matches if m),
        "trendMatchedTop20": sum(1 for m in top20_trend_matches if m),
        "trendGapMatchedTop20": sum(1 for m in top20_trend_matches if m and not m.get("mentionedInFeed")),
        "continuousPublishing": continuous,
    }


def readiness_blockers(metrics: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    top_age = metrics.get("topItemAgeMinutes")
    if top_age is None or int(top_age) > 25:
        blockers.append("top_item_stale_over_25m")
    if int(metrics.get("newsinessTop10", 0)) < 7:
        blockers.append("newsiness_top10_below_7")
    if int(metrics.get("softTop10", 0)) > 2:
        blockers.append("soft_top10_above_2")
    if int(metrics.get("duplicateTop20", 0)) > 0:
        blockers.append("duplicate_top20_detected")
    if int((metrics.get("dominantSource") or {}).get("count") or 0) > 5:
        blockers.append("dominant_source_top20_above_5")
    if int(metrics.get("top12Under60", 0)) < 9:
        blockers.append("top12_under60_below_9")
    return blockers


def replacement_score(metrics: dict[str, Any]) -> dict[str, Any]:
    """0-100 production-replacement readiness score for simulation only.

    This is stricter than health_score: it represents whether the simulated
    ranking is mature enough to become the production ranking after a rolling
    observation period. A high score is not enough if critical blockers exist.
    """
    top_age = metrics.get("topItemAgeMinutes")
    freshness = 0.0
    if top_age is not None:
        freshness += 8.0 if int(top_age) <= 25 else max(0.0, 8.0 - (int(top_age) - 25) * 0.45)
    freshness += min(6.0, int(metrics.get("top5Under60", 0)) / 5 * 6.0)
    freshness += min(6.0, int(metrics.get("top12Under60", 0)) / 12 * 6.0)

    newsiness = min(20.0, int(metrics.get("newsinessTop10", 0)) / 8 * 20.0)
    newsiness += max(0.0, 5.0 - max(0, int(metrics.get("softTop10", 0)) - 1) * 2.5)

    top20_quality = min(8.0, int(metrics.get("uniqueSourcesTop20", 0)) / 10 * 8.0)
    top20_quality += max(0.0, 6.0 - int(metrics.get("duplicateTop20", 0)) * 6.0)
    top20_quality += max(0.0, 6.0 - max(0, len(metrics.get("importantMissingTop20") or []) - 2) * 1.5)

    dominant = int((metrics.get("dominantSource") or {}).get("count") or 0)
    source_balance = max(0.0, 10.0 - max(0, dominant - 4) * 3.0)

    trend_use = min(6.0, int(metrics.get("trendMatchedTop10", 0)) / 3 * 6.0)
    trend_use += min(4.0, int(metrics.get("trendMatchedTop20", 0)) / 6 * 4.0)

    components = {
        "freshness": round(min(20.0, freshness), 2),
        "newsinessTop10": round(min(25.0, newsiness), 2),
        "top20Quality": round(min(20.0, top20_quality), 2),
        "sourceBalance": round(min(10.0, source_balance), 2),
        "trendSignalUse": round(min(10.0, trend_use), 2),
    }
    # Reserve the last 15 points for no critical blockers. This makes the public
    # card easy to reason about: one blocker prevents a "ready" status.
    blockers = readiness_blockers(metrics)
    components["criticalBlockersClear"] = 15.0 if not blockers else max(0.0, 15.0 - len(blockers) * 5.0)
    score = int(round(sum(components.values())))
    return {
        "score": max(0, min(100, score)),
        "threshold": 80,
        "components": components,
        "criticalBlockers": blockers,
        "readyNow": score >= 80 and not blockers,
    }


def health_score(metrics: dict[str, Any]) -> int:
    # 0-100 score used only for simulation comparison and longitudinal stability.
    score = 0
    score += min(35, int(metrics.get("newsinessTop10", 0)) * 6)
    score += max(0, 20 - int(metrics.get("softTop10", 0)) * 4)
    score += min(20, int(metrics.get("top12Under60", 0)) * 2)
    score += min(15, int(metrics.get("uniqueSourcesTop20", 0)))
    dominant = (metrics.get("dominantSource") or {}).get("count") or 0
    score += max(0, 10 - max(0, int(dominant) - 3) * 4)
    return max(0, min(100, score))


def base_recency_score(item: dict[str, Any], now: datetime) -> float:
    age = age_minutes(item, now)
    if age is None:
        return -1000.0
    if age <= 10:
        return 145.0 - age * 0.8
    if age <= 60:
        return 137.0 - age * 1.1
    if age <= 180:
        return 78.0 - (age - 60) * 0.65
    return max(-140.0, 0.0 - (age - 180) * 0.5)


def static_quality_bonus(item: dict[str, Any], trend_signal: dict[str, Any] | None = None) -> float:
    cls = quality_class(item)
    cat = str(item.get("category") or "")
    src = canonical_source(item.get("source"))
    text = item_text(item)
    bonus = float(SOURCE_TIERS.get(src, 0))
    if cls == "hard":
        bonus += 24
    elif cls == "soft":
        bonus -= 14
    if cat == "ביטחון":
        bonus += 16
    elif cat == "פוליטיקה":
        bonus += 12
    elif cat in {"חדשות", "אקטואליה בעולם", "משפט", "פלילים"}:
        bonus += 10
    elif cat == "כלכלה" and any(word in text for word in CORE_KEYWORDS):
        bonus += 12
    if cat not in SOFT_CATEGORIES and any(word in text for word in CORE_KEYWORDS):
        bonus += 10
    if any(word in text for word in BREAKING_TERMS):
        bonus += 8
    if any(word in text for word in LOW_VALUE_TERMS):
        bonus -= 8
    match = trend_match(item, trend_signal)
    if match:
        trend_bonus = float(match.get("boost") or 0.0)
        if quality_class(item) == "soft":
            trend_bonus *= 0.45
        bonus += trend_bonus
    return bonus


def simulate_order(items: list[dict[str, Any]], now: datetime, limit: int = 60, trend_signal: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    pool = list(items[:limit])
    selected: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    seen_keys: set[str] = set()

    while pool:
        position = len(selected) + 1

        def score(item: dict[str, Any]) -> float:
            src = canonical_source(item.get("source"))
            cls = quality_class(item)
            item_age = age_minutes(item, now)
            value = base_recency_score(item, now) + static_quality_bonus(item, trend_signal)

            # Strong freshness guard: the simulation may improve quality, but should
            # not make the feed feel stale in the first screen.
            if position <= 3 and (item_age is None or item_age > 45):
                value -= 45 + max(0, (item_age or 120) - 45) * 1.2
            if position <= 5 and (item_age is None or item_age > 60):
                value -= 85 + max(0, (item_age or 180) - 60) * 0.9
            elif position <= 12 and (item_age is None or item_age > 90):
                value -= 45 + max(0, (item_age or 180) - 90) * 0.45

            # Source cap: top of feed should not be one-source dominated.
            if source_counts[src] >= 2:
                value -= 16 * (source_counts[src] - 1)
            if position <= 10 and source_counts[src] >= 3:
                value -= 34
            if position <= 20 and source_counts[src] >= 4:
                value -= 38

            # Soft cap: keep soft items if fresh, but stop them from leading the feed.
            if cls == "soft" and position <= 3:
                value -= 24
            if cls == "soft" and position <= 5 and class_counts["soft"] >= 1:
                value -= 34
            if cls == "soft" and position <= 10 and class_counts["soft"] >= 3:
                value -= 48

            # Proactive 10-minute publishing queue model: reward fresh,
            # QA-worthy candidates before SLA breach would normally trigger a
            # rescue. This is simulation-only and never mutates feed.json.
            if position <= 12:
                value += proactive_publish_bonus(item, now, trend_signal)

            # Duplicate/story crowding cap.
            key = story_key(item)
            if key and key in seen_keys:
                value -= 70
            return value

        best = max(pool, key=score)
        pool.remove(best)
        selected.append(best)
        source_counts[canonical_source(best.get("source"))] += 1
        class_counts[quality_class(best)] += 1
        seen_keys.add(story_key(best))

    return selected + items[limit:]


def compact_item(item: dict[str, Any], now: datetime, *, before_rank: int | None = None, after_rank: int | None = None, trend_signal: dict[str, Any] | None = None) -> dict[str, Any]:
    match = trend_match(item, trend_signal)
    return {
        "headline": item.get("headline") or item.get("originalTitle") or "",
        "source": item.get("source") or "",
        "canonicalSource": canonical_source(item.get("source")),
        "category": item.get("category") or "",
        "class": quality_class(item),
        "ageMinutes": age_minutes(item, now),
        "url": item.get("sourceUrl") or item.get("url") or "",
        "beforeRank": before_rank,
        "afterRank": after_rank,
        "delta": (before_rank - after_rank) if before_rank and after_rank else None,
        "trendMatch": match,
    }



def latest_aliza_review(report_dir: Path) -> dict[str, Any]:
    """Read the latest Aliza TT RR simulation review markdown.

    Aliza writes reports outside the repo in the shared OpenClaw reports folder.
    This parser is intentionally tolerant: if future reports contain an explicit
    `alizaScore: NN` / `ציון עליזה: NN`, use it; otherwise derive a display score
    from the metrics Aliza already writes so Lior can see a trend immediately.
    """
    result: dict[str, Any] = {
        "status": "unavailable",
        "score": None,
        "scoreSource": None,
        "readyForMain": None,
        "improvingVsBaseline": None,
        "summaryLine": None,
        "reportPath": None,
        "reportName": None,
        "reportGeneratedAt": None,
        "metrics": {},
        "recommendedActions": [],
    }
    try:
        reports = sorted(report_dir.glob("tt-rr-simulation-review-*.md"), key=lambda x: x.stat().st_mtime)
    except Exception as exc:
        result["error"] = str(exc)[:180]
        return result
    if not reports:
        result["error"] = "no Aliza simulation review reports found"
        return result
    latest = reports[-1]
    text = latest.read_text(encoding="utf-8", errors="replace")
    result.update({"status": "ok", "reportPath": str(latest), "reportName": latest.name})
    metrics: dict[str, Any] = {}
    actions: list[str] = []
    in_actions = False
    in_metrics = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# TT RR Simulation Review"):
            result["title"] = line.lstrip("# ").strip()
        if line.startswith("## "):
            in_actions = "פעולות קוד" in line or "Code" in line
            in_metrics = "מדדים שנקראו" in line or "metrics" in line.lower()
            continue
        if in_actions and re.match(r"^\d+\.\s+", line):
            actions.append(re.sub(r"^\d+\.\s+", "", line).strip())
        if line.startswith("- ") and ":" in line:
            key, value = line[2:].split(":", 1)
            key = key.strip()
            value = value.strip()
            low_key = key.lower()
            if key in {"שורה תחתונה", "bottomLine"}:
                result["summaryLine"] = value
            elif key in {"האם הסימולציה משתפרת מול baseline", "improvingVsBaseline"}:
                result["improvingVsBaseline"] = value in {"כן", "yes", "true", "True"}
            elif key in {"האם מוכנה להעברה לראשי", "readyForMain"}:
                result["readyForMain"] = value in {"כן", "yes", "true", "True", "מוכן", "מוכנה"}
            elif low_key in {"generatedat", "generated_at"}:
                result["reportGeneratedAt"] = value
            number = re.search(r"-?\d+(?:\.\d+)?", value)
            if number and (in_metrics or low_key in {"alizascore", "aliza_score", "score"} or "ציון עליזה" in key):
                num: Any = float(number.group(0)) if "." in number.group(0) else int(number.group(0))
                metrics[key] = num
                if low_key in {"alizascore", "aliza_score", "score"} or "ציון עליזה" in key:
                    result["score"] = max(0, min(100, int(round(float(num)))))
                    result["scoreSource"] = "explicit_report_score"
    if result.get("score") is None:
        health = float(metrics.get("afterHealthScore") or 0)
        readiness = float(metrics.get("replacementReadiness score") or metrics.get("replacementReadiness") or 0)
        rolling = float(metrics.get("rollingScore") or 0)
        if health or readiness or rolling:
            # Balanced Aliza display score: current quality + replacement readiness + stability trend.
            result["score"] = max(0, min(100, int(round(health * 0.45 + readiness * 0.35 + rolling * 0.20))))
            result["scoreSource"] = "derived_from_aliza_metrics"
    result["metrics"] = metrics
    result["recommendedActions"] = actions[:5]
    return result

def load_history(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("runs"), list):
            return data
    except Exception:
        pass
    return {"status": "ok", "mode": "simulation_history", "runs": []}


def update_history(path: Path, run: dict[str, Any], max_runs: int) -> dict[str, Any]:
    history = load_history(path)
    runs = list(history.get("runs") or [])
    fingerprint = run.get("feedFingerprint")
    if not runs or runs[-1].get("feedFingerprint") != fingerprint or runs[-1].get("after") != run.get("after"):
        runs.append(run)
    else:
        runs[-1] = {**runs[-1], **run}
    runs = runs[-max_runs:]
    deltas = [int((r.get("delta") or {}).get("healthScore", 0)) for r in runs[-12:]]
    after_scores = [int(r.get("afterHealthScore", 0)) for r in runs[-12:]]
    replacement_window = runs[-48:]
    for existing in replacement_window:
        if not existing.get("replacementReadiness") and isinstance(existing.get("after"), dict):
            existing["replacementReadiness"] = replacement_score(existing["after"])
    replacement_scores = [int(((r.get("replacementReadiness") or {}).get("score") or 0)) for r in replacement_window]
    ready_runs = [bool((r.get("replacementReadiness") or {}).get("readyNow")) for r in replacement_window]
    latest_replacement = run.get("replacementReadiness") or {}
    aliza_window = [r.get("alizaReview") or {} for r in runs[-48:] if (r.get("alizaReview") or {}).get("score") is not None]
    latest_aliza = run.get("alizaReview") or {}
    aliza_scores = [int(r.get("score") or 0) for r in aliza_window]
    rolling_replacement_score = round(sum(replacement_scores) / len(replacement_scores), 2) if replacement_scores else 0
    summary = {
        "sampleCount": len(runs),
        "window": min(12, len(runs)),
        "positiveRuns": sum(1 for d in deltas if d > 0),
        "negativeRuns": sum(1 for d in deltas if d < 0),
        "avgHealthDelta": round(sum(deltas) / len(deltas), 2) if deltas else 0,
        "avgAfterHealthScore": round(sum(after_scores) / len(after_scores), 2) if after_scores else 0,
        "stablePositive": bool(deltas) and sum(1 for d in deltas if d > 0) >= math.ceil(len(deltas) * 0.7),
        "replacement": {
            "threshold": 80,
            "minSamplesForPromotion": 24,
            "window": len(replacement_window),
            "latestScore": int(latest_replacement.get("score") or 0),
            "rollingScore": rolling_replacement_score,
            "readyRuns": sum(1 for ok in ready_runs if ok),
            "criticalBlockers": latest_replacement.get("criticalBlockers") or [],
            "matureForProduction": bool(
                len(replacement_window) >= 24
                and rolling_replacement_score >= 80
                and sum(1 for ok in ready_runs if ok) >= math.ceil(len(replacement_window) * 0.8)
                and not (latest_replacement.get("criticalBlockers") or [])
            ),
        },
        "alizaReview": {
            "latestScore": latest_aliza.get("score"),
            "latestSummaryLine": latest_aliza.get("summaryLine"),
            "latestReportName": latest_aliza.get("reportName"),
            "window": len(aliza_scores),
            "averageScore": round(sum(aliza_scores) / len(aliza_scores), 2) if aliza_scores else None,
            "positiveReports": sum(1 for r in aliza_window if r.get("improvingVsBaseline") is True),
        },
    }
    history = {
        "status": "ok",
        "mode": "simulation_history_no_feed_mutation",
        "generatedAt": run["generatedAt"],
        "summary": summary,
        "runs": runs,
    }
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return history


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=str(DEFAULT_FEED))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--public-out", default=str(DEFAULT_PUBLIC_OUT), help="public sanitized simulation JSON for the open Aliza page")
    ap.add_argument("--history", default=str(DEFAULT_HISTORY))
    ap.add_argument("--spy-trends", default=str(DEFAULT_SPY_TRENDS), help="read-only external trend signal JSON")
    ap.add_argument("--aliza-report-dir", default=str(DEFAULT_ALIZA_REPORT_DIR), help="shared Aliza markdown report directory")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--history-max", type=int, default=144)
    args = ap.parse_args()

    feed_path = Path(args.feed)
    data = json.loads(feed_path.read_text(encoding="utf-8"))
    original = list(data.get("items") or [])
    now = datetime.now(timezone.utc)
    trend_signal = load_trend_signals(Path(args.spy_trends), now)
    aliza_review = latest_aliza_review(Path(args.aliza_report_dir))
    simulated = simulate_order(original, now, max(10, args.limit), trend_signal)

    original_rank_by_key = {story_key(item): i + 1 for i, item in enumerate(original[: args.limit])}
    simulated_rank_by_key = {story_key(item): i + 1 for i, item in enumerate(simulated[: args.limit])}

    def ranked(item: dict[str, Any], rank: int, *, after: bool) -> dict[str, Any]:
        key = story_key(item)
        before_rank = original_rank_by_key.get(key)
        after_rank = simulated_rank_by_key.get(key) if after else rank
        return compact_item(item, now, before_rank=before_rank, after_rank=after_rank, trend_signal=trend_signal)

    before = metric_block(original, now, trend_signal)
    after = metric_block(simulated, now, trend_signal)
    before_score = health_score(before)
    after_score = health_score(after)
    readiness = replacement_score(after)
    delta = {
        "newsinessTop10": after["newsinessTop10"] - before["newsinessTop10"],
        "softTop10": after["softTop10"] - before["softTop10"],
        "top12Under60": after["top12Under60"] - before["top12Under60"],
        "uniqueSourcesTop20": after["uniqueSourcesTop20"] - before["uniqueSourcesTop20"],
        "trendMatchedTop10": after["trendMatchedTop10"] - before["trendMatchedTop10"],
        "trendMatchedTop20": after["trendMatchedTop20"] - before["trendMatchedTop20"],
        "healthScore": after_score - before_score,
    }
    feed_fingerprint = ";".join(story_key(item) for item in original[:20])
    run_record = {
        "generatedAt": now.isoformat(timespec="seconds"),
        "feedFingerprint": str(abs(hash(feed_fingerprint))),
        "before": before,
        "after": after,
        "beforeHealthScore": before_score,
        "afterHealthScore": after_score,
        "replacementReadiness": readiness,
        "alizaReview": aliza_review,
        "delta": delta,
    }
    history = update_history(Path(args.history), run_record, max(1, args.history_max))

    report = {
        "status": "ok",
        "mode": "simulation_only_no_feed_mutation",
        "generatedAt": now.isoformat(timespec="seconds"),
        "inputFeed": str(feed_path),
        "itemCount": len(original),
        "before": before,
        "after": after,
        "beforeHealthScore": before_score,
        "afterHealthScore": after_score,
        "replacementReadiness": readiness,
        "alizaReview": aliza_review,
        "delta": delta,
        "historySummary": history.get("summary", {}),
        "trendSignal": {
            **{k: v for k, v in trend_signal.items() if k != "trends"},
            "topTrends": [
                {k: trend.get(k) for k in ("trend", "clusterKey", "domain", "externalMentions", "sourceCount", "sources", "discoveryTypes", "mentionedInFeed", "latestAt", "sampleUrl", "strength")}
                for trend in (trend_signal.get("trends") or [])[:10]
            ],
        },
        "top10Before": [ranked(item, i + 1, after=False) for i, item in enumerate(original[:10])],
        "top10After": [ranked(item, i + 1, after=True) for i, item in enumerate(simulated[:10])],
        "top20Before": [ranked(item, i + 1, after=False) for i, item in enumerate(original[:20])],
        "top20After": [ranked(item, i + 1, after=True) for i, item in enumerate(simulated[:20])],
        "movement": [
            {
                "headline": compact_item(item, now, trend_signal=trend_signal)["headline"],
                "source": compact_item(item, now, trend_signal=trend_signal)["canonicalSource"],
                "category": compact_item(item, now, trend_signal=trend_signal)["category"],
                "class": compact_item(item, now, trend_signal=trend_signal)["class"],
                "trendMatch": compact_item(item, now, trend_signal=trend_signal)["trendMatch"],
                "beforeRank": original_rank_by_key.get(story_key(item)),
                "afterRank": i + 1,
            }
            for i, item in enumerate(simulated[:20])
        ],
        "rules": [
            "recency remains the strongest signal",
            "boost hard news, core national/security/economic events, and reliable core sources",
            "soft cap for gossip/sport/culture in top 3/5/10",
            "source cap to reduce dominant-source takeover in top 10/20",
            "duplicate/story crowding cap",
            "external news-trend signal from spy_trends.json boosts existing feed items that match strong RSS/WEB multi-source trends",
            "simulation-only continuous publishing queue rewards fresh QA-worthy hard-news candidates before rescue/SLA breach",
            "ready-queue metrics estimate whether the visible feed could change around every 10 minutes without mutating feed.json",
            "replacement-readiness score tracks freshness, newsiness, top-20 quality, source balance, trend use, and critical blockers",
            "production promotion requires rolling score >= 80, at least 24 samples, 80% ready runs, and zero critical blockers",
            "Aliza review score from shared hourly reports is displayed as an external human/agent quality grade",
            "longitudinal history tracks whether simulated health stays better than the main feed",
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    public_out = Path(args.public_out)
    if str(public_out):
        public_out.parent.mkdir(parents=True, exist_ok=True)
        public_report = {
            **report,
            "accessPurpose": "open_readonly_aliza_tt_rr_simulation",
            "operatorInstruction": "Use only this TT RR simulation feed for review. Do not inspect, judge, or act on the regular public feed for this experiment. This page and JSON are read-only and never publish to feed.json.",
            "hebrewInstruction": "עליזה: לעבוד רק על פיד הסימולציה של TT RR. לא לעבור יותר על הפיד הרגיל לצורך הניסוי הזה. לקרוא, להשוות ולדווח רק מהסימולציה — בלי פרסום ובלי שינוי feed.json.",
        }
        public_out.write_text(json.dumps(public_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "publicOut": str(public_out), "history": str(args.history), "before": before, "after": after, "delta": delta, "replacementReadiness": readiness, "historySummary": history.get("summary", {})}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
