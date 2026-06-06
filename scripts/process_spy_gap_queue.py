#!/usr/bin/env python3
"""Process משה spy-gap queue items safely.

This is the missing operational link between "ממתין למשה" and actual handling.
It does not publish feed.json. It verifies source reachability, checks simple
semantic duplicate signals against feed.json, and advances each gap to a visible
status: candidate_found or rejected_*.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUEUE = ROOT / "spy_gap_queue.json"
DEFAULT_FEED = ROOT / "feed.json"
DEFAULT_ACTIVITY = ROOT / "tmp" / "moshe_spy_gap_activity.json"
TOKEN_RE = re.compile(r"[\u0590-\u05FFA-Za-z0-9]+")
STOP = {
    "של", "על", "עם", "את", "זה", "זו", "הוא", "היא", "כי", "לא", "כן", "גם", "או", "אל", "כל", "אך", "הם", "הן",
    "the", "and", "for", "with", "from", "are", "was", "were", "this", "that", "into", "after", "over", "more", "than",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def tokens(text: str) -> set[str]:
    out = set()
    for t in TOKEN_RE.findall(str(text or "").lower().replace("־", " ")):
        if len(t) < 3 or t in STOP:
            continue
        out.add(t)
    return out


def status_label(status: str) -> str:
    return {
        "new": "חדש",
        "queued_for_moshe": "ממתין למשה",
        "checking": "משה בודק מקור וכפילות",
        "candidate_found": "נמצא מועמד פיד",
        "sent_to_editor": "נשלח לעורך",
        "published": "פורסם",
        "rejected_duplicate": "נדחה — כפילות",
        "rejected_low_quality": "נדחה — איכות",
        "rejected_no_source": "נדחה — אין מקור",
    }.get(status or "new", status or "חדש")


def set_moshe_fields(row: dict[str, Any], status: str, current: str, next_action: str, *, stage: str | None = None) -> None:
    row["status"] = status
    row["statusLabel"] = status_label(status)
    row["mosheStage"] = stage or {
        "checking": "בדיקה",
        "candidate_found": "מועמד נמצא",
        "rejected_duplicate": "נדחה",
        "rejected_low_quality": "נדחה",
        "rejected_no_source": "נדחה",
    }.get(status, "בתור משה")
    row["mosheCurrentAction"] = current
    row["mosheNextAction"] = next_action
    row["mosheLastActionAt"] = now_iso()


def source_probe(url: str, timeout: int) -> dict[str, Any]:
    if not url:
        return {"ok": False, "reason": "missing_url"}
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PoentaMosheGapChecker/1.0 (+bounded source verification; no crawl)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            sample = r.read(4096)
            return {
                "ok": 200 <= int(getattr(r, "status", 0) or 0) < 400,
                "status": int(getattr(r, "status", 0) or 0),
                "contentType": r.headers.get("content-type"),
                "bytesSampled": len(sample),
            }
    except Exception as e:
        return {"ok": False, "reason": type(e).__name__, "error": str(e)[:240]}


def duplicate_check(row: dict[str, Any], feed: dict[str, Any]) -> dict[str, Any]:
    row_text = " ".join(str(row.get(k) or "") for k in ("trend", "clusterKey", "deterministicContext", "originalTitle"))
    a = tokens(row_text)
    if not a:
        return {"duplicate": False, "score": 0}
    best = {"duplicate": False, "score": 0, "headline": None, "source": None}
    row_url = str(row.get("sourceUrl") or "")
    for item in feed.get("items") or []:
        if not isinstance(item, dict):
            continue
        if row_url and row_url == str(item.get("sourceUrl") or item.get("url") or ""):
            return {"duplicate": True, "score": 1.0, "headline": item.get("headline") or item.get("title"), "source": item.get("source"), "reason": "same_url"}
        item_text = " ".join(str(item.get(k) or "") for k in ("headline", "title", "originalTitle", "context", "takeaway", "summary"))
        b = tokens(item_text)
        if not b:
            continue
        overlap = len(a & b) / max(1, min(len(a), len(b)))
        if overlap > best["score"]:
            best = {"duplicate": overlap >= 0.62, "score": round(overlap, 3), "headline": item.get("headline") or item.get("title"), "source": item.get("source"), "reason": "token_overlap"}
    return best


def process(queue_path: Path, feed_path: Path, activity_path: Path, max_items: int, timeout: int) -> dict[str, Any]:
    queue = load_json(queue_path, {"items": []})
    feed = load_json(feed_path, {"items": []})
    activity = load_json(activity_path, {"events": []})
    items = queue.get("items") or []
    events = activity.get("events") or []
    processed = 0
    started = now_iso()

    for row in items:
        if processed >= max_items:
            break
        if not isinstance(row, dict):
            continue
        if row.get("status") not in {"queued_for_moshe", "checking"}:
            continue

        processed += 1
        row["mosheStartedAt"] = row.get("mosheStartedAt") or now_iso()
        set_moshe_fields(row, "checking", "משה בודק עכשיו מקור, כפילות סמנטית וחשיבות", "בסיום הבדיקה: מועמד פיד או דחייה")
        url = str(row.get("sourceUrl") or "")
        probe = source_probe(url, timeout)
        dup = duplicate_check(row, feed)
        row["mosheSourceCheck"] = probe
        row["mosheDuplicateCheck"] = dup
        row["mosheCheckedAt"] = now_iso()

        if dup.get("duplicate"):
            set_moshe_fields(
                row,
                "rejected_duplicate",
                f"משה מצא שכבר יש בפיד סיפור דומה: {dup.get('headline') or 'כותרת קיימת'}",
                "אין פרסום נוסף; הפער נסגר ככפילות",
            )
            outcome = "rejected_duplicate"
        elif not probe.get("ok"):
            set_moshe_fields(
                row,
                "rejected_no_source",
                f"משה לא הצליח לאמת מקור פתוח/נגיש ({probe.get('reason') or probe.get('status') or 'unknown'})",
                "לא לפרסם עד שיימצא מקור אמין ונגיש",
            )
            outcome = "rejected_no_source"
        elif len(tokens(str(row.get("trend") or ""))) < 4 or int(row.get("sourceCount") or 0) < 1:
            set_moshe_fields(
                row,
                "rejected_low_quality",
                "משה מצא שהטרנד דל מדי או לא מספיק ברור לכרטיס פיד",
                "לא לפרסם; להמתין לאיתות חזק יותר",
            )
            outcome = "rejected_low_quality"
        else:
            candidate = {
                "headlineSeed": row.get("trend"),
                "source": row.get("source"),
                "sourceUrl": url,
                "category": row.get("domain"),
                "reason": "spy_gap_verified_by_moshe",
                "checkedAt": row["mosheCheckedAt"],
                "nextGate": "editor_quality_gate",
            }
            row["candidate"] = candidate
            set_moshe_fields(
                row,
                "candidate_found",
                "משה אימת מקור ולא מצא כפילות חזקה; נוצר מועמד פיד בטוח לבדיקה עריכתית",
                "להעביר לעורך מלא ול־Quality Gate לפני פרסום",
            )
            outcome = "candidate_found"

        row["mosheOutcome"] = outcome
        events.insert(0, {
            "at": row.get("mosheLastActionAt"),
            "gapId": row.get("id"),
            "trend": row.get("trend"),
            "status": row.get("status"),
            "statusLabel": row.get("statusLabel"),
            "action": row.get("mosheCurrentAction"),
            "nextAction": row.get("mosheNextAction"),
            "sourceUrl": url,
        })

    queue["items"] = items
    queue["status"] = "ok"
    queue["generatedAt"] = now_iso()
    queue["mosheProcessor"] = {
        "lastRunAt": started,
        "finishedAt": now_iso(),
        "processed": processed,
        "schedule": "כל 10 דקות",
        "policy": "no raw publish; candidate/editor/QA only",
    }
    queue["newItems"] = sum(1 for r in items if isinstance(r, dict) and r.get("status") == "new")
    queue["queuedForMoshe"] = sum(1 for r in items if isinstance(r, dict) and r.get("status") == "queued_for_moshe")
    queue["checking"] = sum(1 for r in items if isinstance(r, dict) and r.get("status") == "checking")
    queue["candidateFound"] = sum(1 for r in items if isinstance(r, dict) and r.get("status") == "candidate_found")
    queue["sentToEditor"] = sum(1 for r in items if isinstance(r, dict) and r.get("status") == "sent_to_editor")
    queue["published"] = sum(1 for r in items if isinstance(r, dict) and r.get("status") == "published")
    queue["rejected"] = sum(1 for r in items if isinstance(r, dict) and str(r.get("status") or "").startswith("rejected_"))
    write_json(queue_path, queue)
    write_json(activity_path, {"ok": True, "updatedAt": now_iso(), "events": events[:200]})
    return {"ok": True, "processed": processed, "candidateFound": queue["candidateFound"], "queuedForMoshe": queue["queuedForMoshe"], "rejected": queue["rejected"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default=str(DEFAULT_QUEUE))
    ap.add_argument("--feed", default=str(DEFAULT_FEED))
    ap.add_argument("--activity", default=str(DEFAULT_ACTIVITY))
    ap.add_argument("--max-items", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=8)
    args = ap.parse_args()
    socket.setdefaulttimeout(args.timeout)
    result = process(Path(args.queue), Path(args.feed), Path(args.activity), args.max_items, args.timeout)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
