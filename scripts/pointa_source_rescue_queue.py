#!/usr/bin/env python3
"""Build a non-blocking rescue queue for fresh important-source candidates.

Purpose: catch cases where a source has fresh RSS items, but deterministic Pointa
rewriting fails QA and the item silently disappears before the full editor sees it.
This script reports only. It does not modify feed.json, publish, or trigger repair.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import update_feed  # type: ignore

TZ = timezone(timedelta(hours=3))
IMPORTANT_SOURCES = ["הארץ", "ynet", "וואלה", "מעריב", "גלובס", "ישראל היום", "דה מרקר"]
DEFAULT_OUT = ROOT / "tmp" / "pointa_source_rescue_queue.json"


def source_group(name: str) -> str:
    low = (name or "").lower()
    if "הארץ" in name or "haaretz" in low:
        return "הארץ"
    if "דה מרקר" in name or "themarker" in low:
        return "דה מרקר"
    if "ynet" in low:
        return "ynet"
    if "וואלה" in name or "walla" in low:
        return "וואלה"
    if "מעריב" in name or "maariv" in low:
        return "מעריב"
    if "גלובס" in name or "globes" in low:
        return "גלובס"
    if "ישראל היום" in name or "israel hayom" in low:
        return "ישראל היום"
    return ""


def parse_dt(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    except Exception:
        return None


def candidate_to_item(c: Any) -> dict[str, Any]:
    c.original_title = c.original_title or c.title
    c.title = update_feed.sanitize_title(c.title)
    category, cls = update_feed.categorize_item(c.title, c.description, c.source)
    return {
        "category": category,
        "categoryClass": cls,
        "source": c.source,
        "sourceLogo": update_feed.source_logo(c.source),
        "sourceUrl": c.url,
        "imageUrl": c.image_url,
        "publishedAt": c.published_at,
        "hasSourceDate": bool(c.published_at),
        "time": "rescue-candidate",
        "headline": update_feed.poanta_headline(c.title, c.description, c.source),
        "originalTitle": c.original_title or c.title,
        "context": update_feed.context_text(c.title, c.description, c.source),
        "takeaway": update_feed.takeaway_text(category, c.title, c.description),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-min", type=int, default=180)
    ap.add_argument("--sync-profile", choices=["all", "fast", "medium", "slow"], default="all")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    now = datetime.now(TZ)
    cutoff = now - timedelta(minutes=args.max_age_min)
    rows: list[dict[str, Any]] = []

    for source in update_feed.load_sources(args.sync_profile):
        group = source_group(source.get("name", ""))
        if group not in IMPORTANT_SOURCES:
            continue
        try:
            candidates = update_feed.extract_source(source)
        except Exception as exc:
            rows.append({"sourceGroup": group, "source": source.get("name"), "status": "fetch_error", "error": str(exc)})
            continue
        candidates = sorted(candidates, key=lambda x: (x.published_at, x.score), reverse=True)
        for c in candidates[:4]:
            dt = parse_dt(c.published_at)
            if not dt or dt < cutoff:
                continue
            item = candidate_to_item(c)
            errors = update_feed.item_quality_errors(item)
            if errors:
                rows.append({
                    "sourceGroup": group,
                    "source": c.source,
                    "publishedAt": c.published_at,
                    "sourceUrl": c.url,
                    "originalTitle": c.original_title or c.title,
                    "deterministicHeadline": item["headline"],
                    "deterministicContext": item["context"],
                    "deterministicTakeaway": item["takeaway"],
                    "qaErrors": errors,
                    "recommendedAction": "send_to_full_editor_rescue_queue",
                })

    report = {
        "name": "Pointa source rescue queue",
        "mode": "shadow-report-only",
        "checkedAt": now.isoformat(timespec="seconds"),
        "maxAgeMin": args.max_age_min,
        "items": rows,
        "counts": {
            "total": len(rows),
            "bySource": {s: sum(1 for r in rows if r.get("sourceGroup") == s) for s in IMPORTANT_SOURCES},
        },
        "note": "Report only. Does not modify feed.json, publish, or trigger repair.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"items": len(rows), "out": str(out), "bySource": report["counts"]["bySource"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
