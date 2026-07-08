#!/usr/bin/env python3
"""Promote Feed B into the live feed without legacy Feed A gates."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FEED_B = ROOT / "feed_b.json"
LIVE_FEED = ROOT / "feed.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def item_url(item: dict[str, Any]) -> str:
    return str(item.get("url") or item.get("sourceUrl") or item.get("link") or "").strip()


def item_title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("headline") or "").strip()


def item_summary(item: dict[str, Any]) -> str:
    return str(item.get("summary") or item.get("subtitle") or item.get("context") or "").strip()


def default_image_kind(item: dict[str, Any]) -> str:
    blob = " ".join(
        str(item.get(key) or "")
        for key in ("category", "categoryClass", "source", "sourceLogo", "title", "headline")
    ).lower()
    if "מזג" in blob:
        return "weather"
    if any(term in blob for term in ("ביטחון", "צבא", "חמאס", "איראן", "חיזבאללה", "עזה")):
        return "security"
    if any(term in blob for term in ("פוליט", "ממשלה", "כנסת", "בג״ץ", "בג\"ץ")):
        return "politics"
    if any(term in blob for term in ("כלכלה", "בורסה", "עסקים", "נדל")):
        return "economy"
    if any(term in blob for term in ("טכנולוג", "הייטק", "ai")):
        return "tech"
    if "ספורט" in blob:
        return "sports"
    if any(term in blob for term in ("תרבות", "בידור", "רכילות")):
        return "culture"
    if any(term in blob for term in ("עולם", "global", "jazeera", "bbc", "reuters", "france24")):
        return "world"
    if any(term in blob for term in ("מקומי", "עירוני", "רכב", "תחבורה")):
        return "local"
    return "news"


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    fixed = dict(item)
    url = item_url(fixed)
    title = item_title(fixed)
    summary = item_summary(fixed)
    fixed["url"] = url
    if title and not fixed.get("title"):
        fixed["title"] = title
    if summary and not fixed.get("summary"):
        fixed["summary"] = summary
    if not str(fixed.get("imageUrl") or "").strip():
        kind = default_image_kind(fixed)
        fixed["imageUrl"] = f"https://poanta-demo.pages.dev/assets/feed-defaults/{kind}.png"
        fixed["imageFallbackKind"] = kind
    return fixed


def promote(source: dict[str, Any], *, limit: int, min_items: int) -> dict[str, Any]:
    now = datetime.now(timezone(timedelta(hours=3))).isoformat(timespec="seconds")
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in source.get("items") or []:
        if not isinstance(raw, dict):
            continue
        item = normalize_item(raw)
        url = item_url(item)
        if not url or url in seen:
            continue
        if len(item_title(item)) < 6:
            continue
        selected.append(item)
        seen.add(url)
        if limit > 0 and len(selected) >= limit:
            break
    if len(selected) < min_items:
        raise SystemExit(f"Feed B live promotion too small: {len(selected)} items")
    return {
        "updatedAt": source.get("updatedAt") or source.get("generatedAt") or now,
        "mode": "feed-b-live",
        "source": "Poenta Feed B promoted directly to live feed.json",
        "promotedAt": now,
        "items": selected,
        "errors": [],
        "breakingFeed": "breaking_feed.json is managed separately and is not replaced by Feed B.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(FEED_B))
    ap.add_argument("--out", default=str(LIVE_FEED))
    ap.add_argument("--limit", type=int, default=0, help="Maximum items to promote; 0 means all eligible 7-day Feed B items")
    ap.add_argument("--min-items", type=int, default=20)
    args = ap.parse_args()

    payload = promote(load_json(Path(args.source)), limit=args.limit, min_items=args.min_items)
    write_json(Path(args.out), payload)
    print(json.dumps({
        "ok": True,
        "out": args.out,
        "mode": payload.get("mode"),
        "updatedAt": payload.get("updatedAt"),
        "items": len(payload.get("items") or []),
        "topPublishedAt": (payload.get("items") or [{}])[0].get("publishedAt"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
