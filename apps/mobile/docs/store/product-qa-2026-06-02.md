# Poenta mobile — Product QA pass

Last updated: 2026-06-02

## Scope
QA pass for the store-ready mobile app preparation while Google Play and Apple account access are pending.

## Static product checks
- Store-facing app name: `Poenta` / `Poenta — פואנטה` in listing.
- Package/bundle ID: `app.poenta`.
- v1 scope: phone app, no iPad, no login, no push notifications, no camera/microphone/location/payment prompts.
- Android production AAB `versionCode 2` already inspected and has only expected permissions: `INTERNET`, `VIBRATE`, and app-scoped dynamic receiver permission.
- Google Play assets exist: 5 phone screenshots and 1024×500 feature graphic.
- First screenshot visually reviewed after regeneration: Hebrew RTL is readable, no white bottom strip, no loading spinner.

## Runtime/build checks run
- `npm run typecheck` — passed on 2026-06-02.
- `npm run export:web` — passed on 2026-06-02; Expo web export generated `dist-web` successfully.
- Local browser smoke at `http://127.0.0.1:19006` — passed; page title `Poenta`, real feed cards visible, no spinner/blank state.
- Visual browser QA — passed; Hebrew RTL readable, no visible reversed/cut text, dark premium news-app look acceptable. Minor note: mixed Hebrew/English source names should be watched during tester QA, and summary contrast can be improved later if needed.
- Google Play asset dimensions — passed: feature graphic `1024×500`, screenshots `1080×1920`.
- Store-facing wording scan — passed for active listing/assets; no implementation-only wording intended for users.

## Tester-facing acceptance checks
1. Open app: header and feed title visible.
2. Feed loads real content, not placeholder/sample launch text.
3. Hebrew text is readable and right-aligned.
4. Cards show headline, summary/context, source, and time when available.
5. No obvious repeated stories in top feed items.
6. No permission prompt appears on launch.
7. Errors show a readable Hebrew message instead of a broken screen.

## Current blockers
- Actual Google Play upload/internal-test release requires Play Console access after Google completes developer/account verification.
- iOS/TestFlight requires Apple Developer/App Store Connect login/credential setup.
