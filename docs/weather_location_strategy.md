# Pointa Weather Location Strategy

Status: planned after the Jerusalem fallback release.

## Current behavior

- Daily weather card is generated at 06:00 Israel time.
- Default/fallback location is Jerusalem.
- Source is the official Israel Meteorological Service RSS.

## Product direction

Keep Jerusalem as the fallback, but add an app-side location mechanism so the weather card can use the user's actual area when available.

## Recommended UX

1. Ask for browser/app location permission only when the user enables or configures weather personalization.
2. If permission is granted:
   - detect approximate coordinates;
   - map coordinates to the closest supported IMS city/area;
   - store only the chosen area/city id locally when possible, not raw coordinates.
3. If permission is denied, unavailable, or blocked:
   - use the manually selected city if one exists;
   - otherwise fall back to Jerusalem.
4. Always let the user override the detected city manually in settings.

## Privacy rule

Do not require system/browser location permission for the app to function. Weather personalization is optional.

## Implementation notes

- IMS city RSS feeds are keyed by city feed ids, e.g. Jerusalem uses `rssForecastCity_510_he.xml`.
- Add a mapping layer: coordinates/user selection → IMS city rss id.
- The 06:00 cron/feed refresh should use the resolved city per user/device when user-specific feeds exist. Until then, global static feed uses Jerusalem.
