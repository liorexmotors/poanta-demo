import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_feed  # noqa: E402


def _item(category: str, idx: int) -> dict:
    return {
        "headline": f"כותרת {category} {idx}",
        "context": f"הקשר {category} {idx}",
        "category": category,
        "source": f"מקור {category} {idx % 5}",
        "sourceLogo": f"מקור {category} {idx % 5}",
        "publishedAt": f"2026-05-30T12:{idx % 60:02d}:00+03:00",
        "hasSourceDate": True,
    }


def test_balance_feed_category_mix_caps_sports_and_gossip():
    items = [_item("רכילות", i) for i in range(40)]
    items += [_item("ספורט", i) for i in range(40)]
    items += [_item("ביטחון", i) for i in range(40)]

    balanced = update_feed.balance_feed_category_mix(items)

    assert sum(1 for x in balanced if x["category"] == "רכילות") == 24
    assert sum(1 for x in balanced if x["category"] == "ספורט") == 28
    assert sum(1 for x in balanced if x["category"] == "ביטחון") == 40


def test_official_idf_artillery_update_has_specific_takeaway():
    c = update_feed.Candidate(
        source="דובר צה״ל - טלגרם רשמי",
        url="https://t.me/idf_telegram/example",
        title='דובר צה"ל: צה"ל השמיד מפקדת ארטילריה מאוישת של חיזבאללה',
        description="לאחר התקיפה זוהו פיצוצי משנה המעידים על הימצאות אמצעי לחימה בתוך המבנה.",
        published_at="2026-05-30T12:00:00+03:00",
    )

    fields = update_feed.official_telegram_pointa_fields(c)

    assert fields is not None
    assert fields[2] == "פיצוצי המשנה מעידים שחיזבאללה עדיין מחזיק אמצעי לחימה במבנים צבאיים בדרום לבנון."
    assert "עדכון צבאי נקודתי" not in fields[2]


def test_diversify_visible_top_limits_low_priority_categories():
    items = []
    # Newest low-priority items arrive first, followed by enough current-affairs
    # cards. The visible top should not be swallowed by sports/gossip.
    items += [_item("ספורט", i) for i in range(8)]
    items += [_item("רכילות", i) for i in range(8)]
    items += [_item("ביטחון", i) for i in range(12)]
    items += [_item("פוליטיקה", i) for i in range(4)]

    visible = update_feed.diversify_visible_top(items)[:20]

    assert sum(1 for x in visible if x["category"] == "ספורט") <= 2
    assert sum(1 for x in visible if x["category"] == "רכילות") <= 2
    assert sum(1 for x in visible if x["category"] in update_feed.CURRENT_AFFAIRS_CATEGORIES) >= 12
