#!/usr/bin/env python3
"""Poanta מבקר תזמון.

Reads the gatekeeper publication event stream and checks freshness SLA with a
stopwatch. It does not judge card quality and it does not need the public feed as
its primary source of truth.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENTS = ROOT / "tmp" / "publication_events.jsonl"
DEFAULT_REPORT = ROOT / "tmp" / "pointa_timing_auditor_last.json"
DEFAULT_SLA_CONFIG = ROOT / "config" / "pointa_freshness_sla.json"

DEFAULT_GROUP_THRESHOLDS_MIN = {
    # Overall publication silence: same top-feed SLA used by the live auditor.
    "all": 25,
    # Category/domain SLA, aligned with feedback-dashboard.html THRESHOLDS red limits.
    "ביטחון": 25,
    "פוליטיקה": 30,
    "חדשות": 35,
    "פלילים": 40,
    "משפט": 45,
    "כלכלה": 45,
    "צרכנות": 60,
    "רכב": 60,
    "ספורט": 60,
    "אקטואליה בעולם": 60,
    "דעות": 90,
    "טכנולוגיה": 90,
    "בריאות": 90,
    "תרבות": 120,
    "רכילות": 120,
    "נדל״ן": 120,
    "מזג אוויר": 180,
    # Source-view SLA remains less aggressive than domain SLA to avoid source-specific false alarms.
    "important": 60,
    "foreign": 60,
    "דה מרקר": 120,
    "הארץ": 90,
    "מעריב": 90,
}
DEFAULT_ALL_WARNING_MIN = 15
IMPORTANT_SOURCES = ["הארץ", "ynet", "וואלה", "מעריב", "גלובס", "ישראל היום", "דה מרקר"]
FOREIGN_SOURCES = ["Reuters", "AP", "NYT", "Axios", "Al Jazeera", "Bloomberg", "BBC", "CNN", "Sky", "Guardian", "Politico"]


def now_dt() -> datetime:
    return datetime.now(timezone(timedelta(hours=3)))


def parse_dt(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone(timedelta(hours=3)))
        return d.astimezone(timezone(timedelta(hours=3)))
    except Exception:
        return None


def read_events(path: Path, limit: int = 2000) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            ev = json.loads(line)
            if isinstance(ev, dict) and ev.get("eventType") == "card_published":
                out.append(ev)
        except Exception:
            continue
    return out


def source_group(ev: dict[str, Any]) -> str:
    label = str(ev.get("sourceLogo") or ev.get("source") or "")
    for src in IMPORTANT_SOURCES:
        if src in label:
            return src
    for src in FOREIGN_SOURCES:
        if src.lower() in label.lower():
            return src
    clean = re.split(r"\s+-\s+|\s+דרך\s+", label)[0].strip()
    return clean or "unknown"


def event_time(ev: dict[str, Any], use_seen_at: bool) -> datetime | None:
    if use_seen_at:
        return parse_dt(ev.get("seenAt"))
    return parse_dt(ev.get("publishedAt")) or parse_dt(ev.get("seenAt"))


def audit(events: list[dict[str, Any]], thresholds: dict[str, int], use_seen_at: bool = False, all_warning_min: int = DEFAULT_ALL_WARNING_MIN) -> dict[str, Any]:
    now = now_dt()
    latest_by_group: dict[str, dict[str, Any]] = {}
    latest_all: dict[str, Any] | None = None
    latest_important: dict[str, Any] | None = None
    latest_foreign: dict[str, Any] | None = None
    recent_sources = set()
    recent_items = 0

    for ev in events:
        t = event_time(ev, use_seen_at)
        if not t:
            continue
        ev2 = dict(ev)
        ev2["_time"] = t
        group = source_group(ev2)
        ev2["sourceGroup"] = group
        category = str(ev2.get("category") or "").strip()
        if category:
            # Track domain/category freshness in the same report the dashboard
            # surfaces as timing findings. Source groups are still tracked below.
            if category not in latest_by_group or t > latest_by_group[category]["_time"]:
                latest_by_group[category] = ev2
        if latest_all is None or t > latest_all["_time"]:
            latest_all = ev2
        if group in IMPORTANT_SOURCES and (latest_important is None or t > latest_important["_time"]):
            latest_important = ev2
        if group in FOREIGN_SOURCES and (latest_foreign is None or t > latest_foreign["_time"]):
            latest_foreign = ev2
        if group not in latest_by_group or t > latest_by_group[group]["_time"]:
            latest_by_group[group] = ev2
        if now - t <= timedelta(minutes=60):
            recent_items += 1
            recent_sources.add(group)

    findings: list[dict[str, Any]] = []

    def check(name: str, ev: dict[str, Any] | None, threshold_min: int) -> None:
        if not ev:
            findings.append({"severity": "error", "code": "no_publication_events", "group": name, "message": f"No publication event found for {name}"})
            return
        age = now - ev["_time"]
        age_min = int(age.total_seconds() // 60)
        if name == "all" and 6 <= now.hour < 23 and age > timedelta(minutes=all_warning_min) and age <= timedelta(minutes=threshold_min):
            findings.append({
                "severity": "warning",
                "code": "publication_silence_warning",
                "group": name,
                "thresholdMinutes": threshold_min,
                "warningMinutes": all_warning_min,
                "ageMinutes": age_min,
                "latestAt": ev["_time"].isoformat(timespec="seconds"),
                "headline": ev.get("headline"),
                "source": ev.get("source"),
                "message": f"No new publication event for {age_min} minutes; warn Aliza now. At {threshold_min} minutes this becomes an operational problem.",
                "recommendedAction": "alert_aliza_monitor_until_fast_rescue_threshold",
                "escalateTo": "aliza",
            })
        if age > timedelta(minutes=threshold_min):
            findings.append({
                "severity": "error",
                "code": "publication_timing_sla",
                "group": name,
                "thresholdMinutes": threshold_min,
                "ageMinutes": age_min,
                "latestAt": ev["_time"].isoformat(timespec="seconds"),
                "headline": ev.get("headline"),
                "source": ev.get("source"),
                "message": f"No fresh {name} publication event for {age_min} minutes; threshold is {threshold_min} minutes. Alert Aliza and trigger deterministic rescue without lowering editorial standards.",
                "recommendedAction": "trigger_source_rescue_and_alert_aliza" if name != "all" else "trigger_fast_rescue_and_alert_aliza",
                "escalateTo": "aliza",
            })

    check("all", latest_all, thresholds.get("all", 90))
    check("important", latest_important, thresholds.get("important", 120))
    check("foreign", latest_foreign, thresholds.get("foreign", 90))
    for group, threshold in thresholds.items():
        if group in {"all", "important", "foreign"}:
            continue
        check(group, latest_by_group.get(group), threshold)

    if recent_items < 5:
        findings.append({"severity": "warning", "code": "low_recent_event_volume", "recent60m": recent_items, "message": f"Only {recent_items} publication events in the last 60 minutes."})
    if len(recent_sources) < 3:
        findings.append({"severity": "warning", "code": "low_recent_source_diversity", "recentSources60m": sorted(recent_sources), "message": f"Only {len(recent_sources)} source groups published in the last 60 minutes."})

    errors = [f for f in findings if f.get("severity") == "error"]
    warnings = [f for f in findings if f.get("severity") == "warning"]
    latest_summary = {k: {"latestAt": v["_time"].isoformat(timespec="seconds"), "headline": v.get("headline"), "source": v.get("source")} for k, v in sorted(latest_by_group.items())}
    return {
        "auditor": "timing",
        "status": "fail" if errors else "ok",
        "checkedAt": now.isoformat(timespec="seconds"),
        "eventsChecked": len(events),
        "clock": "seenAt" if use_seen_at else "publishedAt_fallback_seenAt",
        "thresholdsMinutes": thresholds,
        "warningMinutes": {"all": all_warning_min},
        "recentItems60m": recent_items,
        "recentSourceGroups60m": sorted(recent_sources),
        "latestByGroup": latest_summary,
        "errors": errors,
        "warnings": warnings,
        "findings": findings,
    }


def thresholds_from_config(path: Path = DEFAULT_SLA_CONFIG) -> dict[str, int]:
    """Load SLA fail thresholds from the shared dashboard/ops config.

    The hard-coded defaults stay as a safe fallback so a broken/missing config
    cannot disable the timing auditor.
    """
    out = dict(DEFAULT_GROUP_THRESHOLDS_MIN)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return out
    top = data.get("topFeed") or {}
    if isinstance(top.get("failMinutes"), int):
        out["all"] = int(top["failMinutes"])
    for group_name in ("domains", "sources"):
        group_data = data.get(group_name) or {}
        if not isinstance(group_data, dict):
            continue
        for name, spec in group_data.items():
            if isinstance(spec, dict) and isinstance(spec.get("failMinutes"), int):
                out[str(name)] = int(spec["failMinutes"])
    return out


def parse_thresholds(raw: str, config_path: Path = DEFAULT_SLA_CONFIG) -> dict[str, int]:
    out = thresholds_from_config(config_path)
    if raw:
        for part in raw.split(","):
            if not part.strip() or "=" not in part:
                continue
            k, v = part.split("=", 1)
            out[k.strip()] = int(v.strip())
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default=str(DEFAULT_EVENTS))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--threshold", default="", help="Comma list, e.g. all=90,foreign=60,דה מרקר=240")
    ap.add_argument("--sla-config", default=str(DEFAULT_SLA_CONFIG), help="Shared freshness SLA config JSON")
    ap.add_argument("--use-seen-at", action="store_true", help="Measure publication pipeline silence rather than source publication time")
    ap.add_argument("--all-warning-min", type=int, default=DEFAULT_ALL_WARNING_MIN, help="Warn Aliza after this many minutes without any new publication event")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on-error", action="store_true")
    args = ap.parse_args()
    events = read_events(Path(args.events))
    result = audit(events, parse_thresholds(args.threshold, Path(args.sla_config)), use_seen_at=args.use_seen_at, all_warning_min=args.all_warning_min)
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Pointa timing auditor: {result['status']} · events={result['eventsChecked']} · recent60m={result['recentItems60m']} · errors={len(result['errors'])} · warnings={len(result['warnings'])}")
    return 1 if args.fail_on_error and result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
