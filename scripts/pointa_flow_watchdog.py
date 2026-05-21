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
    timing_code, timing, timing_err = run_json([sys.executable, "scripts/pointa_timing_auditor.py", "--json"])
    quality_code, quality, quality_err = run_json([sys.executable, "scripts/pointa_quality_auditor.py", "--json"])
    drill_code, drill, drill_err = run_json([sys.executable, "scripts/poanta_p0_stuck_feed_drill.py"])
    qg_code, qg_text = run_text([sys.executable, "scripts/pointa_quality_gate.py", "--report", "tmp/flow_watchdog_quality_gate.md"])

    if not live:
        errors.append({"code": "live_auditor_unreadable", "message": live_err.strip()})
    else:
        errors.extend({**e, "owner": "המבקר"} for e in live.get("errors", []))
        warnings.extend({**w, "owner": "המבקר"} for w in live.get("warnings", []))

    if not timing:
        errors.append({"code": "timing_auditor_unreadable", "message": timing_err.strip()})
    else:
        errors.extend({**e, "owner": "מבקר התזמון"} for e in timing.get("errors", []))
        warnings.extend({**w, "owner": "מבקר התזמון"} for w in timing.get("warnings", []))

    if not quality:
        errors.append({"code": "quality_auditor_unreadable", "message": quality_err.strip()})
    else:
        errors.extend({**e, "owner": "השוער"} for e in quality.get("errors", []))
        warnings.extend({**w, "owner": "השוער"} for w in quality.get("warnings", []))

    if qg_code != 0:
        errors.append({"code": "quality_gate_failed", "owner": "השוער", "message": qg_text[:1200]})

    if not drill or drill_code != 0 or not all(drill.get(k) for k in ["staleFeedBlocked", "freshFeedPasses", "badGossipBlocked"]):
        errors.append({"code": "p0_drill_failed", "owner": "המעורר", "message": drill_err.strip() or json.dumps(drill, ensure_ascii=False)})

    try:
        feed = fetch_live_feed()
        errors.extend({**e, "owner": "השוער/האספן"} for e in image_presence_findings(feed))
    except Exception as exc:
        errors.append({"code": "live_feed_fetch_failed", "owner": "המבקר", "message": str(exc)})

    result = {
        "watchdog": "pointa_flow_watchdog",
        "checkedAt": checked_at,
        "status": "fail" if errors else "ok",
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "live": live.get("status") if live else None,
            "timing": timing.get("status") if timing else None,
            "quality": quality.get("status") if quality else None,
            "qualityGateExit": qg_code,
            "p0Drill": drill,
        },
    }
    out = ROOT / "tmp" / "pointa_flow_watchdog_last.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
