#!/usr/bin/env python3
"""Poanta publication event bus.

The gatekeeper (השוער) calls this after a feed candidate passes Quality Gate.
It records one append-only JSONL event per newly observed published card, so the
new auditors can inspect the publication stream directly instead of inferring
state only from the public feed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEED = ROOT / "feed.json"
DEFAULT_EVENTS = ROOT / "tmp" / "publication_events.jsonl"
DEFAULT_STATE = ROOT / "tmp" / "publication_events_state.json"


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=3))).isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_feed(path: Path) -> dict[str, Any]:
    data = load_json(path, {})
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise SystemExit(f"Invalid feed: {path}")
    return data


def canonical_key(item: dict[str, Any]) -> str:
    url = str(item.get("sourceUrl") or "").strip()
    if url:
        return "url:" + url.split("#", 1)[0].rstrip("/")
    blob = "|".join(str(item.get(k) or "") for k in ["source", "publishedAt", "headline", "originalTitle"])
    return "hash:" + hashlib.sha1(blob.encode("utf-8")).hexdigest()


def event_from_item(item: dict[str, Any], feed: dict[str, Any], gatekeeper: str, run_id: str) -> dict[str, Any]:
    # A publication event represents what the gatekeeper actually exposed to
    # users.  If the same source URL is republished with corrected Pointa text,
    # that must count as a new pipeline event for the timing/quality auditors.
    # Otherwise a repaired foreign/source card can remain invisible to timing
    # because the old eventId was based only on URL + source publishedAt.
    visible_fingerprint = "|".join(str(item.get(k) or "") for k in ["headline", "context", "takeaway", "category", "categoryClass", "editorStatus"])
    return {
        "eventType": "card_published",
        "eventId": hashlib.sha1((canonical_key(item) + "|" + str(item.get("publishedAt") or "") + "|" + visible_fingerprint).encode("utf-8")).hexdigest(),
        "seenAt": now_iso(),
        "feedUpdatedAt": feed.get("updatedAt"),
        "gatekeeper": gatekeeper,
        "runId": run_id,
        "itemKey": canonical_key(item),
        "publishedAt": item.get("publishedAt"),
        "source": item.get("source"),
        "sourceLogo": item.get("sourceLogo"),
        "category": item.get("category"),
        "categoryClass": item.get("categoryClass"),
        "headline": item.get("headline"),
        "summary": item.get("context"),
        "takeaway": item.get("takeaway"),
        "originalTitle": item.get("originalTitle"),
        "sourceUrl": item.get("sourceUrl"),
        "editorStatus": item.get("editorStatus"),
        "hasSourceDate": item.get("hasSourceDate"),
    }


def record(feed_path: Path, events_path: Path, state_path: Path, gatekeeper: str, run_id: str, replay_all: bool) -> dict[str, Any]:
    feed = load_feed(feed_path)
    state = load_json(state_path, {})
    if not isinstance(state, dict):
        state = {}
    # A URL can legitimately receive a newer source timestamp when an article is
    # updated or when the collector previously saw a stale bridge timestamp.
    # The timing auditor needs that to count as a fresh publication event.  The
    # old state keyed only by itemKey suppressed those updates and made the
    # watchdog look "ok" while no fresh events were emitted.  Track eventId
    # (itemKey + publishedAt) instead, and migrate from the existing JSONL so we
    # do not replay the whole historical feed after the change.
    seen_events = set(state.get("seenEventIds") or [])
    if not seen_events and events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except Exception:
                continue
            event_id = ev.get("eventId")
            if event_id:
                seen_events.add(str(event_id))
    seen_items = set(state.get("seenItemKeys") or [])
    events_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    new_events: list[dict[str, Any]] = []
    for item in feed.get("items", []):
        if not isinstance(item, dict):
            continue
        key = canonical_key(item)
        ev = event_from_item(item, feed, gatekeeper=gatekeeper, run_id=run_id)
        event_id = str(ev.get("eventId") or "")
        if not replay_all and event_id in seen_events:
            continue
        new_events.append(ev)
        seen_events.add(event_id)
        seen_items.add(key)

    if new_events:
        with events_path.open("a", encoding="utf-8") as fh:
            for ev in new_events:
                fh.write(json.dumps(ev, ensure_ascii=False, sort_keys=True) + "\n")

    state.update({
        "updatedAt": now_iso(),
        "feedUpdatedAt": feed.get("updatedAt"),
        "seenItemKeys": sorted(seen_items),
        "seenEventIds": sorted(seen_events),
        "lastEventAt": new_events[-1]["seenAt"] if new_events else state.get("lastEventAt"),
        "lastPublishedAt": max([str(ev.get("publishedAt") or "") for ev in new_events] or [state.get("lastPublishedAt", "")]),
        "eventCount": int(state.get("eventCount") or 0) + len(new_events),
    })
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "ok", "newEvents": len(new_events), "totalSeen": len(seen_items), "totalSeenEvents": len(seen_events), "eventsPath": str(events_path), "statePath": str(state_path)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("record", nargs="?", default="record")
    ap.add_argument("--feed", default=str(DEFAULT_FEED))
    ap.add_argument("--events", default=str(DEFAULT_EVENTS))
    ap.add_argument("--state", default=str(DEFAULT_STATE))
    ap.add_argument("--gatekeeper", default="pointa-gatekeeper")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--replay-all", action="store_true", help="Write events even for already seen item keys")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.record != "record":
        raise SystemExit("Only supported command: record")
    result = record(Path(args.feed), Path(args.events), Path(args.state), args.gatekeeper, args.run_id, args.replay_all)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Publication events: {result['newEvents']} new · totalSeen={result['totalSeen']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
