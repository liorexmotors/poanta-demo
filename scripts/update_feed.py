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
MAX_FEED_ITEMS = 200
FEED_RETENTION_DAYS = 7
FAST_CATEGORY_RETENTION_HOURS = 18
RSS_SOURCES_PATH = ROOT / "rss_sources.json"
SYNC_PROFILES_PATH = ROOT / "pointa_sync_profiles.json"
EXPERIMENTAL_VERSION = "20260517-pointa-fast-answer-v2"

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
    "דלק", "ממשלה", "ביטוח", "צרכנים", "הייטק", "בורסה", "רכב", "כביש", "תחבורה", "ספורט", "כדורגל", "נבחרת", "ליגת", "בחירות", "כנסת", "תקציב",
]
CATEGORY_RULES = [
    # Order matters: prefer specific practical topics over broad local/world buckets.
    ("משפט", "security", ["בגץ", "בג\"ץ", "בית המשפט", "עליון", "שופט", "שופטים", "יועמ\"ש", "פרקליטות", "כתב אישום", "עתירה", "חוק", "חקיקה", "משפטי", "legal", "court", "supreme court", "trial"]),
    ("פלילים", "security", ["רצח", "ירי", "דקירה", "חשד", "נעצר", "מעצר", "משטרה", "חקירה", "עבריין", "פשע", "פלילי", "סמים", "אלימות", "אונס", "crime", "police", "shooting", "murder", "arrest"]),
    ("ביטחון", "security", ["איראן", "מלחמה", "צה״ל", "צהל", "פיקוד העורף", "טילים", "ביטחון", "הורמוז", "אמירויות", "לבנון", "חמאס", "חיזבאללה", "פוטין", "קרמלין", "התנקשות", "ביון", "צבא", "טרור", "war", "iran", "russia", "ukraine", "gaza", "israel", "military", "terror"]),
    ("פוליטיקה", "security", ["כנסת", "ממשלה", "בחירות", "קואליציה", "אופוזיציה", "תקציב", "שרים", "ח״כ", "חכים", "נתניהו", "טראמפ", "ביידן", "נשיא", "ראש ממשלה", "politics", "election", "government", "minister", "president", "trump", "white house"]),
    ("נדל״ן", "real", ["נדל", "דירה", "דירות", "בנייה", "פינוי-בינוי", "תל אביב", "דיור", "קרקע", "real estate", "housing"]),
    ("כלכלה", "money", ["ריבית", "מיסים", "מע״מ", "שכר", "מניות", "בורסה", "מחירים", "פיצויים", "עסקים", "אקזיט", "מיליון", "מיליארד", "דולר", "אינפלציה", "markets", "stocks", "economy", "bank", "inflation", "dollar"]),
    ("צרכנות", "money", ["צרכן", "רשתות", "שופרסל", "מחירי", "קניות", "ביטוח", "סופר", "חלב", "consumer", "shopping"]),
    ("טכנולוגיה", "tech", ["AI", "סייבר", "וואטסאפ", "אפל", "גוגל", "אפליקציה", "טכנולוג", "סטארטאפ", "GPT", "tech", "cyber", "apple", "google", "openai"]),
    ("רכב", "real", ["טיסות", "רכבת", "כביש", "רכב", "תחבורה", "דלק", "נתבג", "דובאי", "פקקים", "נהגים", "car", "vehicle", "transport", "flight"]),
    ("בריאות", "real", ["בריאות", "רפואה", "מחקר", "חולים", "תרופה", "תזונה", "כושר", "health", "medical", "medicine", "disease"]),
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
    if "n12" in s or "mako" in s:
        return "N12"
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
    title = re.sub(r"\s*[-–|]\s*(N12|mako|וואלה|ynet|גלובס|ערוץ 14|CNN|BBC|Sky News).*$", "", title, flags=re.I).strip()
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




def image_from_html_fragment(fragment: str) -> str:
    fragment = html.unescape(fragment or "")
    for m in re.finditer(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", fragment, flags=re.I):
        url = clean_text(m.group(1))
        low = url.lower()
        if not url or low.startswith("data:") or ".svg" in low or "logo" in low:
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
        low = url.lower()
        if not url or low.startswith("data:") or ".svg" in low or "logo" in low:
            continue
        return urljoin(link, url)
    return ""

def extract_rss(source: dict) -> list[Candidate]:
    rss_url = source.get("rss")
    if not rss_url:
        return []
    try:
        raw = fetch(rss_url)
        root = ET.fromstring(raw)
    except Exception as e:
        print(f"WARN rss fetch failed {source['name']}: {e}", file=sys.stderr)
        return []
    out = []
    for item in root.findall('.//item'):
        title = sanitize_title(''.join(item.findtext('title') or ''))
        link = clean_text(item.findtext('link') or '')
        raw_desc = item.findtext('description') or ''
        desc = clean_text(re.sub(r'<[^>]+>', ' ', raw_desc))
        published_at = parse_feed_datetime(child_text_by_local(item, {'pubdate', 'published', 'updated', 'date', 'dc:date', 'created'}))
        image = image_from_rss_item(item, link, raw_desc)
        if len(title) < 18 or not link:
            continue
        if source.get("name", "").startswith("גלובס") and "en.globes.co.il" in link:
            continue
        score = score_title(title + ' ' + desc)
        if source.get("language") == "en" or any(x in source.get("name", "") for x in ["BBC", "CNN", "Sky"]):
            score += 20
        if score <= 0:
            continue
        out.append(Candidate(source=source['name'], url=link, title=title, description=desc, score=score, image_url=image, original_title=title, published_at=published_at))
    return sorted(out, key=lambda c: c.score, reverse=True)[:12]


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


def enrich(candidate: Candidate) -> Candidate:
    try:
        raw = fetch(candidate.url, timeout=12)
        parser = parse_html(raw)
    except Exception:
        raw = ""
        parser = parse_html("")

    exact_title = clean_text(parser.meta.get("og:title") or parser.meta.get("twitter:title") or "")
    image = clean_text(parser.meta.get("og:image") or parser.meta.get("twitter:image") or parser.meta.get("image") or "")

    # Some N12/Mako URLs return a Radware block page to direct fetches.
    # In that case, use Jina Reader as a metadata fallback so the footer link
    # still gets the exact source headline instead of the rewritten Poanta title.
    if not exact_title or "Radware Block Page" in raw:
        jina_title, jina_image = fetch_jina_metadata(candidate.url)
        exact_title = jina_title or exact_title
        image = image or jina_image

    if exact_title and len(exact_title) >= 18:
        candidate.original_title = exact_title
        candidate.title = sanitize_title(exact_title) or exact_title
    if image:
        candidate.image_url = urljoin(candidate.url, image)
    desc = clean_text(parser.meta.get("og:description") or parser.meta.get("description") or parser.meta.get("twitter:description") or "")
    if not desc:
        ps = [clean_text(p) for p in parser.paragraphs]
        desc = clean_text(" ".join(p for p in ps if len(p) > 40)[:450])
    if bad_description(desc):
        desc = ""
    candidate.description = desc
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


def categorize_item(title: str, desc: str, source: str) -> tuple[str, str]:
    # With many section RSS feeds enabled, the feed name is a strong signal.
    # Prefer it over incidental keywords in the title/description so sports,
    # car, tech, health and culture feeds are not mislabeled as politics/real estate.
    text = f"{title} {desc} {source}"
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
    if any(x in source for x in ["תרבות", "סלבס", "טלוויזיה", "מוזיקה", "קולנוע", "ספרות", "אמנות", "אוכל", "תיירות", "טיולים", "אופנה", "בית ועיצוב"]):
        return "תרבות", "real"
    if any(x in source for x in ["CNN", "BBC", "Sky News", "סקיי"]):
        fp = foreign_pointa_tuple(title, desc)
        if fp:
            return fp[3], fp[4]
        return categorize(text)
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

def is_foreign_relevant(title: str, desc: str) -> bool:
    """Foreign feeds are allowed only for Israel / Middle East relevance.

    Lior's rule: international sources should not fill Poanta with general world
    news. They are useful when they add outside reporting about Israel, Iran,
    Gaza, Lebanon, the region, Jews/antisemitism, or direct policy/security
    implications for Israel/the Middle East.
    """
    text = f"{title} {desc}".lower()
    if any(k in text for k in FOREIGN_RELEVANCE_KEYWORDS):
        return True
    # Keep a very small safety escape hatch for headlines where the regional
    # hook is in source metadata but not the RSS title/description.
    if "middle east" in text or "mideast" in text:
        return True
    return False


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


def story_headline(title: str, desc: str, source: str) -> str:
    text = f'{title} {desc}'
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


def compact_context(text: str, category: str = '', title: str = '') -> str:
    text = clean_text(text).replace('…', '').replace('...', '').strip(' ,;:-–')
    if len(text) <= 145:
        return text
    sentences = split_sentences(text)
    for sentence in sentences:
        sentence = sentence.replace('…', '').replace('...', '').strip(' ,;:-–')
        if 35 <= len(sentence) <= 145:
            return sentence
    return fallback_context_from_title(title, category)


def story_context(title: str, desc: str, source: str) -> str:
    text = f'{title} {desc}'
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
    if 'מלחמה עם איראן' in text or 'אין מלחמה עם איראן' in text:
        return 'אי־ודאות ביטחונית שוחקת את הציבור גם בלי הכרזה רשמית.'
    if any(x in text for x in ['מט גאלה', 'פטמות', 'נשף']):
        return 'אופנה על השטיח האדום מוכרת דימוי לפני שהיא מוכרת בגד.'
    if any(x in text for x in ['מסעדה', 'תיסגר', 'סגירה מפתיעה']):
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
    if any(x in text for x in ['חברות התעופה', 'האוכל הכי טוב', 'אל על']):
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
    if 'דסה' in text or 'גלוך' in text or 'למקין' in text:
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


def load_seen() -> dict:
    try:
        data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
        urls = set(data.get("urls", []))
        url_keys = set(data.get("urlKeys", [])) | {canonical_url_key(u) for u in urls}
        return {
            "urls": urls,
            "urlKeys": url_keys,
            "titleKeys": set(data.get("titleKeys", [])),
        }
    except Exception:
        return {"urls": set(), "urlKeys": set(), "titleKeys": set()}


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
    for item in feed.get("items", []):
        url = item.get("sourceUrl")
        title = item.get("headline") or ""
        if url:
            seen["urls"].add(url)
            seen.setdefault("urlKeys", set()).add(canonical_url_key(url))
        key = normalized_key(title)
        if key:
            seen["titleKeys"].add(key)
        original_key = normalized_key(item.get("originalTitle") or "")
        if original_key:
            seen["titleKeys"].add(original_key)
    payload = {
        "urls": sorted(seen["urls"]),
        "urlKeys": sorted(seen.get("urlKeys", set())),
        "titleKeys": sorted(seen["titleKeys"]),
        "updatedAt": datetime.now(timezone(timedelta(hours=3))).isoformat(timespec="seconds"),
    }
    SEEN_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def build_feed(candidates: Iterable[Candidate], experimental: bool = False) -> dict:
    items = []
    seen_titles = set()
    for c in candidates:
        key = normalized_key(c.title)
        if key in seen_titles:
            continue
        seen_titles.add(key)
        category, cls = categorize_item(c.title, c.description, c.source)
        if "פיקוד העורף" in c.source:
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
            "takeaway": takeaway,
        }
        if not item_quality_errors(item):
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
    low = image.lower()
    if low.startswith("data:") or ".svg" in low or "logo" in low:
        return ""
    return urljoin(url, image)

def refresh_item_pointa(item: dict) -> dict:
    title = str(item.get("originalTitle") or item.get("headline") or "")
    desc = str(item.get("context") or "")
    source = str(item.get("source") or "")
    if "משטרת ישראל" in source or "דוברות משטרת" in source:
        # Official Telegram notices are already terse operational updates. A
        # second generic rewrite can accidentally promote footer text or make
        # the headline duplicate the summary, so keep the bridge's cleaned card.
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
    category = str(item.get("category") or "חדשות")
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
WEATHER_DEFAULT_CITY_ID = "510"
WEATHER_DAILY_HOUR = 6
WEATHER_SOURCE = "השירות המטאורולוגי"
WEATHER_CITY_RSS = f"https://ims.gov.il/sites/default/files/ims_data/rss/forecast_city/rssForecastCity_{WEATHER_DEFAULT_CITY_ID}_he.xml"
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
    forecast = None
    for line in [ln.strip() for ln in desc.splitlines() if ln.strip()]:
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


def build_daily_weather_card(now: datetime | None = None, fetcher=fetch, force: bool = False) -> dict | None:
    tz = timezone(timedelta(hours=3))
    now = (now or datetime.now(tz)).astimezone(tz)
    if now.hour < WEATHER_DAILY_HOUR and not force:
        return None
    try:
        forecast = parse_ims_city_forecast(fetcher(WEATHER_CITY_RSS, timeout=15))
    except Exception as exc:
        print(f"Weather card skipped: {exc}", file=sys.stderr)
        return None
    try:
        country = parse_ims_country_highlights(fetcher(WEATHER_COUNTRY_RSS, timeout=15))
    except Exception:
        country = {}
    try:
        uv = parse_ims_uv_for_city(fetcher(WEATHER_RADIATION_RSS, timeout=15), WEATHER_DEFAULT_CITY)
    except Exception:
        uv = {}
    forecast_date = now.date()
    raw_date = forecast.get("date") or ""
    m = re.match(r"(\d{2})/(\d{2})", raw_date)
    if m:
        forecast_date = datetime(now.year, int(m.group(2)), int(m.group(1)), tzinfo=tz).date()
        # IMS may publish tomorrow's first day in the evening. The daily card is
        # a 06:00 morning item, so do not surface tomorrow's card tonight.
        if forecast_date > now.date() and not force:
            return None
    min_temp = forecast.get("min") or forecast.get("nightMin") or ""
    max_temp = forecast.get("max") or ""
    temp_range = f"{min_temp}°–{max_temp}°" if min_temp and max_temp else (f"עד {max_temp}°" if max_temp else "")
    condition = forecast.get("condition") or "תחזית מתעדכנת"
    city = WEATHER_DEFAULT_CITY
    day_start = datetime(forecast_date.year, forecast_date.month, forecast_date.day, WEATHER_DAILY_HOUR, tzinfo=tz)
    if force:
        day_start = now.replace(microsecond=0)
    cloud = weather_cloud_phrase(condition)
    uv_text = f"UV {uv.get('level')} {uv.get('from')}–{uv.get('to')}" if uv.get("level") and uv.get("from") and uv.get("to") else ""
    headline_bits = [f"מזג האוויר בירושלים: {temp_range}" if temp_range else "מזג האוויר בירושלים", cloud]
    if uv.get("level") in {"גבוה", "גבוה מאוד", "קיצוני"}:
        headline_bits.append(f"UV {uv['level']} בצהריים")
    headline = "; ".join([b for b in headline_bits if b])
    highlight_text = "; ".join(country.get("highlights") or [])
    context_parts = []
    context_parts.append(f"בירושלים צפויה {cloud} וטווח של {temp_range}." if temp_range else f"בירושלים צפויה {cloud}.")
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
    return {
        "category": "מזג אוויר",
        "categoryClass": "real",
        "source": WEATHER_SOURCE,
        "sourceLogo": "IMS",
        "sourceUrl": WEATHER_CITY_RSS,
        "imageUrl": weather_image_asset(condition, uv, country.get("highlights") or []),
        "publishedAt": day_start.isoformat(timespec="seconds"),
        "hasSourceDate": True,
        "time": "06:00",
        "headline": trim_words(headline, 75),
        "originalTitle": f"תחזית לירושלים - {forecast.get('date', '')}".strip(),
        "context": trim_words(context, 180),
        "takeaway": trim_words(takeaway, 95),
        "noSourceLink": True,
        "weather": {
            "city": city,
            "defaultCity": True,
            "dailyHour": WEATHER_DAILY_HOUR,
            "min": min_temp,
            "max": max_temp,
            "condition": condition,
            "cloud": cloud,
            "uv": uv,
            "countryHighlights": country.get("highlights") or [],
            "forecastDate": forecast.get("date", ""),
        },
    }


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

def merge_with_existing_feed(new_feed: dict, force_weather_card: bool = False) -> dict:
    tz = timezone(timedelta(hours=3))
    now = datetime.now(tz)
    cutoff = now - timedelta(days=FEED_RETENTION_DAYS)
    fast_cutoff = now - timedelta(hours=FAST_CATEGORY_RETENTION_HOURS)
    sync_profiles = load_sync_profiles()
    merged = []
    seen_keys = set()
    for feed in [new_feed, json.loads(FEED_PATH.read_text(encoding="utf-8")) if FEED_PATH.exists() else {"items": []}]:
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
                item["hasSourceDate"] = bool(item.get("publishedAt") and item.get("sourceUrl") and False)
            d = item_datetime(item, fallback)
            if d < cutoff:
                continue
            if category_sync_profile(str(item.get("category") or "חדשות"), sync_profiles) == "fast" and d < fast_cutoff:
                continue
            if item.get("hasSourceDate") and not item.get("publishedAt"):
                item["publishedAt"] = d.isoformat(timespec="seconds")
            item = refresh_item_pointa(item)
            if not str(item.get("imageUrl") or "").strip():
                image = fetch_article_image(str(item.get("sourceUrl") or ""))
                if image:
                    item["imageUrl"] = image
            merged.append(item)
            seen_keys.add(key)
    weather_card = build_daily_weather_card(now, force=force_weather_card)
    if weather_card:
        weather_key = feed_item_key(weather_card)
        merged = [item for item in merged if feed_item_key(item) != weather_key]
        merged.append(weather_card)
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
        if sig:
            final_seen_signatures.add(sig)
        deduped.append(item)
    merged = deduped
    new_feed["items"] = merged[:MAX_FEED_ITEMS]
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
    used_urls: set[str] = set()
    seen = load_seen()
    sources = load_sources(args.sync_profile)
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
        # preserve source-local ranking while dropping duplicate URLs
        local_seen = set()
        candidates = [x for x in candidates if not (x.url in local_seen or local_seen.add(x.url))]
        if args.sync_profile == "fast" or source.get("telegram"):
            # Fast-lane feeds must feel alive: prefer newer qualified items over
            # older items that merely score higher on keyword density.
            candidates = sorted(candidates, key=lambda x: (x.published_at, x.score), reverse=True)
        else:
            candidates = sorted(candidates, key=lambda x: x.score, reverse=True)
        for c in candidates:
            if c.url in used_urls:
                continue
            c.original_title = c.original_title or c.title
            c.title = sanitize_title(c.title)
            if source.get("language") == "en" and not is_foreign_relevant(c.original_title or c.title, c.description):
                continue
            if len(c.title) < 18 or bad_description(c.description):
                continue
            if args.draft and candidate_seen(c, seen):
                continue
            picked.append(c)
            used_urls.add(c.url)
            time.sleep(0.2)
            if len(picked) >= 2:
                break
        selected.extend(picked)

    if args.sync_profile == "fast":
        selected = sorted(selected, key=lambda x: (x.published_at, x.score), reverse=True)
    else:
        selected = sorted(selected, key=lambda x: x.score, reverse=True)

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
    feed["syncProfile"] = args.sync_profile
    if args.draft:
        feed["status"] = "draft"
        CANDIDATES_PATH.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        remember_feed(feed)
        STATE_PATH.write_text(json.dumps({"lastDraftRun": feed["updatedAt"], "draftCount": len(feed["items"])}), encoding="utf-8")
        print(f"Wrote {len(feed['items'])} approval candidates to {CANDIDATES_PATH}")
    else:
        feed = merge_with_existing_feed(feed, force_weather_card=args.force_weather_card)
        feed["mode"] = f"rss_sync_{args.sync_profile}"
        FEED_PATH.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        remember_feed(feed)
        STATE_PATH.write_text(json.dumps({"lastRun": feed["updatedAt"], "count": len(feed["items"])}), encoding="utf-8")
        print(f"Wrote {len(feed['items'])} items to {FEED_PATH}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
