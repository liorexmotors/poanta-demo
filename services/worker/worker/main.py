from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    feed_path = ROOT / "feed.json"
    if not feed_path.exists():
        print(json.dumps({"ok": False, "error": "feed.json missing"}, ensure_ascii=False))
        return 1
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    print(json.dumps({
        "ok": True,
        "service": "worker",
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "legacyFeedUpdatedAt": feed.get("updatedAt"),
        "items": len(feed.get("items") or []),
        "next": "replace this smoke check with collector/editor/qa jobs",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
