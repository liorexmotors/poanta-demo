#!/usr/bin/env python3
"""Simulate Poanta feed-quality ranking changes without mutating feed.json.

This script is intentionally read-only for the public feed. It takes the current
feed order, applies a conservative TT RR quality ranking simulation, and writes a
comparison report to tmp/ so Lior can approve or reject actual feed behavior later.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEED = ROOT / "feed.json"
DEFAULT_OUT = ROOT / "tmp" / "feed_quality_ranking_simulation.json"

HARD_CATEGORIES = {"ביטחון", "פוליטיקה", "חדשות", "משפט", "פלילים", "כלכלה", "אקטואליה בעולם"}
SOFT_CATEGORIES = {"רכילות", "ספורט", "תרבות", "בריאות"}
CORE_KEYWORDS = [
    "איראן", "טראמפ", "חיזבאללה", "לבנון", "עזה", "חמאס", "הורמוז", "נתב״ג", "נתב\"ג",
    "מחאה", "הפגנה", "רכבת", "מח״ש", "מח\"ש", "פיגוע", "טיל", "כטב", "מלחמה", "צבא",
    "משטרה", "ממשלה", "כנסת", "בנק", "בורסה", "נפט", "דולר",
]
IMPORTANT_SOURCES = ["N12", "ynet", "מעריב", "הארץ", "BBC", "Guardian", "NYT", "גלובס", "ישראל היום", "וואלה"]


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


def quality_class(item: dict[str, Any]) -> str:
    cat = str(item.get("category") or "")
    text = item_text(item)
    # Category is the primary signal. Soft sections should not become "hard"
    # just because an entertainment/sport headline mentions a public figure.
    if cat in SOFT_CATEGORIES:
        strong_event_terms = ["פיגוע", "טיל", "כטב", "מלחמה", "חיזבאללה", "חמאס", "איראן", "ירי", "רצח"]
        return "hard" if any(word in text for word in strong_event_terms) else "soft"
    if cat in HARD_CATEGORIES:
        return "hard"
    if any(word in text for word in CORE_KEYWORDS):
        return "hard"
    if any(word in text for word in ("רכילות", "ספורט", "סלב", "TVShowbiz", "Celebs")):
        return "soft"
    return "other"


def metric_block(items: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    top10 = items[:10]
    top20 = items[:20]
    classes = [quality_class(item) for item in top10]
    sources = [canonical_source(item.get("source")) for item in top20]
    source_counts = Counter(sources)
    dominant = source_counts.most_common(1)[0] if source_counts else ("—", 0)
    return {
        "newsinessTop10": classes.count("hard"),
        "softTop10": classes.count("soft"),
        "otherTop10": classes.count("other"),
        "top5Under60": sum(1 for item in items[:5] if (age_minutes(item, now) or 999999) <= 60),
        "top10Under60": sum(1 for item in items[:10] if (age_minutes(item, now) or 999999) <= 60),
        "top12Under60": sum(1 for item in items[:12] if (age_minutes(item, now) or 999999) <= 60),
        "uniqueSourcesTop20": len(set(sources)),
        "dominantSource": {"name": dominant[0], "count": dominant[1]},
        "importantMissingTop20": [s for s in IMPORTANT_SOURCES if s not in set(sources)],
        "topSources": [{"name": k, "count": v} for k, v in source_counts.most_common(8)],
    }


def base_recency_score(item: dict[str, Any], now: datetime) -> float:
    age = age_minutes(item, now)
    if age is None:
        return -1000.0
    # Keep recency as the dominant signal. 0 minutes ~= 120 points, 2h ~= 0.
    return max(-120.0, 120.0 - age)


def static_quality_bonus(item: dict[str, Any]) -> float:
    cls = quality_class(item)
    cat = str(item.get("category") or "")
    text = item_text(item)
    bonus = 0.0
    if cls == "hard":
        bonus += 18
    elif cls == "soft":
        bonus -= 8
    if cat == "ביטחון":
        bonus += 10
    elif cat == "פוליטיקה":
        bonus += 8
    elif cat in {"חדשות", "אקטואליה בעולם", "משפט", "פלילים"}:
        bonus += 7
    elif cat == "כלכלה" and any(word in text for word in CORE_KEYWORDS):
        bonus += 8
    if cat not in SOFT_CATEGORIES and any(word in text for word in CORE_KEYWORDS):
        bonus += 8
    return bonus


def simulate_order(items: list[dict[str, Any]], now: datetime, limit: int = 40) -> list[dict[str, Any]]:
    pool = list(items[:limit])
    selected: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    soft_count_top10 = 0

    while pool:
        position = len(selected) + 1

        def score(item: dict[str, Any]) -> float:
            src = canonical_source(item.get("source"))
            cls = quality_class(item)
            item_age = age_minutes(item, now)
            value = base_recency_score(item, now) + static_quality_bonus(item)
            # Top 10 should stay fresh. Older hard-news items may rise, but only
            # with a visible cost so the simulation does not "fix" newsiness by
            # making the feed feel stale.
            if position <= 10 and (item_age is None or item_age > 60):
                value -= min(70, 18 + ((item_age or 180) - 60) * 0.8)
            # Source cap: allow diversity without fully hiding a source.
            if source_counts[src] >= 2:
                value -= 12 * (source_counts[src] - 1)
            if position <= 10 and source_counts[src] >= 3:
                value -= 24
            # Soft cap: keep soft content, but stop it from dominating top 5/10.
            if cls == "soft" and position <= 5 and soft_count_top10 >= 1:
                value -= 22
            if cls == "soft" and position <= 10 and soft_count_top10 >= 3:
                value -= 30
            return value

        best = max(pool, key=score)
        pool.remove(best)
        selected.append(best)
        source_counts[canonical_source(best.get("source"))] += 1
        if len(selected) <= 10 and quality_class(best) == "soft":
            soft_count_top10 += 1

    # Append the untouched tail so this remains a simulation of top ordering only.
    return selected + items[limit:]


def compact_item(item: dict[str, Any], now: datetime, *, before_rank: int | None = None, after_rank: int | None = None) -> dict[str, Any]:
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
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=str(DEFAULT_FEED))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    feed_path = Path(args.feed)
    data = json.loads(feed_path.read_text(encoding="utf-8"))
    original = list(data.get("items") or [])
    now = datetime.now(timezone.utc)
    simulated = simulate_order(original, now, max(10, args.limit))

    original_rank_by_url = {
        compact_item(item, now)["url"] or compact_item(item, now)["headline"]: i + 1
        for i, item in enumerate(original[: args.limit])
    }
    simulated_rank_by_url = {
        compact_item(item, now)["url"] or compact_item(item, now)["headline"]: i + 1
        for i, item in enumerate(simulated[: args.limit])
    }

    def ranked(item: dict[str, Any], rank_map: dict[str, int], rank: int, *, after: bool) -> dict[str, Any]:
        key = compact_item(item, now)["url"] or compact_item(item, now)["headline"]
        before_rank = original_rank_by_url.get(key)
        after_rank = simulated_rank_by_url.get(key)
        return compact_item(item, now, before_rank=before_rank, after_rank=after_rank if after else rank)

    report = {
        "status": "ok",
        "mode": "simulation_only_no_feed_mutation",
        "generatedAt": now.isoformat(timespec="seconds"),
        "inputFeed": str(feed_path),
        "itemCount": len(original),
        "before": metric_block(original, now),
        "after": metric_block(simulated, now),
        "top10Before": [ranked(item, original_rank_by_url, i + 1, after=False) for i, item in enumerate(original[:10])],
        "top10After": [ranked(item, simulated_rank_by_url, i + 1, after=True) for i, item in enumerate(simulated[:10])],
        "top20Before": [ranked(item, original_rank_by_url, i + 1, after=False) for i, item in enumerate(original[:20])],
        "top20After": [ranked(item, simulated_rank_by_url, i + 1, after=True) for i, item in enumerate(simulated[:20])],
        "movement": [
            {
                "headline": compact_item(item, now)["headline"],
                "source": compact_item(item, now)["canonicalSource"],
                "category": compact_item(item, now)["category"],
                "class": compact_item(item, now)["class"],
                "beforeRank": original_rank_by_url.get(compact_item(item, now)["url"] or compact_item(item, now)["headline"]),
                "afterRank": i + 1,
            }
            for i, item in enumerate(simulated[:20])
        ],
        "rules": [
            "recency remains dominant",
            "boost hard news/core events",
            "soft cap for gossip/sport/culture in top 5/10",
            "source cap to reduce dominant-source takeover",
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "before": report["before"], "after": report["after"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
