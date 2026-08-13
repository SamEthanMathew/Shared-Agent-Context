"""Serving the built web app.

The front end lives in ``web/`` and its Vite build output is committed to
``app/static/app``. Committing the build is deliberate: it keeps Node out of the
production image and off the deploy path, so a Python-only host builds and starts
the service exactly as before. ``web/README.md`` documents the rebuild step.

Two routing details matter:

* the app does client-side routing, so every unmatched ``/app/...`` path has to
  return ``index.html`` rather than a 404, or refreshing a deep link breaks;
* these routes must be registered before the catch-all MCP mount at the domain
  root, which would otherwise swallow them.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

STATIC_ROOT = Path(__file__).parent / "static" / "app"
INDEX = STATIC_ROOT / "index.html"

router = APIRouter()


def is_built() -> bool:
    return INDEX.is_file()


_MISSING_BUILD = """<!doctype html><meta charset="utf-8">
<title>Osmos</title>
<style>body{font-family:system-ui,sans-serif;background:#0B111B;color:#F7FAFF;
margin:0;display:grid;place-items:center;height:100vh;text-align:center}
code{background:#162033;padding:.15rem .4rem;border-radius:6px}
a{color:#3E8CFF}</style>
<div><h1>The web app isn't built</h1>
<p>Run <code>npm install &amp;&amp; npm run build</code> in <code>web/</code>.</p>
<p><a href="/console">Use the basic console instead</a></p></div>"""


def _index_response() -> Response:
    if not is_built():
        # A missing build is a developer mistake, not a user-facing 500 — say
        # which command fixes it and offer the server-rendered console.
        return HTMLResponse(_MISSING_BUILD, status_code=503)
    # index.html must never be cached: it names the content-hashed asset files,
    # so a stale copy pins the browser to a previous deploy.
    return FileResponse(INDEX, headers={"Cache-Control": "no-store"})


@router.get("/app", include_in_schema=False)
def app_root() -> Response:
    return _index_response()


@router.get("/app/favicon.svg", include_in_schema=False)
def favicon():
    icon = STATIC_ROOT / "favicon.svg"
    if not icon.is_file():
        return HTMLResponse("", status_code=404)
    return FileResponse(icon, media_type="image/svg+xml")


@router.get("/app/assets/{filename}", include_in_schema=False)
def asset(filename: str):
    """Serve a hashed build asset.

    Resolved and then checked against the assets directory so a traversal
    attempt (``..%2f..%2fdb.sqlite``) cannot escape it.
    """
    assets = (STATIC_ROOT / "assets").resolve()
    target = (assets / filename).resolve()
    if not target.is_file() or assets not in target.parents:
        return HTMLResponse("", status_code=404)
    # Filenames carry a content hash, so they can be cached indefinitely.
    return FileResponse(
        target, headers={"Cache-Control": "public, max-age=31536000, immutable"}
    )


@router.get("/app/{spa_path:path}", include_in_schema=False)
def app_deep_link(spa_path: str) -> Response:
    """Any other /app path is a client-side route."""
    return _index_response()


@router.get("/", include_in_schema=False)
def site_root():
    """Send people to the app; the OAuth discovery routes live at the root too."""
    return RedirectResponse("/app", status_code=307)
