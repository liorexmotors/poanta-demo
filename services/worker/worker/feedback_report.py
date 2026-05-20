from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row


def database_url() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("POANTA_DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL/POANTA_DATABASE_URL is required")
    return url


def build_report(hours: int = 24) -> dict:
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
            SELECT source_name, feedback, count(*) AS count
            FROM feedback_events
            WHERE received_at >= now() - (%s || ' hours')::interval
            GROUP BY source_name, feedback
            ORDER BY source_name, feedback
            """,
            (hours,),
        ).fetchall()
        worst_cards = conn.execute(
            """
            SELECT card_key, max(headline) AS headline, max(source_name) AS source_name,
                   count(*) FILTER (WHERE feedback = 'down') AS down_count,
                   count(*) FILTER (WHERE feedback = 'up') AS up_count
            FROM feedback_events
            WHERE received_at >= now() - (%s || ' hours')::interval
            GROUP BY card_key
            HAVING count(*) FILTER (WHERE feedback = 'down') > 0
            ORDER BY down_count DESC, up_count ASC
            LIMIT 20
            """,
            (hours,),
        ).fetchall()
    return {
        "status": "ok",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "windowHours": hours,
        "totals": [dict(r) for r in totals],
        "bySource": [dict(r) for r in by_source],
        "worstCards": [dict(r) for r in worst_cards],
        "routing": ["מבקר איכות", "העורך"],
        "mode": "report-only",
    }


def main() -> int:
    hours = int(os.getenv("FEEDBACK_REPORT_HOURS", "24"))
    print(json.dumps(build_report(hours), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
