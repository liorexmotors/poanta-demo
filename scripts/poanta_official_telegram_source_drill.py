#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify IDF/Israel Police Telegram sources produce publishable Pointa cards."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_feed  # noqa: E402

TARGETS = ["דובר צה״ל - טלגרם רשמי", "דוברות משטרת ישראל - טלגרם רשמי"]


def main() -> int:
    report = {"status": "ok", "sources": []}
    ok = True
    sources = {s["name"]: s for s in update_feed.load_sources("all")}
    for name in TARGETS:
        src = sources.get(name)
        row = {"source": name, "configured": bool(src), "candidates": 0, "publishable": 0, "errors": []}
        if not src:
            row["errors"].append("source_missing")
            ok = False
            report["sources"].append(row)
            continue
        candidates = update_feed.extract_source(src)
        built = update_feed.build_feed(candidates)
        row["candidates"] = len(candidates)
        row["publishable"] = len(built.get("items", []))
        for item in built.get("items", []):
            errors = update_feed.item_quality_errors(item)
            if errors:
                row["errors"].append({"headline": item.get("headline"), "errors": errors})
        if row["candidates"] == 0:
            row["errors"].append("no_raw_candidates")
        if row["publishable"] == 0:
            row["errors"].append("no_publishable_cards")
        if row["errors"]:
            ok = False
        row["sampleHeadlines"] = [item.get("headline") for item in built.get("items", [])[:5]]
        report["sources"].append(row)
    if not ok:
        report["status"] = "fail"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
