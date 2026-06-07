# Poenta — iOS TestFlight / App Store handoff

Last updated: 2026-06-07

## Current iOS state
- Expo project: `@poenta.app/poenta`
- App name: `Poenta`
- Bundle ID: `app.poenta`
- Version: `0.3.38`
- iOS build number: `47`
- v1 scope: iPhone only (`ios.supportsTablet=false`)
- Support email for store submission: `support@poenta.app`
- Privacy policy: `https://poenta.app/privacy`
- Terms: `https://poenta.app/terms`
- Support URL: `https://poenta.app/support`

## Verified / prepared so far
- The iOS app uses the same Expo / React Native source as the Android `0.3.38 / versionCode 47` hotfix prepared for the next Google Play update.
- iOS `buildNumber` is explicitly set to `47` to match the Android `versionCode 47` release line.
- `CFBundleIdentifier` target remains `app.poenta`.
- iPhone-only device family remains the v1 decision.
- No camera/microphone/location/tracking permission strings are intentionally used by the app.
- `ITSAppUsesNonExemptEncryption=false` is set in `app.json` for standard HTTPS-only usage.
- Previous iOS simulator artifact existed for older baseline `0.3.34`; a fresh `0.3.38` iOS build is still needed.

## Current blocker
This machine is not logged into Expo/EAS:

```text
npx eas-cli whoami --non-interactive
Not logged in
```

A real iOS device/TestFlight build also requires completed Apple credentials in EAS / App Store Connect:
- Apple Distribution Certificate
- Provisioning profile for bundle ID `app.poenta`
- App Store Connect app record

Do **not** paste Apple passwords, 2FA codes, Expo tokens, private keys, or certificates in chat.

## Recommended secure paths

### Option A — interactive EAS Apple login on a secure machine
Run where the Apple account owner can complete login/2FA:

```bash
cd /root/.openclaw/workspace/projects/poanta-demo/apps/mobile
npx eas-cli login
npx eas-cli whoami
npx eas-cli build --platform ios --profile preview
```

For the first real TestFlight build:

```bash
npx eas-cli build --platform ios --profile production
```

When prompted:
1. Sign in with Apple Developer account.
2. Let EAS create/manage the Distribution Certificate.
3. Let EAS create/manage the provisioning profile for bundle ID `app.poenta`.
4. Confirm the build starts.

### Option B — App Store Connect API key / Expo token
Create credentials in the official dashboards and store them only in a secure secrets store, not in repo/chat.

## App Store Connect app record checklist
1. Create or verify app record for bundle ID `app.poenta`.
2. Primary language: Hebrew if available/desired.
3. App name: `Poenta` / `פואנטה` as available.
4. Category: News.
5. Privacy policy URL: `https://poenta.app/privacy`.
6. Support URL: `https://poenta.app/support`.
7. Support email: `support@poenta.app`.
8. Export compliance: app uses standard HTTPS only; `ITSAppUsesNonExemptEncryption=false` is set.

## Required QA before App Review
1. Install on real iPhone via TestFlight.
2. Smoke test:
   - app launches quickly
   - Hebrew RTL layout readable
   - feed loads from `https://poenta.app/feed.json`
   - bottom navigation works
   - Settings source/topic/day taps respond immediately
   - language selector is visible and functional
   - no login/push prompts
   - no unexpected permission prompts
   - support/privacy/terms are correct
3. Lock Apple Privacy Nutrition answers after device-build inspection.
