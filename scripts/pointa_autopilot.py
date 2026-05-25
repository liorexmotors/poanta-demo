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
import os
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
WORKER_LOCK_PATH = TMP / "pointa_autopilot_stage3.lock"
PUBLIC_FEED_URL = "https://liorexmotors.github.io/poanta-demo/feed.json"
RAW_GHPAGES_URL = "https://raw.githubusercontent.com/liorexmotors/poanta-demo/gh-pages/feed.json"
TZ = timezone(timedelta(hours=3))
TOP_STALE_CODES = {"stale_updated_at", "no_new_top_item_sla", "stale_top_item", "too_few_fresh_top_items", "too_few_recent_items_sla", "too_few_recent_sources_sla"}
QUALITY_BLOCK_CODES = {"summary_fragment_headline", "headline_too_close_to_source", "generic_takeaway_regression", "weather_on_top"}
STAGE3_COOLDOWN_MINUTES = 20


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


def parse_iso(raw: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    except Exception:
        return None


def extract_first_path(text: str) -> Path | None:
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(str(ROOT)) or line.startswith("tmp/") or line.startswith("/tmp/"):
            return (ROOT / line).resolve() if not line.startswith("/") else Path(line)
    return None


def lock_is_active(path: Path = WORKER_LOCK_PATH, max_age_minutes: int = 45) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        created = parse_iso(data.get("createdAt"))
        pid = int(data.get("pid") or 0)
        if created and datetime.now(TZ) - created > timedelta(minutes=max_age_minutes):
            return False
        if pid:
            try:
                os.kill(pid, 0)
                return True
            except ProcessLookupError:
                return False
            except PermissionError:
                return True
        return bool(created)
    except Exception:
        return True


def acquire_lock(path: Path = WORKER_LOCK_PATH) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if lock_is_active(path):
        return False
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "createdAt": now_iso(), "purpose": "pointa_autopilot_stage3"}, f, ensure_ascii=False)
    return True


def release_lock(path: Path = WORKER_LOCK_PATH) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


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


def execute_stage2_repair(
    incident: dict[str, Any],
    *,
    run_func=run,
    collect_func=collect_snapshot,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Execute only Stage-2 safe deploy, then reclassify public health.

    Stage 2 is deliberately narrow: if the local candidate has already passed
    the hard gates and the public feed is stale, deploy the current feed and
    verify the public outcome. It must not prepare rescue queues, edit the feed,
    or touch domain repair.
    """
    if incident.get("automaticAction") != "deploy_current_feed_then_verify_public":
        return [], incident
    if incident.get("recommendedStage") != "stage_2_safe_deploy":
        return [], incident

    actions: list[dict[str, Any]] = []
    code, text = run_func(["bash", "scripts/deploy_current_feed.sh"], timeout=300)
    actions.append({"action": "deploy_current_feed", "exit": code, "tail": text[-3000:]})
    if code != 0:
        failed = {**incident, "status": "blocked", "incidentType": "safe_deploy_failed", "automaticAction": "do_not_publish"}
        return actions, failed

    verified_snapshot = collect_func()
    verified_incident = classify_incident(verified_snapshot)
    actions.append({
        "action": "verify_public_after_deploy",
        "status": verified_incident.get("status"),
        "incidentType": verified_incident.get("incidentType"),
    })
    return actions, verified_incident



def stage3_cooldown_active(state: dict[str, Any], incident: dict[str, Any], *, now: str | None = None) -> bool:
    last = state.get("lastStage3StartedAt")
    last_key = state.get("lastStage3IncidentKey")
    if not last or last_key != incident.get("incidentKey"):
        return False
    last_dt = parse_iso(last)
    now_dt = parse_iso(now or now_iso())
    if not last_dt or not now_dt:
        return False
    return now_dt - last_dt < timedelta(minutes=STAGE3_COOLDOWN_MINUTES)


def execute_stage3_repair(
    incident: dict[str, Any],
    state: dict[str, Any],
    *,
    now: str | None = None,
    run_func=run,
    collect_func=collect_snapshot,
    lock_path: Path = WORKER_LOCK_PATH,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Run Stage-3 general top-feed rescue as a bounded worker lane.

    The worker has its own lock and cooldown. It prepares an adaptive rescue run,
    then only applies/deploys if editor result files exist and every hard gate
    passes. If a previous run is waiting and results were written, it resumes that
    run even during cooldown instead of preparing another batch.
    """
    now = now or now_iso()
    if incident.get("recommendedStage") != "stage_3_general_rescue" or incident.get("automaticAction") != "prepare_general_rescue_worker":
        return [], incident, state

    resume_run_dir = Path(str(state.get("lastStage3RunDir") or "")) if state.get("lastStage3RunDir") else None
    resume_has_results = bool(resume_run_dir and resume_run_dir.exists() and sorted(resume_run_dir.glob("batch_*_results.json")))

    if stage3_cooldown_active(state, incident, now=now) and not resume_has_results:
        skipped = {**incident, "status": "degraded", "incidentType": "stage3_cooldown_active", "automaticAction": "wait_for_cooldown"}
        return [{"action": "stage3_skip_cooldown", "cooldownMinutes": STAGE3_COOLDOWN_MINUTES}], skipped, state
    if not acquire_lock(lock_path):
        locked = {**incident, "status": "degraded", "incidentType": "stage3_worker_already_running", "automaticAction": "wait_for_worker"}
        return [{"action": "stage3_skip_lock_active", "lock": str(lock_path)}], locked, state

    actions: list[dict[str, Any]] = []
    new_state = {**state, "lastStage3StartedAt": now, "lastStage3IncidentKey": incident.get("incidentKey")}
    try:
        if resume_has_results and resume_run_dir is not None:
            run_dir = resume_run_dir
            run_id = run_dir.name
            actions.append({"action": "stage3_resume_editor_run", "runDir": str(run_dir), "resultFiles": len(sorted(run_dir.glob("batch_*_results.json")))})
        else:
            queue_cmd = [sys.executable, "scripts/pointa_source_rescue_queue.py", "--max-age-min", "180", "--sync-profile", "all", "--per-source", "8"]
            code, text = run_func(queue_cmd, timeout=240)
            actions.append({"action": "stage3_prepare_source_rescue_queue", "exit": code, "tail": text[-3000:]})
            if code != 0:
                return actions, {**incident, "status": "blocked", "incidentType": "stage3_source_queue_failed", "automaticAction": "do_not_publish"}, new_state

            run_id = "autopilot-" + datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
            prepare_cmd = [sys.executable, "scripts/pointa_rescue_editor_pipeline.py", "prepare", "--run-id", run_id, "--limit", "18", "--batch-size", "6", "--oversample-factor", "4"]
            code, text = run_func(prepare_cmd, timeout=420)
            run_dir = extract_first_path(text) or (ROOT / "tmp" / "editor-runs" / run_id)
            actions.append({"action": "stage3_prepare_editor_run", "exit": code, "runDir": str(run_dir), "tail": text[-3000:]})
            new_state["lastStage3RunDir"] = str(run_dir)
            if code != 0:
                return actions, {**incident, "status": "blocked", "incidentType": "stage3_editor_prepare_failed", "automaticAction": "do_not_publish"}, new_state

            result_files = sorted(run_dir.glob("batch_*_results.json")) if run_dir.exists() else []
            if not result_files:
                waiting = {**incident, "status": "repair_needed", "incidentType": "stage3_waiting_for_editor_results", "automaticAction": "write_batch_results_then_rerun_stage3"}
                actions.append({"action": "stage3_wait_for_editor_results", "runDir": str(run_dir), "resultFiles": 0})
                return actions, waiting, new_state

        qa_cmd = [sys.executable, "scripts/pointa_editor_pipeline.py", "qa", "--run-dir", str(run_dir), "--auto-reject-failed"]
        code, text = run_func(qa_cmd, timeout=240)
        actions.append({"action": "stage3_qa_editor_results", "exit": code, "tail": text[-3000:]})
        if code != 0:
            return actions, {**incident, "status": "blocked", "incidentType": "stage3_editor_qa_failed", "automaticAction": "do_not_publish"}, new_state

        apply_cmd = [sys.executable, "scripts/pointa_editor_pipeline.py", "apply", "--run-dir", str(run_dir)]
        code, text = run_func(apply_cmd, timeout=180)
        actions.append({"action": "stage3_apply_editor_preview", "exit": code, "tail": text[-3000:]})
        if code != 0:
            return actions, {**incident, "status": "blocked", "incidentType": "stage3_apply_failed", "automaticAction": "do_not_publish"}, new_state

        for name, cmd in [
            ("stage3_quality_gate", [sys.executable, "scripts/pointa_quality_gate.py", "--feed", "feed.json"]),
            ("stage3_publication_health_gate", [sys.executable, "scripts/pointa_publication_health_gate.py"]),
            ("stage3_live_auditor_local", [sys.executable, "scripts/pointa_live_auditor.py", "--json"]),
        ]:
            code, text = run_func(cmd, timeout=180)
            actions.append({"action": name, "exit": code, "tail": text[-3000:]})
            if code != 0:
                return actions, {**incident, "status": "blocked", "incidentType": f"{name}_failed", "automaticAction": "do_not_publish"}, new_state

        code, text = run_func([sys.executable, "scripts/pointa_publication_events.py", "record", "--gatekeeper", "pointa-autopilot-stage3", "--run-id", run_id, "--json"], timeout=120)
        actions.append({"action": "stage3_record_publication_event", "exit": code, "tail": text[-3000:]})
        if code != 0:
            return actions, {**incident, "status": "blocked", "incidentType": "stage3_publication_event_failed", "automaticAction": "do_not_publish"}, new_state

        code, text = run_func(["bash", "scripts/deploy_current_feed.sh"], timeout=300)
        actions.append({"action": "stage3_deploy_current_feed", "exit": code, "tail": text[-3000:]})
        if code != 0:
            return actions, {**incident, "status": "blocked", "incidentType": "stage3_deploy_failed", "automaticAction": "do_not_publish"}, new_state

        verified_snapshot = collect_func()
        verified_incident = classify_incident(verified_snapshot)
        actions.append({"action": "stage3_verify_public_after_deploy", "status": verified_incident.get("status"), "incidentType": verified_incident.get("incidentType")})
        return actions, verified_incident, new_state
    finally:
        release_lock(lock_path)

def build_report(
    *,
    mode: str,
    snapshot: dict[str, Any],
    incident: dict[str, Any],
    state: dict[str, Any],
    started_at: str,
    executed_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    action = incident.get("automaticAction")
    executed_actions = executed_actions or []
    would_run = [] if action in (None, "", "none", "do_not_publish") or executed_actions else [action]
    deploys = any(a.get("action") == "deploy_current_feed" for a in executed_actions)
    stage3_deploys = any(a.get("action") == "stage3_deploy_current_feed" for a in executed_actions)
    mutates_feed = any(a.get("action") == "stage3_apply_editor_preview" and a.get("exit") == 0 for a in executed_actions)
    return {
        "autopilot": "pointa_autopilot",
        "version": 3,
        "mode": mode,
        "checkedAt": started_at,
        "status": incident.get("status"),
        "incidentType": incident.get("incidentType"),
        "recommendedStage": incident.get("recommendedStage"),
        "automaticAction": action,
        "wouldRun": would_run,
        "executedActions": executed_actions,
        "mutatesFeed": mutates_feed,
        "deploys": deploys or stage3_deploys,
        "snapshot": snapshot,
        "incident": incident,
        "state": state,
        "policy": "Stage 3 may prepare a separate top-feed rescue worker. It applies/deploys only after editor results exist and Quality/Publication/Live hard gates pass; otherwise it stops without publishing.",
    }


def exit_code_for_mode(mode: str, incident: dict[str, Any]) -> int:
    if mode == "dry-run":
        return 0
    return 0 if incident.get("status") in {"ok", "degraded"} else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Pointa autopilot staged self-healing")
    ap.add_argument("--mode", choices=["dry-run", "auto-repair"], default="dry-run")
    ap.add_argument("--state", default=str(STATE_PATH))
    ap.add_argument("--out", default=str(REPORT_PATH))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    started_at = now_iso()
    snapshot = collect_snapshot()
    incident = classify_incident(snapshot)
    executed_actions: list[dict[str, Any]] = []
    state_path = Path(args.state)
    loaded_state = read_json(state_path)
    if args.mode == "auto-repair":
        executed_actions, incident = execute_stage2_repair(incident)
        if incident.get("recommendedStage") == "stage_3_general_rescue":
            stage3_actions, incident, loaded_state = execute_stage3_repair(incident, loaded_state, now=started_at)
            executed_actions.extend(stage3_actions)
    state = update_state(loaded_state, incident, now=started_at)
    report = build_report(
        mode=args.mode,
        snapshot=asdict(snapshot),
        incident=incident,
        state=state,
        started_at=started_at,
        executed_actions=executed_actions,
    )
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
