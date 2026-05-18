#!/usr/bin/env python3
"""Compute Pointa editor-review engagement scores from local/debug events.

Input event format matches browser localStorage `pointa:engagement-events:v1`:
[
  {"type":"impression","key":"...","ts":1710000000000,"category":"...","source":"...","publishedAt":"..."},
  {"type":"source_open","key":"..."},
  {"type":"quick_return","key":"..."},
  {"type":"dwell","key":"...","ms":2400}
]

This script intentionally scores cards relatively against peer groups, not by nominal
counts. It is a QA/local tool; production analytics can use the same logic server-side.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

AGE_BUCKETS = (
    (2, "0-2h"),
    (6, "2-6h"),
    (24, "6-24h"),
    (72, "1-3d"),
)

DEFAULT_WEIGHTS = {
    "openGap": 0.40,
    "quickReturnGap": 0.25,
    "unsatisfiedReadGap": 0.20,
    "saveWeakness": 0.10,
    "dwellWeakness": 0.05,
}


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        # Browser events use milliseconds; tolerate seconds too.
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def age_bucket(published_at: Any, now: datetime) -> str:
    dt = parse_time(published_at)
    if not dt:
        return "3d+"
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    hours = max(0.0, (now - dt).total_seconds() / 3600)
    for upper, label in AGE_BUCKETS:
        if hours <= upper:
            return label
    return "3d+"


def percentile(values: list[float], value: float) -> int:
    if not values:
        return 50
    values = sorted(values)
    below_or_equal = sum(1 for v in values if v <= value)
    return round((below_or_equal / len(values)) * 100)


def aggregate(events: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for event in events:
        key = str(event.get("key") or "").strip()
        if not key:
            continue
        row = rows.setdefault(
            key,
            {
                "key": key,
                "category": event.get("category") or "",
                "source": event.get("source") or "",
                "publishedAt": event.get("publishedAt") or "",
                "impression": 0,
                "source_open": 0,
                "quick_return": 0,
                "save": 0,
                "unsave": 0,
                "mark_read": 0,
                "dwell_ms": 0,
            },
        )
        for field in ("category", "source", "publishedAt"):
            if event.get(field) and not row.get(field):
                row[field] = event[field]
        event_type = event.get("type")
        if event_type == "dwell":
            row["dwell_ms"] += max(0, int(float(event.get("ms") or 0)))
        elif event_type in row:
            row[event_type] += 1
    out = []
    for row in rows.values():
        impressions = row["impression"] or 0
        opens = row["source_open"] or 0
        row["ageBucket"] = age_bucket(row.get("publishedAt"), now)
        row["openRate"] = opens / impressions if impressions else 0.0
        row["quickReturnRate"] = row["quick_return"] / opens if opens else 0.0
        row["saveRate"] = row["save"] / impressions if impressions else 0.0
        row["readWithoutOpenRate"] = max(0, row["mark_read"] - opens) / impressions if impressions else 0.0
        row["avgDwellMs"] = row["dwell_ms"] / impressions if impressions else 0.0
        out.append(row)
    return out


def peer_rows(rows: list[dict[str, Any]], row: dict[str, Any], min_peer_cards: int) -> tuple[str, list[dict[str, Any]]]:
    stages = [
        ("category+source+age", lambda r: r.get("category") == row.get("category") and r.get("source") == row.get("source") and r.get("ageBucket") == row.get("ageBucket")),
        ("category+age", lambda r: r.get("category") == row.get("category") and r.get("ageBucket") == row.get("ageBucket")),
        ("age", lambda r: r.get("ageBucket") == row.get("ageBucket")),
        ("all", lambda r: True),
    ]
    for name, pred in stages:
        peers = [r for r in rows if r.get("key") != row.get("key") and pred(r)]
        if len(peers) >= min_peer_cards or name == "all":
            return name, peers
    return "all", []


def score_rows(
    rows: list[dict[str, Any]],
    min_impressions: int = 30,
    min_peer_cards: int = 8,
) -> list[dict[str, Any]]:
    eligible = [r for r in rows if r.get("impression", 0) >= min_impressions]
    scored = []
    for row in eligible:
        peer_group, peers = peer_rows(eligible, row, min_peer_cards)

        def pct(field: str) -> int:
            return percentile([float(p.get(field) or 0) for p in peers], float(row.get(field) or 0))

        open_gap = pct("openRate")
        quick_return_gap = pct("quickReturnRate")
        unsatisfied_read_gap = 100 - pct("readWithoutOpenRate")
        save_weakness = 100 - pct("saveRate")
        dwell_weakness = 100 - pct("avgDwellMs")
        score = round(
            DEFAULT_WEIGHTS["openGap"] * open_gap
            + DEFAULT_WEIGHTS["quickReturnGap"] * quick_return_gap
            + DEFAULT_WEIGHTS["unsatisfiedReadGap"] * unsatisfied_read_gap
            + DEFAULT_WEIGHTS["saveWeakness"] * save_weakness
            + DEFAULT_WEIGHTS["dwellWeakness"] * dwell_weakness
        )
        review_level = "normal"
        if score >= 85:
            review_level = "urgent_editor_review"
        elif score >= 75:
            review_level = "editor_review_candidate"
        elif score >= 60:
            review_level = "watchlist"
        scored.append(
            {
                **row,
                "peerGroup": peer_group,
                "peerCount": len(peers),
                "openGap": open_gap,
                "quickReturnGap": quick_return_gap,
                "unsatisfiedReadGap": unsatisfied_read_gap,
                "saveWeakness": save_weakness,
                "dwellWeakness": dwell_weakness,
                "editorReviewScore": score,
                "reviewLevel": review_level,
            }
        )
    return sorted(scored, key=lambda r: r["editorReviewScore"], reverse=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute relative Pointa editor-review scores")
    ap.add_argument("events", type=Path, help="JSON file with engagement events")
    ap.add_argument("--out", type=Path, help="Write scored rows to JSON")
    ap.add_argument("--min-impressions", type=int, default=30)
    ap.add_argument("--min-peer-cards", type=int, default=8)
    args = ap.parse_args()

    events = json.loads(args.events.read_text(encoding="utf-8"))
    if not isinstance(events, list):
        raise SystemExit("events JSON must be a list")
    rows = aggregate(events, datetime.now(timezone.utc))
    scored = score_rows(rows, args.min_impressions, args.min_peer_cards)
    result = {
        "totalCardsWithEvents": len(rows),
        "eligibleCards": len(scored),
        "minImpressions": args.min_impressions,
        "minPeerCards": args.min_peer_cards,
        "reviewCandidates": [r for r in scored if r["editorReviewScore"] >= 75],
        "scores": scored,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
