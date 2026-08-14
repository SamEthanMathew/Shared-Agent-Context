"""Serving the built web app, and the marketing site in front of it.

The front end lives in ``web/`` and its Vite build output is committed to
``app/static/app``. Committing the build is deliberate: it keeps Node out of the
production image and off the deploy path, so a Python-only host builds and starts
the service exactly as before. ``web/README.md`` documents the rebuild step.

The marketing site is plain files in ``website/site`` — no build step at all —
and it is served by this same process rather than a separate static host. Osmos
is a hosted product, so the domain has to answer two different questions at once:
a stranger arriving at ``/`` should be told what this is, and a customer arriving
at ``/`` should be dropped into their contexts. One origin also keeps the OAuth
issuer where it is; moving the app to a subdomain to make room for a site would
change ``SAC_PUBLIC_URL`` and force every connected Claude and ChatGPT to be
re-added.

Three routing details matter:

* the app does client-side routing, so every unmatched ``/app/...`` path has to
  return ``index.html`` rather than a 404, or refreshing a deep link breaks;
* these routes must be registered before the catch-all MCP mount at the domain
  root, which would otherwise swallow them;
* nothing here may claim a path the OAuth discovery documents need. The site's
  routes are therefore named exactly — a catch-all for the site would break
  every connected client and look like a marketing change while doing it.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from .browser import SESSION_COOKIE, principal_from_session
from .runtime import get_store

STATIC_ROOT = Path(__file__).parent / "static" / "app"
INDEX = STATIC_ROOT / "index.html"

SITE_ROOT = Path(__file__).parent.parent / "website" / "site"

# The site's files carry no content hash, and its copy changes far more often
# than the app is deployed, so they are revalidated in minutes rather than
# cached for a year like the hashed build assets below.
SITE_CACHE = "public, max-age=300"

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


def _within(directory: Path, relative: str) -> Path | None:
    """Resolve ``relative`` inside ``directory``, or ``None`` if it isn't there.

    Resolved *before* the containment check, so a traversal attempt
    (``..%2f..%2fdb.sqlite``) cannot escape the directory being served from.
    Every route that reads a file off disk goes through here; a second copy of
    this check is a second chance to get it wrong.
    """
    root = directory.resolve()
    target = (root / relative).resolve()
    if not target.is_file() or root not in target.parents:
        return None
    return target


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
    """Serve a hashed build asset."""
    target = _within(STATIC_ROOT / "assets", filename)
    if target is None:
        return HTMLResponse("", status_code=404)
    # Filenames carry a content hash, so they can be cached indefinitely.
    return FileResponse(
        target, headers={"Cache-Control": "public, max-age=31536000, immutable"}
    )


@router.get("/app/{spa_path:path}", include_in_schema=False)
def app_deep_link(spa_path: str) -> Response:
    """Any other /app path is a client-side route."""
    return _index_response()


# --- the marketing site -----------------------------------------------------


def _site_page(filename: str) -> Response:
    page = _within(SITE_ROOT, filename)
    if page is None:
        return HTMLResponse("", status_code=404)
    return FileResponse(page, headers={"Cache-Control": SITE_CACHE})


@router.get("/", include_in_schema=False)
def site_root(request: Request) -> Response:
    """The pitch for a stranger; the app for someone already signed in.

    Never cached: this one URL answers differently depending on the session
    cookie, so a shared cache holding either answer would show it to the wrong
    person.
    """
    if principal_from_session(get_store(), request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse("/app", status_code=307)
    home = _within(SITE_ROOT, "index.html")
    if home is None:
        # A deployment without the site files still has a product. Falling back
        # to the old behaviour keeps the domain useful rather than 404ing.
        return RedirectResponse("/app", status_code=307)
    return FileResponse(home, headers={"Cache-Control": "no-store"})


@router.get("/get-started", include_in_schema=False)
def site_get_started() -> Response:
    return _site_page("get-started.html")


@router.get("/security", include_in_schema=False)
def site_security() -> Response:
    return _site_page("security.html")


@router.get("/pricing", include_in_schema=False)
def site_pricing() -> Response:
    return _site_page("pricing.html")


@router.get("/privacy", include_in_schema=False)
def site_privacy() -> Response:
    return _site_page("privacy.html")


@router.get("/terms", include_in_schema=False)
def site_terms() -> Response:
    return _site_page("terms.html")


@router.get("/contact", include_in_schema=False)
def site_contact() -> Response:
    return _site_page("contact.html")


# The site's own stylesheets, scripts, and images. Named by extension rather
# than served from a mount, because a mount at the root would sit in front of
# the OAuth discovery documents and the MCP endpoint.


@router.get("/{name}.css", include_in_schema=False)
def site_stylesheet(name: str) -> Response:
    return _site_page(f"{name}.css")


@router.get("/{name}.js", include_in_schema=False)
def site_script(name: str) -> Response:
    return _site_page(f"{name}.js")


@router.get("/assets/{filename}", include_in_schema=False)
def site_asset(filename: str) -> Response:
    return _site_page(f"assets/{filename}")
