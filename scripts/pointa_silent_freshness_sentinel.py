#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Silent Pointa freshness sentinel.

This is a non-chat operational guard for the failure mode where Poanta's local
feed/candidate pipeline moves but the public GitHub Pages feed stays stale or
thin. It never sends Telegram. It either proves the live feed is healthy,
publishes an already-healthy local candidate under the existing gates, or
prepares a rescue queue/run for the editor path.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "tmp"
TZ = timezone(timedelta(hours=3))
LIVE_FEED = "https://liorexmotors.github.io/poanta-demo/feed.json"
LAST = TMP / "pointa_silent_freshness_sentinel_last.json"
LIVE_AUDITOR_LAST = TMP / "pointa_live_auditor_last.json"


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def parse_dt(raw: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    except Exception:
        return None


def run(cmd: list[str], *, timeout: int = 180) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run_json(cmd: list[str], *, timeout: int = 120) -> tuple[int, dict[str, Any] | None, str]:
    code, text = run(cmd, timeout=timeout)
    try:
        return code, json.loads(text), text
    except Exception:
        return code, None, text


def fetch_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PointaSilentFreshnessSentinel/1.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def feed_top(feed: dict[str, Any]) -> dict[str, Any]:
    items = feed.get("items") or []
    if not items:
        return {}
    return items[0] if isinstance(items[0], dict) else {}


def feed_signature(feed: dict[str, Any]) -> dict[str, Any]:
    top = feed_top(feed)
    return {
        "updatedAt": feed.get("updatedAt"),
        "topPublishedAt": top.get("publishedAt"),
        "topHeadline": top.get("headline"),
        "topUrl": top.get("sourceUrl"),
        "items": len(feed.get("items") or []),
    }


def local_candidate_health() -> tuple[bool, dict[str, Any], dict[str, Any]]:
    qg_code, qg_text = run([sys.executable, "scripts/pointa_quality_gate.py", "--report", "tmp/sentinel_quality_gate.md"], timeout=90)
    health_code, health, health_text = run_json([
        sys.executable,
        "scripts/pointa_publication_health_gate.py",
        "--mode",
        "candidate",
        "--feed",
        "feed.json",
        "--out",
        "tmp/sentinel_candidate_health.json",
        "--json",
    ], timeout=90)
    ok = qg_code == 0 and health_code == 0 and bool(health and health.get("status") == "ok")
    return ok, {"exit": qg_code, "textTail": qg_text[-1500:]}, health or {"exit": health_code, "rawTail": health_text[-1500:]}


def local_is_ahead_and_healthy(live: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    local = json.loads((ROOT / "feed.json").read_text(encoding="utf-8"))
    ok, qg, health = local_candidate_health()
    local_sig = feed_signature(local)
    live_sig = feed_signature(live)
    local_top_dt = parse_dt(local_sig.get("topPublishedAt"))
    live_top_dt = parse_dt(live_sig.get("topPublishedAt"))
    updated_local_dt = parse_dt(local_sig.get("updatedAt"))
    updated_live_dt = parse_dt(live_sig.get("updatedAt"))
    ahead = False
    if local_top_dt and live_top_dt and local_top_dt > live_top_dt + timedelta(minutes=2):
        ahead = True
    if updated_local_dt and updated_live_dt and updated_local_dt > updated_live_dt + timedelta(minutes=5):
        ahead = True
    if local_sig.get("topUrl") and local_sig.get("topUrl") != live_sig.get("topUrl") and local_top_dt and live_top_dt and local_top_dt >= live_top_dt:
        ahead = True
    return ok and ahead, {"candidateOk": ok, "ahead": ahead, "local": local_sig, "live": live_sig, "qualityGate": qg, "health": health}


def audit_live() -> tuple[dict[str, Any] | None, str]:
    url = LIVE_FEED + f"?sentinel={int(datetime.now(TZ).timestamp() * 1000)}"
    code, audit, raw = run_json([sys.executable, "scripts/pointa_live_auditor.py", "--url", url, "--json"], timeout=90)
    if audit:
        LIVE_AUDITOR_LAST.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return audit, raw
    return None, raw


def build_rescue_queue() -> dict[str, Any]:
    run([sys.executable, "scripts/pointa_source_rescue_queue.py", "--sync-profile", "all", "--max-age-min", "180", "--per-source", "10", "--auditor", str(LIVE_AUDITOR_LAST)], timeout=180)
    queue_path = TMP / "pointa_source_rescue_queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else {}
    code, text = run([sys.executable, "scripts/pointa_rescue_editor_pipeline.py", "prepare", "--limit", "24", "--batch-size", "8", "--oversample-factor", "4"], timeout=240)
    run_dir = ""
    for line in text.splitlines():
        if line.startswith(str(ROOT / "tmp" / "editor-runs")):
            run_dir = line.strip()
            break
    return {"queueItems": len(queue.get("items") or []), "runDir": run_dir, "prepareExit": code, "prepareTail": text[-2000:]}


def write_result(result: dict[str, Any]) -> None:
    TMP.mkdir(exist_ok=True)
    LAST.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repair", action="store_true", help="Attempt deterministic repair/deploy when live is stale")
    ap.add_argument("--no-deploy", action="store_true", help="Do not publish even if local candidate is healthy")
    args = ap.parse_args()

    started = now_iso()
    try:
        live_feed = fetch_json(LIVE_FEED + f"?sentinelFeed={int(datetime.now(TZ).timestamp()*1000)}")
    except Exception as exc:
        live_feed = {}
        fetch_error = str(exc)
    else:
        fetch_error = ""

    audit, audit_raw = audit_live()
    live_ok = bool(audit and audit.get("status") == "ok")
    result: dict[str, Any] = {
        "sentinel": "pointa_silent_freshness_sentinel",
        "checkedAt": started,
        "status": "ok" if live_ok else "fail",
        "live": feed_signature(live_feed) if live_feed else {"error": fetch_error},
        "liveAuditor": {"status": audit.get("status") if audit else None, "errors": (audit or {}).get("errors", [])[:8], "warnings": (audit or {}).get("warnings", [])[:8]},
        "actions": [],
    }

    if live_ok:
        ahead, detail = local_is_ahead_and_healthy(live_feed)
        result["localVsLive"] = detail
        if ahead and args.repair and not args.no_deploy:
            code, text = run(["bash", "scripts/deploy_current_feed.sh"], timeout=900)
            result["actions"].append({"action": "deploy_healthy_local_candidate", "exit": code, "tail": text[-3000:]})
            audit2, _ = audit_live()
            result["postDeployLiveAuditor"] = {"status": audit2.get("status") if audit2 else None, "errors": (audit2 or {}).get("errors", [])[:5]}
            result["status"] = "ok" if audit2 and audit2.get("status") == "ok" else "fail"
        write_result(result)
        return 0 if result["status"] == "ok" else 1

    if not args.repair:
        write_result(result)
        return 1

    # First try the normal deterministic FAST sync/deploy path.
    code, text = run(["bash", "scripts/fast_sync_and_deploy_feed.sh"], timeout=900)
    result["actions"].append({"action": "fast_sync_and_deploy", "exit": code, "tail": text[-3000:]})

    # If FAST produced a healthy local candidate but did not get it live, publish it.
    try:
        live_after_fast = fetch_json(LIVE_FEED + f"?afterFast={int(datetime.now(TZ).timestamp()*1000)}")
    except Exception:
        live_after_fast = live_feed
    ahead, detail = local_is_ahead_and_healthy(live_after_fast)
    result["localVsLiveAfterFast"] = detail
    if ahead and not args.no_deploy:
        code2, text2 = run(["bash", "scripts/deploy_current_feed.sh"], timeout=900)
        result["actions"].append({"action": "deploy_healthy_local_candidate_after_fast", "exit": code2, "tail": text2[-3000:]})

    audit_after, _ = audit_live()
    if audit_after and audit_after.get("status") == "ok":
        result["postRepairLiveAuditor"] = {"status": "ok", "errors": []}
        result["status"] = "ok"
        write_result(result)
        return 0

    # Still stale/thin: prepare full-editor rescue so the next agent turn has a
    # concrete batch instead of silently stopping after FAST failed.
    rescue = build_rescue_queue()
    result["actions"].append({"action": "prepare_source_rescue_editor_run", **rescue})
    result["status"] = "rescue_prepared" if rescue.get("queueItems", 0) else "blocked_no_rescue_candidates"
    write_result(result)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
