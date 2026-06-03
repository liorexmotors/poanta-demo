#!/usr/bin/env python3
"""Generate Poenta dashboard trend-intelligence snapshot for agent "מרגל".

The spy scans active RSS news/current-affairs sources, clusters fresh titles into
currently discussed topics, counts external mentions, and marks whether each
trend appears in our current feed.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import email.utils
import html
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STOP_HE = {
    "של", "על", "עם", "את", "אל", "או", "גם", "כי", "לא", "כן", "כל", "כך", "זה", "זו", "הוא", "היא", "הם", "הן",
    "בין", "אחרי", "לפני", "יותר", "פחות", "חדש", "חדשה", "חדשות", "עדכון", "דיווח", "דיווחים", "היום", "הלילה", "בגלל",
    "והוא", "והיא", "אבל", "בלי", "תוך", "עוד", "ראשון", "אחרון", "שני", "מול", "עבר", "אצל", "מתוך", "כדי",
}
STOP_EN = {
    "the", "and", "for", "with", "from", "that", "this", "are", "was", "were", "will", "after", "before", "over", "under",
    "into", "about", "news", "live", "latest", "updates", "update", "breaking", "more", "than", "have", "has", "not", "but",
}
CURRENT_AFFAIRS_HINTS = {
    "חדשות", "ביטחון", "פוליטיקה", "אקטואליה בעולם", "כלכלה", "משפט", "פלילים", "טכנולוגיה", "בריאות", "צרכנות", "רכב", "נדל״ן", "דעות", "מזג אוויר"
}
UA = "PoentaSpy/1.0 (+https://poenta.app)"
TOKEN_RE = re.compile(r"[A-Za-z0-9\u0590-\u05ff₪$€£]+")
TAG_RE = re.compile(r"<[^>]+>")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def clean_text(s: Any) -> str:
    s = html.unescape(str(s or ""))
    s = TAG_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    for parser in (email.utils.parsedate_to_datetime,):
        try:
            d = parser(raw)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d.astimezone(timezone.utc)
        except Exception:
            pass
    try:
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None


def tokens(text: str) -> list[str]:
    out = []
    for t in TOKEN_RE.findall(text.lower().replace("־", "-")):
        t = t.strip("-–—_:.,!?()[]{}'\"׳״")
        if len(t) < 3 or t.isdigit():
            continue
        if t in STOP_HE or t in STOP_EN:
            continue
        out.append(t)
    return out


def source_name(src: dict[str, Any]) -> str:
    return str(src.get("logo") or src.get("name") or "מקור")


def parse_feed_xml(raw: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(raw)
    items = []
    # RSS items
    for item in root.findall(".//item"):
        title = clean_text((item.findtext("title") or ""))
        desc = clean_text(item.findtext("description") or item.findtext("summary") or "")
        link = clean_text(item.findtext("link") or "")
        published = item.findtext("pubDate") or item.findtext("published") or item.findtext("updated")
        if title:
            items.append({"title": title, "summary": desc, "url": link, "publishedAt": parse_dt(published)})
    # Atom entries
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//a:entry", ns) + root.findall(".//entry"):
        title = clean_text(entry.findtext("a:title", namespaces=ns) or entry.findtext("title") or "")
        desc = clean_text(entry.findtext("a:summary", namespaces=ns) or entry.findtext("summary") or entry.findtext("a:content", namespaces=ns) or "")
        link_el = entry.find("a:link", ns) or entry.find("link")
        link = clean_text(link_el.get("href") if link_el is not None else "")
        published = entry.findtext("a:published", namespaces=ns) or entry.findtext("a:updated", namespaces=ns) or entry.findtext("published") or entry.findtext("updated")
        if title:
            items.append({"title": title, "summary": desc, "url": link, "publishedAt": parse_dt(published)})
    return items


def fetch_source(src: dict[str, Any], timeout: int, max_items: int) -> dict[str, Any]:
    url = src.get("rss")
    if not url:
        return {"source": source_name(src), "items": [], "error": "no_rss"}
    try:
        req = urllib.request.Request(str(url), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(2_500_000)
        items = parse_feed_xml(raw)[:max_items]
        for it in items:
            it["source"] = source_name(src)
            it["sourceName"] = src.get("name") or source_name(src)
            it["domain"] = src.get("categoryHint") or "חדשות"
        return {"source": source_name(src), "items": items, "error": None}
    except Exception as e:
        return {"source": source_name(src), "items": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}


def phrase_keys(title: str) -> set[tuple[str, ...]]:
    ts = tokens(title)
    keys: set[tuple[str, ...]] = set()
    # Adjacent meaningful pairs/triples are stronger signals than single words.
    for n in (3, 2):
        for i in range(max(0, len(ts) - n + 1)):
            part = tuple(ts[i:i+n])
            if len(set(part)) == len(part):
                keys.add(part)
    if not keys and ts:
        keys.add(tuple(ts[:2] if len(ts) >= 2 else ts))
    return keys


def feed_text_index(feed: dict[str, Any]) -> tuple[list[set[str]], str]:
    rows = []
    combined = []
    for item in feed.get("items", []) or []:
        text = clean_text(" ".join(str(item.get(k) or "") for k in ("headline", "originalTitle", "summary", "context", "takeaway", "source")))
        tk = set(tokens(text))
        if tk:
            rows.append(tk)
            combined.append(text.lower())
    return rows, "\n".join(combined)


def mentioned_in_feed(key: tuple[str, ...], feed_sets: list[set[str]], feed_all: str) -> bool:
    kset = set(key)
    if len(kset) == 1:
        return any(next(iter(kset)) in s for s in feed_sets)
    if " ".join(key) in feed_all:
        return True
    return any(len(kset & s) >= min(2, len(kset)) for s in feed_sets)


def build_trends(items: list[dict[str, Any]], feed: dict[str, Any], top_n: int) -> list[dict[str, Any]]:
    feed_sets, feed_all = feed_text_index(feed)
    clusters: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for it in items:
        for key in phrase_keys(it["title"]):
            clusters[key].append(it)
    candidates = []
    seen_labels = set()
    for key, rows in clusters.items():
        sources = {r["source"] for r in rows}
        if len(rows) < 2 and len(sources) < 2:
            continue
        domain = Counter(r.get("domain") or "חדשות" for r in rows).most_common(1)[0][0]
        rep = max(rows, key=lambda r: ((r.get("publishedAt") or datetime.min.replace(tzinfo=timezone.utc)), len(r.get("title", ""))))
        label = " ".join(key)
        if label in seen_labels:
            continue
        seen_labels.add(label)
        candidates.append({
            "domain": domain,
            "trend": clean_text(rep.get("title") or label)[:145],
            "clusterKey": label,
            "externalMentions": len(rows),
            "sourceCount": len(sources),
            "sources": sorted(sources)[:8],
            "mentionedInFeed": mentioned_in_feed(key, feed_sets, feed_all),
            "latestAt": (rep.get("publishedAt") or datetime.now(timezone.utc)).isoformat(),
            "sampleUrl": rep.get("url") or "",
        })
    candidates.sort(key=lambda r: (r["externalMentions"] * 2 + r["sourceCount"] * 3, r["latestAt"]), reverse=True)
    # Dedupe by token overlap so one story does not occupy the whole table.
    out = []
    used: list[set[str]] = []
    for c in candidates:
        tk = set(tokens(c["trend"]))
        if any(len(tk & u) >= min(3, len(tk), len(u)) for u in used):
            continue
        used.append(tk)
        out.append(c)
        if len(out) >= top_n:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=str(ROOT / "rss_sources.json"))
    ap.add_argument("--feed", default=str(ROOT / "feed.json"))
    ap.add_argument("--out", default=str(ROOT / "spy_trends.json"))
    ap.add_argument("--hours", type=int, default=8)
    ap.add_argument("--max-sources", type=int, default=80)
    ap.add_argument("--max-items-per-source", type=int, default=18)
    ap.add_argument("--timeout", type=int, default=8)
    ap.add_argument("--top", type=int, default=14)
    args = ap.parse_args()

    sources_doc = json.loads(Path(args.sources).read_text(encoding="utf-8"))
    feed = json.loads(Path(args.feed).read_text(encoding="utf-8"))
    sources = [s for s in sources_doc.get("active", []) if s.get("rss") and (s.get("categoryHint") in CURRENT_AFFAIRS_HINTS)]
    sources = sources[: args.max_sources]
    started = time.time()
    fetched = []
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(fetch_source, s, args.timeout, args.max_items_per_source) for s in sources]
        for fut in cf.as_completed(futs):
            fetched.append(fut.result())
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    items = []
    errors = []
    for res in fetched:
        if res.get("error"):
            errors.append({"source": res.get("source"), "error": res.get("error")})
        for it in res.get("items") or []:
            d = it.get("publishedAt")
            if d is None or d >= cutoff:
                items.append(it)
    trends = build_trends(items, feed, args.top)
    doc = {
        "status": "ok" if trends else "empty",
        "agent": {"id": "spy", "name": "מרגל", "role": "איתור טרנדים חיצוניים והשוואה לפיד פואנטה"},
        "generatedAt": now_iso(),
        "windowHours": args.hours,
        "sourcesChecked": len(sources),
        "sourcesWithErrors": len(errors),
        "itemsScanned": len(items),
        "durationSec": round(time.time() - started, 2),
        "errorsSample": errors[:12],
        "trends": trends,
    }
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: doc[k] for k in ("status", "sourcesChecked", "itemsScanned", "durationSec")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
