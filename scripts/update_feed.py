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
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "feed.json"
STATE_PATH = ROOT / ".poanta-state.json"
CANDIDATES_PATH = ROOT / "candidates.json"
SEEN_PATH = ROOT / ".poanta-seen.json"
RSS_SOURCES_PATH = ROOT / "rss_sources.json"

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


def load_sources() -> list[dict]:
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
        for src in active:
            if not src.get("rss"):
                continue
            sources.append({
                "name": src["name"],
                "url": src.get("rss"),
                "rss": src["rss"],
                "host": urlparse(src["rss"]).netloc,
                "categoryHint": src.get("categoryHint", "חדשות"),
                "logo": src.get("logo") or src["name"],
            })
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
    # Order matters: prefer the practical topic over incidental war/politics words.
    ("נדל״ן", "real", ["נדל", "דירה", "דירות", "בנייה", "פינוי-בינוי", "תל אביב", "דיור", "קרקע"]),
    ("כלכלה", "money", ["ריבית", "מיסים", "מע״מ", "שכר", "מניות", "בורסה", "מחירים", "פיצויים", "עסקים", "אקזיט", "מיליון", "מיליארד", "דולר", "אינפלציה"]),
    ("צרכנות", "money", ["צרכן", "רשתות", "שופרסל", "מחירי", "קניות", "ביטוח", "סופר", "חלב"]),
    ("טכנולוגיה", "tech", ["AI", "סייבר", "וואטסאפ", "אפל", "גוגל", "אפליקציה", "טכנולוג", "סטארטאפ", "GPT"]),
    ("תחבורה", "real", ["טיסות", "רכבת", "כביש", "רכב", "תחבורה", "דלק", "נתבג", "דובאי", "פקקים", "נהגים"]),
    ("ספורט", "real", ["ספורט", "כדורגל", "כדורסל", "נבחרת", "ליגה", "ליגת", "מכבי", "הפועל", "ביתר", "אליפות", "מסי", "סוארס", "ניימאר", "יורוליג"]),
    ("ביטחון", "security", ["איראן", "מלחמה", "צה״ל", "צהל", "פיקוד העורף", "טילים", "ביטחון", "הורמוז", "אמירויות", "לבנון", "חמאס", "חיזבאללה", "פוטין", "קרמלין", "התנקשות", "ביון"]),
    ("פוליטיקה", "security", ["כנסת", "ממשלה", "בחירות", "קואליציה", "אופוזיציה", "תקציב", "שרים", "ח״כ", "חכים", "טייוואן", "סין"]),
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


def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[|\-–:•\s]+", "", text)
    return text[:500]


def source_logo(source: str) -> str:
    s = source.lower()
    if "n12" in s or "mako" in s:
        return "N12"
    if "וואלה" in source:
        return "וואלה"
    if "ynet" in s:
        return "ynet"
    if "גלובס" in source:
        return "גלובס"
    if "14" in source:
        return "14"
    return source.split()[0] if source else "מקור"



def sanitize_title(title: str) -> str:
    title = clean_text(title)
    title = re.sub(r"\s*[-–|]\s*(N12|mako|וואלה|ynet|גלובס|ערוץ 14).*$", "", title, flags=re.I).strip()
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
        desc = clean_text(re.sub(r'<[^>]+>', ' ', item.findtext('description') or ''))
        image = ""
        for child in item.iter():
            local = child.tag.split('}')[-1].lower()
            if local in {"thumbnail", "content", "enclosure"}:
                url = child.attrib.get("url") or child.attrib.get("href")
                typ = child.attrib.get("type", "")
                if url and ("image" in typ or local in {"thumbnail", "content"}):
                    image = clean_text(url)
                    break
        if len(title) < 18 or not link:
            continue
        if source.get("name", "").startswith("גלובס") and "en.globes.co.il" in link:
            continue
        score = score_title(title + ' ' + desc)
        if score <= 0:
            continue
        out.append(Candidate(source=source['name'], url=link, title=title, description=desc, score=score, image_url=image, original_title=title))
    return sorted(out, key=lambda c: c.score, reverse=True)[:12]


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


def categorize(text: str) -> tuple[str, str]:
    titleish = text.split(". ", 1)[0]
    for cat, cls, words in CATEGORY_RULES:
        if any(w.lower() in titleish.lower() for w in words):
            return cat, cls
    for cat, cls, words in CATEGORY_RULES:
        if any(w.lower() in text.lower() for w in words):
            return cat, cls
    return "חדשות", ""


def categorize_item(title: str, desc: str, source: str) -> tuple[str, str]:
    # With many section RSS feeds enabled, the feed name is a strong signal.
    # Prefer it over incidental keywords in the title/description so sports,
    # car, tech, health and culture feeds are not mislabeled as politics/real estate.
    if any(x in source for x in ["ספורט", "כדורגל", "כדורסל", "NBA", "טניס"]):
        return "ספורט", "real"
    if any(x in source for x in ["רכב", "דו-גלגלי", "ביטוח רכב", "בטיחות"]):
        return "תחבורה", "real"
    if any(x in source for x in ["TECH", "טכנולוג", "סייבר", "סטארטאפים", "סמארטפונים", "מחשבים", "מדע"]):
        return "טכנולוגיה", "tech"
    if any(x in source for x in ["בריאות", "תזונה", "כושר", "רפואה", "הריון"]):
        return "בריאות", "real"
    if any(x in source for x in ["כלכלה", "כסף", "שוק ההון", "גלובס", "צרכנות", "קריפטו", "קריירה"]):
        return "כלכלה", "money"
    if any(x in source for x in ["תרבות", "טלוויזיה", "מוזיקה", "קולנוע", "ספרות", "אמנות", "אוכל", "תיירות", "טיולים", "אופנה", "בית ועיצוב"]):
        return "תרבות", "real"
    if any(x in source for x in ["דעות", "פרשנויות"]):
        return "דעות", "security"
    cat, cls = categorize(title)
    if cat != "חדשות":
        return cat, cls
    return cat, cls


def poanta_headline(title: str, desc: str) -> str:
    h = sanitize_title(title)
    # Remove common clickbait wrappers while preserving claim.
    replacements = [
        (r"^.*?נחשף[:：]?\s*", ""),
        (r"^.*?כאוס[:：]?\s*", ""),
        (r"^.*?הבלוף של\s*", ""),
        (r"כל מה שצריך לדעת על\s*", ""),
        (r"זה מה ש\s*", ""),
    ]
    original = h
    for pat, rep in replacements:
        h = re.sub(pat, rep, h).strip(" -–:|")
    h = h.replace("?", "")
    if len(h) < 18:
        h = original
    if len(h) < 18 and desc:
        h = clean_text(desc).split(". ")[0]
    # Poanta headline must not be the source headline with punctuation removed.
    # If deterministic cleanup did not materially rewrite it, fall back to a
    # neutral explanatory headline that states the practical reading angle.
    def norm(text: str) -> str:
        return re.sub(r"[^0-9A-Za-z\u0590-\u05ff]+", "", text or "").lower()
    if norm(h) == norm(original):
        cat, _ = categorize(f"{title} {desc}")
        fallbacks = {
            "ביטחון": "האירוע הביטחוני מחייב להיצמד לעדכונים רשמיים",
            "כלכלה": "הכותרת הכלכלית חשובה רק דרך ההשפעה בפועל",
            "צרכנות": "הפרסום הצרכני דורש בדיקת מחיר ותנאים בפועל",
            "טכנולוגיה": "החידוש הטכנולוגי חשוב דרך ההשפעה היומיומית",
            "נדל״ן": "הסיפור הנדלני חשוב בעיקר דרך השפעת המחירים",
            "תחבורה": "השינוי התחבורתי חשוב רק אם הוא משפיע על נסיעה",
            "פוליטיקה": "מאחורי הכותרת הפוליטית צריך לבדוק מה משתנה",
            "ספורט": "הדרמה הספורטיבית חשובה רק דרך ההמשך המעשי",
        }
        h = fallbacks.get(cat, "הפואנטה היא המשמעות, לא ניסוח הכותרת המקורית")
    return h[:95]


def context_text(title: str, desc: str, source: str) -> str:
    # Never publish article descriptions verbatim. Poanta cards must be
    # original explanatory summaries, not copied OG/RSS snippets. Use the
    # description only as weak signal for categorization elsewhere.
    cat, _ = categorize_item(title, desc, source)
    headline = poanta_headline(title, desc)
    if cat == "ביטחון":
        return "מאחורי הכותרות הדרמטיות יש בעיקר שאלה מעשית: האם יש הנחיות חדשות לציבור ומה הרשויות אומרות בפועל. עד שאין הנחיה רשמית, חשוב להפריד בין רעש תקשורתי לבין שינוי אמיתי בשגרה."
    if cat == "כלכלה":
        return "זו ידיעה כלכלית שכדאי לקרוא דרך ההשפעה הישירה: כסף נכנס, כסף יוצא, זכאות, מחירים או תזרים. הכותרת חשובה פחות מהשאלה מה צריך לבדוק או להכין עכשיו."
    if cat == "צרכנות":
        return "הסיפור הצרכני כאן הוא הפער בין הודעות רשמיות לבין מה שקורה בפועל בקופה. לכן הפואנטה היא לבדוק מחיר אמיתי והשוואה, לא להסתפק בסיסמה של מבצע או בכותרת."
    if cat == "טכנולוגיה":
        return "העניין הטכנולוגי הוא לא רק החידוש עצמו, אלא איך הוא עשוי להשפיע על שימוש יומיומי, פרטיות, עבודה או שירותים שאתה כבר צורך."
    if cat == "נדל״ן":
        return "בנדל״ן ההשפעה בדרך כלל לא מיידית, אבל שינוי כזה יכול להשפיע על ביקושים, תמחור והחלטות רכישה או שכירות בהמשך."
    if cat == "תחבורה":
        return "זו ידיעה שיכולה להשפיע על מי שנוסע או תלוי בשירות תחבורתי, אבל צריך להבחין בין בדיקה/כוונה לבין פתרון שכבר עובד בשטח."
    if cat == "פוליטיקה":
        return "הסיפור הפוליטי חשוב רק אם מבינים מה הוא משנה בפועל: החלטות, תקציבים, יציבות או שירותים לציבור. לכן הפואנטה היא ההשלכה, לא הריב סביב הכותרת."
    if cat == "ספורט":
        return "בספורט קל להיתפס לדרמה של רגע, אבל הפואנטה היא מה זה אומר להמשך: טבלה, סגל, פציעות, ניהול או מומנטום."
    return f"{source} פרסם ידיעה בנושא: {headline}. פואנטה מסכמת את המשמעות המעשית בלי להעתיק את נוסח המקור ובלי למשוך לקליק מיותר."


def takeaway_text(category: str, title: str, desc: str) -> str:
    text = f"{title} {desc}"
    if category == "ביטחון":
        return "לעקוב אחרי עדכונים רשמיים, אבל לא לשנות שגרה בלי הנחיה ברורה מהרשויות."
    if category == "כלכלה":
        return "כדאי לבדוק איך זה משפיע על הכיס: תלוש שכר, החזרי הלוואות, מחירים או החלטות השקעה."
    if category == "צרכנות":
        return "לפני קנייה או חידוש שירות, שווה להשוות מחירים ולא להסתמך על הכותרת או המבצע הראשון."
    if category == "טכנולוגיה":
        return "זו מגמה שכדאי להכיר: היא יכולה להשפיע על עבודה, פרטיות, אבטחה או שימוש יומיומי באפליקציות."
    if category == "נדל״ן":
        return "ההשפעה לא תמיד מיידית, אבל היא יכולה להשפיע על מחירים, ביקושים ותכנון רכישה באזור."
    if category == "תחבורה":
        return "אם אתה נוסע, טס או תלוי בשירות הזה — בדוק עדכונים לפני יציאה ואל תחכה לרגע האחרון."
    if category == "פוליטיקה":
        return "כדאי לבדוק מה ההחלטה משנה בפועל: תקציב, שירותים, מסים או יציבות פוליטית — ולא להסתפק בסיסמאות."
    if category == "ספורט":
        return "אם אתה עוקב אחרי הקבוצה או האירוע, שווה לבדוק את המשמעות להמשך העונה ולא רק את הדרמה של הכותרת."
    return "זו ידיעה למעקב: הפואנטה היא להבין את ההשפעה בפועל, לא רק את הכותרת."


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

def build_feed(candidates: Iterable[Candidate]) -> dict:
    items = []
    seen_titles = set()
    for c in candidates:
        key = normalized_key(c.title)
        if key in seen_titles:
            continue
        seen_titles.add(key)
        category, cls = categorize_item(c.title, c.description, c.source)
        items.append({
            "category": category,
            "categoryClass": cls,
            "source": c.source,
            "sourceLogo": source_logo(c.source),
            "sourceUrl": c.url,
            "imageUrl": c.image_url,
            "time": "עודכן אוטומטית",
            "headline": poanta_headline(c.title, c.description),
            "originalTitle": c.original_title or c.title,
            "context": context_text(c.title, c.description, c.source),
            "takeaway": takeaway_text(category, c.title, c.description),
        })
    tz = timezone(timedelta(hours=3))
    return {"updatedAt": datetime.now(tz).isoformat(timespec="seconds"), "items": items[:12]}


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
    args = ap.parse_args()

    # Never leave a previous approval batch in candidates.json during a new draft.
    # If the scan fails or finds too few fresh stories, the cron must see an empty
    # draft rather than accidentally resending yesterday/today's stale candidates.
    if args.draft:
        write_empty_draft("generating", "Draft generation in progress; do not send this file.")

    selected: list[Candidate] = []
    used_urls: set[str] = set()
    seen = load_seen()
    for source in load_sources():
        picked = []
        # RSS-only phase: do not scrape homepages and do not use fallback readers.
        candidates = extract_rss(source)
        # preserve source-local ranking while dropping duplicate URLs
        local_seen = set()
        candidates = [x for x in candidates if not (x.url in local_seen or local_seen.add(x.url))]
        candidates = sorted(candidates, key=lambda x: x.score, reverse=True)
        for c in candidates:
            if c.url in used_urls:
                continue
            c.original_title = c.original_title or c.title
            c.title = sanitize_title(c.title)
            if len(c.title) < 18 or bad_description(c.description):
                continue
            if candidate_seen(c, seen):
                continue
            picked.append(c)
            used_urls.add(c.url)
            time.sleep(0.2)
            if len(picked) >= 2:
                break
        selected.extend(picked)

    selected = sorted(selected, key=lambda x: x.score, reverse=True)

    if len(selected) < 4:
        msg = f"Too few fresh unseen items selected: {len(selected)}"
        print(f"ERROR {msg}", file=sys.stderr)
        if args.draft:
            write_empty_draft("failed_too_few_fresh_items", msg)
            STATE_PATH.write_text(json.dumps({"lastDraftError": msg}), encoding="utf-8")
        return 2

    feed = build_feed(selected)
    if args.draft:
        feed["status"] = "draft"
        CANDIDATES_PATH.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        remember_feed(feed)
        STATE_PATH.write_text(json.dumps({"lastDraftRun": feed["updatedAt"], "draftCount": len(feed["items"])}), encoding="utf-8")
        print(f"Wrote {len(feed['items'])} approval candidates to {CANDIDATES_PATH}")
    else:
        FEED_PATH.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        remember_feed(feed)
        STATE_PATH.write_text(json.dumps({"lastRun": feed["updatedAt"], "count": len(feed["items"])}), encoding="utf-8")
        print(f"Wrote {len(feed['items'])} items to {FEED_PATH}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
