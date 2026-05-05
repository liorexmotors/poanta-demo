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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PoantaBot/0.1; +https://github.com/liorexmotors/poanta-demo)",
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
    ("ביטחון", "security", ["איראן", "מלחמה", "צה״ל", "צהל", "פיקוד העורף", "טילים", "ביטחון", "הורמוז", "אמירויות"]),
    ("כלכלה", "money", ["ריבית", "מס", "שכר", "מניות", "בורסה", "מחירים", "פיצויים", "עסקים", "אקזיט", "מיליון", "מיליארד"]),
    ("צרכנות", "money", ["צרכן", "רשתות", "שופרסל", "מחירי", "קניות", "ביטוח", "סופר", "חלב"]),
    ("טכנולוגיה", "tech", ["AI", "סייבר", "וואטסאפ", "אפל", "גוגל", "אפליקציה", "טכנולוג", "סטארטאפ"]),
    ("נדל״ן", "real", ["נדל", "דירה", "דירות", "בנייה", "תל אביב", "דיור", "קרקע"]),
    ("תחבורה", "real", ["טיסות", "רכבת", "כביש", "רכב", "תחבורה", "דלק", "נתבג", "דובאי", "פקקים", "נהגים"]),
    ("פוליטיקה", "security", ["כנסת", "ממשלה", "בחירות", "קואליציה", "אופוזיציה", "תקציב", "שר", "שרים"]),
    ("ספורט", "real", ["ספורט", "כדורגל", "כדורסל", "נבחרת", "ליגה", "ליגת", "מכבי", "הפועל", "ביתר", "אליפות"]),
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


def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[|\-–:•\s]+", "", text)
    return text[:500]



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
        if len(title) < 18 or not link:
            continue
        score = score_title(title + ' ' + desc)
        if score <= 0:
            continue
        out.append(Candidate(source=source['name'], url=link, title=title, description=desc, score=score))
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
        parser = parse_html(fetch(candidate.url, timeout=12))
    except Exception:
        return candidate
    meta_title = sanitize_title(parser.meta.get("og:title") or parser.meta.get("twitter:title") or "")
    if meta_title and len(meta_title) >= 18:
        candidate.title = meta_title
    desc = clean_text(parser.meta.get("og:description") or parser.meta.get("description") or parser.meta.get("twitter:description") or "")
    if not desc:
        ps = [clean_text(p) for p in parser.paragraphs]
        desc = clean_text(" ".join(p for p in ps if len(p) > 40)[:450])
    if bad_description(desc):
        desc = ""
    candidate.description = desc
    return candidate


def categorize(text: str) -> tuple[str, str]:
    for cat, cls, words in CATEGORY_RULES:
        if any(w.lower() in text.lower() for w in words):
            return cat, cls
    return "חדשות", ""


def poanta_headline(title: str, desc: str) -> str:
    h = sanitize_title(title)
    # Remove common clickbait wrappers while preserving claim.
    replacements = [
        (r"^.*?נחשף[:：]?\s*", ""),
        (r"^.*?דרמטי[:：]?\s*", ""),
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
    return h[:95]


def context_text(title: str, desc: str, source: str) -> str:
    # Never publish article descriptions verbatim. Poanta cards must be
    # original explanatory summaries, not copied OG/RSS snippets. Use the
    # description only as weak signal for categorization elsewhere.
    cat, _ = categorize(f"{title} {desc}")
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


def normalized_key(text: str) -> str:
    text = re.sub(r"[^0-9A-Za-z\u0590-\u05ff]+", "", text).lower()
    return text[:70]


def load_seen() -> dict:
    try:
        data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
        return {
            "urls": set(data.get("urls", [])),
            "titleKeys": set(data.get("titleKeys", [])),
        }
    except Exception:
        return {"urls": set(), "titleKeys": set()}


def candidate_seen(c: Candidate, seen: dict) -> bool:
    return c.url in seen["urls"] or normalized_key(c.title) in seen["titleKeys"]


def remember_feed(feed: dict) -> None:
    seen = load_seen()
    for item in feed.get("items", []):
        url = item.get("sourceUrl")
        title = item.get("headline") or ""
        if url:
            seen["urls"].add(url)
        key = normalized_key(title)
        if key:
            seen["titleKeys"].add(key)
    payload = {
        "urls": sorted(seen["urls"]),
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
        text = f"{c.title} {c.description}"
        category, cls = categorize(text)
        items.append({
            "category": category,
            "categoryClass": cls,
            "source": c.source,
            "sourceUrl": c.url,
            "time": "עודכן אוטומטית",
            "headline": poanta_headline(c.title, c.description),
            "originalTitle": c.title,
            "context": context_text(c.title, c.description, c.source),
            "takeaway": takeaway_text(category, c.title, c.description),
        })
    tz = timezone(timedelta(hours=3))
    return {"updatedAt": datetime.now(tz).isoformat(timespec="seconds"), "items": items[:12]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Update or draft Poanta feed cards")
    ap.add_argument("--draft", action="store_true", help="Write candidates.json for approval instead of publishing feed.json")
    args = ap.parse_args()

    selected: list[Candidate] = []
    used_urls: set[str] = set()
    seen = load_seen()
    for source in SOURCES:
        picked = []
        candidates = extract_rss(source) + extract_links(source)
        # preserve source-local ranking while dropping duplicate URLs
        local_seen = set()
        candidates = [x for x in candidates if not (x.url in local_seen or local_seen.add(x.url))]
        candidates = sorted(candidates, key=lambda x: x.score, reverse=True)
        for c in candidates:
            if c.url in used_urls:
                continue
            if not c.description:
                c = enrich(c)
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

    if len(selected) < 4:
        print(f"ERROR too few items selected: {len(selected)}", file=sys.stderr)
        return 2

    feed = build_feed(selected)
    if args.draft:
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
