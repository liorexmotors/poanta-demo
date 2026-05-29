#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Drill every active Poanta source for extraction coverage.

This catches source-level regressions where an RSS/Telegram endpoint is configured
but update_feed.extract_source() silently returns no usable candidates.
It does not modify feed.json or publish anything.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import update_feed  # type: ignore

SOURCES_PATH = ROOT / "rss_sources.json"
DEFAULT_OUT = ROOT / "tmp" / "poanta_all_sources_extract_drill.json"


def _timeout_handler(signum: int, frame: object) -> None:
    raise TimeoutError("source extraction timeout")


def load_active_sources() -> list[dict[str, Any]]:
    data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    return [src for src in data.get("active", []) if isinstance(src, dict)]


def audit_source(source: dict[str, Any], timeout: int) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "name": source.get("name", ""),
        "rss": source.get("rss"),
        "telegram": source.get("telegram"),
        "categoryHint": source.get("categoryHint"),
        "logo": source.get("logo"),
    }
    start = time.time()
    try:
        signal.alarm(timeout)
        candidates = update_feed.extract_source(source)
        signal.alarm(0)
        rec["ok"] = bool(candidates)
        rec["candidateCount"] = len(candidates)
        rec["durationSec"] = round(time.time() - start, 2)
        if candidates:
            first = candidates[0]
            rec["sample"] = {
                "title": getattr(first, "title", ""),
                "url": getattr(first, "url", ""),
                "publishedAt": getattr(first, "published_at", ""),
            }
        else:
            rec["error"] = "no_candidates"
    except Exception as exc:  # noqa: BLE001 - report drill diagnostics, do not crash mid-source
        signal.alarm(0)
        rec["ok"] = False
        rec["candidateCount"] = 0
        rec["durationSec"] = round(time.time() - start, 2)
        rec["error"] = repr(exc)[:400]
    return rec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--timeout", type=int, default=18)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    signal.signal(signal.SIGALRM, _timeout_handler)
    sources = load_active_sources()
    results = [audit_source(src, args.timeout) for src in sources]
    failures = [r for r in results if not r.get("ok")]
    report = {
        "ok": not failures,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceCount": len(results),
        "withCandidates": sum(1 for r in results if r.get("candidateCount", 0) > 0),
        "failureCount": len(failures),
        "failures": failures,
        "results": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False, indent=2))
    else:
        print(f"sources={report['sourceCount']} withCandidates={report['withCandidates']} failures={report['failureCount']} out={out}")
        for failure in failures[:30]:
            print(f"FAIL {failure.get('name')}: {failure.get('error')}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
