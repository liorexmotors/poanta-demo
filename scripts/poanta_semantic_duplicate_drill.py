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


CASES = [
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
    print(f"Semantic duplicate drill passed: {len(CASES)}/{len(CASES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
