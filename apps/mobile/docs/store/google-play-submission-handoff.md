# Poenta — Google Play submission handoff

Last updated: 2026-06-02

## Current Android artifact
- Package name: `app.poenta`
- App version: `0.1.0`
- Version code: `2`
- EAS production build ID: `add92129-12a1-4fa7-adf2-961e7474b19f`
- AAB artifact: `https://expo.dev/artifacts/eas/nt7HffKF1CLBSvymM53u9P.aab`
- Local inspected artifact: `/tmp/poenta-add92129.aab`
- Local submission pack: `/tmp/poenta-google-play-submission-pack.zip`

## Native manifest inspection
Inspected the production AAB base manifest with `bundletool 1.18.1`.

Result:
- Package: `app.poenta`
- Version name: `0.1.0`
- Version code: `2`
- minSdk: `24`
- targetSdk: `36`

Permissions present:
- `android.permission.INTERNET`
- `android.permission.VIBRATE`
- `app.poenta.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`

Permissions absent / regression fixed:
- `android.permission.READ_EXTERNAL_STORAGE`
- `android.permission.WRITE_EXTERNAL_STORAGE`
- `android.permission.SYSTEM_ALERT_WINDOW`

## Store listing
### App name
Poenta — פואנטה

### Short description
פואנטה מרכזת עדכוני חדשות בעברית ממקורות ציבוריים, מציגה את הפואנטה בכל ידיעה, ומאפשרת לעבור מהר בין כותרות, הקשר ומקור.

### Full description
פואנטה היא אפליקציית חדשות בעברית שמיועדת לקריאה מהירה וברורה.
במקום לגלול בין עשרות כותרות כפולות, פואנטה מציגה פיד מסודר עם כותרת, תקציר, מקור והקשר — כדי להבין מהר מה קרה ולמה זה חשוב.

מה יש באפליקציה:
- פיד חדשות בעברית ממקורות ציבוריים
- כרטיסי ידיעה קצרים וברורים
- הצגת מקור הידיעה לצד התקציר
- עיצוב כהה ונוח לקריאה
- ללא הרשמה וללא התחברות בגרסה הראשונה

פואנטה אינה גוף חדשות ואינה מחליפה את המקורות המקוריים. האפליקציה מסייעת לארגן, לתמצת ולהציג ידיעות ממקורות ציבוריים, עם הפניה למקור כאשר רלוונטי.

### Category
News & Magazines / חדשות

### Contact details
- Website: `https://poenta.app`
- Privacy policy: `https://poenta.app/privacy`
- Support URL: `https://poenta.app/support`
- Terms: `https://poenta.app/terms`
- Support email: `support@poenta.app`

## Google Play assets
Prepared under `apps/mobile/store-assets/google-play/`:
- Feature graphic: `feature-graphic-1024x500.png`
- Phone screenshots:
  - `screenshots/01.png`
  - `screenshots/02.png`
  - `screenshots/03.png`
  - `screenshots/04.png`
  - `screenshots/05.png`

Visual QA: first screenshot reviewed after regeneration; it shows real feed content, correct Hebrew RTL, no loading spinner, and no white/cut-off bottom artifact.

## Play Console setup steps
1. Open Google Play Console.
2. Create app:
   - App name: `Poenta — פואנטה`
   - Default language: Hebrew (`he-IL`) if available, otherwise Hebrew/Israel listing.
   - App type: App.
   - Free or paid: Free.
   - Declarations: accept Developer Program policies and US export laws after review.
3. Main store listing:
   - Paste short/full description above.
   - Category: News & Magazines.
   - Upload feature graphic and phone screenshots from `store-assets/google-play/`.
4. App content:
   - Privacy policy URL: `https://poenta.app/privacy`.
   - Ads: No ads.
   - App access: all functionality available without login/special access.
   - Target audience: not designed for children; recommended 13+ / Teen because it is a news app and can include current events/security/politics.
   - News app declaration: yes, it is a news/feed app that organizes public-source news and links/context.
   - Data safety: see draft below.
5. Testing/release:
   - Prefer Internal testing first.
   - Upload AAB `versionCode 2`.
   - Add release notes in Hebrew:
     `גרסה ראשונה לבדיקה: פיד חדשות בעברית, כרטיסי תקציר, מקור והקשר לכל ידיעה.`
   - Review errors/warnings before rollout.

## Data Safety draft
Use after confirming no analytics/ads/user accounts were added.

### Data collection and sharing
- Does the app collect or share user data? Conservative answer: No user-provided personal data is intentionally collected or shared by the app.
- The app fetches a public news feed over HTTPS. Standard server/infrastructure logs may process technical request data for security/reliability only and are not used for advertising, profiling, or account linkage.
- No third-party advertising SDK.
- No advertising ID use.
- No account creation / no login.

### Data types
- Location: No.
- Personal info: No.
- Financial info: No.
- Health and fitness: No.
- Messages: No.
- Photos and videos: No.
- Audio files: No.
- Files and docs: No.
- Calendar: No.
- Contacts: No.
- App activity: No intentional analytics in current code.
- Web browsing: No.
- App info and performance: No app analytics/crash SDK intentionally configured in current code; if Play detects platform crash reports, answer according to Play Console prompt.
- Device or other IDs: No advertising ID in current code.

### Security practices
- Data encrypted in transit: Yes, app fetches over HTTPS.
- Users can request deletion: Not applicable for user accounts because v1 has no accounts/login. Keep support channel available for privacy/support requests.

## Current blockers
- Google Play upload itself requires access to Lior's Play Console / developer account. No Play Console service-account credentials are stored locally.
- iOS remains blocked separately by Apple Developer / App Store Connect login/approval issue.
