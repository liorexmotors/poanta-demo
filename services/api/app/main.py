from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .db import connect, db_available
from services.worker.worker.feedback_report import build_report as build_feedback_report

ROOT = Path(__file__).resolve().parents[3]
LEGACY_FEED = ROOT / "feed.json"
SPY_TRENDS = ROOT / "spy_trends.json"
SPY_SCRIPT = ROOT / "scripts" / "generate_spy_trends.py"
DEFAULT_SQLITE = ROOT / "var" / "poanta_feedback.sqlite3"
OPS_REPORTS = {
    "liveAuditor": ROOT / "tmp" / "pointa_live_auditor_last.json",
    "timingAuditor": ROOT / "tmp" / "pointa_timing_auditor_last.json",
    "qualityAuditor": ROOT / "tmp" / "pointa_quality_auditor_last.json",
    "publicationState": ROOT / "tmp" / "publication_events_state.json",
}

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


class UsageRequest(BaseModel):
    deviceId: str | None = None
    eventType: str = "page_view"
    path: str | None = None
    clientTs: str | None = None
    metadata: dict[str, Any] | None = None


def load_legacy_feed() -> dict[str, Any]:
    if not LEGACY_FEED.exists():
        return {"updatedAt": datetime.now(timezone.utc).isoformat(), "items": []}
    return json.loads(LEGACY_FEED.read_text(encoding="utf-8"))


def load_json_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def parse_dt(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def feed_freshness(data: dict[str, Any]) -> dict[str, Any]:
    latest: datetime | None = None
    latest_item: dict[str, Any] | None = None
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        d = parse_dt(item.get("publishedAt"))
        if d and (latest is None or d > latest):
            latest = d
            latest_item = item
    now = datetime.now(latest.tzinfo if latest else timezone.utc)
    age_min = int((now - latest).total_seconds() // 60) if latest else None
    if age_min is None:
        color = "red"
    elif age_min < 15:
        color = "green"
    elif age_min < 30:
        color = "yellow"
    else:
        color = "red"
    return {
        "latestPublishedAt": latest.isoformat() if latest else None,
        "ageMinutes": max(age_min, 0) if age_min is not None else None,
        "color": color,
        "headline": latest_item.get("headline") if latest_item else None,
        "source": latest_item.get("source") if latest_item else None,
        "sourceUrl": latest_item.get("sourceUrl") if latest_item else None,
    }


def sqlite_path() -> Path:
    return Path(os.getenv("POANTA_SQLITE_PATH") or DEFAULT_SQLITE)


def sqlite_available() -> bool:
    return bool(os.getenv("POANTA_SQLITE_PATH")) or not db_available()


def sqlite_connect() -> sqlite3.Connection:
    path = sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          device_id TEXT,
          event_type TEXT NOT NULL,
          path TEXT,
          client_ts TEXT,
          received_at TEXT NOT NULL DEFAULT (datetime('now')),
          metadata TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_received_at ON usage_events (received_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_device_received ON usage_events (device_id, received_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_type_received ON usage_events (event_type, received_at DESC)")
    return conn


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
    return {"ok": True, "service": "api", "checkedAt": datetime.now(timezone.utc).isoformat(), "feedbackStore": "postgres" if db_available() else "sqlite", "sqlitePath": str(sqlite_path()) if not db_available() else None}


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


@app.get("/v1/ops/status")
def ops_status() -> dict[str, Any]:
    """Operational dashboard state for Poanta control agents.

    This endpoint intentionally exposes summarized status only: enough for the
    dashboard to show whether האספן/העורך/השוער/המבקר are healthy, without
    streaming noisy internal logs to users.
    """
    feed_data = load_db_feed() or load_legacy_feed()
    reports = {name: load_json_file(path) for name, path in OPS_REPORTS.items()}
    live = reports.get("liveAuditor") or {}
    timing = reports.get("timingAuditor") or {}
    quality = reports.get("qualityAuditor") or {}
    pub_state = reports.get("publicationState") or {}
    agents = [
        {
            "id": "collector",
            "name": "האספן",
            "status": "ok" if feed_data.get("items") else "fail",
            "summary": f"{len(feed_data.get('items') or [])} כרטיסים זמינים בפיד",
        },
        {
            "id": "editor",
            "name": "העורך",
            "status": "ok" if (feed_data.get("editorRun") or pub_state.get("lastEventAt")) else "idle",
            "summary": "ריצת עריכה/פרסום אחרונה זמינה" if (feed_data.get("editorRun") or pub_state.get("lastEventAt")) else "אין ריצת עריכה אחרונה מזוהה",
        },
        {
            "id": "gatekeeper",
            "name": "השוער",
            "status": "ok" if quality.get("status") == "ok" else "fail" if quality.get("status") == "fail" else "unknown",
            "summary": f"Quality auditor: {quality.get('status') or 'unknown'} · שגיאות {len(quality.get('errors') or [])}",
        },
        {
            "id": "timing",
            "name": "מבקר תזמון",
            "status": "ok" if timing.get("status") == "ok" else "fail" if timing.get("status") == "fail" else "unknown",
            "summary": f"Timing: {timing.get('status') or 'unknown'} · שגיאות {len(timing.get('errors') or [])}",
            "findings": (timing.get("errors") or timing.get("warnings") or [])[:3],
        },
        {
            "id": "live",
            "name": "מבקר חי",
            "status": "ok" if live.get("status") == "ok" else "fail" if live.get("status") == "fail" else "unknown",
            "summary": f"Live auditor: {live.get('status') or 'unknown'} · שגיאות {len(live.get('errors') or [])}",
            "findings": (live.get("errors") or live.get("warnings") or [])[:3],
        },
    ]
    return {
        "ok": True,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "feed": {
            "updatedAt": feed_data.get("updatedAt"),
            "itemCount": len(feed_data.get("items") or []),
            "freshness": feed_freshness(feed_data),
        },
        "publication": {
            "lastEventAt": pub_state.get("lastEventAt"),
            "lastPublishedAt": pub_state.get("lastPublishedAt"),
            "eventCount": pub_state.get("eventCount"),
        },
        "agents": agents,
        "reports": {
            "liveAuditor": {"status": live.get("status"), "checkedAt": live.get("checkedAt"), "errors": live.get("errors") or [], "warnings": live.get("warnings") or []},
            "timingAuditor": {"status": timing.get("status"), "checkedAt": timing.get("checkedAt"), "errors": timing.get("errors") or [], "warnings": timing.get("warnings") or []},
            "qualityAuditor": {"status": quality.get("status"), "checkedAt": quality.get("checkedAt"), "errors": quality.get("errors") or [], "warnings": quality.get("warnings") or []},
        },
    }


@app.get("/v1/spy/trends")
def spy_trends() -> dict[str, Any]:
    """Return the latest generated spy snapshot for the dashboard."""
    data = load_json_file(SPY_TRENDS)
    if data is None:
        return {
            "ok": False,
            "status": "unavailable",
            "generatedAt": None,
            "trends": [],
            "error": "spy_trends.json is not available",
        }
    data.setdefault("ok", data.get("status") == "ok")
    data.setdefault("source", "api-spy-trends-json")
    return data


@app.post("/v1/spy/run")
def run_spy_trends() -> dict[str, Any]:
    """Run the bounded RSS + approved-Web-target spy scan on demand.

    The scan writes only spy_trends.json. It does not mutate or publish feed.json.
    """
    if not SPY_SCRIPT.exists():
        return {"ok": False, "status": "error", "error": "generate_spy_trends.py is missing"}
    started = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(
            ["python3", str(SPY_SCRIPT), "--out", str(SPY_TRENDS)],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "status": "timeout",
            "startedAt": started.isoformat(),
            "finishedAt": datetime.now(timezone.utc).isoformat(),
            "error": "הסריקה חרגה ממגבלת הזמן",
        }
    if proc.returncode != 0:
        return {
            "ok": False,
            "status": "error",
            "startedAt": started.isoformat(),
            "finishedAt": datetime.now(timezone.utc).isoformat(),
            "error": (proc.stderr or proc.stdout or "spy scan failed")[-2000:],
        }
    data = load_json_file(SPY_TRENDS) or {}
    data.update({
        "ok": True,
        "manualRun": True,
        "startedAt": started.isoformat(),
        "finishedAt": datetime.now(timezone.utc).isoformat(),
        "stdout": (proc.stdout or "")[-1000:],
    })
    return data


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
    client_ts = None
    if req.clientTs:
        try:
            client_ts = datetime.fromisoformat(req.clientTs.replace("Z", "+00:00"))
        except Exception:
            client_ts = None
    if not db_available():
        with sqlite_connect() as conn:
            conn.execute(
                """
                INSERT INTO feedback_events (
                  device_id, card_key, source_url, source_name, category,
                  headline, feedback, client_ts, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req.deviceId,
                    req.cardKey,
                    req.sourceUrl,
                    req.source,
                    req.category,
                    req.headline,
                    value,
                    client_ts.isoformat() if client_ts else None,
                    json.dumps(req.metadata or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
        return {"ok": True, "stored": True, "feedback": value, "store": "sqlite"}
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


def parse_client_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def build_usage_report(hours: int = 24) -> dict[str, Any]:
    safe_hours = max(1, min(int(hours), 24 * 30))
    if db_available():
        return {"status": "unavailable", "reason": "usage report is not wired to postgres yet", "windowHours": safe_hours}
    with sqlite_connect() as conn:
        totals = conn.execute(
            """
            SELECT
              COUNT(*) AS events,
              COUNT(DISTINCT COALESCE(NULLIF(device_id,''), 'anon-' || id)) AS users,
              SUM(CASE WHEN event_type IN ('page_view','refresh') THEN 1 ELSE 0 END) AS visits,
              SUM(CASE WHEN event_type='refresh' THEN 1 ELSE 0 END) AS refreshes,
              SUM(CASE WHEN event_type='page_view' THEN 1 ELSE 0 END) AS page_views
            FROM usage_events
            WHERE received_at >= datetime('now', ?)
            """,
            (f"-{safe_hours} hours",),
        ).fetchone()
        by_type = [dict(r) for r in conn.execute(
            """
            SELECT event_type, COUNT(*) AS count, COUNT(DISTINCT COALESCE(NULLIF(device_id,''), 'anon-' || id)) AS users
            FROM usage_events
            WHERE received_at >= datetime('now', ?)
            GROUP BY event_type
            ORDER BY count DESC, event_type ASC
            """,
            (f"-{safe_hours} hours",),
        ).fetchall()]
        recent = [dict(r) for r in conn.execute(
            """
            SELECT device_id, event_type, path, received_at
            FROM usage_events
            WHERE received_at >= datetime('now', ?)
            ORDER BY received_at DESC
            LIMIT 20
            """,
            (f"-{safe_hours} hours",),
        ).fetchall()]
    return {
        "status": "ok",
        "windowHours": safe_hours,
        "users": int(totals["users"] or 0),
        "events": int(totals["events"] or 0),
        "visits": int(totals["visits"] or 0),
        "pageViews": int(totals["page_views"] or 0),
        "refreshes": int(totals["refreshes"] or 0),
        "byType": by_type,
        "recentEvents": recent,
    }


@app.post("/v1/usage")
def usage(req: UsageRequest) -> dict[str, Any]:
    event_type = req.eventType if req.eventType in {"page_view", "refresh", "dashboard_view", "dashboard_refresh"} else "page_view"
    client_ts = parse_client_ts(req.clientTs)
    if not db_available():
        with sqlite_connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_events (device_id, event_type, path, client_ts, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    req.deviceId,
                    event_type,
                    req.path,
                    client_ts.isoformat() if client_ts else None,
                    json.dumps(req.metadata or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
        return {"ok": True, "stored": True, "eventType": event_type, "store": "sqlite"}
    return {"ok": False, "stored": False, "reason": "usage postgres storage is not enabled yet"}


@app.get("/v1/usage/report")
def usage_report(hours: int = 24) -> dict[str, Any]:
    report = build_usage_report(hours=hours)
    report["ok"] = report.get("status") == "ok"
    return report


@app.get("/v1/feedback/report")
def feedback_report(hours: int = 24, limit: int = 20) -> dict[str, Any]:
    """Operational report for Poanta card markings.

    This is the machine-readable חיווי Aliza/מבקר איכות should consume:
    recent 👍👎 events, worst cards, source/category patterns, and action items.
    """
    safe_hours = max(1, min(int(hours), 24 * 30))
    safe_limit = max(1, min(int(limit), 100))
    report = build_feedback_report(hours=safe_hours, limit=safe_limit)
    report["usage"] = build_usage_report(hours=safe_hours)
    report["ok"] = True
    return report
