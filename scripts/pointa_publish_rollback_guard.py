#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prevent Poanta production feed rollbacks.

The publishing pipeline may have multiple targets (GitHub main, gh-pages,
Cloudflare Pages production/custom domain). This guard compares the candidate
feed being deployed against the freshest known/public feed and blocks a deploy
that would move production backwards.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "tmp" / "last_public_feed_fingerprint.json"
DEFAULT_PUBLIC_URLS = [
    "https://www.poenta.app/feed.json",
    "https://poenta.app/feed.json",
    "https://poanta-demo.pages.dev/feed.json",
    "https://raw.githubusercontent.com/liorexmotors/poanta-demo/main/feed.json",
    "https://raw.githubusercontent.com/liorexmotors/poanta-demo/gh-pages/feed.json",
]


def parse_iso(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        value = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def read_feed(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8")), raw


def feed_fingerprint(feed: dict[str, Any], raw: bytes | None = None, *, source: str = "") -> dict[str, Any]:
    items = feed.get("items") or []
    top = items[0] if items and isinstance(items[0], dict) else {}
    updated = feed.get("updatedAt")
    top_published = top.get("publishedAt") or top.get("timestamp") or top.get("createdAt")
    updated_dt = parse_iso(updated)
    top_dt = parse_iso(top_published)
    # Use topPublishedAt as primary freshness: what the user sees first. Use
    # updatedAt as a secondary tiebreaker because some builds can refresh metadata
    # without adding a newer top card.
    sort_key = (
        top_dt.timestamp() if top_dt else float("-inf"),
        updated_dt.timestamp() if updated_dt else float("-inf"),
        len(items),
    )
    return {
        "source": source,
        "updatedAt": updated,
        "topPublishedAt": top_published,
        "itemCount": len(items),
        "topHeadline": (top.get("headline") or top.get("title") or "")[:180],
        "sha256": hashlib.sha256(raw or json.dumps(feed, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "sortKey": sort_key,
    }


def fetch_public(url: str) -> dict[str, Any]:
    try:
        sep = "&" if "?" in url else "?"
        req = urllib.request.Request(
            f"{url}{sep}rollbackGuard={int(datetime.now(timezone.utc).timestamp())}",
            headers={"User-Agent": "PointaRollbackGuard/1.0", "Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read()
        return feed_fingerprint(json.loads(raw.decode("utf-8")), raw, source=url)
    except Exception as exc:
        return {"source": url, "error": f"{type(exc).__name__}: {exc}", "sortKey": (float("-inf"), float("-inf"), 0)}


def load_state(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "freshest" in data and isinstance(data["freshest"], dict):
            return data["freshest"]
        if "topPublishedAt" in data or "updatedAt" in data:
            return data
    except Exception:
        pass
    return None


def normalize_sort_key(fp: dict[str, Any]) -> tuple[float, float, int]:
    if isinstance(fp.get("sortKey"), (list, tuple)) and len(fp["sortKey"]) >= 3:
        try:
            return (float(fp["sortKey"][0]), float(fp["sortKey"][1]), int(fp["sortKey"][2]))
        except Exception:
            pass
    top_dt = parse_iso(fp.get("topPublishedAt"))
    upd_dt = parse_iso(fp.get("updatedAt"))
    return (
        top_dt.timestamp() if top_dt else float("-inf"),
        upd_dt.timestamp() if upd_dt else float("-inf"),
        int(fp.get("itemCount") or fp.get("items") or 0),
    )


def compare_candidate(candidate: dict[str, Any], references: list[dict[str, Any]], *, min_margin_seconds: int = 0) -> dict[str, Any]:
    usable = [r for r in references if "error" not in r]
    freshest = max(usable, key=normalize_sort_key) if usable else None
    cand_key = normalize_sort_key(candidate)
    freshest_key = normalize_sort_key(freshest) if freshest else (float("-inf"), float("-inf"), 0)
    blocked = bool(freshest and cand_key[0] + min_margin_seconds < freshest_key[0])
    return {
        "status": "blocked" if blocked else "ok",
        "reason": "candidate_older_than_known_public" if blocked else "candidate_not_older_than_known_public",
        "candidate": candidate,
        "freshestReference": freshest,
        "references": references,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Poanta feed rollback publication guard")
    ap.add_argument("--candidate", default="feed.json")
    ap.add_argument("--state", default=str(STATE_PATH))
    ap.add_argument("--url", action="append", default=[], help="Reference public feed URL; may be repeated")
    ap.add_argument("--out", default="tmp/pointa_publish_rollback_guard.json")
    ap.add_argument("--write-state", action="store_true", help="Persist freshest successful candidate/reference fingerprint")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    candidate_path = (ROOT / args.candidate).resolve() if not Path(args.candidate).is_absolute() else Path(args.candidate)
    feed, raw = read_feed(candidate_path)
    candidate = feed_fingerprint(feed, raw, source=str(candidate_path))

    urls = args.url or DEFAULT_PUBLIC_URLS
    refs = [fetch_public(url) for url in urls]
    state_fp = load_state(Path(args.state))
    if state_fp:
        state_fp = {**state_fp, "source": state_fp.get("source") or str(args.state), "fromState": True}
        refs.append(state_fp)

    report = compare_candidate(candidate, refs)
    report["guard"] = "pointa_publish_rollback_guard"
    report["checkedAt"] = datetime.now(timezone.utc).isoformat()
    report["rule"] = "Block deployment if candidate topPublishedAt is older than the freshest known public/saved production fingerprint."

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.write_state and report["status"] == "ok":
        freshest = max([candidate] + [r for r in refs if "error" not in r], key=normalize_sort_key)
        state_path = Path(args.state)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "freshest": freshest,
            "candidate": candidate,
            "guardReport": str(out_path),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Pointa rollback guard: {report['status']} · {report['reason']}")
        if report["status"] != "ok":
            ref = report.get("freshestReference") or {}
            print(f"BLOCKED candidate top={candidate.get('topPublishedAt')} older than {ref.get('source')} top={ref.get('topPublishedAt')}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
