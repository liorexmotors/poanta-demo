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
  - Android permissions `[]`
- Android EAS preview build started: `71c931c6-9592-48c5-b65a-c2bf72a7c624`.
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
1. Android EAS build must finish successfully, then inspect the produced APK/AAB permissions and runtime behavior with `apps/mobile/scripts/inspect_android_artifact.py`.
2. Final Apple Privacy Nutrition / Google Play Data Safety answers should be locked only after native build artifact inspection.
3. For TestFlight/App Store (not simulator preview), connect Apple Developer / App Store Connect credentials and run a non-simulator iOS build.

## Support mailbox decision
- Temporary support email: `tsach@care.co.il`; DNS for `care.co.il` has Microsoft/Outlook MX.
- Later switch public pages/store metadata to `support@poenta.app` only after MX/routing and inbound delivery are configured and tested.

## Current EAS builds
### Android preview
- Build ID: `71c931c6-9592-48c5-b65a-c2bf72a7c624`
- Platform: Android
- Profile: preview
- Logs: https://expo.dev/accounts/poenta.app/projects/poenta/builds/71c931c6-9592-48c5-b65a-c2bf72a7c624
- Status at last check: in queue

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
