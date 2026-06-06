# Poenta Google Play handoff — 0.3.34 / vc43

Status: Lior approved the Android 0.3.34 / versionCode 43 build as final for Google Play upload.

## Approved baseline
- App: Poenta / פואנטה
- Android package: `poenta.app`
- Version name: `0.3.34`
- Version code: `43`
- Source baseline: `apps/mobile` Expo / React Native app
- Approved release archive: `releases/mobile/0.3.34-vc43-settings-performance-fix/`

## Verified local test artifacts
- `poenta-0.3.34-vc43-arm64-release.apk` — physical Android sideload testing
- `poenta-0.3.34-vc43-x86_64-release.apk` — Android Studio emulator/simulator testing
- `poenta-0.3.34-vc43-universal-release.apk` — universal manual-test APK

These APKs are debug-signed local/manual-test builds and are not the final Google Play upload artifact.

## Verification completed before Play handoff
- `npm run typecheck` — PASS
- `npx expo-doctor` — PASS, 18/18 checks
- `npx expo config --type public --json` — confirms `poenta.app`, `0.3.34`, `versionCode 43`
- `npm run export:web` — PASS
- APK manifest inspection — confirms package `poenta.app`, `versionName 0.3.34`, `versionCode 43`
- APK signing verification — PASS for local/manual-test APKs

## Current blocker for actual Play upload
No active Expo/EAS login or Google Play service-account credentials are available in this environment:
- `npx eas-cli whoami --non-interactive` returned `Not logged in`.
- No `EXPO_TOKEN`, Google Play service-account JSON, or related Play upload env var is configured.

## Required next step to upload to Google Play
Provide one of the following through a secure/private channel, not a group chat:
1. Expo/EAS credentials/token with Android production build credentials configured, so we can run a production AAB build and inspect it; or
2. Google Play Console access/service-account JSON plus the final production AAB produced by EAS/Play signing flow; or
3. Lior drives Play Console manually and uploads the AAB after we produce/verify it.

Do not upload the local debug-signed APK/AAB to Play.

## Before actual upload
- Build production Android AAB using EAS production profile.
- Download and inspect the AAB manifest with bundletool.
- Verify package `poenta.app`, versionCode, min/target SDK, permissions, and signing/upload key compatibility with Play Console.
- Upload to the selected Play track only after these checks pass.
