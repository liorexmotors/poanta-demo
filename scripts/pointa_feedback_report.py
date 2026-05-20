#!/usr/bin/env python3
"""Poanta feedback markings reporter.

Reads stored 👍/👎 card feedback and prints either JSON or a short Hebrew
operator report. Intended for Aliza/מבקר איכות cron runs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.worker.worker.feedback_report import build_report, format_hebrew_report  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Poanta feedback markings report")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--format", choices=["json", "text"], default="text")
    ap.add_argument("--only-actionable", action="store_true", help="Exit 2 and print nothing when there are no negative/actionable markings")
    args = ap.parse_args()

    try:
        report = build_report(hours=args.hours, limit=args.limit)
    except (SystemExit, ModuleNotFoundError) as exc:
        unavailable = {
            "status": "unavailable",
            "reason": str(exc),
            "actionRequired": "Configure POANTA_DATABASE_URL/DATABASE_URL and production FEEDBACK_API_URL before live feedback can reach Aliza.",
        }
        if not args.only_actionable:
            if args.format == "json":
                print(json.dumps(unavailable, ensure_ascii=False, indent=2))
            else:
                print("חיווי סימוני פואנטה לא פעיל עדיין: חסר DATABASE_URL/POANTA_DATABASE_URL או API פרודקשן.")
        return 2

    if args.only_actionable and not report.get("actionItems"):
        return 2

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_hebrew_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
