#!/usr/bin/env python3
"""Quarantine item-level auditor failures without stopping the whole feed."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def item_url(item: dict[str, Any]) -> str:
    return str(item.get("sourceUrl") or item.get("url") or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", default="feed.json")
    parser.add_argument("--report", required=True)
    parser.add_argument("--quarantine", default="pointa_quarantine.json")
    args = parser.parse_args()

    feed_path = Path(args.feed)
    report_path = Path(args.report)
    quarantine_path = Path(args.quarantine)
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    items = [item for item in feed.get("items", []) if isinstance(item, dict)]
    errors = [issue for issue in report.get("errors", []) if isinstance(issue, dict)]
    error_by_url = {
        str(issue.get("url") or "").strip(): issue
        for issue in errors
        if str(issue.get("url") or "").strip()
    }
    matched_urls = {item_url(item) for item in items} & set(error_by_url)
    unresolved = [
        issue for issue in errors
        if str(issue.get("url") or "").strip() not in matched_urls
    ]
    if unresolved:
        print(json.dumps({
            "status": "system_blocker",
            "quarantined": 0,
            "unresolvedErrors": unresolved,
        }, ensure_ascii=False))
        return 2

    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    for item in items:
        url = item_url(item)
        issue = error_by_url.get(url)
        if not issue:
            kept.append(item)
            continue
        removed.append({
            "quarantinedAt": now,
            "reason": issue.get("code") or "quality_auditor_error",
            "message": issue.get("message") or "",
            "headline": item.get("headline") or item.get("title") or "",
            "source": item.get("source") or "",
            "url": url,
            "item": item,
        })

    if removed:
        feed["items"] = kept
        feed_path.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        existing = json.loads(quarantine_path.read_text(encoding="utf-8")) if quarantine_path.exists() else {}
        existing_items = existing.get("items", []) if isinstance(existing, dict) else []
        known = {
            (str(entry.get("url") or ""), str(entry.get("reason") or ""))
            for entry in existing_items if isinstance(entry, dict)
        }
        for entry in removed:
            key = (entry["url"], entry["reason"])
            if key not in known:
                existing_items.append(entry)
                known.add(key)
        quarantine_path.write_text(json.dumps({
            "schemaVersion": 2,
            "updatedAt": now,
            "items": existing_items,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": "ok",
        "quarantined": len(removed),
        "remainingItems": len(kept),
        "systemBlockers": 0,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
