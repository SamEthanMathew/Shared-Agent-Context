"""Sign in with Google or GitHub.

Anthropic and OpenAI do not offer consumer OAuth SSO to third-party apps, so
"sign in with your Claude account" is not something SAC can implement. What it
can do is remove the reason people wanted it — not having to invent yet another
password — and Google covers most of that, since the account behind a ChatGPT or
Claude login is usually a Google one anyway.

Two properties matter here beyond the plumbing:

**A provider's assertion can substitute for our verification email.** Google
tells us whether it has verified the address; GitHub exposes which address is
primary *and* verified. When the provider vouches for the mailbox, requiring our
own round trip would ask the user to prove the same fact twice. When it does
not, the account stays unverified and the normal gate applies.

**Linking by email is only safe in one direction.** Finding an existing local
account by the provider's email and attaching to it is safe *only* when the
provider verified that email — otherwise anyone could create an account at a
sloppy provider bearing someone else's address and inherit their contexts.

Configured entirely by environment variable. With no credentials set the
providers are simply absent, and every surface degrades to email + password.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    authorize_url: str
    token_url: str
    scope: str

    @property
    def client_id(self) -> str:
        return os.getenv(f"SAC_{self.name.upper()}_CLIENT_ID", "").strip()

    @property
    def client_secret(self) -> str:
        return os.getenv(f"SAC_{self.name.upper()}_CLIENT_SECRET", "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)


GOOGLE = Provider(
    name="google",
    label="Google",
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    scope="openid email profile",
)

GITHUB = Provider(
    name="github",
    label="GitHub",
    authorize_url="https://github.com/login/oauth/authorize",
    token_url="https://github.com/login/oauth/access_token",
    scope="read:user user:email",
)

PROVIDERS: dict[str, Provider] = {p.name: p for p in (GOOGLE, GITHUB)}


def get_provider(name: str) -> Provider | None:
    provider = PROVIDERS.get((name or "").strip().lower())
    return provider if (provider and provider.enabled) else None


def enabled_providers() -> list[Provider]:
    return [p for p in PROVIDERS.values() if p.enabled]


def authorize_url(provider: Provider, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": provider.scope,
        "state": state,
    }
    if provider.name == "google":
        # Ask for an account chooser rather than silently reusing whichever
        # Google session the browser already has.
        params["prompt"] = "select_account"
    return f"{provider.authorize_url}?{urlencode(params)}"


def new_state() -> str:
    return secrets.token_urlsafe(24)


@dataclass(frozen=True)
class Profile:
    """What we learned about the person from the provider."""

    account_id: str
    email: str
    display_name: str
    email_verified: bool


def _http():
    import httpx

    return httpx.Client(timeout=15, follow_redirects=False)


def exchange_code(provider: Provider, code: str, redirect_uri: str) -> str:
    """Swap the authorization code for an access token."""
    with _http() as client:
        response = client.post(
            provider.token_url,
            data={
                "client_id": provider.client_id,
                "client_secret": provider.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
    if response.status_code >= 400:
        raise SSOError("the sign-in provider rejected the request")
    token = (response.json() or {}).get("access_token")
    if not token:
        raise SSOError("the sign-in provider returned no access token")
    return token


def fetch_profile(provider: Provider, access_token: str) -> Profile:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    with _http() as client:
        if provider.name == "google":
            r = client.get(
                "https://openidconnect.googleapis.com/v1/userinfo", headers=headers
            )
            if r.status_code >= 400:
                raise SSOError("could not read your Google profile")
            data: dict[str, Any] = r.json() or {}
            return Profile(
                account_id=str(data.get("sub") or ""),
                email=(data.get("email") or "").strip().lower(),
                display_name=(data.get("name") or "").strip(),
                email_verified=bool(data.get("email_verified")),
            )

        r = client.get("https://api.github.com/user", headers=headers)
        if r.status_code >= 400:
            raise SSOError("could not read your GitHub profile")
        data = r.json() or {}
        # /user hides the address when the profile email is private, and never
        # says whether it is verified — so the verified state comes from
        # /user/emails, which is the only place GitHub asserts it.
        email, verified = "", False
        er = client.get("https://api.github.com/user/emails", headers=headers)
        if er.status_code < 400:
            for entry in er.json() or []:
                if entry.get("primary") and entry.get("verified"):
                    email = (entry.get("email") or "").strip().lower()
                    verified = True
                    break
        if not email:
            email = (data.get("email") or "").strip().lower()
        return Profile(
            account_id=str(data.get("id") or ""),
            email=email,
            display_name=(data.get("name") or data.get("login") or "").strip(),
            email_verified=verified,
        )


class SSOError(Exception):
    """A provider-side failure worth showing the user in plain words."""


def link_or_create_user(store, provider_name: str, profile: Profile) -> str:
    """Resolve a provider profile to a local user id, creating one if needed.

    Order matters. An existing *link* wins, because it is the strongest claim:
    this exact provider account has signed in here before. Only then do we
    consider matching by email, and only if the provider verified it.
    """
    linked = store.auth.get_sso_identity(provider_name, profile.account_id)
    if linked:
        return linked

    if not profile.email:
        raise SSOError(
            f"your {provider_name} account has no email address we can use"
        )

    existing = store.projects.get_user_by_email(profile.email)
    if existing and not profile.email_verified:
        # Refuse rather than attach: an unverified provider email must never be
        # a way to take over an account that already exists here.
        raise SSOError(
            "that email already has an account here, but "
            f"{provider_name} has not verified it. Sign in with your password "
            "instead."
        )

    if existing:
        user_id = existing["id"]
    else:
        user_id = store.projects.create_user(
            profile.email, display_name=profile.display_name or profile.email
        )

    if profile.email_verified:
        # The provider vouches for the mailbox, so our own verification email
        # would be asking the user to prove the same thing twice.
        store.auth.mark_email_verified(user_id)

    store.auth.link_sso_identity(
        user_id, provider_name, profile.account_id, profile.email
    )
    return user_id
