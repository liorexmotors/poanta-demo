#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Produce a concise Poanta agent accountability report.

This report is for Lior: what broke, which agent owned it, what was fixed,
and what preventive guard was added so the same class of mistake is less likely
next time.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=3))

AGENT_KEYWORDS = {
    "האוסף": ["source", "rss", "candidate", "prepare", "fresh"],
    "העורך": ["editor", "headline", "takeaway", "summary", "pointa"],
    "השוער": ["finalize", "deploy", "quality", "gate", "feed snapshot"],
    "המבקר": ["auditor", "audit", "stale", "live"],
    "המתקן": ["repair", "fix", "regression", "guard"],
}


def run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def classify(text: str) -> str:
    low = text.lower()
    hits = []
    for agent, keys in AGENT_KEYWORDS.items():
        if any(k in low for k in keys):
            hits.append(agent)
    return "+".join(hits[:2]) if hits else "לא זוהה"


def git_lines() -> list[str]:
    raw = run(["git", "log", "--since=6 hours ago", "--pretty=format:%h%x09%s", "--", "."])
    if not raw:
        return []
    lines = []
    for row in raw.splitlines()[:12]:
        sha, _, msg = row.partition("\t")
        owner = classify(msg)
        lines.append(f"• {sha} · {owner}: {msg}")
    return lines


def cron_status_lines() -> list[str]:
    jobs = load_json(Path.home() / ".openclaw" / "cron" / "jobs.json")
    if isinstance(jobs, dict):
        vals = jobs.get("jobs") or jobs.get("items") or jobs.values()
    else:
        vals = jobs if isinstance(jobs, list) else []
    wanted = ["Poanta", "פואנט", "המבקר", "editor", "FAST", "MEDIUM", "SLOW"]
    out = []
    for job in vals:
        if not isinstance(job, dict):
            continue
        name = str(job.get("name") or "")
        if not any(w.lower() in name.lower() for w in wanted):
            continue
        state = job.get("state") or {}
        enabled = "פעיל" if job.get("enabled", True) else "כבוי"
        status = state.get("lastRunStatus") or state.get("lastStatus") or "לא ידוע"
        out.append(f"• {name}: {enabled}, ריצה אחרונה {status}")
    return out[:10]


def auditor_section() -> tuple[list[str], bool]:
    data = load_json(ROOT / "tmp" / "pointa_live_auditor_last.json")
    if not data:
        return (["• אין קובץ מבקר אחרון."], True)
    status = data.get("status", "unknown")
    lines = [f"• מבקר חי: {status} · updatedAt {data.get('updatedAt','?')} · פריטים {data.get('items','?')}"]
    errors = data.get("errors") or []
    warnings = data.get("warnings") or []
    for e in errors[:5]:
        lines.append(f"  - שגיאה: {e.get('code')} · {e.get('headline') or e.get('message')}")
    for w in warnings[:3]:
        lines.append(f"  - אזהרה: {w.get('code')} · {w.get('headline') or w.get('message')}")
    return lines, bool(errors)


def main() -> int:
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    auditor, has_errors = auditor_section()
    commits = git_lines()
    cron = cron_status_lines()

    print(f"דו״ח סוכני פואנטה — {now}")
    print()
    print("מצב חי:")
    print("\n".join(auditor))
    print()
    print("תיקונים/חיזוקים ב־6 השעות האחרונות:")
    if commits:
        print("\n".join(commits))
    else:
        print("• לא זוהו קומיטים/תיקונים חדשים בפרק הזמן הזה.")
    print()
    print("מצב אוטומציות:")
    if cron:
        print("\n".join(cron))
    else:
        print("• לא נמצאו סטטוסים זמינים לאוטומציות פואנטה.")
    print()
    if has_errors:
        print("נדרש טיפול: יש שגיאות מבקר פתוחות. המתקן צריך לטפל, להריץ QA, לפרסם, ולהריץ מבקר חוזר.")
    else:
        print("סיכום: אין שגיאות מבקר פתוחות כרגע. אם הייתה תקלה ותוקנה, יש לוודא שנוסף guard/QA/נוהל מניעתי.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
