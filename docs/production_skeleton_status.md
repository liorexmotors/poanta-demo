# Production Skeleton Status

עודכן: 2026-05-20

## אישור ליאור
מאושר להתחיל Production skeleton לפי ברירות המחדל, למעט שם המוצר.
השם אינו סופי ונמצא בדיון. אין להשתמש בשם סופי בחנויות/מיתוג ציבורי עד אישור מפורש.

## נוצר מקומית

```text
apps/mobile/              # placeholder לאפליקציית Expo
services/api/             # FastAPI skeleton
services/worker/          # worker skeleton
packages/schemas/         # JSON schemas/contracts
infra/docker-compose.yml  # postgres + redis + api dev stack
```

## API ראשוני
- `GET /health`
- `GET /v1/feed`
- `GET /v1/sources`
- `GET /v1/topics`
- `POST /v1/device/register`

בשלב זה ה־API קורא את `feed.json` הקיים כדי לאפשר מעבר הדרגתי. השלב הבא הוא Postgres-backed feed versions.

## Worker ראשוני
- smoke check שקורא את `feed.json` ומחזיר מספר פריטים.
- הבא: להפוך את האספן/עורך/שוער/מבקר/מתקן ל־jobs מסודרים.

## בדיקות שבוצעו
- `python3 -m py_compile services/api/app/main.py services/worker/worker/main.py`
- `python3 services/worker/worker/main.py`
- venv זמני + התקנת requirements של ה־API
- קריאה ישירה לפונקציות API: health/feed/sources/topics/register_device

## תוצאות בדיקה אחרונה
- worker ok
- feed items: 77
- API health ok
- sources: 52
- device registration anonymous ok

## התקדמות נוספת — 2026-05-20
- נוסף schema ראשוני ל־Postgres: `sources`, `feed_versions`, `feed_items`, `devices`.
- נוסף importer מ־`feed.json` ל־Postgres: `services/worker/worker/import_legacy_feed.py`.
- `GET /v1/feed` יודע לקרוא מ־DB כאשר `DATABASE_URL` מוגדר, עם fallback בטוח ל־`feed.json`.
- בדיקה: `py_compile` עבר ל־API, DB helper וה־importer.

## השלב הבא
1. להריץ Postgres מקומי/סטייג׳ינג ולהפעיל importer אמיתי.
2. להוסיף endpoint/version rollback מלא.
3. להפוך את worker למסלול jobs מסודר.
4. לאחר מכן ליצור Expo app בפועל ב־`apps/mobile`.

## Feedback pipeline task — 2026-05-20
The released 👍/👎 UI is currently client-local only (`localStorage`). Production task now defined:
1. Add backend endpoint `POST /v1/feedback`.
2. Store feedback events in DB with device id, card key/sourceUrl, feedback value, source, category, headline, timestamp.
3. Aggregate daily feedback by source/category/card/editor pattern.
4. Feed the aggregate to מבקר איכות and העורך as report-only signals first.
5. Only after stable evidence, use feedback to tune source priority/editor guidance; never auto-publish weak cards just because engagement is high.

## Feedback pipeline implementation — 2026-05-20
- Added DB table `feedback_events` in `infra/migrations/001_initial.sql`.
- Added API endpoint `POST /v1/feedback` in `services/api/app/main.py`.
- Added client-side queueing and retry from the web UI. The live GitHub Pages build keeps feedback locally and can forward it once `localStorage['pointa:feedback-api-url']` is configured to the production API base URL.
- Added daily/report-only aggregator: `services/worker/worker/feedback_report.py`; output is intended for מבקר איכות and העורך.
- Guardrail: feedback is a quality signal, not an automatic publication rule. It can lower source/card priority or guide editor training only after repeated evidence.
