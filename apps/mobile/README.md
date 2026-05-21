# Poanta Mobile App

Expo / React Native skeleton for the production Poanta app.

Working name only. The public store name is not final.

Principles:
- Hebrew + RTL first.
- Anonymous device id in v1.
- No push notifications in first public MVP unless explicitly added later.
- UI should stay visually aligned with the live Poanta feed: dark premium cards, yellow accent, compact news-first reading.

Commands:
```bash
npm install
npm run start
npm run android
npm run ios
npm run web
```

Store path:
1. Build local Expo MVP.
2. Connect to staging feed API.
3. Internal Android test build.
4. TestFlight build.
5. Privacy policy / support URL / store screenshots / data safety forms.
