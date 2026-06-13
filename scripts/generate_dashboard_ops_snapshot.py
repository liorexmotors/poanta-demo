#!/usr/bin/env python3
"""Generate a static dashboard ops fallback snapshot for feedback-dashboard.html.

The public dashboard normally reads /v1/ops/status from poanta-api. When that API is
unavailable (for example 502 from clawbud), this snapshot lets the static GitHub
Pages dashboard still show the latest known auditor/action status instead of
misleading blanks.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "tmp"
OUT = ROOT / "dashboard_ops_snapshot.json"
TZ = timezone(timedelta(hours=3))


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def agent_from_report(agent_id: str, name: str, report: dict[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {
            "id": agent_id,
            "name": name,
            "status": "unknown",
            "summary": "אין snapshot אחרון זמין",
            "findings": [],
        }
    status = str(report.get("status") or "unknown")
    findings = list(report.get("errors") or []) + list(report.get("warnings") or []) + list(report.get("blockers") or [])
    checked = report.get("checkedAt") or report.get("generatedAt") or ""
    if status == "ok":
        summary = f"תקין בבדיקה האחרונה {checked}".strip()
    elif findings:
        summary = str(findings[0].get("message") or findings[0].get("code") or f"סטטוס {status}")
    else:
        summary = f"סטטוס {status} בבדיקה האחרונה {checked}".strip()
    return {
        "id": agent_id,
        "name": name,
        "status": "fail" if status == "fail" else ("ok" if status == "ok" else "unknown"),
        "summary": summary,
        "checkedAt": checked,
        "findings": findings[:8],
    }


HARD_CATEGORIES = {"ביטחון", "פוליטיקה", "חדשות", "משפט", "פלילים", "כלכלה", "אקטואליה בעולם"}
SOFT_CATEGORIES = {"רכילות", "ספורט", "תרבות", "בריאות"}
HARD_KEYWORDS = [
    "איראן", "טראמפ", "חיזבאללה", "לבנון", "עזה", "חמאס", "הורמוז", "נתב״ג", "נתב\"ג",
    "מחאה", "הפגנה", "רכבת", "מח״ש", "מח\"ש", "פיגוע", "טיל", "כטב", "מלחמה", "צבא",
    "משטרה", "ממשלה", "כנסת", "בנק", "בורסה", "נפט", "דולר",
]
IMPORTANT_SOURCES = ["N12", "ynet", "מעריב", "הארץ", "BBC", "Guardian", "NYT", "גלובס", "ישראל היום", "וואלה"]


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def age_minutes(value: Any, now: datetime) -> int | None:
    dt = parse_dt(value)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
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
    for token in ["וואלה", "מעריב", "הארץ", "גלובס", "ישראל היום", "דה מרקר", "Jerusalem Post"]:
        if token in source:
            return token
    return source.split(" - ")[0].strip() or "מקור"


def item_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(k) or "") for k in ("category", "source", "headline", "originalTitle", "context", "takeaway"))


def classify_item(item: dict[str, Any]) -> str:
    category = str(item.get("category") or "")
    text = item_text(item)
    if category in SOFT_CATEGORIES:
        strong_event_terms = ["פיגוע", "טיל", "כטב", "מלחמה", "חיזבאללה", "חמאס", "איראן", "ירי", "רצח"]
        return "hard" if any(k in text for k in strong_event_terms) else "soft"
    if category in HARD_CATEGORIES:
        return "hard"
    if any(k in text for k in HARD_KEYWORDS):
        return "hard"
    if any(k in text for k in ("רכילות", "ספורט", "סלב", "תרבות", "TVShowbiz", "Celebs")):
        return "soft"
    return "other"


def build_feed_quality(feed: dict[str, Any] | None, breaking: dict[str, Any] | None, now: datetime) -> dict[str, Any]:
    items = list((feed or {}).get("items") or [])
    breaking_items = list((breaking or {}).get("items") or [])
    top10 = items[:10]
    top20 = items[:20]
    top12 = items[:12]
    top5 = items[:5]
    classes = [classify_item(item) for item in top10]
    ages = [age_minutes(item.get("publishedAt"), now) for item in items]
    sources = [canonical_source(item.get("source")) for item in top20]
    source_counts = {source: sources.count(source) for source in sorted(set(sources)) if source}
    dominant = max(source_counts.items(), key=lambda kv: kv[1], default=("—", 0))
    breaking_ages = [age_minutes(item.get("publishedAt"), now) for item in breaking_items]
    important_presence = {source: any(canonical_source(item.get("source")) == source for item in top20) for source in IMPORTANT_SOURCES}
    newsiness = classes.count("hard")
    soft = classes.count("soft")
    top12_under60 = sum(1 for age in ages[:12] if age is not None and age <= 60)
    score = "ok" if newsiness >= 5 and soft <= 3 and top12_under60 >= 8 else "warn"
    if newsiness <= 2 or soft >= 6 or top12_under60 < 6:
        score = "fail"
    return {
        "generatedAt": now.isoformat(timespec="seconds"),
        "score": score,
        "newsinessTop10": newsiness,
        "softTop10": soft,
        "otherTop10": classes.count("other"),
        "topItemAgeMinutes": ages[0] if ages else None,
        "top5Under60": sum(1 for age in ages[:5] if age is not None and age <= 60),
        "top10Under60": sum(1 for age in ages[:10] if age is not None and age <= 60),
        "top12Under60": top12_under60,
        "uniqueSourcesTop20": len(set(sources)),
        "dominantSource": {"name": dominant[0], "count": dominant[1]},
        "importantSourcesInTop20": important_presence,
        "breaking": {
            "visible": bool(breaking_items),
            "topAgeMinutes": breaking_ages[0] if breaking_ages else None,
            "top12Under60": sum(1 for age in breaking_ages[:12] if age is not None and age <= 60),
            "count": len(breaking_items),
        },
        "notes": [
            "מדידה בלבד — לא משנה את דירוג הפיד.",
            "מדדי חדשותיות, תוכן רך וגיוון מקורות נוספו כדי ללמוד מדוחות עליזה ולכוון שיפור מבוקר.",
        ],
    }


def main() -> int:
    live = load_json(TMP / "pointa_live_auditor_last.json")
    timing = load_json(TMP / "pointa_timing_auditor_last.json")
    health = load_json(TMP / "pointa_publication_health_gate.json")
    autopilot = load_json(TMP / "pointa_autopilot_state.json")
    feed = load_json(ROOT / "feed.json")
    breaking = load_json(ROOT / "breaking_feed.json")
    feed_simulation = load_json(TMP / "feed_quality_ranking_simulation.json")
    feed_simulation_history = load_json(ROOT / "dashboard_simulation_history.json")

    generated = datetime.now(TZ).isoformat(timespec="seconds")
    now = datetime.now(TZ)
    snapshot = {
        "status": "snapshot",
        "snapshotOnly": True,
        "generatedAt": generated,
        "note": "Static fallback for feedback-dashboard.html when poanta-api /v1/ops/status is unavailable.",
        "reports": {
            "liveAuditor": live or {"status": "unknown", "errors": [], "warnings": []},
            "timingAuditor": timing or {"status": "unknown", "errors": [], "warnings": []},
            "publicationHealthGate": health or {"status": "unknown", "blockers": []},
            "autopilot": autopilot or {"status": "unknown"},
        },
        "agents": [
            agent_from_report("live", "מבקר חי", live),
            agent_from_report("timing", "מבקר תזמון", timing),
            agent_from_report("gatekeeper", "השוער", health),
            agent_from_report("repair", "המתקן", autopilot),
        ],
        "feedQuality": build_feed_quality(feed, breaking, now),
        "feedQualitySimulation": feed_simulation,
        "feedQualitySimulationHistory": feed_simulation_history,
    }
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "generatedAt": generated, "agents": len(snapshot["agents"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
