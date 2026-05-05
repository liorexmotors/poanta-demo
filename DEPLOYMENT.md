# Poanta Deployment

Do not deploy this project through Vercel.
Do not reconnect Vercel for this project.

Publishing path: commit and push to GitHub repository `liorexmotors/poanta-demo`.

Important:
- `npm run build` must copy `feed.json`, `sw.js`, `manifest.webmanifest`, and icons into `dist/`; otherwise the site can show stale/fallback content instead of the approved Poanta feed.
- GitHub Pages is not currently enabled for this repository. The Pages workflow is manual-only until an owner enables Pages in repository settings.
