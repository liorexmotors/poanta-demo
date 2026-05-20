from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime, timezone
from typing import Any


def database_url() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("POANTA_DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL/POANTA_DATABASE_URL is required")
    return url


def sqlite_path() -> Path | None:
    raw = os.getenv("POANTA_SQLITE_PATH")
    if raw:
        return Path(raw)
    if not (os.getenv("DATABASE_URL") or os.getenv("POANTA_DATABASE_URL")):
        return Path(__file__).resolve().parents[3] / "var" / "poanta_feedback.sqlite3"
    return None


def init_sqlite(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          device_id TEXT,
          card_key TEXT NOT NULL,
          source_url TEXT,
          source_name TEXT,
          category TEXT,
          headline TEXT,
          feedback TEXT NOT NULL CHECK (feedback IN ('up', 'down', 'clear')),
          client_ts TEXT,
          received_at TEXT NOT NULL DEFAULT (datetime('now')),
          metadata TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_events_received_at ON feedback_events (received_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_events_card_key ON feedback_events (card_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_events_source_name ON feedback_events (source_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_events_feedback_received_at ON feedback_events (feedback, received_at DESC)")


def _sqlite_rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def build_sqlite_report(path: Path, hours: int, limit: int) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    since_modifier = f"-{int(hours)} hours"
    with sqlite3.connect(path) as conn:
        init_sqlite(conn)
        totals = _sqlite_rows(conn, """
            SELECT feedback, count(*) AS count
            FROM feedback_events
            WHERE datetime(received_at) >= datetime('now', ?)
            GROUP BY feedback
            ORDER BY feedback
        """, (since_modifier,))
        by_source = _sqlite_rows(conn, """
            SELECT coalesce(nullif(source_name, ''), 'unknown') AS source_name,
                   feedback, count(*) AS count
            FROM feedback_events
            WHERE datetime(received_at) >= datetime('now', ?)
            GROUP BY coalesce(nullif(source_name, ''), 'unknown'), feedback
            ORDER BY source_name, feedback
        """, (since_modifier,))
        by_category = _sqlite_rows(conn, """
            SELECT coalesce(nullif(category, ''), 'unknown') AS category,
                   feedback, count(*) AS count
            FROM feedback_events
            WHERE datetime(received_at) >= datetime('now', ?)
            GROUP BY coalesce(nullif(category, ''), 'unknown'), feedback
            ORDER BY category, feedback
        """, (since_modifier,))
        cards = _sqlite_rows(conn, """
            SELECT card_key,
                   max(headline) AS headline,
                   max(source_name) AS source_name,
                   max(source_url) AS source_url,
                   max(category) AS category,
                   max(received_at) AS last_feedback_at,
                   sum(CASE WHEN feedback = 'down' THEN 1 ELSE 0 END) AS down_count,
                   sum(CASE WHEN feedback = 'up' THEN 1 ELSE 0 END) AS up_count,
                   sum(CASE WHEN feedback = 'clear' THEN 1 ELSE 0 END) AS clear_count,
                   count(*) AS total_count
            FROM feedback_events
            WHERE datetime(received_at) >= datetime('now', ?)
            GROUP BY card_key
            ORDER BY down_count DESC, up_count ASC, total_count DESC, last_feedback_at DESC
            LIMIT ?
        """, (since_modifier, limit))
        recent = _sqlite_rows(conn, """
            SELECT received_at, feedback, card_key, headline, source_name, source_url, category
            FROM feedback_events
            WHERE datetime(received_at) >= datetime('now', ?)
            ORDER BY received_at DESC
            LIMIT ?
        """, (since_modifier, limit))
    return build_report_payload(hours, totals, by_source, by_category, cards, recent, store="sqlite")


def _ratio(up: int, down: int) -> float:
    total = up + down
    return round(down / total, 3) if total else 0.0


def _row_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def build_report_payload(hours: int, totals: list[dict[str, Any]], by_source: list[dict[str, Any]], by_category: list[dict[str, Any]], cards: list[dict[str, Any]], recent: list[dict[str, Any]], *, store: str) -> dict[str, Any]:
    cards_out: list[dict[str, Any]] = []
    action_items: list[dict[str, Any]] = []
    for row in cards:
        card = dict(row)
        up = int(card.get("up_count") or 0)
        down = int(card.get("down_count") or 0)
        card["downRatio"] = _ratio(up, down)
        if down >= 1:
            if down >= 2 or card["downRatio"] >= 0.67:
                action = "editor_review_required"
                owner = "העורך + השוער"
            else:
                action = "watch"
                owner = "המבקר"
            action_items.append({
                "action": action,
                "owner": owner,
                "cardKey": card.get("card_key"),
                "headline": card.get("headline"),
                "source": card.get("source_name"),
                "sourceUrl": card.get("source_url"),
                "down": down,
                "up": up,
                "downRatio": card["downRatio"],
            })
        cards_out.append(card)

    return {
        "status": "ok",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "windowHours": hours,
        "store": store,
        "totals": _row_dicts(totals),
        "bySource": _row_dicts(by_source),
        "byCategory": _row_dicts(by_category),
        "cards": cards_out,
        "worstCards": [c for c in cards_out if int(c.get("down_count") or 0) > 0],
        "recentEvents": _row_dicts(recent),
        "actionItems": action_items,
        "routing": ["מבקר איכות", "העורך", "השוער"],
        "mode": "actionable-report",
    }


def build_report(hours: int = 24, limit: int = 20) -> dict[str, Any]:
    """Build an operational report for Poanta card feedback markings.

    The report is intentionally action-oriented: it does not just count 👍/👎;
    it identifies cards/sources/categories that should go back to the editor,
    gatekeeper, or source policy loop.
    """
    spath = sqlite_path()
    if spath is not None:
        return build_sqlite_report(spath, hours, limit)

    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        totals = conn.execute(
            """
            SELECT feedback, count(*) AS count
            FROM feedback_events
            WHERE received_at >= now() - (%s || ' hours')::interval
            GROUP BY feedback
            ORDER BY feedback
            """,
            (hours,),
        ).fetchall()
        by_source = conn.execute(
            """
            SELECT coalesce(nullif(source_name, ''), 'unknown') AS source_name,
                   feedback, count(*) AS count
            FROM feedback_events
            WHERE received_at >= now() - (%s || ' hours')::interval
            GROUP BY coalesce(nullif(source_name, ''), 'unknown'), feedback
            ORDER BY source_name, feedback
            """,
            (hours,),
        ).fetchall()
        by_category = conn.execute(
            """
            SELECT coalesce(nullif(category, ''), 'unknown') AS category,
                   feedback, count(*) AS count
            FROM feedback_events
            WHERE received_at >= now() - (%s || ' hours')::interval
            GROUP BY coalesce(nullif(category, ''), 'unknown'), feedback
            ORDER BY category, feedback
            """,
            (hours,),
        ).fetchall()
        cards = conn.execute(
            """
            SELECT card_key,
                   max(headline) AS headline,
                   max(source_name) AS source_name,
                   max(source_url) AS source_url,
                   max(category) AS category,
                   max(received_at) AS last_feedback_at,
                   count(*) FILTER (WHERE feedback = 'down') AS down_count,
                   count(*) FILTER (WHERE feedback = 'up') AS up_count,
                   count(*) FILTER (WHERE feedback = 'clear') AS clear_count,
                   count(*) AS total_count
            FROM feedback_events
            WHERE received_at >= now() - (%s || ' hours')::interval
            GROUP BY card_key
            ORDER BY down_count DESC, up_count ASC, total_count DESC, last_feedback_at DESC
            LIMIT %s
            """,
            (hours, limit),
        ).fetchall()
        recent = conn.execute(
            """
            SELECT received_at, feedback, card_key, headline, source_name, source_url, category
            FROM feedback_events
            WHERE received_at >= now() - (%s || ' hours')::interval
            ORDER BY received_at DESC
            LIMIT %s
            """,
            (hours, limit),
        ).fetchall()

    return build_report_payload(hours, _row_dicts(totals), _row_dicts(by_source), _row_dicts(by_category), _row_dicts(cards), _row_dicts(recent), store="postgres")


def compact_counts(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        grouped[str(row.get(key) or "unknown")][str(row.get("feedback") or "unknown")] += int(row.get("count") or 0)
    out = []
    for name, counts in grouped.items():
        up = counts.get("up", 0)
        down = counts.get("down", 0)
        clear = counts.get("clear", 0)
        out.append({"name": name, "up": up, "down": down, "clear": clear, "downRatio": _ratio(up, down)})
    return sorted(out, key=lambda x: (-x["down"], -x["downRatio"], x["name"]))


def format_hebrew_report(report: dict[str, Any]) -> str:
    totals = {str(r.get("feedback")): int(r.get("count") or 0) for r in report.get("totals", [])}
    up = totals.get("up", 0)
    down = totals.get("down", 0)
    clear = totals.get("clear", 0)
    lines = [
        f"דוח סימוני פואנטה — {report.get('windowHours')} שעות אחרונות",
        f"סה״כ: 👍 {up} · 👎 {down} · ניקוי {clear}",
    ]

    actions = report.get("actionItems") or []
    if actions:
        lines.append("")
        lines.append("דורש טיפול:")
        for item in actions[:8]:
            lines.append(
                f"• {item.get('headline') or 'ללא כותרת'} — 👎 {item.get('down')} / 👍 {item.get('up')} · {item.get('source') or 'מקור לא ידוע'} · {item.get('owner')}"
            )
    else:
        lines.append("")
        lines.append("אין כרטיסים שסומנו לשלילה ודורשים טיפול כרגע.")

    sources = compact_counts(report.get("bySource", []), "source_name")[:5]
    if sources:
        lines.append("")
        lines.append("מקורות בולטים לפי סימון שלילי:")
        for src in sources:
            if src["down"]:
                lines.append(f"• {src['name']}: 👎 {src['down']} / 👍 {src['up']} ({src['downRatio']:.0%} שלילי)")

    recent = report.get("recentEvents") or []
    if recent:
        lines.append("")
        lines.append("סימונים אחרונים:")
        for ev in recent[:5]:
            emoji = {"up": "👍", "down": "👎", "clear": "ניקוי"}.get(str(ev.get("feedback")), str(ev.get("feedback")))
            lines.append(f"• {emoji} {ev.get('headline') or ev.get('card_key')} · {ev.get('source_name') or ''}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Poanta feedback markings report")
    parser.add_argument("--hours", type=int, default=int(os.getenv("FEEDBACK_REPORT_HOURS", "24")))
    parser.add_argument("--limit", type=int, default=int(os.getenv("FEEDBACK_REPORT_LIMIT", "20")))
    parser.add_argument("--format", choices=["json", "text"], default=os.getenv("FEEDBACK_REPORT_FORMAT", "json"))
    args = parser.parse_args()
    report = build_report(args.hours, args.limit)
    if args.format == "text":
        print(format_hebrew_report(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
