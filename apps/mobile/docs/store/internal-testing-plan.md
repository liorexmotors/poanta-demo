# Poenta — Internal Testing plan

Last updated: 2026-06-02

## Goal
Run Google Play Internal testing before any production rollout, verify real install from Play, basic feed loading, RTL layout, screenshots/listing accuracy, and support flow.

## Tester list template
Use this table before creating the Internal testing track.

| Name | Email | Device / OS | Role | Notes |
|---|---|---|---|---|
| ליאור |  | Android phone | owner/product | Install + approve launch readiness |
| נטלי |  | Android phone | content/UX | Hebrew readability + visual QA |
| צחי |  | Android phone | ops/support | Support links + policy/contact QA |
| Tester 4 |  | Android phone | general user | Fresh eyes |
| Tester 5 |  | Android phone | general user | Fresh eyes |

## Minimum tester checklist
Ask each tester to verify:
1. App installs from Google Play Internal testing link.
2. App opens without crash.
3. Feed loads within a reasonable time.
4. Hebrew text is readable and not reversed/cut.
5. Top stories are not obvious duplicates of the same story.
6. Images render or placeholders look acceptable.
7. Privacy/Terms/Support links in the store listing open correctly.
8. No login, payment, notification, location, camera, or microphone prompt appears.
9. Report any crash, blank screen, stale feed, or confusing text with screenshot.

## Suggested invite message to testers
היי, העלינו גרסת בדיקה ראשונה של Poenta / פואנטה ל־Google Play Internal Testing.

המטרה: לוודא שהאפליקציה נפתחת, הפיד נטען, העברית נראית טוב, ואין כפילויות/תקלות בולטות לפני פתיחה רחבה יותר.

מה לבדוק:
- התקנה מהקישור של Google Play
- פתיחה וטעינת פיד
- קריאות בעברית ו־RTL
- כותרות/תקצירים/מקורות
- שאין בקשות הרשאה מוזרות
- אם יש תקלה — לשלוח צילום מסך ומה קרה

תודה 🙏

## Play Console setup notes
- Track: Internal testing first.
- Release artifact: `poenta-0.1.0-vc2.aab` / versionCode `2`.
- Tester emails: add as an email list in Play Console.
- Do not use Production until Lior approves results from the internal test.
