#!/usr/bin/env python3
"""Pointa domain freshness rescue engine (dry-run first).

Reads the shared SLA config and current feed state, reports domains that are OK,
in warning, or failing, and optionally prepares a domain-filtered source rescue
queue. It never publishes and never modifies feed.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEED = ROOT / "feed.json"
DEFAULT_SLA = ROOT / "config" / "pointa_freshness_sla.json"
DEFAULT_DOMAIN_SOURCES = ROOT / "config" / "pointa_domain_sources.json"
DEFAULT_RESERVE = ROOT / "tmp" / "pointa_reserve_cards.json"
DEFAULT_OUT = ROOT / "tmp" / "pointa_domain_rescue_status.json"
TZ = timezone(timedelta(hours=3))


def now_dt() -> datetime:
    return datetime.now(TZ)


def parse_dt(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
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


def load_sla(path: Path) -> dict[str, Any]:
    data = load_json(path, {})
    domains = data.get("domains") if isinstance(data, dict) else None
    if not isinstance(domains, dict):
        raise SystemExit(f"Missing domains in SLA config: {path}")
    return data


def main_feed_items(feed: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in feed.get("items") or []:
        text = " ".join(str(item.get(k) or "") for k in ("source", "subSource", "category", "headline", "title"))
        if item.get("breaking") is True or "מבזק" in text or "breaking" in text.lower():
            continue
        rows.append(item)
    return rows


def latest_by_domain(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in items:
        domain = str(item.get("category") or "חדשות").strip() or "חדשות"
        dt = parse_dt(item.get("publishedAt"))
        if not dt:
            continue
        if domain not in latest or dt > latest[domain]["publishedAtDt"]:
            latest[domain] = {"publishedAtDt": dt, "item": item}
    return latest


def reserve_counts(path: Path, domain: str, now: datetime) -> dict[str, int]:
    data = load_json(path, {})
    rows: list[dict[str, Any]] = []
    if isinstance(data, dict):
        raw = data.get(domain) or []
        if isinstance(raw, list):
            rows = [r for r in raw if isinstance(r, dict)]
        elif isinstance(data.get("cards"), list):
            rows = [r for r in data["cards"] if isinstance(r, dict) and r.get("domain") == domain]
    ready = near_ready = expired = used = 0
    for row in rows:
        if row.get("usedAt"):
            used += 1
            continue
        exp = parse_dt(row.get("expiresAt"))
        status = str(row.get("status") or "")
        if status == "ready" and exp and exp >= now:
            ready += 1
        elif status in {"near_ready", "near_ready_editor_required"} and exp and exp >= now:
            near_ready += 1
        else:
            expired += 1
    return {"total": len(rows), "ready": ready, "nearReady": near_ready, "expired": expired, "used": used}


def state_for(age: int | None, warn: int, fail: int) -> str:
    if age is None:
        return "missing"
    if age <= warn:
        return "ok"
    if age <= fail:
        return "warning"
    return "fail"


def recommended_action(state: str, reserve_ready: int) -> str:
    if state == "ok":
        return "none"
    if state == "warning":
        return "prepare_domain_rescue"
    if reserve_ready:
        return "use_valid_reserve_after_quality_gate"
    if state == "missing":
        return "prepare_domain_rescue_no_recent_card"
    return "prepare_domain_rescue_high_priority"


def prepare_source_queue(domain: str, max_age_min: int, out_dir: Path) -> dict[str, Any]:
    safe = "".join(ch if ch.isalnum() else "-" for ch in domain).strip("-") or "domain"
    out = out_dir / f"pointa_source_rescue_queue_{safe}.json"
    cmd = [
        sys.executable,
        "scripts/pointa_source_rescue_queue.py",
        "--domain",
        domain,
        "--max-age-min",
        str(max_age_min),
        "--per-source",
        "10",
        "--out",
        str(out),
    ]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=240)
    return {"action": "prepare_source_rescue_queue", "exitCode": proc.returncode, "out": str(out), "stdout": proc.stdout[-1000:], "stderr": proc.stderr[-1000:]}


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    now = now_dt()
    sla = load_sla(Path(args.sla_config))
    feed = load_json(Path(args.feed), {})
    items = main_feed_items(feed if isinstance(feed, dict) else {})
    latest = latest_by_domain(items)
    source_map = load_json(Path(args.domain_sources), {})

    rows = []
    actions = []
    domains_cfg = sla.get("domains") or {}
    for domain, spec in domains_cfg.items():
        if args.domain and domain != args.domain:
            continue
        warn = int(spec.get("warnMinutes", 60))
        fail = int(spec.get("failMinutes", 90))
        latest_row = latest.get(domain)
        latest_dt = latest_row["publishedAtDt"] if latest_row else None
        age = int((now - latest_dt).total_seconds() // 60) if latest_dt else None
        reserve = reserve_counts(Path(args.reserve), domain, now)
        st = state_for(age, warn, fail)
        max_age = int((source_map.get(domain) or {}).get("maxAgeMinutes") or max(fail * 3, 180)) if isinstance(source_map, dict) else max(fail * 3, 180)
        row = {
            "domain": domain,
            "ageMinutes": age,
            "warnMinutes": warn,
            "failMinutes": fail,
            "priority": spec.get("priority"),
            "state": st,
            "latestAt": latest_dt.isoformat(timespec="seconds") if latest_dt else None,
            "latestHeadline": (latest_row or {}).get("item", {}).get("headline"),
            "latestSource": (latest_row or {}).get("item", {}).get("source"),
            "recommendedAction": recommended_action(st, reserve["ready"]),
            "candidateCount": 0,
            "reserveReadyCount": reserve["ready"],
            "reserveNearReadyCount": reserve.get("nearReady", 0),
            "reserveExpiredCount": reserve["expired"],
            "qualityBlocked": False,
            "maxCandidateAgeMinutes": max_age,
        }
        if args.prepare_editor_run and st in {"warning", "fail", "missing"}:
            action = prepare_source_queue(domain, max_age, DEFAULT_OUT.parent)
            row["preparedQueue"] = action.get("out")
            actions.append({"domain": domain, **action})
            q = load_json(Path(action.get("out", "")), {})
            if isinstance(q, dict):
                row["candidateCount"] = len(q.get("items") or [])
                row["qualityBlocked"] = row["candidateCount"] > 0
        rows.append(row)

    status = "fail" if any(r["state"] in {"fail", "missing"} for r in rows) else ("warn" if any(r["state"] == "warning" for r in rows) else "ok")
    return {
        "name": "Pointa domain rescue engine",
        "mode": "dry-run" if args.dry_run else "report-only",
        "status": status,
        "checkedAt": now.isoformat(timespec="seconds"),
        "dryRun": bool(args.dry_run),
        "feed": str(Path(args.feed)),
        "slaConfig": str(Path(args.sla_config)),
        "domains": rows,
        "actions": actions,
        "note": "Does not publish and does not modify feed.json. Prepared queues are reports only; publication still requires editor output and quality gates.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=str(DEFAULT_FEED))
    ap.add_argument("--sla-config", default=str(DEFAULT_SLA))
    ap.add_argument("--domain-sources", default=str(DEFAULT_DOMAIN_SOURCES))
    ap.add_argument("--reserve", default=str(DEFAULT_RESERVE))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--domain", default="")
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--prepare-editor-run", action="store_true", help="Prepare domain-filtered rescue queues only; no publication")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    result = build_report(args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Pointa domain rescue engine: {result['status']} · domains={len(result['domains'])} · out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
