#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Poanta opinion-author attribution drill.

Synthetic regression tests for opinion cards after user feedback: if the source is
Maariv/opinions and the byline is known, the card must name the columnist instead
of using generic wording such as "הטור" or "הכותבת טוענת".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp" / "agent-training" / "poanta_opinion_author_drill_report.json"
TEAM = ["העורך", "השוער", "המבקר", "המתקן", "עליזה"]
GENERIC = ["הטור", "הכותבת טוענת", "הכותב טוען", "לטענת הכותבת", "לטענת הכותב", "בעיני הכותבת", "בעיני הכותב"]


@dataclass(frozen=True)
class Case:
    id: str
    author: str
    source: str
    source_url: str
    headline: str
    context: str
    expected: str  # pass/reject
    owner_if_fail: str


def classify(c: Case) -> dict[str, str | bool | list[str]]:
    blob = f"{c.headline} | {c.context}"
    author_variants = {c.author, re.sub(r"^(?:עו[״\"]?ד|ד[״\"]?ר|פרופ[׳']?)\s+", "", c.author).strip()}
    is_opinion = "דעות" in c.source or "/opinions/" in c.source_url
    problems: list[str] = []
    if is_opinion and c.author:
        if any(x in blob for x in GENERIC):
            problems.append("generic_opinion_reference")
        if not any(a and a in blob for a in author_variants):
            problems.append("author_missing")
    status = "reject" if problems else "pass"
    owner = "השוער" if problems else "המבקר"
    action = "block_and_route_to_editor_rewrite" if problems else "allow_after_full_QA"
    return {"status": status, "owner": owner, "action": action, "problems": problems}


def cases() -> list[Case]:
    return [
        Case("O01", "דניאל רוט אבנרי", "מעריב - דעות", "/news/opinions/article-1", "הטור טוען שנתניהו יהפוך את משפטו לקמפיין", "הכותבת טוענת שנתניהו ינצל את ההליך", "reject", "השוער"),
        Case("O02", "דניאל רוט אבנרי", "מעריב - דעות", "/news/opinions/article-1", "דניאל רוט אבנרי: נתניהו יהפוך את משפטו לקמפיין", "רוט אבנרי מציגה את ההליך כנכס פוליטי", "pass", ""),
        Case("O03", "דפנה נתניהו", "מעריב - דעות", "/news/opinions/article-2", "מוזיאון הקומוניזם בפראג הופך בטור לאזהרה פוליטית", "הכותבת משתמשת במוזיאון כדי לתקוף קומוניזם", "reject", "השוער"),
        Case("O04", "דפנה נתניהו", "מעריב - דעות", "/news/opinions/article-2", "דפנה נתניהו הופכת מוזיאון בפראג לאזהרה אנטי־קומוניסטית", "נתניהו מציגה את הזיכרון ההיסטורי כאזהרה", "pass", ""),
        Case("O05", "לילך סיגן", "מעריב - דעות", "/news/opinions/article-3", "הטור מאשים את הממשלה בדיבורים בלי תוצאות", "הכותבת טוענת שהממשלה לא סיפקה תיקון ממשי", "reject", "השוער"),
        Case("O06", "לילך סיגן", "מעריב - דעות", "/news/opinions/article-3", "לילך סיגן: הממשלה דיברה הרבה ולא סיפקה תוצאות", "סיגן מודדת את הממשלה לפי תוצאות ולא סיסמאות", "pass", ""),
        Case("O07", "עו״ד גיא בוסי", "מעריב - דעות", "/news/opinions/article-4", "הטור מזהיר ממשפטיזציה עמוקה של הביטחון הישראלי", "הכותב טוען שבג״ץ הרחיב ביקורת", "reject", "השוער"),
        Case("O08", "עו״ד גיא בוסי", "מעריב - דעות", "/news/opinions/article-4", "גיא בוסי מזהיר מהתרחבות משפטית לתוך החלטות ביטחון", "בוסי מציג את המשפטיזציה כסיכון מבצעי", "pass", ""),
        Case("O09", "אבי בניהו", "מעריב - דעות", "/news/opinions/article-5", "מאמר מזהיר מקריסת נורמות שלטון", "בעיני הכותב הבחירות הן הכרעה על שיקום מוסדות", "reject", "השוער"),
        Case("O10", "אבי בניהו", "מעריב - דעות", "/news/opinions/article-5", "אבי בניהו מזהיר מקריסת נורמות שלטון בזמן המלחמה", "בניהו מציג את הבחירות כהכרעה על שיקום מוסדות", "pass", ""),
    ]


def main() -> int:
    rows=[]
    for c in cases():
        got=classify(c)
        passed=got["status"] == c.expected and (c.expected == "pass" or got["owner"] == c.owner_if_fail)
        rows.append({"case": asdict(c), "got": got, "passed": passed})
    passed=sum(r["passed"] for r in rows)
    report={
        "name":"Poanta opinion author attribution drill",
        "checkedAt":datetime.now(timezone.utc).isoformat(),
        "teamTrained":TEAM,
        "total":len(rows),
        "passed":passed,
        "score":round(100*passed/len(rows),2),
        "status":"pass" if passed==len(rows) else "fail",
        "rule":"Known opinion byline must appear in visible card text; generic writer/column references are rejected.",
        "rows":rows,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":report["status"],"score":report["score"],"passed":passed,"total":len(rows),"report":str(OUT)},ensure_ascii=False))
    return 0 if report["status"]=="pass" else 2

if __name__ == "__main__":
    raise SystemExit(main())
