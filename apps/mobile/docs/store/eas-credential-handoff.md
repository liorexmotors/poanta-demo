# Poenta EAS Credential Handoff

## Current blocker
EAS build cannot start on this machine because no Expo account/token is configured.

Verified commands:
```bash
npx eas-cli whoami
npx eas-cli build --profile preview --platform android --non-interactive
```

Result:
```text
Not logged in
An Expo user account is required to proceed.
Either log in with eas login or set the EXPO_TOKEN environment variable.
```

## Option A — interactive login on this machine
Use only if this environment can safely open/browser-auth your Expo account:

```bash
cd /root/.openclaw/workspace/projects/poanta-demo/apps/mobile
npx eas-cli login
npx eas-cli whoami
npx eas-cli build --profile preview --platform android
```

## Option B — token for agent/CI
Preferred for agent work. In Expo dashboard:
1. Log in to Expo.
2. Create an access token for EAS/CI.
3. Provide it via a private secure channel only — never in group chat/screenshots.
4. Set it as `EXPO_TOKEN` for the build environment.

Then run:
```bash
cd /root/.openclaw/workspace/projects/poanta-demo/apps/mobile
EXPO_TOKEN=*** npx eas-cli whoami
EXPO_TOKEN=*** npx eas-cli build --profile preview --platform android --non-interactive
```

## After EAS auth is connected
Run Android preview first:
```bash
npx eas-cli build --profile preview --platform android
```

Then iOS preview/TestFlight path:
```bash
npx eas-cli build --profile preview --platform ios
```

## Important
Do not paste Expo tokens into Telegram/group chat. Treat leaked tokens as compromised and revoke/rotate them.
