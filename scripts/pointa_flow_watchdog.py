#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pointa flow watchdog — המעורר.

Runs an end-to-end flow health check. This is not another card-quality auditor;
it checks whether the whole publication flow is awake: live feed, timing,
quality, P0 disaster drill, and top-card image presence.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIVE_FEED = "https://liorexmotors.github.io/poanta-demo/feed.json"
TZ = timezone(timedelta(hours=3))
AGENT_JOB_NAMES = {
    "האספן": [
        "Poanta quiet FAST feed sync/deploy every 10m",
        "Poanta quiet FAST feed sync/deploy every 15m",
    ],
    "מבזק": ["Poanta breaking feed refresh every 10m"],
}

CRITICAL_TIMING_GROUPS = {"all", "important", "foreign"}


def run_json(cmd: list[str]) -> tuple[int, dict[str, Any] | None, str]:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    text = (proc.stdout or "").strip()
    try:
        return proc.returncode, json.loads(text), proc.stderr
    except Exception:
        return proc.returncode, None, (proc.stderr or "") + "\n" + text[:1000]


def run_text(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def fetch_live_feed() -> dict[str, Any]:
    url = LIVE_FEED + f"?watchdog={int(datetime.now().timestamp() * 1000)}"
    req = urllib.request.Request(url, headers={"User-Agent": "PointaFlowWatchdog/1.0", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def quality_gate_feed_path() -> str:
    """Use the freshest local publish candidate for watchdog quality checks."""
    dist_feed = ROOT / "dist" / "feed.json"
    root_feed = ROOT / "feed.json"
    if dist_feed.exists():
        return str(dist_feed.relative_to(ROOT))
    return str(root_feed.relative_to(ROOT))


def agent_readiness_findings() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Verify the control-room agents are awake and ready for action.

    המעורר is responsible for waking the room, not for running long repairs.
    In practice this means every watchdog pass checks that each role has its
    scheduled job enabled and not obviously stuck. Failures are routed to
    המתקן / עליזה instead of being hidden behind a generic OK.
    """
    readiness: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    try:
        proc = subprocess.run(
            ["openclaw", "cron", "list", "--json", "--timeout", "10000"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=15,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "").strip())
        payload = json.loads(proc.stdout)
    except Exception as exc:
        return {}, [{"code": "agent_roster_unreadable", "owner": "המעורר", "message": f"openclaw cron list failed: {exc}"}], []

    jobs = payload.get("jobs") if isinstance(payload, dict) else payload
    if not isinstance(jobs, list):
        return {}, [{"code": "agent_roster_invalid", "owner": "המעורר", "message": "cron jobs file has no jobs list"}], []
    by_name = {str(job.get("name") or ""): job for job in jobs if isinstance(job, dict)}
    now_ms = int(datetime.now(TZ).timestamp() * 1000)
    for role, names in AGENT_JOB_NAMES.items():
        role_entries = []
        role_ok = True
        found_any = False
        for name in names:
            job = by_name.get(name)
            if not job:
                role_entries.append({"name": name, "ready": False, "reason": "missing"})
                continue
            found_any = True
            state = job.get("state") or {}
            enabled = bool(job.get("enabled"))
            running_at = int(state.get("runningAtMs") or 0)
            running_age_min = round((now_ms - running_at) / 60000, 1) if running_at else 0
            stuck = bool(running_at and running_age_min > 20)
            ready = enabled and not stuck
            role_ok = role_ok and ready
            role_entries.append({
                "name": name,
                "ready": ready,
                "enabled": enabled,
                "lastRunStatus": state.get("lastRunStatus"),
                "nextRunAtMs": state.get("nextRunAtMs"),
                "runningAgeMin": running_age_min if running_at else None,
            })
            if not enabled:
                errors.append({"code": "agent_job_disabled", "owner": role, "message": f"{name} is disabled"})
            elif stuck:
                errors.append({"code": "agent_job_stuck", "owner": role, "message": f"{name} appears stuck for {running_age_min} minutes"})
            elif state.get("lastRunStatus") == "error":
                warnings.append({"code": "agent_last_run_error", "owner": role, "message": f"{name} last run ended with error"})
        if not found_any:
            role_ok = False
            errors.append({"code": "agent_job_missing", "owner": role, "message": f"None of the expected cron jobs exist: {', '.join(names)}"})
        readiness[role] = {"ready": role_ok, "jobs": role_entries}
    return readiness, errors, warnings


def image_presence_findings(feed: dict[str, Any], top_n: int = 40) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    items = feed.get("items") or []
    missing = []
    for idx, item in enumerate(items[:top_n]):
        if not str(item.get("imageUrl") or "").strip():
            missing.append({"index": idx, "source": item.get("source"), "headline": item.get("headline"), "url": item.get("sourceUrl")})
    if missing:
        findings.append({
            "severity": "error",
            "code": "top_cards_missing_images",
            "message": f"{len(missing)} of top {top_n} live cards have no imageUrl",
            "items": missing[:10],
        })
    return findings


def main() -> int:
    checked_at = datetime.now(TZ).isoformat(timespec="seconds")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    live_code, live, live_err = run_json([sys.executable, "scripts/pointa_live_auditor.py", "--json"])
    timing_code, timing, timing_err = run_json([sys.executable, "scripts/pointa_timing_auditor.py", "--json", "--use-seen-at"])
    quality_code, quality, quality_err = run_json([sys.executable, "scripts/pointa_quality_auditor.py", "--json"])
    drill_code, drill, drill_err = run_json([sys.executable, "scripts/poanta_p0_stuck_feed_drill.py"])
    qg_feed = quality_gate_feed_path()
    qg_code, qg_text = run_text([sys.executable, "scripts/pointa_quality_gate.py", "--feed", qg_feed, "--report", "tmp/flow_watchdog_quality_gate.md"])
    agent_readiness, agent_errors, agent_warnings = agent_readiness_findings()
    errors.extend(agent_errors)
    warnings.extend(agent_warnings)

    if not live:
        errors.append({"code": "live_auditor_unreadable", "message": live_err.strip()})
    else:
        errors.extend({**e, "owner": "המבקר"} for e in live.get("errors", []))
        warnings.extend({**w, "owner": "המבקר"} for w in live.get("warnings", []))

    if not timing:
        errors.append({"code": "timing_auditor_unreadable", "message": timing_err.strip()})
    else:
        for e in timing.get("errors", []):
            item = {**e, "owner": "מבקר התזמון"}
            if e.get("code") == "publication_timing_sla" and e.get("group") not in CRITICAL_TIMING_GROUPS:
                item["severity"] = "warning"
                warnings.append(item)
            else:
                errors.append(item)
        warnings.extend({**w, "owner": "מבקר התזמון"} for w in timing.get("warnings", []))

    if not quality:
        errors.append({"code": "quality_auditor_unreadable", "message": quality_err.strip()})
    else:
        errors.extend({**e, "owner": "השוער"} for e in quality.get("errors", []))
        warnings.extend({**w, "owner": "השוער"} for w in quality.get("warnings", []))

    if qg_code != 0:
        errors.append({"code": "quality_gate_failed", "owner": "השוער", "message": qg_text[:1200]})

    stale_drill_ok = bool(drill and (drill.get("staleFeedBlocked") or drill.get("staleFeedPublishesWithFreshnessWarning")))
    if not drill or drill_code != 0 or not stale_drill_ok or not all(drill.get(k) for k in ["freshFeedPasses", "badGossipBlocked"]):
        errors.append({"code": "p0_drill_failed", "owner": "המעורר", "message": drill_err.strip() or json.dumps(drill, ensure_ascii=False)})

    try:
        feed = fetch_live_feed()
        errors.extend({**e, "owner": "השוער/האספן"} for e in image_presence_findings(feed))
    except Exception as exc:
        errors.append({"code": "live_feed_fetch_failed", "owner": "המבקר", "message": str(exc)})

    status = "fail" if errors else "ok"
    state_path = ROOT / "tmp" / "pointa_flow_watchdog_state.json"
    previous: dict[str, Any] = {}
    if state_path.exists():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    previous_status = str(previous.get("status") or "")
    recovered = previous_status == "fail" and status == "ok"
    still_failing = previous_status == "fail" and status == "fail"
    newly_failing = previous_status != "fail" and status == "fail"

    result = {
        "watchdog": "pointa_flow_watchdog",
        "checkedAt": checked_at,
        "status": status,
        "previousStatus": previous_status or None,
        "transition": {
            "recovered": recovered,
            "stillFailing": still_failing,
            "newlyFailing": newly_failing,
        },
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "live": live.get("status") if live else None,
            "timing": timing.get("status") if timing else None,
            "quality": quality.get("status") if quality else None,
            "qualityGateExit": qg_code,
            "qualityGateFeed": qg_feed,
            "p0Drill": drill,
            "agentReadiness": agent_readiness,
        },
    }
    out = ROOT / "tmp" / "pointa_flow_watchdog_last.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state_path.write_text(json.dumps({
        "status": status,
        "checkedAt": checked_at,
        "lastErrors": errors[:5],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
