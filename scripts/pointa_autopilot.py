#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pointa Autopilot stage 1: dry-run diagnosis and action planning.

This script is intentionally non-mutating for feed/publication state.  It reads
current local/public health, classifies the incident, updates a small autopilot
state file for loop protection, and writes a dashboard-friendly report.  Later
stages may execute selected repairs, but dry-run must never deploy or edit the
feed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "tmp"
STATE_PATH = TMP / "pointa_autopilot_state.json"
REPORT_PATH = TMP / "pointa_autopilot_report.json"
PUBLIC_FEED_URL = "https://liorexmotors.github.io/poanta-demo/feed.json"
RAW_GHPAGES_URL = "https://raw.githubusercontent.com/liorexmotors/poanta-demo/gh-pages/feed.json"
TZ = timezone(timedelta(hours=3))
TOP_STALE_CODES = {"stale_updated_at", "no_new_top_item_sla", "stale_top_item", "too_few_fresh_top_items", "too_few_recent_items_sla", "too_few_recent_sources_sla"}
QUALITY_BLOCK_CODES = {"summary_fragment_headline", "headline_too_close_to_source", "generic_takeaway_regression", "weather_on_top"}


@dataclass
class HealthSnapshot:
    public_health: dict[str, Any]
    live: dict[str, Any]
    timing: dict[str, Any]
    raw_health: dict[str, Any]
    local_health: dict[str, Any]
    local_quality: dict[str, Any]
    feed_signature: dict[str, Any]
    local_signature: dict[str, Any] | None = None


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        text = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        return 124, f"TIMEOUT after {timeout}s: {' '.join(cmd)}\n{text}"


def run_json(cmd: list[str], timeout: int = 120) -> tuple[int, dict[str, Any], str]:
    code, text = run(cmd, timeout=timeout)
    try:
        return code, json.loads(text), text
    except Exception:
        return code, {"status": "error", "parseError": True, "exit": code, "tail": text[-2000:]}, text


def fetch_feed_signature(url: str) -> dict[str, Any]:
    try:
        req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache", "User-Agent": "PointaAutopilot/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            feed = json.loads(resp.read().decode("utf-8"))
        return feed_signature(feed)
    except Exception as exc:
        return {"error": str(exc)}


def feed_signature(feed: dict[str, Any]) -> dict[str, Any]:
    items = feed.get("items") or []
    top = items[0] if items and isinstance(items[0], dict) else {}
    return {
        "updatedAt": feed.get("updatedAt"),
        "items": len(items),
        "topPublishedAt": top.get("publishedAt"),
        "topHeadline": top.get("headline"),
        "topSource": top.get("source"),
        "topUrl": top.get("sourceUrl") or top.get("url"),
    }


def local_feed_signature() -> dict[str, Any]:
    try:
        return feed_signature(json.loads((ROOT / "feed.json").read_text(encoding="utf-8")))
    except Exception as exc:
        return {"error": str(exc)}


def collect_snapshot() -> HealthSnapshot:
    _public_code, public_health, _ = run_json([sys.executable, "scripts/pointa_publication_health_gate.py", "--mode", "public", "--json"], timeout=120)
    _live_code, live, _ = run_json([sys.executable, "scripts/pointa_live_auditor.py", "--json"], timeout=120)
    _timing_code, timing, _ = run_json([sys.executable, "scripts/pointa_timing_auditor.py", "--json"], timeout=120)
    _raw_code, raw_live, _ = run_json([sys.executable, "scripts/pointa_live_auditor.py", "--url", RAW_GHPAGES_URL, "--raw-url", RAW_GHPAGES_URL, "--json"], timeout=120)
    raw_health = {"status": "ok" if raw_live.get("status") == "ok" else "fail", "liveStatus": raw_live.get("status"), "blockers": raw_live.get("errors") or []}
    qg_code, qg_text = run([sys.executable, "scripts/pointa_quality_gate.py", "--feed", "feed.json"], timeout=120)
    _local_code, local_health, _ = run_json([sys.executable, "scripts/pointa_publication_health_gate.py", "--mode", "candidate", "--feed", "feed.json", "--json"], timeout=120)
    return HealthSnapshot(
        public_health=public_health,
        live=live,
        timing=timing,
        raw_health=raw_health,
        local_health=local_health,
        local_quality={"exit": qg_code, "summary": qg_text.strip().splitlines()[0] if qg_text.strip() else ""},
        feed_signature=fetch_feed_signature(PUBLIC_FEED_URL + f"?autopilot={int(datetime.now(TZ).timestamp()*1000)}"),
        local_signature=local_feed_signature(),
    )


def _codes(rows: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("code")) for row in rows if row.get("code")}


def _status(data: dict[str, Any]) -> str:
    return str(data.get("status") or "unknown")


def classify_incident(snapshot: HealthSnapshot) -> dict[str, Any]:
    public_blockers = snapshot.public_health.get("blockers") or []
    public_codes = _codes(public_blockers) | _codes(snapshot.live.get("errors") or [])
    local_blockers = snapshot.local_health.get("blockers") or []
    local_codes = _codes(local_blockers)
    timing_errors = snapshot.timing.get("errors") or []
    timing_groups = sorted({str(e.get("group")) for e in timing_errors if e.get("group")})
    public_ok = _status(snapshot.public_health) == "ok" and _status(snapshot.live) == "ok"
    raw_ok = _status(snapshot.raw_health) == "ok"
    local_ok = _status(snapshot.local_health) == "ok" and int(snapshot.local_quality.get("exit") or 0) == 0

    if public_ok:
        incident_type = "healthy" if _status(snapshot.timing) == "ok" else "healthy_with_domain_timing_debt"
        return {
            "status": "ok",
            "incidentType": incident_type,
            "recommendedStage": "none" if incident_type == "healthy" else "stage_4_domain_backlog",
            "automaticAction": "none",
            "incidentKey": f"{incident_type}|{snapshot.feed_signature.get('updatedAt')}|{snapshot.feed_signature.get('topUrl')}",
            "signals": {"publicCodes": sorted(public_codes), "localCodes": sorted(local_codes), "timingGroups": timing_groups},
        }

    if raw_ok and not public_ok:
        return {
            "status": "degraded",
            "incidentType": "github_pages_propagation_lag",
            "recommendedStage": "wait_and_reverify",
            "automaticAction": "verify_public_again",
            "incidentKey": f"pages_lag|{snapshot.raw_health.get('liveStatus')}|{snapshot.feed_signature.get('updatedAt')}",
            "signals": {"publicCodes": sorted(public_codes), "localCodes": sorted(local_codes), "timingGroups": timing_groups},
        }

    if int(snapshot.local_quality.get("exit") or 0) != 0 or (local_codes & QUALITY_BLOCK_CODES):
        return {
            "status": "blocked",
            "incidentType": "local_candidate_quality_blocked",
            "recommendedStage": "editor_or_agent_review",
            "automaticAction": "do_not_publish",
            "incidentKey": f"quality_blocked|{','.join(sorted(local_codes))}|{snapshot.feed_signature.get('updatedAt')}",
            "signals": {"publicCodes": sorted(public_codes), "localCodes": sorted(local_codes), "timingGroups": timing_groups},
        }

    if not public_ok and local_ok:
        return {
            "status": "repair_needed",
            "incidentType": "deploy_public_stale_local_candidate_healthy",
            "recommendedStage": "stage_2_safe_deploy",
            "automaticAction": "deploy_current_feed_then_verify_public",
            "incidentKey": f"deploy_needed|{snapshot.local_signature or {}}|{snapshot.feed_signature.get('updatedAt')}",
            "signals": {"publicCodes": sorted(public_codes), "localCodes": sorted(local_codes), "timingGroups": timing_groups},
        }

    if public_codes & TOP_STALE_CODES or any(e.get("group") == "all" for e in timing_errors):
        return {
            "status": "repair_needed",
            "incidentType": "top_feed_stale_or_thin",
            "recommendedStage": "stage_3_general_rescue",
            "automaticAction": "prepare_general_rescue_worker",
            "incidentKey": f"top_stale|{','.join(sorted(public_codes))}|{snapshot.feed_signature.get('updatedAt')}|{snapshot.feed_signature.get('topUrl')}",
            "signals": {"publicCodes": sorted(public_codes), "localCodes": sorted(local_codes), "timingGroups": timing_groups},
        }

    return {
        "status": "blocked",
        "incidentType": "unknown_publication_failure",
        "recommendedStage": "diagnose_manually",
        "automaticAction": "do_not_publish",
        "incidentKey": f"unknown|{','.join(sorted(public_codes))}|{snapshot.feed_signature.get('updatedAt')}",
        "signals": {"publicCodes": sorted(public_codes), "localCodes": sorted(local_codes), "timingGroups": timing_groups},
    }


def update_state(state: dict[str, Any], incident: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    now = now or now_iso()
    previous_key = state.get("currentIncidentKey")
    current_key = incident.get("incidentKey")
    repeat_count = int(state.get("currentIncidentRepeatCount") or 0) + 1 if previous_key == current_key else 1
    loop_active = repeat_count >= 3 and incident.get("status") != "ok"
    new_state = {
        **state,
        "lastCheckedAt": now,
        "lastStatus": incident.get("status"),
        "lastIncidentType": incident.get("incidentType"),
        "currentIncidentKey": current_key,
        "currentIncidentRepeatCount": repeat_count,
        "lastAutomaticAction": incident.get("automaticAction"),
        "loopProtection": {
            "active": loop_active,
            "reason": "same_incident_repeated" if loop_active else "",
            "repeatCount": repeat_count,
        },
    }
    if incident.get("status") == "ok":
        new_state["lastOkAt"] = now
    return new_state


def build_report(*, mode: str, snapshot: dict[str, Any], incident: dict[str, Any], state: dict[str, Any], started_at: str) -> dict[str, Any]:
    action = incident.get("automaticAction")
    would_run = [] if action in (None, "", "none", "do_not_publish") else [action]
    return {
        "autopilot": "pointa_autopilot",
        "version": 1,
        "mode": mode,
        "checkedAt": started_at,
        "status": incident.get("status"),
        "incidentType": incident.get("incidentType"),
        "recommendedStage": incident.get("recommendedStage"),
        "automaticAction": action,
        "wouldRun": would_run,
        "executedActions": [],
        "mutatesFeed": False,
        "deploys": False,
        "snapshot": snapshot,
        "incident": incident,
        "state": state,
        "policy": "Stage 1 is diagnose/report only. No feed edits, no rescue preparation, no deploy.",
    }


def exit_code_for_mode(mode: str, incident: dict[str, Any]) -> int:
    if mode == "dry-run":
        return 0
    return 0 if incident.get("status") in {"ok", "degraded"} else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Pointa autopilot stage 1 dry-run")
    ap.add_argument("--mode", choices=["dry-run"], default="dry-run")
    ap.add_argument("--state", default=str(STATE_PATH))
    ap.add_argument("--out", default=str(REPORT_PATH))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    started_at = now_iso()
    snapshot = collect_snapshot()
    incident = classify_incident(snapshot)
    state_path = Path(args.state)
    state = update_state(read_json(state_path), incident, now=started_at)
    report = build_report(mode=args.mode, snapshot=asdict(snapshot), incident=incident, state=state, started_at=started_at)
    write_json(state_path, state)
    write_json(Path(args.out), report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Pointa autopilot: {report['status']} · {report['incidentType']} · action={report['automaticAction']}")
        print(f"Report: {Path(args.out).resolve()}")
    return exit_code_for_mode(args.mode, incident)


if __name__ == "__main__":
    raise SystemExit(main())
