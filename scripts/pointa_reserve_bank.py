#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Maintain a Pointa domain reserve bank of fresh near-ready rescue candidates.

The reserve bank is deliberately non-publishing. It stores fresh, source-backed
candidates that can be routed quickly into the full editor when a domain/top-feed
SLA breach appears. A candidate in this bank is *not* publishable until the editor
pipeline, Quality Gate, Publication Health Gate and live auditor pass.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SLA = ROOT / "config" / "pointa_freshness_sla.json"
DEFAULT_OUT = ROOT / "tmp" / "pointa_reserve_cards.json"
DEFAULT_TMP = ROOT / "tmp"
TZ = timezone(timedelta(hours=3))


def now_dt() -> datetime:
    return datetime.now(TZ)


def parse_dt(raw: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    except Exception:
        return None


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ttl_for_domain(domain: str, sla: dict[str, Any]) -> int:
    spec = (sla.get("domains") or {}).get(domain) or {}
    priority = str(spec.get("priority") or "medium")
    if priority == "critical":
        return 90
    if priority == "high":
        return 180
    if priority == "medium":
        return 360
    return 720


def safe_name(domain: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in domain).strip("-") or "domain"


def build_domain_queue(domain: str, max_age: int, per_source: int) -> dict[str, Any]:
    out = DEFAULT_TMP / f"pointa_reserve_queue_{safe_name(domain)}.json"
    cmd = [
        sys.executable,
        "scripts/pointa_source_rescue_queue.py",
        "--domain",
        domain,
        "--max-age-min",
        str(max_age),
        "--per-source",
        str(per_source),
        "--out",
        str(out),
    ]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=360)
    data = load_json(out, {}) if out.exists() else {}
    return {"exit": proc.returncode, "out": str(out), "stdout": proc.stdout[-1000:], "stderr": proc.stderr[-1000:], "data": data}


def candidate_key(row: dict[str, Any]) -> str:
    return str(row.get("sourceUrl") or row.get("originalTitle") or row.get("deterministicHeadline") or "")


def compact_candidate(domain: str, row: dict[str, Any], now: datetime, ttl_min: int) -> dict[str, Any]:
    return {
        "domain": domain,
        "status": "near_ready_editor_required",
        "createdAt": now.isoformat(timespec="seconds"),
        "expiresAt": (now + timedelta(minutes=ttl_min)).isoformat(timespec="seconds"),
        "publishedAt": row.get("publishedAt"),
        "sourceGroup": row.get("sourceGroup"),
        "source": row.get("source"),
        "sourceUrl": row.get("sourceUrl"),
        "originalTitle": row.get("originalTitle"),
        "deterministicHeadline": row.get("deterministicHeadline"),
        "deterministicContext": row.get("deterministicContext"),
        "deterministicTakeaway": row.get("deterministicTakeaway"),
        "deterministicCategory": row.get("deterministicCategory"),
        "qaErrorCodes": row.get("qaErrorCodes") or [],
        "recommendedAction": "send_to_full_editor_rescue_queue",
        "publishable": False,
        "note": "Reserve candidate only. Must pass full editor QA, Quality Gate, Publication Health Gate, and live auditor before deploy.",
    }


def prune_existing(cards: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    kept = []
    for card in cards:
        exp = parse_dt(card.get("expiresAt"))
        if card.get("usedAt"):
            continue
        if exp and exp >= now:
            kept.append(card)
    return kept


def main() -> int:
    ap = argparse.ArgumentParser(description="Build/refresh Pointa reserve candidate bank")
    ap.add_argument("--domains", default="all", help="all or comma-separated domain names")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--sla-config", default=str(DEFAULT_SLA))
    ap.add_argument("--limit-per-domain", type=int, default=6)
    ap.add_argument("--per-source", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    now = now_dt()
    sla = load_json(Path(args.sla_config), {})
    all_domains = list((sla.get("domains") or {}).keys())
    domains = all_domains if args.domains == "all" else [d.strip() for d in args.domains.split(",") if d.strip()]

    existing = load_json(Path(args.out), {"cards": []})
    cards = prune_existing(existing.get("cards") if isinstance(existing, dict) else [], now)
    seen = {candidate_key(c) for c in cards if candidate_key(c)}
    actions = []

    for domain in domains:
        ttl = ttl_for_domain(domain, sla)
        max_age = max(ttl, int(((sla.get("domains") or {}).get(domain) or {}).get("failMinutes") or 60) * 3)
        q = build_domain_queue(domain, max_age=max_age, per_source=args.per_source)
        rows = [r for r in (q.get("data") or {}).get("items", []) if r.get("recommendedAction") == "send_to_full_editor_rescue_queue"]
        added = 0
        for row in rows:
            key = candidate_key(row)
            if not key or key in seen:
                continue
            cards.append(compact_candidate(domain, row, now, ttl))
            seen.add(key)
            added += 1
            if added >= args.limit_per_domain:
                break
        actions.append({"domain": domain, "queueExit": q["exit"], "queueItems": len(rows), "added": added, "queue": q["out"]})

    # Keep newest/soonest-relevant first and cap total size.
    cards = sorted(cards, key=lambda c: (str(c.get("createdAt") or ""), str(c.get("publishedAt") or "")), reverse=True)[:160]
    by_domain = {d: sum(1 for c in cards if c.get("domain") == d) for d in domains}
    report = {
        "name": "Pointa reserve candidate bank",
        "checkedAt": now.isoformat(timespec="seconds"),
        "status": "ok",
        "cards": cards,
        "counts": {"total": len(cards), "byDomain": by_domain},
        "actions": actions,
        "policy": "Non-publishing near-ready bank. Cards are not publishable until editor QA and all hard gates pass.",
    }
    write_json(Path(args.out), report)
    summary = {"status": "ok", "out": str(Path(args.out)), "total": len(cards), "byDomain": by_domain, "added": sum(a["added"] for a in actions)}
    print(json.dumps(report if args.json else summary, ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
