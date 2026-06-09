#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hard publication health gate for Poanta feed automation.

This is the shared P0 guard for האספן / השוער / המבקר / המתקן.
A job is not allowed to claim success merely because it ran or committed files.
It must prove the candidate/public feed has user-visible freshness.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

CRITICAL_LIVE_CODES = {
    "empty_feed",
    "missing_updated_at",
    "stale_updated_at",
    "top_missing_published_at",
    "no_new_top_item_sla",
    "stale_top_item",
    "too_few_fresh_top_items",
    "too_few_recent_items_sla",
    "too_few_recent_sources_sla",
    "weather_on_top",
    "summary_fragment_headline",
    "headline_too_close_to_source",
    "generic_takeaway_regression",
}

CRITICAL_TIMING_GROUPS = {"all", "important", "foreign"}


def run_json(cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}")
    out = proc.stdout.strip()
    if not out:
        raise RuntimeError(f"command produced no JSON: {' '.join(cmd)}")
    return json.loads(out)


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def live_blockers(live: dict[str, Any], *, mode: str) -> list[dict[str, Any]]:
    blockers = []
    for err in live.get("errors") or []:
        code = err.get("code")
        # Public mode treats cache mismatch as a blocker; local candidate mode
        # cannot compare GitHub Pages to raw and ignores source-view warnings.
        if code in CRITICAL_LIVE_CODES or (mode == "public" and code == "live_raw_mismatch"):
            blockers.append(err)
    return blockers


def timing_blockers(timing: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = []
    for err in timing.get("errors") or []:
        if err.get("code") != "publication_timing_sla":
            blockers.append(err)
            continue
        if err.get("group") in CRITICAL_TIMING_GROUPS:
            blockers.append(err)
    return blockers


def main() -> int:
    ap = argparse.ArgumentParser(description="Poanta hard publication health gate")
    ap.add_argument("--mode", choices=["candidate", "public"], default="candidate")
    ap.add_argument("--feed", default="feed.json", help="Candidate feed path for --mode=candidate")
    ap.add_argument("--timing", action="store_true", help="Also check critical timing groups")
    ap.add_argument("--out", default="tmp/pointa_publication_health_gate.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.mode == "candidate":
        live = run_json([sys.executable, "scripts/pointa_live_auditor.py", "--feed-file", args.feed, "--json"])
        no_breaking = run_json([sys.executable, "scripts/pointa_main_feed_no_breaking_guard.py", "--feed", args.feed, "--json"])
    else:
        live = run_json([sys.executable, "scripts/pointa_live_auditor.py", "--json"])
        no_breaking = run_json([sys.executable, "scripts/pointa_main_feed_no_breaking_guard.py", "--feed", "feed.json", "--json"])

    blockers = live_blockers(live, mode=args.mode)
    for leak in no_breaking.get("leaks") or []:
        blockers.append({
            "code": "main_feed_breaking_leak",
            "message": "feed.json contains a breaking/live-like item that belongs only in breaking_feed.json",
            "item": leak,
        })
    timing = None
    if args.timing:
        timing = run_json([sys.executable, "scripts/pointa_timing_auditor.py", "--json"])
        blockers.extend(timing_blockers(timing))

    report = {
        "gate": "pointa_publication_health_gate",
        "mode": args.mode,
        "status": "fail" if blockers else "ok",
        "liveStatus": live.get("status"),
        "noBreakingStatus": no_breaking.get("status"),
        "noBreakingLeaks": no_breaking.get("leaks") or [],
        "timingStatus": timing.get("status") if timing else None,
        "blockers": blockers,
        "liveErrors": live.get("errors") or [],
        "timingErrors": timing.get("errors") if timing else [],
        "top": (live.get("top") or [])[:5],
        "rule": "No script/agent may report OK if the candidate/public feed still violates visible freshness/quantity SLA.",
    }
    write_report(ROOT / args.out, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Pointa publication health gate: {report['status']} · blockers={len(blockers)}")
        for b in blockers[:8]:
            print(f"- {b.get('code')} {b.get('group','')}: {b.get('message','')}")
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
