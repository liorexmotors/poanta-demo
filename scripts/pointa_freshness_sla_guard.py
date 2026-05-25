#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pointa feed freshness SLA guard.

Independent, deterministic guard for the live Poanta feed. This is deliberately
outside the normal OpenClaw cron fan-out: it checks the public outcome, tries the
safe local repair path, and escalates exactly once per incident to an agent run
when editorial rescue is required.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "tmp"
STATE = TMP / "pointa_freshness_sla_guard_state.json"
LOG = TMP / "pointa_freshness_sla_guard.jsonl"
LOCK = Path("/tmp/pointa-freshness-sla-guard.lock")
TZ = timezone(timedelta(hours=3))
AGENT_COOLDOWN_SEC = 20 * 60


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def run(cmd: list[str], timeout: int = 240) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run_json(cmd: list[str], timeout: int = 180) -> tuple[int, dict[str, Any] | None, str]:
    code, text = run(cmd, timeout=timeout)
    try:
        return code, json.loads(text), text
    except Exception:
        return code, None, text


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict[str, Any]) -> None:
    TMP.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def log_event(event: dict[str, Any]) -> None:
    TMP.mkdir(exist_ok=True)
    event = {"ts": now_iso(), **event}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    print(json.dumps(event, ensure_ascii=False))


def incident_key(audit: dict[str, Any]) -> str:
    top = (audit.get("top") or [{}])[0]
    codes = ",".join(sorted({str(e.get("code")) for e in audit.get("errors") or []}))
    return "|".join([str(audit.get("updatedAt") or ""), str(top.get("publishedAt") or ""), str(top.get("url") or ""), codes])


def should_escalate(state: dict[str, Any], key: str) -> bool:
    last_key = state.get("lastEscalationKey")
    last_at = float(state.get("lastEscalationAt") or 0)
    if key != last_key:
        return True
    return time.time() - last_at > AGENT_COOLDOWN_SEC


def agent_message(audit: dict[str, Any], sentinel: dict[str, Any] | None) -> str:
    errors = audit.get("errors") or []
    top = (audit.get("top") or [{}])[0]
    rescue = None
    if sentinel:
        for action in sentinel.get("actions") or []:
            if action.get("action") == "prepare_source_rescue_editor_run":
                rescue = action
    run_dir = rescue.get("runDir") if rescue else ""
    return f"""Poanta freshness SLA breach detected by independent guard.
Live feed is stale/thin. Do not ask Lior for decisions; operate under feed-autonomy hard gates.

Live updatedAt: {audit.get('updatedAt')}
Top item: {top.get('publishedAt')} · {top.get('source')} · {top.get('headline')}
Errors: {json.dumps(errors[:5], ensure_ascii=False)}
Prepared rescue run: {run_dir}

Required action:
1. If {run_dir!r} has batch files and missing results, edit all batches with Pointa editor rules.
2. Run editor QA/apply, Quality Gate, publication health gate.
3. Deploy only if gates pass.
4. Re-run live auditor and report concise outcome.
5. Strengthen a deterministic guard if this incident exposes a repeated failure class.
"""


def escalate_to_agent(audit: dict[str, Any], sentinel: dict[str, Any] | None) -> tuple[int, str]:
    msg = agent_message(audit, sentinel)
    return run([
        "openclaw", "agent",
        "--agent", "main",
        "--message", msg,
        "--timeout", "1200",
        "--json",
    ], timeout=1250)


def main() -> int:
    # advisory lock without external flock dependency
    try:
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        # stale lock cleanup after 15 minutes
        try:
            if time.time() - LOCK.stat().st_mtime > 900:
                LOCK.unlink()
            else:
                log_event({"status": "skip", "reason": "locked"})
                return 0
        except Exception:
            return 0
    try:
        state = load_state()
        code, audit, raw = run_json([sys.executable, "scripts/pointa_live_auditor.py", "--json"], timeout=120)
        if not audit:
            log_event({"status": "audit_error", "exit": code, "tail": raw[-1000:]})
            return 2
        if audit.get("status") == "ok":
            state["lastOkAt"] = now_iso()
            save_state(state)
            log_event({"status": "ok", "updatedAt": audit.get("updatedAt"), "top": (audit.get("top") or [{}])[0]})
            return 0

        # Safe deterministic repair first. It deploys only when existing hard gates pass;
        # otherwise it prepares a rescue editor run.
        s_code, sentinel, s_raw = run_json([sys.executable, "scripts/pointa_silent_freshness_sentinel.py", "--repair"], timeout=600)
        if sentinel and sentinel.get("status") == "ok":
            log_event({"status": "repaired", "actions": [a.get("action") for a in sentinel.get("actions") or []]})
            return 0

        key = incident_key(audit)
        if should_escalate(state, key):
            a_code, a_text = escalate_to_agent(audit, sentinel)
            state["lastEscalationKey"] = key
            state["lastEscalationAt"] = time.time()
            state["lastEscalationAtIso"] = now_iso()
            save_state(state)
            log_event({"status": "escalated", "agentExit": a_code, "sentinelStatus": (sentinel or {}).get("status"), "tail": a_text[-1500:]})
            return 1 if a_code else 0

        log_event({"status": "incident_already_escalated", "sentinelStatus": (sentinel or {}).get("status")})
        return 1
    finally:
        try:
            LOCK.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
