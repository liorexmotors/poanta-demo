#!/usr/bin/env python3
"""Prepare clean custom-domain routes for GitHub Pages / Cloudflare Pages.

Routes:
- /              -> marketing website (home.html)
- /app/          -> Poenta app (app/index.html source)
- /dashboard/    -> feedback dashboard
- /rss-dashboard/ -> RSS dashboard helper
- /tt-rr-simulation/ -> open TT RR simulation-only page for Aliza

The app/dashboard/simulation copies get <base href="/"> so their existing relative
references continue to resolve to the root assets/feed files when served from
subdirectories.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def insert_base(html: str) -> str:
    if "<base " in html[:1000]:
        return html
    return html.replace("<head>", '<head>\n<base href="/">', 1)


def write_route(route: str, source: str | Path, *, base: bool = True) -> None:
    src = source if isinstance(source, Path) else DIST / source
    target_dir = DIST / route
    target_dir.mkdir(parents=True, exist_ok=True)
    html = src.read_text(encoding="utf-8")
    if base:
        html = insert_base(html)
    (target_dir / "index.html").write_text(html, encoding="utf-8")


def main() -> int:
    if not DIST.exists():
        raise SystemExit("dist/ does not exist. Run npm run build from the repo root.")

    app_html = DIST / "index.html"
    app_source_html = ROOT / "app" / "index.html"
    home_html = DIST / "home.html"
    if not app_source_html.exists() or not home_html.exists():
        raise SystemExit("app/index.html and dist/home.html are required")

    # Preserve the full app under /app/ from the app source, not the domain root.
    # The root index.html is the marketing website in the Pages build, so using it
    # here would incorrectly serve the home page at /app/.
    write_route("app", app_source_html, base=True)
    write_route("dashboard", "feedback-dashboard.html", base=True)
    write_route("tt-rr-simulation", "tt-rr-simulation.html", base=True)
    write_route("rss-dashboard", "rss-dashboard.html", base=True)
    write_route("rss-viewer", "rss-viewer.html", base=True)

    # Root of poenta.app is the public marketing website.
    shutil.copyfile(home_html, app_html)

    # Keep CNAME in the build output for GitHub Pages custom domain deploys.
    (DIST / "CNAME").write_text("poenta.app\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
