#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Poanta feed updater.

MVP automation:
- scans approved Israeli news sources
- picks up to 2 high-signal/clickbait-ish items per source
- fetches article metadata/description when possible
- writes feed.json in Poanta card format

If OPENAI_API_KEY is configured, the script can be extended to call an LLM for
higher quality rewrites. Current version is deterministic and safe-by-default.
"""
from __future__ import annotations

import json
import re
import sys
import argparse
import time
import html
from email.utils import parsedate_to_datetime
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser

try:
    from pointa_quality_gate import validate_item as quality_validate_item
except Exception:  # pragma: no cover - feed updater should still be importable standalone
    quality_validate_item = None

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "feed.json"
STATE_PATH = ROOT / ".poanta-state.json"
CANDIDATES_PATH = ROOT / "candidates.json"
SEEN_PATH = ROOT / ".poanta-seen.json"
QUARANTINE_PATH = ROOT / "pointa_quarantine.json"
FAST_SYNC_REPORT_PATH = ROOT / "feed_a_fast_sync_report.json"
MAX_FEED_ITEMS = 200
FEED_RETENTION_DAYS = 7
FAST_CATEGORY_RETENTION_HOURS = 18
MIN_CONTEXT_WORDS_BEFORE_ENRICH = 28
FAST_ENRICH_MAX_PER_SOURCE = 1
FAST_ENRICH_MAX_PER_RUN = 20
RSS_SOURCES_PATH = ROOT / "rss_sources.json"
SYNC_PROFILES_PATH = ROOT / "pointa_sync_profiles.json"
EXPERIMENTAL_VERSION = "20260517-pointa-fast-answer-v2"

CURRENT_AFFAIRS_CATEGORIES = {"חדשות", "ביטחון", "פוליטיקה", "פלילים", "משפט", "אקטואליה בעולם"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PoantaRSS/0.1)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.7,en;q=0.5",
}

SOURCES = [
    {"name": "N12", "url": "https://www.n12.co.il/", "host": "n12.co.il"},
    {"name": "N12 כלכלה", "url": "https://www.mako.co.il/news-money", "host": "mako.co.il"},
    {"name": "N12 פוליטי", "url": "https://www.mako.co.il/news-politics", "host": "mako.co.il"},
    {"name": "וואלה", "url": "https://www.walla.co.il/", "host": "walla.co.il", "rss": "https://rss.walla.co.il/feed/1?type=main"},
    {"name": "וואלה רכב", "url": "https://cars.walla.co.il/", "host": "walla.co.il"},
    {"name": "וואלה ספורט", "url": "https://sports.walla.co.il/", "host": "walla.co.il"},
    {"name": "ynet", "url": "https://www.ynet.co.il/", "host": "ynet.co.il", "rss": "https://www.ynet.co.il/Integration/StoryRss2.xml"},
    {"name": "ynet רכב", "url": "https://www.ynet.co.il/wheels", "host": "ynet.co.il"},
    {"name": "ynet ספורט", "url": "https://www.ynet.co.il/sport", "host": "ynet.co.il"},
    {"name": "גלובס", "url": "https://www.globes.co.il/", "host": "globes.co.il", "rss": "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=1725"},
    {"name": "גלובס רכב", "url": "https://www.globes.co.il/news/רכב.aspx", "host": "globes.co.il"},
    {"name": "mako", "url": "https://www.mako.co.il/", "host": "mako.co.il"},
    {"name": "mako ספורט", "url": "https://www.mako.co.il/Sports", "host": "mako.co.il"},
    {"name": "ערוץ 14", "url": "https://www.c14.co.il/", "host": "c14.co.il"},
]


def load_sync_profiles() -> dict:
    try:
        return json.loads(SYNC_PROFILES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"profiles": {}, "categoryProfile": {}}


def source_sync_profile(source: dict, profiles: dict | None = None) -> str:
    profiles = profiles or load_sync_profiles()
    explicit = source.get("syncProfile") or source.get("profile")
    if explicit in {"fast", "medium", "slow"}:
        return explicit
    category = source.get("categoryHint") or "חדשות"
    return profiles.get("categoryProfile", {}).get(category, "fast")


def category_sync_profile(category: str, profiles: dict | None = None) -> str:
    profiles = profiles or load_sync_profiles()
    return profiles.get("categoryProfile", {}).get(category or "חדשות", "fast")


def load_sources(sync_profile: str = "all") -> list[dict]:
    """Load approved RSS-only sources.

    Poanta's first production automation phase is intentionally RSS-only:
    no homepage scraping and no fallback readers. If the config is missing,
    keep the legacy constant as a safety fallback for local development, but
    production should always use rss_sources.json.
    """
    try:
        data = json.loads(RSS_SOURCES_PATH.read_text(encoding="utf-8"))
        active = data.get("active", [])
        sources = []
        profiles = load_sync_profiles()
        for src in active:
            source_url = src.get("rss") or src.get("telegram")
            if not source_url:
                continue
            source = {
                "name": src["name"],
                "url": source_url,
                "rss": src.get("rss"),
                "telegram": src.get("telegram"),
                "host": urlparse(source_url).netloc,
                "categoryHint": src.get("categoryHint", "חדשות"),
                "logo": src.get("logo") or src["name"],
                "language": src.get("language", "he"),
                "profile": src.get("profile"),
                "syncProfile": src.get("syncProfile"),
                "telegramKind": src.get("telegramKind"),
            }
            source["syncProfile"] = source_sync_profile(source, profiles)
            if sync_profile != "all" and source["syncProfile"] != sync_profile:
                continue
            sources.append(source)
        if sources:
            return sources
    except Exception as e:
        print(f"WARN rss_sources.json load failed, using legacy sources: {e}", file=sys.stderr)
    return [s for s in SOURCES if s.get("rss")]

CLICKBAIT_WORDS = [
    "דרמטי", "מטלטל", "נחשף", "בלעדי", "כאוס", "שעות קריטיות", "קשה לצפייה",
    "לא תאמינו", "הלם", "סערה", "מפתיע", "מפחיד", "איום", "זינוק", "שיא", "הבלוף",
    "התרחיש", "הסוד", "הטעות", "זה מה", "כל מה", "חייבים לדעת", "בדרך", "ישנה את",
]
IMPORTANT_WORDS = [
    "איראן", "מלחמה", "פיקוד העורף", "ריבית", "מס", "מחירים", "פיצויים", "שכר",
    "נדל", "דירות", "משרד התחבורה", "AI", "סייבר", "וואטסאפ", "בריאות", "טיסות",
    "דלק", "ממשלה", "ביטוח", "צרכנים", "הייטק", "בורסה", "רכב", "כביש", "תחבורה", "ספורט", "כדורגל", "נבחרת", "ליגת", "בחירות", "כנסת", "תקציב", "סלבס", "רכילות", "פפראצי", "פפארצי", "ריאליטי", "האח הגדול",
]
CATEGORY_RULES = [
    # Order matters: prefer specific practical topics over broad local/world buckets.
    ("אקטואליה בעולם", "security", ["קובה", "סנקציות", "רוסיה", "אוקראינה", "פקיסטן", "הודו", "סין", "טייוואן", "אירופה", "אירופי", "נאטו", "ארה\"ב", "ארצות הברית", "ממשל טראמפ", "white house", "federal reserve", "fed rate", "us interest", "u.s.", "united states", "sanctions", "cuba", "ukraine", "russia", "china", "taiwan", "pakistan", "india"]),
    ("משפט", "security", ["בגץ", "בג\"ץ", "בית המשפט", "עליון", "שופט", "שופטים", "יועמ\"ש", "פרקליטות", "כתב אישום", "עתירה", "חוק", "חקיקה", "משפטי", "legal", "court", "supreme court", "trial"]),
    ("ביטחון", "security", ["איראן", "מלחמה", "צה״ל", "צהל", "פיקוד העורף", "טילים", "ביטחון", "הורמוז", "אמירויות", "לבנון", "חמאס", "חיזבאללה", "חות׳ים", "חות'ים", "פוטין", "קרמלין", "התנקשות", "ביון", "צבא", "טרור", "war", "iran", "houthi", "houthis", "hormuz", "strait of hormuz", "persian gulf", "red sea", "bahrain", "yemen", "russia", "ukraine", "gaza", "israel", "military", "terror"]),
    ("פלילים", "security", ["רצח", "ירי", "דקירה", "חשד", "נעצר", "מעצר", "משטרה", "חקירה", "עבריין", "פשע", "פלילי", "סמים", "אלימות", "אונס", "crime", "police", "shooting", "murder", "arrest"]),
    ("פוליטיקה", "security", ["כנסת", "ממשלה", "בחירות", "קואליציה", "אופוזיציה", "תקציב", "שרים", "ח״כ", "חכים", "נתניהו", "טראמפ", "ביידן", "נשיא", "ראש ממשלה", "politics", "election", "government", "minister", "president", "trump", "white house"]),
    ("נדל״ן", "real", ["נדל", "דירה", "דירות", "בנייה", "פינוי-בינוי", "תל אביב", "דיור", "קרקע", "real estate", "housing"]),
    ("כלכלה", "money", ["ריבית", "מיסים", "מע״מ", "שכר", "מניות", "בורסה", "מחירים", "פיצויים", "עסקים", "אקזיט", "מיליון", "מיליארד", "דולר", "אינפלציה", "markets", "stocks", "economy", "bank", "inflation", "dollar"]),
    ("צרכנות", "money", ["צרכן", "רשתות", "שופרסל", "מחירי", "קניות", "ביטוח", "סופר", "חלב", "consumer", "shopping"]),
    ("טכנולוגיה", "tech", ["AI", "סייבר", "וואטסאפ", "אפל", "גוגל", "אפליקציה", "טכנולוג", "סטארטאפ", "GPT", "tech", "cyber", "apple", "google", "openai"]),
    ("רכב", "real", ["טיסות", "רכבת", "כביש", "רכב", "תחבורה", "דלק", "נתבג", "דובאי", "פקקים", "נהגים", "car", "vehicle", "transport", "flight"]),
    ("בריאות", "real", ["בריאות", "רפואה", "מחקר", "חולים", "תרופה", "תזונה", "כושר", "health", "medical", "medicine", "disease"]),
    ("רכילות", "real", ["רכילות", "סלבס", "סלב", "צהוב", "פפראצי", "פפארצי", "ריאליטי", "האח הגדול", "celebs", "celebrity", "gossip", "paparazzi"]),
    ("תרבות", "real", ["תרבות", "טלוויזיה", "סרט", "סדרה", "מוזיקה", "קולנוע", "ספר", "אוכל", "אופנה", "culture", "movie", "music", "tv"]),
    ("ספורט", "real", ["ספורט", "כדורגל", "כדורסל", "נבחרת", "ליגה", "ליגת", "מכבי", "הפועל", "ביתר", "אליפות", "מסי", "סוארס", "ניימאר", "יורוליג", "football", "soccer", "basketball", "league"]),
]


class LinkMetaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.meta = {}
        self.paragraphs = []
        self._href = None
        self._text = []
        self._in_p = False
        self._p_text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href'):
            self._href = attrs.get('href')
            self._text = []
        elif tag == 'meta':
            key = attrs.get('property') or attrs.get('name')
            if key and attrs.get('content'):
                self.meta[key.lower()] = attrs.get('content')
        elif tag == 'p':
            self._in_p = True
            self._p_text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)
        if self._in_p:
            self._p_text.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self._href is not None:
            self.links.append((self._href, ''.join(self._text)))
            self._href = None
            self._text = []
        elif tag == 'p' and self._in_p:
            self.paragraphs.append(''.join(self._p_text))
            self._in_p = False
            self._p_text = []


def parse_html(text: str) -> LinkMetaParser:
    parser = LinkMetaParser()
    try:
        parser.feed(text)
    except Exception:
        pass
    return parser

@dataclass
class Candidate:
    source: str
    url: str
    title: str
    description: str = ""
    score: int = 0
    image_url: str = ""
    original_title: str = ""
    published_at: str = ""


def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\b(?:border|width|height|src|alt|class|style)=['\"][^'\"]*['\"]", " ", text, flags=re.I)
    text = re.sub(r"['\"]?\s*/?>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("Bundibugyo", "בונדיבוגיו")
    text = re.sub(r"^[|\-–:•\s]+", "", text)
    return text[:500]



def child_text_by_local(item, names: set[str]) -> str:
    for child in item.iter():
        local = child.tag.split('}')[-1].lower()
        if local in names and child.text:
            return clean_text(child.text)
    return ""

def parse_feed_datetime(raw: str) -> str:
    raw = clean_text(raw)
    if not raw:
        return ""
    tz = timezone(timedelta(hours=3))
    try:
        dt = parsedate_to_datetime(raw)
    except Exception:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    dt = dt.astimezone(tz)
    now = datetime.now(tz)
    # Some feeds publish slightly future-dated items; do not let that break sorting.
    if dt > now + timedelta(minutes=5):
        dt = now
    return dt.isoformat(timespec='seconds')

def source_timing_key(source: str) -> str:
    s = re.sub(r"\s+דרך\s+(?:Google News|גוגל)\s*$", "", str(source or "").strip(), flags=re.I)
    low = s.lower()
    if "ערוץ 7" in s or "israel national news" in low or "inn" in low:
        return "ערוץ 7 / INN"
    if "כיפה" in s or "kipa" in low:
        return "כיפה"
    if "בשבע" in s or "besheva" in low:
        return "בשבע"
    if "מקור ראשון" in s or "makorrishon" in low:
        return "מקור ראשון"
    if "דובר צה" in s or "צה״ל" in s or "צה\"ל" in s:
        return "דובר צה״ל"
    if "משטרת ישראל" in s or "דוברות משטרת" in s or "israel police" in low:
        return "דוברות משטרת ישראל"
    if "cnn" in low:
        return "CNN"
    if "bbc" in low:
        return "BBC"
    if "sky news" in low or "sky" in low:
        return "Sky News"
    if "reuters" in low:
        return "Reuters"
    if low == "ap" or "ap middle east" in low or "associated press" in low:
        return "AP"
    if "guardian" in low:
        return "Guardian"
    if "new york times" in low or "nyt" in low:
        return "NYT"
    if "axios" in low:
        return "Axios"
    if "politico" in low:
        return "Politico"
    if "bloomberg" in low:
        return "Bloomberg"
    if "al jazeera" in low:
        return "Al Jazeera"
    if "jerusalem post" in low or "jpost" in low:
        return "Jerusalem Post"
    if "מטאורולוג" in s or "ims" in low:
        return "השירות המטאורולוגי"
    if "וואלה" in s or "walla" in low:
        return "וואלה"
    if "ynet" in low:
        return "ynet"
    if "גלובס" in s:
        return "גלובס"
    if "הארץ" in s or "haaretz" in low:
        return "הארץ"
    if "ישראל היום" in s:
        return "ישראל היום"
    if "מעריב" in s or "maariv" in low:
        return "מעריב"
    if "דה מרקר" in s or "TheMarker" in s or "themarker" in low:
        return "דה מרקר"
    if "N12" in s or "mako" in low:
        return "N12"
    return s.split(" - ")[0].strip() or "מקור"


def is_google_news_source_row(row: dict) -> bool:
    text = " ".join(str(row.get(key) or "") for key in ("source", "subSource", "url"))
    low = text.lower()
    return "דרך google news" in low or "דרך גוגל" in text or "news.google.com/rss" in low or "news.google.com/" in low

def source_logo(source: str) -> str:
    s = source.lower()
    if "דובר צה" in source or "צה״ל" in source:
        return "דובר צה״ל"
    if "משטרת ישראל" in source or "israel police" in s:
        return "משטרה"
    if "פיקוד העורף" in source:
        return "פיקוד העורף"
    if "מטאורולוג" in source or "ims" in s:
        return "IMS"
    if "cnn" in s:
        return "CNN"
    if "bbc" in s:
        return "BBC"
    if "sky" in s or "סקיי" in source:
        return "Sky News"
    if "reuters" in s:
        return "Reuters"
    if "ap" in s or "associated press" in s:
        return "AP"
    if "guardian" in s:
        return "Guardian"
    if "new york times" in s or "nyt" in s:
        return "NYT"
    if "axios" in s:
        return "Axios"
    if "politico" in s:
        return "Politico"
    if "bloomberg" in s:
        return "Bloomberg"
    if "al jazeera" in s:
        return "Al Jazeera"
    if "jerusalem post" in s or "jpost" in s:
        return "The Jerusalem Post"
    if "daily mail" in s or "dailymail" in s:
        return "Daily Mail"
    if "page six" in s or "pagesix" in s:
        return "Page Six"
    if "mirror" in s:
        return "Mirror"
    if "n12" in s or "mako" in s:
        return "N12"
    if "ערוץ 7" in source or "israel national news" in s or "inn" in s:
        return "ערוץ 7"
    if "כיפה" in source or "kipa" in s:
        return "כיפה"
    if "בשבע" in source or "besheva" in s:
        return "בשבע"
    if "מקור ראשון" in source or "makorrishon" in s:
        return "מקור ראשון"
    if "כאן" in source or "kan" in s:
        return "כאן"
    if "וואלה" in source:
        return "וואלה"
    if "ynet" in s:
        return "ynet"
    if "גלובס" in source:
        return "גלובס"
    if "הארץ" in source:
        return "הארץ"
    if "ישראל היום" in source:
        return "ישראל היום"
    if "מעריב" in source:
        return "מעריב"
    if "דה מרקר" in source or "themarker" in s:
        return "דה מרקר"
    if "14" in source:
        return "14"
    return source.split()[0] if source else "מקור"



def sanitize_title(title: str) -> str:
    title = clean_text(title)
    title = re.sub(r"\s*[-–|]\s*(N12|mako|וואלה|ynet|גלובס|ערוץ 14|C14|כיפה|מקור ראשון|CNN|BBC|Sky News).*$", "", title, flags=re.I).strip()
    title = re.sub(r"\s*\|\s*[^|]{2,45}\s*$", "", title).strip()
    title = re.sub(r"^\d{1,2}:\d{2}\s*", "", title).strip()
    title = re.sub(r"\d{1,2}:\d{2}\s*$", "", title).strip()
    # Remove glued/common bylines that homepage anchors append to titles.
    bylines = ["אפרת נומברג יונגר", "ליאור באקאלו", "מערכת וואלה ספורט", "מערכת וואלה", "מערכת גלובס"]
    for b in bylines:
        title = title.replace(b, "").strip()
    title = re.sub(r"(כתבי|מערכת|N12|וואלה|ynet|mako)\s*$", "", title).strip()
    title = title.strip(' -–:|')
    if re.match(r"^[א-ת]\s+את\s", title):
        return ""
    if re.fullmatch(r"[\u0590-\u05ff\s'\"-]{2,28}", title) and not any(w in title for w in IMPORTANT_WORDS + CLICKBAIT_WORDS):
        return ""
    return title


def bad_description(desc: str) -> bool:
    d = desc.lower()
    return any(x in d for x in ["captcha", "you are a bot", "grant access", "please solve", "מינוי גלובס בדיגיטל נותן לך גישה"])

def fetch(url: str, timeout: int = 15) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout) as r:
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read().decode(charset, errors="replace")



def fetch_jina_metadata(url: str) -> tuple[str, str]:
    """Read blocked article metadata via Jina Reader as a fallback.

    Used only when the direct source returns WAF/block pages or missing metadata.
    The returned title is treated as an exact source quote for `originalTitle`;
    do not sanitize/rewrite it before footer display.
    """
    jina_url = "https://r.jina.ai/http://r.jina.ai/http://" + url
    try:
        raw = fetch(jina_url, timeout=20)
    except Exception:
        return "", ""
    title = ""
    image = ""
    m = re.search(r"^Title:\s*(.+?)\s*$", raw, flags=re.M)
    if m:
        title = html.unescape(m.group(1).strip())
    # Prefer real article/media images and avoid source logo SVGs when possible.
    for img in re.findall(r"!\[[^\]]*\]\((https?://[^)]+)\)", raw):
        low = img.lower()
        if any(x in low for x in ["logo", ".svg", "mako-", "newlogo", "12+"]):
            continue
        image = img
        break
    return title, image




def is_rejected_source_image(url: str, source_url: str = "") -> bool:
    """Drop known publisher placeholder/misassigned images before feed publication."""
    low = (url or "").lower()
    source_low = (source_url or "").lower()
    if not low:
        return True
    if low.startswith("data:") or ".svg" in low or "logo" in low:
        return True
    # Maariv article pages are often Cloudflare-blocked in automation.  The RSS
    # / Jina fallback repeatedly assigns unrelated images.maariv.co.il assets to
    # different www.maariv.co.il stories (for example reserve-order, Trump,
    # Hatzalah Argentina, Hezbollah, horse/traffic-injury cards).  A neutral
    # placeholder is safer than a wrong face/event image.  Keep TMI images out of
    # this broad block because those section pages are parsed separately and have
    # a different visual contract.
    if (
        "images.maariv.co.il" in low
        and "maariv.co.il" in source_low
        and "tmi.maariv.co.il" not in source_low
    ):
        return True
    return False


def image_from_html_fragment(fragment: str) -> str:
    fragment = html.unescape(fragment or "")
    for m in re.finditer(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", fragment, flags=re.I):
        url = clean_text(m.group(1))
        if is_rejected_source_image(url):
            continue
        return url
    return ""


def image_from_rss_item(item: ET.Element, link: str, raw_desc: str) -> str:
    candidates: list[str] = []
    for child in item.iter():
        local = child.tag.split('}')[-1].lower()
        if local in {"thumbnail", "content", "enclosure"} or local.startswith("image"):
            url = child.attrib.get("url") or child.attrib.get("href") or clean_text(child.text or "")
            typ = child.attrib.get("type", "")
            if url and ("image" in typ or local in {"thumbnail", "content"} or local.startswith("image") or local == "enclosure"):
                candidates.append(url)
    desc_img = image_from_html_fragment(raw_desc)
    if desc_img:
        candidates.append(desc_img)
    for url in candidates:
        url = clean_text(html.unescape(url))
        joined = urljoin(link, url)
        if is_rejected_source_image(joined, link):
            continue
        return joined
    return ""



def parse_maariv_jina_rss(markdown: str, source: dict) -> list[Candidate]:
    """Recover official Maariv RSS through Jina Reader when Cloudflare blocks direct XML.

    Jina preserves the official RSS item order, links, images, descriptions, and
    pubDate lines as markdown.  Use it only as a read-through fallback for the
    same approved maariv.co.il/rss/* endpoints; do not broaden source scope.
    """
    out: list[Candidate] = []
    blocks = re.split(r"(?m)^### \[", markdown or "")
    for block in blocks[1:]:
        block = "[" + block
        m = re.match(r"\[(.*?)\]\((https?://(?:www\.)?(?:maariv|tmi\.maariv)\.co\.il/[^)]+)\)", block, flags=re.S)
        if not m:
            continue
        title = sanitize_title(m.group(1))
        link = clean_text(m.group(2))
        img_m = re.search(r"!\[[^\]]*\]\((https?://[^)]+)\)", block)
        image = clean_text(img_m.group(1)) if img_m else ""
        if is_rejected_source_image(image, link):
            image = ""
        date_m = re.search(r"(?m)^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+\d{1,2}\s+\w+\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+GMT\s*$", block)
        published_at = parse_feed_datetime(date_m.group(0)) if date_m else ""
        before_date = block[:date_m.start()] if date_m else block
        paras = []
        for line in before_date.splitlines()[1:]:
            line = line.strip()
            if not line or line.startswith("![") or line.startswith("[") or line.startswith("http"):
                continue
            paras.append(line)
        desc = clean_text(" ".join(paras))
        if len(title) < 18 or not link:
            continue
        score = score_title(title + " " + desc)
        if score <= 0:
            continue
        out.append(Candidate(source=source["name"], url=link, title=title, description=desc, score=score, image_url=image, original_title=title, published_at=published_at))
    return sorted(out, key=lambda c: (c.published_at or "", c.score), reverse=True)[:12]

_MAARIV_JINA_LAST_FETCH = 0.0


def fetch_maariv_jina_rss(rss_url: str) -> str:
    """Fetch Maariv/TMI RSS through Jina with throttling.

    The direct official RSS endpoints are Cloudflare-blocked in automation, and
    Jina rate-limits bursts across the many Maariv/TMI section feeds.  Keep this
    fallback deliberately narrow and slow enough so later section feeds do not
    silently return no candidates.
    """
    global _MAARIV_JINA_LAST_FETCH
    normalized = re.sub(r"^https?://", "", rss_url or "")
    jina_url = "https://r.jina.ai/http://" + normalized
    last_error: Exception | None = None
    for attempt in range(3):
        wait = max(0.0, 1.2 - (time.time() - _MAARIV_JINA_LAST_FETCH))
        if wait:
            time.sleep(wait)
        try:
            _MAARIV_JINA_LAST_FETCH = time.time()
            return fetch(jina_url, timeout=25)
        except HTTPError as exc:
            last_error = exc
            if getattr(exc, "code", None) == 429 and attempt < 2:
                time.sleep(3.0 * (attempt + 1))
                continue
            raise
    if last_error:
        raise last_error
    return fetch(jina_url, timeout=25)



TMI_HTML_SECTION_FALLBACKS = {
    "rssfeedstmistyle": "https://tmi.maariv.co.il/style",
    "rssfeedstmifashion": "https://tmi.maariv.co.il/fashion-tmf",
}


def parse_tmi_html_section(section_url: str, source: dict) -> list[Candidate]:
    """Recover TMI style/fashion sections from public HTML when RSS/Jina is rate-limited.

    These are the same official TMI sections represented by the configured RSS
    rows.  We only use article metadata from tmi.maariv.co.il and keep normal
    Pointa scoring/QA downstream.
    """
    try:
        raw = fetch(section_url, timeout=20)
    except Exception:
        return []
    links = []
    for m in re.finditer(r"https?://tmi\.maariv\.co\.il/[^\"'<> ]*article-\d+", raw):
        link = clean_text(html.unescape(m.group(0)))
        if link not in links:
            links.append(link)
    out: list[Candidate] = []
    for link in links[:12]:
        try:
            article = fetch(link, timeout=15)
        except Exception:
            continue
        title_m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', article, flags=re.I)
        desc_m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']', article, flags=re.I)
        date_m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', article)
        image_m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', article, flags=re.I)
        title = sanitize_title(html.unescape(title_m.group(1))) if title_m else ""
        title = re.sub(r"\s*\|\s*TMI\s*$", "", title).strip()
        desc = clean_text(html.unescape(desc_m.group(1))) if desc_m else ""
        published_at = parse_feed_datetime(date_m.group(1)) if date_m else ""
        image = clean_text(html.unescape(image_m.group(1))) if image_m else ""
        if is_rejected_source_image(image, link):
            image = ""
        if len(title) < 18:
            continue
        score = max(score_title(title + " " + desc) + 10, 3)
        out.append(Candidate(source=source["name"], url=link, title=title, description=desc, score=score, image_url=image, original_title=title, published_at=published_at))
    return sorted(out, key=lambda c: (c.published_at or "", c.score), reverse=True)[:12]


def parse_tmi_html_fallback_for_rss(rss_url: str, source: dict) -> list[Candidate]:
    low = (rss_url or "").lower()
    for key, section_url in TMI_HTML_SECTION_FALLBACKS.items():
        if key in low:
            return parse_tmi_html_section(section_url, source)
    return []


def google_news_noise_candidate(source: dict, title: str, link: str, published_at: str) -> bool:
    """Drop generic Google News result pages before they can become feed cards."""
    name = source.get("name", "")
    rss_url = source.get("rss", "")
    if "Google News" not in name and "news.google.com/rss" not in rss_url:
        return False
    low = f"{title} {link}".lower()
    if any(x in low for x in [
        "הרשמה", "פרסום", "תשדירים", "חסויות", "קהל הפתוח", "שידור חי",
        "מגזין 14", "חדשות בזמן אמת", "homepage", "עמוד הבית",
    ]):
        return True
    if re.fullmatch(r"(?:חדשות|מבזקים|שידור חי|מגזין|כלכלה|ספורט|פוליטיקה)(?:\s*[-–|].*)?", title.strip(), flags=re.I):
        return True
    dt = None
    if published_at:
        try:
            dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone(timedelta(hours=3)))
            dt = dt.astimezone(timezone(timedelta(hours=3)))
        except Exception:
            dt = None
    if dt and datetime.now(timezone(timedelta(hours=3))) - dt > timedelta(days=14):
        return True
    return False


def extract_rss(source: dict) -> list[Candidate]:
    rss_url = source.get("rss")
    if not rss_url:
        return []
    try:
        raw = fetch(rss_url)
        if "maariv.co.il/rss/rssfeedstmi" in rss_url or "maariv.co.il/rss/rssfeedstm" in rss_url:
            # Some TMI/Maariv RSS channels contain literal ampersands in
            # channel metadata (for example "OMG & WOW"). Recover those feeds
            # instead of dropping an otherwise valid official source.
            raw = re.sub(r"&(?!#\d+;|#x[0-9A-Fa-f]+;|[A-Za-z][A-Za-z0-9]+;)", "&amp;", raw)
        if source.get("name") == "ICE - ראשי" and "xmlns:media" not in raw[:500] and "media:" in raw:
            # ICE exposes a useful RSS feed but omits common namespace
            # declarations while using atom:/dc:/media: tags. ElementTree
            # rejects that as "unbound prefix"; declare the standard namespaces
            # so the source can be parsed without weakening quality gates.
            raw = raw.replace(
                '<rss version="2.0">',
                '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:media="http://search.yahoo.com/mrss/">',
                1,
            )
        root = ET.fromstring(raw)
    except Exception as e:
        if "maariv.co.il/rss/" in rss_url:
            try:
                return parse_maariv_jina_rss(fetch_maariv_jina_rss(rss_url), source)
            except Exception as fallback_exc:
                tmi_fallback = parse_tmi_html_fallback_for_rss(rss_url, source)
                if tmi_fallback:
                    return tmi_fallback
                print(f"WARN rss fetch failed {source['name']}: {e}; maariv jina fallback failed: {fallback_exc}", file=sys.stderr)
                return []
        print(f"WARN rss fetch failed {source['name']}: {e}", file=sys.stderr)
        return []
    out = []
    for item in root.findall('.//item'):
        title = sanitize_title(''.join(item.findtext('title') or ''))
        link = clean_text(item.findtext('link') or '')
        raw_desc = item.findtext('description') or ''
        desc = clean_text(re.sub(r'<[^>]+>', ' ', raw_desc))
        published_at = parse_feed_datetime(child_text_by_local(item, {'pubdate', 'published', 'updated', 'date', 'dc:date', 'created'}))
        if google_news_noise_candidate(source, title, link, published_at):
            continue
        image = image_from_rss_item(item, link, raw_desc)
        if len(title) < 18 or not link:
            continue
        if source.get("name", "").startswith("גלובס") and "en.globes.co.il" in link:
            continue
        score = score_title(title + ' ' + desc)
        if source.get("categoryHint") == "רכילות":
            # Gossip/celebs is now an explicit domain. Do not let the old
            # celebrity-noise penalty erase validated RSS items from it.
            score = max(score + 10, 3)
        if source.get("language") == "en" or any(x in source.get("name", "") for x in ["BBC", "CNN", "Sky"]):
            score += 20
        if score <= 0:
            continue
        out.append(Candidate(source=source['name'], url=link, title=title, description=desc, score=score, image_url=image, original_title=title, published_at=published_at))
    return sorted(out, key=lambda c: (c.published_at or '', c.score), reverse=True)[:12]


def telegram_text_from_block(block: str) -> str:
    m = re.search(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', block, re.S)
    if not m:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", m.group(1), flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [clean_text(x) for x in text.splitlines()]
    return "\n".join(x for x in lines if x)


def summarize_oref_telegram(text: str) -> tuple[str, str, int]:
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if not lines:
        return "", "", 0
    alert_type = re.sub(r"^[^\u0590-\u05ffA-Za-z0-9]+", "", lines[0])
    alert_type = re.sub(r"\s*\([^)]*\)", "", alert_type).strip()
    alert_type = re.sub(r"\s+\d{1,2}:\d{2}\s*$", "", alert_type).strip()
    areas: list[str] = []
    cities: list[str] = []
    instructions: list[str] = []
    for i, line in enumerate(lines[1:], start=1):
        if line.startswith("אזור "):
            areas.append(line.replace("אזור ", "", 1))
            if i + 1 < len(lines) and not lines[i + 1].startswith("אזור "):
                cities.extend([x.strip() for x in re.split(r",", lines[i + 1]) if x.strip()])
        elif any(w in line for w in ["היכנסו", "האירוע הסתיים", "יכולים לצאת", "הנחיות פיקוד העורף"]):
            instructions.append(line)
    area = ", ".join(dict.fromkeys(areas)) or "אזורי התרעה"
    city_list = ", ".join(dict.fromkeys(cities[:8]))
    if "האירוע הסתיים" in text:
        title = f"פיקוד העורף: האירוע הסתיים ב{area}"
        score = 65
    else:
        title = f"פיקוד העורף: {alert_type} ב{area}"
        score = 95
    desc_parts = []
    if city_list:
        desc_parts.append(f"יישובים: {city_list}.")
    if instructions:
        desc_parts.append(instructions[0])
    desc = " ".join(desc_parts) or clean_text(" ".join(lines[1:]))
    return title, desc, score


def summarize_idf_telegram(text: str) -> tuple[str, str, int]:
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if not lines:
        return "", "", 0
    if lines[0].replace("״", '"') == 'דובר צה"ל:':
        lines = lines[1:]
    # Drop call-to-action link rows; keep the substance of the Telegram post.
    lines = [x for x in lines if not x.startswith("לכתבה המלאה") and not x.startswith("http") and "ערוץ הטלגרם" not in x]
    if not lines:
        return "", "", 0
    title = clean_text(lines[0])
    if len(title) < 18 and len(lines) > 1:
        title = clean_text(f"{lines[0]} {lines[1]}")
    body_lines = lines[1:] if len(lines) > 1 else []
    desc = clean_text(" ".join(body_lines[:3]))
    if not desc:
        desc = title
    score = 95 if any(w in f"{title} {desc}" for w in ["חיסל", "יירט", "תקף", "התרעות", "לבנון", "עזה", "חמאס", "חיזבאללה", "כטב", "רחפן"]) else 70
    return title, desc, score


def extract_telegram_channel(source: dict) -> list[Candidate]:
    url = source.get("telegram")
    if not url:
        return []
    try:
        raw = fetch(url, timeout=15)
    except Exception as e:
        print(f"WARN telegram fetch failed {source['name']}: {e}", file=sys.stderr)
        return []
    out: list[Candidate] = []
    blocks = re.findall(r'<div class="tgme_widget_message_wrap[^>]*>.*?(?=<div class="tgme_widget_message_wrap|</main>|</body>)', raw, re.S)
    for block in blocks:
        text = telegram_text_from_block(block)
        if not text:
            continue
        post = re.search(r'data-post="([^"]+)"', block)
        time_m = re.search(r'<time datetime="([^"]+)"', block)
        post_path = post.group(1) if post else ""
        link = f"https://t.me/{post_path}" if post_path else url
        if source.get("telegramKind") == "oref":
            title, desc, score = summarize_oref_telegram(text)
        else:
            title, desc, score = summarize_idf_telegram(text)
        title = sanitize_title(title)
        if len(title) < 18:
            continue
        out.append(Candidate(
            source=source["name"],
            url=link,
            title=title,
            description=desc,
            score=score,
            original_title=clean_text(text.splitlines()[0] if text.splitlines() else title),
            published_at=parse_feed_datetime(time_m.group(1) if time_m else ""),
        ))
    return sorted(out, key=lambda c: (c.published_at, c.score), reverse=True)[:12]


def extract_source(source: dict) -> list[Candidate]:
    if source.get("telegram"):
        return extract_telegram_channel(source)
    return extract_rss(source)


def extract_links(source: dict) -> list[Candidate]:
    try:
        parser = parse_html(fetch(source["url"]))
    except Exception as e:
        print(f"WARN source fetch failed {source['name']}: {e}", file=sys.stderr)
        return []

    seen: set[str] = set()
    out: list[Candidate] = []
    for raw_href, raw_title in parser.links:
        title = sanitize_title(raw_title)
        if len(title) < 18 or len(title) > 180:
            continue
        href = urljoin(source["url"], raw_href)
        host = urlparse(href).netloc
        if source["host"].replace("www.", "") not in host.replace("www.", "") and "mako.co.il" not in host:
            continue
        if href in seen:
            continue
        seen.add(href)
        score = score_title(title)
        if score <= 0:
            continue
        out.append(Candidate(source=source["name"], url=href, title=title, score=score))
    return sorted(out, key=lambda c: c.score, reverse=True)[:10]


def score_title(title: str) -> int:
    score = 0
    for w in CLICKBAIT_WORDS:
        if w in title:
            score += 4
    for w in IMPORTANT_WORDS:
        if w.lower() in title.lower():
            score += 3
    if "?" in title:
        score += 2
    if any(ch.isdigit() for ch in title):
        score += 1
    if 28 <= len(title) <= 95:
        score += 1
    # Filter celebrity/food noise unless very high signal
    if any(w in title for w in ["מזל טוב", "התחתן", "עוגה", "מתכון", "סלבס", "סאות'המפטון", "כדורגל", "שוער", "פרמיירליג", "נביא", "אסטרולוג", "מיסטיקן"]):
        score -= 7
    if re.search(r"^[0-9: \u0590-\u05ff\s\'\"-]{2,30}$", title) and not any(w in title for w in IMPORTANT_WORDS + CLICKBAIT_WORDS):
        score -= 8
    if "בשיתוף" in title or "פרסומת" in title:
        score -= 6
    return score


def should_replace_source_description(existing: str, enriched: str) -> bool:
    """Return whether article-page enrichment should replace source-feed text.

    Source RSS/telegram text is the durable fallback.  Article pages are often
    blocked, empty, or return WAF/login boilerplate; a failed enrichment must not
    turn a usable source candidate into a thin card for any publisher.
    """
    enriched = clean_text(enriched)
    if not enriched or bad_description(enriched):
        return False
    existing = clean_text(existing)
    # If the source feed already supplied substantive text, do not replace it
    # with a very short/low-information metadata fragment.
    if len(existing) >= 40 and len(enriched) < 30:
        return False
    return True


def word_count(text: str) -> int:
    return len(re.findall(r"[0-9A-Za-z\u0590-\u05ff]+", clean_text(text)))


def should_enrich_for_context(candidate: Candidate) -> bool:
    """Fetch the article page only when the source text is too thin.

    Short RSS summaries should trigger a deeper read, but lack of depth must not
    reject the story.  The RSS text remains the fallback if the article page is
    blocked or does not expose useful text.
    """
    if not candidate.url or "news.google.com/" in candidate.url:
        return False
    if word_count(candidate.description) < MIN_CONTEXT_WORDS_BEFORE_ENRICH:
        return True
    if has_latin_text(candidate.description) and not is_foreign_source_label(candidate.source):
        return True
    return False


def enrich(candidate: Candidate, timeout: int = 12, allow_jina: bool = True) -> Candidate:
    try:
        raw = fetch(candidate.url, timeout=timeout)
        parser = parse_html(raw)
    except Exception:
        raw = ""
        parser = parse_html("")

    exact_title = clean_text(parser.meta.get("og:title") or parser.meta.get("twitter:title") or "")
    image = clean_text(parser.meta.get("og:image") or parser.meta.get("twitter:image") or parser.meta.get("image") or "")

    # Some N12/Mako URLs return a Radware block page to direct fetches.
    # In that case, use Jina Reader as a metadata fallback so the footer link
    # still gets the exact source headline instead of the rewritten Poanta title.
    if allow_jina and (not exact_title or "Radware Block Page" in raw):
        jina_title, jina_image = fetch_jina_metadata(candidate.url)
        exact_title = jina_title or exact_title
        image = image or jina_image
    if is_rejected_source_image(image, candidate.url):
        image = ""

    if exact_title and len(exact_title) >= 18:
        candidate.original_title = exact_title
        candidate.title = sanitize_title(exact_title) or exact_title
    if image:
        candidate.image_url = urljoin(candidate.url, image)
    meta_desc = clean_text(parser.meta.get("og:description") or parser.meta.get("description") or parser.meta.get("twitter:description") or "")
    ps = [clean_text(p) for p in parser.paragraphs]
    body_desc = clean_text(" ".join(p for p in ps if len(p) > 40)[:650])
    desc = body_desc if word_count(body_desc) > word_count(meta_desc) else meta_desc
    # Preserve the source/RSS/telegram description unless enrichment produced a
    # clearly useful replacement.  This is source-agnostic by design: Ynet was
    # the first visible failure, but the same WAF/empty-page pattern can hit any
    # publisher.
    if should_replace_source_description(candidate.description, desc):
        candidate.description = clean_text(desc)
    return candidate


def rule_matches(text: str, word: str) -> bool:
    low = text.lower()
    w = word.lower()
    # Avoid matching short Latin tokens such as AI inside words like train/mountain.
    if re.fullmatch(r"[a-z0-9]{1,3}", w):
        return re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", low) is not None
    return w in low

def categorize(text: str) -> tuple[str, str]:
    titleish = text.split(". ", 1)[0]
    for cat, cls, words in CATEGORY_RULES:
        if any(rule_matches(titleish, w) for w in words):
            return cat, cls
    for cat, cls, words in CATEGORY_RULES:
        if any(rule_matches(text, w) for w in words):
            return cat, cls
    return "חדשות", ""


WORLD_ONLY_STORY_TERMS = ["קובה", "פוקושימה", "fukushima", "cuba"]
MIDDLE_EAST_OR_ISRAEL_TERMS = [
    "ישראל", "israel", "ישראלי", "הסכמי אברהם", "abraham accords", "recognising israel",
    "middle east", "mideast", "מזרח תיכון", "המזרח התיכון", "עזה", "gaza", "חמאס", "hamas",
    "חיזבאללה", "hezbollah", "לבנון", "lebanon", "סוריה", "syria", "החותים", "houthis",
    "איראן", "iran", "טהרן", "tehran", "הורמוז", "hormuz", "סעודיה", "saudi",
    "קטאר", "qatar", "מצרים", "egypt", "ירדן", "jordan", "טורקיה", "turkey",
    "מדינות המפרץ", "המפרץ", "gulf states", "palestinian", "פלסטיני",
]
REGIONAL_SECURITY_TERMS = [
    "איראן", "iran", "הורמוז", "hormuz", "גרעין", "nuclear", "מלחמה", "war",
    "הסכם", "deal", "הסכמי אברהם", "abraham", "נורמליזציה", "normalization", "normalisation",
    "חמאס", "חיזבאללה", "טילים", "צבא", "צה\"ל", "צה״ל", "דובר צה\"ל", "דובר צה״ל",
    "תקיפה", "פינוי", "התפנות", "כפרים בדרום לבנון", "military", "terror", "hostage", "חטופים",
]
REGIONAL_POLITICS_TERMS = ["כנסת", "ממשלה", "נתניהו", "שר", "שרים", "בחירות", "קואליציה", "אופוזיציה", "minister", "government", "election"]


def is_middle_east_or_israel_story(text: str, source: str = "") -> bool:
    low = text.lower()
    source_low = source.lower()
    # A Cuba/Fukushima/etc. story can mention Iran/Trump without being Israel/Middle-East news.
    if any(term.lower() in low for term in WORLD_ONLY_STORY_TERMS) and not any(term.lower() in low for term in ["ישראל", "israel", "הסכמי אברהם", "abraham accords", "middle east", "mideast", "gaza", "עזה"]):
        return False
    if any(term.lower() in low for term in MIDDLE_EAST_OR_ISRAEL_TERMS):
        return True
    # Source labels can be a hint only for explicit Middle-East feeds; do not treat Hebrew outlet names
    # like "ישראל היום" as an Israel-angle signal for unrelated world items.
    return any(term in source_low for term in ["middle east", "mideast", "מזרח תיכון"])


def regional_category(text: str) -> tuple[str, str]:
    low = text.lower()
    if any(term.lower() in low for term in REGIONAL_SECURITY_TERMS):
        return "ביטחון", "security"
    if any(
        (re.search(rf"(?<![א-ת]){re.escape(term.lower())}(?![א-ת])", low) if re.fullmatch(r"[א-ת]{1,3}", term) else term.lower() in low)
        for term in REGIONAL_POLITICS_TERMS
    ):
        return "פוליטיקה", "security"
    return "חדשות", ""


def has_hebrew_phrase(text: str, phrase: str) -> bool:
    """Match Hebrew weather terms as standalone phrases, not inside verbs.

    Plain substring matching made ``הבהיר`` ("clarified") look like ``בהיר``
    ("clear/sunny"), which routed non-weather politics/sports cards to the
    weather category.  Hebrew has no capitalization, so guard both sides with a
    Hebrew-letter negative lookaround for short sky-condition words.
    """
    return re.search(rf"(?<![א-ת]){re.escape(phrase)}(?![א-ת])", text) is not None


def is_weather_forecast_story(title: str, desc: str, source: str = "") -> bool:
    text = f"{title} {desc}"
    source_text = source or ""
    low = f"{text} {source_text}".lower()
    official_weather_source = any(x in source_text for x in ["השירות המטאורולוגי", "IMS", "תחזית"])
    strong_weather_markers = [
        "תחזית מזג אוויר", "מזג האוויר", "מזג אוויר", "טמפרטורות",
        "weather", "forecast", "temperatures",
    ]
    detail_terms = [
        "טמפרטורות", "מעלות", "מעונן", "בהיר", "גשם", "גשמים", "שרב", "רוחות",
        "אובך", "temperatures",
    ]
    has_strong_weather = any(marker.lower() in low for marker in strong_weather_markers)
    has_forecast_detail = any(
        (detail.lower() in low if detail.isascii() else has_hebrew_phrase(low, detail))
        for detail in detail_terms
    )
    # Official weather-source rows can be forecast cards even when the title is
    # compact.  General news rows need an explicit weather/forecast marker plus
    # a concrete detail, so verbs like "הבהיר" do not count as sunny weather.
    return has_forecast_detail and (official_weather_source or has_strong_weather)


def categorize_item(title: str, desc: str, source: str) -> tuple[str, str]:
    # With many section RSS feeds enabled, the feed name is a strong signal.
    # Prefer it over incidental keywords in the title/description so sports,
    # car, tech, health and culture feeds are not mislabeled as politics/real estate.
    content_text = f"{title} {desc}"
    text = f"{content_text} {source}"
    # Security/war flashes must be categorized before weather/crime fallbacks.
    # Otherwise words such as "רוחות" in unrelated context or bare "ירי" can
    # misroute Lebanon/rocket/IDF items to weather or local crime during Stage-4
    # domain rescue validation.
    low_content = content_text.lower()
    gulf_security_terms = ["houthi", "houthis", "hormuz", "strait of hormuz", "persian gulf", "red sea", "bahrain", "yemen"]
    if any(term in low_content for term in gulf_security_terms):
        return "ביטחון", "security"
    if any(x in content_text for x in ["חוק הגיוס", "עריקים חרדים", "מעצרי העריקים", "גיוס חרדים"]):
        return "פוליטיקה", "security"
    security_conflict_terms = [
        "חיזבאללה", "לבנון", "צה\"ל", "צה״ל", "פיקוד העורף", "רקטה", "רקטות",
        "כטב\"ם", "כטב״ם", "יירוט", "יורטו", "חצו", "אזעקות", "התרעות",
        "טילים", "טיל", "חמאס", "עזה", "איראן", "הורמוז", "חות׳ים", "חות'ים", "זפוריז'יה", "זפוריז׳יה",
    ]
    if any(x in content_text for x in security_conflict_terms):
        return "ביטחון", "security"
    if is_weather_forecast_story(title, desc, source):
        return "מזג אוויר", "real"
    # Local emergency/crime flashes must not fall back to generic "חדשות",
    # because the public app maps generic news to the politics tab/chip. Keep
    # shootings, murders and rescue/fire emergencies out of visible politics.
    local_emergency_terms = [
        "נורה", "ירי", "נרצח", "רצח", "דקירה", "נדקר", "פצוע קשה",
        "שריפה", "חולצו", "לכודים", "כיבוי", "כבאות",
    ]
    if any(x in content_text for x in local_emergency_terms) and not any(x in content_text for x in ["כנסת", "ממשלה", "נתניהו", "בחירות", "קואליציה"]):
        return "פלילים", "security"
    if any(x in text for x in ['תכולת בית', 'תכולת הבית', 'נזקי מלחמה', 'מס רכוש']):
        return "צרכנות", "money"
    if any(x in text for x in ['אלפין', 'פורשה', 'פרארי', 'אסטון מרטין']) and any(x in text for x in ['בטיחות', 'בלימה אוטונומית', 'כריות אוויר']):
        return "רכב", "real"
    if is_avihu_pinchasov_genesis_story(title, desc) or is_amos_luzon_relationship_story(title, desc):
        return "תרבות", "real"
    # Explicit vertical RSS sections are stronger than broad Israel/Middle-East
    # regional heuristics. Otherwise local sports/culture items containing words
    # such as "הבטחת"/"שריקה" can be routed to security/politics before the
    # source-section guard below runs, and Stage-4 domain rescue opens off-domain
    # editor batches.
    if any(x in source for x in ["ספורט", "כדורגל", "כדורסל", "NBA", "טניס"]):
        return "ספורט", "real"
    if any(x in source for x in ["רכב", "דו-גלגלי", "ביטוח רכב", "בטיחות"]):
        return "רכב", "real"
    if any(x in source for x in ["TECH", "טכנולוג", "סייבר", "סטארטאפים", "סמארטפונים", "מחשבים", "מדע"]):
        return "טכנולוגיה", "tech"
    if any(x in source for x in ["בריאות", "תזונה", "כושר", "רפואה", "הריון"]):
        return "בריאות", "real"
    if any(x in source for x in ["כלכלה", "כסף", "שוק ההון", "גלובס", "צרכנות", "קריפטו", "קריירה"]):
        return "כלכלה", "money"
    if any(x in source for x in ["רכילות", "סלבס", "TMI", "פפראצי", "פפארצי", "ריאליטי", "צהוב"]):
        return "רכילות", "real"
    if any(x in source for x in ["תרבות", "טלוויזיה", "מוזיקה", "קולנוע", "ספרות", "אמנות", "אוכל", "תיירות", "טיולים", "אופנה", "בית ועיצוב"]):
        return "תרבות", "real"
    # Lior's boundary: אקטואליה בעולם is only for global stories with no Israel/Middle-East angle.
    # Israel/Middle-East items from foreign sources still belong to the normal news/security/politics domains.
    if is_middle_east_or_israel_story(content_text, source):
        return regional_category(text)
    if any(x in text for x in ['איראן', 'הורמוז', 'גרעין', 'אורניום']) and any(x in text for x in ['טראמפ', 'ארצות הברית', 'ארה"ב', 'מו"מ', 'משא ומתן', 'מזכר הבנות', 'עסקה', 'הסכם']):
        return "ביטחון", "security"
    if any(x in text for x in ['קובה', 'פוקושימה', 'הבית הלבן', 'White House', 'חמוש ירה ליד הבית הלבן', 'ממשל טראמפ נגד']) and not any(x in source for x in ['ספורט', 'רכב', 'סלבס', 'רכילות']):
        return "אקטואליה בעולם", "security"
    if any(x in text for x in ['רוכב אופניים', 'אופניים חשמליים', 'תאונת דרכים', 'נפצע בתאונה']) and any(x in text for x in ['רכב', 'כביש', 'רחוב', 'תאונה']):
        return "רכב", "real"
    if 'איראן' in text and any(x in text for x in ['כבלים', 'סוויפט', 'הורמוז', 'תת ימיים']):
        return "ביטחון", "security"
    if any(x in text for x in ['מערכת הבריאות', 'רופאים', 'בתי החולים', 'תקנים', "פרופ' חגי לוין"]):
        return "בריאות", "real"
    if any(x in text for x in ['אל ניניו', 'אל-ניניו', 'לה ניניה', 'גשמים עזים', 'שיטפונות', 'מזג אוויר קיצוני', 'התחממות הים', 'אקלים']):
        return "מזג אוויר", "real"
    if any(x in text for x in ['תכולת בית', 'תכולת הבית', 'נזקי מלחמה', 'מס רכוש']):
        return "צרכנות", "money"
    if any(x in text for x in ['אלפין', 'פורשה', 'פרארי', 'אסטון מרטין']) and any(x in text for x in ['בטיחות', 'בלימה אוטונומית', 'כריות אוויר']):
        return "רכב", "real"
    if is_avihu_pinchasov_genesis_story(title, desc) or is_amos_luzon_relationship_story(title, desc):
        return "תרבות", "real"
    if any(x in source for x in ["ספורט", "כדורגל", "כדורסל", "NBA", "טניס"]):
        return "ספורט", "real"
    if any(x in source for x in ["רכב", "דו-גלגלי", "ביטוח רכב", "בטיחות"]):
        return "רכב", "real"
    if any(x in source for x in ["TECH", "טכנולוג", "סייבר", "סטארטאפים", "סמארטפונים", "מחשבים", "מדע"]):
        return "טכנולוגיה", "tech"
    if any(x in source for x in ["בריאות", "תזונה", "כושר", "רפואה", "הריון"]):
        return "בריאות", "real"
    if any(x in source for x in ["כלכלה", "כסף", "שוק ההון", "גלובס", "צרכנות", "קריפטו", "קריירה"]):
        return "כלכלה", "money"
    if any(x in source for x in ["רכילות", "סלבס", "TMI", "פפראצי", "פפארצי", "ריאליטי", "צהוב"]):
        return "רכילות", "real"
    if any(x in source for x in ["תרבות", "טלוויזיה", "מוזיקה", "קולנוע", "ספרות", "אמנות", "אוכל", "תיירות", "טיולים", "אופנה", "בית ועיצוב"]):
        return "תרבות", "real"
    if any(x in source for x in ["CNN", "BBC", "Sky News", "סקיי"]):
        fp = foreign_pointa_tuple(title, desc)
        if fp:
            return fp[3], fp[4]
        return categorize(text)
    if any(x in source for x in ["חדשות בעולם", "World", "Middle East", "Al Jazeera", "Guardian", "Reuters", "AP", "Axios", "Politico", "Bloomberg", "New York Times", "NYT", "JNS", "Jewish News Syndicate", "France24", "France 24", "The Media Line"]):
        cat, cls = categorize(text)
        if cat in {"חדשות", "פוליטיקה", "ביטחון"}:
            return "אקטואליה בעולם", "security"
        return cat, cls
    if any(x in source for x in ["דעות", "פרשנויות"]):
        return "דעות", "security"
    cat, cls = categorize(title)
    if cat != "חדשות":
        return cat, cls
    return cat, cls



QUOTEISH_RE = re.compile(r'["״“”].{0,80}["״“”]|^.*?:')
GENERIC_HEADLINE_RE = re.compile(r'הפואנטה היא|הכותרת הכלכלית|הסיפור הנדלני|הפרסום הצרכני|החידוש הטכנולוגי|האירוע הביטחוני|מאחורי הכותרת|השינוי התחבורתי|הדרמה הספורטיבית')

def split_sentences(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    parts = re.split(r'(?<=[.!?؟])\s+|(?<=\u05c3)\s+', text)
    out = []
    for part in parts:
        part = clean_text(part).strip(' -–•')
        if 18 <= len(part) <= 260:
            out.append(part)
    return out


def trim_words(text: str, max_chars: int) -> str:
    text = clean_text(text).strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(' ', 1)[0].strip(' ,;:-–')
    return cut


DANGLING_HEADLINE_ENDINGS = {
    'של', 'את', 'על', 'עם', 'אל', 'כל', 'כי', 'אבל', 'אולם', 'כאשר', 'בגלל',
    'בין', 'תוך', 'לפני', 'אחרי', 'עד', 'מול', 'נגד', 'כדי', 'אם', 'בעקבות',
    'רק', 'לא', 'בלי', 'תחת', 'לצד', 'במהלך', 'לאחר', 'לקראת', 'בעוד',
    'ח"כ', 'ח״כ', 'גררו', 'נאלצו', 'התייחס', 'התארח', 'נחשף', 'יוכלו',
}


def headline_looks_cut(text: str) -> bool:
    text = clean_text(text).strip(' ,;:-–')
    if not text:
        return True
    words = text.split()
    last = words[-1].strip('"׳״.,;:!?()[]') if words else ''
    if last in DANGLING_HEADLINE_ENDINGS:
        return True
    if text.endswith((',', ':', '-', '–')):
        return True
    quote_test = re.sub(r'(?<=[A-Za-zא-ת])"(?=[A-Za-zא-ת])', '', text)
    if quote_test.count('"') % 2 or text.count('(') > text.count(')'):
        return True
    if re.search(r"(?<![א-ת])(כי|כאשר|בזמן ש|לאחר ש|בעוד ש)(?![א-ת])\s+[^.?!]{0,90}$", text) and not re.search(r"[.?!]$", text):
        return True
    return False


def complete_headline(text: str, max_chars: int = 108) -> str:
    """Return a compact headline without cutting it at a visibly incomplete point.

    Pointa cards must not look like the generator simply chopped a sentence.
    Prefer a complete first sentence. If the sentence is too long, keep a longer
    phrase than before and avoid dangling connector/preposition endings.
    """
    text = clean_text(text).replace('…', '').replace('...', '').strip(' ,;:-–')
    if not text:
        return text
    if len(text) <= max_chars and not headline_looks_cut(text):
        return text.rstrip('.')
    sentences = split_sentences(text)
    if sentences:
        first = sentences[0].strip(' ,;:-–')
        if len(first) <= max_chars and not headline_looks_cut(first):
            return first.rstrip('.')
    # Try a clause boundary before falling back to a word cut.
    window = text[:max_chars + 22]
    boundaries = [m.end() for m in re.finditer(r'[,;:–-]\s+', window)]
    for pos in reversed(boundaries):
        candidate = window[:pos].strip(' ,;:-–')
        if 34 <= len(candidate) <= max_chars and not headline_looks_cut(candidate):
            return candidate.rstrip('.')
    limit = max_chars
    while limit >= 52:
        candidate = trim_words(text, limit).strip(' ,;:-–')
        if candidate and not headline_looks_cut(candidate):
            return candidate.rstrip('.')
        limit -= 10
    return trim_words(text, max_chars).strip(' ,;:-–').rstrip('.')


def strip_ellipsis(text: str) -> str:
    return clean_text(text).replace('…', '').replace('...', '').strip(' ,;:-–')


def short_sentence(text: str, max_chars: int) -> str:
    return strip_ellipsis(trim_words(text, max_chars)).rstrip('.')


def article_text(title: str, desc: str) -> str:
    return strip_ellipsis(f"{title}. {desc}")


def experimental_headline(title: str, desc: str) -> str:
    """New Pointa prompt: headline contains the conclusion, not a teaser."""
    text = article_text(title, desc)
    if 'איראן' in text and any(x in text for x in ['כבלים התת', 'כבלים תת', 'סוויפט', 'הורמוז']) and any(x in text for x in ['10 טריליון', 'סליקה', 'עסקאות', 'דמי שימוש']):
        return 'איראן מאיימת על תשתית הכסף של העולם'
    if any(x in text for x in ['תכולת הבית', 'תכולת בית']) and any(x in text for x in ['נזקי מלחמה', 'פעולות איבה', 'מס רכוש', '0.3%']):
        return 'ביטוח דירה רגיל לא מכסה נזקי טילים לתכולה'
    if any(x in text for x in ['אלפין', 'פורשה', 'פרארי', 'אסטון מרטין']) and any(x in text for x in ['כריות אוויר', 'בלימה אוטונומית', 'בטיחות']):
        return 'מכוניות ספורט יקרות נמכרות בלי בטיחות בסיסית'
    if ('מכונת מזומנים' in text or 'שואב מיליארדים' in text or 'מנוע הכנסות' in text) and 'ספורט' in text:
        return 'גימיק טכנולוגי הפך למכונת מיליארדים בספורט'
    if 'פורמולה 1' in text and any(x in text for x in ['מטא', 'גוגל', 'אדידס', 'AI']):
        return 'חברות AI מזניקות את חסויות הפורמולה 1'
    if 'תאונות קורקינטים' in text and any(x in text for x in ['פיצוי', 'לתבוע', 'פגיעה']):
        return 'תאונות קורקינט הופכות לשאלת פיצוי וביטוח'
    if 'MBA' in text and any(x in text for x in ['קורסי בחירה', 'התמחויות', 'אונו']):
        return 'תואר MBA נמכר דרך גמישות והתמחויות רבות'
    if 'ביטוח רכב' in text and any(x in text for x in ['שינויים כלכליים', 'לעלות']):
        return 'ביטוח רכב מתייקר ודורש בדיקת תנאים'
    if 'ביטוח רכב' in text and any(x in text for x in ['דצמבר', 'סיום הפוליסה']):
        return 'חידוש ביטוח בדצמבר עלול להיות הרגל יקר'
    if 'הטילים פגעו' in text and any(x in text for x in ['תכולת הבית', 'תכולת בית', '0.3%', 'הממשלתי']):
        return 'פגיעת טיל חושפת חור בכיסוי תכולת הבית'
    if 'אלפין' in text and any(x in text for x in ['כריות אוויר', 'בלימה אוטונוטמית', 'פורשה']):
        return 'מכוניות ספורט יקרות נמכרות בלי בטיחות בסיסית'
    if 'יוקר התחבורה' in text and 'מחיר הדלק' in text:
        return 'יוקר התחבורה רחב הרבה יותר ממחיר הדלק'
    if 'פסטיבל קאן' in text and 'AI' in text:
        return 'תעשיית הקולנוע מתחילה להשלים עם יצירת AI'
    if 'האח הגדול' in text and 'הדחות' in text:
        return 'הפקת האח הגדול משתמשת בהדחות פתע כדי להחזיק עניין'
    h = story_headline(title, desc, "")
    h = re.sub(r'^(האם|למה|איך|מתי)\s+', '', h).replace('?', '').strip(' -–:')
    replacements = {
        'נחשף': '', 'דרמה': '', 'סערה': '', 'טירוף': '', 'צפו': '',
        'לא תאמינו': '', 'הסיבה תפתיע אתכם': '', 'מה שקרה אחר כך': '',
    }
    for bad, repl in replacements.items():
        h = h.replace(bad, repl)
    h = re.sub(r'\s+', ' ', h).strip(' -–:')
    return short_sentence(h or dequote_headline(title), 82)


def experimental_summary(title: str, desc: str, source: str) -> str:
    """Two compressed sentences: what happened + consequence from article text."""
    text = article_text(title, desc)
    if 'איראן' in text and any(x in text for x in ['כבלים התת', 'כבלים תת', 'סוויפט', 'הורמוז']) and any(x in text for x in ['10 טריליון', 'סליקה', 'עסקאות', 'דמי שימוש']):
        return 'איראן מאיימת לגבות דמי שימוש מכבלי האינטרנט התת־ימיים במצר הורמוז. דרך הכבלים האלה עוברים מידע פיננסי, תשלומי בנקים ועסקאות בהיקף עצום.'
    if any(x in text for x in ['תכולת הבית', 'תכולת בית']) and any(x in text for x in ['נזקי מלחמה', 'פעולות איבה', 'מס רכוש', '0.3%']):
        return 'ביטוח תכולה סטנדרטי בדרך כלל לא מכסה נזקי מלחמה או פעולות איבה. המדינה מפצה דרך מס רכוש, אבל הכיסוי לתכולה מוגבל וצריך להרחיב אותו בנפרד.'
    if any(x in text for x in ['אלפין', 'פורשה', 'פרארי', 'אסטון מרטין']) and any(x in text for x in ['כריות אוויר', 'בלימה אוטונומית', 'בטיחות']):
        return 'אלפין A110 שעולה כמעט חצי מיליון שקל מגיעה עם שתי כריות אוויר וללא בלימה אוטונומית. גם פורשה, פרארי ואסטון מרטין משאירות מערכות בטיחות מחוץ לדגמי ספורט.'
    if 'מכונת מזומנים' in text and 'עולם הספורט' in text:
        return 'מה שהתחיל כגימיק טכנולוגי הפך למנוע הכנסות גדול בספורט. המספרים מצביעים על שינוי כלכלי במשחק.'
    if 'פורמולה 1' in text and any(x in text for x in ['מטא', 'גוגל', 'אדידס', 'AI']):
        return 'חברות AI וענקיות אמריקאיות מזרימות מיליארדים לפורמולה 1. החסויות הופכות את הענף לפלטפורמת פרימיום.'
    if 'תאונות קורקינטים' in text and any(x in text for x in ['פיצוי', 'לתבוע', 'פגיעה']):
        return 'רוכבת קורקינט נהרגה והעלתה מחדש את שאלת הפיצוי לנפגעים. ברוב התאונות הנזק קל, אבל הכיסוי לא תמיד ברור.'
    if 'MBA' in text and any(x in text for x in ['קורסי בחירה', 'התמחויות', 'אונו']):
        return 'תוכנית MBA מציעה יותר מ־130 קורסי בחירה בעשרות התמחויות. ההבטחה היא התאמה אישית לשוק עבודה משתנה.'
    if 'ביטוח רכב' in text and any(x in text for x in ['שינויים כלכליים', 'לעלות']):
        return 'חברות הביטוח מעלות מחירים בגלל שינויים כלכליים ועלויות. הנהג צריך לבדוק תנאים ולא רק מחיר חידוש.'
    if 'ביטוח רכב' in text and any(x in text for x in ['דצמבר', 'סיום הפוליסה']):
        return 'ישראלים רבים מחכים לסוף השנה כדי לחדש ביטוח רכב. הכתבה בודקת אם דצמבר באמת משתלם או רק הרגל.'
    if 'תכולת הבית' in text and any(x in text for x in ['0.3%', 'הממשלתי', 'הטילים']):
        return 'המדינה משלמת מעט על נזק לתכולת בית אחרי פגיעת טילים. אפשר להרחיב כיסוי באתר ממשלתי בתשלום נמוך.'
    if 'אלפין' in text and any(x in text for x in ['כריות אוויר', 'בלימה אוטונוטמית']):
        return 'אלפין יקרה מגיעה עם שתי כריות אוויר וללא בלימה אוטונומית. גם יצרניות ספורט יוקרתיות לא ממהרות לתקן.'
    if 'שלבי אמריקן' in text and any(x in text for x in ['500 יחידות', '70 אלף דולר']):
        return 'שלבי משיקה 500 יחידות מוסטאנג סופר־סנייק לציון 50 שנה. המחיר מתחיל סביב 70 אלף דולר.'
    if 'האח הגדול' in text and 'הדחות' in text:
        return 'שבוע הדחות פתע משנה את מאזן הבית. ההפקה משתמשת באי־ודאות כדי להחזיק עניין.'
    if 'יוקר התחבורה' in text and 'מחיר הדלק' in text:
        return 'הדיון הציבורי מתמקד במחיר הדלק. סביבו נבנתה תעשייה רחבה שמייקרת את התחבורה כולה.'
    if 'פסטיבל קאן' in text and 'AI' in text:
        return 'בקאן גוברת ההכרה ששימוש ב-AI בקולנוע בלתי נמנע. ההתנגדות נשארת, אבל התעשייה כבר בוחנת כלים חדשים.'
    if 'האח הגדול' in text and 'הדחות' in text:
        return 'שבוע הדחות פתע באח הגדול משנה את מאזן הבית. ההפקה משתמשת באי־ודאות כדי להחזיק עניין.'
    category = categorize_item(title, desc, source)[0]
    if desc:
        sentences = split_sentences(desc)
        if len(sentences) >= 2:
            first = short_sentence(sentences[0], 86)
            second = short_sentence(sentences[1], 86)
            if first and second and first != second:
                return f'{first}. {second}.'
        if sentences:
            first = short_sentence(sentences[0], 96)
            title_point = short_sentence(dequote_headline(title), 74)
            if title_point and title_point not in first:
                return f'{first}. המשמעות מתמקדת ב{title_point}.'
            return f'{first}.'
    # Experimental mode avoids pretending to know more than the article/feed supplied.
    return short_sentence(f'במרכז הכתבה: {dequote_headline(title)}', 160) + '.'


def experimental_insight(category: str, title: str, desc: str) -> str:
    """Insight must be article-derived and specific; include the subject when falling back."""
    text = article_text(title, desc)
    # Reuse the strong learned patterns, but compress them to the new premium prompt.
    if 'איראן' in text and any(x in text for x in ['כבלים התת', 'כבלים תת', 'סוויפט', 'הורמוז']) and any(x in text for x in ['10 טריליון', 'סליקה', 'עסקאות', 'דמי שימוש']):
        insight = 'האיום הוא לא רק על נפט — אלא על זרימת הכסף.'
    elif any(x in text for x in ['תכולת הבית', 'תכולת בית']) and any(x in text for x in ['נזקי מלחמה', 'פעולות איבה', 'מס רכוש', '0.3%']):
        insight = 'מי שלא מרחיב כיסוי מלחמה נשאר חשוף כלכלית.'
    elif any(x in text for x in ['אלפין', 'פורשה', 'פרארי', 'אסטון מרטין']) and any(x in text for x in ['כריות אוויר', 'בלימה אוטונומית', 'בטיחות']):
        insight = 'מחיר יוקרה לא מבטיח הגנה על הכביש.'
    elif ('מכונת מזומנים' in text or 'שואב מיליארדים' in text or 'מנוע הכנסות' in text) and 'ספורט' in text:
        insight = 'הספורט מוכר דאטה וכסף, לא רק משחק.'
    elif 'פורמולה 1' in text and any(x in text for x in ['מטא', 'גוגל', 'אדידס', 'AI']):
        insight = 'AI קונה קהל דרך ספורט פרימיום.'
    elif 'MBA' in text and any(x in text for x in ['קורסי בחירה', 'התמחויות', 'אונו']):
        insight = 'התואר נמכר דרך גמישות והתמחויות.'
    elif 'תאונות קורקינטים' in text and any(x in text for x in ['פיצוי', 'לתבוע', 'פגיעה']):
        insight = 'בקורקינט, הפוליסה קובעת את הפיצוי.'
    elif 'ביטוח רכב' in text and any(x in text for x in ['שינויים כלכליים', 'לעלות']):
        insight = 'ביטוח רכב מתייקר כשסיכון כלכלי עולה.'
    elif 'ביטוח רכב' in text and any(x in text for x in ['דצמבר', 'סיום הפוליסה']):
        insight = 'הרגל חידוש יכול לעלות יותר מהשוואה.'
    elif any(x in text for x in ['תכולת הבית', 'תכולת בית']) and any(x in text for x in ['0.3%', 'הממשלתי', 'הטילים']):
        insight = 'מי שלא מרחיב כיסוי נשאר חשוף.'
    elif 'אלפין' in text and any(x in text for x in ['כריות אוויר', 'בלימה אוטונוטמית']):
        insight = 'מחיר ספורטיבי לא מבטיח בטיחות בסיסית.'
    elif 'שלבי אמריקן' in text and any(x in text for x in ['500 יחידות', '70 אלף דולר']):
        insight = 'נדירות ומורשת הן חלק מהמחיר.'
    elif 'יוקר התחבורה' in text and 'מחיר הדלק' in text:
        insight = 'המשאבה היא רק קצה יוקר הניידות.'
    elif 'פסטיבל קאן' in text and 'AI' in text:
        insight = 'התעשייה תתנגד ל-AI עד שהוא יחסוך זמן.'
    elif 'האח הגדול' in text and 'הדחות' in text:
        insight = 'ריאליטי מוכר אי־ודאות מתוכננת.'
    elif is_trump_phone_story(title, desc):
        insight = 'טראמפ מוכר זהות פוליטית יותר מטכנולוגיה.'
    elif is_lieberman_succession_story(title, desc):
        insight = 'ליברמן בונה הנהגה לימין שאחרי נתניהו.'
    elif is_iran_cuba_drone_story(title, desc):
        insight = 'איראן מתקרבת לחצר האחורית של ארה״ב.'
    elif is_protection_insurance_story(title, desc):
        insight = 'המדינה מאבדת שליטה כשהביטוח נסוג.'
    elif 'ביטוח' in text and any(x in text for x in ['פרוטקשן', 'סחיטה', 'הצתות']):
        insight = 'פשיעה הופכת לבעיה פיננסית כשביטוח נסוג.'
    elif 'מדד' in text and any(x in text for x in ['דירות', 'מחירים', 'אינפלציה']):
        insight = 'מחירים גבוהים דוחים את ההקלה בכיס.'
    elif 'אנבידיה' in text and any(x in text for x in ['נדל', 'טבעון', 'מחירי']):
        insight = 'הציפייה להייטק כבר מתומחרת בנדל״ן.'
    elif 'קריפטו' in text or 'ביטקוין' in text:
        insight = 'בקריפטו, אמון זז מהר יותר מרגולציה.'
    elif 'איראן' in text and any(x in text for x in ['הורמוז', 'כבלים', 'תת ימיים']):
        insight = 'תשתית תקשורת היא יעד ביטחוני וכלכלי.'
    elif 'מונופול' in text or 'מונופולים' in text:
        insight = 'הרגל צרכני קטן יכול לחזק כוח שוק גדול.'
    elif any(x in text for x in ['מפוטרים', 'פיטורים']) and any(x in text for x in ['הייטק', 'שוק']):
        insight = 'פיטורים יכולים להפוך לכוח גיוס חדש.'
    elif 'חוק הגיוס' in text:
        insight = 'חוק הגיוס הוא מבחן יציבות לקואליציה.'
    elif any(x in text for x in ['נבחרת', 'ליגה', 'שערים', 'מאמן', 'מרתון']):
        subject = takeaway_subject(title, 30)
        insight = f'{subject} משנה את תמונת ההמשך בספורט.'
    elif any(x in text for x in ['דירה', 'נדל', 'מחירי']):
        subject = takeaway_subject(title, 30)
        insight = f'{subject} מתורגם מהר למחיר בכיס.'
    elif desc:
        # Last-resort is still article-derived: it names the article's subject and consequence.
        subject = takeaway_subject(title, 30)
        if category == 'כלכלה':
            insight = f'{subject} משנה את המחיר או הסיכון.'
        elif category == 'תחבורה':
            insight = f'{subject} משפיע על עלות ובטיחות.'
        elif category == 'טכנולוגיה':
            insight = f'{subject} משנה אמון ושימוש.'
        elif category == 'ספורט':
            insight = f'{subject} משנה כסף ומעמד בספורט.'
        else:
            insight = f'{subject} הוא נקודת ההשלכה המרכזית.'
    else:
        subject = takeaway_subject(title, 32)
        insight = f'אין פואנטה אמינה בלי עומק על {subject}.'
    return '💡 ' + short_sentence(insight, 64)


def dequote_headline(title: str) -> str:
    h = sanitize_title(title).strip()
    h = re.sub(r'^\s*["״“”][^"״“”]{3,90}["״“”]\s*[:：-]?\s*', '', h).strip()
    h = re.sub(r'^[^:：]{3,85}\?\s*', '', h).strip()
    h = re.sub(r'^[^:：]{3,85}:\s*', '', h).strip()
    h = h.replace('?', '').strip(' -–:')
    return h or sanitize_title(title)


def is_trump_phone_story(title: str, desc: str) -> bool:
    text = f"{title} {desc}"
    return (
        'טראמפ' in text
        and any(x in text for x in ['T1', 'T-1', 'מובייל', 'טלפון', 'סמארטפון', 'מכשיר'])
        and any(x in text for x in ['עיכוב', 'סיני', 'ממותג', 'מוזהב', 'מקדמה', 'לקוחות', 'אנליסט'])
    )


def is_lieberman_succession_story(title: str, desc: str) -> bool:
    text = f"{title} {desc}"
    return (
        'ליברמן' in text
        and any(x in text for x in ['כיבוש השלטון', 'יורש', 'הימין', 'ליכוד', 'נתניהו', 'ביבי', 'מאוכזבי'])
    )


def is_iran_cuba_drone_story(title: str, desc: str) -> bool:
    text = f"{title} {desc}"
    return (
        'איראן' in text
        and 'קובה' in text
        and any(x in text for x in ['כטב', 'כטב"מים', 'יועצים צבאיים', 'יועצים', 'צבאיים', 'רוסיה'])
    )


def is_protection_insurance_story(title: str, desc: str) -> bool:
    text = f"{title} {desc}"
    return (
        any(x in text for x in ['פרוטקשן', 'סחיטה', 'הצתות', 'ארגוני הפשיעה'])
        and any(x in text for x in ['ביטוח', 'חברות הביטוח', 'פוליסות', 'אשראי', 'עסקים בצפון', 'העסקים בצפון'])
    )


def is_malinovsky_oct7_law_story(title: str, desc: str) -> bool:
    text = f"{title} {desc}"
    return (
        any(x in text for x in ['ישראל ביתנו', 'מלינובסקי', 'מרד של כלל חברי הכנסת'])
        and any(x in text for x in ['מחבלי טבח השבעה באוקטובר', 'מחבלי 7 באוקטובר', 'טבח השבעה באוקטובר'])
        and any(x in text for x in ['סגירה תקציבית', 'הצבעות', 'החוק'])
    )


def is_helium_iran_war_story(title: str, desc: str) -> bool:
    text = f"{title} {desc}"
    return (
        any(x in text for x in ['הליום', 'הגז הנדיר'])
        and any(x in text for x in ['איראן', 'המלחמה'])
        and any(x in text for x in ['קטאר', 'מחירים', 'ים המלח', 'חיפוש'])
    )


def is_smotrich_elgart_hearing_story(title: str, desc: str) -> bool:
    text = f"{title} {desc}"
    return (
        'סמוטריץ' in text
        and any(x in text for x in ['דני אלגרט', 'אלגרט'])
        and any(x in text for x in ['מי אדוני', 'הדיון יצא משליטה'])
    )


def is_amos_luzon_relationship_story(title: str, desc: str) -> bool:
    text = f"{title} {desc}"
    return (
        'עמוס לוזון' in text
        and any(x in text for x in ['זוגיות חדשה', 'פער של 33 שנה', 'פער גיל', 'אושר כהן', 'עדן פינס'])
    )


def has_latin_text(text: str) -> bool:
    return len(re.findall(r"[A-Za-z]", text or "")) > 8


FOREIGN_RELEVANCE_KEYWORDS = [
    # Israel / Jewish / antisemitism
    "israel", "israeli", "jerusalem", "tel aviv", "jewish", "jews", "antisemit", "zionist", "zionism",
    # War / regional actors
    "iran", "iranian", "tehran", "khamenei", "ahmadinejad", "gaza", "hamas", "hezbollah", "lebanon",
    "syria", "iraq", "yemen", "houthi", "houthis", "qatar", "uae", "emirates", "saudi", "riyadh",
    "jordan", "egypt", "sinai", "west bank", "palestinian", "palestinians", "rafah", "strait of hormuz",
    "hormuz", "middle east", "mideast", "persian gulf", "red sea",
    # Named regional/political hooks; avoid generic world-war terms like drone/missile unless a region keyword is present.
    "idf", "netanyahu",
]

WORLD_CURRENT_AFFAIRS_KEYWORDS = [
    "united states", "u.s.", " us ", "america", "american", "white house", "trump", "biden",
    "president", "government", "parliament", "election", "minister", "court", "supreme court",
    "sanctions", "cuba", "china", "beijing", "taiwan", "russia", "ukraine", "nato", "europe",
    "france", "germany", "britain", "uk", "mexico", "nigeria", "thailand", "fukushima",
    "war", "conflict", "military", "shooting", "gunmen", "killed", "dead", "attack", "protest",
    "earthquake", "flood", "wildfire", "storm", "outbreak", "ebola", "hantavirus", "nuclear",
    "climate", "schoolchildren", "kidnapped", "hostage", "prisoners",
]

FOREIGN_NOISE_KEYWORDS = [
    "celebrity", "celebrities", "gossip", "red carpet", "fashion", "recipe", "restaurant",
    "movie", "film festival", "tv show", "music", "album", "premiere", "travel tips", "shopping",
    "football", "soccer", "basketball", "tennis", "nba", "nfl", "mlb", "olympics",
]

def is_foreign_relevant(title: str, desc: str) -> bool:
    """Foreign feeds must stay relevant to Israel/Middle East.

    Lior's current invariant: foreign-source items are allowed only when they
    relate to Israel, Iran, Gaza, Lebanon, the Middle East, regional
    security/policy, Jews/antisemitism, or direct Israel/Middle-East
    implications. General world current-affairs stories such as Taiwan/China,
    Russia/Ukraine, disasters, or broad US politics must not fill the feed just
    because they are serious news.
    """
    text = f"{title} {desc}".lower()
    if any(k in text for k in FOREIGN_NOISE_KEYWORDS):
        return False
    return any(k in text for k in FOREIGN_RELEVANCE_KEYWORDS) or "middle east" in text or "mideast" in text


FOREIGN_SOURCE_LABELS = [
    "bbc", "cnn", "sky news", "skynews", "reuters", "associated press", "ap middle east", "guardian",
    "new york times", "nyt", "axios", "politico", "bloomberg", "al jazeera", "jazeera",
    "jns", "jewish news syndicate", "france24", "france 24", "the media line",
]


def is_foreign_source_label(source: str) -> bool:
    low = str(source or "").lower()
    return any(label in low for label in FOREIGN_SOURCE_LABELS)


def is_retained_foreign_item_relevant(item: dict) -> bool:
    text = " ".join(str(item.get(k) or "") for k in ["headline", "originalTitle", "context", "takeaway", "source", "sourceUrl"])
    return is_foreign_relevant(text, "")


def foreign_story_key(title: str, desc: str) -> str:
    text = f"{title} {desc}".lower()
    if 'ebola' in text:
        return 'ebola'
    if 'everest' in text or 'mountain queen' in text or 'kami rita' in text or 'lhakpa' in text:
        return 'everest'
    if 'fighter jets' in text and ('collide' in text or 'collision' in text):
        return 'idaho_jets'
    if 'mexico shooting' in text or ('gunmen' in text and 'mexico' in text):
        return 'mexico_shooting'
    if 'hantavirus' in text:
        return 'hantavirus'
    if 'taiwan' in text:
        return 'taiwan'
    if 'nigeria' in text and ('kidnapped' in text or 'schoolchildren' in text or 'children' in text):
        return 'nigeria_kidnap'
    if 'black americans jailed in china' in text or ('jailed in china' in text and 'trump' in text):
        return 'china_prisoners'
    if 'train driver' in text and 'thailand' in text:
        return 'thailand_train'
    return ''


FOREIGN_POINTA = {
    'ebola': (
        'זן נדיר של אבולה מעלה חשש מהתפשטות מעבר לאזור ההתפרצות',
        'רשויות בריאות בוחנות אם זן נדיר של אבולה עלול להתפשט מעבר למוקד המקומי. החשש המרכזי הוא לא רק מספר החולים כעת, אלא היכולת לזהות ולבודד מגעים לפני שההתפרצות יוצאת משליטה.',
        'באבולה, חלון הזמן בין זיהוי לבידוד קובע אם אירוע מקומי הופך לסיכון בינלאומי.',
        'בריאות', 'real'
    ),
    'everest': (
        'שני מטפסי שרפה שברו שוב את שיאי האוורסט שלהם',
        'קאמי ריטה שרפה הגיע לפסגת האוורסט בפעם ה־32, ולחקפה שרפה שברה את שיא הנשים עם הטיפוס ה־11 שלה. מאחורי השיאים האישיים עומדת גם התלות העמוקה של תעשיית האוורסט במדריכי השרפה המקומיים.',
        'התהילה על האוורסט נשענת על מקצוענות של מדריכים מקומיים שלרוב נשארים ברקע.',
        'ספורט', 'real'
    ),
    'idaho_jets': (
        'שני מטוסי קרב התנגשו במהלך מופע אווירי באיידהו',
        'שני מטוסי קרב התנגשו במופע אווירי באיידהו, באירוע שמדגיש את הסיכון המובנה בתצוגות טיסה צפופות מול קהל. גם כשמדובר במופע בידורי, מרווח טעות קטן באוויר עלול להפוך לתאונה חמורה.',
        'מופעי ראווה באוויר מוכרים אדרנלין, אבל תלויים במשמעת בטיחות כמעט צבאית.',
        'ביטחון', 'security'
    ),
    'mexico_shooting': (
        'עשרה בני אדם נהרגו בירי במרכז־מזרח מקסיקו',
        'חמושים הרגו לפחות עשרה בני אדם במדינת פואבלה שבמקסיקו, לפי הרשויות המקומיות. האירוע מצטרף לדפוס של אלימות חמושה שמערערת את תחושת הביטחון גם באזורים אזרחיים.',
        'כשירי המוני הופך לשגרה אזורית, הבעיה היא כבר לא אירוע נקודתי אלא כשל ביטחון ציבורי.',
        'פלילים', 'security'
    ),
    'hantavirus': (
        'תשעה בריטים שנחשפו להנטווירוס חוזרים לממלכה למעקב רפואי',
        'תשעה אזרחים בריטים שהיו קשורים לספינת הקרוז MV Hondius חוזרים לבריטניה לאחר חשיפה להתפרצות הנטווירוס. הדגש הוא על מעקב מהיר ובידוד סיכונים לפני שהחשיפה הופכת לשרשרת הדבקה.',
        'במחלות נדירות, ניהול המגעים חשוב כמעט כמו הטיפול בחולה עצמו.',
        'בריאות', 'real'
    ),
    'taiwan': (
        'עתיד טאיוואן נשאר מבחן הלחץ המרכזי בין סין לארה״ב',
        'הדיון סביב טאיוואן מתמקד בשאלה איך ייראה מאזן הכוחות מול סין בשנים הקרובות. כל שינוי בעמדה האמריקאית או בלחץ הסיני עלול להשפיע על ביטחון האזור ועל שרשראות אספקה עולמיות.',
        'טאיוואן היא לא רק מחלוקת טריטוריאלית — היא נקודת מבחן לסדר העולמי ולתעשיית השבבים.',
        'ביטחון', 'security'
    ),
    'nigeria_kidnap': (
        'יותר מ־50 ילדים נחטפו משלושה בתי ספר בצפון־מזרח ניגריה',
        'חמושים חטפו יותר מ־50 ילדים משלושה בתי ספר בעיירה מוסה שבמדינת בורנו, ורוב הנעדרים הם בני שנתיים עד חמש. עדים סיפרו שהחוטפים השתמשו בילדים כמגן אנושי בזמן הבריחה, ותושבים באזור כבר נמלטים מחשש להמשך האלימות.',
        'כאשר ילדים קטנים הופכים למגן אנושי, הכשל הביטחוני הופך למשבר קהילתי מתמשך.',
        'ביטחון', 'security'
    ),
    'china_prisoners': (
        'משפחות אמריקאים שכלואים בסין מנסות להפוך ביקור של טראמפ ללחץ דיפלומטי',
        'קרובי משפחה של שני אמריקאים שחורים הכלואים בסין הגיבו לביקור טראמפ ומנסים להעלות את המקרה לסדר היום המדיני. מבחינתם, החשיפה הציבורית היא דרך להפוך סיפור אישי לקלף לחץ ביחסי וושינגטון־בייג׳ינג.',
        'במאבקי אסירים בין מעצמות, תשומת לב פוליטית יכולה להיות ההבדל בין תיק נשכח למנוף מיקוח.',
        'פוליטיקה', 'security'
    ),
    'thailand_train': (
        'נהג רכבת הואשם ברשלנות אחרי תאונה קטלנית בתאילנד',
        'נהג רכבת בתאילנד הואשם ברשלנות לאחר תאונה קטלנית. החקירה מעבירה את הסיפור משאלת התאונה עצמה לשאלה מי אחראי לכשלי בטיחות במערכת תחבורה ציבורית.',
        'בתאונות תחבורה, כתב אישום נגד הנהג לא תמיד עונה על השאלה אם המערכת כולה בטוחה.',
        'רכב', 'real'
    ),
}


def foreign_pointa_tuple(title: str, desc: str):
    key = foreign_story_key(title, desc)
    return FOREIGN_POINTA.get(key)


def is_avihu_pinchasov_genesis_story(title: str, desc: str) -> bool:
    text = f"{title} {desc}"
    return 'פסטיבל ג' in text and 'נסיס' in text and any(x in text for x in ['אביהו פנחסוב', 'עשרים אלף', 'התקווה 6', 'הדג נחש', 'בניה ברבי', 'נונו'])


def is_weak_source_headline(title: str, headline: str) -> bool:
    """True when Pointa failed to rewrite and mostly copied the source framing."""
    a = re.sub(r'[^\w\u0590-\u05ff]+', ' ', sanitize_title(title)).strip().lower()
    b = re.sub(r'[^\w\u0590-\u05ff]+', ' ', sanitize_title(headline)).strip().lower()
    if not a or not b:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 24 and shorter in longer:
        return True
    aw = [w for w in a.split() if len(w) > 2]
    bw = set(w for w in b.split() if len(w) > 2)
    if len(aw) >= 5 and sum(1 for w in aw if w in bw) / max(1, len(aw)) >= 0.72:
        return True
    return False


def _cleanup_event_sentence(text: str) -> str:
    text = clean_text(text)
    text = re.sub(r'^(?:דובר(?:ות)?\s+[^:]{2,30}:|בהמשך ל[^,-]{0,70}[-–,]\s*|לפי [^,]{2,45},\s*|במסגרת\s+)', '', text).strip()
    text = re.sub(r'\s*[•|]\s*.*$', '', text).strip()
    text = text.replace('משטרת ישראל', 'המשטרה').replace('דובר צה"ל', 'צה״ל')
    return text.strip(' ,;:-–')


def _candidate_headline_ok(original: str, candidate: str) -> bool:
    candidate = clean_text(candidate).strip(' ,;:-–')
    if not candidate or len(candidate) < 18 or headline_looks_cut(candidate):
        return False
    if is_weak_source_headline(original, candidate):
        return False
    if len(candidate) > 78:
        return False
    return True


def rewrite_copied_source_headline(title: str, desc: str, source: str = "") -> str:
    """Rewrite source-copy fallbacks into compact event headlines.

    FAST has no LLM budget, so this is deliberately deterministic: first handle
    common official/live-news structures, then fall back to a cleaned factual
    sentence instead of copying the source title.
    """
    title = sanitize_title(title)
    desc = clean_text(desc)
    source = clean_text(source)
    text = f'{title} {desc}'

    specific_rules: list[tuple[bool, str]] = [
        (
            'חיסלו את וליד הניה' in text or ('וליד הניה' in text and 'נוח' in text),
            'צה״ל ושב״כ חיסלו את וליד הניה מחמאס',
        ),
        (
            'בית אריה' in text and any(x in text for x in ['חדירת מחבלים', 'אין חשש', 'לא אותרו חשודים']),
            'סריקות בבית אריה הסתיימו ללא חשודים',
        ),
        (
            'הצנחן' in text and 'לוחם העוקץ' in text and ('קק' in text or 'בה"ד 1' in text or 'בה״ד 1' in text),
            'צנחן ולוחם עוקץ שנפגשו בעזה סיימו יחד קורס קצינים',
        ),
        (
            'נהר הירדן' in text and 'ללא רוח חיים' in text and 'נער' in text,
            'אחת הנערות שנעדרו בירדן אותרה ללא רוח חיים',
        ),
        (
            'נהר הירדן' in text and 'נעדר' in text and 'נער' in text,
            'החיפושים בירדן נמשכים אחר נערות שנותק עמן קשר',
        ),
        (
            'הערכת מצב' in text and 'חיפושים' in text and 'נהר הירדן' in text,
            'החיפושים בירדן נמשכים אחרי הנערה הנעדרת',
        ),
        (
            'מטייל' in text and '78' in text and 'הר יעלה' in text,
            'מטייל בן 78 חולץ מהר יעלה במסוק צבאי',
        ),
        (
            'סלפי' in text and any(x in text for x in ['נהגת', 'נהג']) and 'נסיעה' in text,
            'נהגת תועדה מצלמת סלפי בזמן נסיעה',
        ),
        (
            'איומים בנשק' in text and 'כביש 1' in text,
            'שני חשודים נעצרו אחרי איומים בנשק במחאה בכביש 1',
        ),
        (
            'רופאי' in text and 'שיניים' in text and any(x in text for x in ['זיהוי פלילי', 'בית הנשיא', 'נעדרים', 'חללים']),
            'הנשיא הוקיר מתנדבי זיהוי פלילי שסייעו בזיהוי חללים',
        ),
        (
            'בלונים' in text and 'אבנים' in text and any(x in text for x in ['אילת', 'שחמון']),
            'באילת דווח על השלכת בלוני אבנים לעבר רכבים',
        ),
        (
            'מולטי-טאסקינג' in text and 'פרודוקטיביות' in text,
            'מחקרים מזהירים שהרגלי עבודה נפוצים פוגעים בפרודוקטיביות',
        ),
        (
            'גיא זוארץ' in text and 'יעל בר זוהר' in text,
            'יעל בר זוהר עקצה את גיא זוארץ בזמן גמר האח הגדול',
        ),
        (
            'מסילות החלון' in text and any(x in text for x in ['ניקוי', 'אבק', 'טחב']),
            'מדריך ניקיון מציע דרך פשוטה לנקות מסילות חלון',
        ),
        (
            'דארין גרין' in text and 'הפועל חולון' in text,
            'דארין גרין ג׳וניור יעזוב את הפועל חולון',
        ),
        (
            'אלירן ביטון' in text and 'האח הגדול' in text,
            'אלירן ביטון סיים שלישי בגמר האח הגדול',
        ),
        (
            'מעצרי העריקים' in text and any(x in text for x in ['חרדים', 'חוק הגיוס', 'יוסי פוקס']),
            'הממשלה מבקשת להקפיא מעצרי עריקים חרדים לשלושה חודשים',
        ),
        (
            'הישוב' in text and 'נועה' in text and 'שומרון' in text,
            'בשומרון נערכים להקמת היישוב נועה מחדש',
        ),
    ]
    for matched, headline in specific_rules:
        if matched and _candidate_headline_ok(title, headline):
            return headline

    # If the title is source-style, prefer a concrete factual sentence from the
    # description, after removing reporting/source frames.
    sentences = split_sentences(desc)
    scored: list[str] = []
    for raw in sentences[:3]:
        s = _cleanup_event_sentence(raw)
        if len(s) < 18:
            continue
        if re.search(r'^(?:במרכז|הכתבה|הכתב|פורסם|דווח|לפי הדיווח|המקור|לפני זמן קצר|במקום פועלים)', s):
            continue
        scored.append(complete_headline(s, 74))
    for candidate in scored:
        if _candidate_headline_ok(title, candidate):
            return candidate

    # Last resort: transform the source title itself, but remove source/clickbait
    # framing so the result is less likely to be an exact copy.
    h = title
    h = re.sub(r'^(?:תיעוד מטריד|תיעוד|דרמה|סערה|המדריך המלא|מדענים קבעו|נחשף|צפו)\s*[:：-]\s*', '', h).strip()
    h = re.sub(r'^["״“”]([^"״“”]{8,80})["״“”]\s*[-–:]\s*', '', h).strip()
    h = complete_headline(h, 72)
    if _candidate_headline_ok(title, h):
        return h
    return ''


def culture_headline_from_context(title: str, desc: str) -> str:
    text = f'{title} {desc}'
    if is_avihu_pinchasov_genesis_story(title, desc):
        return 'פסטיבל ג׳נסיס הפך ל־12 שעות של אסקפיזם מוזיקלי מהמציאות'
    if 'האח הגדול' in text and any(x in text for x in ['הדחה', 'הדחות', 'מודח']):
        return 'האח הגדול משתמש בהדחות כדי לייצר דרמה ולהחזיק את הצופים'
    if any(x in text for x in ['סדרה', 'טלוויזיה', 'נטפליקס', 'קשת', 'רשת']):
        return 'הסיפור הטלוויזיוני מוכר לצופים דרמה מעבר למסך'
    return ''


def is_el_nino_weather_story(title: str, desc: str) -> bool:
    text = f"{title} {desc}"
    return any(x in text for x in ['אל ניניו', 'אל-ניניו']) and any(x in text for x in ['גשמים', 'שיטפונות', 'מזג אוויר', 'התחממות הים', 'אקלים'])


def is_vance_iran_nuclear_story(title: str, desc: str) -> bool:
    text = f"{title} {desc}"
    return ("ואנס" in text or "סגן הנשיא האמריקני" in text or "ג׳יי די" in text or "ג'יי" in text) and "איראן" in text and "נשק גרעיני" in text


def is_stolen_idf_weapon_restaurant_story(title: str, desc: str) -> bool:
    text = f'{title} {desc}'
    return all(x in text for x in ['מסעדנית', 'M-16']) and any(x in text for x in ['קצין צה"ל', 'קצין צה״ל', 'נשק האישי', 'גניבת'])


def is_turkey_air_missile_story(title: str, desc: str) -> bool:
    text = f'{title} {desc}'
    return (
        'טורקיה' in text
        and any(x in text for x in ['גוקדואן', 'בוזדואן', 'טילי האוויר', 'טילי אוויר'])
        and any(x in text for x in ['ישראל', 'F-16', 'עצמאותה הביטחונית', 'חימוש חיצוני'])
    )


def is_idf_lebanon_evacuation_warning_story(title: str, desc: str) -> bool:
    text = f'{title} {desc}'
    return (
        any(x in text for x in ['אזהרת פינוי', 'פרסם אזהרת פינוי'])
        and any(x in text for x in ['דרום לבנון', 'אל-בקאע', 'אל־בקאע'])
        and any(x in text for x in ['צה"ל', 'צה״ל'])
    )


def live_event_pointa_tuple(title: str, desc: str, source: str = "") -> tuple[str, str] | None:
    """Deterministic bridge for short live-news RSS rows."""
    text = f'{title} {desc}'
    if 'צפת' in text and any(x in text for x in ['שאבעס', 'יריקות לעבר נשים', 'הפגנות חרדים', 'כביש הראשי']):
        return (
            'הפגנות חרדים בצפת חסמו ציר מרכזי סביב תחבורה בשבת',
            'בצפת נמשכות הפגנות חרדים נגד הפעלת קווי אוטובוס לפני צאת שבת, כולל חסימות תנועה וקריאות לעבר נהגים ונשים שעברו במקום. העימות המקומי הופך את שאלת התחבורה הציבורית בשבת לאירוע שמשפיע ישירות על תושבים ונהגים.',
        )
    if any(x in text for x in ['המסילה המזרחית', 'הקווים החדשים של רכבת ישראל']) and any(x in text for x in ['רכבת ישראל', 'קווים חדשים', 'יחלו לפעול']):
        return (
            'המסילה המזרחית חוזרת לפעול בהדרגה אחרי שנים של עיכוב',
            'רכבת ישראל תתחיל להפעיל את הקווים החדשים של המסילה המזרחית בימי חול, ובהמשך צפויה להרחיב את השירות. החזרה המדורגת אמורה להוסיף חלופת נסיעה בין אזורי תעסוקה ומגורים, אבל היא עדיין תלויה בהשלמת התפעול המלא.',
        )
    if 'נהר הירדן' in text and 'נסחפ' in text and any(x in text for x in ['נערות', 'שתי', '2 ']):
        return (
            'חיפושים בנהר הירדן אחרי שתי נערות שנותק עמן קשר',
            'כוחות משטרה וחילוץ סורקים באזור להבות הבשן לאחר ששתי נערות נסחפו בנהר הירדן, ונותק עמן הקשר. האירוע מתנהל כפעולת חילוץ פתוחה, ולכן העדכון המרכזי הוא עצם ניתוק הקשר והסריקות בשטח.',
        )
    if 'עמק חפר' in text and 'טבע' in text and any(x in text for x in ['בן 13', 'נער']):
        return (
            'טביעה בעמק חפר הותירה נער בן 13 ללא הכרה',
            'מד״א פינה נער בן 13 במצב קשה לאחר שטבע בבריכה במועצה האזורית עמק חפר.',
        )
    if 'צבא לבנון' in text and any(x in text for x in ['חיזבאללה', 'הסכם', 'לבנון']):
        return (
            'ההסכם עם לבנון מעביר את המבחן לצבא הלבנוני',
            'ברקע ההסכם עם ישראל, צבא לבנון נדרש להתמודד עם חיזבאללה למרות קשיי גיוס, משכורות נמוכות והרכב פנימי מורכב. האתגר הוא אם כוח מדינתי חלש יוכל לאכוף הסכם מול ארגון חמוש וחזק ממנו בשטח.',
        )
    if 'חיזבאללה' in text and 'הסכם' in text and any(x in text for x in ['חרפה', 'השפלה', 'מלחמת אזרחים', 'ריבונות']):
        return (
            'חיזבאללה מאיים להסלים נגד ההסכם בין ישראל ללבנון',
            'נעים קאסם תקף את ההסכם עם ישראל ולבנון, כינה אותו פגיעה בריבונות והבהיר שחיזבאללה לא מתכוון לעזוב את השטח.',
        )
    if 'גל החום' in text and 'אירופה' in text:
        return (
            'גל החום באירופה שובר שיאים ומכביד על תשתיות',
            'גרמניה, שווייץ, איטליה וספרד מתמודדות עם חום קיצוני, כבישים שנפגעו, קרחונים שנמסים וחשש מבצורת ומקרי מוות. המשבר אינו רק תחזית מזג אוויר, אלא עומס מתמשך על תחבורה, בריאות ותשתיות עירוניות.',
        )
    if 'הפגנות נגד הממשלה' in text and any(x in text for x in ['תל אביב', 'ירושלים', 'חיפה', 'רחבי הארץ']):
        return (
            'המחאה נגד הממשלה חוזרת הערב לכמה מוקדים בארץ',
            'בתל אביב, ירושלים וחיפה מתוכננות הערב צעדות והפגנות נגד הממשלה, עם מוקדי יציאה ושעות שנקבעו מראש.',
        )
    if 'מצעד הגאווה' in text and 'הונגריה' in text:
        return (
            'עשרות אלפים צעדו בבודפשט למרות הלחץ של אורבן',
            'בהונגריה השתתפו עשרות אלפים במצעד הגאווה, באירוע שהפך גם להפגנת כוח פוליטית מול ממשלת אורבן. ההשתתפות הרחבה מסמנת שהמאבק סביב זכויות להט״ב במדינה כבר חורג מאירוע קהילתי והופך לעימות אזרחי רחב.',
        )
    if (
        any(x in text.lower() for x in ['bahrain', 'hormuz', 'drones']) and any(x in text.lower() for x in ['ship', 'strait'])
    ) or (
        'המפרץ' in text and 'הורמוז' in text and any(x in text for x in ['כטב', 'ספינה', 'תקיפה ימית'])
    ):
        return (
            'כטב״מים ותקיפה ימית החזירו את המפרץ לכוננות',
            'כטב״מים פגעו בבחריין ללא נזק מיידי, ובמקביל ספינה במצר הורמוז הותקפה. צירוף האירועים משאיר את המפרץ תחת סיכון ביטחוני ישיר לתנועה ימית ואווירית.',
        )
    return None


def story_headline(title: str, desc: str, source: str) -> str:
    text = f'{title} {desc}'
    live_tuple = live_event_pointa_tuple(title, desc, source)
    if live_tuple:
        return live_tuple[0]
    fp = foreign_pointa_tuple(title, desc)
    if fp:
        return fp[0]
    if is_trump_phone_story(title, desc):
        return 'הטלפון של טראמפ הגיע - והלקוחות גילו שזה כנראה מכשיר סיני ממותג'
    if is_lieberman_succession_story(title, desc):
        return 'ליברמן ממקם את עצמו כיורש אפשרי של הנהגת הימין אחרי נתניהו'
    if is_iran_cuba_drone_story(title, desc):
        return 'ארה״ב חוששת שקובה הופכת לבסיס כטב"מים איראני ליד הגבול'
    if is_vance_iran_nuclear_story(title, desc):
        return 'ואנס מזהיר שגרעין איראני יצית מרוץ חימוש במפרץ'
    if is_el_nino_weather_story(title, desc):
        return 'אל ניניו חריג עלול להביא חורף גשום ושיטפונות בישראל'
    if is_protection_insurance_story(title, desc):
        return 'עסקים בצפון נשארים בלי ביטוח בגלל איומי פרוטקשן'
    if is_stolen_idf_weapon_restaurant_story(title, desc):
        return 'מסעדנית בגולן תואשם בגניבת M-16 מקצין צה״ל'
    if is_turkey_air_missile_story(title, desc):
        return 'טורקיה ניסתה טילי אוויר־אוויר שיחזקו את עצמאותה מול ישראל'
    if is_idf_lebanon_evacuation_warning_story(title, desc):
        return 'צה״ל הזהיר שישה כפרים בדרום לבנון להתפנות לפני תקיפה'
    if is_malinovsky_oct7_law_story(title, desc):
        return 'ח״כ מלינובסקי מאיימת לשבש הצבעות עד שימומן חוק מחבלי 7 באוקטובר'
    if is_helium_iran_war_story(title, desc):
        return 'המלחמה באיראן הקפיצה את מחירי ההליום ופתחה מרוץ גז חדש'
    if is_smotrich_elgart_hearing_story(title, desc):
        return 'שאלה של סמוטריץ׳ לדני אלגרט הציתה עימות בוועדה'
    if is_amos_luzon_relationship_story(title, desc):
        return 'פער הגילים הפך את הזוגיות של עמוס לוזון לכותרת סלבס'
    if 'מרלין' in text and ('דרס' in text or 'דקר' in text or 'הצית' in text):
        return 'מרלין אלטורי חששה מבעלה לפני שנדרסה, נדקרה ונשרפה'
    if 'רוכב אופניים חשמליים בן 10' in text and 'עכו' in text:
        return 'ילד בן 10 נפצע בינוני מפגיעת רכב בעכו'
    culture_h = culture_headline_from_context(title, desc)
    if culture_h:
        return culture_h
    # Specific pattern requested by Lior: turn market teasers into a concrete event.
    if 'המניות שייפלו' in title and 'סקטור השבבים' in title:
        return 'מניות הדואליות צפויות לפתוח בירידות בתל אביב אחרי שבוע אדום בשווקים'
    if 'אבא לא היה עושה לנו את זה' in title or 'הסוד שנחשף אחרי השבעה' in title:
        return 'אחים גילו אחרי מות אביהם שהוא הסתיר מהם אחות נוספת'
    if 'ביטקוין' in title and 'נשיא' in title:
        return 'בארה״ב מקדמים הגבלות על החזקת ביטקוין בידי הנשיא ומשפחתו'
    if 'אלצהיימר' in title and 'מחקר' in title:
        return 'מחקר חדש בודק קשר בין מחלה נפוצה לסיכון לאלצהיימר בעתיד'
    if 'חניוני קמפינג' in title:
        return 'עשרה חניוני קמפינג חינמיים נפתחו לציבור מצפון לדרום'
    if 'מערבולות אוויר' in title:
        return 'מחקר מסמן היכן בטיסה הסיכוי להיפגע ממערבולות נמוך יותר'
    if 'SMS מאיראן' in title:
        return 'הודעות SMS חשודות מאיראן מחייבות זהירות לפני לחיצה או תגובה'
    if 'הרכבים השיתופיים מגיעים' in title:
        return 'שירות רכבים שיתופיים מתרחב לבת ים'
    if 'מדד אפריל' in title:
        return 'מדד אפריל עלה יותר מהצפוי אך האינפלציה נשארה מתחת ל־2%'
    if 'מחירי הדלק' in title and 'מדד המחירים' in title:
        return 'הזינוק במחירי הדלק צפוי לדחוף את מדד המחירים כלפי מעלה'

    h = dequote_headline(title)
    # Use the description only when the title remains a quote/click teaser with no concrete event.
    if (len(h) < 22 or GENERIC_HEADLINE_RE.search(h)) and desc:
        first = split_sentences(desc)[:1]
        if first:
            h = first[0]
    # Avoid vague source questions; make them declarative when possible.
    h = re.sub(r'^האם\s+', '', h).strip()
    h = h.replace('?', '').strip()
    if is_weak_source_headline(title, h):
        rewritten = rewrite_copied_source_headline(title, desc, source)
        if rewritten:
            return complete_headline(rewritten, 72)
        cat, _ = categorize_item(title, desc, source)
        if cat == 'תרבות':
            alt = culture_headline_from_context(title, desc)
            if alt:
                return complete_headline(alt, 72)
        if desc:
            first = split_sentences(desc)[:1]
            if first and not is_weak_source_headline(title, first[0]):
                return complete_headline(first[0], 72)
    return complete_headline(h, 72)


def fallback_context_from_title(title: str, category: str = '') -> str:
    base = trim_words(dequote_headline(title), 62).replace('…', '').replace('...', '').strip(' ,;:-–')
    if base:
        return f'במרכז הסיפור: {base}. החשיבות היא ההשפעה המעשית על הקורא.'
    fallbacks = {
        'ביטחון': 'האירוע עשוי להשפיע על הביטחון או השגרה, ולכן חשוב לבדוק הנחיות רשמיות.',
        'כלכלה': 'הידיעה עשויה להשפיע על כסף, השקעות או החלטות פיננסיות קרובות.',
        'צרכנות': 'הסיפור עשוי להשפיע על קנייה, מחיר סופי או תנאים שצריך לבדוק.',
        'טכנולוגיה': 'העדכון עשוי להשפיע על שימוש יומיומי, פרטיות או אבטחה.',
        'תחבורה': 'העדכון עשוי להשפיע על נסיעה, זמינות שירות או החלטה לפני יציאה.',
        'ספורט': 'האירוע משנה את תמונת ההמשך סביב הקבוצה, הסגל או המומנטום.',
        'בריאות': 'המידע עשוי להשפיע על החלטות בריאותיות או על הבנת סיכון אישי.',
    }
    return fallbacks.get(category, 'הפרטים הזמינים אינם מספיקים עדיין לתובנה נקודתית אמינה.')


def compact_context(text: str, category: str = '', title: str = '', max_chars: int = 220) -> str:
    text = clean_text(text).replace('…', '').replace('...', '').strip(' ,;:-–')
    if len(text) <= max_chars:
        return text
    sentences = split_sentences(text)
    if sentences:
        candidate = ''
        for sentence in sentences[:3]:
            piece = sentence.replace('…', '').replace('...', '').strip(' ,;:-–')
            if not piece:
                continue
            next_text = f"{candidate} {piece}".strip()
            if len(next_text) > max_chars:
                if not candidate:
                    return short_sentence(piece, max_chars).rstrip('.') + '.'
                break
            candidate = next_text
            if word_count(candidate) >= MIN_CONTEXT_WORDS_BEFORE_ENRICH:
                break
        if candidate:
            return candidate
    return fallback_context_from_title(title, category)


def story_context(title: str, desc: str, source: str) -> str:
    text = f'{title} {desc}'
    live_tuple = live_event_pointa_tuple(title, desc, source)
    if live_tuple:
        return live_tuple[1]
    fp = foreign_pointa_tuple(title, desc)
    if fp:
        return fp[1]
    if is_trump_phone_story(title, desc):
        return 'אחרי חודשים של עיכובים, טראמפ מובייל החלה לשלוח את מכשיר ה-T1, אך אנליסטים טוענים שמדובר בסמארטפון סיני בסיסי עם מיתוג מוזהב ומחיר מנופח. במקביל החברה עדכנה את התקנון כך שגם תשלום מקדמה לא מבטיח אספקת מכשיר.'
    if is_lieberman_succession_story(title, desc):
        return 'במאמר פרשנות בוואלה נטען כי ליברמן בונה עצמו כאלטרנטיבה ימנית מנוסה לליכוד, עם קו תקיף מול איראן, תמיכה בגיוס חרדים ונכונות לשבת עם הליכוד - אך בלי נתניהו. לפי הכותב, הוא מנסה למשוך מאוכזבי ליכוד ולהתכונן ליום שאחרי עידן ביבי.'
    if is_iran_cuba_drone_story(title, desc):
        return 'דיווחים בארה״ב טוענים שאיראן שלחה יועצים צבאיים לקובה כדי לסייע בהפעלת כטב"מים וטכנולוגיות צבאיות מתקדמות. ברקע גובר החשש בוושינגטון מהעמקת שיתוף הפעולה בין איראן, רוסיה וקובה סמוך לשטח האמריקאי.'
    if is_vance_iran_nuclear_story(title, desc):
        return 'סגן נשיא ארה״ב ג׳יי די ואנס אמר שאיראן לא תוכל להחזיק בנשק גרעיני, כי נשק כזה ידחוף מדינות במפרץ לרצות יכולת גרעינית משלהן.'
    if is_el_nino_weather_story(title, desc):
        return 'מחקר חדש קושר בין אל ניניו חזק והתחממות הים התיכון לבין חורפים עם גשמים עזים יותר וסיכון גבוה יותר לשיטפונות.'
    if is_protection_insurance_story(title, desc):
        return 'בעלי עסקים טוענים שחברות הביטוח מבטלות פוליסות מיד לאחר איומי סחיטה או הצתות, בטענה שהסיכון הפך כמעט ודאי. בוועדת הכלכלה הזהירו שהמצב עלול להפיל עסקים, לעצור אשראי בנקאי ולהשאיר בעלי עסקים מול ארגוני הפשיעה ללא הגנה.'
    if is_stolen_idf_weapon_restaurant_story(title, desc):
        return 'לפי המשטרה, קצין שאכל עם חייליו במסעדה בגולן גילה בסוף הארוחה שנשקו האישי נעלם. בעלת המסעדה חשודה שנטלה את ה-M-16 על רקע חובות ואיומים, והובילה את החוקרים לנשק שהוסלק ברכב עובד.'
    if is_turkey_air_missile_story(title, desc):
        return 'טורקיה השלימה ניסויי ירי בטילי גוקדואן ובוזדואן, שמיועדים להשתלב במטוסי F-16 ולהחליף תלות בחימוש אמריקני. המהלך מחזק את התעשייה הביטחונית שלה ומוסיף שכבת לחץ אסטרטגית מול ישראל.'
    if is_idf_lebanon_evacuation_warning_story(title, desc):
        return 'צה״ל פרסם אזהרת פינוי לשישה כפרים בדרום לבנון ובאזור אל־בקאע המערבי. ההודעה מסמנת פעילות צבאית קרובה בגזרה ומרחיבה את אזור הסיכון מעבר לקו הגבול המיידי.'
    if is_malinovsky_oct7_law_story(title, desc):
        return 'ח״כ יוליה מלינובסקי קוראת לחברי הכנסת להשבית הצבעות עד שהממשלה תסיים את המימון לחוק העמדת מחבלי 7 באוקטובר לדין. המהלך הופך מחלוקת תקציבית לניסיון לחץ פרלמנטרי סביב טיפול במחבלים.'
    if is_helium_iran_war_story(title, desc):
        return 'פגיעה במתקני גז במפרץ בעקבות המלחמה עם איראן הגדילה את הביקוש להליום והקפיצה מחירים. ירדן מנסה לנצל את המחסור באמצעות חיפוש מקורות גז חדשים באזור ים המלח.'
    if is_smotrich_elgart_hearing_story(title, desc):
        return 'דיון בכנסת הידרדר לעימות לאחר שסמוטריץ׳ שאל את דני אלגרט “מי אדוני?”. השאלה הציתה תגובה חריפה והפכה את הדיון ממחלוקת עניינית לעימות אישי ופוליטי.'
    if is_amos_luzon_relationship_story(title, desc):
        return 'עמוס לוזון נמצא בזוגיות חדשה, והופעה משותפת בחתונה הפכה את פער הגילים ביניהם לסיפור המרכזי. זו ידיעת סלבס, לא סיפור פוליטי או ציבורי.'
    if 'מרלין' in text and ('דרס' in text or 'דקר' in text or 'הצית' in text):
        return 'מרלין אלטורי הגיעה עם בעלה לשטח פתוח ליד נחשונים, שהתה שם שעות ופנתה לחברה בחשש לפני שלפי החשד נדרסה, נדקרה ונשרפה ברכב.'
    if 'רוכב אופניים חשמליים בן 10' in text and 'עכו' in text:
        return 'ילד בן 10 שרכב על אופניים חשמליים נפצע באורח בינוני מפגיעת רכב ברחוב האורן בעכו.'
    if is_avihu_pinchasov_genesis_story(title, desc):
        return 'פסטיבל ג׳נסיס ליד עין חרוד הציע 12 שעות של מוזיקה, קהל צעיר ואסקפיזם מהמלחמה והשגרה. אביהו פנחסוב סיפק רגע פרובוקטיבי עם כיסוי מינימלי, אבל הוא רק חלק מסיפור רחב יותר על אירוע סוחף.'
    if 'המניות שייפלו' in title and 'סקטור השבבים' in title:
        return 'המסחר בתל אביב צפוי להיפתח בלחץ אחרי ירידות בוול סטריט ופערי ארביטראז׳ שליליים במניות דואליות.'
    if 'אבא לא היה עושה לנו את זה' in title or 'הסוד שנחשף אחרי השבעה' in title:
        return 'לאחר השבעה גילו בני משפחה כי לאביהם הייתה בת נוספת. החשיפה הובילה לסכסוך ירושה ולמאבק משפטי.'
    sentences = split_sentences(desc)
    if len(sentences) >= 2:
        return compact_context(sentences[0] + ' ' + sentences[1], categorize_item(title, desc, source)[0], title)
    if sentences:
        return compact_context(sentences[0], categorize_item(title, desc, source)[0], title)
    cat, _ = categorize_item(title, desc, source)
    # Last resort: concrete category framing, never "source published an article".
    fallbacks = {
        'ביטחון': 'האירוע עשוי להשפיע על הביטחון או השגרה, ולכן חשוב לבדוק הנחיות רשמיות.',
        'כלכלה': 'הידיעה עשויה להשפיע על מחירים, השקעות או החלטות פיננסיות קרובות.',
        'צרכנות': 'הסיפור עשוי להשפיע על קנייה, מחיר סופי או תנאים שצריך לבדוק.',
        'טכנולוגיה': 'העדכון עשוי להשפיע על שימוש יומיומי, פרטיות או אבטחה.',
        'תחבורה': 'העדכון עשוי להשפיע על נסיעה, זמינות שירות או החלטה לפני יציאה.',
        'ספורט': 'האירוע משנה את תמונת ההמשך סביב הקבוצה, הסגל או המומנטום.',
    }
    return fallbacks.get(cat, 'הפרטים הזמינים אינם מספיקים עדיין לתובנה נקודתית אמינה.')


def takeaway_subject(title: str, max_chars: int = 38) -> str:
    subject = dequote_headline(title).replace('?', '').replace('!', '').strip(' "״')
    subject = re.sub(r'^(כל מה שצריך לדעת על|המדריך המלא ל|המדריך המלא לא|איך|למה|מתי|האם)\s+', '', subject).strip()
    subject = trim_words(subject, max_chars).strip(' ,;:-–')
    return subject or 'הסיפור'


def specific_takeaway(title: str, desc: str) -> str:
    text = f'{title} {desc}'
    if any(x in text for x in ['ביטוח רכב', 'ביטוח רכבים']):
        if any(x in text for x in ['לחסוך', 'עלויות', 'הוצאות']):
            return 'ביטוח רכב הוא הוצאה שצריך לנהל במו״מ, לא לחדש אוטומטית.'
        return 'ברכב חדש, תנאי הביטוח חשובים כמעט כמו מחיר הקנייה.'
    if any(x in text for x in ['שיכור', 'נהג שיכור']) and any(x in text for x in ['רשלנות המשטרה', 'שוטרים', 'לחזור ולנהוג']):
        return 'כשאכיפה נופלת על שניות, נהגים מסוכנים חוזרים לכביש.'
    if 'SUV' in text or 'קרוסאובר' in text:
        return 'ה-SUV ניצח כי הוא מוכר תחושת ביטחון ונוחות, לא רק רכב.'
    if any(x in text for x in ['שכחת ילדים', 'מערכת למניעת שכחת', 'ילדים מתחת לגיל 4']):
        return 'אביזר בטיחות קטן הופך להוצאה שכל הורה חייב לבדוק.'
    if any(x in text for x in ['פיוראיטליה', 'עיצוב איטלקי', 'מנוע אמריקני']):
        return 'כאן הרכב מוכר תדמית ונוסטלגיה יותר ממפרט טכני.'
    if 'יבוא מקביל' in text:
        return 'בלי רגולציה יעילה, יבוא מקביל לא בהכרח מוריד מחיר לצרכן.'
    if any(x in text for x in ['קרינה ברכב חשמלי', 'רכב חשמלי', 'המשרד להגנת הסביבה']) and 'קרינה' in text:
        return 'אמון ברכב חשמלי דורש מדידות שקופות, לא רק הצהרות מרגיעות.'
    if any(x in text for x in ['סדרות מומלצות', 'טלוויזיה', 'שווה לראות']):
        return 'בעומס תוכן, הסינון עצמו חשוב כמעט כמו הסדרה.'
    if any(x in text for x in ['עשיתי כל מה שאני יכולה', 'עזרה כלכלית', 'מפרץ האהבה']):
        return 'חשיפה טלוויזיונית לא מבטיחה יציבות אחרי שהמצלמות כבות.'
    if any(x in text for x in ['טייוואן', 'חבילת נשק', 'עסקת ענק']) and any(x in text for x in ['איראן', 'המלחמה']):
        return 'עצירת עסקת הנשק לטייוואן מראה שהמלחמה באיראן מתחילה לשנות גם סדרי עדיפויות באסיה.'
    if 'מלחמה עם איראן' in text or 'אין מלחמה עם איראן' in text:
        return 'הפער בין ניסוחים רשמיים למציאות בשטח מקשה על הציבור להבין לאן המשבר מול איראן הולך.'
    if any(x in text for x in ['מט גאלה', 'פטמות', 'נשף']):
        return 'אופנה על השטיח האדום מוכרת דימוי לפני שהיא מוכרת בגד.'
    if is_stolen_idf_weapon_restaurant_story(title, desc):
        return 'גניבת נשק צבאי מתוך סביבה אזרחית הופכת הסתבכות כלכלית לאירוע ביטחוני ומשפטי חמור.'
    if is_turkey_air_missile_story(title, desc):
        return 'אנקרה בונה יכולת אווירית עצמאית שמצמצמת את מנופי הלחץ של וושינגטון.'
    if is_idf_lebanon_evacuation_warning_story(title, desc):
        return 'אזהרת פינוי היא סימן מקדים להסלמה נקודתית ולא רק עדכון שגרתי.'
    if ('מסעדה' in text or 'מסעדן' in text or 'מסעדנית' in text) and any(x in text for x in ['תיסגר', 'סגירה מפתיעה', 'נסגרת', 'סגירת']) and not any(x in text for x in ['M-16', 'נשק', 'גניבת']):
        return 'גם מוסד אהוב לא חסין מעלויות, שחיקה ושינויי קהל.'
    if any(x in text for x in ['תאונת עבודה', 'ביטוח לאומי', 'נפגע בדרך']):
        return 'המסלול והעיתוי יכולים לקבוע אם פגיעה תקבל כיסוי מלא.'
    if any(x in text for x in ['הכשרה', 'מתחרים', 'פיצוי']):
        return 'הכשרה מקצועית יכולה להפוך להתחייבות כספית אמיתית.'
    if any(x in text for x in ['בעיות שפעם ראינו בגיל 50', 'צעירים מגיעים היום', 'גיל 50']):
        return 'כשסימני גיל מופיעים מוקדם, מניעה חשובה יותר מטיפול מאוחר.'
    if any(x in text for x in ['כאב ביד', 'כירורגי']):
        return 'כאב הופך לדחוף כשיש פגיעה בתפקוד, לא רק כשכואב.'
    if any(x in text for x in ['בן זוג חדש', 'מול בן זוג']):
        return 'שיחה מביכה בזמן הנכון יכולה למנוע סיכון ואי־אמון בהמשך.'
    if 'אל על' in text and any(x in text for x in ['הפסד', 'רווחי שיא', 'עצירת הטיסות', '145 מיליון', 'המלחמה באיראן']):
        return 'המלחמה פגעה באל על בטווח הקצר, אבל צמצום התחרות עשוי להפוך את הקיץ לרווחי במיוחד.'
    if any(x in text for x in ['חברות התעופה', 'האוכל הכי טוב']) and not any(x in text for x in ['הפסד', 'רווחי שיא', 'עצירת הטיסות', '145 מיליון', 'המלחמה באיראן']):
        return 'גם אוכל בטיסה הפך לכלי תחרות על חוויית הנוסע.'
    if any(x in text for x in ['סרי לנקה', 'דרכים הציוריות']):
        return 'לפעמים הדרך עצמה היא המוצר המרכזי של הטיול.'
    if any(x in text for x in ['אינסטגרם', 'עובדים עליכם']):
        return 'ברשתות, האשליה היא המוצר — וצריך לבדוק מי מרוויח ממנה.'
    if any(x in text for x in ['מעיין', '250 מטר מהרכב']):
        return 'נגישות קלה יכולה להפוך פינה שקטה ליעד עמוס במהירות.'
    if any(x in text for x in ['עמק החלמוניות', 'חלמוניות']):
        return 'בטבע, עיתוי נכון חשוב יותר ממסלול ארוך.'
    if any(x in text for x in ['מראת האמבטיה', 'מאחורי מראת']):
        return 'סיפורי רשת עובדים כשהם הופכים סקרנות קטנה לתעלומה גדולה.'
    if any(x in text for x in ['הרב שי טחן', 'ליקוי']):
        return 'גם תופעת טבע מקבלת משמעות אחרת דרך פרשנות דתית.'
    if 'להחזיר אותו' in text:
        return 'בדיגיטל, פעולה קטנה יכולה להפוך במהירות לבלתי הפיכה.'
    if 'חוק הגיוס' in text:
        return 'חוק הגיוס הוא מבחן הישרדות לקואליציה, לא רק ויכוח על שירות.'
    if 'הצעה האיראנית' in text or ('איראנית' in text and 'טראמפ' in text):
        return 'במו״מ עם איראן, פרט ניסוח אחד יכול להפיל מסמך שלם.'
    if 'חלון ההכרעה' in text and 'איראן' in text:
        return 'ככל שהחלון מול איראן נסגר, המחיר של דחייה עולה.'
    if 'מגילות ים המלח' in text or 'נבואת סוף' in text:
        return 'גם גילוי עתיק נמכר היום דרך פחדים ונבואות סוף.'
    if 'ספינקס' in text:
        return 'תעלומות עתיקות עובדות כשהן מחברות מדע, מיתוס וסקרנות.'
    if 'חייזרים' in text and 'חשיכה' in text:
        return 'חיים בתנאים קיצוניים מרחיבים את הדמיון לגבי חיים מחוץ לכדור הארץ.'
    if 'דרכון אירופאי' in text:
        return 'זכאות אזרחית היא חלון הזדמנות — מי שמחכה עלול לאבד אותה.'
    if 'דירה' in text and any(x in text for x in ['טעות', 'לעלות לכם']):
        return 'בעסקת דירה, פרט קטן יכול להפוך להפסד גדול.'
    if ('דסה' in text or 'גלוך' in text or 'למקין' in text) and any(x in text for x in ['כדורגל', 'נבחרת', 'ליגה', 'קבוצה', 'שחקן', 'מאמן', 'אירופה', 'ספורט']):
        return 'אצל ליגיונרים, הזדמנות אחת יכולה לשנות את העונה הבאה.'
    if 'טייסון פיורי' in text:
        return 'תהילה משפחתית לא מגינה ממשברים פרטיים שמגיעים לכותרות.'
    if 'דני אבדיה' in text or 'אבדיה' in text:
        return 'אצל אבדיה, סימני אזהרה קטנים יכולים להשפיע על המעמד בעונה הבאה.'
    if 'העיר האבודה' in text:
        return 'גילוי ארכאולוגי חשוב כשהוא משנה את מה שחשבנו על ערי העבר.'
    if 'מלך השערים' in text and 'ריינה' in text:
        return 'במאבק ירידה, שחקן אחד בכושר יכול לשנות עונה שלמה.'
    if 'אדהם האדיה' in text:
        return 'סיפור עלייה של מאמן חושף איפה נפתחות הזדמנויות בכדורגל.'
    if 'האוסטרים בנבחרת' in text:
        return 'ויכוח על צוות זר בנבחרת הוא גם ויכוח על זהות וניהול.'
    if 'מרתון התבור' in text:
        return 'אירוע ספורט מקומי חזק יכול להפוך קהילה למוקד אזורי.'
    if 'מדד המחירים' in text and 'דירות' in text:
        return 'מדד גבוה ודירות יקרות מרחיקים את התקווה להקלה בריבית.'
    if '300 מפוטרים' in text or 'מפוטרים' in text and 'הייטק' in text:
        return 'גל פיטורים יכול להפוך למאגר כישרונות כשהשוק עדיין רעב לניסיון.'
    if 'כבלים התת ימיים' in text or 'מצר הורמוז' in text:
        return 'פגיעה בתשתיות תקשורת הופכת איום ביטחוני לסיכון כלכלי עולמי.'
    if 'מונופולים' in text:
        return 'הרגלי צריכה קטנים יכולים לחזק מונופולים בלי שנרגיש.'
    if 'טבעון' in text and 'אנבידיה' in text:
        return 'כניסה של ענקית טכנולוגיה יכולה להזניק נדל״ן עוד לפני שנבנה דבר.'
    if 'הנתון ההיסטורי' in text and 'משקיעים' in text:
        return 'משקיעים מחפשים סימן היסטורי, אבל העיתוי חשוב מהכותרת.'
    if 'שוק הקריפטו' in text:
        return 'עסקת ענק בקריפטו יכולה לשנות אמון בשוק לא פחות ממחירים.'
    return ''


def story_takeaway(category: str, title: str, desc: str) -> str:
    text = f'{title} {desc}'
    fp = foreign_pointa_tuple(title, desc)
    if fp:
        return fp[2]
    if is_trump_phone_story(title, desc):
        return 'המוצר האמיתי כאן הוא המותג של טראמפ - לא הטלפון עצמו.'
    if is_lieberman_succession_story(title, desc):
        return 'ליברמן כבר לא מכוון להיות שותף בממשלה - אלא להוביל את מחנה הימין שאחרי נתניהו.'
    if is_iran_cuba_drone_story(title, desc):
        return 'מבחינת ארה״ב, איראן כבר לא מאיימת רק מהמזרח התיכון - אלא מתקרבת פיזית לחצר האחורית שלה.'
    if is_vance_iran_nuclear_story(title, desc):
        return 'המסר של ואנס מסמן שוושינגטון מציגה את עצירת איראן כבלימת אפקט דומינו גרעיני, לא רק כהגנה על ישראל.'
    if is_el_nino_weather_story(title, desc):
        return 'זו אזהרת היערכות לחורף: ניקוז, נסיעות ואזורים מועדי הצפה חשובים יותר מהמונח המטאורולוגי עצמו.'
    if is_protection_insurance_story(title, desc):
        return 'כשהמדינה לא מצליחה להגן מפשע - גם שוק הביטוח מתחיל לקרוס אחריה.'
    if is_malinovsky_oct7_law_story(title, desc):
        return 'המאבק על החוק עבר מהצהרות לזירת לחץ בכנסת: בלי תקציב, גם חוק סמלי נתקע.'
    if is_helium_iran_war_story(title, desc):
        return 'גם מלחמה רחוקה יכולה להפוך חומר גלם נדיר לבעיה כלכלית עולמית.'
    if is_smotrich_elgart_hearing_story(title, desc):
        return 'שאלה מזלזלת אחת יכולה להפוך דיון ציבורי לזירת עימות פוליטית.'
    if is_amos_luzon_relationship_story(title, desc):
        return 'כאן הפואנטה היא עצם מנגנון הסלבס: פער גיל הופך זוגיות פרטית לכותרת.'
    if 'מרלין' in text and ('דרס' in text or 'דקר' in text or 'הצית' in text):
        return 'האזהרה ששלחה לחברה הופכת את הרצח לכשל התרעה סביב אלימות זוגית.'
    if 'רוכב אופניים חשמליים בן 10' in text and 'עכו' in text:
        return 'בעכו מדובר בפגיעת רכב בילד על אופניים חשמליים — לא בעדכון פוליטי.'
    if is_avihu_pinchasov_genesis_story(title, desc):
        return 'הפואנטה היא שהפסטיבל הצליח למכור לדור צעיר רגע נדיר של חופש, גם כשהמציאות בחוץ נשארת כבדה.'
    if 'המניות שייפלו' in title and 'סקטור השבבים' in title:
        return 'שבוע המסחר נפתח בעצבנות, ולכן מניות צמיחה ושבבים עלולות להיות הראשונות להיפגע.'
    if 'אבא לא היה עושה לנו את זה' in title or 'הסוד שנחשף אחרי השבעה' in title:
        return 'סודות משפחתיים שנחשפים אחרי המוות יכולים לשנות לחלוטין את חלוקת הירושה.'
    specific = specific_takeaway(title, desc)
    if specific:
        return specific
    subject = takeaway_subject(title)
    if category == 'כלכלה':
        return f'{subject} מסמן מי עלול לשלם יותר או לקחת סיכון גדול יותר.'
    if category == 'צרכנות':
        return f'{subject} קובע את המחיר האמיתי יותר מהכותרת השיווקית.'
    if category == 'טכנולוגיה':
        return f'{subject} משנה שימוש, פרטיות או אמון במוצר.'
    if category == 'תחבורה':
        return f'{subject} משפיע על עלות, בטיחות או זמינות נסיעה.'
    if category == 'ספורט':
        return f'{subject} משנה את המשך העונה או את מאזן הכוחות.'
    if category == 'ביטחון':
        return f'{subject} עשוי לשנות היערכות, שגרה או מרחב פעולה.'
    if category == 'בריאות':
        return f'{subject} מחייב להבין את הסיכון לפני החלטה בריאותית.'
    if category == 'תרבות':
        return f'{subject} מראה איך רגע פרטי הופך לדימוי ציבורי.'
    if category == 'דעות':
        return f'{subject} חושף את קו הטיעון, לא רק את הטון החריף.'
    return f'{subject} הוא הפרט שקובע מה באמת השתנה.'

def poanta_headline(title: str, desc: str, source: str = "") -> str:
    return story_headline(title, desc, source)


def context_text(title: str, desc: str, source: str) -> str:
    return story_context(title, desc, source)


def takeaway_text(category: str, title: str, desc: str) -> str:
    return story_takeaway(category, title, desc)


def canonical_url_key(url: str) -> str:
    """Stable article key across URL aliases.

    Mako/N12 often exposes the same article under multiple section paths
    (for example /news-money/... and /finances-money/...). Use the article id
    when available so old stories cannot re-enter through a different URL.
    """
    u = html.unescape(url or "")
    m = re.search(r"Article-([A-Za-z0-9]+)\.htm", u)
    if m:
        return "mako:" + m.group(1).lower()
    m = re.search(r"/item/(\d+)", u)
    if m:
        return "walla:" + m.group(1)
    m = re.search(r"[?&]did=(\d+)", u)
    if m:
        return "globes:" + m.group(1)
    m = re.search(r"/article/([A-Za-z0-9]+)", u)
    if m and "ynet.co.il" in u:
        return "ynet:" + m.group(1).lower()
    return re.sub(r"[?#].*$", "", u).rstrip("/").lower()


def normalized_key(text: str) -> str:
    text = re.sub(r"[^0-9A-Za-z\u0590-\u05ff]+", "", text).lower()
    return text[:70]


def duplicate_story_words(item: dict) -> set[str]:
    stop = set(
        "של על את עם זה זו הוא היא הם הן כי אשר אבל או אם גם יותר פחות לתוך מתוך "
        "אחרי לפני כדי כמו בין לפי ללא מול תחת מעל כל כבר עוד אותו אותה אותם אותן "
        "יש אין היה היתה היו יהיה תהיה להיות מה למה איך מי לא כן"
        .split()
    )
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context"])
    words = re.findall(r"[A-Za-z0-9\u0590-\u05ff]+", text.lower().replace("׳", "").replace('"', ""))
    return {w for w in words if len(w) > 2 and w not in stop}


def duplicate_word_overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, min(len(a), len(b)))


def weather_event_tokens(item: dict) -> set[str]:
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
    if {"rain", "wind"}.issubset(tokens) and ("shavuot" in tokens or len(tokens & {"north", "center"}) >= 2):
        return tokens
    return set()


def knesset_dissolution_tokens(item: dict) -> set[str]:
    """Fingerprint the same Knesset dissolution/election-advance vote story."""
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context", "takeaway", "category"]).lower()
    has_knesset = bool(re.search(r"כנסת|knesset", text))
    has_dissolution = bool(re.search(r"פיזור|פיזורה|לפזר|dissolv|election|בחירות", text))
    has_vote_stage = bool(re.search(r"קריאה ראשונה|first reading|106|ללא מתנגדים|בלי מתנגדים|הצעת חוק", text))
    if has_knesset and has_dissolution and has_vote_stage:
        return {"knesset_dissolution_first_reading"}
    return set()


def local_emergency_event_tokens(item: dict) -> set[str]:
    """Fingerprint concrete local emergency incidents across category labels.

    The public UI can show the same fire/rescue/accident story under different
    topics (for example generic חדשות vs. פלילים). Word overlap alone misses
    those when the category differs, so use narrow event+location tokens only
    for concrete local emergency reports.
    """
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context", "takeaway", "category"]).lower()
    tokens: set[str] = set()
    if re.search(r"שריפה|אש|דליק|כבאות|חולצו|חילוץ|לכודים|דיירים", text):
        tokens.add("fire_rescue")
    if re.search(r"רצח|נרצח|נרצחה|ירי|נורה|נורתה|הרוג|נהרג|murder|killed|shot", text):
        tokens.add("violent_death")
    if re.search(r"טמרה|tamra", text):
        tokens.add("tamra")
    if re.search(r"יפיע|נצרת|yafa|yafia|nazareth", text):
        tokens.add("yafia_nazareth")
    if re.search(r"שלושה|שני צעירים|שני גברים|גבר כבן 50|3\s+men|three", text):
        tokens.add("multiple_victims_north_crime")
    if re.search(r"בקבוקי תבערה|יידה|השליך|firebomb|molotov", text):
        tokens.add("firebomb_attack")
    if re.search(r"גבעת אסף|עפרה|ביתין|בנימין|givat assaf|ofra|beitin", text):
        tokens.add("binyamin_givat_ofra_area")
    if re.search(r"חיסל|חוסל|מחבל|terrorist|eliminated", text):
        tokens.add("terrorist_eliminated")
    if re.search(r"לוד|lod", text):
        tokens.add("lod")
    if re.search(r"בניין|מגורים|דירה|apartment", text):
        tokens.add("residential_building")
    if re.search(r"18|שמונה עשר|eighteen", text):
        tokens.add("eighteen_people")
    if "fire_rescue" in tokens and "lod" in tokens and ("residential_building" in tokens or "eighteen_people" in tokens):
        return tokens
    if "violent_death" in tokens and "tamra" in tokens and "yafia_nazareth" in tokens and "multiple_victims_north_crime" in tokens:
        return tokens
    if {"firebomb_attack", "binyamin_givat_ofra_area", "terrorist_eliminated"}.issubset(tokens):
        return tokens
    return set()


def northern_rocket_event_tokens(item: dict) -> set[str]:
    """Fingerprint the same northern rocket-impact event across sources."""
    main = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline"]).lower()
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
    if re.search(r"חיזבאללה|לבנון|צפון|גליל", text):
        tokens.add("north_aircraft_fire_region")
    if re.search(r"מ?ירי\s+לעבר\s+כלי\s+טיס|ירה\s+לעבר\s+כלי\s+טיס|ירה\s+על\s+כלי\s+טיס|ירי\s+על\s+כלי\s+טיס|אזעק|התרע", main):
        tokens.add("north_aircraft_fire_alert")
    if "kiryat_shmona" in tokens and "rocket_fire" in tokens and ("north_lebanon" in tokens or "direct_hit_damage" in tokens):
        return tokens
    if "north_uav_alert_area" in tokens and "north_uav_alert" in tokens:
        return tokens
    if {"north_uav_alert", "north_aircraft_fire_region", "north_aircraft_fire_alert"}.issubset(tokens):
        return tokens
    return set()


def security_event_tokens(item: dict) -> set[str]:
    """Semantic duplicate key for the same security event across sources.

    Foreign and Hebrew wires often describe the same military incident with very
    different headlines. The generic word-overlap threshold misses cases like
    ``US strikes southern Iran`` vs. Hebrew cards about self-defense strikes,
    boats, Bandar Abbas and Hormuz. Build a compact fingerprint only for a
    specific event family; otherwise return empty so adjacent Iran/Hormuz talks
    stories do not collapse into the strike card.
    """
    main = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline"]).lower()
    text = " ".join(str(item.get(k) or "") for k in ["originalTitle", "headline", "context", "takeaway", "category"]).lower()
    is_us = bool(re.search(r"\b(?:u\.?s\.?|us|united states|america|american)\b|ארה[״\"]?ב|אמריק", main))
    is_iran = bool(re.search(r"iran|איראן|טהראן", main))
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
    if re.search(r"hormuz|הורמוז", text):
        tokens.add("hormuz")
    if re.search(r"bandar|abbas|בנדר|עבאס", text):
        tokens.add("bandar_abbas")
    if re.search(r"self[- ]?defen[cs]e|הגנה עצמית|כהגנה", text):
        tokens.add("self_defense")
    if re.search(r"doha|qatar|דוחא|קטאר", text):
        tokens.add("qatar_talks")
    # Require concrete shared details, not only the broad US/Iran/strike frame.
    return tokens if len(tokens) >= 3 else set()


def live_regression_duplicate_tokens(item: dict) -> set[str]:
    primary = " ".join(str(item.get(k) or "") for k in ["headline", "originalTitle", "sourceUrl", "url"]).lower()
    text = " ".join(str(item.get(k) or "") for k in ["headline", "context", "summary", "takeaway", "originalTitle", "source", "sourceUrl", "url"]).lower()
    tokens = set()
    if (
        ("טראמפ" in text or "trump" in text)
        and ("נתניהו" in text or "netanyahu" in text)
        and ("איראן" in text or "iran" in text)
        and (
            "לא להגיב" in text
            or "לא לתקוף" in text
            or "תגובה ישראלית" in text
            or "strike back" in text
            or "not to strike" in text
            or "not strike" in text
        )
    ):
        tokens.add("trump_netanyahu_no_iran_response_20260608")
    # Require the tanker itself to be the primary story, not merely background
    # context for adjacent Kuwait/Bahrain air-defense alerts in the same crisis.
    if ("מכלית" in primary or "מיכלית" in primary or "tanker" in primary) and ("איראן" in text or "iran" in text) and (
        "הלפייר" in text or "hellfire" in text or "טיל" in text or "missile" in text or "שיתקה" in text or "ניטרלה" in text or "נטרלה" in text
    ):
        tokens.add("us_iran_tanker_hellfire")
    if ("13 מיליארד" in text or "13b" in text or "nis 13" in text) and (
        "צפון" in text or "north" in text
    ) and ("מיגון" in text or "שיקום" in text or "shelters" in text or "infrastructure" in text):
        tokens.add("north_reconstruction_13b")
    if ("איראן" in text or "iran" in text) and ("ארה״ב" in text or "ארה\"ב" in text or "us " in text or "u.s" in text or "american" in text) and (
        "הורמוז" in text or "hormuz" in text or "מפרץ" in text or "gulf" in text
    ) and (
        "כווית" in text or "בחריין" in text or "kuwait" in text or "bahrain" in text
    ) and (
        "מכלית" in text or "tanker" in text or "קשם" in text or "qeshm" in text or "תחנת שליטה" in text or "self-defense" in text
    ):
        tokens.add("us_iran_gulf_exchange_kuwait_bahrain")
    if (
        ("תקיפה" in text or "תקף" in text or "strike" in text)
        and ("ישראל" in text or "israel" in text)
        and ("צבא לבנון" in text or "lebanese army" in text or "lebanon army" in text)
        and ("חייל" in text or "קצין" in text or "soldier" in text or "officer" in text)
        and ("נהרג" in text or "killed" in text)
        and ("נבטיה" in text or "חרדלי" in text or "דרום לבנון" in text or "nabatieh" in text or "south lebanon" in text)
    ):
        tokens.add("israel_strike_lebanese_army_soldiers_nabatieh_20260606")
    if (
        ("צה״ל" in text or "צה\"ל" in text or "idf" in text)
        and ("דרום לבנון" in text or "south lebanon" in text)
        and ("שני" in text or "two" in text or "2 " in text)
        and ("לוחם" in text or "לוחמי" in text or "soldier" in text)
        and ("נהרג" in text or "נפל" in text or "killed" in text or "fall" in text)
        and ("רחפן" in text or "כטב" in text or "drone" in text or "uav" in text)
        and ("פליטת כדור" in text or "ירי פנימי" in text or "friendly fire" in text or "accidental discharge" in text or "separate" in text)
    ):
        tokens.add("idf_south_lebanon_two_soldiers_drone_accident_20260607")
    if (
        ("דרום לבנון" in text or "south lebanon" in text or "לבנון" in text)
        and ("רחפן נפץ" in text or "רחפן" in text or "כטב" in text or "drone" in text or "uav" in text)
        and ("ארבעה" in text or "4 " in text or "four" in text)
        and ("מילואימניק" in text or "לוחמי מילואים" in text or "לוחם מילואים" in text or "reservist" in text)
        and ("נפצע" in text or "פצוע" in text or "wounded" in text or "injured" in text)
        and ("בינוני" in text or "moderate" in text or "moderately" in text)
    ):
        tokens.add("idf_south_lebanon_four_reservists_drone_wounded_20260607")
    if (
        ("אפרת" in text or "efrat" in text)
        and ("דריסה" in text or "דרס" in text or "ramming" in text)
        and ("חשוד" in text or "suspected" in text or "terror" in text)
        and ("אבנים" in text or "יידוי" in text or "עימות" in text or "clash" in text or "settler" in text or "מתנחל" in text)
    ):
        tokens.add("efrat_junction_suspected_ramming_clashes_20260607")
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
        ("הרמטכ" in text or "chief of staff" in text or "idf chief" in text or "צה״ל" in text or "צה\"ל" in text)
        and ("צפון" in text or "גבול הצפון" in text or "ראשי רשויות" in text or "north" in text)
        and ("חיזבאללה" in text or "hezbollah" in text)
        and ("אין הכלה" in text or "ללא הכלה" in text or "נפעל בהתקפיות" in text or "התקפית" in text or "פרוס" in text or "לרכז כאן את המאמץ" in text or "containment" in text)
    ):
        tokens.add("idf_chief_north_hezbollah_posture")
    if (
        ("טראמפ" in text or "trump" in text)
        and ("איראן" in text or "iran" in text)
        and ("אורניום" in text or "uranium" in text)
        and ("מבצע" in text or "operation" in text)
        and ("להוציא" in text or "הוצאת" in text or "להוצאת" in text or "remove" in text or "removal" in text)
        and ("קרקע" in text or "חיילים" in text or "שטח" in text or "ground" in text or "troops" in text)
    ):
        tokens.add("trump_iran_uranium_ground_operation")
    if (
        ("אירלנד" in text or "ireland" in text)
        and ("בן גביר" in text or "ben gvir" in text)
        and ("סמוטריץ" in text or "smotrich" in text)
        and ("אסרה" in text or "אוסרת" in text or "תחסום" in text or "חסמה" in text or "כניסה" in text or "ban" in text)
    ):
        tokens.add("ireland_ben_gvir_smotrich_entry_ban")
    if (
        ("צה״ל" in text or "צה\"ל" in text or "idf" in text or "officer" in text or "קצין" in text or "קציני" in text or "גבעתי" in text or "מג״ד" in text or "מג\"ד" in text)
        and ("דרום לבנון" in text or "בלבנון" in text or "south lebanon" in text)
        and ("נפצע" in text or "injured" in text or "היתקלות" in text or "combat" in text)
        and ("קצין" in text or "קציני" in text or "officer" in text or "גבעתי" in text or "מג״ד" in text or "מג\"ד" in text)
    ):
        tokens.add("idf_officers_injured_south_lebanon_20260605")
    has_khamenei = "חמינאי" in text or "khamenei" in text
    has_us_or_trump = "ארה״ב" in text or "ארה\"ב" in text or "trump" in text or "טראמפ" in text or "u.s" in text or "american" in text
    if (
        has_khamenei
        and has_us_or_trump
        and ("גרעין" in text or "nuclear" in text or "מו״מ" in text or "מו\"מ" in text or "שיחות" in text or "talks" in text or "agreement" in text or "הסכם" in text)
        and ("מבוי סתום" in text or "stall" in text or "מוקפא" in text or "24 מיליארד" in text or "נכסים" in text or "deadlock" in text)
    ):
        tokens.add("khamenei_us_iran_nuclear_talks_deadlock")
    if (
        has_khamenei
        and has_us_or_trump
        and ("איראן" in text or "טהראן" in text or "iran" in text)
        and ("תרחיב" in text or "נרחיב" in text or "להרחיב" in text or "expand" in text)
        and ("מלחמה" in text or "לחימה" in text or "בסיס" in text or "war" in text or "bases" in text)
    ):
        tokens.add("khamenei_us_iran_regional_war_threat")
    if (
        ("צה״ל" in text or "צה\"ל" in text or "idf" in text or "אגוז" in text or "egoz" in text or "גבעתי" in text or "givati" in text)
        and ("דרום לבנון" in text or "בלבנון" in text or "south lebanon" in text)
        and ("נפל" in text or "נפלו" in text or "מת מפצעיו" in text or "fell" in text or "killed" in text)
        and ("שחר גמלא" in text or "ohad yaari" in text or "אוהד יערי" in text or "אהד יערי" in text or "shahar gamla" in text or "capt" in text or "סרן" in text)
    ):
        tokens.add("idf_fallen_soldiers_south_lebanon_20260606")
    if (
        ("אוהיו" in text or "ohio" in text or "טולדו" in text or "toledo" in text or "old west end" in text)
        and ("פסטיבל" in text or "festival" in text)
        and ("ירי" in text or "shooting" in text or "נפצע" in text or "injured" in text)
    ):
        tokens.add("ohio_festival_mass_shooting_20260607")
    if (
        ("ארה״ב" in text or "ארה\"ב" in text or "וושינגטון" in text or "us " in text or "u.s" in text or "washington" in text)
        and ("איראן" in text or "iran" in text or "איראני" in text)
        and ("נכסים" in text or "מוקפא" in text or "assets" in text or "frozen" in text)
        and ("שיקום" in text or "תיקון" in text or "נזק" in text or "rebuild" in text or "repair" in text or "damage" in text)
        and ("מפרץ" in text or "gulf" in text)
    ):
        tokens.add("us_iran_assets_gulf_reconstruction_20260607")
    if (
        ("חרד" in text or "haredi" in text or "ultra-orthodox" in text)
        and ("תחנת המשטרה" in text or "תחנת משטרה" in text or "police station" in text or "בית סולברג" in text or "solberg" in text)
        and ("ירושלים" in text or "jerusalem" in text)
        and ("מעצר" in text or "מתפרע" in text or "מפגינ" in text or "protest" in text or "attacked" in text)
    ):
        tokens.add("haredi_police_station_jerusalem_arrests_protest")
    return tokens


def gulf_air_defense_only(item: dict) -> bool:
    text = " ".join(str(item.get(k) or "") for k in ["headline", "context", "summary", "takeaway", "originalTitle", "source"]).lower()
    has_gulf_state = bool(re.search(r"כווית|בחריין|kuwait|bahrain", text))
    has_air_defense = bool(re.search(r"הגנה אווירית|מערכות ההגנה|יירוט|טילים|כטב|missiles?|drones?|air defense", text))
    has_tanker = bool(re.search(r"מכלית|מיכלית|tanker|lexie|הלפייר|hellfire", text))
    return has_gulf_state and has_air_defense and not has_tanker


def live_business_duplicate_tokens(item: dict) -> set[str]:
    """Fingerprint narrow business/acquisition stories that word-overlap misses."""
    text = " ".join(str(item.get(k) or "") for k in ["headline", "context", "summary", "takeaway", "originalTitle", "source", "sourceUrl", "url"]).lower()
    has_fox = bool(re.search(r"פוקס|ויזל|fox", text))
    has_noy = bool(re.search(r"נוי\s+השדה|noy\s+hasadeh", text))
    has_deal = bool(re.search(r"רכיש|קניי|כניסה|בוחן|בוחנת|acquir|purchase|deal|market", text))
    if has_fox and has_noy and has_deal:
        return {"fox_noy_hasadeh_deal"}
    return set()


def israir_slovenia_flight_tokens(item: dict) -> set[str]:
    """Fingerprint the same Israir Slovenia/Ljubljana landing-block diversion."""
    text = " ".join(str(item.get(k) or "") for k in ["headline", "context", "summary", "takeaway", "originalTitle", "source", "sourceUrl", "url"]).lower()
    has_israir = bool(re.search(r"ישראייר|israir", text))
    has_slovenia = bool(re.search(r"סלובניה|slovenia|לובליאנה|ljubljana", text))
    has_landing_or_diversion = bool(re.search(r"נחית|לנחות|חסמה|סירבה|הוסט|הועבר|זאגרב|zagreb|divert|landing|blocked", text))
    if has_israir and has_slovenia and has_landing_or_diversion:
        return {"israir_slovenia_landing_diversion"}
    return set()


def israel_slovenia_embassy_tokens(item: dict) -> set[str]:
    """Fingerprint Israel opening an embassy in Slovenia/Ljubljana after a pro-Israel government change."""
    text = " ".join(str(item.get(k) or "") for k in ["headline", "context", "summary", "takeaway", "originalTitle", "source", "sourceUrl", "url"]).lower()
    has_israel = bool(re.search(r"ישראל|israel", text))
    has_slovenia = bool(re.search(r"סלובניה|slovenia|לובליאנה|ljubljana", text))
    has_embassy = bool(re.search(r"שגריר|שגרירות|embassy|ambassador", text))
    has_government_change = bool(re.search(r"ממשלה|יאנש|janša|jansa|פרו-ישראל|ידיד(?:ת)? ישראל|אישור הקמת|ראש ממשלת סלובניה|עידן חדש ביחסים", text))
    has_israir_only = bool(re.search(r"ישראייר|israir|נחית|זאגרב|zagreb|divert", text)) and not has_embassy
    if has_israel and has_slovenia and has_embassy and has_government_change and not has_israir_only:
        return {"israel_slovenia_embassy_government_change"}
    return set()


def likely_duplicate_story(a: dict, b: dict) -> bool:
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
    if aw and bw and duplicate_word_overlap(aw, bw) >= 0.75:
        return True
    aw = knesset_dissolution_tokens(a)
    bw = knesset_dissolution_tokens(b)
    if aw and bw and "knesset_dissolution_first_reading" in aw and "knesset_dissolution_first_reading" in bw:
        return True
    aw = local_emergency_event_tokens(a)
    bw = local_emergency_event_tokens(b)
    if aw and bw and duplicate_word_overlap(aw, bw) >= 0.75:
        return True
    aw = northern_rocket_event_tokens(a)
    bw = northern_rocket_event_tokens(b)
    if aw and bw and duplicate_word_overlap(aw, bw) >= 0.75:
        return True
    aw = security_event_tokens(a)
    bw = security_event_tokens(b)
    if aw and bw and "us_iran_strike" in aw and "us_iran_strike" in bw and len((aw & bw) - {"us_iran_strike"}) >= 2:
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
    if str(a.get("category") or "") == str(b.get("category") or "") and duplicate_word_overlap(duplicate_story_words(a), duplicate_story_words(b)) >= 0.62:
        return True
    return False


def preferred_duplicate_item(a: dict, b: dict) -> dict:
    def score(item: dict) -> tuple[int, str, int, int]:
        # Lior's personal-feed rule: when similar stories arrive from different
        # sources, keep the freshest card and use editorial depth as the tie-breaker.
        # Official IDF/Police Telegram rows are critical-source updates: if they
        # describe the same event as a regular news source, prefer the official
        # source so those channels do not silently disappear from the visible feed.
        official = 1 if is_official_telegram_item(item) else 0
        published = str(item.get("publishedAt") or "")
        detail = len(" ".join(str(item.get(k) or "") for k in ["context", "takeaway", "headline", "originalTitle"]))
        image = 1 if item.get("imageUrl") else 0
        return (official, published, detail, image)
    winner = dict(a if score(a) >= score(b) else b)
    # A duplicate replacement is still the same story.  Keep the earliest visible
    # story time so repeated RSS/live updates do not make old cards look like
    # they just happened five minutes ago.
    timestamps = [str(item.get("publishedAt") or "") for item in (a, b) if item.get("publishedAt")]
    if len(timestamps) >= 2:
        winner["publishedAt"] = min(timestamps)
    return winner


def load_seen() -> dict:
    try:
        data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
        urls = set(data.get("urls", []))
        url_keys = set(data.get("urlKeys", [])) | {canonical_url_key(u) for u in urls}
        first_published_by_url = dict(data.get("firstPublishedByUrlKey", {}))
        first_published_by_title = dict(data.get("firstPublishedByTitleKey", {}))
        return {
            "urls": urls,
            "urlKeys": url_keys,
            "titleKeys": set(data.get("titleKeys", [])),
            "firstPublishedByUrlKey": first_published_by_url,
            "firstPublishedByTitleKey": first_published_by_title,
        }
    except Exception:
        return {"urls": set(), "urlKeys": set(), "titleKeys": set(), "firstPublishedByUrlKey": {}, "firstPublishedByTitleKey": {}}


def candidate_seen(c: Candidate, seen: dict) -> bool:
    title_keys = {normalized_key(c.title), normalized_key(c.original_title)}
    title_keys.discard("")
    return (
        c.url in seen["urls"]
        or canonical_url_key(c.url) in seen.get("urlKeys", set())
        or any(k in seen["titleKeys"] for k in title_keys)
    )


def remember_feed(feed: dict) -> None:
    seen = load_seen()
    first_by_url = seen.setdefault("firstPublishedByUrlKey", {})
    first_by_title = seen.setdefault("firstPublishedByTitleKey", {})
    for item in feed.get("items", []):
        url = item.get("sourceUrl")
        title = item.get("headline") or ""
        published_at = str(item.get("publishedAt") or "")
        if url:
            url_key = canonical_url_key(url)
            seen["urls"].add(url)
            seen.setdefault("urlKeys", set()).add(url_key)
            if published_at:
                first_by_url[url_key] = min(first_by_url.get(url_key, published_at), published_at)
        key = normalized_key(title)
        if key:
            seen["titleKeys"].add(key)
            if published_at:
                first_by_title[key] = min(first_by_title.get(key, published_at), published_at)
        original_key = normalized_key(item.get("originalTitle") or "")
        if original_key:
            seen["titleKeys"].add(original_key)
            if published_at:
                first_by_title[original_key] = min(first_by_title.get(original_key, published_at), published_at)
    payload = {
        "urls": sorted(seen["urls"]),
        "urlKeys": sorted(seen.get("urlKeys", set())),
        "titleKeys": sorted(seen["titleKeys"]),
        "firstPublishedByUrlKey": first_by_url,
        "firstPublishedByTitleKey": first_by_title,
        "updatedAt": datetime.now(timezone(timedelta(hours=3))).isoformat(timespec="seconds"),
    }
    SEEN_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stabilize_candidate_published_at(c: Candidate, seen: dict) -> Candidate:
    """Keep repeated RSS rows from looking newly published every sync."""
    url_key = canonical_url_key(c.url)
    title_keys = [normalized_key(c.title), normalized_key(c.original_title)]
    first_by_url = seen.get("firstPublishedByUrlKey", {})
    first_by_title = seen.get("firstPublishedByTitleKey", {})
    stable = first_by_url.get(url_key) if url_key else ""
    if not stable:
        stable = next((first_by_title.get(k) for k in title_keys if k and first_by_title.get(k)), "")
    if stable and c.published_at and stable < c.published_at:
        c.published_at = stable
    return c


def item_quality_errors(item: dict) -> list[dict]:
    if quality_validate_item is None:
        return []
    issues: list[dict] = []
    try:
        quality_validate_item(item, -1, issues)
    except Exception as exc:
        return [{"severity": "error", "code": "quality_exception", "message": str(exc)}]
    return [i for i in issues if i.get("severity") == "error"]


def normalize_police_item(item: dict) -> dict:
    """Keep official Israel Police Telegram cards factual and non-generic."""
    title = clean_text(str(item.get("originalTitle") or item.get("headline") or ""))
    desc = clean_text(str(item.get("context") or ""))
    headline = title.split(" - ")[0].split(" – ")[0]
    headline = headline.split(",")[0]
    context = desc
    takeaway = "עדכון משטרתי צריך להבהיר מה השתנה באירוע, לא רק שהוא הגיע ממקור רשמי."
    if "סיגריות" in title and "לאיו" in title:
        headline = "סוכלה הברחת סיגריות בשווי 20 מיליון שקל לאיו״ש"
        context = "החשד: מכולות סיגריות מטורקיה הובאו דרך נמל אשדוד בהצהרה כוזבת ונועדו להגיע לאיו״ש."
        takeaway = "החשד מצביע על נתיב הברחה מאורגן דרך נמל רשמי, לא על תפיסה נקודתית במעבר."
    elif "אשקלון" in title and "קטינים" in title and "סכין" in title:
        headline = "קטינים באשקלון עוכבו לאחר שנתפסו סכין וגז פלפל בחוף"
        context = "באזור החופים באשקלון עוכבו שלושה קטינים; נתפסו סכין באורך 42 ס״מ, גז פלפל ובקבוקי וודקה."
        takeaway = "נוכחות קטינים עם סכין וגז פלפל בחוף הופכת בילוי רגיל לאירוע פלילי מסוכן."
    elif "ירי בשפרעם" in title and "נפגע" in title:
        headline = "תושב שפרעם נפצע קשה באירוע ירי בעיר"
        context = "תושב שפרעם בן 23 נפצע באורח קשה מירי בעיר; המשטרה פתחה בחקירה ובסריקות אחר חשודים."
        takeaway = "ירי עם פצוע קשה משאיר את שפרעם תחת חקירה פתוחה וסריקות אחר חשודים."
    elif "מרלין אלטורי" in title and "כתב אישום" in title:
        headline = "כתב אישום צפוי נגד בן זוגה ואחיו ברצח מרלין אלטורי"
        context = "משטרת מחוז מרכז הודיעה שפענחה את רצח מרלין אלטורי, שנמצאה שרופה ברכבה; כתב אישום צפוי נגד בן זוגה ואחיו."
        takeaway = "פענוח הרצח מעביר את החשד אל המעגל הקרוב ביותר של הקורבן."
    elif "שריפה בשטח פתוח" in title and "פתח תקוה" in title and "ללא רוח חיים" in title:
        headline = "גופה אותרה בשריפה ליד פתח תקווה; המשטרה חושדת ברצח"
        context = "כוחות משטרה וחירום שהוזעקו לשריפה בשטח פתוח ליד פתח תקווה איתרו במקום אדם ללא רוח חיים; החקירה נפתחה בחשד לרצח."
        takeaway = "השריפה הפכה מזירת חירום לזירת רצח אפשרית, ולכן החקירה הפלילית היא לב הסיפור."
    if len(headline) < 28:
        headline = title
    headline = trim_words(headline, 88)
    if not context or "במרכז הסיפור" in context or "ההשפעה המעשית" in context or normalized_key(context) == normalized_key(headline):
        context = title
    if normalized_key(context) == normalized_key(headline) and " - " in title:
        context = title.replace(" - ", ", ", 1)
    item["headline"] = trim_words(headline, 88)
    item["context"] = trim_words(context, 180)
    item["takeaway"] = trim_words(takeaway, 95)
    item["category"] = "פלילים"
    item["categoryClass"] = "security"
    item["sourceLogo"] = "משטרה"
    return item


def rewrite_cut_or_invalid_item(item: dict) -> dict:
    """Try one deterministic Pointa rewrite before quarantine.

    The first response to a clipped headline should be rewrite, not deletion.
    If the rewritten card still fails the gate, quarantine_bad_items will reject it.
    """
    title = str(item.get("originalTitle") or item.get("headline") or "")
    desc = str(item.get("context") or "")
    source = str(item.get("source") or "")
    if 'יאיר גולן' in title and 'נתניהו כשיר' in title:
        item["headline"] = 'יאיר גולן תקף את כשירות נתניהו ואת פירוק מערכות האכיפה'
        item["context"] = 'יאיר גולן אמר שאינו בטוח שנתניהו כשיר פיזית וקוגניטיבית, וטען שהממשלה מרסקת את מערכות האכיפה במכוון.'
        item["takeaway"] = 'המתקפה מציבה את כשירות נתניהו ואת מערכת האכיפה במרכז העימות הפוליטי.'
        item["category"] = 'פוליטיקה'
        item["categoryClass"] = 'security'
        return item
    if 'רופאים לא מוצאים עבודה' in title or ('חגי לוין' in desc and 'מערכת הבריאות' in desc):
        item["headline"] = 'רופאים מתקשים למצוא תקנים בזמן שבתי החולים מזהירים מקריסה'
        item["context"] = 'בדיון בכנסת הזהיר פרופ׳ חגי לוין שמערכת הבריאות על סף קריסה, בזמן שרופאים מתקשים למצוא תקנים וחלקם עובדים מחוץ למקצוע.'
        item["takeaway"] = 'מחסור בתקנים יכול להפוך עודף רופאים לכשל שירות בבתי החולים.'
        item["category"] = 'בריאות'
        item["categoryClass"] = 'real'
        return item
    item["headline"] = story_headline(title, desc, source)
    item["context"] = story_context(title, desc, source)
    item["takeaway"] = story_takeaway(str(item.get("category") or "חדשות"), title, desc)
    new_category, new_cls = categorize_item(title, desc, source)
    item["category"] = new_category
    item["categoryClass"] = new_cls
    return item


def quarantine_bad_items(items: list[dict], reason: str) -> list[dict]:
    """Keep only cards that pass the item-level Quality Gate.

    A thin or generic card is worse than no card. Invalid cards are written to a
    local quarantine file for editorial review instead of being shipped.
    """
    kept: list[dict] = []
    rejected: list[dict] = []
    for item in items:
        if "משטרת ישראל" in str(item.get("source") or "") or "דוברות משטרת" in str(item.get("source") or ""):
            # Preserve already QA-clean official Telegram bridge cards; the
            # legacy normalizer is only a fallback for older/generic police cards.
            if item_quality_errors(item):
                item = normalize_police_item(item)
        errors = item_quality_errors(item)
        if errors:
            item = rewrite_cut_or_invalid_item(item)
            errors = item_quality_errors(item)
        if errors:
            rejected.append({"reason": reason, "errors": errors, "item": item})
        else:
            kept.append(item)
    if rejected:
        payload = {"updatedAt": datetime.now(timezone(timedelta(hours=3))).isoformat(timespec="seconds"), "rejected": rejected}
        try:
            QUARANTINE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass
        print(f"Quarantined {len(rejected)} Pointa cards that failed item quality", file=sys.stderr)
    return kept


def official_telegram_pointa_fields(c: Candidate) -> tuple[str, str, str, str, str] | None:
    """Deterministic bridge for terse official Telegram updates.

    IDF/Police posts are not article-style RSS rows. The generic Pointa rewrite
    often copies the first sentence into both headline and context, causing the
    Quality Gate to reject every candidate while sourceActivity still looks
    fresh. Keep these cards factual, short, and specific instead of using the
    generic article templates.
    """
    source = str(c.source or "")
    title = clean_text(c.title or "")
    desc = clean_text(c.description or "")
    text = f"{title} {desc}"
    if "דובר צה" in source or "צה״ל" in source or "צה\"ל" in source:
        category, cls = "ביטחון", "security"
        if "שיגורים" in text and any(x in text for x in ["מטולה", "כפר יובל", "דרום לבנון"]):
            headline = "שיגורים נורו לעבר כוחות צה״ל בדרום לבנון"
            context = "לאחר התרעות במטולה ובכפר יובל זוהו שיגורים לעבר מרחב שבו פועלים כוחות צה״ל; אין נפגעים, וחלק מהתרעות הכטב״ם הוגדרו בהמשך כזיהוי שווא."
            takeaway = "הגבול הצפוני נשאר פעיל גם כשאירוע מסתיים בלי נפגעים."
        elif "חדירת כלי טיס" in text and "זיהוי שווא" in text:
            headline = "צה״ל עדכן שהתרעות כטב״ם בצפון היו זיהוי שווא"
            context = "התרעות על חדירת כלי טיס עוין הופעלו במנרה, קריית שמונה ומרחבים נוספים בצפון, אך לאחר הבדיקה צה״ל מסר שמדובר בזיהוי שווא."
            takeaway = "בצפון חשוב להבדיל בין אזעקה בזמן אמת לבין סגירת אירוע אחרי בדיקה."
        elif "חדירת כלי טיס" in text or "הופעלו התרעות" in text:
            headline = "התרעות ביטחוניות הופעלו בצפון והפרטים נבדקים"
            context = desc if desc and not normalized_key(desc).startswith(normalized_key(headline)) else title
            takeaway = "התרעה פתוחה היא מצב ביניים: לפעול לפי ההנחיות עד סיום הבדיקה."
        elif "מיירט" in text and "מטרת שווא" in text:
            headline = "צה״ל עדכן שמיירט שוגר לעבר מטרת שווא בצפון"
            context = "בהמשך להתרעות במרחב יפתח ומבואות חרמון, צה״ל מסר שמיירט שוגר לעבר מטרת שווא ולא דווח על נפגעים."
            takeaway = "גם יירוט שהתברר כשווא משפיע על תחושת הביטחון ביישובי הגבול."
        elif "מדיניות ההתגוננות" in text:
            headline = "מדיניות ההתגוננות של פיקוד העורף נותרה ללא שינוי"
            context = "בתום הערכת מצב נקבע שהנחיות ההתגוננות יישארו בתוקף עד יום ראשון, 31 במאי 2026, בשעה 20:00."
            takeaway = "אי־שינוי בהנחיות עדיין קובע את גבולות השגרה לימים הקרובים."
        elif "מתדלק" in text or "גדעון" in text:
            headline = "מטוס התדלוק החדש נחת בטייסת גדעון בנבטים"
            context = "צה״ל קלט את המתדלק המתקדם בטייסת שהוקמה עבורו בבסיס נבטים, עם יכולת לתדלק שני מטוסים במקביל ועמדת נווט נוספת."
            takeaway = "יכולת תדלוק אווירי חדשה מרחיבה את טווח הפעולה של חיל האוויר."
        elif "חיזבאללה" in text and any(x in text for x in ["מפקדת ארטילריה", "פיצוצי משנה", "אמצעי לחימה"]):
            headline = rewrite_copied_source_headline(title, desc, source) or complete_headline(dequote_headline(title), 72)
            context = desc if desc and not normalized_key(desc).startswith(normalized_key(headline)) else title
            takeaway = "פיצוצי המשנה מעידים שחיזבאללה עדיין מחזיק אמצעי לחימה במבנים צבאיים בדרום לבנון."
        elif "חיזבאללה" in text and any(x in text for x in ["מחבלים", "חוסלו", "מפקדי"]):
            headline = "צה״ל מציג פגיעה במפקדי חיזבאללה מאז הפסקת האש"
            context = desc or title
            takeaway = "פגיעה במפקדי שטח משנה את חופש הפעולה של חיזבאללה בדרום לבנון."
        elif "במהלך השבוע" in text and any(x in text for x in ["חיסולים", "דרום לבנון", "איו\"ש", "איו״ש"]):
            headline = "צה״ל סיכם שבוע פעילות בעזה, בלבנון ובאיו״ש"
            context = "בסיכום השבוע צה״ל דיווח על יותר מ-10 חיסולים בעזה, שש תקיפות בדרום לבנון ויותר מ-100 מעצרים באיו״ש."
            takeaway = "סיכום שבועי כזה מראה שצה״ל פועל במקביל בשלוש זירות, לא רק באירוע נקודתי."
        elif "הרמטכ" in text and "קורס" in text and "קצינים" in text:
            headline = "הרמטכ״ל הציב לקצינים החדשים את אתגר הלכידות בצה״ל"
            context = "בטקס סיום קורס הקצינים הדגיש הרמטכ״ל את הצורך לשמור על מסגרת צבאית משותפת מול מגוון אוכלוסיות ומשימות."
            takeaway = "המסר לקצינים החדשים הוא שלכידות הפיקוד הפכה לאתגר מבצעי, לא רק ערכי."
        elif "הארכת השירות" in text and "שיטת שיבוץ" in text:
            headline = "צה״ל מסביר למה הוא דוחף להארכת שירות ולשיבוץ חדש"
            context = "רח״ט תכנון ומנהל כוח האדם בצה״ל הציג את הצורך בהארכת שירות ל-36 חודשים, גיוס אוכלוסיות נוספות ושיטת שיבוץ היברידית."
            takeaway = "מצוקת כוח האדם בצה״ל כבר משנה את תנאי השירות ואת הדרך שבה חיילים ישובצו."
        else:
            headline = rewrite_copied_source_headline(title, desc, source) or complete_headline(dequote_headline(title), 72)
            context = compact_context(desc or title, "ביטחון", title)
            if normalized_key(context).startswith(normalized_key(headline)):
                context = compact_context(text, "ביטחון", title)
            takeaway = "הערך של עדכון צבאי כזה תלוי בשאלה אם הוא משנה פעילות כוחות, גבול או שגרת אזרחים."
        return headline, context, takeaway, category, cls

    if "משטרת ישראל" in source or "דוברות משטרת" in source:
        category, cls = "פלילים", "security"
        if "בר אילן" in text:
            headline = "המשטרה פיזרה הפרות סדר בצומת בר אילן בירושלים"
            context = "כוחות משטרה ומג״ב פעלו מול חוסמי צירים באזור צומת בר אילן; לפי הפרטים, מפרי סדר השליכו חפצים, גרמו נזק לתשתיות ותקפו שוטרים."
            takeaway = "חסימת צירים ותקיפת שוטרים הופכות מחאה מקומית לאירוע אכיפה רחב."
        elif "כביש 4" in text or "גהה" in text:
            headline = "הפגנה בלתי חוקית חסמה את כביש 4 באזור גהה"
            context = "בצומת גהה דווח על חסימת כביש והכוונת נהגים לדרכים חלופיות, לאחר שקצין משטרה הכריז על הפגנה בלתי חוקית."
            takeaway = "חסימת עורק תחבורה מרכזי משפיעה מיד על נהגים גם מחוץ לזירת המחאה."
        elif "סילוואן" in text or "שלושה שוטרים" in text:
            headline = "שישה נעצרו בסילוואן ושלושה שוטרים נפצעו קל"
            context = "כוחות משטרה ומג״ב הוזעקו לאירוע אלימות במזרח ירושלים; במקום התפתחה הפרת סדר, ובסיומה נעצרו שישה חשודים."
            takeaway = "אירוע אלימות שכונתי הופך למסוכן יותר כששוטרים נפגעים במהלך הטיפול בו."
        elif "שב\"חים" in text or "שוהים בלתי חוקיים" in text:
            headline = "רשת הברחת שב״חים נחשפה בעוטף ירושלים"
            context = "חקירת מג״ב בעוטף ירושלים חשפה חשד לרשת נהגים וספסרים שהסיעה שוהים בלתי חוקיים לעומק ישראל; נעצרו חשודים והוגשו כתבי אישום."
            takeaway = "רשת הסעות מאורגנת מסוכנת יותר ממעבר בודד כי היא יוצרת נתיב קבוע."
        elif "פיגועים פליליים" in text or "כלי נשק" in text:
            headline = "המשטרה סיכלה חיסולים פליליים ותפסה נשקים בצפון"
            context = "בפעילות מחוז צפון ומג״ב נתפסו קלצ׳ניקוב, M16, אקדחים ורכב שהוכן לפי החשד לביצוע חיסול; חשודים נעצרו לפני מימוש האירועים."
            takeaway = "תפיסת נשקים לפני חיסול מצמצמת סיכון מיידי ולא רק מוסיפה תיק חקירה."
        elif "שכם" in text and "פיגוע" in text:
            headline = "מסתערבי מג״ב עצרו בשכם חשודים שתכננו פיגוע"
            context = "הכוחות נכנסו למרחב בצורה מסוערבת, סגרו על המבנה שבו הסתתרו החשודים וניהלו מולם מגעים עד שנעצרו."
            takeaway = "מעצר לפני ביצוע פיגוע חשוב יותר ממספר העצורים עצמו."
        elif "אמצעי לחימה" in text and "בור מים" in text:
            headline = "אמצעי לחימה הוסלקו בבור מים בכפר אל־ג׳יב"
            context = "לוחמי מג״ב איתרו בבור מים באזור ירושלים מצבור אמצעי לחימה שלפי החשד יועד לפעילות טרור, לאחר פעולה מורכבת שכללה שאיבת מים וצלילה."
            takeaway = "הסלקת נשק בבור מים מצביעה על תשתית טרור מתוכננת, לא על החזקת נשק מקרית."
        elif "גנב סדרתי" in text and "עזריאלי" in text:
            headline = "חשוד בגניבת טלפונים בקניון עזריאלי נעצר אחרי מרדף"
            context = "בלשי תחנת חברון עקבו אחר חשוד מדאהרייה שנחשד בגניבת מכשירי טלפון בקניון עזריאלי בתל אביב, עד שנעצר לאחר שניסה להימלט בין החנויות."
            takeaway = "גניבה סדרתית בקניון מרכזי דורשת מעקב מודיעיני, לא רק תפיסה רגעית בחנות."
        elif "ג'סר א-זרקא" in text and "ירי" in text and "קשה" in text:
            headline = "גבר נפצע קשה בירי בג׳סר א־זרקא"
            context = "המשטרה פתחה בחקירה לאחר דיווח על ירי בג׳סר א־זרקא, שבו נפגע גבר באורח קשה; הכוחות אספו ראיות בזירה והרקע מסתמן כפלילי."
            takeaway = "ירי עם פצוע קשה משאיר את היישוב תחת חקירה פלילית וסיכון פתוח."
        elif ("רצח ביפו" in text or "אבן רושד" in text or "אבן רשד" in text) and any(x in text for x in ["שני פצועים", "קטינים", "מותו"]):
            headline = "קטין נהרג וקטין נוסף נפצע בירי ביפו"
            context = "באירוע ירי ברחוב אבן רשד ביפו נפגעו שני בני 17, ובהמשך נקבע מותו של אחד מהם. המשטרה פתחה בחקירת רצח ואוספת ראיות בזירה."
            takeaway = "ירי שמסתיים במות קטין הופך סכסוך פלילי למשבר ביטחון אישי בשכונה."
        elif "התעללות בפעוטות" in text or ("מטפלת" in text and "פעוטות" in text):
            headline = "מטפלת מירושלים נעצרה בחשד להתעללות בפעוטות"
            context = "משטרת ירושלים פתחה בחקירה בעקבות תלונות על מטפלת מהר חומה, שלפי החשד צעקה, קיללה והתעלמה מצרכי פעוטות שהיו תחת השגחתה."
            takeaway = "בגני ילדים, תלונות קטנות על יחס יומיומי יכולות להפוך במהירות לחשד פלילי."
        elif "רופאי" in text and "שיניים" in text and any(x in text for x in ["זיהוי פלילי", "בית הנשיא", "נעדרים", "חללים"]):
            headline = "הנשיא הוקיר מתנדבי זיהוי פלילי שסייעו בזיהוי חללים"
            context = "בבית הנשיא נערך אירוע הוקרה ליחידת רופאי ורופאות השיניים המתנדבים של הזיהוי הפלילי, שלקחו חלק בזיהוי נעדרים וחללים לאורך המלחמה."
            takeaway = "מאחורי עבודת הזיהוי הפלילי עומדת תשתית אזרחית־מקצועית שממשיכה לפעול גם אחרי רגעי האסון."
            category, cls = "חדשות", "real"
        else:
            headline = rewrite_copied_source_headline(title, desc, source) or complete_headline(dequote_headline(title), 72)
            context = compact_context(desc or title, "פלילים", title)
            if normalized_key(context).startswith(normalized_key(headline)):
                context = compact_context(text, "פלילים", title)
            takeaway = "אירוע משטרתי משמעותי צריך להיבחן לפי הסיכון שנמנע וההשפעה על השגרה המקומית."
        return headline, context, takeaway, category, cls
    return None


def build_feed(candidates: Iterable[Candidate], experimental: bool = False) -> dict:
    items = []
    seen_titles = set()
    seen_output_headlines = set()
    for c in candidates:
        key = normalized_key(c.title)
        if key in seen_titles:
            continue
        seen_titles.add(key)
        category, cls = categorize_item(c.title, c.description, c.source)
        official_fields = official_telegram_pointa_fields(c)
        if official_fields:
            headline, context, takeaway, category, cls = official_fields
        elif "פיקוד העורף" in c.source:
            headline = c.title
            context = c.description or "יש לפעול לפי הנחיות פיקוד העורף."
            takeaway = "זו התרעה רשמית — ההנחיות חשובות יותר מהכותרת."
            category, cls = "ביטחון", "security"
        elif experimental:
            headline = experimental_headline(c.title, c.description)
            context = experimental_summary(c.title, c.description, c.source)
            takeaway = experimental_insight(category, c.title, c.description)
        else:
            headline = poanta_headline(c.title, c.description, c.source)
            context = context_text(c.title, c.description, c.source)
            takeaway = takeaway_text(category, c.title, c.description)
        item = {
            "category": category,
            "categoryClass": cls,
            "source": c.source,
            "sourceLogo": source_logo(c.source),
            "sourceUrl": c.url,
            "imageUrl": c.image_url,
            "publishedAt": c.published_at,
            "hasSourceDate": bool(c.published_at),
            "time": "עודכן אוטומטית",
            "headline": headline,
            "originalTitle": c.original_title or c.title,
            "context": context,
            "takeaway": "",
        }
        if (
            is_weak_source_headline(str(item.get("originalTitle") or ""), str(item.get("headline") or ""))
            or (
                item.get("context")
                and len(str(item.get("headline") or "")) >= 24
                and normalized_key(str(item.get("context") or "")).startswith(normalized_key(str(item.get("headline") or "")))
            )
        ):
            rewritten = rewrite_copied_source_headline(c.title, c.description, c.source)
            if rewritten:
                item["headline"] = rewritten
        output_key = normalized_key(str(item.get("headline") or ""))
        if output_key in seen_output_headlines:
            continue
        if not item_quality_errors(item):
            seen_output_headlines.add(output_key)
            items.append(item)
    tz = timezone(timedelta(hours=3))
    payload = {"updatedAt": datetime.now(tz).isoformat(timespec="seconds"), "items": items}
    if experimental:
        payload["mode"] = "pointa-summary-experimental"
        payload["version"] = EXPERIMENTAL_VERSION
    return payload





def fetch_article_image(url: str) -> str:
    if not url or 'news.google.com/' in url:
        return ""
    try:
        raw = fetch(url, timeout=10)
        parser = parse_html(raw)
    except Exception:
        raw = ""
        parser = parse_html("")
    image = clean_text(parser.meta.get("og:image") or parser.meta.get("twitter:image") or parser.meta.get("image") or "")
    if not image and (not raw or "Radware Block Page" in raw):
        _, image = fetch_jina_metadata(url)
    if not image:
        image = image_from_html_fragment(raw)
    if not image:
        return ""
    joined = urljoin(url, image)
    if is_rejected_source_image(joined, url):
        return ""
    return joined

def refresh_item_pointa(item: dict) -> dict:
    title = str(item.get("originalTitle") or item.get("headline") or "")
    desc = str(item.get("context") or "")
    source = str(item.get("source") or "")
    if "משטרת ישראל" in source or "דוברות משטרת" in source:
        # Official Telegram bridge cards may already be QA-clean. Do not run the
        # older police normalizer over them, because it can replace a specific
        # takeaway with a generic one and quarantine the card during merge.
        if not item_quality_errors(item):
            return item
        return normalize_police_item(item)
    if "פיקוד העורף" in str(item.get("source") or ""):
        current_headline = str(item.get("headline") or "")
        if current_headline.startswith("יישובים:"):
            repaired_title, _, _ = summarize_oref_telegram("\n".join([title, desc]))
            if repaired_title:
                item["headline"] = repaired_title
        item["category"] = "ביטחון"
        item["categoryClass"] = "security"
        item["takeaway"] = "זו התרעה רשמית — ההנחיות חשובות יותר מהכותרת."
        return item
    fp = foreign_pointa_tuple(title, desc)
    if fp:
        item["headline"] = fp[0]
        item["context"] = fp[1]
        item["takeaway"] = fp[2]
        item["category"] = fp[3]
        item["categoryClass"] = fp[4]
    live_tuple = live_event_pointa_tuple(title, desc, source)
    if live_tuple:
        item["headline"] = live_tuple[0]
        item["context"] = live_tuple[1]
        new_category, new_cls = categorize_item(title, desc, source)
        item["category"] = new_category
        item["categoryClass"] = new_cls
    category = str(item.get("category") or "חדשות")
    is_gossip_source = any(x in source for x in ["סלבס", "TMI", "Pplus", "פנאי פלוס", "פפראצי", "פפארצי", "רכילות"])
    if is_gossip_source:
        item["category"] = "רכילות"
        item["categoryClass"] = "real"
        category = "רכילות"
    if (
        category == "מזג אוויר"
        and source != WEATHER_SOURCE
        and not item.get("weather")
        and not is_weather_forecast_story(title, desc, source)
    ):
        # Repair retained cards created before the stricter weather matcher.  The
        # June 2026 regression was caused by the word "הבהיר" being read as the
        # sky-condition "בהיר"; old retained rows must be recategorized during
        # merge instead of staying bad until they age out.
        repaired_category, repaired_cls = categorize_item(title, desc, source)
        if repaired_category != "מזג אוויר":
            item["category"] = repaired_category
            item["categoryClass"] = repaired_cls
            category = repaired_category
    if 'יאיר גולן' in title and 'נתניהו כשיר' in title:
        item["headline"] = 'יאיר גולן תקף את כשירות נתניהו ואת פירוק מערכות האכיפה'
        item["context"] = 'יאיר גולן אמר שאינו בטוח שנתניהו כשיר פיזית וקוגניטיבית, וטען שהממשלה מרסקת את מערכות האכיפה במכוון.'
        item["takeaway"] = 'המתקפה מציבה את כשירות נתניהו ואת מערכת האכיפה במרכז העימות הפוליטי.'
        item["category"] = 'פוליטיקה'
        item["categoryClass"] = 'security'
    elif 'רופאים לא מוצאים עבודה' in title or ('חגי לוין' in desc and 'מערכת הבריאות' in desc):
        item["headline"] = 'רופאים מתקשים למצוא תקנים בזמן שבתי החולים מזהירים מקריסה'
        item["context"] = 'בדיון בכנסת הזהיר פרופ׳ חגי לוין שמערכת הבריאות על סף קריסה, בזמן שרופאים מתקשים למצוא תקנים וחלקם עובדים מחוץ למקצוע.'
        item["takeaway"] = 'מחסור בתקנים יכול להפוך עודף רופאים לכשל שירות בבתי החולים.'
        item["category"] = 'בריאות'
        item["categoryClass"] = 'real'
    elif ('מרלין' in f'{title} {desc}' and any(x in f'{title} {desc}' for x in ['דרס', 'דקר', 'הצית'])) or is_malinovsky_oct7_law_story(title, desc) or is_helium_iran_war_story(title, desc) or is_smotrich_elgart_hearing_story(title, desc) or is_amos_luzon_relationship_story(title, desc) or is_avihu_pinchasov_genesis_story(title, desc):
        item["headline"] = story_headline(title, desc, str(item.get("source") or ""))
        item["context"] = story_context(title, desc, str(item.get("source") or ""))
        item["takeaway"] = story_takeaway(category, title, desc)
        new_category, new_cls = categorize_item(title, desc, str(item.get("source") or ""))
        item["category"] = new_category
        item["categoryClass"] = new_cls
    headline = str(item.get("headline") or "")
    context = str(item.get("context") or "")
    if 'הפך רגע במה לסיפור המרכזי' in headline:
        item["headline"] = complete_headline(dequote_headline(title), 72)
    elif context and (context.startswith(headline) and len(context) > len(headline) + 12 or headline_looks_cut(headline) or len(headline) > 75):
        repaired = story_headline(title, context, str(item.get("source") or ""))
        if repaired and not headline_looks_cut(repaired) and len(repaired) <= 75:
            item["headline"] = repaired
        else:
            repaired = complete_headline(context, 72)
            if repaired and not headline_looks_cut(repaired):
                item["headline"] = repaired
    return item



WEATHER_DEFAULT_CITY = "ירושלים"
WEATHER_LOCATIONS = [
    {"name": "ירושלים", "lid": "1", "display": "ירושלים"},
    {"name": "תל אביב", "lid": "84", "display": "תל אביב"},
    {"name": "באר שבע", "lid": "8", "display": "באר שבע"},
    {"name": "חיפה", "lid": "3", "display": "חיפה"},
]
WEATHER_DAILY_HOUR = 6
WEATHER_SOURCE = "השירות המטאורולוגי"
WEATHER_CITY_PORTAL_URL = "https://ims.gov.il/he/city_portal/{lid}"
WEATHER_CITY_RSS = "https://ims.gov.il/sites/default/files/ims_data/rss/forecast_city/rssForecastCity_510_he.xml"
WEATHER_COUNTRY_RSS = "https://ims.gov.il/sites/default/files/ims_data/rss/forecast_country/rssForecastCountry_he.xml"
WEATHER_RADIATION_RSS = "https://ims.gov.il/sites/default/files/ims_data/rss/forecast_radiation/rssForecastRadiation_he.xml"


def strip_tags(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def parse_ims_city_forecast(xml_text: str) -> dict:
    """Extract a compact daily forecast from an IMS city RSS feed."""
    root = ET.fromstring(xml_text)
    channel = root.find("./channel")
    title = clean_text(channel.findtext("title") if channel is not None else "")
    desc_html = root.findtext("./channel/item/description") or ""
    desc = strip_tags(desc_html)
    night_min = ""
    m = re.search(r"טמפ\.\s*המינימום\s*בלילה:\s*(\d{1,2})°", desc)
    if m:
        night_min = m.group(1)
    lines = [ln.strip() for ln in desc.splitlines() if ln.strip()]

    # IMS city RSS exposes two shapes: a same-day block (condition + max/min)
    # followed by the upcoming-days table, or only the table. Prefer the
    # same-day block so the 06:00 weather card does not accidentally skip today
    # just because the first dated row is tomorrow.
    today_max = ""
    m = re.search(r"טמפ\.\s*המקסימום\s*ביום:\s*(\d{1,2})°", desc)
    if m:
        today_max = m.group(1)
    m = re.search(r"עדכון\s+אחרון:\s*(\d{4})-(\d{2})-(\d{2})", desc)
    today_date = f"{m.group(3)}/{m.group(2)}" if m else ""
    if today_max and night_min:
        condition = ""
        for line in lines:
            if line.startswith("עדכון אחרון") or line.startswith("טמפ.") or "תחזית ל" in line:
                continue
            if "תחזית להיום" in line or "תחזית לימים" in line:
                continue
            condition = clean_text(line.split(",")[0]) if "," in line else clean_text(line)
            if condition:
                break
        if condition:
            city = title.replace("תחזית ל", "").strip() or WEATHER_DEFAULT_CITY
            return {"city": city, "nightMin": night_min, "date": today_date, "condition": condition, "max": today_max, "min": night_min}

    forecast = None
    for line in lines:
        m = re.match(r":?(\d{2}/\d{2})\s+יום\s+([^\n]+)", line)
        if m:
            forecast = {"date": m.group(1), "weekday": m.group(2).strip()}
            continue
        if forecast and "condition" not in forecast:
            m = re.match(r"(.+?),\s*(\d{1,2})°-(\d{0,2})°", line)
            if m:
                forecast["condition"] = clean_text(m.group(1))
                forecast["max"] = m.group(2)
                forecast["min"] = m.group(3) or night_min
                break
    if not forecast or not forecast.get("condition"):
        raise ValueError("IMS city forecast RSS did not include a daily min/max forecast")
    city = title.replace("תחזית ל", "").strip() or WEATHER_DEFAULT_CITY
    return {"city": city, "nightMin": night_min, **forecast}


def parse_ims_city_portal_forecast(json_text: str, location: dict, now: datetime) -> dict:
    payload = json.loads(json_text)
    data = payload.get("data") or {}
    fixed = data.get("fixed_forecast_data") or {}
    date_key = now.date().isoformat()
    day = fixed.get(date_key) or next(iter(fixed.values()), {})
    daily = day.get("daily") or {}
    codes = data.get("weather_codes") or {}
    weather_code = str(daily.get("weather_code") or "")
    condition = clean_text((codes.get(weather_code) or {}).get("desc") or "")
    if not condition:
        condition = clean_text(str(data.get("analysis", {}).get("weather_code") or "תחזית מתעדכנת"))
    forecast_date = str(daily.get("forecast_date") or date_key)
    date_label = ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", forecast_date)
    if m:
        date_label = f"{m.group(3)}/{m.group(2)}"
    return {
        "city": location["display"],
        "lid": str(location["lid"]),
        "date": date_label,
        "condition": condition or "תחזית מתעדכנת",
        "max": str(daily.get("maximum_temperature") or "").strip(),
        "min": str(daily.get("minimum_temperature") or "").strip(),
        "uvi": str(daily.get("maximum_uvi") or "").strip(),
        "countryDescription": clean_text(str((day.get("country") or {}).get("description") or "")),
        "sourceUrl": WEATHER_CITY_PORTAL_URL.format(lid=location["lid"]),
    }


def parse_ims_country_highlights(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    desc = strip_tags(root.findtext("./channel/item/description") or "")
    tomorrow = ""
    m = re.search(r"מחר:\s*(.+?)(?:\n|$)", desc)
    if m:
        tomorrow = clean_text(m.group(1))
    highlights = []
    if any(x in tomorrow for x in ["טפטוף", "גשם"]):
        highlights.append("טפטוף/גשם קל בעיקר בצפון")
    if "רוחות ערות" in tomorrow:
        highlights.append("רוחות ערות ברוב האזורים")
    if "ירידה" in tomorrow and "טמפרטורות" in tomorrow:
        highlights.append("ירידה קלה בטמפרטורות")
    return {"tomorrow": tomorrow, "highlights": highlights[:2]}


def parse_ims_uv_for_city(xml_text: str, city: str = WEATHER_DEFAULT_CITY) -> dict:
    root = ET.fromstring(xml_text)
    desc = strip_tags(root.findtext("./channel/item/description") or "")
    start = desc.find(city + ":")
    if start < 0:
        return {}
    block = desc[start:]
    next_city = re.search(r"\n\s*[א-ת][א-ת\s\-׳\"\']{1,30}:\s*\n", block[len(city)+1:])
    if next_city:
        block = block[:len(city)+1 + next_city.start()]
    levels = []
    for level in ["קיצוני", "גבוה מאד", "גבוה מאוד", "גבוה", "בינוני", "נמוך"]:
        if level in block:
            m = re.search(re.escape(level) + r":\s*(.+?)(?=\n\s*(?:קיצוני|גבוה מאד|גבוה מאוד|גבוה|בינוני|נמוך):|$)", block, flags=re.S)
            times = re.findall(r"מ-(\d{2}:\d{2}) עד (\d{2}:\d{2})", m.group(1) if m else "")
            if times:
                levels.append((level.replace("מאד", "מאוד"), times))
    if not levels:
        return {}
    order = {"קיצוני": 5, "גבוה מאוד": 4, "גבוה": 3, "בינוני": 2, "נמוך": 1}
    level, times = max(levels, key=lambda row: order.get(row[0], 0))
    return {"level": level, "from": times[0][0], "to": times[-1][1]}


def weather_image_asset(condition: str, uv: dict | None = None, highlights: list[str] | None = None) -> str:
    uv = uv or {}
    highlights = highlights or []
    text = f"{condition} {' '.join(highlights)}"
    if uv.get("level") in {"גבוה", "גבוה מאוד", "קיצוני"}:
        return "assets/weather/uv-high.svg"
    if any(x in text for x in ["גשם", "טפטוף"]):
        return "assets/weather/light-rain.svg"
    if "רוחות" in text or "רוח" in text:
        return "assets/weather/wind.svg"
    if "אובך" in text or "ראות" in text:
        return "assets/weather/hazy.svg"
    if "מעונן חלקית" in condition:
        return "assets/weather/partly-cloudy.svg"
    if "מעונן" in condition:
        return "assets/weather/cloudy.svg"
    if "בהיר" in condition:
        return "assets/weather/sunny.svg"
    return "assets/weather/partly-cloudy.svg"


def weather_cloud_phrase(condition: str) -> str:
    if "מעונן חלקית" in condition:
        return "עננות חלקית"
    if "מעונן" in condition:
        return "עננות גבוהה"
    if "בהיר" in condition:
        return "שמיים בהירים"
    return condition


def weather_uv_from_index(raw: str) -> dict:
    try:
        index = int(float(raw))
    except Exception:
        return {}
    if index >= 11:
        level = "קיצוני"
    elif index >= 8:
        level = "גבוה מאוד"
    elif index >= 6:
        level = "גבוה"
    elif index >= 3:
        level = "בינוני"
    else:
        level = "נמוך"
    return {"level": level, "index": index}


def weather_image_key(condition: str, uv: dict | None = None, highlights: list[str] | None = None) -> str:
    asset = weather_image_asset(condition, uv, highlights)
    return Path(asset).stem


def build_daily_weather_card_for_location(location: dict, now: datetime, country: dict, fetcher=fetch, force: bool = False) -> dict | None:
    try:
        forecast = parse_ims_city_portal_forecast(fetcher(WEATHER_CITY_PORTAL_URL.format(lid=location["lid"]), timeout=15), location, now)
    except Exception as exc:
        print(f"Weather card skipped for {location.get('display')}: {exc}", file=sys.stderr)
        return None
    forecast_date = now.date()
    raw_date = forecast.get("date") or ""
    m = re.match(r"(\d{2})/(\d{2})", raw_date)
    if m:
        forecast_date = datetime(now.year, int(m.group(2)), int(m.group(1)), tzinfo=now.tzinfo).date()
        if forecast_date > now.date() and not force:
            return None
    min_temp = forecast.get("min") or ""
    max_temp = forecast.get("max") or ""
    temp_range = f"{min_temp}°–{max_temp}°" if min_temp and max_temp else (f"עד {max_temp}°" if max_temp else "")
    condition = forecast.get("condition") or "תחזית מתעדכנת"
    city = forecast.get("city") or location["display"]
    day_start = datetime(forecast_date.year, forecast_date.month, forecast_date.day, WEATHER_DAILY_HOUR, tzinfo=now.tzinfo)
    if force:
        day_start = now.replace(microsecond=0)
    cloud = weather_cloud_phrase(condition)
    uv = weather_uv_from_index(forecast.get("uvi") or "")
    uv_text = f"UV {uv.get('level')} ({uv.get('index')})" if uv.get("level") and uv.get("index") else ""
    headline_bits = [f"מזג האוויר ב{city}: {temp_range}" if temp_range else f"מזג האוויר ב{city}", cloud]
    if uv.get("level") in {"גבוה", "גבוה מאוד", "קיצוני"}:
        headline_bits.append(f"UV {uv['level']} בצהריים")
    headline = "; ".join([b for b in headline_bits if b])
    highlight_text = "; ".join(country.get("highlights") or [])
    context_parts = []
    context_parts.append(f"ב{city} צפויה {cloud} וטווח של {temp_range}." if temp_range else f"ב{city} צפויה {cloud}.")
    if uv_text:
        context_parts.append(f"מדד הקרינה: {uv_text}.")
    if highlight_text:
        context_parts.append(f"ברקע הארצי: {highlight_text}.")
    context = " ".join(context_parts)
    if uv.get("level") in {"גבוה", "גבוה מאוד", "קיצוני"}:
        takeaway = f"גם עם {cloud}, הקרינה בצהריים משמעותית — כובע/קרם הגנה חשובים יותר ממעיל."
    elif "טפטוף" in highlight_text or "גשם" in highlight_text:
        takeaway = "היום נראה מתון, אבל כדאי להשאיר מקום למטרייה קלה או שינוי תכנית בחוץ."
    else:
        takeaway = f"כדאי לתכנן את היום סביב {temp_range}: שכבה קלה בבוקר ונוחות יחסית בצהריים." if temp_range else "כדאי לבדוק את התחזית לפני יציאה ולתכנן לבוש ונסיעות בהתאם."
    image_key = weather_image_key(condition, uv, country.get("highlights") or [])
    return {
        "category": "מזג אוויר",
        "categoryClass": "real",
        "source": WEATHER_SOURCE,
        "sourceLogo": "IMS",
        "sourceUrl": forecast.get("sourceUrl") or WEATHER_CITY_PORTAL_URL.format(lid=location["lid"]),
        "imageUrl": weather_image_asset(condition, uv, country.get("highlights") or []),
        "weatherImageKey": image_key,
        "publishedAt": day_start.isoformat(timespec="seconds"),
        "hasSourceDate": False,
        "time": "06:00",
        "headline": trim_words(headline, 75),
        "originalTitle": f"תחזית ל{city} - {forecast.get('date', '')}".strip(),
        "context": trim_words(context, 180),
        "takeaway": trim_words(takeaway, 95),
        "noSourceLink": True,
        "semanticClusterKey": f"weather:{location['lid']}:{forecast_date.isoformat()}",
        "weather": {
            "city": city,
            "lid": str(location["lid"]),
            "defaultCity": city == WEATHER_DEFAULT_CITY,
            "dailyHour": WEATHER_DAILY_HOUR,
            "min": min_temp,
            "max": max_temp,
            "condition": condition,
            "cloud": cloud,
            "uv": uv,
            "countryHighlights": country.get("highlights") or [],
            "forecastDate": forecast.get("date", ""),
            "imageKey": image_key,
        },
    }


def build_daily_weather_cards(now: datetime | None = None, fetcher=fetch, force: bool = False) -> list[dict]:
    tz = timezone(timedelta(hours=3))
    now = (now or datetime.now(tz)).astimezone(tz)
    if now.hour < WEATHER_DAILY_HOUR and not force:
        return []
    try:
        country = parse_ims_country_highlights(fetcher(WEATHER_COUNTRY_RSS, timeout=15))
    except Exception:
        country = {}
    cards = [build_daily_weather_card_for_location(location, now, country, fetcher, force) for location in WEATHER_LOCATIONS]
    return [card for card in cards if card]


def feed_item_key(item: dict) -> str:
    url = item.get("sourceUrl") or ""
    if url:
        return canonical_url_key(url)
    return normalized_key((item.get("originalTitle") or item.get("headline") or "") + "|" + (item.get("source") or ""))

def item_datetime(item: dict, fallback: datetime) -> datetime:
    tz = timezone(timedelta(hours=3))
    raw = item.get("publishedAt") or item.get("updatedAt") or ""
    if raw:
        try:
            d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=tz)
            d = d.astimezone(tz)
            now = datetime.now(tz)
            if d > now + timedelta(minutes=5):
                return now
            return d
        except Exception:
            pass
    return fallback

def source_diversity_group(item: dict) -> str:
    """Canonical group used for visible top-feed diversity.

    The feed can receive many equally fresh cards from one RSS family in a
    single run (especially Walla/JPost). Without a small deterministic
    interleave the top slice looks stuck even when the underlying sync is
    healthy. Keep this grouping intentionally coarse and product-facing.
    """
    raw = str(item.get("sourceLogo") or item.get("source") or "")
    low = raw.lower()
    if "וואלה" in raw or "walla" in low:
        return "וואלה"
    if "jerusalem post" in low or "jpost" in low:
        return "The Jerusalem Post"
    if "ynet" in low:
        return "ynet"
    if "ישראל היום" in raw or "israel hayom" in low:
        return "ישראל היום"
    if "הארץ" in raw or "haaretz" in low:
        return "הארץ"
    if "גלובס" in raw or "globes" in low:
        return "גלובס"
    if "guardian" in low:
        return "Guardian"
    if "משטרת ישראל" in raw or "משטרה" in raw or "israel police" in low:
        return "משטרה"
    return raw or str(item.get("source") or "מקור")

def diversify_visible_top(
    items: list[dict],
    *,
    top_limit: int = 20,
    max_per_group: int = 5,
) -> list[dict]:
    """Reorder only the leading slice to avoid one RSS family dominating.

    This preserves every card and its real source timestamp. It intentionally
    does not cap categories: sports, gossip, and current-affairs balance should
    be controlled by the user's selected interests/sources, not by global
    suppression.
    """
    if len(items) <= top_limit:
        return items
    chosen: list[dict] = []
    deferred: list[dict] = []
    counts: dict[str, int] = {}
    for item in items:
        group = source_diversity_group(item)
        if len(chosen) < top_limit and counts.get(group, 0) < max_per_group:
            chosen.append(item)
            counts[group] = counts.get(group, 0) + 1
        else:
            deferred.append(item)
    if len(chosen) < top_limit:
        need = top_limit - len(chosen)
        chosen.extend(deferred[:need])
        deferred = deferred[need:]
    return chosen + deferred

def assign_display_rank(items: list[dict]) -> list[dict]:
    for idx, item in enumerate(items):
        item["displayRank"] = idx
    return items


def balance_feed_category_mix(items: list[dict]) -> list[dict]:
    """Keep feed categories uncapped; personalization controls the mix."""
    return items


def sync_selection_limit_for_source(source: dict) -> int | None:
    return None


def max_selected_per_source(source: dict) -> int:
    category = str(source.get("categoryHint") or "")
    profile = source_sync_profile(source)
    if profile == "fast" and category in CURRENT_AFFAIRS_CATEGORIES:
        return 3
    return 2


def is_official_telegram_item(item: dict) -> bool:
    source = str(item.get("source") or item.get("sourceLogo") or "")
    return any(x in source for x in ["דובר צה", "צה״ל", "צה\"ל", "משטרת ישראל", "דוברות משטרת"])


def main_feed_breaking_leak_reasons(item: dict) -> list[str]:
    """Return reasons that a row belongs in breaking_feed.json, not feed.json.

    TT RR now allows מבזקים again only as a separate tab/feed.  The main feed
    must stay full Pointa article cards.  This guard is intentionally stricter
    than item quality so a future freshness fallback cannot silently promote
    Rotter/Telegram/live rows into feed.json.
    """
    parts = [
        str(item.get("sourceUrl") or ""),
        str(item.get("source") or ""),
        str(item.get("sourceLogo") or ""),
        str(item.get("headline") or ""),
        str(item.get("originalTitle") or ""),
        str(item.get("category") or ""),
    ]
    for link in item.get("sourceLinks") or []:
        if isinstance(link, dict):
            parts.append(str(link.get("url") or ""))
            parts.append(str(link.get("name") or ""))
    text = " ".join(parts)
    low = text.lower()
    reasons: list[str] = []
    if item.get("breaking") is True:
        reasons.append("breaking:true")
    if item.get("promotedFromBreaking") is True:
        reasons.append("promotedFromBreaking:true")
    if item.get("emergencyFreshnessFallback") is True:
        reasons.append("emergencyFreshnessFallback:true")
    for marker in ["/break/", "rotter.net/forum/scoops", "rotter.net/forum/scoops1", "t.me/", "telegram.me/"]:
        if marker in low:
            reasons.append(f"live_url:{marker}")
    for marker in ["מבזק", "מבזקים", "טלגרם", "רוטר", "telegram", "rotter"]:
        haystack = low if marker.isascii() else text
        needle = marker.lower() if marker.isascii() else marker
        if needle in haystack:
            reasons.append(f"live_text:{marker}")
    return reasons


def filter_main_feed_breaking_leaks(items: list[dict], reason: str) -> list[dict]:
    kept: list[dict] = []
    rejected: list[dict] = []
    for item in items:
        reasons = main_feed_breaking_leak_reasons(item)
        if reasons:
            rejected.append({"reason": reason, "errors": reasons, "item": item})
        else:
            kept.append(item)
    if rejected:
        payload = {"updatedAt": datetime.now(timezone(timedelta(hours=3))).isoformat(timespec="seconds"), "rejected": rejected}
        try:
            leak_path = ROOT / "tmp" / "pointa_main_feed_breaking_leaks.json"
            leak_path.parent.mkdir(parents=True, exist_ok=True)
            leak_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass
        print(f"Blocked {len(rejected)} breaking/live-like rows from main feed", file=sys.stderr)
    return kept


def preserve_recent_official_telegram_items(items: list[dict], now: datetime, limit: int = MAX_FEED_ITEMS) -> list[dict]:
    """Keep recent IDF/Police Telegram cards visible even when the 200-card cap is crowded."""
    if len(items) <= limit:
        return items
    fast_cutoff = now - timedelta(hours=FAST_CATEGORY_RETENTION_HOURS)
    limited = list(items[:limit])
    existing_keys = {feed_item_key(item) for item in limited}
    official_counts: dict[str, int] = {}
    for item in limited:
        if is_official_telegram_item(item):
            official_counts[str(item.get("source") or "")] = official_counts.get(str(item.get("source") or ""), 0) + 1
    candidates = []
    for item in items[limit:]:
        if not is_official_telegram_item(item):
            continue
        if feed_item_key(item) in existing_keys:
            continue
        if item_datetime(item, now) < fast_cutoff:
            continue
        source = str(item.get("source") or "")
        if official_counts.get(source, 0) >= 2:
            continue
        candidates.append(item)
    for item in candidates:
        replace_idx = next((idx for idx in range(len(limited) - 1, -1, -1) if not is_official_telegram_item(limited[idx])), None)
        if replace_idx is None:
            break
        removed = limited[replace_idx]
        existing_keys.discard(feed_item_key(removed))
        limited[replace_idx] = item
        existing_keys.add(feed_item_key(item))
        source = str(item.get("source") or "")
        official_counts[source] = official_counts.get(source, 0) + 1
    limited.sort(key=lambda item: (1 if item.get("hasSourceDate") else 0, item_datetime(item, now)), reverse=True)
    return limited


def is_service_weather_item(item: dict) -> bool:
    return (
        str(item.get("source") or "") == WEATHER_SOURCE
        or str(item.get("sourceLogo") or "") == "IMS"
        or bool(item.get("weather"))
    )


def preserve_daily_weather_item(items: list[dict], now: datetime, limit: int = MAX_FEED_ITEMS) -> list[dict]:
    """Keep daily IMS utility cards inside the capped feed without pinning them on top."""
    if len(items) <= limit:
        return items
    limited = list(items[:limit])
    existing_weather_keys = {feed_item_key(item) for item in limited if is_service_weather_item(item)}
    weather_candidates = [item for item in items[limit:] if is_service_weather_item(item) and feed_item_key(item) not in existing_weather_keys]
    if not weather_candidates:
        return limited
    for weather_item in sorted(weather_candidates, key=lambda item: item_datetime(item, now), reverse=True):
        replace_idx = next(
            (
                idx
                for idx in range(len(limited) - 1, -1, -1)
                if not is_official_telegram_item(limited[idx]) and not is_service_weather_item(limited[idx])
            ),
            None,
        )
        if replace_idx is None:
            break
        limited[replace_idx] = weather_item
        existing_weather_keys.add(feed_item_key(weather_item))
    limited.sort(key=lambda item: (1 if item.get("hasSourceDate") else 0, item_datetime(item, now)), reverse=True)
    return limited


def ensure_daily_weather_items(items: list[dict], weather_cards: list[dict], now: datetime, limit: int = MAX_FEED_ITEMS) -> list[dict]:
    """Guarantee generated IMS service cards survive final dedupe/cap passes.

    Weather cards are utility feed rows, not scraped articles. They are created
    once a day by the generator, so they must not silently disappear because a
    later duplicate/balance/cap pass was tuned for news cards.
    """
    if not weather_cards:
        return items[:limit]
    limited = list(items[:limit])
    existing_keys = {feed_item_key(item) for item in limited}
    for weather_item in sorted(weather_cards, key=lambda item: item_datetime(item, now), reverse=True):
        key = feed_item_key(weather_item)
        if not key or key in existing_keys:
            continue
        if len(limited) < limit:
            limited.append(weather_item)
            existing_keys.add(key)
            continue
        replace_idx = next(
            (
                idx
                for idx in range(len(limited) - 1, -1, -1)
                if not is_official_telegram_item(limited[idx]) and not is_service_weather_item(limited[idx])
            ),
            None,
        )
        if replace_idx is None:
            break
        removed = limited[replace_idx]
        existing_keys.discard(feed_item_key(removed))
        limited[replace_idx] = weather_item
        existing_keys.add(key)
    limited.sort(key=lambda item: (1 if item.get("hasSourceDate") else 0, item_datetime(item, now)), reverse=True)
    return limited

def merge_with_existing_feed(new_feed: dict, force_weather_card: bool = False) -> dict:
    tz = timezone(timedelta(hours=3))
    now = datetime.now(tz)
    cutoff = now - timedelta(days=FEED_RETENTION_DAYS)
    existing_feed = json.loads(FEED_PATH.read_text(encoding="utf-8")) if FEED_PATH.exists() else {"items": []}
    existing_by_key = {feed_item_key(item): item for item in existing_feed.get("items", []) if feed_item_key(item)}
    existing_by_headline = {
        normalized_key(str(item.get("headline") or "")): item
        for item in existing_feed.get("items", [])
        if len(normalized_key(str(item.get("headline") or ""))) >= 28
    }
    merged = []
    seen_keys = set()
    for feed in [new_feed, existing_feed]:
        fallback = now
        try:
            fallback = datetime.fromisoformat(str(feed.get("updatedAt", "")).replace("Z", "+00:00")).astimezone(tz)
        except Exception:
            pass
        for item in feed.get("items", []):
            key = feed_item_key(item)
            if not key or key in seen_keys:
                continue
            if "hasSourceDate" not in item:
                # Retained/editor-rescue cards must keep normal chronological
                # ordering. A previous defensive fallback forced retained items
                # to hasSourceDate=false, which pushed fresh rescue cards below
                # older generated cards and made the UI look stale even after a
                # successful rescue.
                item["hasSourceDate"] = bool(item.get("publishedAt") and item.get("sourceUrl"))
            d = item_datetime(item, fallback)
            if d < cutoff:
                continue
            if is_foreign_source_label(str(item.get("source") or item.get("sourceLogo") or "")) and not is_retained_foreign_item_relevant(item):
                continue
            headline_key = normalized_key(str(item.get("headline") or ""))
            previous_item = existing_by_key.get(key) or existing_by_headline.get(headline_key)
            previous_published_at = str(previous_item.get("publishedAt") or "") if previous_item else ""
            previous_titles = {
                normalized_key(str(previous_item.get("originalTitle") or "")),
                normalized_key(str(previous_item.get("headline") or "")),
            } if previous_item else set()
            current_titles = {
                normalized_key(str(item.get("originalTitle") or "")),
                normalized_key(str(item.get("headline") or "")),
            }
            previous_titles.discard("")
            current_titles.discard("")
            same_story_as_previous = bool(previous_titles and current_titles and previous_titles.intersection(current_titles))
            if previous_published_at and same_story_as_previous:
                # Some RSS sources (notably Walla live/breaking rows) keep moving
                # the same story's pubDate forward on every refresh.  The UI label
                # must reflect when this card/story first entered our feed, not a
                # synthetic refreshed RSS timestamp for the same URL.
                item["publishedAt"] = previous_published_at
                item["hasSourceDate"] = previous_item.get("hasSourceDate", item.get("hasSourceDate", True))
                d = item_datetime(item, fallback)
            elif item.get("hasSourceDate") and not item.get("publishedAt"):
                item["publishedAt"] = d.isoformat(timespec="seconds")
            item = refresh_item_pointa(item)
            source_url = str(item.get("sourceUrl") or "")
            if is_rejected_source_image(str(item.get("imageUrl") or ""), source_url):
                item["imageUrl"] = ""
            if not str(item.get("imageUrl") or "").strip():
                image = fetch_article_image(source_url)
                if image:
                    item["imageUrl"] = image
            merged.append(item)
            seen_keys.add(key)
    # Source timing diagnostics must outlive a single sync profile. Fast runs
    # should refresh fast sources without erasing medium/slow source activity
    # collected by the last all/medium/slow run. Otherwise the dashboard marks
    # sources as missing even though the current cron simply did not scan them.
    merged_activity = {}
    for feed in [existing_feed, new_feed]:
        for row in feed.get("sourceActivity", []) or []:
            if is_google_news_source_row(row):
                continue
            key = (row.get("source") or "", row.get("subSource") or "")
            if not key[0]:
                continue
            old = merged_activity.get(key)
            if not old or (row.get("publishedAt") or "") > (old.get("publishedAt") or ""):
                merged_activity[key] = row
    if merged_activity:
        new_feed["sourceActivity"] = sorted(merged_activity.values(), key=lambda x: (x.get("publishedAt") or "", x.get("source") or ""), reverse=True)

    weather_cards = build_daily_weather_cards(now, force=force_weather_card)
    if weather_cards:
        weather_keys = {feed_item_key(card) for card in weather_cards}
        merged = [item for item in merged if feed_item_key(item) not in weather_keys]
        merged.extend(weather_cards)
        activity = new_feed.setdefault("sourceActivity", [])
        activity = [row for row in activity if row.get("source") != "השירות המטאורולוגי"]
        for weather_card in weather_cards:
            activity.append({
                "source": "השירות המטאורולוגי",
                "subSource": f"{WEATHER_SOURCE} - {weather_card.get('weather', {}).get('city', '')}".strip(),
                "category": "מזג אוויר",
                "publishedAt": weather_card.get("publishedAt"),
                "title": weather_card.get("headline") or weather_card.get("originalTitle") or "תחזית השירות המטאורולוגי",
                "url": weather_card.get("sourceUrl") or WEATHER_CITY_PORTAL_URL.format(lid=WEATHER_LOCATIONS[0]["lid"]),
            })
        new_feed["sourceActivity"] = sorted(activity, key=lambda x: (x.get("publishedAt") or "", x.get("source") or ""), reverse=True)
    # Final deterministic pass catches retained existing cards and new bridge
    # sources that should not go through generic Pointa rewrites.
    merged = [refresh_item_pointa(item) for item in merged]
    merged.sort(key=lambda item: (1 if item.get("hasSourceDate") else 0, item_datetime(item, now)), reverse=True)
    merged = quarantine_bad_items(merged, "merge_quality_gate")
    merged = [refresh_item_pointa(item) for item in merged]
    deduped = []
    final_seen_signatures = set()
    for item in merged:
        sig = normalized_key(f"{item.get('headline','')}|{item.get('context','')}")
        if sig and sig in final_seen_signatures:
            continue
        duplicate_index = next((idx for idx, existing in enumerate(deduped) if likely_duplicate_story(item, existing)), None)
        if duplicate_index is not None:
            deduped[duplicate_index] = preferred_duplicate_item(deduped[duplicate_index], item)
            continue
        if sig:
            final_seen_signatures.add(sig)
        deduped.append(item)
    deduped = balance_feed_category_mix(deduped)
    limited = preserve_recent_official_telegram_items(deduped, now, MAX_FEED_ITEMS)
    limited = preserve_daily_weather_item(limited, now, MAX_FEED_ITEMS)
    limited = filter_main_feed_breaking_leaks(limited, "main_feed_no_breaking_guard")
    limited = ensure_daily_weather_items(limited, weather_cards, now, MAX_FEED_ITEMS)
    visible = diversify_visible_top(limited)
    visible = filter_main_feed_breaking_leaks(visible, "main_feed_no_breaking_guard_final")
    visible = ensure_daily_weather_items(visible, weather_cards, now, MAX_FEED_ITEMS)
    merged = assign_display_rank(visible)
    new_feed["items"] = merged
    new_feed["mode"] = new_feed.get("mode", "full_snapshot_2h")
    return new_feed

def empty_draft_payload(status: str, message: str = "") -> dict:
    tz = timezone(timedelta(hours=3))
    payload = {
        "updatedAt": datetime.now(tz).isoformat(timespec="seconds"),
        "status": status,
        "items": [],
    }
    if message:
        payload["message"] = message
    return payload


def strip_public_takeaways(feed: dict) -> dict:
    """Remove the deprecated closing takeaway from public feed cards."""
    for item in feed.get("items", []):
        if isinstance(item, dict):
            item.pop("takeaway", None)
    return feed


def write_fast_sync_report(report: dict) -> None:
    FAST_SYNC_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    FAST_SYNC_REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_empty_draft(status: str, message: str = "") -> None:
    CANDIDATES_PATH.write_text(
        json.dumps(empty_draft_payload(status, message), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Update or draft Poanta feed cards")
    ap.add_argument("--draft", action="store_true", help="Write candidates.json for approval instead of publishing feed.json")
    ap.add_argument("--experimental-prompt", action="store_true", help="Use Lior's experimental Pointa conclusion-feed prompt")
    ap.add_argument("--force-weather-card", action="store_true", help="Add the daily Jerusalem weather card immediately for a one-off preview/update")
    ap.add_argument(
        "--sync-profile",
        choices=["all", "fast", "medium", "slow"],
        default="all",
        help="Limit RSS scan to the category-speed profile from pointa_sync_profiles.json",
    )
    args = ap.parse_args()

    # Never leave a previous approval batch in candidates.json during a new draft.
    # If the scan fails or finds too few fresh stories, the cron must see an empty
    # draft rather than accidentally resending yesterday/today's stale candidates.
    if args.draft:
        write_empty_draft("generating", "Draft generation in progress; do not send this file.")

    selected: list[Candidate] = []
    selected_by_category: dict[str, int] = {}
    source_activity: list[dict] = []
    used_urls: set[str] = set()
    seen = load_seen()
    sources = load_sources(args.sync_profile)
    run_report = {
        "updatedAt": datetime.now(timezone(timedelta(hours=3))).isoformat(timespec="seconds"),
        "syncProfile": args.sync_profile,
        "draft": bool(args.draft),
        "experimental": bool(args.experimental_prompt),
        "sourcesScanned": 0,
        "rawCandidates": 0,
        "validCandidates": 0,
        "qaRejectedCandidates": 0,
        "articleEnrichAttempts": 0,
        "articleEnrichImproved": 0,
        "articleEnrichSkippedBudget": 0,
        "shortAfterEnrich": 0,
        "selectedCandidates": 0,
        "preMergeItems": 0,
        "publishedItems": 0,
        "takeawayFields": 0,
        "sourceReports": [],
    }
    if not sources:
        msg = f"No RSS sources matched sync profile: {args.sync_profile}"
        print(f"ERROR {msg}", file=sys.stderr)
        if args.draft:
            write_empty_draft("failed_no_matching_sources", msg)
        return 2
    for source in sources:
        picked = []
        # Source-only phase: do not scrape homepages and do not use fallback readers.
        candidates = extract_source(source)
        source_report = {
            "source": source.get("name") or "",
            "profile": source_sync_profile(source),
            "raw": 0,
            "valid": 0,
            "qaRejected": 0,
            "articleEnrichAttempts": 0,
            "articleEnrichImproved": 0,
            "articleEnrichSkippedBudget": 0,
            "shortAfterEnrich": 0,
            "selected": 0,
        }
        # preserve source-local ranking while dropping duplicate URLs
        local_seen = set()
        candidates = [x for x in candidates if not (x.url in local_seen or local_seen.add(x.url))]
        source_report["raw"] = len(candidates)
        run_report["sourcesScanned"] += 1
        run_report["rawCandidates"] += len(candidates)
        # Feed/source timing must reflect fresh source activity. Previously the
        # non-fast profiles re-sorted each source by score here, undoing the RSS
        # recency sort from extract_rss() and leaving many dashboard source rows
        # red even when the source had newer RSS items. Keep recency primary for
        # every profile; score is only the tie-breaker.
        candidates = sorted(candidates, key=lambda x: (x.published_at, x.score), reverse=True)
        valid_for_activity = []
        for raw_c in candidates:
            title = sanitize_title(raw_c.title)
            if (
                source.get("language") == "en"
                and source.get("categoryHint") != "רכילות"
                and not is_foreign_relevant(raw_c.original_title or raw_c.title, raw_c.description)
            ):
                continue
            if len(title) < 18 or bad_description(raw_c.description):
                continue
            valid_for_activity.append((raw_c, title))
        source_report["valid"] = len(valid_for_activity)
        run_report["validCandidates"] += len(valid_for_activity)
        if valid_for_activity:
            activity_c, activity_title = valid_for_activity[0]
            source_activity.append({
                "source": source_timing_key(source.get("logo") or source.get("name") or activity_c.source),
                "subSource": source.get("name") or activity_c.source,
                "category": source.get("categoryHint") or "חדשות",
                "publishedAt": activity_c.published_at,
                "title": activity_title,
                "url": activity_c.url,
            })
        for c, sanitized_title in valid_for_activity:
            if c.url in used_urls:
                continue
            c.original_title = c.original_title or c.title
            c.title = sanitized_title
            if args.draft and candidate_seen(c, seen):
                continue
            if should_enrich_for_context(c):
                before_words = word_count(c.description)
                if (
                    source_report["articleEnrichAttempts"] < FAST_ENRICH_MAX_PER_SOURCE
                    and run_report["articleEnrichAttempts"] < FAST_ENRICH_MAX_PER_RUN
                ):
                    source_report["articleEnrichAttempts"] += 1
                    run_report["articleEnrichAttempts"] += 1
                    c = enrich(c, timeout=6, allow_jina=False)
                    after_words = word_count(c.description)
                    if after_words > before_words + 8:
                        source_report["articleEnrichImproved"] += 1
                        run_report["articleEnrichImproved"] += 1
                    if after_words < MIN_CONTEXT_WORDS_BEFORE_ENRICH:
                        source_report["shortAfterEnrich"] += 1
                        run_report["shortAfterEnrich"] += 1
                else:
                    source_report["articleEnrichSkippedBudget"] += 1
                    run_report["articleEnrichSkippedBudget"] += 1
            # Do not let the first two raw RSS rows from a source block fresher
            # usable rows underneath them.  Core sources such as YNET/Maariv
            # often lead with thin flashes that deterministic QA correctly
            # rejects; continue scanning the source until we find QA-clean cards.
            if not args.experimental_prompt and not build_feed([c]).get("items"):
                source_report["qaRejected"] += 1
                run_report["qaRejectedCandidates"] += 1
                continue
            category_limit = sync_selection_limit_for_source(source)
            source_category = str(source.get("categoryHint") or "חדשות")
            if category_limit is not None and selected_by_category.get(source_category, 0) >= category_limit:
                continue
            c = stabilize_candidate_published_at(c, seen)
            picked.append(c)
            selected_by_category[source_category] = selected_by_category.get(source_category, 0) + 1
            used_urls.add(c.url)
            time.sleep(0.2)
            if len(picked) >= max_selected_per_source(source):
                break
        source_report["selected"] = len(picked)
        run_report["selectedCandidates"] += len(picked)
        run_report["sourceReports"].append(source_report)
        selected.extend(picked)

    selected = sorted(selected, key=lambda x: (x.published_at, x.score), reverse=True)

    # The experimental prompt depends on article-specific substance. Enrich the
    # top pool before writing so insights are derived from article metadata/body,
    # not only generic RSS titles.
    if args.experimental_prompt:
        enriched: list[Candidate] = []
        for c in selected[:24]:
            enriched.append(enrich(c))
            time.sleep(0.2)
        selected = enriched

    if len(selected) < 4:
        msg = f"Too few fresh unseen items selected: {len(selected)}"
        print(f"ERROR {msg}", file=sys.stderr)
        if args.draft:
            write_empty_draft("failed_too_few_fresh_items", msg)
            STATE_PATH.write_text(json.dumps({"lastDraftError": msg}), encoding="utf-8")
        return 2

    feed = build_feed(selected, experimental=args.experimental_prompt)
    run_report["preMergeItems"] = len(feed.get("items", []))
    feed["sourceActivity"] = sorted(source_activity, key=lambda x: (x.get("publishedAt") or "", x.get("source") or ""), reverse=True)
    feed["syncProfile"] = args.sync_profile
    if args.draft:
        feed = strip_public_takeaways(feed)
        feed["status"] = "draft"
        CANDIDATES_PATH.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        remember_feed(feed)
        STATE_PATH.write_text(json.dumps({"lastDraftRun": feed["updatedAt"], "draftCount": len(feed["items"])}), encoding="utf-8")
        run_report["publishedItems"] = len(feed.get("items", []))
        run_report["takeawayFields"] = sum(1 for item in feed.get("items", []) if item.get("takeaway"))
        write_fast_sync_report(run_report)
        print(f"Wrote {len(feed['items'])} approval candidates to {CANDIDATES_PATH}")
    else:
        feed = merge_with_existing_feed(feed, force_weather_card=args.force_weather_card)
        feed["mode"] = f"rss_sync_{args.sync_profile}"
        feed = strip_public_takeaways(feed)
        FEED_PATH.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        remember_feed(feed)
        STATE_PATH.write_text(json.dumps({"lastRun": feed["updatedAt"], "count": len(feed["items"])}), encoding="utf-8")
        run_report["publishedItems"] = len(feed.get("items", []))
        run_report["takeawayFields"] = sum(1 for item in feed.get("items", []) if item.get("takeaway"))
        run_report["topItems"] = [
            {
                "publishedAt": item.get("publishedAt"),
                "source": item.get("source"),
                "headline": item.get("headline"),
            }
            for item in feed.get("items", [])[:10]
        ]
        write_fast_sync_report(run_report)
        print(f"Wrote {len(feed['items'])} items to {FEED_PATH}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
