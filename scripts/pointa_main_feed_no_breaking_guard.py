#!/usr/bin/env python3
"""Hard guard: the main Poanta feed must not contain breaking/live-like rows.

This guard intentionally checks the full main feed, not only the top cards.  The
breaking feed is allowed to contain Rotter/Telegram/live rows; feed.json is not.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEED = ROOT / "feed.json"

LIVE_URL_PATTERNS = (
    "/break/",
    "rotter.net/forum/scoops",
    "rotter.net/forum/scoops1",
    "t.me/",
    "telegram.me/",
)
LIVE_TEXT_PATTERNS = (
    "מבזק",
    "מבזקים",
    "טלגרם",
    "telegram",
    "rotter",
    "רוטר",
)


def item_text(item: dict[str, Any]) -> str:
    fields = [
        item.get("sourceUrl"),
        item.get("source"),
        item.get("sourceLogo"),
        item.get("headline"),
        item.get("originalTitle"),
        item.get("category"),
    ]
    if isinstance(item.get("sourceLinks"), list):
        for link in item.get("sourceLinks") or []:
            if isinstance(link, dict):
                fields.append(link.get("url"))
                fields.append(link.get("name"))
    return " ".join(str(x or "") for x in fields)


def leak_reasons(item: dict[str, Any]) -> list[str]:
    text = item_text(item)
    low = text.lower()
    reasons: list[str] = []
    if item.get("breaking") is True:
        reasons.append("breaking:true")
    if item.get("promotedFromBreaking") is True:
        reasons.append("promotedFromBreaking:true")
    if item.get("emergencyFreshnessFallback") is True:
        reasons.append("emergencyFreshnessFallback:true")
    for pat in LIVE_URL_PATTERNS:
        if pat in low:
            reasons.append(f"live_url:{pat}")
    for pat in LIVE_TEXT_PATTERNS:
        haystack = low if re.fullmatch(r"[A-Za-z]+", pat) else text
        needle = pat.lower() if haystack is low else pat
        if needle in haystack:
            reasons.append(f"live_text:{pat}")
    return reasons


def load_feed(path_or_url: str) -> dict[str, Any]:
    if path_or_url.startswith(("http://", "https://")):
        req = urllib.request.Request(path_or_url, headers={"User-Agent": "PoantaMainFeedNoBreakingGuard/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    path = Path(path_or_url)
    if not path.is_absolute():
        path = ROOT / path
    return json.loads(path.read_text(encoding="utf-8"))


def run(path_or_url: str, *, top: int | None = None) -> dict[str, Any]:
    feed = load_feed(path_or_url)
    items = feed.get("items") or []
    if top is not None:
        items = items[:top]
    leaks = []
    for idx, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        reasons = leak_reasons(item)
        if reasons:
            leaks.append(
                {
                    "index": idx,
                    "id": item.get("id"),
                    "source": item.get("source") or item.get("sourceLogo"),
                    "category": item.get("category"),
                    "headline": item.get("headline") or item.get("title") or item.get("originalTitle"),
                    "sourceUrl": item.get("sourceUrl"),
                    "reasons": reasons,
                }
            )
    return {
        "guard": "pointa_main_feed_no_breaking_guard",
        "status": "fail" if leaks else "ok",
        "checkedItems": len(items),
        "leakCount": len(leaks),
        "leaks": leaks,
        "rule": "feed.json must contain full Pointa article cards only; breaking/live-like rows belong only in breaking_feed.json.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=str(DEFAULT_FEED), help="feed.json path or URL")
    ap.add_argument("--top", type=int, default=None, help="optional top-N check")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = run(args.feed, top=args.top)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Poanta main-feed no-breaking guard: {report['status']} · leaks={report['leakCount']} checked={report['checkedItems']}")
        for leak in report["leaks"][:12]:
            print(f"- #{leak['index']} {leak.get('source')}: {leak.get('headline')} ({', '.join(leak['reasons'])})")
    return 1 if report["leaks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
