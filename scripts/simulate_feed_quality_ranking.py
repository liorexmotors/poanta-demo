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

HARD_CATEGORIES = {"ביטחון", "פוליטיקה", "חדשות", "משפט", "פלילים", "כלכלה", "אקטואליה בעולם"}
SOFT_CATEGORIES = {"רכילות", "ספורט", "תרבות", "בריאות"}
CORE_KEYWORDS = [
    "איראן", "טראמפ", "חיזבאללה", "לבנון", "עזה", "חמאס", "הורמוז", "נתב״ג", "נתב\"ג",
    "מחאה", "הפגנה", "רכבת", "מח״ש", "מח\"ש", "פיגוע", "טיל", "כטב", "מלחמה", "צבא",
    "משטרה", "ממשלה", "כנסת", "בנק", "בורסה", "נפט", "דולר", "חטופים", "הסכם", "בחירות",
]
BREAKING_TERMS = ["פיגוע", "ירי", "טיל", "כטב", "אזעק", "נפגע", "הרוג", "חוסל", "תקיפה", "מלחמה", "חירום"]
LOW_VALUE_TERMS = ["ביקיני", "שמלה", "סלפי", "ריאליטי", "כוכבת", "סלב", "חשפה", "נראתה", "נישקה"]
IMPORTANT_SOURCES = ["N12", "ynet", "מעריב", "הארץ", "BBC", "Guardian", "NYT", "גלובס", "ישראל היום", "וואלה"]
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


def quality_class(item: dict[str, Any]) -> str:
    cat = str(item.get("category") or "")
    text = item_text(item)
    if cat in SOFT_CATEGORIES:
        return "hard" if any(word in text for word in BREAKING_TERMS + ["חיזבאללה", "חמאס", "איראן", "רצח"]) else "soft"
    if cat in HARD_CATEGORIES:
        return "hard"
    if any(word in text for word in CORE_KEYWORDS):
        return "hard"
    if any(word in text for word in ("רכילות", "ספורט", "סלב", "TVShowbiz", "Celebs")):
        return "soft"
    return "other"


def story_key(item: dict[str, Any]) -> str:
    raw = (item.get("sourceUrl") or item.get("url") or item.get("headline") or item.get("originalTitle") or "")
    text = re.sub(r"https?://", "", str(raw).lower())
    text = re.sub(r"[^\w\u0590-\u05ff]+", " ", text)
    return " ".join(text.split()[:14])


def metric_block(items: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    top10 = items[:10]
    top20 = items[:20]
    classes = [quality_class(item) for item in top10]
    sources = [canonical_source(item.get("source")) for item in top20]
    source_counts = Counter(sources)
    dominant = source_counts.most_common(1)[0] if source_counts else ("—", 0)
    ages = [age_minutes(item, now) for item in items]
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
        "topSources": [{"name": k, "count": v} for k, v in source_counts.most_common(8)],
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


def static_quality_bonus(item: dict[str, Any]) -> float:
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
    return bonus


def simulate_order(items: list[dict[str, Any]], now: datetime, limit: int = 60) -> list[dict[str, Any]]:
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
            value = base_recency_score(item, now) + static_quality_bonus(item)

            # Strong freshness guard: the simulation may improve quality, but should
            # not make the feed feel stale in the first screen.
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
    summary = {
        "sampleCount": len(runs),
        "window": min(12, len(runs)),
        "positiveRuns": sum(1 for d in deltas if d > 0),
        "negativeRuns": sum(1 for d in deltas if d < 0),
        "avgHealthDelta": round(sum(deltas) / len(deltas), 2) if deltas else 0,
        "avgAfterHealthScore": round(sum(after_scores) / len(after_scores), 2) if after_scores else 0,
        "stablePositive": bool(deltas) and sum(1 for d in deltas if d > 0) >= math.ceil(len(deltas) * 0.7),
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
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--history-max", type=int, default=144)
    args = ap.parse_args()

    feed_path = Path(args.feed)
    data = json.loads(feed_path.read_text(encoding="utf-8"))
    original = list(data.get("items") or [])
    now = datetime.now(timezone.utc)
    simulated = simulate_order(original, now, max(10, args.limit))

    original_rank_by_key = {story_key(item): i + 1 for i, item in enumerate(original[: args.limit])}
    simulated_rank_by_key = {story_key(item): i + 1 for i, item in enumerate(simulated[: args.limit])}

    def ranked(item: dict[str, Any], rank: int, *, after: bool) -> dict[str, Any]:
        key = story_key(item)
        before_rank = original_rank_by_key.get(key)
        after_rank = simulated_rank_by_key.get(key) if after else rank
        return compact_item(item, now, before_rank=before_rank, after_rank=after_rank)

    before = metric_block(original, now)
    after = metric_block(simulated, now)
    before_score = health_score(before)
    after_score = health_score(after)
    delta = {
        "newsinessTop10": after["newsinessTop10"] - before["newsinessTop10"],
        "softTop10": after["softTop10"] - before["softTop10"],
        "top12Under60": after["top12Under60"] - before["top12Under60"],
        "uniqueSourcesTop20": after["uniqueSourcesTop20"] - before["uniqueSourcesTop20"],
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
        "delta": delta,
        "historySummary": history.get("summary", {}),
        "top10Before": [ranked(item, i + 1, after=False) for i, item in enumerate(original[:10])],
        "top10After": [ranked(item, i + 1, after=True) for i, item in enumerate(simulated[:10])],
        "top20Before": [ranked(item, i + 1, after=False) for i, item in enumerate(original[:20])],
        "top20After": [ranked(item, i + 1, after=True) for i, item in enumerate(simulated[:20])],
        "movement": [
            {
                "headline": compact_item(item, now)["headline"],
                "source": compact_item(item, now)["canonicalSource"],
                "category": compact_item(item, now)["category"],
                "class": compact_item(item, now)["class"],
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
    print(json.dumps({"out": str(out), "publicOut": str(public_out), "history": str(args.history), "before": before, "after": after, "delta": delta}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
