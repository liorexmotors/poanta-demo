# Poenta mobile store readiness audit — 2026-06-01

## Scope
Expo / React Native app at `apps/mobile`, Android preview EAS build, and public store-support URLs under `https://poenta.app`.

## Passed
- Expo authentication works with the local secret token file; token value was not printed.
- EAS project created and linked: `@poenta.app/poenta` / project ID `6c7c9525-1161-45cf-a4c7-7a9bb7f99df1`.
- `npm run typecheck` passed.
- `npx expo-doctor` passed: 18/18 checks.
- `npx expo config --type public` shows:
  - app name `Poenta`
  - slug `poenta`
  - owner `poenta.app`
  - iOS bundle ID `app.poenta`
  - iOS tablet support disabled for v1 (`supportsTablet: false`) to avoid iPad screenshot/review scope
  - Android package `app.poenta`
  - Android permissions `[]` and `android.blockedPermissions` blocks legacy storage/overlay permissions observed in the first APK inspection.
- First Android EAS preview build finished: `71c931c6-9592-48c5-b65a-c2bf72a7c624`; inspection found unwanted `READ_EXTERNAL_STORAGE`, `WRITE_EXTERNAL_STORAGE`, and `SYSTEM_ALERT_WINDOW` permissions from native/template output.
- Follow-up Android EAS preview build started after adding `blockedPermissions`: `0d84d083-6526-40e1-8b74-f4da82b1e564`.
- Store-facing text scan in `apps/mobile` found no `demo`, `MVP`, `skeleton`, `שלד`, `דמו`, or `mockup` wording.
- Web export smoke passed: `npm run export:web`.
- Public pages are real HTTPS pages, not home fallbacks:
  - `https://poenta.app/` → 200
  - `https://poenta.app/privacy` → 200
  - `https://poenta.app/terms` → 200
  - `https://poenta.app/support` → 200
- Internal dashboards are protected from public browsing:
  - `https://poenta.app/feedback-dashboard.html` → 401
  - `https://poenta.app/rss-dashboard.html` → 401
  - `https://poenta.app/rss-viewer.html` → 401
- Feed endpoint for the native app is reachable with browser/app-style headers:
  - `https://poenta.app/feed.json` → 200 JSON
  - observed items: 218
  - observed `updatedAt`: `2026-06-01T18:56:39+02:00`

## Open gates / blockers before final store submission
1. Android permission-fix preview APK `e7c48df6-09e8-48b5-bdd0-ed602f34eb85` finished and was inspected with `androguard`: legacy storage/overlay permissions are gone. Remaining manifest permissions are `INTERNET`, `VIBRATE`, and `app.poenta.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`.
2. Android production AAB build for Google Play `add92129-12a1-4fa7-adf2-961e7474b19f` finished and was inspected with `bundletool` manifest dump. The production AAB has the same clean permission set as the preview APK.
3. Final Apple Privacy Nutrition / Google Play Data Safety answers can use the cleaned Android production artifact inspection below; keep iOS answers gated on the non-simulator iOS production artifact.
4. For TestFlight/App Store (not simulator preview), complete Apple Developer / App Store Connect credentials in EAS, then run a non-simulator iOS production build. A non-interactive production attempt currently fails because the Distribution Certificate/provisioning setup is not completed; see `ios-testflight-handoff.md`.

## Support mailbox decision
- Store support email: `support@poenta.app`.
- DNS for `poenta.app` has Google MX/SPF configured, and inbound delivery was reported tested successfully before switching public pages/store metadata from the temporary mailbox.

## Current EAS builds
### Android preview — first build
- Build ID: `71c931c6-9592-48c5-b65a-c2bf72a7c624`
- Platform: Android
- Profile: preview
- Logs: https://expo.dev/accounts/poenta.app/projects/poenta/builds/71c931c6-9592-48c5-b65a-c2bf72a7c624
- Status: finished
- Artifact inspected: `https://expo.dev/artifacts/eas/f3WMQdgmewiXP7Pv1yyyAQ.apk`
- Inspection result: package `app.poenta`, version `0.1.0`, versionCode `1`, minSdk `24`, targetSdk `36`; unwanted permissions found and fixed in follow-up config (`READ_EXTERNAL_STORAGE`, `WRITE_EXTERNAL_STORAGE`, `SYSTEM_ALERT_WINDOW`).

### Android preview — permission-fix build
- Build ID: `e7c48df6-09e8-48b5-bdd0-ed602f34eb85`
- Platform: Android
- Profile: preview
- Status: finished
- Artifact inspected: `https://expo.dev/artifacts/eas/uBWA1SQn8Rt5wjdmd4Krct.apk`
- Inspection tool: `androguard` on `/tmp/poenta-e7c48df6.apk`
- Inspection result: package `app.poenta`, version `0.1.0`, versionCode `1`, minSdk `24`, targetSdk `36`.
- Manifest permissions found:
  - `android.permission.INTERNET`
  - `android.permission.VIBRATE`
  - `app.poenta.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`
- Regression check passed: `READ_EXTERNAL_STORAGE`, `WRITE_EXTERNAL_STORAGE`, and `SYSTEM_ALERT_WINDOW` are absent.

### Android production — Google Play AAB
- Build ID: `add92129-12a1-4fa7-adf2-961e7474b19f`
- Platform: Android
- Profile: production
- Status: finished
- Artifact inspected: `https://expo.dev/artifacts/eas/nt7HffKF1CLBSvymM53u9P.aab`
- Local inspection path: `/tmp/poenta-add92129.aab`
- Inspection tool: `bundletool 1.18.1` manifest dump for base module
- Inspection result: package `app.poenta`, version `0.1.0`, versionCode `2`, minSdk `24`, targetSdk `36`.
- Manifest permissions found:
  - `android.permission.INTERNET`
  - `android.permission.VIBRATE`
  - `app.poenta.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`
- Regression check passed: `READ_EXTERNAL_STORAGE`, `WRITE_EXTERNAL_STORAGE`, and `SYSTEM_ALERT_WINDOW` are absent.
- This is the current Google Play upload candidate, pending Play Console account/track/submission steps.

### iOS simulator preview
- Finished build ID: `e57f9f9c-f08f-4a94-bb70-6b9d3fd4372d`
- Artifact: `https://expo.dev/artifacts/eas/ukFW6tZSoGcvkNn3x8UMYZ.tar.gz`
- Prior finished build ID inspected: `49a8027a-c20b-4ec0-a6cb-17c664a67b59`
- Basic artifact inspection passed on the prior simulator `.app` archive:
  - Bundle ID `app.poenta`
  - Display name `Poenta`
  - Version `0.1.0`, build `1`
  - `UIDeviceFamily = [1]` (iPhone only)
  - no camera/microphone/location/tracking usage strings in `Info.plist`
  - `PrivacyInfo.xcprivacy` exists with no collected data types and tracking disabled
