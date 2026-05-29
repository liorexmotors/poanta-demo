#!/usr/bin/env python3
"""Regression drill: breaking feed must collapse same-story multi-source flashes."""
from __future__ import annotations

from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
MOD_PATH = ROOT / "scripts" / "update_breaking_feed.py"
spec = importlib.util.spec_from_file_location("update_breaking_feed", MOD_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

DUPLICATE_CASES = [
    (
        'המשטרה הודיעה: לא נגיש בקשה חדשה לקבלת חומרי הגלם של ראיון פלדשטיין אצל אסנהיים',
        'המשטרה: לא נבקש מחדש את חומרי הגלם של הריאיון של פלדשטיין אצל אסנהיים',
    ),
    (
        'צה"ל: תוקפים תשתיות חיזבאללה בדרום לבנון',
        "בבקאע וברחבי דרום לבנון: צה''ל תקף לאורך הלילה יותר מ-100 תשתיות טרור ומחבלים של ארגון הטרור חיזבאללה",
    ),
    (
        'אזעקות בגליל המערבי',
        'בפעם הרביעית תוך שעתיים: אזעקות בנטועה בשל חשש לחדירת כטב"ם',
    ),
    (
        'חשד לרצח בחיפה: גופת אישה בת 50 אותרה בדירה',
        'גופת אישה בשנות החמישים אותרה בחיפה - שלושה חשודים נעצרו',
    ),
    (
        'טראמפ: אקבל כעת החלטה סופית בנוגע לעסקה עם איראן',
        'טראמפ על המו"מ עם איראן: "אקיים פגישה עכשיו - לקבל החלטה סופית"',
    ),
    (
        'ילד בן 4 נהרג בתאונת טרקטורון סמוך למושב חוסן',
        'נקבע מותו של בן ה-3 שנפצע אנוש בתאונת טרקטורון באזור מעלות תרשיחא',
    ),
    (
        'ילד בן 4 נהרג בתאונת טרקטורון סמוך למושב חוסן',
        'בן 3 נפצע אנושות בתאונת טרקטורון בשטח פתוח באזור מעלות תרשיחא',
    ),
]

DISTINCT_CASES = [
    (
        'דיווח - איראן מאיימת להגיב על תקיפת ארה"ב הלילה',
        'מחיר הנפט מזנק לאחר תקיפת ארה"ב באיראן והחשש לשיבושים במצר הורמוז',
    ),
    (
        'אזעקות בגליל המערבי בשל חשש לחדירת כטב"ם',
        'שריפה פרצה בגליל המערבי; צוותי כיבוי פועלים במקום',
    ),
    (
        'צה"ל תקף תשתיות חיזבאללה בדרום לבנון',
        'שליח ארה"ב יגיע ללבנון לשיחות על הסדרה מדינית',
    ),
]


def main() -> int:
    failures: list[str] = []
    for left, right in DUPLICATE_CASES:
        if not mod.near_duplicate(left, right):
            failures.append(f"expected duplicate: {left!r} <=> {right!r}")
    for left, right in DISTINCT_CASES:
        if mod.near_duplicate(left, right):
            failures.append(f"expected distinct: {left!r} <=> {right!r}")
    if failures:
        for failure in failures:
            print("FAIL", failure)
        return 1
    print("breaking semantic dedupe drill: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
