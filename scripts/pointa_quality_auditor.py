#!/usr/bin/env python3
"""Poanta מבקר איכות.

Consumes publication_events.jsonl and reviews newly published cards as cards,
not as a whole feed. It is intentionally close to the Quality Gate but emits an
auditor report with ownership/context for the gatekeeper loop.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENTS = ROOT / "tmp" / "publication_events.jsonl"
DEFAULT_REPORT = ROOT / "tmp" / "pointa_quality_auditor_last.json"

sys.path.insert(0, str(ROOT / "scripts"))
from pointa_quality_gate import validate_item  # type: ignore  # noqa: E402
try:
    from update_feed import is_foreign_source_label, is_retained_foreign_item_relevant  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover
    is_foreign_source_label = None
    is_retained_foreign_item_relevant = None


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=3))).isoformat(timespec="seconds")


def read_events(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
            if isinstance(ev, dict):
                out.append(ev)
        except Exception:
            out.append({"eventType": "invalid_jsonl", "raw": line})
    return out


def item_from_event(ev: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": ev.get("category"),
        "categoryClass": ev.get("categoryClass"),
        "source": ev.get("source"),
        "sourceLogo": ev.get("sourceLogo"),
        "sourceUrl": ev.get("sourceUrl"),
        "publishedAt": ev.get("publishedAt"),
        "hasSourceDate": ev.get("hasSourceDate"),
        "headline": ev.get("headline"),
        "context": ev.get("summary"),
        "takeaway": ev.get("takeaway"),
        "originalTitle": ev.get("originalTitle"),
        "editorStatus": ev.get("editorStatus"),
    }


def audit(events: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for idx, ev in enumerate(events):
        if ev.get("eventType") == "invalid_jsonl":
            findings.append({"severity": "error", "code": "invalid_publication_event_json", "message": "publication event JSONL line is invalid", "raw": ev.get("raw")})
            continue
        item = item_from_event(ev)
        issues: list[dict[str, Any]] = []
        validate_item(item, idx, issues)
        for issue in issues:
            issue = dict(issue)
            issue.update({"eventId": ev.get("eventId"), "itemKey": ev.get("itemKey"), "seenAt": ev.get("seenAt"), "gatekeeper": ev.get("gatekeeper")})
            findings.append(issue)
        if is_foreign_source_label and is_retained_foreign_item_relevant:
            label = str(item.get("source") or item.get("sourceLogo") or "")
            if is_foreign_source_label(label) and not is_retained_foreign_item_relevant(item):
                findings.append({
                    "severity": "error",
                    "code": "foreign_item_not_relevant",
                    "message": "Foreign-source publication event is not Israel/Middle-East/Jews/security relevant",
                    "headline": item.get("headline"),
                    "source": item.get("source"),
                    "url": item.get("sourceUrl"),
                    "eventId": ev.get("eventId"),
                })
    errors = [f for f in findings if f.get("severity") == "error"]
    warnings = [f for f in findings if f.get("severity") == "warning"]
    return {
        "auditor": "quality",
        "status": "fail" if errors else "ok",
        "checkedAt": now_iso(),
        "eventsChecked": len(events),
        "errors": errors,
        "warnings": warnings,
        "findings": findings,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default=str(DEFAULT_EVENTS))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on-error", action="store_true")
    args = ap.parse_args()
    events = read_events(Path(args.events), args.limit)
    result = audit(events)
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Pointa quality auditor: {result['status']} · events={result['eventsChecked']} · errors={len(result['errors'])} · warnings={len(result['warnings'])}")
    return 1 if args.fail_on_error and result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
