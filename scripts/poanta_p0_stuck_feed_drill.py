#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 stuck-feed disaster drill.

Regression test for the incident class where FAST/finalizer/cron reports OK
while unsafe content ships. Freshness gaps are now monitoring warnings, not
candidate-publication blockers: the feed should keep a good 7-day archive live
even during a quiet news cycle.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=3))


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)


def make_feed(path: Path, *, fresh: bool, gossip_ok: bool = True) -> None:
    now = datetime.now(TZ)
    top_time = now - (timedelta(minutes=10) if fresh else timedelta(minutes=70))
    items = []
    for i in range(12):
        d = top_time - timedelta(minutes=i)
        items.append({
            "id": f"drill-{i}",
            "source": "ynet" if i % 3 == 0 else ("וואלה" if i % 3 == 1 else "מעריב"),
            "sourceLogo": "ynet" if i % 3 == 0 else ("וואלה" if i % 3 == 1 else "מעריב"),
            "sourceUrl": f"https://example.com/{i}",
            "publishedAt": d.isoformat(timespec="seconds"),
            "hasSourceDate": True,
            "category": "חדשות",
            "categoryClass": "security",
            "headline": f"כרטיס בדיקה טרי מספר {i} מציג אירוע ברור",
            "originalTitle": f"כותרת מקור לבדיקה {i}",
            "context": "זהו כרטיס בדיקה עם תיאור עובדתי מספיק שמדמה ידיעה אמיתית בפיד.",
            "takeaway": "כרטיסי בדיקה חייבים להוכיח שהפיד באמת מתעדכן בזמן.",
            "imageUrl": "https://example.com/image.jpg",
        })
    if not gossip_ok:
        items[0].update({
            "source": "וואלה סלבס - כל הכתבות",
            "sourceLogo": "וואלה סלבס",
            "category": "תרבות",
            "headline": "ריאליטי הבישול מגייס פרעון פוליטי ובנו",
            "imageUrl": None,
        })
    updated_at = now if fresh else now - timedelta(hours=4)
    path.write_text(json.dumps({"updatedAt": updated_at.isoformat(timespec="seconds"), "items": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        stale = Path(td) / "stale.json"
        fresh = Path(td) / "fresh.json"
        bad_gossip = Path(td) / "bad_gossip.json"
        make_feed(stale, fresh=False)
        make_feed(fresh, fresh=True)
        make_feed(bad_gossip, fresh=True, gossip_ok=False)

        stale_gate = run([sys.executable, "scripts/pointa_publication_health_gate.py", "--mode", "candidate", "--feed", str(stale), "--json"])
        fresh_gate = run([sys.executable, "scripts/pointa_publication_health_gate.py", "--mode", "candidate", "--feed", str(fresh), "--json"])
        bad_qg = run([sys.executable, "scripts/pointa_quality_gate.py", "--feed", str(bad_gossip), "--report", str(Path(td) / "qg.md")])

        stale_report = json.loads(stale_gate.stdout)
        stale_ok = (
            stale_gate.returncode == 0
            and stale_report.get("status") == "ok"
            and any(signal.get("code") in {"no_new_top_item_sla", "stale_updated_at"} for signal in stale_report.get("freshnessSignals") or [])
        )
        fresh_ok = fresh_gate.returncode == 0
        gossip_blocked = bad_qg.returncode != 0 and "gossip_missing_image" in (Path(td) / "qg.md").read_text(encoding="utf-8") and "category_celebs" in (Path(td) / "qg.md").read_text(encoding="utf-8")

        report = {
            "staleFeedPublishesWithFreshnessWarning": stale_ok,
            "freshFeedPasses": fresh_ok,
            "badGossipBlocked": gossip_blocked,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if all(report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
