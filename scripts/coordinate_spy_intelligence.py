#!/usr/bin/env python3
"""Coordinate raw Spy gaps into cooked intelligence briefings for משה.

This is the safety layer between מרגל and משה:
- Reads spy_gap_queue.json (raw gaps created from spy_trends.json).
- Triage/dedupes/noise-filters the raw gaps.
- Writes intelligence_briefing_queue.json for dashboard/API visibility.
- Optionally hands only ready_for_moshe rows to משה by marking matching
  spy_gap_queue.json rows as queued_for_moshe and attaching a briefing.

It never mutates feed.json and never publishes.
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
DEFAULT_GAPS = ROOT / "spy_gap_queue.json"
DEFAULT_FEED = ROOT / "feed.json"
DEFAULT_OUT = ROOT / "intelligence_briefing_queue.json"
DEFAULT_TASK = ROOT / "tmp" / "intelligence_to_moshe_task.json"
TOKEN_RE = re.compile(r"[\u0590-\u05FFA-Za-z0-9]+")
STOP = {
    "של", "על", "עם", "את", "זה", "זו", "הוא", "היא", "כי", "לא", "כן", "גם", "או", "אל", "כל", "אך", "הם", "הן", "אחרי", "לפני",
    "the", "and", "for", "with", "from", "are", "was", "were", "this", "that", "into", "after", "over", "more", "than",
}
TERMINAL_STATUSES = {"published", "rejected_duplicate", "rejected_low_quality", "rejected_no_source"}
MOSHE_ACTIVE_STATUSES = {"queued_for_moshe", "checking", "candidate_found", "sent_to_editor"}


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
    out: set[str] = set()
    for t in TOKEN_RE.findall(str(text or "").lower().replace("־", " ")):
        if len(t) < 3 or t in STOP:
            continue
        out.add(t)
    return out


def duplicate_check(row: dict[str, Any], feed: dict[str, Any]) -> dict[str, Any]:
    row_url = str(row.get("sourceUrl") or "")
    row_text = " ".join(str(row.get(k) or "") for k in ("trend", "clusterKey", "originalTitle", "deterministicContext"))
    a = tokens(row_text)
    best = {"duplicate": False, "score": 0, "headline": None, "source": None, "reason": "no_overlap"}
    for item in feed.get("items") or []:
        if not isinstance(item, dict):
            continue
        item_url = str(item.get("sourceUrl") or item.get("url") or "")
        if row_url and item_url and row_url == item_url:
            return {"duplicate": True, "score": 1.0, "headline": item.get("headline") or item.get("title"), "source": item.get("source"), "reason": "same_url"}
        b = tokens(" ".join(str(item.get(k) or "") for k in ("headline", "title", "originalTitle", "context", "summary", "takeaway")))
        if not a or not b:
            continue
        score = len(a & b) / max(1, min(len(a), len(b)))
        if score > float(best.get("score") or 0):
            best = {"duplicate": score >= 0.62, "score": round(score, 3), "headline": item.get("headline") or item.get("title"), "source": item.get("source"), "reason": "token_overlap"}
    return best


def source_probe(url: str, timeout: int) -> dict[str, Any]:
    if not url:
        return {"ok": False, "reason": "missing_url"}
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "PoentaIntelCoordinator/1.0 (+bounded source check; no crawl)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            sample = r.read(2048)
            status = int(getattr(r, "status", 0) or 0)
            return {"ok": 200 <= status < 400, "status": status, "contentType": r.headers.get("content-type"), "bytesSampled": len(sample)}
    except Exception as e:
        return {"ok": False, "reason": type(e).__name__, "error": str(e)[:200]}


def status_label(status: str) -> str:
    return {
        "new_from_spy": "חדש מהמרגל",
        "dismissed_duplicate": "נופה — כפילות",
        "dismissed_noise": "נופה — רעש/לא רלוונטי",
        "needs_more_signal": "ממתין לאיתות חזק יותר",
        "needs_source_check": "דורש בדיקת מקור",
        "ready_for_moshe": "מוכן למשה",
        "sent_to_moshe": "הועבר למשה",
    }.get(status, status)


def make_briefing(row: dict[str, Any], feed: dict[str, Any], timeout: int, *, check_source: bool) -> dict[str, Any]:
    source_count = int(row.get("sourceCount") or 0)
    external_mentions = int(row.get("externalMentions") or 0)
    web_mentions = int(row.get("webMentions") or 0)
    rss_mentions = int(row.get("rssMentions") or 0)
    stale = bool(row.get("staleFromCurrentSpy"))
    status = str(row.get("status") or "new")
    dup = duplicate_check(row, feed)
    probe = source_probe(str(row.get("sourceUrl") or ""), timeout) if check_source else {"ok": None, "reason": "not_checked_in_static_mode"}

    reasons: list[str] = []
    priority = external_mentions * 2 + source_count * 4 + web_mentions + rss_mentions
    if stale:
        priority -= 8
        reasons.append("הפער לא מופיע ברשימת האדומים הנוכחית של המרגל")
    if source_count >= 2:
        reasons.append(f"מופיע אצל {source_count} מקורות חיצוניים")
    if external_mentions >= 3:
        reasons.append(f"{external_mentions} אזכורים חיצוניים")
    if row.get("discoveryTypes"):
        reasons.append("שכבות גילוי: " + "+".join(map(str, row.get("discoveryTypes") or [])))

    if status in MOSHE_ACTIVE_STATUSES:
        intel_status = "sent_to_moshe"
        next_action = "משה כבר קיבל את התדריך; להמשיך במסלול בדיקת מקור/כפילות/עורך/QA"
    elif status in TERMINAL_STATUSES:
        intel_status = "dismissed_duplicate" if status == "rejected_duplicate" else "dismissed_noise"
        next_action = "אין פעולה נוספת כרגע"
    elif dup.get("duplicate"):
        intel_status = "dismissed_duplicate"
        next_action = "לא להעביר למשה; נראה שכבר יש בפיד סיפור דומה"
        reasons.append(f"כפילות אפשרית מול הפיד: {dup.get('headline') or 'כותרת קיימת'}")
    elif stale:
        intel_status = "needs_more_signal"
        next_action = "להמתין לסריקת מרגל נוספת; לא להעביר למשה עד שהפער חוזר כאדום נוכחי"
    elif not row.get("sourceUrl"):
        intel_status = "needs_source_check"
        next_action = "צריך מקור מוביל לפני העברה למשה"
    elif probe.get("ok") is False and probe.get("reason") not in {"HTTPError"}:
        intel_status = "needs_source_check"
        next_action = "המקור לא אומת; לחפש מקור נגיש/אמין לפני משה"
        reasons.append(f"בדיקת מקור נכשלה: {probe.get('reason') or probe.get('status')}")
    elif source_count < 2 and external_mentions < 3:
        intel_status = "needs_more_signal"
        next_action = "האיתות חלש מדי; להמתין לעוד מקור/אזכור"
    else:
        intel_status = "ready_for_moshe"
        next_action = "להעביר למשה לבדיקה רגילה: מקור, עדכניות, כפילות סמנטית, מועמד עורך/QA"
        reasons.append("עובר סף רכז מודיעין להעברה מבושלת")

    return {
        "id": "intel_" + str(row.get("id") or "unknown").removeprefix("gap_"),
        "gapId": row.get("id"),
        "status": intel_status,
        "statusLabel": status_label(intel_status),
        "coordinator": {"id": "intelligence-coordinator", "name": "רכז מודיעין"},
        "createdAt": row.get("createdAt") or now_iso(),
        "updatedAt": now_iso(),
        "trend": row.get("trend"),
        "domain": row.get("domain"),
        "clusterKey": row.get("clusterKey"),
        "priority": max(priority, 0),
        "whyImportant": reasons,
        "mosheBriefing": {
            "headlineSeed": row.get("trend"),
            "source": row.get("source"),
            "sourceUrl": row.get("sourceUrl"),
            "supportingSources": row.get("sources") or [],
            "discoveryTypes": row.get("discoveryTypes") or [],
            "externalMentions": external_mentions,
            "sourceCount": source_count,
            "missingReason": "המרגל זיהה שזה טרנד חיצוני שלא מופיע בפיד הנוכחי",
            "checksForMoshe": [
                "לאמת שהמקור אמיתי, נגיש ועדכני",
                "לבדוק כפילות סמנטית מול הפיד",
                "לבנות מועמד פיד רק אם יש ערך חדשותי מספיק",
                "להעביר לעורך מלא ול־Quality Gate לפני כל פרסום",
            ],
            "doNotRawPublish": True,
        },
        "duplicateCheck": dup,
        "sourceProbe": probe,
        "nextAction": next_action,
        "rawGap": row,
    }


def run(gaps_path: Path, feed_path: Path, out_path: Path, task_path: Path, max_rows: int, max_moshe: int, timeout: int, handoff: bool, check_source: bool) -> dict[str, Any]:
    gaps = load_json(gaps_path, {"items": []})
    feed = load_json(feed_path, {"items": []})
    rows = [r for r in (gaps.get("items") or []) if isinstance(r, dict)]
    briefings = [make_briefing(r, feed, timeout, check_source=check_source) for r in rows]
    briefings.sort(key=lambda b: (b.get("status") != "ready_for_moshe", -int(b.get("priority") or 0), str(b.get("updatedAt") or "")))
    if max_rows > 0:
        briefings = briefings[:max_rows]

    handed = []
    if handoff:
        by_gap = {b.get("gapId"): b for b in briefings if b.get("status") == "ready_for_moshe"}
        changed = 0
        for row in rows:
            if changed >= max_moshe:
                break
            gid = row.get("id")
            b = by_gap.get(gid)
            if not b or row.get("status") != "new":
                continue
            row["status"] = "queued_for_moshe"
            row["statusLabel"] = "ממתין למשה"
            row["owner"] = "משה"
            row["preparedBy"] = "רכז מודיעין"
            row["intelligenceBriefingId"] = b.get("id")
            row["intelligenceBriefing"] = b.get("mosheBriefing")
            row["mosheStage"] = "בתור משה"
            row["mosheCurrentAction"] = "משה קיבל תדריך מבושל מרכז המודיעין וצריך לבדוק מקור, עדכניות וכפילות סמנטית"
            row["mosheNextAction"] = "אם תקין: מועמד פיד לעורך/QA; אם לא: דחייה עם סיבה"
            row["mosheQueuedAt"] = now_iso()
            row["updatedAt"] = now_iso()
            b["status"] = "sent_to_moshe"
            b["statusLabel"] = status_label("sent_to_moshe")
            b["sentToMosheAt"] = row["mosheQueuedAt"]
            b["nextAction"] = "משה קיבל; להמשיך במסלול בדיקה רגיל"
            handed.append(b)
            changed += 1
        gaps["items"] = rows
        gaps["status"] = "ok"
        gaps["generatedAt"] = now_iso()
        gaps["queuedForMoshe"] = sum(1 for r in rows if r.get("status") == "queued_for_moshe")
        gaps["newItems"] = sum(1 for r in rows if r.get("status") == "new")
        gaps["intelligenceCoordinator"] = {"lastRunAt": now_iso(), "handedToMoshe": len(handed), "policy": "only coordinator-ready gaps are queued for משה"}
        write_json(gaps_path, gaps)
        write_json(task_path, {"createdAt": now_iso(), "instruction": "משה: לטפל רק בתדריכים המבושלים של רכז המודיעין; לא לפרסם גולמית.", "items": handed})

    counts: dict[str, int] = {}
    for b in briefings:
        counts[str(b.get("status") or "unknown")] = counts.get(str(b.get("status") or "unknown"), 0) + 1
    doc = {
        "ok": True,
        "status": "ok",
        "agent": {"id": "intelligence-coordinator", "name": "רכז מודיעין", "role": "בישול פערי מרגל לפני העברה למשה"},
        "generatedAt": now_iso(),
        "sourceGapGeneratedAt": gaps.get("generatedAt"),
        "policy": "Spy gaps are triaged before משה; no raw publish; no feed mutation.",
        "scheduleRecommendation": "every 15m",
        "handoffToMoshe": bool(handoff),
        "handedToMoshe": len(handed),
        "counts": counts,
        "items": briefings,
    }
    write_json(out_path, doc)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gaps", default=str(DEFAULT_GAPS))
    ap.add_argument("--feed", default=str(DEFAULT_FEED))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--task", default=str(DEFAULT_TASK))
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--max-moshe", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=6)
    ap.add_argument("--handoff-to-moshe", action="store_true")
    ap.add_argument("--no-source-check", action="store_true", help="Skip network source probe for static build snapshots")
    args = ap.parse_args()
    socket.setdefaulttimeout(args.timeout)
    doc = run(Path(args.gaps), Path(args.feed), Path(args.out), Path(args.task), args.limit, args.max_moshe, args.timeout, args.handoff_to_moshe, not args.no_source_check)
    print(json.dumps({"ok": doc.get("ok"), "status": doc.get("status"), "counts": doc.get("counts"), "handedToMoshe": doc.get("handedToMoshe")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
