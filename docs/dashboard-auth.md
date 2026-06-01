# Poenta dashboard authentication

The public Poenta app remains public. The operational dashboard routes are protected at Cloudflare Pages Functions middleware level using HTTP Basic Auth.

Protected paths:

- `/feedback-dashboard.html`
- `/feedback-dashboard`
- `/rss-dashboard.html`
- `/rss-dashboard`
- `/rss-viewer.html`
- `/rss-viewer`
- `/dashboard_ops_snapshot.json`

Required Cloudflare Pages environment variables/secrets:

- `POENTA_DASHBOARD_USER` — optional; defaults to `poenta` if unset.
- `POENTA_DASHBOARD_PASSWORD` — required secret. If missing, the dashboard fails closed with HTTP 503 instead of becoming public.

Set/rotate the password without printing it in shell history:

```bash
npx wrangler pages secret put POENTA_DASHBOARD_PASSWORD --project-name poanta-demo
```

If changing the username:

```bash
npx wrangler pages secret put POENTA_DASHBOARD_USER --project-name poanta-demo
```

Deploy after the secret exists:

```bash
npm run deploy:cloudflare
```

Verification:

```bash
# Must be 401 without credentials
curl -I https://poanta-demo.pages.dev/feedback-dashboard.html

# Must be 200 with credentials; do not paste the password into chat/logs.
curl -I -u "$POENTA_DASHBOARD_USER:$POENTA_DASHBOARD_PASSWORD" https://poanta-demo.pages.dev/feedback-dashboard.html

# Public app must remain public
curl -I https://poanta-demo.pages.dev/
```
