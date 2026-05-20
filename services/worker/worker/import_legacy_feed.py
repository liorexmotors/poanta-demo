from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[3]
FEED_PATH = ROOT / "feed.json"
MIGRATION_PATH = ROOT / "infra" / "migrations" / "001_initial.sql"


def database_url() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("POANTA_DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL/POANTA_DATABASE_URL is required")
    return url


def parse_dt(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


def version_key(feed: dict[str, Any]) -> str:
    updated = str(feed.get("updatedAt") or "unknown")
    digest = hashlib.sha1(json.dumps(feed.get("items", []), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return f"legacy:{updated}:{digest}"


def run_migrations(conn: psycopg.Connection) -> None:
    conn.execute(MIGRATION_PATH.read_text(encoding="utf-8"))


def import_feed(feed_path: Path = FEED_PATH) -> dict[str, Any]:
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    items = feed.get("items", [])
    key = version_key(feed)
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        run_migrations(conn)
        existing = conn.execute("SELECT id FROM feed_versions WHERE version_key = %s", (key,)).fetchone()
        if existing:
            return {"status": "exists", "versionKey": key, "items": len(items)}
        row = conn.execute(
            """
            INSERT INTO feed_versions (version_key, source, legacy_updated_at, item_count, metadata)
            VALUES (%s, 'legacy_feed_json', %s, %s, %s)
            RETURNING id
            """,
            (key, feed.get("updatedAt"), len(items), json.dumps({"mode": feed.get("mode"), "importedFrom": str(feed_path)})),
        ).fetchone()
        version_id = row["id"]
        for pos, item in enumerate(items):
            source_name = str(item.get("source") or "מקור")
            source_logo = item.get("sourceLogo")
            source_url = item.get("sourceUrl")
            source = conn.execute(
                """
                INSERT INTO sources (name, logo, url, is_foreign)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET logo = COALESCE(EXCLUDED.logo, sources.logo), url = COALESCE(EXCLUDED.url, sources.url)
                RETURNING id
                """,
                (source_name, source_logo, source_url, bool(source_logo in {"BBC", "CNN", "Reuters", "AP", "NYT", "Guardian", "Al Jazeera", "Bloomberg", "Axios", "Politico", "Sky News"})),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO feed_items (
                  feed_version_id, source_id, source_name, source_logo, source_url,
                  original_title, headline, summary, takeaway, category, category_class,
                  image_url, published_at, has_source_date, editor_status, position, raw
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    version_id,
                    source["id"],
                    source_name,
                    source_logo,
                    source_url,
                    item.get("originalTitle"),
                    item.get("headline") or "",
                    item.get("context") or "",
                    item.get("takeaway") or "",
                    item.get("category") or "חדשות",
                    item.get("categoryClass"),
                    item.get("imageUrl"),
                    parse_dt(item.get("publishedAt")),
                    bool(item.get("hasSourceDate")),
                    item.get("editorStatus"),
                    pos,
                    json.dumps(item, ensure_ascii=False),
                ),
            )
        return {"status": "imported", "versionKey": key, "items": len(items)}


def main() -> int:
    result = import_feed(Path(sys.argv[1]) if len(sys.argv) > 1 else FEED_PATH)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
