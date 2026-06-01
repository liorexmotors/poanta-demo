# Poenta — iOS TestFlight / App Store handoff

Last updated: 2026-06-01

## Current iOS state
- Expo project: `@poenta.app/poenta`
- App name: `Poenta`
- Bundle ID: `app.poenta`
- Version: `0.1.0`
- v1 scope: iPhone only (`ios.supportsTablet=false`)
- Support email for store submission: `support@poenta.app`
- Privacy policy: `https://poenta.app/privacy`
- Terms: `https://poenta.app/terms`
- Support URL: `https://poenta.app/support`

## Verified so far
- iOS simulator/preview EAS build finished and was inspected.
- Basic simulator artifact checks passed:
  - `CFBundleIdentifier=app.poenta`
  - Display name `Poenta`
  - Version `0.1.0`, build `1`
  - iPhone-only device family
  - No camera/microphone/location/tracking permission strings
  - `PrivacyInfo.xcprivacy` exists and does not declare tracking/collected data types

## Current blocker
A real iOS device/TestFlight build requires completed Apple credentials in EAS.

Attempted command:

```bash
npx --yes eas-cli build --platform ios --profile production --non-interactive --no-wait --json
```

Result:

```text
Using remote iOS credentials (Expo server)
Distribution Certificate is not validated for non-interactive builds.
Failed to set up credentials.
Credentials are not set up. Run this command again in interactive mode.
```

This means EAS is connected enough to start credential flow, but the Apple distribution certificate / provisioning setup is not completed for non-interactive production builds.

## What Lior / Apple admin must provide or do
Do **not** paste Apple passwords, 2FA codes, private keys, or certificates in chat.

One of these paths is needed:

### Option A — interactive EAS Apple login (fastest)
Run locally in a secure terminal where the Apple account owner can complete login/2FA:

```bash
cd apps/mobile
npx --yes eas-cli build --platform ios --profile production
```

When prompted:
1. Sign in with Apple Developer account.
2. Let EAS create/manage the Distribution Certificate.
3. Let EAS create/manage the provisioning profile for bundle ID `app.poenta`.
4. Confirm the build starts.

After that, future non-interactive builds should work from Hermes/EAS using the existing Expo token.

### Option B — App Store Connect API key
Create an App Store Connect API key with enough permissions for app/build management, then store locally as secrets (not in repo/chat):
- `ASC_ISSUER_ID`
- `ASC_KEY_ID`
- `.p8` private key file path

Then EAS/automation can be configured to run without Apple ID prompts.

## App Store Connect app record checklist
In App Store Connect:
1. Create or verify app record for bundle ID `app.poenta`.
2. Primary language: Hebrew (or Hebrew/English according to listing strategy).
3. App name: `Poenta` / `פואנטה` as available.
4. Category: News.
5. Privacy policy URL: `https://poenta.app/privacy`.
6. Support URL: `https://poenta.app/support`.
7. Support email: `support@poenta.app`.
8. Export compliance: app uses standard HTTPS only; `ITSAppUsesNonExemptEncryption=false` is set in `app.json`.

## Next verification after a real iOS build finishes
1. Download `.ipa`/artifact or inspect App Store Connect/TestFlight processing status.
2. Verify bundle ID, version/build number, and device family.
3. Confirm no unexpected permission usage strings were introduced.
4. Install via TestFlight on iPhone.
5. Smoke test:
   - app launches
   - Hebrew RTL layout readable
   - feed loads from `https://poenta.app/feed.json`
   - no login/push prompts
   - support/privacy links are correct where applicable
6. Lock Apple Privacy Nutrition answers after this device-build inspection.
