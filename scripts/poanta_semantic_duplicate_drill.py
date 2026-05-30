#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression drill for semantic duplicate story filtering.

This drill covers cases where two cards are the same news event from different
sources but wording overlap is too low for exact/title-only dedupe.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pointa_live_auditor import likely_duplicate_story  # noqa: E402
import update_feed  # noqa: E402


CASES = [
    (
        "us_southern_iran_strikes_cross_language",
        True,
        {
            "source": "New York Times Middle East",
            "category": "ביטחון",
            "headline": "ארה״ב ביצעה תקיפות הגנה עצמית בדרום איראן",
            "originalTitle": "U.S. Carries Out Renewed Strikes in Southern Iran",
            "context": "פיקוד המרכז האמריקני מסר כי תקף אתרי שיגור טילים וסירות איראניות שניסו להניח מוקשים, כדי להגן על כוחותיו בזמן הפסקת האש. התקיפות ליד בנדר עבאס הגיעו במקביל לשיחות בדוחא על סיום המלחמה ועל פתיחת מצר הורמוז.",
            "sourceUrl": "https://www.nytimes.com/example-us-iran-strikes",
        },
        {
            "source": "וואלה חדשות - מבזקים",
            "category": "ביטחון",
            "headline": "ארה״ב אישרה תקיפות הגנתיות בתוך איראן",
            "originalTitle": "ארה\"ב אישרה כי כוחותיה ביצעו הלילה תקיפות \"להגנה עצמית\" בשטח איראן",
            "context": "פיקוד המרכז האמריקני אישר שכוחות ארה״ב תקפו בתוך איראן אתרי שיגור טילים וסירות שניסו להניח מוקשים. הפיקוד הציג את הפעולה כהגנה עצמית במהלך הפסקת האש.",
            "sourceUrl": "https://news.walla.co.il/break/example-us-iran-strikes",
        },
    ),
    (
        "hormuz_talks_background_not_same_as_strike",
        False,
        {
            "source": "The Guardian Middle East",
            "category": "ביטחון",
            "headline": "רוביו מאיים לפתוח את הורמוז בזמן שיחות עם איראן",
            "originalTitle": "Tehran expresses ‘resolute support’ for Hezbollah – as it happened",
            "context": "שר החוץ האמריקני מרקו רוביו אמר שמצר הורמוז חייב להיפתח כך או אחרת, אחרי תקיפות אמריקניות בדרום איראן. במקביל, נציגים איראניים הגיעו לדוחא לשיחות על הסכם אפשרי.",
            "sourceUrl": "https://www.theguardian.com/example-hormuz-talks",
        },
        {
            "source": "New York Times Middle East",
            "category": "ביטחון",
            "headline": "ארה״ב ביצעה תקיפות הגנה עצמית בדרום איראן",
            "originalTitle": "U.S. Carries Out Renewed Strikes in Southern Iran",
            "context": "פיקוד המרכז האמריקני מסר כי תקף אתרי שיגור טילים וסירות איראניות שניסו להניח מוקשים ליד בנדר עבאס.",
            "sourceUrl": "https://www.nytimes.com/example-us-iran-strikes",
        },
    ),
    (
        "weather_shavuot_rain_wind",
        True,
        {
            "source": "וואלה חדשות",
            "category": "חדשות",
            "headline": "גשם ורוחות ילוו את ערב שבועות בצפון ובמרכז",
            "originalTitle": "חג שבועות חורפי: גשם מקומי ורוחות ערות ברחבי הארץ",
            "context": "היום ומחר צפויה ירידה בטמפרטורות, עם גשם מקומי בצפון ובמרכז ורוחות ערות.",
            "sourceUrl": "https://news.walla.co.il/item/3839781",
        },
        {
            "source": "מעריב - חדשות",
            "category": "חדשות",
            "headline": "גשם ורוחות צפויים בערב חג השבועות",
            "originalTitle": "רגע לפני ערב חג השבועות - שינוי מפתיע במזג האוויר",
            "context": "בערב חג השבועות צפויה ירידה נוספת בטמפרטורות. בצפון ובמרכז צפויים גשמים ורוחות.",
            "sourceUrl": "https://www.maariv.co.il/news/weather/article-1323962",
        },
    ),
    (
        "same_concert_move",
        True,
        {
            "source": "וואלה חדשות",
            "category": "תרבות",
            "headline": "נשף רוק של אביב גפן הוקדם ל־17 ביוני",
            "context": "המופע הוקדם בגלל שלוש הופעות ענק באזור גוש דן באותו שבוע.",
            "sourceUrl": "https://news.walla.co.il/example-a",
        },
        {
            "source": "ישראל היום - כל הכתבות",
            "category": "תרבות",
            "headline": "נשף רוק הוקדם בגלל שלוש הופעות ענק בגוש דן",
            "context": "אביב גפן הזיז את הנשף ל־17 ביוני כדי לא להתנגש עם עומס מופעים גדול בגוש דן.",
            "sourceUrl": "https://www.israelhayom.co.il/example-b",
        },
    ),
    (
        "lod_residential_fire_cross_category",
        True,
        {
            "source": "חדשות 12",
            "category": "חדשות",
            "headline": "18 דיירים חולצו משריפה בבניין בלוד",
            "originalTitle": "18 דיירים חולצו משריפה בבניין מגורים בלוד",
            "context": "צוותי כבאות חילצו 18 דיירים מבניין מגורים בלוד לאחר שפרצה בו שריפה.",
            "sourceUrl": "https://www.mako.co.il/news-example-lod-fire",
        },
        {
            "source": "מעריב - חדשות",
            "category": "פלילים",
            "headline": "שריפה בבניין בלוד הסתיימה בחילוץ דיירים",
            "originalTitle": "שריפה פרצה בבניין מגורים בלוד; דיירים חולצו מהמקום",
            "context": "כוחות הכיבוי פינו דיירים מבניין בלוד בעקבות שריפה שפרצה במקום.",
            "sourceUrl": "https://www.maariv.co.il/news/israel/example-lod-fire",
        },
    ),
    (
        "kiryat_shmona_rocket_cross_source",
        True,
        {
            "source": "וואלה חדשות",
            "category": "ביטחון",
            "headline": "רקטה פגעה במרכז קריית שמונה וגרמה נזק כבד לעסקים",
            "originalTitle": "לילה לא שקט בצפון: פגיעה ישירה בקריית שמונה - נזק כבד לעסקים, אין נפגעים",
            "context": "במהלך הלילה נורו עשרה שיגורים מלבנון לעבר קריית שמונה והגליל העליון, ותשעה מהם יורטו.",
            "sourceUrl": "https://news.walla.co.il/item/example-k8",
        },
        {
            "source": "הארץ - חדשות",
            "category": "ביטחון",
            "headline": "רקטה נפלה במרכז קריית שמונה אחרי מטח מלבנון",
            "originalTitle": "ירי בלתי פוסק לעבר הצפון: רקטה נפלה בקריית שמונה",
            "context": "רקטה ששוגרה מלבנון נפלה בקריית שמונה וגרמה נזק לחנויות ולעסקים, ללא נפגעים.",
            "sourceUrl": "https://www.haaretz.co.il/example-k8",
        },
    ),
    (
        "yirka_samer_halabi_murder_cross_source",
        True,
        {
            "source": "ynet - מבזקי החדשות",
            "category": "פלילים",
            "headline": "סאמר חלבי בן ה־24 נרצח בירכא במהלך חגיגת יום הולדת",
            "originalTitle": "הנרצח בירכא: תושב היישוב סאמר חלבי",
            "context": "סאמר חלבי, בן 24 מירכא, נורה למוות במהלך חגיגת יום הולדת ביישוב.",
            "sourceUrl": "https://www.ynet.co.il/news/article/example-yirka",
        },
        {
            "source": "וואלה חדשות - מבזקים",
            "category": "פלילים",
            "headline": "בן 24 נרצח בירכא והירי נשאר ללא חשודים",
            "originalTitle": "בן 24 נורה למוות בירכא; המשטרה פתחה בחקירה",
            "context": "גבר בן 24 מירכא נורה למוות, והמשטרה טרם איתרה חשודים בירי.",
            "sourceUrl": "https://news.walla.co.il/break/example-yirka",
        },
    ),
    (
        "iran_hardliners_against_us_deal_cross_source",
        True,
        {
            "source": "ynet - כל ערוץ החדשות",
            "category": "ביטחון",
            "headline": "הקיצונים באיראן לוחצים על חמינאי לבלום הסכם עם ארה״ב",
            "originalTitle": "עצרות המונים ומכתב מתריס למנהיג העליון: הקיצונים באיראן שפועלים נגד ההסכם",
            "context": "פלג קיצוני בהנהגה האיראנית מפעיל לחץ על חמינאי נגד הסכם עם ארה״ב, כולל עצרות ומכתב שמאשים את צוות המשא ומתן בפיוס יתר.",
            "sourceUrl": "https://www.ynet.co.il/news/article/example-iran-hardliners",
        },
        {
            "source": "N12 - בעולם",
            "category": "ביטחון",
            "headline": "המחנה הקיצוני באיראן לוחץ נגד הסכם עם ארה״ב",
            "originalTitle": "המאבק בתוך איראן נגד ההסכם: טראמפ חייב לדעת, טהראן קובעת את התנאים",
            "context": "גורמים במחנה הקיצוני בטהראן דורשים להקשיח תנאים מול טראמפ ולמנוע פשרה מהירה במשא ומתן עם ארה״ב.",
            "sourceUrl": "https://www.mako.co.il/news-world/example-iran-hardliners",
        },
    ),
    (
        "different_weather_city_forecast",
        False,
        {
            "source": "השירות המטאורולוגי",
            "category": "מזג אוויר",
            "headline": "מזג האוויר בירושלים: 12°–20°; עננות חלקית",
            "context": "בירושלים צפויה עננות חלקית וקרינה גבוהה בצהריים.",
            "sourceUrl": "https://ims.gov.il/jerusalem",
        },
        {
            "source": "וואלה חדשות",
            "category": "חדשות",
            "headline": "גשם ורוחות ילוו את ערב שבועות בצפון ובמרכז",
            "context": "בערב החג צפויים גשם ורוחות בצפון ובמרכז.",
            "sourceUrl": "https://news.walla.co.il/item/3839781",
        },
    ),
]


def main() -> int:
    failures = []
    for name, expected, a, b in CASES:
        got = likely_duplicate_story(a, b)
        if got != expected:
            failures.append(f"{name}: expected {expected}, got {got}")
    if failures:
        print("Semantic duplicate drill failed:")
        for failure in failures:
            print("-", failure)
        return 1

    older_detailed = {
        "source": "מקור א",
        "publishedAt": "2026-05-26T06:00:00+03:00",
        "headline": "ארה״ב תקפה בדרום איראן",
        "context": "פירוט ארוך מאוד על התקיפה, השיחות, הורמוז ובנדר עבאס " * 5,
        "takeaway": "טייקאוויי מפורט",
        "sourceUrl": "https://example.com/older",
    }
    newer_shorter = {
        "source": "מקור ב",
        "publishedAt": "2026-05-26T07:00:00+03:00",
        "headline": "ארה״ב תקפה באיראן",
        "context": "עדכון קצר אך מאוחר יותר",
        "takeaway": "",
        "sourceUrl": "https://example.com/newer",
    }
    preferred = update_feed.preferred_duplicate_item(older_detailed, newer_shorter)
    if preferred is not newer_shorter:
        print("Semantic duplicate drill failed:")
        print("- preferred_duplicate_item: expected freshest duplicate to win over older detailed card")
        return 1

    print(f"Semantic duplicate drill passed: {len(CASES)}/{len(CASES)} + freshest-preferred")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
