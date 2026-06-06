#!/usr/bin/env python3
"""Maintain Poenta spy gap queue for missing external trends.

This script turns spy trends where mentionedInFeed=false into a safe operational
queue for משה. It does not publish feed.json. Rows are shaped so the existing
rescue editor pipeline can later consume them after source/content QA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPY = ROOT / "spy_trends.json"
DEFAULT_OUT = ROOT / "spy_gap_queue.json"
TOKEN_RE = re.compile(r"[\w\u0590-\u05ff]+")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def norm_text(text: str) -> str:
    tokens = TOKEN_RE.findall(str(text or "").lower().replace("־", " "))
    return " ".join(tokens[:16])


def gap_id(trend: dict[str, Any]) -> str:
    seed = "|".join([
        norm_text(str(trend.get("clusterKey") or "")),
        norm_text(str(trend.get("trend") or "")),
        str(trend.get("domain") or "חדשות"),
    ]).strip("|")
    if not seed:
        seed = json.dumps(trend, ensure_ascii=False, sort_keys=True)[:500]
    return "gap_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def first_source(sources: Any) -> str:
    if isinstance(sources, list) and sources:
        return str(sources[0] or "מקור")
    return "מקור"


def status_label(status: str) -> str:
    return {
        "new": "חדש",
        "queued_for_moshe": "ממתין למשה",
        "checking": "משה בודק מקור וכפילות",
        "sent_to_editor": "נשלח לעורך",
        "candidate_found": "נמצא מועמד פיד",
        "published": "פורסם",
        "rejected_duplicate": "נדחה — כפילות",
        "rejected_low_quality": "נדחה — איכות",
        "rejected_no_source": "נדחה — אין מקור",
    }.get(status or "new", status or "חדש")


def moshe_stage(status: str) -> dict[str, str]:
    return {
        "new": {
            "stage": "זוהה פער",
            "currentAction": "ממתין לשליחה לתור משה",
            "nextAction": "ללחוץ שלח אדומים למשה או לחכות לריצה השעתית",
        },
        "queued_for_moshe": {
            "stage": "בתור משה",
            "currentAction": "משה צריך לפתוח את המקור, לבדוק שזה סיפור אמיתי ועדכני, ולבדוק שאין אצלנו כפילות סמנטית",
            "nextAction": "אם תקין: להפוך למועמד פיד ולהעביר לעורך; אם לא: לדחות עם סיבה",
        },
        "checking": {
            "stage": "בדיקה",
            "currentAction": "בדיקת מקור, כפילות, חשיבות ואיכות",
            "nextAction": "מועמד לעורך או דחייה",
        },
        "candidate_found": {
            "stage": "מועמד נמצא",
            "currentAction": "נמצא מקור מתאים ונבנה מועמד פיד",
            "nextAction": "העברה לעורך מלא ול־QA",
        },
        "sent_to_editor": {
            "stage": "אצל העורך",
            "currentAction": "העורך מכין כרטיס פואנטה מלא: כותרת, תקציר ופואנטה",
            "nextAction": "Quality Gate ואז פרסום אם עבר",
        },
        "published": {
            "stage": "פורסם",
            "currentAction": "הפער נסגר בפיד",
            "nextAction": "אין פעולה",
        },
        "rejected_duplicate": {
            "stage": "נדחה",
            "currentAction": "נמצא שכבר יש אצלנו אותו סיפור סמנטית",
            "nextAction": "אין פרסום נוסף",
        },
        "rejected_low_quality": {
            "stage": "נדחה",
            "currentAction": "המקור/הנושא לא מספיק איכותי לפיד",
            "nextAction": "אין פרסום",
        },
        "rejected_no_source": {
            "stage": "נדחה",
            "currentAction": "לא נמצא מקור אמין/פתוח מספיק",
            "nextAction": "אין פרסום",
        },
    }.get(status or "new", {"stage": "לא ידוע", "currentAction": "סטטוס לא מוכר", "nextAction": "בדיקה ידנית"})


def trend_to_queue_row(trend: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = existing or {}
    gid = gap_id(trend)
    created_at = existing.get("createdAt") or now_iso()
    status = existing.get("status") or "new"
    sources = trend.get("sources") if isinstance(trend.get("sources"), list) else []
    sample_url = str(trend.get("sampleUrl") or existing.get("sourceUrl") or "")
    source = first_source(sources) or str(existing.get("source") or "מקור")
    title = str(trend.get("trend") or existing.get("trend") or "").strip()
    domain = str(trend.get("domain") or existing.get("domain") or "חדשות").strip() or "חדשות"
    row = dict(existing)
    stage = moshe_stage(status)
    row.update({
        "id": gid,
        "status": status,
        "statusLabel": status_label(status),
        "mosheStage": stage["stage"],
        "mosheCurrentAction": stage["currentAction"],
        "mosheNextAction": stage["nextAction"],
        "createdAt": created_at,
        "updatedAt": now_iso(),
        "trend": title,
        "domain": domain,
        "clusterKey": trend.get("clusterKey") or existing.get("clusterKey"),
        "reason": "missing_from_feed",
        "recommendedAction": "send_to_full_editor_rescue_queue",
        "owner": "משה",
        "priority": int(trend.get("externalMentions") or 0) * 2 + int(trend.get("sourceCount") or 0) * 3 + int(trend.get("webMentions") or 0),
        "externalMentions": trend.get("externalMentions") or 0,
        "sourceCount": trend.get("sourceCount") or 0,
        "sources": sources,
        "discoveryTypes": trend.get("discoveryTypes") or [],
        "rssMentions": trend.get("rssMentions") or 0,
        "webMentions": trend.get("webMentions") or 0,
        "latestAt": trend.get("latestAt"),
        "source": source,
        "sourceGroup": source,
        "sourceUrl": sample_url,
        "originalTitle": title,
        "deterministicHeadline": title,
        "deterministicContext": f"טרנד חיצוני חסר בפיד פואנטה: {title}",
        "mosheInstruction": "לא לפרסם גולמית. לבדוק מקור, כפילות סמנטית ואיכות; להעביר לעורך מלא רק אם יש מקור מספיק טוב.",
        "rawSpyTrend": trend,
    })
    return row


def refresh_queue(spy_path: Path, out_path: Path, limit: int) -> dict[str, Any]:
    spy = load_json(spy_path, {})
    existing_doc = load_json(out_path, {})
    existing_items = existing_doc.get("items") if isinstance(existing_doc, dict) else []
    existing_by_id = {str(row.get("id")): row for row in existing_items or [] if isinstance(row, dict) and row.get("id")}

    missing = [t for t in (spy.get("trends") or []) if isinstance(t, dict) and not t.get("mentionedInFeed")]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for trend in missing:
        gid = gap_id(trend)
        rows.append(trend_to_queue_row(trend, existing_by_id.get(gid)))
        seen.add(gid)

    # Keep unresolved historical rows even if they are not in the current top spy table.
    for row in existing_items or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or "")
        if not rid or rid in seen:
            continue
        if row.get("status") in {"published", "rejected_duplicate", "rejected_low_quality", "rejected_no_source"}:
            continue
        row = dict(row)
        status = str(row.get("status") or "new")
        stage = moshe_stage(status)
        row["statusLabel"] = status_label(status)
        row["mosheStage"] = row.get("mosheStage") or stage["stage"]
        row["mosheCurrentAction"] = row.get("mosheCurrentAction") or stage["currentAction"]
        row["mosheNextAction"] = row.get("mosheNextAction") or stage["nextAction"]
        row["staleFromCurrentSpy"] = True
        row["updatedAt"] = row.get("updatedAt") or now_iso()
        rows.append(row)

    rows.sort(key=lambda r: (r.get("status") not in {"new", "queued_for_moshe"}, -int(r.get("priority") or 0), str(r.get("latestAt") or "")))
    if limit > 0:
        rows = rows[:limit]

    stats = {
        "missingInCurrentSpy": len(missing),
        "queueItems": len(rows),
        "newItems": sum(1 for r in rows if r.get("status") == "new"),
        "queuedForMoshe": sum(1 for r in rows if r.get("status") == "queued_for_moshe"),
        "sentToEditor": sum(1 for r in rows if r.get("status") == "sent_to_editor"),
        "candidateFound": sum(1 for r in rows if r.get("status") == "candidate_found"),
        "published": sum(1 for r in rows if r.get("status") == "published"),
        "rejected": sum(1 for r in rows if str(r.get("status") or "").startswith("rejected_")),
    }
    doc = {
        "ok": True,
        "status": "ok",
        "agent": {"id": "moshe-spy-gap", "name": "משה · פערי מרגל", "role": "הפיכת טרנדים חסרים למועמדי פיד בטוחים"},
        "generatedAt": now_iso(),
        "sourceSpyGeneratedAt": spy.get("generatedAt"),
        "policy": "missing spy trends enter a queue for משה/editor QA; no raw auto-publish",
        "mosheProcessor": existing_doc.get("mosheProcessor") if isinstance(existing_doc, dict) else None,
        **stats,
        "items": rows,
    }
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def mark_for_moshe(out_path: Path, max_items: int) -> dict[str, Any]:
    doc = load_json(out_path, {"items": []})
    items = doc.get("items") or []
    changed = 0
    task_items = []
    for row in items:
        if changed >= max_items:
            break
        if row.get("status") == "new":
            row["status"] = "queued_for_moshe"
            row["statusLabel"] = status_label("queued_for_moshe")
            stage = moshe_stage("queued_for_moshe")
            row["mosheStage"] = stage["stage"]
            row["mosheCurrentAction"] = stage["currentAction"]
            row["mosheNextAction"] = stage["nextAction"]
            row["mosheQueuedAt"] = now_iso()
            row["updatedAt"] = now_iso()
            changed += 1
            task_items.append(row)
    doc["generatedAt"] = now_iso()
    doc["lastQueued"] = changed
    doc["queued"] = changed
    doc["status"] = "queued"
    doc["queuedForMoshe"] = sum(1 for r in items if r.get("status") == "queued_for_moshe")
    doc["newItems"] = sum(1 for r in items if r.get("status") == "new")
    doc["items"] = items
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    task_path = ROOT / "tmp" / "moshe_spy_gap_task.json"
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(json.dumps({
        "createdAt": now_iso(),
        "instruction": "משה: להפוך טרנדים חסרים למועמדי פיד, דרך עורך/QA בלבד; לא לפרסם גולמית.",
        "items": task_items,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "status": "queued", "queued": changed, "taskPath": str(task_path), **doc}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spy", default=str(DEFAULT_SPY))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--mark-for-moshe", action="store_true")
    ap.add_argument("--max-moshe", type=int, default=5)
    args = ap.parse_args()
    doc = refresh_queue(Path(args.spy), Path(args.out), args.limit)
    if args.mark_for_moshe:
        doc = mark_for_moshe(Path(args.out), args.max_moshe)
    print(json.dumps({k: doc.get(k) for k in ("ok", "status", "missingInCurrentSpy", "queueItems", "newItems", "queuedForMoshe", "queued")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
