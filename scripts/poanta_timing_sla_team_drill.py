#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Poanta timing/SLA team drill.

Synthetic but realistic red-dashboard scenarios for the full Poanta team.
The goal is to prove that timing/source freshness incidents are not hidden by a
single live-auditor OK result. Every scenario grades the expected owner, trigger,
repair route, and publication gate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp" / "agent-training" / "poanta_timing_sla_team_drill_report.json"

TEAM = ["המבקר", "סוכן התזמון", "האספן", "העורך", "השוער", "המתקן", "עליזה"]


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    live_status: str
    live_errors: list[str]
    timing_status: str
    timing_errors: list[str]
    quality_status: str
    quality_errors_current: int
    quality_errors_historical_fixed: int
    qg_errors: int
    live_raw_agree: bool
    expected_owner: str
    expected_action: str
    expected_ok_allowed: bool


def classify(s: Scenario) -> dict[str, Any]:
    """Training classifier mirroring the hardened auditor contract."""
    blockers: list[str] = []
    if s.live_status != "ok" or s.live_errors:
        blockers.append("live")
    if s.timing_status != "ok" or s.timing_errors:
        blockers.append("timing")
    if s.quality_status != "ok" and s.quality_errors_current:
        blockers.append("quality_current")
    if s.qg_errors:
        blockers.append("quality_gate")
    if not s.live_raw_agree:
        blockers.append("cache_or_deploy_agreement")

    ok_allowed = not blockers

    if ok_allowed:
        owner = "המבקר"
        action = "AUDITOR_OK_after_full_bundle"
    elif "quality_gate" in blockers:
        owner = "השוער"
        action = "block_publish_fix_quality_gate_then_rerun_bundle"
    elif "quality_current" in blockers:
        owner = "השוער"
        action = "block_publish_repair_current_live_quality_then_rerun_bundle"
    elif "live" in blockers:
        owner = "המבקר"
        action = "trigger_fast_then_adaptive_rescue_if_still_stale"
    elif "timing" in blockers:
        owner = "המבקר"
        action = "trigger_timing_source_rescue_even_if_live_ok"
    elif "cache_or_deploy_agreement" in blockers:
        owner = "המתקן"
        action = "verify_raw_live_cache_then_redeploy_or_wait"
    else:
        owner = "עליזה"
        action = "investigate_unclassified_health_failure"

    return {"owner": owner, "action": action, "okAllowed": ok_allowed, "blockers": blockers}


def scenarios() -> list[Scenario]:
    return [
        Scenario("T01", "live OK but foreign timing red", "ok", [], "fail", ["foreign>90m"], "ok", 0, 0, 0, True, "המבקר", "trigger_timing_source_rescue_even_if_live_ok", False),
        Scenario("T02", "top item older than 30m", "fail", ["no_new_top_item_sla"], "ok", [], "ok", 0, 0, 0, True, "המבקר", "trigger_fast_then_adaptive_rescue_if_still_stale", False),
        Scenario("T03", "too few top-12 recent items", "fail", ["too_few_recent_items_sla"], "ok", [], "ok", 0, 0, 0, True, "המבקר", "trigger_fast_then_adaptive_rescue_if_still_stale", False),
        Scenario("T04", "current live card has pipe artifact", "ok", [], "ok", [], "fail", 1, 0, 0, True, "השוער", "block_publish_repair_current_live_quality_then_rerun_bundle", False),
        Scenario("T05", "Quality Gate error after rescue", "ok", [], "ok", [], "ok", 0, 0, 1, True, "השוער", "block_publish_fix_quality_gate_then_rerun_bundle", False),
        Scenario("T06", "raw and pages disagree after deploy", "ok", [], "ok", [], "ok", 0, 0, 0, False, "המתקן", "verify_raw_live_cache_then_redeploy_or_wait", False),
        Scenario("T07", "historical fixed quality error only", "ok", [], "ok", [], "fail", 0, 2, 0, True, "המבקר", "AUDITOR_OK_after_full_bundle", True),
        Scenario("T08", "important source stale timing", "ok", [], "fail", ["ישראל היום>180m"], "ok", 0, 0, 0, True, "המבקר", "trigger_timing_source_rescue_even_if_live_ok", False),
        Scenario("T09", "weather card stuck on top", "fail", ["weather_on_top"], "ok", [], "ok", 0, 0, 0, True, "המבקר", "trigger_fast_then_adaptive_rescue_if_still_stale", False),
        Scenario("T10", "all clean after full bundle", "ok", [], "ok", [], "ok", 0, 0, 0, True, "המבקר", "AUDITOR_OK_after_full_bundle", True),
        Scenario("T11", "live OK but DeMarker source timing red", "ok", [], "fail", ["דה מרקר>240m"], "ok", 0, 0, 0, True, "המבקר", "trigger_timing_source_rescue_even_if_live_ok", False),
        Scenario("T12", "bad JSON/empty live feed", "fail", ["bad_json_live"], "fail", ["all>30m"], "ok", 0, 0, 0, False, "המבקר", "trigger_fast_then_adaptive_rescue_if_still_stale", False),
    ]


def main() -> int:
    rows = []
    for s in scenarios():
        got = classify(s)
        passed = (
            got["owner"] == s.expected_owner
            and got["action"] == s.expected_action
            and got["okAllowed"] == s.expected_ok_allowed
        )
        rows.append({"scenario": asdict(s), "got": got, "passed": passed})

    passed = sum(1 for r in rows if r["passed"])
    report = {
        "name": "Poanta timing/SLA team drill",
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "teamTrained": TEAM,
        "total": len(rows),
        "passed": passed,
        "score": round(100 * passed / len(rows), 2),
        "status": "pass" if passed == len(rows) else "fail",
        "criticalRule": "AUDITOR_OK is forbidden unless live+timing+quality+QG+raw/live agreement were all checked and clean.",
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "score": report["score"], "passed": passed, "total": len(rows), "report": str(OUT)}, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
