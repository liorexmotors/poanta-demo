# Poenta — Privacy / Data Safety Draft

Last prepared: 2026-06-01

## Current v1 product decision
- No login / no account creation.
- No push notifications.
- No in-app purchases.
- No location, camera, microphone, contacts, calendar, Bluetooth, health, or photos access.
- Public news feed is fetched from `https://poenta.app/feed.json`.

## App permissions expectation
Android permissions should remain empty/minimal. The cleaned preview APK `e7c48df6-09e8-48b5-bdd0-ed602f34eb85` was inspected and contains only:
- `android.permission.INTERNET`
- `android.permission.VIBRATE`
- `app.poenta.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`

The earlier legacy storage/overlay permissions are absent. Re-check the production AAB before final Play submission.

## Apple Privacy Nutrition draft
Subject to final SDK/build inspection before submission.

### Data collected from this app
Current Expo app code does not intentionally collect user-identifying personal data.

Potential server-side operational logs may include standard technical request data:
- IP address
- user agent/device/browser/app client string
- request time
- requested URL

Use in Apple answers:
- If only standard server logs are kept for security/operations and not linked to a user profile: disclose conservatively as diagnostics/other usage data only if Apple form requires it.
- No tracking across apps/websites.
- No advertising ID use.
- No third-party ad SDK.

### Tracking
No.

### Linked to user
No account exists in v1, so app data is not linked to an account identity.

### Account deletion
Not applicable for v1 because there are no user accounts.

## Google Play Data Safety draft
Subject to final SDK/build inspection before submission.

### Does the app collect or share user data?
Conservative draft answer: app does not intentionally collect user-provided personal data. Standard technical logs may be processed by hosting/infrastructure for security and reliability.

### Data types
- Personal info: No.
- Financial info: No.
- Location: No.
- Photos/videos/audio/files: No.
- Contacts: No.
- App activity: No intentional analytics in current code.
- Web browsing: No.
- App info and performance: only crash/diagnostic data if Expo/EAS or platform crash reporting is enabled later.
- Device identifiers: No advertising ID in current code.

### Data sharing
No intentional sharing with advertisers or data brokers.
Infrastructure processors may serve app/feed content.

### Security practices
- Data in transit over HTTPS.
- No account, so deletion request for user account data is not applicable.

## Launch gates before final submission
1. Verify actual native permissions after EAS build:
   - Android manifest permissions.
   - iOS Info.plist permission usage strings.
2. Verify whether EAS/Expo build includes crash reporting or analytics by default.
3. Store support mailbox: `support@poenta.app` (Poenta-domain Google MX configured; inbound delivery tested).
4. Confirm public pages are real and reachable:
   - `https://poenta.app/privacy`
   - `https://poenta.app/terms`
   - `https://poenta.app/support`
5. Confirm dashboard/internal pages are not exposed through the mobile app.
