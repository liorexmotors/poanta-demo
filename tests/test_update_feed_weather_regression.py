import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_feed  # noqa: E402


def test_clarified_hebrew_verb_does_not_make_politics_weather():
    title = "שתי שיחות - ואיום אחד: כך בלם טראמפ את התקיפות, וקיפל את נתניהו"
    desc = 'הנשיא האמריקני הבהיר לרה"מ: אתה עלול למצוא את עצמך לבד'

    assert not update_feed.is_weather_forecast_story(title, desc, "וואלה חדשות - פוליטי-מדיני")
    assert update_feed.categorize_item(title, desc, "וואלה חדשות - פוליטי-מדיני") == ("פוליטיקה", "security")


def test_retained_bad_weather_card_from_sports_is_repaired():
    item = {
        "category": "מזג אוויר",
        "categoryClass": "real",
        "source": "וואלה ספורט - כדורגל ישראלי",
        "originalTitle": "פחות מסעיף השחרור? בית\"ר ירושלים תבוא לקראתו של ירדן שועה",
        "context": "הבעלים ברק אברמוב הבהיר לכוכב כי גם אם יביא הצעה מעט נמוכה יותר מסעיף השחרור ייתכן שתיבחן עסקה.",
        "headline": "הבעלים ברק אברמוב הבהיר לכוכב כי גם אם יביא הצעה מעט נמוכה יותר מסעיף",
    }

    repaired = update_feed.refresh_item_pointa(item)

    assert repaired["category"] == "ספורט"
    assert repaired["categoryClass"] == "real"


def test_preserve_daily_weather_item_inside_capped_feed_without_top_pin():
    tz = timezone(timedelta(hours=3))
    now = datetime(2026, 6, 10, 15, 0, tzinfo=tz)
    items = []
    for idx in range(update_feed.MAX_FEED_ITEMS + 5):
        items.append(
            {
                "headline": f"חדשות {idx}",
                "category": "חדשות",
                "source": f"מקור {idx}",
                "publishedAt": (now - timedelta(minutes=idx)).isoformat(timespec="seconds"),
                "hasSourceDate": True,
            }
        )
    weather = {
        "headline": "מזג האוויר בירושלים: 19°–29°; שמיים בהירים",
        "category": "מזג אוויר",
        "source": update_feed.WEATHER_SOURCE,
        "sourceLogo": "IMS",
        "publishedAt": now.replace(hour=6, minute=0).isoformat(timespec="seconds"),
        "hasSourceDate": False,
        "weather": {"city": "ירושלים"},
    }
    items.append(weather)

    limited = update_feed.preserve_daily_weather_item(items, now, update_feed.MAX_FEED_ITEMS)

    assert len(limited) == update_feed.MAX_FEED_ITEMS
    assert any(update_feed.is_service_weather_item(item) for item in limited)
    assert not update_feed.is_service_weather_item(limited[0])
