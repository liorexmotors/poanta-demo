#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression drill for Poanta visible/personal-feed semantic dedupe.

The law this protects: after user personalization/preferences and the active top
filter are applied, the rendered feed may show only one visible card from the
same semantic story cluster. This is separate from raw/global feed dedupe.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pointa_live_auditor import likely_duplicate_story  # noqa: E402


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def topic_for(item: dict) -> str:
    category = str(item.get("category") or "חדשות")
    if category == "תחבורה":
        return "רכב"
    if category == "חדשות":
        return "פוליטיקה"
    if category == "עולם":
        return "אקטואליה בעולם"
    return category


def semantic_text(item: dict) -> str:
    return " ".join(str(item.get(k) or "") for k in ["headline", "context", "takeaway", "originalTitle", "source"]).lower()


def has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def semantic_story_key(item: dict) -> str:
    text = semantic_text(item)
    has_iran = has_any(text, ["איראן", "איראני", "iran", "iranian", "tehran"])
    has_us = has_any(text, ["ארה״ב", "ארה\"ב", "אמריק", "u.s.", "u.s", "us ", " us ", "united states", "american"])
    has_strike = has_any(text, ["תקיפ", "תקפה", "תקיפות", "הפצצ", "strikes", "strike", "attacks", "launches strikes", "carries out"])
    has_south = has_any(text, ["דרום איראן", "בדרום איראן", "southern iran", "south iran"])
    has_context = has_any(text, ["missile sites", "missile", "טילים", "סירות", "boats", "self-defence", "self defense", "הגנה עצמית", "qatar", "קטאר", "שיחות", "talks"])
    has_market = has_any(text, ["נפט", "ברנט", "שווקים", "מחיר הנפט", "מחירי הנפט", "גז", "זרימת נפט", "oil", "brent", "markets", "market impact", "energy prices"])
    if has_market:
        return ""
    if has_iran and has_us and has_strike and (has_south or has_context):
        return "event:us-strikes-iran-20260526"
    has_actor = has_us or has_any(text, ["טראמפ", "trump", "וושינגטון", "white house"])
    has_deal = has_any(text, ["הסכם", "עסקה", "מו״מ", "מו\"מ", "מגעים", "הבנות", "גרעין", "deal", "agreement", "talks", "negotiation"])
    has_decision_delay = has_any(text, ["דחה", "לא החליט", "בלי החלטה", "ללא הכרעה", "לא קיבל החלטה", "בלי מסר ברור", "הסתיימה פגישת", "סיימו דיון", "חדר המצב", "הכרעה", "אישור", "קרובים להבנות", "מחלוקות", "כספים מוקפאים", "שחרור הכספים", "אורניום מועשר", "הורמוז"])
    is_sanctions = has_any(text, ["סנקציות", "רשת רכש", "ציוד סייבר", "הטיל סנקציות", "sanctions"])
    if has_iran and has_actor and has_deal and has_decision_delay and not is_sanctions:
        return "event:us-iran-deal-decision-20260530"
    has_givati = has_any(text, ["גבעתי", "סיירת גבעתי", "givati"])
    has_tyukin = has_any(text, ["טיוקין", "מיכאל טיוקין"])
    has_hezbollah_drone = has_any(text, ["רחפן", "כטב\"ם", "כטב״ם", "drone", "חיזבאללה", "hezbollah"])
    has_south_lebanon = has_any(text, ["דרום לבנון", "לבנון", "זוטר א-שרקיה", "south lebanon"])
    has_fatality = has_any(text, ["נהרג", "נפל", "חלל", "killed", "fallen"])
    if (has_givati or has_tyukin) and has_hezbollah_drone and has_south_lebanon and has_fatality:
        return "event:givati-tyukin-hezbollah-drone-20260531"
    return ""


FIXTURE = [
    {
        "source": "וואלה",
        "category": "ביטחון",
        "headline": "ארה״ב מאשרת תקיפות הגנתיות בתוך איראן",
        "originalTitle": "ארה\"ב אישרה כי כוחותיה ביצעו הלילה תקיפות \"להגנה עצמית\" בשטח איראן",
        "context": "פיקוד המרכז האמריקני אישר שכוחות ארה״ב תקפו אתרי שיגור טילים וסירות איראניות בזמן הפסקת האש.",
        "publishedAt": "2026-05-26T06:00:00+03:00",
        "sourceUrl": "https://news.walla.co.il/iran-strikes",
    },
    {
        "source": "NYT",
        "category": "ביטחון",
        "headline": "ארה״ב ביצעה תקיפות הגנה עצמית בדרום איראן",
        "originalTitle": "U.S. Carries Out Renewed Strikes in Southern Iran",
        "context": "U.S. forces struck missile sites and boats near Bandar Abbas amid talks in Qatar.",
        "publishedAt": "2026-05-26T06:08:00+03:00",
        "sourceUrl": "https://www.nytimes.com/iran-strikes",
    },
    {
        "source": "Al Jazeera",
        "category": "פוליטיקה",
        "headline": "ארה״ב תקפה בדרום איראן בזמן שהמשא ומתן עבר לדוחא",
        "originalTitle": "US military launches strikes on southern Iran amid talks in Qatar",
        "context": "התקיפות בדרום איראן פגעו באתרי טילים וסירות בזמן שיחות בדוחא על הסכם והפסקת אש.",
        "publishedAt": "2026-05-26T06:10:00+03:00",
        "sourceUrl": "https://www.aljazeera.com/iran-strikes",
    },
    {
        "source": "BBC",
        "category": "אקטואליה בעולם",
        "headline": "ארה״ב תקפה מטרות באיראן בזמן שיחות על הסכם",
        "originalTitle": "US strikes Iranian targets during Qatar talks",
        "context": "American strikes hit Iranian missile targets and boats while negotiators met in Qatar.",
        "publishedAt": "2026-05-26T06:05:00+03:00",
        "sourceUrl": "https://www.bbc.com/iran-strikes",
    },
    {
        "source": "Guardian",
        "category": "ביטחון",
        "headline": "רוביו מזהיר שאיום הורמוז יכול לשנות את קצב השיחות",
        "originalTitle": "Rubio warns Hormuz crisis could reshape Iran talks",
        "context": "הסיפור מתמקד בהשלכות הדיפלומטיות ובשיחות, לא בתקיפה עצמה.",
        "publishedAt": "2026-05-26T06:12:00+03:00",
        "sourceUrl": "https://www.theguardian.com/hormuz-talks",
    },
    {
        "source": "וואלה כסף",
        "category": "כלכלה",
        "headline": "תקיפות ארה״ב באיראן החזירו את הנפט לעליות חדות",
        "originalTitle": "מחיר הנפט מזנק בעקבות התקיפות האמריקניות",
        "context": "מחיר הברנט קפץ אחרי תקיפות אמריקאיות בדרום איראן, והשווקים חוששים מפגיעה בזרימת נפט וגז דרך הורמוז.",
        "publishedAt": "2026-05-26T06:14:00+03:00",
        "sourceUrl": "https://finance.walla.co.il/oil-iran-strikes",
    },
    {
        "source": "ynet - כל ערוץ החדשות",
        "category": "ביטחון",
        "headline": "טראמפ שוב דחה הכרעה על הסכם עם איראן",
        "originalTitle": "אופטימיות בארה\"ב, אך טראמפ שוב לא החליט: מחלוקת על שחרור הכספים המוקפאים",
        "context": "טראמפ כינס דיון בחדר המצב על הסכם מול איראן אך לא קיבל החלטה סופית. המחלוקות נוגעות בין היתר לשחרור כספים מוקפאים, לפתיחת הורמוז ולמסגרת הגרעין האיראנית.",
        "takeaway": "גם כשוושינגטון משדרת אופטימיות, הכסף האיראני והורמוז עדיין יכולים להפיל את ההסכם.",
        "publishedAt": "2026-05-30T00:57:05+03:00",
        "sourceUrl": "https://www.ynet.co.il/news/article/s1bveddxzg",
    },
    {
        "source": "וואלה חדשות - חדשות בעולם",
        "category": "ביטחון",
        "headline": "טראמפ דחה שוב הכרעה על הסכם איראן למרות התקדמות במגעים",
        "originalTitle": "הסתיימה פגישת טראמפ על סוגיית ההסכם עם איראן - ללא הכרעה",
        "context": "טראמפ סיים דיון בחדר המצב בלי החלטה סופית על הסכם עם איראן, אף שבממשל מעריכים שהצדדים קרובים להבנות. המחלוקות שנותרו נוגעות לכספים מוקפאים, מצרי הורמוז והאורניום המועשר.",
        "takeaway": "ההכרעה על ההסכם האיראני תלויה עכשיו בעיקר בטראמפ, לא בלחץ הישראלי.",
        "publishedAt": "2026-05-30T00:03:59+03:00",
        "sourceUrl": "https://news.walla.co.il/item/3841771",
    },
    {
        "source": "ישראל היום - כל הכתבות",
        "category": "ביטחון",
        "headline": "ארה״ב הטילה סנקציות על רשת רכש איראנית לטכנולוגיה צבאית",
        "originalTitle": "ברקע מתיחות השיא: המהלך החדש של וושינגטון נגד טהרן",
        "context": "משרד האוצר האמריקני הטיל סנקציות על רשת שהתחזתה לחברות אמריקניות כדי להשיג לאיראן ציוד סייבר וחומרה מתקדמת.",
        "takeaway": "וושינגטון ממשיכה ללחוץ על יכולות הרכש של איראן גם כשהמסלול הדיפלומטי עדיין פתוח.",
        "publishedAt": "2026-05-30T00:12:01+03:00",
        "sourceUrl": "https://www.israelhayom.co.il/news/world-news/usa/article/20647849",
    },
    {
        "source": "ישראל היום - כל הכתבות",
        "category": "ביטחון",
        "headline": "לוחם גבעתי מיכאל טיוקין נהרג מרחפן חיזבאללה",
        "originalTitle": "הותר לפרסום: סמ\"ר מיכאל טיוקין נפל מפגיעת רחפן נפץ בדרום לבנון",
        "context": "צה\"ל התיר לפרסום כי סמ\"ר מיכאל טיוקין, בן 21 מאשקלון ולוחם בסיירת גבעתי, נפל בדרום לבנון מפגיעת רחפן נפץ של חיזבאללה.",
        "takeaway": "האירוע מצביע על איום רחפני לילה מדויק של חיזבאללה גם מצפון לליטני.",
        "publishedAt": "2026-05-31T07:27:29+03:00",
        "sourceUrl": "https://www.israelhayom.co.il/news/defense/article/20652116",
    },
    {
        "source": "וואלה חדשות - צבא וביטחון",
        "category": "ביטחון",
        "headline": "לוחם גבעתי נהרג מפגיעת רחפן חיזבאללה בדרום לבנון",
        "originalTitle": "הותר לפרסום: סמ\"ר מיכאל טיוקין מסיירת גבעתי נפל בדרום לבנון",
        "context": "רחפן נפץ של חיזבאללה פגע בכוח סיירת גבעתי בדרום לבנון והרג את סמ״ר מיכאל טיוקין מאשקלון; ארבעה לוחמים נוספים נפצעו קל.",
        "takeaway": "איום הרחפנים של חיזבאללה ממשיך לגבות מחיר גם אחרי הפסקת האש.",
        "publishedAt": "2026-05-31T08:43:23+03:00",
        "sourceUrl": "https://news.walla.co.il/item/3841922",
    },
]


def visible_personalized(items: list[dict], *, active_filter: str = "all", selected_topics: set[str] | None = None) -> list[dict]:
    selected_topics = selected_topics or {"ביטחון", "פוליטיקה", "אקטואליה בעולם"}
    rows = [item for item in items if topic_for(item) in selected_topics]
    if active_filter != "all":
        rows = [item for item in rows if topic_for(item) == active_filter]
    rows.sort(key=lambda item: dt(item["publishedAt"]), reverse=True)
    seen: set[str] = set()
    out: list[dict] = []
    for item in rows:
        key = semantic_story_key(item)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(item)
    return out


def main() -> int:
    failures: list[str] = []
    strike_items = FIXTURE[:4]
    pairs = [(a, b) for i, a in enumerate(strike_items) for b in strike_items[i + 1 :]]
    if not all(likely_duplicate_story(a, b) for a, b in pairs):
        failures.append("live auditor did not flag all cross-source/cross-category Iran strike variants")
    if likely_duplicate_story(FIXTURE[1], FIXTURE[4]):
        failures.append("live auditor collapsed adjacent Hormuz diplomacy story into strike story")
    if likely_duplicate_story(FIXTURE[1], FIXTURE[5]) or semantic_story_key(FIXTURE[5]):
        failures.append("market/oil-impact card was incorrectly collapsed into the operational strike story")
    deal_ynet, deal_walla, sanctions = FIXTURE[6], FIXTURE[7], FIXTURE[8]
    if not likely_duplicate_story(deal_ynet, deal_walla):
        failures.append("live auditor did not flag the cross-source Trump/Iran deal-decision duplicate")
    if likely_duplicate_story(deal_ynet, sanctions):
        failures.append("Iran sanctions story was incorrectly collapsed into the Trump/Iran deal-decision duplicate")

    all_visible = visible_personalized(FIXTURE, active_filter="all", selected_topics={"ביטחון", "פוליטיקה", "אקטואליה בעולם", "כלכלה"})
    strike_visible = [item for item in all_visible if semantic_story_key(item) == "event:us-strikes-iran-20260526"]
    if len(strike_visible) != 1:
        failures.append(f"personal all-feed expected 1 visible strike card, got {len(strike_visible)}")
    if strike_visible and strike_visible[0]["source"] != "Al Jazeera":
        failures.append(f"personal all-feed did not keep freshest strike card: {strike_visible[0]['source']}")
    deal_visible = [item for item in all_visible if "טראמפ" in item.get("headline", "") and "איראן" in item.get("headline", "")]
    if len(deal_visible) != 1:
        failures.append(f"personal all-feed expected 1 visible Trump/Iran deal-decision card, got {len(deal_visible)}")
    if deal_visible and deal_visible[0]["source"] != "ynet - כל ערוץ החדשות":
        failures.append(f"personal all-feed did not keep freshest Trump/Iran deal-decision card: {deal_visible[0]['source']}")
    if not any("סנקציות" in item["headline"] for item in all_visible):
        failures.append("distinct Iran sanctions story was incorrectly removed")
    givati_visible = [item for item in all_visible if semantic_story_key(item) == "event:givati-tyukin-hezbollah-drone-20260531"]
    if len(givati_visible) != 1:
        failures.append(f"personal all-feed expected 1 visible Givati/Tyukin Hezbollah-drone card, got {len(givati_visible)}")
    if givati_visible and givati_visible[0]["source"] != "וואלה חדשות - צבא וביטחון":
        failures.append(f"personal all-feed did not keep freshest Givati/Tyukin card: {givati_visible[0]['source']}")

    security_visible = visible_personalized(FIXTURE, active_filter="ביטחון")
    security_strikes = [item for item in security_visible if semantic_story_key(item) == "event:us-strikes-iran-20260526"]
    if len(security_strikes) != 1:
        failures.append(f"active ביטחון tab expected 1 visible strike card after tab filter, got {len(security_strikes)}")
    if not any("הורמוז" in item["headline"] for item in security_visible):
        failures.append("distinct adjacent Hormuz story was incorrectly removed")

    app_index = ROOT / "app" / "index.html"
    index_path = app_index if app_index.exists() else ROOT / "index.html"
    index = index_path.read_text(encoding="utf-8")
    returns_deduped_rows = (
        "return dedupeVisibleItems(rows);" in index
        or "return dedupeVisibleItems(rows.map(row=>row.item));" in index
    )
    if "const applyActive=options.applyActiveFilter!==false" not in index or not returns_deduped_rows:
        failures.append("index.html selector must apply active filter before dedupeVisibleItems and return deduped rows")
    if not re.search(r"POANTA_FEED_VERSION\s*=\s*'[^']*dedupe-v3'", index):
        failures.append("POANTA_FEED_VERSION was not bumped for personal dedupe v3")

    if failures:
        print("Personal-feed semantic dedupe drill failed:")
        for failure in failures:
            print("-", failure)
        return 1
    print("Personal-feed semantic dedupe drill passed: source variants collapse to one, including Givati/Tyukin Hezbollah-drone cluster; active tab stays lawful, adjacent story remains")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
