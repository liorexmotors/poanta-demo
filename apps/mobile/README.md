# Poanta Mobile App

Expo / React Native app for the production Poenta / פואנטה store release.

## Locked v1 decisions
- Public name: `Poenta / פואנטה`.
- Bundle/package ID: `app.poenta`.
- Hebrew + RTL first.
- No login/auth in v1.
- No push notifications in v1.
- No sensitive permissions: location, camera, microphone, contacts, calendar, photos.
- Public feed: `https://poenta.app/feed.json`.
- Support/policy pages must be live under `https://poenta.app`.

## Commands
```bash
npm install
npm run typecheck
npm run doctor
npm run export:web
npx expo config --type public
```

## EAS build path
```bash
npx eas-cli whoami
npx eas build --profile preview --platform android
npx eas build --profile preview --platform ios
```

If `whoami` returns `Not logged in`, stop and connect Expo/EAS credentials before attempting real builds.

## Store preparation docs
See `docs/store/`:
- `hebrew-listing.md`
- `privacy-data-safety.md`
- `screenshot-plan.md`
