# Poenta iOS parity plan — based on Android 0.3.34 / vc43

Lior approved Android 0.3.34 / versionCode 43 as final and requested the iOS version to be identical visually and functionally.

## Baseline rule
The iOS app must use the same Expo / React Native source baseline as the approved Android build:
- Same `apps/mobile/App.tsx` behavior
- Same feed/settings/search/saved/breaking flows
- Same RTL layout and Hebrew UX
- Same Settings performance model
- Same visible language selector: Hebrew, English, Russian, Arabic
- Same app identity and icons, adjusted only for iOS platform requirements

## Current iOS config
- Bundle ID: `app.poenta`
- Version: `0.3.34`
- Tablet support: disabled (`supportsTablet: false`)
- Non-exempt encryption flag: `ITSAppUsesNonExemptEncryption=false`
- Associated domain configured: `applinks:poenta.app`

## Verification already completed on shared source
- TypeScript: PASS
- Expo Doctor: PASS, 18/18
- Expo public config: PASS
- Expo web export: PASS

## iOS-specific work needed
1. Run an iOS preview/simulator build from the exact same source baseline.
2. Inspect the generated `.app` / archive:
   - `CFBundleIdentifier=app.poenta`
   - version/build number matches Android baseline intent
   - `UIDeviceFamily=[1]` if iPhone-only remains the decision
   - no camera/microphone/location/tracking usage strings unless a real feature requires them
   - privacy manifest does not declare tracking/collected data unexpectedly
3. Smoke-test visual parity against Android 0.3.34:
   - Home feed
   - Breaking / מבזקים
   - Search
   - Saved
   - Settings: sources/topics/days/language selector
   - More/hamburger/legal/support screens
   - RTL physical alignment and bottom navigation order
4. Only after parity is confirmed, prepare TestFlight/App Store build.

## Current blocker for iOS build/submission
This environment is not logged into Expo/EAS:
- `npx eas-cli whoami --non-interactive` returned `Not logged in`.

For TestFlight/App Store builds, Apple Developer/EAS credentials are also required. Do not request Apple passwords or 2FA codes in chat. Use an approved secure login/token flow.
