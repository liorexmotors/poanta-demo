# Poanta — החלטת Stack ותשתית Production

עודכן: 2026-05-20

## המלצה קצרה
להתחיל עם stack מהיר אך Production-ready:

- Mobile: Expo / React Native
- Backend API: FastAPI / Python
- DB: PostgreSQL managed
- Cache/Queue: Redis managed
- Jobs: Python workers + queue
- CDN/DNS/WAF: Cloudflare
- Errors: Sentry
- Analytics: PostHog או Firebase Analytics
- Hosting מומלץ לשלב ראשון: Render/Fly.io + Neon/Supabase + Upstash Redis + Cloudflare

## למה זה ה־stack הנכון עכשיו

### Expo / React Native
יתרונות:
- אפליקציה אחת ל־iOS ו־Android.
- מהר להגיע ל־TestFlight ו־Google Internal Testing.
- מתאים מאוד ל־MVP.
- אפשר לשחזר את ה־UI הקיים יחסית מהר.
- תומך בעתיד ב־push, deep links, analytics.

חלופה: Flutter
- חזק מאוד, אבל ידרוש יותר כתיבה מחדש.
- פחות מתאים אם רוצים לנוע מהר מהדמו הקיים.

החלטה מומלצת: Expo.

### FastAPI / Python Backend
יתרונות:
- מתאים לקוד הקיים, שרובו Python.
- קל להעביר scripts קיימים לשירותים/jobs.
- מהיר לפיתוח.
- טוב ל־API, workers, validation.

חלופה: Node/NestJS
- מצוין למערכות גדולות, אבל ידרוש מעבר שפה לחלק מהלוגיקה הקיימת.

החלטה מומלצת: FastAPI.

## ארכיטקטורה מוצעת

```text
Mobile App (Expo)
        |
        v
Cloudflare CDN/WAF
        |
        v
FastAPI Backend
   |        |        |
   v        v        v
Postgres  Redis    Object Storage
   |
   v
Feed versions / users / events / sources

Background Workers
   |
   +--> Collector / האספן
   +--> Editor / העורך
   +--> Quality Gate / השוער
   +--> Live Auditor / המבקר
   +--> Repair Queue / המתקן
```

## שירותים מומלצים לשלב ראשון

### אופציה A — מהירה וחסכונית
מתאים ל־Beta ואלפי משתמשים ראשונים.

- API/Workers: Render או Fly.io
- PostgreSQL: Neon או Supabase
- Redis: Upstash
- CDN/DNS: Cloudflare
- Errors: Sentry
- Analytics: PostHog Cloud או Firebase
- Object storage: Cloudflare R2 או Supabase Storage

עלות משוערת התחלתית:
- 30–120 דולר לחודש, תלוי נפח jobs/AI/שרתים.
- לא כולל עלויות מודלים/AI אם יש.

### אופציה B — חזקה יותר מראש
מתאים אם מצפים לקמפיין/כניסות מרובות מהר.

- AWS ECS/Fargate או GCP Cloud Run
- RDS/Cloud SQL Postgres
- Elasticache/Memorystore Redis
- S3/GCS
- Cloudflare לפני הכל

עלות משוערת התחלתית:
- 150–500 דולר לחודש ומעלה.
- יותר שליטה, יותר DevOps.

## המלצה מעשית
להתחיל באופציה A, עם ארכיטקטורה שלא ננעלת לספק אחד.
אם יש קמפיין גדול או עומסים — להעביר API/Workers ל־AWS/GCP בלי לשנות את האפליקציה.

## חלוקת Backend

### API Service
אחראי על:
- הגשת פיד.
- העדפות משתמש.
- שמורים/נקראו.
- מקורות.
- גרסאות פיד.

### Worker Service
אחראי על:
- RSS/Telegram/source collection.
- Full article extraction.
- Editor batches.
- Quality gate.
- Publish feed.
- Auditor.
- Repair queue.

### Admin/ops dashboard
בשלב ראשון יכול להיות פשוט:
- status JSON
- logs
- feed version list
- rollback button בהמשך

## DB ראשוני

טבלאות מומלצות:
- `sources`
- `raw_candidates`
- `articles`
- `feed_items`
- `feed_versions`
- `users`
- `user_preferences`
- `user_events`
- `saved_items`
- `audit_runs`
- `repair_actions`
- `editor_runs`

## API ראשוני

- `GET /health`
- `GET /v1/feed`
- `GET /v1/feed/version/:id`
- `GET /v1/sources`
- `GET /v1/topics`
- `POST /v1/device/register`
- `GET /v1/preferences`
- `PUT /v1/preferences`
- `POST /v1/events`
- `POST /v1/saved`
- `DELETE /v1/saved/:itemId`

## אבטחה ופרטיות
- להתחיל בלי מידע אישי אם אפשר.
- device id אנונימי.
- לא לאסוף מיקום מדויק.
- לא לאסוף אנשי קשר.
- לא לדרוש הרשאות מיותרות באפליקציה.
- Privacy Policy ברור לפני חנויות.

## Scale ראשוני

### Cache
- `/feed` cache ל־30–120 שניות.
- personalized feed יכול להיות client-side filter ב־MVP או server-side קל.
- images/assets דרך CDN.

### Queue
- jobs לא רצים בתוך request.
- כל איסוף/עריכה/בדיקה בתור רקע.

### Rollback
- כל publish יוצר `feed_version`.
- rollback מחזיר לגרסה קודמת בלי rebuild אפליקציה.

## החלטה סופית מומלצת לשלב הבא
לבנות skeleton של:
1. `apps/mobile` — Expo app
2. `services/api` — FastAPI
3. `services/worker` — jobs/queue
4. `packages/shared` או `schemas` — חוזי JSON/Types
5. `infra` — docker compose מקומי + notes ל־hosting

## מה לא לעשות עכשיו
- לא לבנות מערכת משתמשים מורכבת.
- לא להכניס push לפני שיש פיד יציב.
- לא להקים Kubernetes.
- לא לשלם על תשתית יקרה לפני Beta.
- לא להגיש לחנויות לפני TestFlight/Internal Testing יציב.
