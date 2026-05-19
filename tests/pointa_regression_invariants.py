#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.update_feed import categorize_item, story_headline, story_context, story_takeaway


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
    test_marlin_al_turi_card()
    print('Pointa regression invariants: OK')
