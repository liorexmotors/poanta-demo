#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare Poanta RSS candidates without touching live feed/state.

Safe by design:
- reads rss_sources.json
- fetches active RSS feeds
- dedupes + scores items
- writes rss_preview.json and rss_preview.md only
- does NOT modify feed.json, candidates.json, .poanta-seen.json, or deployment files
"""
from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "rss_sources.json"
OUT_JSON = ROOT / "rss_preview.json"
OUT_MD = ROOT / "rss_preview.md"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PoantaRSSPrep/0.1; +https://github.com/liorexmotors/poanta-demo)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.6,en;q=0.4",
}

IMPORTANT_WORDS = [
    "איראן", "מלחמה", "צה\"ל", "צהל", "פיקוד העורף", "ריבית", "מס", "שכר", "מחירים",
    "פיצויים", "בורסה", "נדל", "דירה", "דירות", "תחבורה", "רכב", "טיסות", "דלק",
    "AI", "בינה", "סייבר", "וואטסאפ", "גוגל", "אפל", "ממשלה", "כנסת", "תקציב",
    "בריאות", "צרכנים", "ביטוח", "בנקים", "ספורט", "ליגת", "נבחרת", "מכבי", "הפועל",
]
CLICK_WORDS = [
    "דרמטי", "נחשף", "סערה", "כאוס", "שיא", "זינוק", "ירידה", "מפתיע", "איום", "התרחיש",
    "בדרך", "חייבים לדעת", "זה מה", "כל מה", "בלעדי", "מטלטל", "הסוד", "הטעות",
]
CATEGORY_RULES = [
    # Order matters: classify the practical subject first, not every story that mentions the war as security.
    ("נדל\"ן", "real", ["נדל", "דירה", "דירות", "בנייה", "דיור", "קרקע"]),
    ("כלכלה", "money", ["ריבית", "מס", "שכר", "מניות", "בורסה", "מחירים", "פיצויים", "מיליון", "מיליארד", "דולר", "אינפלציה", "כלכל"]),
    ("צרכנות", "money", ["צרכן", "מחירי", "קניות", "ביטוח", "סופר", "חלב", "רשתות", "מבצע"]),
    ("טכנולוגיה", "tech", ["AI", "בינה", "סייבר", "וואטסאפ", "אפל", "גוגל", "טכנולוג", "סטארטאפ", "GPT"]),
    ("תחבורה", "real", ["טיסות", "רכבת", "כביש", "רכב", "תחבורה", "דלק", "נתבג", "נהגים"]),
    ("פוליטיקה", "security", ["כנסת", "ממשלה", "בחירות", "קואליציה", "אופוזיציה", "תקציב", "שר ", "שרים", "ח\"כ", "ח\"כים", "חכים", "טייוואן", "סין"]),
    ("ספורט", "real", ["ספורט", "כדורגל", "כדורסל", "נבחרת", "ליגה", "ליגת", "מכבי", "הפועל", "בית\"ר"]),
    ("ביטחון", "security", ["איראן", "מלחמה", "צה\"ל", "צהל", "פיקוד העורף", "טילים", "חמאס", "חיזבאללה", "לבנון"]),
]

@dataclass
class RawItem:
    source: str
    sourceLogo: str
    rss: str
    title: str
    link: str
    description: str
    published: str
    imageUrl: str
    score: int
    category: str
    categoryClass: str
    key: str


def clean(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_key(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u0590-\u05ff]+", "", text or "").lower()[:90]


def item_key(link: str, title: str) -> str:
    link = (link or "").strip()
    if link:
        parsed = urlparse(link)
        return hashlib.sha1((parsed.netloc + parsed.path).lower().encode()).hexdigest()[:16]
    return hashlib.sha1(normalize_key(title).encode()).hexdigest()[:16]


def score(title: str, desc: str) -> int:
    text = f"{title} {desc}"
    val = 0
    for w in IMPORTANT_WORDS:
        if w.lower() in text.lower():
            val += 3
    for w in CLICK_WORDS:
        if w in text:
            val += 2
    if any(ch.isdigit() for ch in title):
        val += 1
    if "?" in title:
        val += 1
    if 25 <= len(title) <= 105:
        val += 2
    if any(noise in text for noise in ["רכילות", "סלב", "מתכון", "אסטרולוג", "פרסומת", "בשיתוף"]):
        val -= 6
    return val


def categorize(title: str, desc: str, fallback: str = "חדשות") -> tuple[str, str]:
    # Title is the strongest signal. Description is secondary and can contain noisy context.
    for cat, cls, words in CATEGORY_RULES:
        if any(w.lower() in title.lower() for w in words):
            return cat, cls
    text = f"{title} {desc}"
    for cat, cls, words in CATEGORY_RULES:
        if any(w.lower() in text.lower() for w in words):
            return cat, cls
    return fallback, ""


def fetch(url: str, timeout: int = 15) -> bytes:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_date(text: str) -> str:
    text = clean(text)
    if not text:
        return ""
    try:
        dt = email.utils.parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=3))).isoformat(timespec="minutes")
    except Exception:
        return text[:80]


def first_text(item: ET.Element, names: Iterable[str]) -> str:
    for name in names:
        found = item.find(name)
        if found is not None and found.text:
            return clean(found.text)
    # namespace fallback by localname
    local_names = {n.split("}")[-1].lower() for n in names}
    for child in item.iter():
        local = child.tag.split("}")[-1].lower()
        if local in local_names and child.text:
            return clean(child.text)
    return ""


def image_from_item(item: ET.Element) -> str:
    for child in item.iter():
        local = child.tag.split("}")[-1].lower()
        if local in {"thumbnail", "content", "enclosure"}:
            url = child.attrib.get("url") or child.attrib.get("href")
            typ = child.attrib.get("type", "")
            if url and ("image" in typ or local in {"thumbnail", "content"}):
                return clean(url)
    return ""


def parse_feed(source: dict) -> tuple[list[RawItem], str | None]:
    try:
        raw = fetch(source["rss"])
        root = ET.fromstring(raw)
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"
    items: list[RawItem] = []
    for item in root.findall(".//item"):
        title = first_text(item, ["title"])
        link = first_text(item, ["link", "guid"])
        desc = first_text(item, ["description", "summary"])
        published = parse_date(first_text(item, ["pubDate", "published", "updated"]))
        image = image_from_item(item)
        if len(title) < 12 or not link:
            continue
        if source["name"] == "גלובס" and "en.globes.co.il" in link:
            continue
        sc = score(title, desc)
        cat, cls = categorize(title, desc, source.get("categoryHint", "חדשות"))
        items.append(RawItem(
            source=source["name"],
            sourceLogo=source.get("logo") or source["name"],
            rss=source["rss"],
            title=title,
            link=link,
            description=desc[:360],
            published=published,
            imageUrl=image,
            score=sc,
            category=cat,
            categoryClass=cls,
            key=item_key(link, title),
        ))
    return items, None


def make_poanta_preview(item: RawItem) -> dict:
    # This is only a review preview; final editorial rewrite should happen in the approval flow.
    why = {
        "ביטחון": "לבדוק אם יש הנחיות רשמיות או שינוי מעשי בשגרה.",
        "כלכלה": "לבדוק השפעה על כסף, מחירים, ריבית, השקעות או תזרים.",
        "צרכנות": "לבדוק מחיר/זכאות בפועל ולא להסתפק בכותרת.",
        "טכנולוגיה": "לבדוק השפעה על עבודה, פרטיות או שימוש יומיומי.",
        "תחבורה": "לבדוק השפעה לפני נסיעה או תכנון יציאה.",
        "נדל\"ן": "לבדוק השפעה על מחירים, ביקושים או החלטות רכישה.",
        "פוליטיקה": "לבדוק מה משתנה בפועל בהחלטות, תקציבים או שירותים.",
        "ספורט": "לבדוק משמעות להמשך העונה, סגל או מומנטום.",
    }.get(item.category, "לבדוק מה המשמעות המעשית ולא רק את הכותרת.")
    return {
        "category": item.category,
        "categoryClass": item.categoryClass,
        "source": item.source,
        "sourceLogo": item.sourceLogo,
        "sourceUrl": item.link,
        "imageUrl": item.imageUrl,
        "published": item.published,
        "score": item.score,
        "headlineCandidate": item.title[:95],
        "originalTitle": item.title,
        "summaryCandidate": clean(item.description)[:220],
        "takeawayCandidate": why,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    cfg = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    all_items: list[RawItem] = []
    source_report = []
    for src in cfg.get("active", []):
        items, err = parse_feed(src)
        source_report.append({"name": src["name"], "rss": src["rss"], "count": len(items), "error": err})
        all_items.extend(items)

    deduped = {}
    for item in sorted(all_items, key=lambda x: x.score, reverse=True):
        title_key = normalize_key(item.title)
        if item.key in deduped or any(normalize_key(x.title) == title_key for x in deduped.values()):
            continue
        deduped[item.key] = item

    selected = []
    source_counts = {}
    category_counts = {}
    for item in sorted(deduped.values(), key=lambda x: (x.score, x.published), reverse=True):
        if item.score < 4:
            continue
        if source_counts.get(item.source, 0) >= 3:
            continue
        if category_counts.get(item.category, 0) >= 4:
            continue
        selected.append(item)
        source_counts[item.source] = source_counts.get(item.source, 0) + 1
        category_counts[item.category] = category_counts.get(item.category, 0) + 1
        if len(selected) >= args.limit:
            break
    tz = timezone(timedelta(hours=3))
    payload = {
        "status": "rss_preview_only_not_connected",
        "updatedAt": datetime.now(tz).isoformat(timespec="seconds"),
        "sourceReport": source_report,
        "excludedForNow": cfg.get("excluded_for_now", cfg.get("pending_or_blocked", [])),
        "items": [make_poanta_preview(x) for x in selected],
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = ["# Poanta RSS Preview — לא מחובר לאתר", "", f"עודכן: {payload['updatedAt']}", "", "## מצב מקורות"]
    for r in source_report:
        lines.append(f"- {r['name']}: {r['count']} פריטים" + (f" — שגיאה: {r['error']}" if r.get("error") else ""))
    lines += ["", "## מועמדים ראשונים"]
    for i, item in enumerate(payload["items"], 1):
        lines += [
            f"### {i}. {item['headlineCandidate']}",
            f"- מקור: {item['source']} | קטגוריה: {item['category']} | ניקוד: {item['score']}",
            f"- כותרת מקור: {item['originalTitle']}",
            f"- תמצית זמנית: {item['summaryCandidate'] or 'אין תיאור RSS'}",
            f"- תובנה זמנית: {item['takeawayCandidate']}",
            f"- לינק: {item['sourceUrl']}",
            "",
        ]
    lines += ["## חסומים/ממתינים", ""]
    for p in payload["excludedForNow"]:
        lines.append(f"- {p['name']}: {p['reason']}")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {len(selected)} preview items -> {OUT_JSON}")
    print(f"Report -> {OUT_MD}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
