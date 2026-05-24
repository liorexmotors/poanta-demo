#!/usr/bin/env python3
"""Build Poanta's separate breaking-news feed from dedicated RSS sources."""
from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = ROOT / "breaking_sources.json"
DEFAULT_OUTPUT = ROOT / "breaking_feed.json"
USER_AGENT = "PoantaBreakingFeed/1.0 (+https://liorexmotors.github.io/poanta-demo/)"
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

DROP_PATTERNS = [
    r"פרסומת", r"תוכן שיווקי", r"בשיתוף", r"התחזית", r"מזג האוויר",
]

# רוטר useful but noisy; keep hard-news/security/public affairs language only.
ROTTER_KEEP = re.compile(
    r"(צה.?ל|משטרה|פיגוע|ירי|אזעק|כטב|חמאס|חיזבאללה|איראן|עזה|לבנון|סוריה|כנסת|ממשלה|בג.?ץ|נעצר|תאונ|נפצע|נהרג|נרצח|שריפה|חשד|חקירה|חטופ|מלחמה|ביטחון|מדיני|ארה.?ב|ממשל|טראמפ)",
    re.I,
)


def clean_text(value: str | None) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def parse_date(value: str | None, source: dict[str, Any] | None = None) -> str:
    if not value:
        return ""
    value = clean_text(value)
    source = source or {}
    treat_gmt_as_israel_local = bool(source.get("treatGmtAsIsraelLocal"))
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt.tzinfo is None:
            # Israeli breaking-news feeds that omit an offset normally publish
            # local Israel wall-clock time.  Treating it as UTC creates future
            # timestamps that look suspiciously "now" in the app.
            dt = dt.replace(tzinfo=ISRAEL_TZ)
        elif treat_gmt_as_israel_local and re.search(r"\b(?:GMT|UTC)\b|[+-]0000", value, re.I):
            # Walla's breaking RSS currently labels local Israel time as GMT.
            # Example: "15:20 GMT" arrives while Israel is 15:23, but parsing
            # it literally makes the item 3 hours in the future.  Preserve the
            # wall-clock components and attach Asia/Jerusalem instead.
            dt = dt.replace(tzinfo=ISRAEL_TZ)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ISRAEL_TZ)
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            continue
    return ""


def fetch_url(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read(2_000_000)


def decode_payload(data: bytes) -> str:
    head = data[:200].decode("ascii", "ignore").lower()
    if "windows-1255" in head:
        return data.decode("cp1255", "ignore")
    return data.decode("utf-8", "ignore")


def item_children(item: ET.Element) -> dict[str, str]:
    out: dict[str, str] = {}
    for child in list(item):
        tag = child.tag.split("}")[-1].lower()
        out[tag] = child.text or ""
    return out


def parse_rss(text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    text = re.sub(r"<\?xml[^>]*\?>", "", text, count=1).lstrip()
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    root = ET.fromstring(text.encode("utf-8"))
    rows: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        fields = item_children(item)
        title = clean_text(fields.get("title"))
        if not title:
            continue
        link = clean_text(fields.get("link") or fields.get("guid"))
        desc = clean_text(fields.get("description"))
        published = parse_date(fields.get("pubdate") or fields.get("published") or fields.get("updated") or fields.get("dc:date"), source)
        rows.append(
            {
                "id": hashlib.sha1((link or title).encode("utf-8")).hexdigest()[:16],
                "category": source.get("categoryHint") or "מבזקים",
                "source": source.get("source") or source.get("logo") or source.get("name") or "מקור",
                "sourceLogo": source.get("logo") or source.get("source") or source.get("name") or "מקור",
                "sourceUrl": link,
                "sourceLinks": [{"name": source.get("source") or source.get("logo") or source.get("name") or "מקור", "url": link}],
                "headline": title,
                "originalTitle": title,
                "context": desc or title,
                "publishedAt": published,
                "hasSourceDate": bool(published),
                "breaking": True,
            }
        )
    return rows


def normalize_for_dupe(title: str) -> str:
    text = re.sub(r"[^0-9A-Za-z\u0590-\u05ff]+", " ", title.lower())
    stop = {"של", "את", "על", "עם", "אל", "כי", "לא", "יש", "הוא", "היא", "זה", "זו", "עד", "ב", "ל", "ה"}
    return " ".join(w for w in text.split() if len(w) > 1 and w not in stop)


def token_set(title: str) -> set[str]:
    return set(normalize_for_dupe(title).split())


def near_duplicate(a: str, b: str) -> bool:
    ta, tb = token_set(a), token_set(b)
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return overlap >= 0.72


def should_keep(row: dict[str, Any], source: dict[str, Any]) -> bool:
    text = f"{row.get('headline','')} {row.get('context','')}"
    if any(re.search(p, text, re.I) for p in DROP_PATTERNS):
        return False
    if source.get("needsStrictFiltering") and not ROTTER_KEEP.search(text):
        return False
    return True


def build(sources_path: Path, output_path: Path, limit: int) -> dict[str, Any]:
    cfg = json.loads(sources_path.read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for source in cfg.get("active", []):
        url = source.get("rss")
        if not url:
            continue
        try:
            rows = parse_rss(decode_payload(fetch_url(url)), source)
            items.extend(row for row in rows if should_keep(row, source))
        except Exception as exc:
            errors.append({"source": source.get("name", url), "error": str(exc)[:240]})

    items.sort(key=lambda r: r.get("publishedAt") or "", reverse=True)
    deduped: list[dict[str, Any]] = []
    for row in items:
        match = next((x for x in deduped if near_duplicate(row["headline"], x["headline"])), None)
        if match:
            sources = match.setdefault("sources", [match.get("source")])
            if row.get("source") not in sources:
                sources.append(row.get("source"))
            links = match.setdefault("sourceLinks", [{"name": match.get("source") or "מקור", "url": match.get("sourceUrl") or ""}])
            if row.get("source") and not any(link.get("name") == row.get("source") for link in links):
                links.append({"name": row.get("source"), "url": row.get("sourceUrl") or ""})
            continue
        deduped.append(row)
        if len(deduped) >= limit:
            break

    out = {
        "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "breaking",
        "ttlHours": 12,
        "items": deduped,
        "sources": [s.get("name") for s in cfg.get("active", [])],
        "errors": errors,
    }
    output_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=80)
    args = parser.parse_args(argv)
    out = build(args.sources, args.output, args.limit)
    print(f"breaking_feed: {len(out['items'])} items, {len(out['errors'])} source errors -> {args.output}")
    if out["errors"]:
        for err in out["errors"]:
            print(f"WARN {err['source']}: {err['error']}", file=sys.stderr)
    return 0 if out["items"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
