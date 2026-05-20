from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .db import connect, db_available

ROOT = Path(__file__).resolve().parents[3]
LEGACY_FEED = ROOT / "feed.json"

app = FastAPI(title="Poanta API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


class DeviceRegisterRequest(BaseModel):
    deviceId: str | None = None
    platform: str | None = None


class FeedbackRequest(BaseModel):
    deviceId: str | None = None
    cardKey: str
    sourceUrl: str | None = None
    source: str | None = None
    category: str | None = None
    headline: str | None = None
    feedback: str
    clientTs: str | None = None
    metadata: dict[str, Any] | None = None


def load_legacy_feed() -> dict[str, Any]:
    if not LEGACY_FEED.exists():
        return {"updatedAt": datetime.now(timezone.utc).isoformat(), "items": []}
    return json.loads(LEGACY_FEED.read_text(encoding="utf-8"))


def load_db_feed() -> dict[str, Any] | None:
    if not db_available():
        return None
    try:
        with connect() as conn:
            version = conn.execute(
                """
                SELECT id, published_at, legacy_updated_at, item_count
                FROM feed_versions
                WHERE status = 'published'
                ORDER BY published_at DESC
                LIMIT 1
                """
            ).fetchone()
            if not version:
                return None
            rows = conn.execute(
                """
                SELECT source_name, source_logo, source_url, original_title, headline,
                       summary, takeaway, category, category_class, image_url,
                       published_at, has_source_date, editor_status, raw
                FROM feed_items
                WHERE feed_version_id = %s
                ORDER BY position ASC
                """,
                (version["id"],),
            ).fetchall()
    except Exception:
        return None
    items = []
    for row in rows:
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        item = dict(raw)
        item.update({
            "source": row.get("source_name"),
            "sourceLogo": row.get("source_logo"),
            "sourceUrl": row.get("source_url"),
            "originalTitle": row.get("original_title"),
            "headline": row.get("headline"),
            "context": row.get("summary"),
            "takeaway": row.get("takeaway"),
            "category": row.get("category"),
            "categoryClass": row.get("category_class"),
            "imageUrl": row.get("image_url"),
            "publishedAt": row.get("published_at").isoformat() if row.get("published_at") else item.get("publishedAt"),
            "hasSourceDate": row.get("has_source_date"),
            "editorStatus": row.get("editor_status"),
        })
        items.append(item)
    return {
        "updatedAt": version.get("legacy_updated_at") or version.get("published_at").isoformat(),
        "mode": "db-feed-version",
        "items": items,
        "source": "postgres-feed-version",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "api", "checkedAt": datetime.now(timezone.utc).isoformat()}


@app.get("/v1/feed")
def feed() -> dict[str, Any]:
    db_feed = load_db_feed()
    if db_feed is not None:
        return db_feed
    data = load_legacy_feed()
    return {
        "updatedAt": data.get("updatedAt"),
        "mode": data.get("mode", "legacy-feed-json"),
        "items": data.get("items", []),
        "source": "legacy-feed-json",
    }


@app.get("/v1/sources")
def sources() -> dict[str, Any]:
    data = load_legacy_feed()
    names = sorted({str(item.get("source") or "מקור") for item in data.get("items", [])})
    return {"items": [{"name": name} for name in names]}


@app.get("/v1/topics")
def topics() -> dict[str, Any]:
    data = load_legacy_feed()
    names = sorted({str(item.get("category") or "חדשות") for item in data.get("items", [])})
    return {"items": [{"name": name} for name in names]}


@app.post("/v1/device/register")
def register_device(req: DeviceRegisterRequest) -> dict[str, Any]:
    device_id = req.deviceId or f"anon-{int(datetime.now(timezone.utc).timestamp())}"
    return {"deviceId": device_id, "anonymous": True}


@app.post("/v1/feedback")
def feedback(req: FeedbackRequest) -> dict[str, Any]:
    value = req.feedback if req.feedback in {"up", "down", "clear"} else "clear"
    if not db_available():
        return {"ok": False, "stored": False, "reason": "database_not_configured"}
    client_ts = None
    if req.clientTs:
        try:
            client_ts = datetime.fromisoformat(req.clientTs.replace("Z", "+00:00"))
        except Exception:
            client_ts = None
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO feedback_events (
              device_id, card_key, source_url, source_name, category,
              headline, feedback, client_ts, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                req.deviceId,
                req.cardKey,
                req.sourceUrl,
                req.source,
                req.category,
                req.headline,
                value,
                client_ts,
                json.dumps(req.metadata or {}),
            ),
        )
    return {"ok": True, "stored": True, "feedback": value}
