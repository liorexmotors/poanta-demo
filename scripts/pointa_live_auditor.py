#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Continuous live auditor for Poanta/Pointa.

This is "המבקר": it checks the actual public feed on a fixed schedule,
independently of whether a publish just happened. That way it catches both bad
publishes and missing/stuck publishes. It is intentionally conservative:
warnings are useful; failures mean the feed should be reviewed or fixed before
the next automatic publish cycle keeps reinforcing the issue.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

try:
    from pointa_quality_gate import validate_item  # type: ignore
except Exception:  # pragma: no cover
    validate_item = None

# Public feed is served from Cloudflare Pages. The old GitHub Pages project-path
# URL 404s after the custom-domain/Cloudflare migration, so it must not be the
# default source of truth for public health checks.
LIVE_FEED_URL = "https://poanta-demo.pages.dev/feed.json"
RAW_GHPAGES_URL = "https://raw.githubusercontent.com/liorexmotors/poanta-demo/gh-pages/feed.json"
TZ = timezone(timedelta(hours=3))

BAD_HEADLINE_FRAGMENTS = [
    "בריאיון שקיים",
    "הכתבה עוסקת",
    "הכתב מתאר",
    "פורסם כי",
    "דווח כי",
    "נטען ש",
    "גורם איראני:",
    "גורמים בארה״ב:",
    "גורמים אמריקנים:",
    "מקור ב",
]
GENERIC_TAKEAWAY_FRAGMENTS = [
    "אי־ודאות ביטחונית שוחקת את הציבור",
    "ההשפעה המעשית",
    "זו אזהרת היערכות",
    "כדאי לעקוב",
    "האירוע מדגיש",
    "הסיפור מדגים",
    "הסיפור מציג",
]

FOREIGN_SOURCE_NAMES = {
    "bbc",
    "cnn",
    "sky news",
    "reuters",
    "ap",
    "associated press",
    "guardian",
    "nyt",
    "new york times",
    "axios",
    "politico",
    "bloomberg",
    "al jazeera",
}

IMPORTANT_SOURCE_MAX_AGE_MIN = {
    "הארץ": 120,
    "ynet": 90,
    "וואלה": 90,
    "מעריב": 120,
    "גלובס": 180,
    "ישראל היום": 180,
    "דה מרקר": 240,
}

DUPLICATE_STOPWORDS = set(
    "של על את עם זה זו הוא היא הם הן כי אשר אבל או אם גם יותר פחות לתוך מתוך "
    "אחרי לפני כדי כמו בין לפי ללא מול תחת מעל כל כבר עוד אותו אותה אותם אותן "
    "יש אין היה היתה היו יהיה תהיה להיות מה למה איך מי לא כן "
    "in the a an and or of to for with on at from by is are was were be as that this"
    .split()
)


@dataclass
class Finding:
    severity: str  # error|warning
    code: str
    message: str
    item: int | None = None
    headline: str = ""
    source: str = ""
    url: str = ""


def fetch_json(url: str) -> dict[str, Any]:
    req = Request(
        url + ("&" if "?" in url else "?") + f"auditor={int(datetime.now().timestamp() * 1000)}",
        headers={
            "User-Agent": "PointaLiveAuditor/1.0",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def read_feed_file(path: str) -> dict[str, Any]:
    """Read a local/candidate feed for pre-publish outcome checks."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_dt(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=TZ)
        return d.astimezone(TZ)
    except Exception:
        return None


def norm_words(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z0-9\u0590-\u05ff]+", (text or "").lower())
    return {w for w in words if len(w) > 2}


def too_close(a: str, b: str) -> bool:
    aw = norm_words(a)
    bw = norm_words(b)
    if not aw or not bw:
        return False
    return len(aw & bw) / max(1, min(len(aw), len(bw))) >= 0.72


def duplicate_words(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z0-9\u0590-\u05ff]+", (text or "").lower().replace("׳", "").replace("\"", ""))
    return {w for w in words if len(w) > 2 and w not in DUPLICATE_STOPWORDS}


def story_words(item: dict[str, Any]) -> set[str]:
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context"])
    return set(list(duplicate_words(text))[:48])


def weather_event_tokens(item: dict[str, Any]) -> set[str]:
    """Semantic duplicate key for weather cards.

    Weather articles from different Israeli sources often use very different
    headlines for the same small forecast event (for example ערב שבועות +
    rain + winds + north/center). Plain word overlap is too weak because one
    source may say ``גשם מקומי`` and another ``גשמים`` or ``שינוי במזג האוויר``.
    Return a compact event fingerprint only when enough forecast-specific
    anchors exist; otherwise return an empty set so generic weather mentions do
    not collapse unrelated cards.
    """
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context", "takeaway", "category"]).lower()
    tokens: set[str] = set()
    if re.search(r"גשם|גשמים|טפטופ|מטר", text):
        tokens.add("rain")
    if re.search(r"רוח|רוחות|סוער|ערות", text):
        tokens.add("wind")
    if re.search(r"שבועות|ערב החג|חג השבועות", text):
        tokens.add("shavuot")
    if re.search(r"צפון|בצפון", text):
        tokens.add("north")
    if re.search(r"מרכז|במרכז|חוף|שפלה", text):
        tokens.add("center")
    if re.search(r"ירידה|נמוכות|קריר|חורפי|קור", text):
        tokens.add("cool")
    # A weather duplicate needs the meteorological phenomenon plus either the
    # same date/occasion or the same affected area. This catches the Shavuot
    # rain/wind duplicate without merging unrelated daily city forecasts.
    if {"rain", "wind"}.issubset(tokens) and ("shavuot" in tokens or len(tokens & {"north", "center"}) >= 2):
        return tokens
    return set()


def knesset_dissolution_tokens(item: dict[str, Any]) -> set[str]:
    """Fingerprint the same Knesset dissolution/election-advance vote story."""
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context", "takeaway", "category"]).lower()
    has_knesset = bool(re.search(r"כנסת|knesset", text))
    has_dissolution = bool(re.search(r"פיזור|פיזורה|לפזר|dissolv|election|בחירות", text))
    has_vote_stage = bool(re.search(r"קריאה ראשונה|first reading|106|ללא מתנגדים|בלי מתנגדים|הצעת חוק", text))
    if has_knesset and has_dissolution and has_vote_stage:
        return {"knesset_dissolution_first_reading"}
    return set()


def attorney_general_split_tokens(item: dict[str, Any]) -> set[str]:
    """Fingerprint the attorney-general role-splitting first-reading bill."""
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context", "takeaway", "category"]).lower()
    has_ag = bool(re.search(r"יועמ[״\"]?ש|יועץ משפטי|attorney[- ]?general", text))
    has_split = bool(re.search(r"פיצול|לפצל|split", text))
    has_bill_vote = bool(re.search(r"קריאה ראשונה|first reading|מליאת הכנסת|הצעת החוק|bill", text))
    if has_ag and has_split and has_bill_vote:
        return {"attorney_general_split_first_reading"}
    return set()


def local_emergency_event_tokens(item: dict[str, Any]) -> set[str]:
    """Fingerprint concrete local emergency incidents across category labels."""
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context", "takeaway", "category"]).lower()
    tokens: set[str] = set()
    if re.search(r"שריפה|אש|דליק|כבאות|חולצו|חילוץ|לכודים|דיירים", text):
        tokens.add("fire_rescue")
    if re.search(r"רצח|נרצח|נרצחה|ירי|נורה|נורתה|הרוג|נהרג|murder|killed|shot", text):
        tokens.add("violent_death")
    if re.search(r"לוד|lod", text):
        tokens.add("lod")
    if re.search(r"ירכא|yarka|yirka", text):
        tokens.add("yirka")
    if re.search(r"סאמר\s+חלבי|חלבי|samer", text):
        tokens.add("samer_halabi")
    if re.search(r"בן\s*24|בן ה[־-]?24|24", text):
        tokens.add("age_24")
    if re.search(r"בניין|מגורים|דירה|apartment", text):
        tokens.add("residential_building")
    if re.search(r"18|שמונה עשר|eighteen", text):
        tokens.add("eighteen_people")
    if "fire_rescue" in tokens and "lod" in tokens and ("residential_building" in tokens or "eighteen_people" in tokens):
        return tokens
    if "violent_death" in tokens and "yirka" in tokens and ("samer_halabi" in tokens or "age_24" in tokens):
        return tokens
    return set()


def northern_rocket_event_tokens(item: dict[str, Any]) -> set[str]:
    """Fingerprint the same northern rocket-impact event across sources."""
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context", "takeaway", "category"]).lower()
    tokens: set[str] = set()
    if re.search(r"קריית שמונה|ק\"ש|kiryat shmona", text):
        tokens.add("kiryat_shmona")
    if re.search(r"רקט|טיל|שיגור|מטח|אזעק", text):
        tokens.add("rocket_fire")
    if re.search(r"לבנון|חיזבאללה|צפון|גליל", text):
        tokens.add("north_lebanon")
    if re.search(r"פגיעה ישירה|נפלה|פגע|נזק כבד|עסקים|חנויות", text):
        tokens.add("direct_hit_damage")
    if re.search(r"כפר יובל|אצבע הגליל|גליל מערבי|ערב אל[־-]?עראמשה|ערב אל עראמשה", text):
        tokens.add("north_uav_alert_area")
    if re.search(r"מטרה אווירית|כלי טיס|כטב[״\"]?ם|רחפן|זיהוי שווא|חדירת", text):
        tokens.add("north_uav_alert")
    if "kiryat_shmona" in tokens and "rocket_fire" in tokens and ("north_lebanon" in tokens or "direct_hit_damage" in tokens):
        return tokens
    if "north_uav_alert_area" in tokens and "north_uav_alert" in tokens:
        return tokens
    return set()


def hezbollah_drone_casualty_tokens(item: dict[str, Any]) -> set[str]:
    """Fingerprint the same IDF casualty from a Hezbollah drone across sources."""
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context", "takeaway", "category"]).lower()
    tokens: set[str] = set()
    if re.search(r"מיכאל\s+טיוקין|טיוקין", text):
        tokens.add("michael_tyukin")
    if re.search(r"גבעתי|סיירת גבעתי|givati", text):
        tokens.add("givati")
    if re.search(r"רחפן|כטב[״\"]?ם|drone|uav", text):
        tokens.add("drone")
    if re.search(r"חיזבאללה|hezbollah", text):
        tokens.add("hezbollah")
    if re.search(r"דרום לבנון|לבנון|זוטר א[־-]?שרקיה|south lebanon", text):
        tokens.add("south_lebanon")
    if re.search(r"נהרג|נפל|חלל|killed|fallen", text):
        tokens.add("fatality")
    if {"drone", "hezbollah", "south_lebanon", "fatality"}.issubset(tokens) and ("michael_tyukin" in tokens or "givati" in tokens):
        return tokens
    return set()


def nuclear_facility_strike_tokens(item: dict[str, Any]) -> set[str]:
    """Fingerprint the same nuclear-facility strike/safety incident across sources."""
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context", "takeaway", "category"]).lower()
    tokens: set[str] = set()
    if re.search(r"זפוריז|zaporizh|zaporizhzhia", text):
        tokens.add("zaporizhzhia")
    if re.search(r"גרעינ|nuclear|סבא[״\"]?א|iaea|אנרגיה אטומית", text):
        tokens.add("nuclear_facility")
    if re.search(r"כטב[״\"]?ם|רחפן|drone|uav", text):
        tokens.add("drone")
    if re.search(r"טורבינה|תחנת כוח|power plant|turbine|מבנה", text):
        tokens.add("plant_structure")
    if re.search(r"פגע|פגיעה|תקיפ|חור בקיר|hit|strike|attack", text):
        tokens.add("impact")
    if {"zaporizhzhia", "nuclear_facility", "drone", "impact"}.issubset(tokens):
        return tokens
    return set()


def security_event_tokens(item: dict[str, Any]) -> set[str]:
    """Semantic duplicate key for the same security event across sources.

    This catches cross-language duplicates such as the current U.S. strikes in
    southern Iran cluster, while avoiding adjacent diplomatic-analysis cards
    that merely mention the strikes in background context.
    """
    main = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline"]).lower()
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context", "takeaway", "category"]).lower()
    is_us = bool(re.search(r"\b(?:u\.?s\.?|us|united states|america|american)\b|ארה[״\"]?ב|אמריק", main))
    is_iran = bool(re.search(r"iran|iranian|איראן|איראני|טהראן", main))
    is_strike = bool(re.search(r"strike|strikes|attack|attacks|תקיפ|תקף|תקפה|תקפו|השמיד", main))
    if not (is_us and is_iran and is_strike):
        return set()
    if re.search(r"נפט|ברנט|שווקים|מחיר הנפט|מחירי הנפט|גז|זרימת נפט|\boil\b|\bbrent\b|\bmarkets?\b|energy prices", text):
        return set()
    tokens = {"us_iran_strike"}
    if re.search(r"southern iran|south(?:ern)?|דרום|בדרום", text):
        tokens.add("south")
    if re.search(r"missile|missiles|טיל|טילים|שיגור|נ[״\"]?מ", text):
        tokens.add("missiles")
    if re.search(r"boat|boats|vessel|vessels|סיר|סירות|כלי שיט", text):
        tokens.add("boats")
    if re.search(r"mine|mines|laying|minelaying|מוקש|מוקשים", text):
        tokens.add("mines")
    if re.search(r"hormuz|הורמוז|gulf|מפרץ", text):
        tokens.add("hormuz")
    if re.search(r"ירי|אש|בסיס|מכ[״\"]?ם|מכמים|radar|base|fire", text):
        tokens.add("military_exchange")
    if re.search(r"bandar|abbas|בנדר|עבאס", text):
        tokens.add("bandar_abbas")
    if re.search(r"self[- ]?defen[cs]e|הגנה עצמית|כהגנה", text):
        tokens.add("self_defense")
    if re.search(r"doha|qatar|דוחא|קטאר", text):
        tokens.add("qatar_talks")
    return tokens if len(tokens) >= 3 else set()


def iran_deal_decision_tokens(item: dict[str, Any]) -> set[str]:
    """Semantic duplicate key for the same Trump/U.S.-Iran deal decision story.

    This catches the visible regression where two Hebrew sources publish the
    same White House meeting / no-final-decision story with different wording.
    It intentionally requires decision/delay anchors so separate sanctions,
    market, or military stories that only mention Iran talks in background are
    not collapsed.
    """
    main = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline"]).lower()
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context", "takeaway", "category"]).lower()
    has_actor = bool(re.search(r"טראמפ|trump|ארה[״\"]?ב|אמריק|וושינגטון|white house", text))
    has_iran = bool(re.search(r"איראן|איראני|טהראן|\biran\b|iranian", text))
    has_deal = bool(re.search(r"הסכם|עסקה|מו[״\"]?מ|מגעים|הבנות|גרעין|deal|agreement|talks|negotiation", text))
    has_decision_delay = bool(re.search(
        r"דחה|לא החליט|בלי החלטה|ללא הכרעה|לא קיבל החלטה|בלי מסר ברור|הסתיימה פגישת|סיימו דיון|חדר המצב|הכרעה|אישור|קרובים להבנות|מחלוקות|כספים מוקפאים|שחרור הכספים|אורניום מועשר|הורמוז|דרש|דרישות|תנאים|תנאי הגרעין|לוותר|ויתור|נשק גרעיני|פיקוח גרעיני",
        text,
    ))
    if not (has_actor and has_iran and has_deal and has_decision_delay):
        return set()
    if re.search(r"סנקציות|רשת רכש|ציוד סייבר|הטיל סנקציות|sanctions", main):
        return set()
    tokens = {"us_iran_deal_decision"}
    if re.search(r"טראמפ|trump|white house|חדר המצב", text):
        tokens.add("white_house_meeting")
    if re.search(r"כספים מוקפאים|שחרור הכספים|frozen funds", text):
        tokens.add("frozen_funds")
    if re.search(r"הורמוז|hormuz", text):
        tokens.add("hormuz")
    if re.search(r"אורניום מועשר|גרעין|גרעיני|nuclear|uranium", text):
        tokens.add("nuclear_terms")
    return tokens


def iran_hardliner_deal_tokens(item: dict[str, Any]) -> set[str]:
    """Fingerprint the same Iranian hardliners-vs-U.S.-deal story.

    Hebrew sources often split this story between the external deal frame
    (Trump/U.S. terms) and the internal Tehran power-struggle frame
    (hardliners pressuring Khamenei). The user-visible feed should show one
    card for the same live event, not one per source angle.
    """
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context", "takeaway", "category"]).lower()
    has_iran = bool(re.search(r"איראן|איראני|טהראן|חמינאי|\biran\b|iranian|khamenei", text))
    has_deal = bool(re.search(r"הסכם|עסקה|מו[״\"]?מ|משא ומתן|מגעים|גרעין|deal|agreement|talks|negotiation", text))
    has_hardliners = bool(re.search(r"קיצוני|קיצונים|קשיחים|מחנה קיצוני|פלג קיצוני|hardliner|hardliners", text))
    has_pressure = bool(re.search(r"לוחץ|לחץ|מתנגד|נגד ההסכם|לבלום|למנוע|מכתב|עצרות|קובעת את התנאים|תנאים", text))
    if not (has_iran and has_deal and has_hardliners and has_pressure):
        return set()
    tokens = {"iran_hardliners_deal"}
    if re.search(r"חמינאי|khamenei", text):
        tokens.add("khamenei")
    if re.search(r"טראמפ|trump|ארה[״\"]?ב|אמריק|וושינגטון", text):
        tokens.add("us_trump")
    if re.search(r"מכתב|עצרות", text):
        tokens.add("internal_campaign")
    if re.search(r"תנאים|קובעת את התנאים|מגבלות|נוקשות", text):
        tokens.add("terms_pressure")
    return tokens


def unetcredit_kahlon_tokens(item: dict[str, Any]) -> set[str]:
    """Fingerprint the same Moshe Kahlon / UnetCredit conviction story.

    The story can render as ``משפט`` from an Israeli business source or as
    ``כלכלה`` from an English source. User-visible dedupe must still collapse it
    because the event is the same plea/conviction/reporting-offense case.
    """
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context", "takeaway", "category"]).lower()
    has_kahlon = bool(re.search(r"כחלון|kahlon", text))
    has_unet = bool(re.search(r"יונט\s*קרדיט|unet\s*credit|unetcredit", text))
    has_legal_event = bool(re.search(r"הורשע|הרשעה|הסדר טיעון|עבירת דיווח|הסתרת מידע|convicted|plea|reporting offense", text))
    if has_kahlon and has_unet and has_legal_event:
        return {"unetcredit_kahlon_conviction"}
    return set()


def cancelled_beirut_strike_tokens(item: dict[str, Any]) -> set[str]:
    """Fingerprint the same cancelled Israeli strike in Beirut after Trump pressure."""
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context", "takeaway", "category"]).lower()
    has_beirut = bool(re.search(r"ביירות|beirut", text))
    has_cancel_or_block = bool(re.search(r"בלם|ביטל|ביטול|לעצור|עצר|cancel|cancelled|canceled|hold off", text))
    has_strike = bool(re.search(r"תקיפה|לתקוף|strike|military action", text))
    has_trump = bool(re.search(r"טראמפ|trump", text))
    has_israel = bool(re.search(r"ישראל|נתניהו|israel|netanyahu", text))
    has_hezbollah_or_lebanon = bool(re.search(r"חיזבאללה|לבנון|lebanon|hezbollah", text))
    if has_beirut and has_cancel_or_block and has_strike and has_trump and has_israel:
        tokens = {"cancelled_beirut_strike"}
        if has_hezbollah_or_lebanon:
            tokens.add("lebanon_hezbollah")
        return tokens
    return set()


def live_business_duplicate_tokens(item: dict[str, Any]) -> set[str]:
    """Fingerprint narrow business/acquisition stories that word-overlap misses."""
    text = " ".join(str(item.get(k) or "") for k in ["headline", "context", "summary", "takeaway", "originalTitle", "source", "sourceUrl", "url"]).lower()
    has_fox = bool(re.search(r"פוקס|ויזל|fox", text))
    has_noy = bool(re.search(r"נוי\s+השדה|noy\s+hasadeh", text))
    has_deal = bool(re.search(r"רכיש|קניי|כניסה|בוחן|בוחנת|acquir|purchase|deal|market", text))
    if has_fox and has_noy and has_deal:
        return {"fox_noy_hasadeh_deal"}
    return set()


def israir_slovenia_flight_tokens(item: dict[str, Any]) -> set[str]:
    """Fingerprint the same Israir Slovenia/Ljubljana landing-block diversion."""
    text = " ".join(str(item.get(k) or "") for k in ["headline", "context", "summary", "takeaway", "originalTitle", "source", "sourceUrl", "url"]).lower()
    has_israir = bool(re.search(r"ישראייר|israir", text))
    has_slovenia = bool(re.search(r"סלובניה|slovenia|לובליאנה|ljubljana", text))
    has_landing_or_diversion = bool(re.search(r"נחית|לנחות|חסמה|סירבה|הוסט|הועבר|זאגרב|zagreb|divert|landing|blocked", text))
    if has_israir and has_slovenia and has_landing_or_diversion:
        return {"israir_slovenia_landing_diversion"}
    return set()


def israel_slovenia_embassy_tokens(item: dict[str, Any]) -> set[str]:
    """Fingerprint Israel opening an embassy in Slovenia/Ljubljana after a pro-Israel government change."""
    text = " ".join(str(item.get(k) or "") for k in ["headline", "context", "summary", "takeaway", "originalTitle", "source", "sourceUrl", "url"]).lower()
    has_israel = bool(re.search(r"ישראל|israel", text))
    has_slovenia = bool(re.search(r"סלובניה|slovenia|לובליאנה|ljubljana", text))
    has_embassy = bool(re.search(r"שגריר|שגרירות|embassy|ambassador", text))
    has_government_change = bool(re.search(r"ממשלה|יאנש|janša|jansa|פרו-ישראל|ידיד(?:ת)? ישראל|אישור הקמת", text))
    has_israir_only = bool(re.search(r"ישראייר|israir|נחית|זאגרב|zagreb|divert", text)) and not has_embassy
    if has_israel and has_slovenia and has_embassy and has_government_change and not has_israir_only:
        return {"israel_slovenia_embassy_government_change"}
    return set()


def word_overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, min(len(a), len(b)))


def topic_for_item(item: dict[str, Any]) -> str:
    category = str(item.get("category") or "חדשות")
    if category == "תחבורה":
        return "רכב"
    if category == "חדשות":
        return "פוליטיקה"
    if category == "עולם":
        return "ביטחון"
    return category


def is_hebrew_source(item: dict[str, Any]) -> bool:
    if canonical_source_label(item) in FOREIGN_SOURCE_NAMES:
        return False
    source = str(item.get("source") or item.get("sourceLogo") or "")
    return bool(re.search(r"[\u0590-\u05ff]", source))


def detail_score(item: dict[str, Any]) -> int:
    return len(" ".join(str(item.get(k) or "") for k in ["context", "takeaway", "originalTitle", "headline"])) + (24 if item.get("imageUrl") else 0)


def preferred_duplicate_item(a: tuple[int, dict[str, Any]], b: tuple[int, dict[str, Any]]) -> tuple[int, dict[str, Any]]:
    _, ai = a
    _, bi = b
    # User-visible duplicate law: keep the freshest card first. Source language,
    # detail, and image are only tie-breakers after recency.
    adt = parse_dt(str(ai.get("publishedAt") or "")) or datetime.min.replace(tzinfo=TZ)
    bdt = parse_dt(str(bi.get("publishedAt") or "")) or datetime.min.replace(tzinfo=TZ)
    if adt != bdt:
        return a if adt >= bdt else b
    ah, bh = is_hebrew_source(ai), is_hebrew_source(bi)
    if ah != bh:
        return a if ah else b
    ad, bd = detail_score(ai), detail_score(bi)
    if abs(ad - bd) > 20:
        return a if ad > bd else b
    return a if adt >= bdt else b


def live_regression_duplicate_tokens(item: dict[str, Any]) -> set[str]:
    primary = " ".join(str(item.get(k) or "") for k in ["headline", "originalTitle", "sourceUrl", "url"]).lower()
    text = " ".join(str(item.get(k) or "") for k in ["headline", "context", "summary", "takeaway", "originalTitle", "source", "sourceUrl", "url"]).lower()
    tokens: set[str] = set()
    # Require the tanker itself to be the primary story, not merely background
    # context for adjacent Kuwait/Bahrain air-defense alerts in the same crisis.
    if ("מכלית" in primary or "מיכלית" in primary or "tanker" in primary) and ("איראן" in text or "iran" in text) and (
        "נפט" in text
        or "oil" in text
        or "הלפייר" in text
        or "hellfire" in text
        or "טיל" in text
        or "missile" in text
        or "fired" in text
        or "שיתקה" in text
        or "השביתה" in text
        or "ניטרלה" in text
        or "נטרלה" in text
    ):
        tokens.add("us_iran_tanker_hellfire")
    if ("13 מיליארד" in text or "13b" in text or "nis 13" in text) and (
        "צפון" in text or "north" in text
    ) and ("מיגון" in text or "שיקום" in text or "shelters" in text or "infrastructure" in text):
        tokens.add("north_reconstruction_13b")
    if (
        ("צה״ל" in text or "צה\"ל" in text or "idf" in text)
        and ("פינוי" in text or "להתפנות" in text or "evacuat" in text)
        and ("דרום לבנון" in text or "south lebanon" in text)
        and ("כפר" in text or "villag" in text or "צידון" in text or "צור" in text or "sidon" in text or "tyre" in text)
    ):
        tokens.add("idf_south_lebanon_village_evacuation")
    if (
        ("נתניהו" in text or "netanyahu" in text)
        and ("חיזבאללה" in text or "hezbollah" in text)
        and ("רחפן" in text or "רחפנ" in text or "כטב" in text or "drone" in text)
        and ("פתרון" in text or "מערכת" in text or "solution" in text or "system" in text)
        and ("קרוב" in text or "ימים הקרובים" in text or "soon" in text or "coming days" in text)
        and ("צפון" in text or "north" in text)
    ):
        tokens.add("netanyahu_hezbollah_drone_solution_north")
    if (
        ("הרמטכ" in text or "chief of staff" in text or "idf chief" in text or "צה״ל" in text or "צה\"ל" in text)
        and ("צפון" in text or "גבול הצפון" in text or "ראשי רשויות" in text or "north" in text)
        and ("חיזבאללה" in text or "hezbollah" in text)
        and ("אין הכלה" in text or "ללא הכלה" in text or "נפעל בהתקפיות" in text or "התקפית" in text or "פרוס" in text or "לרכז כאן את המאמץ" in text or "containment" in text)
    ):
        tokens.add("idf_chief_north_hezbollah_posture")
    has_ceasefire_frame = (
        "הפסקת אש" in primary
        or "ceasefire" in primary
        or (
            ("הסכם" in primary or "agreement" in primary or "מאוחדות" in primary)
            and ("הפסקת אש" in text or "הפסקת האש" in text or "ceasefire" in text)
        )
    )
    if (
        ("ישראל" in text or "israel" in text)
        and ("לבנון" in text or "lebanon" in text)
        and ("חיזבאללה" in text or "hezbollah" in text)
        and has_ceasefire_frame
        and ("ליטני" in text or "litani" in text or "נסיג" in text or "הרחק" in text or "יורחק" in text or "פריסת" in text or "אזורי פיילוט" in text)
        and not re.search(r"מחסן נשק|weapon storage|booby|raid|raids|פשט|פשיטה", primary)
    ):
        tokens.add("israel_lebanon_hezbollah_ceasefire_litani")
    if (
        ("ישראל" in text or "israel" in text)
        and ("לבנון" in text or "lebanon" in text)
        and ("חיזבאללה" in text or "hezbollah" in text)
        and has_ceasefire_frame
        and (
            "דחה" in text
            or "דחיית" in text
            or "rejected" in text
            or "rejects" in text
            or "renew" in text
            or "hold" in text
            or "החזיק" in text
            or "תלויה בעצירה" in text
            or "עצירה מלאה" in text
        )
        and not re.search(r"מחסן נשק|weapon storage|booby|raid|raids|פשט|פשיטה", primary)
    ):
        tokens.add("israel_lebanon_hezbollah_ceasefire_rejection")
    if (
        ("צה״ל" in text or "צה\"ל" in text or "idf" in text)
        and ("שב״כ" in text or "שב\"כ" in text or "shin bet" in text)
        and ("חמאס" in text or "hamas" in text)
        and ("מנגנון" in text or "apparatus" in text)
        and ("אבטח" in text or "security" in text)
        and ("חוסל" in text or "חיסלו" in text or "kill" in text)
    ):
        tokens.add("idf_shinbet_hamas_security_apparatus_killings")
    if (
        ("גולני" in text or "golani" in text)
        and ("מח״ט" in text or "מח\"ט" in text or "brigade commander" in text)
        and ("יוצא" in text or "outgoing" in text or "סיכם" in text or "מסכם" in text)
        and ("רחפן" in text or "רחפנ" in text or "132" in text or "נופלים" in text or "fallen" in text or "drones" in text)
    ):
        tokens.add("outgoing_golani_commander_war_summary")
    if ("איראן" in text or "iran" in text) and ("ארה״ב" in text or "ארה\"ב" in text or "us " in text or "u.s" in text or "american" in text) and (
        "הורמוז" in text or "hormuz" in text or "מפרץ" in text or "gulf" in text
    ) and (
        "כווית" in text or "בחריין" in text or "kuwait" in text or "bahrain" in text
    ) and (
        "מכלית" in text or "tanker" in text or "קשם" in text or "qeshm" in text or "תחנת שליטה" in text or "self-defense" in text
    ):
        tokens.add("us_iran_gulf_exchange_kuwait_bahrain")
    if (
        ("טראמפ" in text or "trump" in text)
        and ("איראן" in text or "iran" in text)
        and ("אורניום" in text or "uranium" in text)
        and ("מבצע" in text or "operation" in text)
        and ("להוציא" in text or "הוצאת" in text or "להוצאת" in text or "remove" in text or "removal" in text)
        and ("קרקע" in text or "חיילים" in text or "שטח" in text or "ground" in text or "troops" in text)
    ):
        tokens.add("trump_iran_uranium_ground_operation")
    return tokens


def gulf_air_defense_only(item: dict[str, Any]) -> bool:
    """True for Gulf air-defense/missile alerts adjacent to, but not the same as, the tanker story."""
    text = " ".join(str(item.get(k) or "") for k in ["headline", "context", "summary", "takeaway", "originalTitle", "source"]).lower()
    has_gulf_state = bool(re.search(r"כווית|בחריין|kuwait|bahrain", text))
    has_air_defense = bool(re.search(r"הגנה אווירית|מערכות ההגנה|יירוט|טילים|כטב|missiles?|drones?|air defense", text))
    has_tanker = bool(re.search(r"מכלית|מיכלית|tanker|lexie|הלפייר|hellfire", text))
    return has_gulf_state and has_air_defense and not has_tanker


def likely_duplicate_story(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if str(a.get("sourceUrl") or "") == str(b.get("sourceUrl") or ""):
        return False
    if str(a.get("source") or "") == str(b.get("source") or ""):
        return False
    aw = live_regression_duplicate_tokens(a)
    bw = live_regression_duplicate_tokens(b)
    if ("us_iran_tanker_hellfire" in aw and gulf_air_defense_only(b)) or (
        "us_iran_tanker_hellfire" in bw and gulf_air_defense_only(a)
    ):
        return False
    if aw and bw and aw & bw:
        return True
    aw = weather_event_tokens(a)
    bw = weather_event_tokens(b)
    if aw and bw and len(aw & bw) / max(1, min(len(aw), len(bw))) >= 0.75:
        return True
    aw = knesset_dissolution_tokens(a)
    bw = knesset_dissolution_tokens(b)
    if aw and bw and "knesset_dissolution_first_reading" in aw and "knesset_dissolution_first_reading" in bw:
        return True
    aw = attorney_general_split_tokens(a)
    bw = attorney_general_split_tokens(b)
    if aw and bw and "attorney_general_split_first_reading" in aw and "attorney_general_split_first_reading" in bw:
        return True
    aw = local_emergency_event_tokens(a)
    bw = local_emergency_event_tokens(b)
    if aw and bw and len(aw & bw) / max(1, min(len(aw), len(bw))) >= 0.75:
        return True
    aw = northern_rocket_event_tokens(a)
    bw = northern_rocket_event_tokens(b)
    if aw and bw and len(aw & bw) / max(1, min(len(aw), len(bw))) >= 0.75:
        return True
    aw = hezbollah_drone_casualty_tokens(a)
    bw = hezbollah_drone_casualty_tokens(b)
    if aw and bw and len(aw & bw) / max(1, min(len(aw), len(bw))) >= 0.75:
        return True
    aw = nuclear_facility_strike_tokens(a)
    bw = nuclear_facility_strike_tokens(b)
    if aw and bw and len(aw & bw) / max(1, min(len(aw), len(bw))) >= 0.75:
        return True
    aw = security_event_tokens(a)
    bw = security_event_tokens(b)
    if aw and bw and "us_iran_strike" in aw and "us_iran_strike" in bw and len((aw & bw) - {"us_iran_strike"}) >= 2:
        return True
    aw = iran_deal_decision_tokens(a)
    bw = iran_deal_decision_tokens(b)
    if aw and bw and "us_iran_deal_decision" in aw and "us_iran_deal_decision" in bw:
        # The broad Trump/U.S.-Iran negotiation frame is not enough by itself:
        # Hormuz leverage analysis and written nuclear-terms demands are adjacent
        # developments, not one visible story. Require a concrete shared sub-angle.
        if (aw & bw) - {"us_iran_deal_decision", "white_house_meeting"}:
            return True
    aw = iran_hardliner_deal_tokens(a)
    bw = iran_hardliner_deal_tokens(b)
    if aw and bw and "iran_hardliners_deal" in aw and "iran_hardliners_deal" in bw and len(aw & bw) >= 2:
        return True
    aw = unetcredit_kahlon_tokens(a)
    bw = unetcredit_kahlon_tokens(b)
    if aw and bw and "unetcredit_kahlon_conviction" in aw and "unetcredit_kahlon_conviction" in bw:
        return True
    aw = cancelled_beirut_strike_tokens(a)
    bw = cancelled_beirut_strike_tokens(b)
    if aw and bw and "cancelled_beirut_strike" in aw and "cancelled_beirut_strike" in bw:
        return True
    aw = live_business_duplicate_tokens(a)
    bw = live_business_duplicate_tokens(b)
    if aw and bw and aw & bw:
        return True
    aw = israir_slovenia_flight_tokens(a)
    bw = israir_slovenia_flight_tokens(b)
    if aw and bw and "israir_slovenia_landing_diversion" in aw and "israir_slovenia_landing_diversion" in bw:
        return True
    aw = israel_slovenia_embassy_tokens(a)
    bw = israel_slovenia_embassy_tokens(b)
    if aw and bw and "israel_slovenia_embassy_government_change" in aw and "israel_slovenia_embassy_government_change" in bw:
        return True
    if topic_for_item(a) != topic_for_item(b):
        return False
    if word_overlap(story_words(a), story_words(b)) >= 0.62:
        return True
    at = " ".join(sorted(duplicate_words(str(a.get("originalTitle") or a.get("headline") or ""))))
    bt = " ".join(sorted(duplicate_words(str(b.get("originalTitle") or b.get("headline") or ""))))
    return len(at) > 20 and len(bt) > 20 and (at in bt or bt in at)


def duplicate_story_findings(feed: dict[str, Any], scan_limit: int) -> list[Finding]:
    items = list(enumerate(feed.get("items") or []))[:scan_limit]
    findings: list[Finding] = []
    used: set[int] = set()
    for i, item in items:
        if i in used:
            continue
        cluster = [(i, item)]
        for j, other in items:
            if j <= i or j in used:
                continue
            if likely_duplicate_story(item, other):
                cluster.append((j, other))
        if len(cluster) < 2:
            continue
        keep = cluster[0]
        for candidate in cluster[1:]:
            keep = preferred_duplicate_item(keep, candidate)
        used.update(idx for idx, _ in cluster)
        dropped = [f"#{idx} {it.get('source','')} — {it.get('headline','')}" for idx, it in cluster if idx != keep[0]]
        findings.append(Finding(
            "warning",
            "duplicate_story_cluster",
            "Similar live-feed stories from different sources. Recommended keep: "
            f"#{keep[0]} {keep[1].get('source','')} — {keep[1].get('headline','')}. "
            f"Filter out: {'; '.join(dropped)}",
            keep[0],
            keep[1].get("headline", ""),
            keep[1].get("source", ""),
            keep[1].get("sourceUrl", ""),
        ))
    return findings


def quality_findings(feed: dict[str, Any], top_limit: int) -> list[Finding]:
    findings: list[Finding] = []
    if validate_item is None:
        findings.append(Finding("warning", "quality_gate_unavailable", "Could not import pointa_quality_gate.validate_item"))
        return findings
    for idx, item in enumerate(feed.get("items", [])[:top_limit]):
        issues: list[dict[str, Any]] = []
        try:
            validate_item(item, idx, issues)
        except Exception as exc:
            findings.append(Finding("error", "quality_exception", str(exc), idx, item.get("headline", ""), item.get("source", ""), item.get("sourceUrl", "")))
            continue
        for issue in issues:
            if issue.get("severity") == "error":
                findings.append(Finding(
                    "error",
                    str(issue.get("code") or "quality_error"),
                    str(issue.get("message") or "Quality Gate error"),
                    idx,
                    item.get("headline", ""),
                    item.get("source", ""),
                    item.get("sourceUrl", ""),
                ))
    return findings


def canonical_hebrew_source_label(item: dict[str, Any]) -> str:
    s_raw = str(item.get("sourceLogo") or item.get("source") or "")
    s = s_raw.lower()
    if "הארץ" in s_raw or "haaretz" in s:
        return "הארץ"
    if "דה מרקר" in s_raw or "themarker" in s:
        return "דה מרקר"
    if "ynet" in s:
        return "ynet"
    if "וואלה" in s_raw or "walla" in s:
        return "וואלה"
    if "מעריב" in s_raw or "maariv" in s:
        return "מעריב"
    if "גלובס" in s_raw or "globes" in s:
        return "גלובס"
    if "ישראל היום" in s_raw or "israel hayom" in s:
        return "ישראל היום"
    return ""


def canonical_source_label(item: dict[str, Any]) -> str:
    s = str(item.get("sourceLogo") or item.get("source") or "").lower()
    if "bbc" in s:
        return "bbc"
    if "cnn" in s:
        return "cnn"
    if "sky" in s:
        return "sky news"
    if "reuters" in s:
        return "reuters"
    if "associated press" in s or re.search(r"\bap\b", s):
        return "ap"
    if "guardian" in s:
        return "guardian"
    if "new york times" in s or "nyt" in s:
        return "nyt"
    if "axios" in s:
        return "axios"
    if "politico" in s:
        return "politico"
    if "bloomberg" in s:
        return "bloomberg"
    if "jazeera" in s:
        return "al jazeera"
    return s


def latest_matching_item(items: list[dict[str, Any]], predicate) -> tuple[int, dict[str, Any], datetime] | None:
    best: tuple[int, dict[str, Any], datetime] | None = None
    for idx, item in enumerate(items):
        d = parse_dt(str(item.get("publishedAt") or ""))
        if not d or not predicate(item):
            continue
        if best is None or d > best[2]:
            best = (idx, item, d)
    return best


def audit(feed: dict[str, Any], raw_feed: dict[str, Any] | None, *, max_update_age_min: int, max_top_age_hours: int, max_foreign_age_min: int, top_limit: int, recent_window_min: int, min_recent_items: int, min_recent_sources: int, no_new_warning_min: int, no_new_error_min: int) -> list[Finding]:
    findings: list[Finding] = []
    now = datetime.now(TZ)
    items = feed.get("items") or []
    if not isinstance(items, list) or not items:
        return [Finding("error", "empty_feed", "Live feed has no items")]

    updated = parse_dt(str(feed.get("updatedAt") or ""))
    if not updated:
        findings.append(Finding("error", "missing_updated_at", "Live feed has no valid updatedAt"))
    else:
        age = now - updated
        if age > timedelta(minutes=max_update_age_min):
            findings.append(Finding("error", "stale_updated_at", f"Live updatedAt is stale: {updated.isoformat()} ({age} old)"))

    first_dt = parse_dt(str(items[0].get("publishedAt") or ""))
    if not first_dt:
        findings.append(Finding("error", "top_missing_published_at", "Top item has no valid publishedAt", 0, items[0].get("headline", ""), items[0].get("source", ""), items[0].get("sourceUrl", "")))
    elif now.hour >= 6:
        top_age = now - first_dt
        active_news_hours = 6 <= now.hour < 23
        if active_news_hours and top_age > timedelta(minutes=no_new_error_min):
            findings.append(Finding(
                "error",
                "no_new_top_item_sla",
                f"No new top feed item for more than {no_new_error_min}m: latest is {first_dt.isoformat()} ({top_age} old). Treat as operational problem; do not lower editorial standards, trigger collection/editor/QA/deploy rescue.",
                0,
                items[0].get("headline", ""),
                items[0].get("source", ""),
                items[0].get("sourceUrl", ""),
            ))
        elif active_news_hours and top_age > timedelta(minutes=no_new_warning_min):
            findings.append(Finding(
                "warning",
                "no_new_top_item_warning",
                f"No new top feed item for more than {no_new_warning_min}m: latest is {first_dt.isoformat()} ({top_age} old). Warning only; if it reaches {no_new_error_min}m, treat as operational problem.",
                0,
                items[0].get("headline", ""),
                items[0].get("source", ""),
                items[0].get("sourceUrl", ""),
            ))
        if top_age > timedelta(hours=max_top_age_hours):
            findings.append(Finding("error", "stale_top_item", f"Top item is too old for live feed: {first_dt.isoformat()}", 0, items[0].get("headline", ""), items[0].get("source", ""), items[0].get("sourceUrl", "")))

    top = items[0]
    for source_name, max_age_min in IMPORTANT_SOURCE_MAX_AGE_MIN.items():
        latest_source = latest_matching_item(items, lambda item, source_name=source_name: canonical_hebrew_source_label(item) == source_name)
        if latest_source:
            idx, item, dt = latest_source
            source_age = now - dt
            if now.hour >= 6 and source_age > timedelta(minutes=max_age_min):
                findings.append(Finding(
                    "warning",
                    "stale_important_source_view",
                    f"Latest {source_name} item is older than {max_age_min}m: {dt.isoformat()} ({source_age} old). The overall feed may look fresh while this source view is stale. Alert only; no automatic feed change.",
                    idx,
                    item.get("headline", ""),
                    item.get("source", ""),
                    item.get("sourceUrl", ""),
                ))
        else:
            findings.append(Finding("warning", "missing_important_source_items", f"No {source_name} items found in the live feed; source view may look empty"))

    latest_foreign = latest_matching_item(items, lambda item: canonical_source_label(item) in FOREIGN_SOURCE_NAMES)
    if latest_foreign:
        idx, item, dt = latest_foreign
        foreign_age = now - dt
        if now.hour >= 6 and foreign_age > timedelta(minutes=max_foreign_age_min):
            findings.append(Finding(
                "warning",
                "stale_foreign_source_view",
                f"Latest foreign-source item is older than {max_foreign_age_min}m: {dt.isoformat()} ({foreign_age} old). Overall feed may still look fresh, but the world/source view can look stuck. Alert only; this does not block or modify the feed by itself.",
                idx,
                item.get("headline", ""),
                item.get("source", ""),
                item.get("sourceUrl", ""),
            ))
    else:
        findings.append(Finding("warning", "missing_foreign_source_items", "No foreign-source items found in the live feed; world/source view may look empty"))

    if str(top.get("category") or "") == "מזג אוויר" or "מזג" in str(top.get("headline") or ""):
        findings.append(Finding("error", "weather_on_top", "Weather is the top live item; this usually means fresh news did not publish", 0, top.get("headline", ""), top.get("source", ""), top.get("sourceUrl", "")))

    fresh_count = 0
    recent_count = 0
    recent_sources: set[str] = set()
    for item in items[:top_limit]:
        d = parse_dt(str(item.get("publishedAt") or ""))
        if d and now - d <= timedelta(hours=max_top_age_hours):
            fresh_count += 1
        if d and now - d <= timedelta(minutes=recent_window_min):
            recent_count += 1
            label = canonical_hebrew_source_label(item) or canonical_source_label(item) or str(item.get("source") or "")
            if label:
                recent_sources.add(label)
    if now.hour >= 6 and fresh_count < 3:
        findings.append(Finding("error", "too_few_fresh_top_items", f"Only {fresh_count} of top {top_limit} items are fresh within {max_top_age_hours}h"))
    if now.hour >= 6 and recent_count < min_recent_items:
        findings.append(Finding(
            "error",
            "too_few_recent_items_sla",
            f"Quantity SLA failed: only {recent_count} of top {top_limit} items are newer than {recent_window_min}m; minimum is {min_recent_items}. Quality must stay strict, but low volume must trigger rescue/source expansion.",
        ))
    if now.hour >= 6 and len(recent_sources) < min_recent_sources:
        findings.append(Finding(
            "error",
            "too_few_recent_sources_sla",
            f"Quantity SLA failed: only {len(recent_sources)} distinct recent source groups in top {top_limit} within {recent_window_min}m; minimum is {min_recent_sources}. Feed may look narrow even if items are fresh.",
        ))

    for idx, item in enumerate(items[:top_limit]):
        headline = str(item.get("headline") or "")
        original = str(item.get("originalTitle") or "")
        context = str(item.get("context") or "")
        takeaway = str(item.get("takeaway") or "")
        if any(fragment in headline for fragment in BAD_HEADLINE_FRAGMENTS):
            findings.append(Finding("error", "summary_fragment_headline", "Headline looks like a summary/source fragment, not a Pointa event headline", idx, headline, item.get("source", ""), item.get("sourceUrl", "")))
        if original and too_close(headline, original):
            findings.append(Finding("error", "headline_too_close_to_source", "Headline is too close to original source title", idx, headline, item.get("source", ""), item.get("sourceUrl", "")))
        if context and too_close(headline, context):
            findings.append(Finding("warning", "headline_duplicates_summary", "Headline is too close to the summary", idx, headline, item.get("source", ""), item.get("sourceUrl", "")))
        if any(fragment in takeaway for fragment in GENERIC_TAKEAWAY_FRAGMENTS):
            findings.append(Finding("error", "generic_takeaway_regression", "Takeaway matches a known generic/regression pattern", idx, headline, item.get("source", ""), item.get("sourceUrl", "")))

    findings.extend(quality_findings(feed, top_limit))
    findings.extend(duplicate_story_findings(feed, max(top_limit * 4, 40)))

    if raw_feed:
        if raw_feed.get("updatedAt") != feed.get("updatedAt"):
            findings.append(Finding("warning", "live_raw_mismatch", f"GitHub Pages and raw gh-pages differ: live={feed.get('updatedAt')} raw={raw_feed.get('updatedAt')}"))

    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit the public Poanta feed after publish")
    ap.add_argument("--url", default=LIVE_FEED_URL)
    ap.add_argument("--raw-url", default=RAW_GHPAGES_URL)
    ap.add_argument("--feed-file", default="", help="Audit a local/candidate feed.json instead of fetching --url")
    ap.add_argument("--raw-file", default="", help="Compare against a local raw feed file instead of --raw-url")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--max-update-age-min", type=int, default=25)
    ap.add_argument("--max-top-age-hours", type=int, default=2)
    ap.add_argument("--max-foreign-age-min", type=int, default=60)
    ap.add_argument("--recent-window-min", type=int, default=60, help="Quantity SLA window for fresh visible volume")
    ap.add_argument("--min-recent-items", type=int, default=5, help="Minimum top items newer than recent-window-min")
    ap.add_argument("--min-recent-sources", type=int, default=3, help="Minimum distinct recent source groups in the top slice")
    ap.add_argument("--no-new-warning-min", type=int, default=15, help="Warning threshold for no new top item during active news hours")
    ap.add_argument("--no-new-error-min", type=int, default=25, help="Error threshold for no new top item during active news hours")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    live = read_feed_file(args.feed_file) if args.feed_file else fetch_json(args.url)
    raw = None
    if args.raw_file:
        try:
            raw = read_feed_file(args.raw_file)
        except Exception:
            raw = None
    elif not args.feed_file:
        try:
            raw = fetch_json(args.raw_url)
        except Exception:
            raw = None
    findings = audit(live, raw, max_update_age_min=args.max_update_age_min, max_top_age_hours=args.max_top_age_hours, max_foreign_age_min=args.max_foreign_age_min, top_limit=args.top, recent_window_min=args.recent_window_min, min_recent_items=args.min_recent_items, min_recent_sources=args.min_recent_sources, no_new_warning_min=args.no_new_warning_min, no_new_error_min=args.no_new_error_min)
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    result = {
        "status": "fail" if errors else "ok",
        "checkedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "url": args.feed_file or args.url,
        "updatedAt": live.get("updatedAt"),
        "items": len(live.get("items") or []),
        "top": [
            {
                "publishedAt": item.get("publishedAt"),
                "source": item.get("source"),
                "headline": item.get("headline"),
                "takeaway": item.get("takeaway"),
                "url": item.get("sourceUrl"),
            }
            for item in (live.get("items") or [])[: args.top]
        ],
        "errors": [asdict(f) for f in errors],
        "warnings": [asdict(f) for f in warnings],
    }
    out_dir = ROOT / "tmp"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "pointa_live_auditor_last.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Pointa live auditor: {result['status']} · updatedAt={result['updatedAt']} · items={result['items']}")
        for f in errors + warnings[:8]:
            loc = f" item {f.item}" if f.item is not None else ""
            print(f"- {f.severity.upper()} {f.code}{loc}: {f.message}")
            if f.headline:
                print(f"  headline: {f.headline}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
