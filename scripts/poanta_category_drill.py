#!/usr/bin/env python3
"""Regression drill for deterministic Poanta category boundaries."""
from __future__ import annotations

import update_feed


CASES = [
    {
        "name": "ynet_weather_forecast_not_politics",
        "title": "תחזית מזג אוויר: ללא שינוי ניכר בטמפרטורות",
        "desc": "היום יהיה מעונן חלקית עד בהיר, והטמפרטורות יישארו סביב הממוצע לסוף מאי. בירושלים צפויות 12–25 מעלות, בתל אביב 19–25 ובאילת 22–32.",
        "source": "ynet - מבזקי החדשות",
        "expected": ("מזג אוויר", "real"),
    },
    {
        "name": "political_story_stays_politics",
        "title": "הכנסת אישרה בקריאה ראשונה שינוי בתקציב הממשלה",
        "desc": "הקואליציה והאופוזיציה התעמתו סביב ההצעה לפני ההצבעה.",
        "source": "ynet - פוליטי מדיני",
        "expected": ("פוליטיקה", "security"),
    },
]


def main() -> int:
    failures: list[str] = []
    for case in CASES:
        got = update_feed.categorize_item(case["title"], case["desc"], case["source"])
        if got != case["expected"]:
            failures.append(f"{case['name']}: expected {case['expected']!r}, got {got!r}")
    if failures:
        print("Category drill failed:")
        for failure in failures:
            print("-", failure)
        return 1
    print(f"Category drill passed: {len(CASES)}/{len(CASES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
