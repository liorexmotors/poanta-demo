#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.update_feed import categorize_item, story_headline, story_context, story_takeaway, build_daily_weather_card


def assert_eq(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_in(needle, haystack, label):
    if needle not in haystack:
        raise AssertionError(f"{label}: expected {needle!r} in {haystack!r}")


def test_akko_ebike_accident():
    title = 'רוכב אופניים חשמליים בן 10 נפצע בתאונה בעכו - מצבו בינוני'
    desc = 'ילד בן 10, רוכב אופניים חשמליים נפגע היום (שלישי), באורח בינוני מרכב ברחוב האורן בעכו.'
    source = 'וואלה חדשות - מבזקים'
    category, _ = categorize_item(title, desc, source)
    assert_eq(category, 'רכב', 'Akko e-bike accident category')
    headline = story_headline(title, desc, source)
    assert_in('עכו', headline, 'Akko e-bike accident headline location')
    assert_in('ילד בן 10', headline, 'Akko e-bike accident headline subject')
    context = story_context(title, desc, source)
    assert_in('רחוב האורן בעכו', context, 'Akko e-bike accident context location')
    takeaway = story_takeaway(category, title, desc)
    assert 'הפרט שקובע' not in takeaway, 'Akko e-bike accident takeaway must not be generic'


def test_weather_card_default_jerusalem():
    sample = '''<?xml version='1.0' encoding='us-ascii'?><rss version="2.0"><channel><title>תחזית לירושלים</title><item><description><![CDATA[עדכון אחרון: 2026-05-20 04:55<br/><br/>טמפ. המינימום בלילה: 16°<br/>:20/05 יום רביעי<br/>מעונן חלקית, 24°-13°]]></description></item></channel></rss>'''
    from datetime import datetime, timezone, timedelta
    card = build_daily_weather_card(datetime(2026, 5, 20, 6, 5, tzinfo=timezone(timedelta(hours=3))), fetcher=lambda url, timeout=15: sample)
    assert card, 'Weather card should be generated after 06:00'
    assert_eq(card['category'], 'מזג אוויר', 'Weather card category')
    assert_in('ירושלים', card['headline'], 'Weather headline city')
    assert_in('13°–24°', card['headline'], 'Weather headline min-max')
    assert_eq(card['weather']['dailyHour'], 6, 'Weather daily hour')


def test_weather_card_force_preview():
    sample = """<?xml version='1.0' encoding='us-ascii'?><rss version="2.0"><channel><title>תחזית לירושלים</title><item><description><![CDATA[עדכון אחרון: 2026-05-19 17:43<br/><br/>טמפ. המינימום בלילה: 16°<br/>:20/05 יום רביעי<br/>מעונן חלקית, 24°-13°]]></description></item></channel></rss>"""
    from datetime import datetime, timezone, timedelta
    card = build_daily_weather_card(datetime(2026, 5, 19, 21, 30, tzinfo=timezone(timedelta(hours=3))), fetcher=lambda url, timeout=15: sample, force=True)
    assert card, 'Forced weather card should be available for an exceptional preview update'
    assert_in('ירושלים', card['headline'], 'Forced weather card city')
    assert_in('13°–24°', card['headline'], 'Forced weather card min-max')


def test_marlin_al_turi_card():
    title = 'מרלין חשדה שמשהו רע יקרה. הבעל דרס, דקר - והצית ברכב'
    desc = 'מרלין אלטורי (30) הגיעה עם בעלה לשטח פתוח באזור נחשונים. היא הייתה איתו שם כמה שעות - ואז פנתה לחברתה בחשש.'
    source = 'ynet - כל ערוץ החדשות'
    category, _ = categorize_item(title, desc, source)
    assert_eq(category, 'פלילים', 'Marlin Al-Turi category')
    headline = story_headline(title, desc, source)
    assert_in('מרלין אלטורי', headline, 'Marlin headline name')
    assert_in('נדרסה', headline, 'Marlin headline violent event')
    takeaway = story_takeaway(category, title, desc)
    assert 'הפרט שקובע' not in takeaway, 'Marlin takeaway must not be generic'
    assert_in('אלימות זוגית', takeaway, 'Marlin takeaway article-specific bottom line')


if __name__ == '__main__':
    test_akko_ebike_accident()
    test_weather_card_default_jerusalem()
    test_weather_card_force_preview()
    test_marlin_al_turi_card()
    print('Pointa regression invariants: OK')
