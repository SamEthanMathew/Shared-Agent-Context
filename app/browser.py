"""First-party browser authentication for the API.

The MCP and REST surfaces authenticate AI clients with OAuth bearer tokens. The
web app is a different kind of caller: it is first-party, same-origin, and holds
the login session cookie rather than a token. This module lets ``/v1`` accept
that cookie, and defends the one weakness the cookie introduces.

A bearer token is only ever sent deliberately. A cookie is *ambient* — the
browser attaches it to any request to this origin, including one triggered by a
page the user did not write. That is CSRF, and it is why every mutating
cookie-authenticated request must also present a value the attacking origin
cannot obtain: the double-submit token below.

The token is an HMAC of the session id rather than a random value in a table.
That keeps it stateless, and it binds the token to one session, so a token
planted by a subdomain ("cookie tossing") does not validate.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from urllib.parse import urlparse

from .identity import Principal
from .models import READ_SCOPE, WRITE_SCOPE

SESSION_COOKIE = "sac_session"
CSRF_COOKIE = "sac_csrf"
CSRF_HEADER = "X-SAC-CSRF"

# Methods that change state, and therefore need CSRF protection when the caller
# is authenticated by cookie.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_FALLBACK_SECRET = os.urandom(32)


def _secret() -> bytes:
    """Signing key for CSRF tokens.

    Falls back to a per-process random value when unset. The consequence of a
    changed key is only that existing CSRF cookies stop validating — the SPA
    reissues one on its next ``/v1/me`` call — so this fails safe rather than
    open, and never silently accepts an unsigned token.
    """
    env = os.getenv("SAC_SECRET_KEY", "")
    return env.encode() if env else _FALLBACK_SECRET


def csrf_token_for(session_id: str) -> str:
    return hmac.new(_secret(), session_id.encode(), hashlib.sha256).hexdigest()[:32]


def csrf_ok(session_id: str, presented: str | None) -> bool:
    if not presented:
        return False
    return hmac.compare_digest(csrf_token_for(session_id), presented)


def set_session_cookies(response, session_id: str, secure: bool) -> None:
    """Attach both cookies. Call this everywhere a login session is created.

    ``samesite=lax`` already stops the cookie riding along on a cross-site POST;
    the CSRF token is the second, independent layer, and the one that still holds
    if a future flow needs ``samesite=none``.
    """
    response.set_cookie(
        SESSION_COOKIE, session_id,
        httponly=True, secure=secure, samesite="lax", path="/",
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_token_for(session_id),
        # Deliberately readable by scripts: the front end has to echo it back.
        httponly=False, secure=secure, samesite="lax", path="/",
    )


def clear_session_cookies(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def principal_from_session(store, session_id: str | None) -> Principal | None:
    """Resolve the signed-in human behind a session cookie.

    Browser principals carry both scopes: OAuth scopes exist to limit what a
    *delegated* client may do on someone's behalf, and a person acting directly
    in their own browser is not a delegate. Membership and role still gate
    everything, which is where the real permission boundary lives.
    """
    if not session_id:
        return None
    user_id = store.auth.get_login_user(session_id)
    if not user_id:
        return None
    return Principal(
        user_id=user_id,
        agent_connection_id=None,
        scopes=(READ_SCOPE, WRITE_SCOPE),
        label="web",
    )


def origin_allowed(request, public_url: str) -> bool:
    """Reject a cross-origin mutation outright when the browser declares one.

    Belt-and-braces beside the CSRF token: an ``Origin`` header is sent on all
    cross-origin requests and on same-origin non-GETs, so when it is present and
    foreign we can refuse before doing any work. A missing header is not treated
    as failure — non-browser callers omit it, and the CSRF check still applies.
    """
    origin = request.headers.get("origin")
    if not origin:
        return True
    allowed = {request.url.netloc}
    if public_url:
        allowed.add(urlparse(public_url).netloc)
    return urlparse(origin).netloc in allowed
