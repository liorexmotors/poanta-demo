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


def main() -> int:
    live = load_json(TMP / "pointa_live_auditor_last.json")
    timing = load_json(TMP / "pointa_timing_auditor_last.json")
    health = load_json(TMP / "pointa_publication_health_gate.json")
    autopilot = load_json(TMP / "pointa_autopilot_state.json")

    generated = datetime.now(TZ).isoformat(timespec="seconds")
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
    }
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "generatedAt": generated, "agents": len(snapshot["agents"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
