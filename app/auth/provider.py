"""SACAuthProvider — the OAuth 2.1 authorization-server provider.

The MCP SDK's route handlers do the OAuth mechanics (PKCE S256 verification,
redirect-uri consistency, DCR secret generation, scope validation); this class
persists clients, threads the (user, agent_connection) binding through auth
codes and refresh tokens, mints and rotates tokens, and serves as the token
verifier via ``load_access_token``.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import AnyUrl
from mcp.server.auth.provider import AccessToken, AuthorizationCode, RefreshToken
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from ..runtime import get_store


class SACAuthorizationCode(AuthorizationCode):
    agent_connection_id: str = ""


class SACRefreshToken(RefreshToken):
    agent_connection_id: str = ""
    family_id: str = ""
    resource: str | None = None


def _redirect_host_allowed(uri: str, allowed_hosts: tuple[str, ...]) -> bool:
    if not allowed_hosts:
        return True
    host = urlparse(uri).hostname or ""
    return any(host == h or host.endswith("." + h) for h in allowed_hosts)


class SACAuthProvider:
    """Implements the OAuthAuthorizationServerProvider protocol structurally."""

    def __init__(
        self,
        public_url: str,
        allowed_redirect_hosts: tuple[str, ...] = (),
        allowed_cimd_hosts: tuple[str, ...] = (),
    ) -> None:
        self.public_url = public_url.rstrip("/")
        self.allowed_redirect_hosts = allowed_redirect_hosts
        self.allowed_cimd_hosts = allowed_cimd_hosts

    # --- clients ------------------------------------------------------------

    def _to_client_info(self, row: dict[str, Any]) -> OAuthClientInformationFull:
        # V1 treats every client as a PUBLIC client: token_endpoint_auth_method
        # "none" + mandatory PKCE (the SDK enforces S256). This avoids the trap
        # of storing a secret hash we cannot return for the SDK to compare, which
        # would otherwise let a "confidential" client be used without its secret.
        # PKCE (code_verifier bound to the code) is the actual protection.
        return OAuthClientInformationFull(
            client_id=row["client_id"],
            client_secret=None,
            redirect_uris=[AnyUrl(u) for u in (row["redirect_uris"] or [])],
            token_endpoint_auth_method="none",
            grant_types=row["grant_types"] or ["authorization_code", "refresh_token"],
            response_types=row["response_types"] or ["code"],
            scope=row["scope"] or None,
            client_name=row["client_name"] or None,
            client_uri=AnyUrl(row["client_uri"]) if row["client_uri"] else None,
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        store = get_store()
        if client_id.startswith("https://"):
            return await self._get_cimd_client(client_id)
        row = store.auth.get_client(client_id)
        if not row or row.get("disabled_at") is not None:
            return None
        return self._to_client_info(row)

    async def _get_cimd_client(
        self, client_id: str
    ) -> OAuthClientInformationFull | None:
        # ChatGPT Client ID Metadata Documents: client_id is an https URL whose
        # body describes the client. Fetch, validate, and cache it.
        #
        # SSRF hardening: CIMD is DISABLED unless SAC_CIMD_ALLOWED_HOSTS is set,
        # so the server never fetches an arbitrary attacker-supplied URL. The
        # allowlist is a set of public provider hosts (e.g. chatgpt.com); a bare
        # IP or internal host can't match it. Redirects are refused and the body
        # is size/time-capped below.
        if not self.allowed_cimd_hosts:
            return None
        if not _redirect_host_allowed(client_id, self.allowed_cimd_hosts):
            return None
        try:
            async with httpx.AsyncClient(
                timeout=5.0, follow_redirects=False, max_redirects=0
            ) as client:
                resp = await client.get(client_id, headers={"Accept": "application/json"})
            if resp.status_code != 200 or len(resp.content) > 65536:
                return None
            doc = resp.json()
        except (httpx.HTTPError, ValueError):
            return None
        if doc.get("client_id") != client_id:
            return None
        redirect_uris = doc.get("redirect_uris") or []
        if not redirect_uris:
            return None
        # Apply the same redirect allowlist DCR enforces. Previously a CIMD
        # document could name any redirect host (audit finding).
        if self.allowed_redirect_hosts and not all(
            _redirect_host_allowed(u, self.allowed_redirect_hosts)
            for u in redirect_uris
        ):
            return None
        store = get_store()
        store.auth.upsert_client(
            {
                "client_id": client_id,
                "client_secret_hash": None,
                "token_endpoint_auth_method": "none",
                "redirect_uris": redirect_uris,
                "grant_types": doc.get("grant_types") or ["authorization_code", "refresh_token"],
                "response_types": doc.get("response_types") or ["code"],
                "scope": doc.get("scope") or "",
                "client_name": doc.get("client_name") or "",
                "client_uri": doc.get("client_uri"),
                "logo_uri": doc.get("logo_uri"),
                "registration_source": "cimd",
                "raw_metadata": doc,
            }
        )
        return self._to_client_info(store.auth.get_client(client_id))

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        # DCR: the SDK already generated client_id/secret and validated scopes.
        #
        # V1/V2 treat every client as PUBLIC with mandatory PKCE, because we
        # store only a hash and the SDK compares plaintext — a stored secret
        # could never be verified. Rather than hand back a secret we will always
        # ignore (audit finding: clients were told client_secret_post was in
        # force when it was not), strip it here so the registration response is
        # truthful. The SDK returns this same object to the client.
        client_info.client_secret = None
        client_info.client_secret_expires_at = None
        client_info.token_endpoint_auth_method = "none"

        redirect_uris = [str(u) for u in client_info.redirect_uris]
        for uri in redirect_uris:
            if not _redirect_host_allowed(uri, self.allowed_redirect_hosts):
                from mcp.server.auth.provider import RegistrationError

                raise RegistrationError(
                    error="invalid_redirect_uri",
                    error_description=f"redirect host not allowed: {uri}",
                )
        store = get_store()
        raw = client_info.model_dump(mode="json")
        # Never persist a secret in raw_metadata (audit finding: it was stored
        # in cleartext alongside its hash).
        raw.pop("client_secret", None)
        store.auth.upsert_client(
            {
                "client_id": client_info.client_id,
                "client_secret_hash": None,
                "token_endpoint_auth_method": client_info.token_endpoint_auth_method,
                "redirect_uris": redirect_uris,
                "grant_types": list(client_info.grant_types or []),
                "response_types": list(client_info.response_types or []),
                "scope": client_info.scope or "",
                "client_name": client_info.client_name or "",
                "client_uri": str(client_info.client_uri) if client_info.client_uri else None,
                "logo_uri": str(client_info.logo_uri) if client_info.logo_uri else None,
                "registration_source": "dcr",
                "raw_metadata": raw,
            }
        )

    # --- authorize / codes --------------------------------------------------

    async def authorize(self, client, params) -> str:
        store = get_store()
        txn = store.auth.create_transaction(
            client_id=client.client_id,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided=1 if params.redirect_uri_provided_explicitly else 0,
            scopes=list(params.scopes or []),
            state=params.state,
            code_challenge=params.code_challenge,
            code_challenge_method="S256",
            resource=str(params.resource) if params.resource else None,
        )
        return f"{self.public_url}/auth/login?txn={txn}"

    async def load_authorization_code(
        self, client, authorization_code: str
    ) -> SACAuthorizationCode | None:
        store = get_store()
        row = store.auth.get_code(authorization_code)
        if not row or row["client_id"] != client.client_id:
            return None
        return SACAuthorizationCode(
            code=authorization_code,
            scopes=row["scopes"],
            expires_at=row["expires_at"].timestamp(),
            client_id=row["client_id"],
            code_challenge=row["code_challenge"],
            redirect_uri=AnyUrl(row["redirect_uri"]),
            redirect_uri_provided_explicitly=bool(row["redirect_uri_provided"]),
            resource=row["resource"],
            subject=row["user_id"],
            agent_connection_id=row["agent_connection_id"],
        )

    async def exchange_authorization_code(
        self, client, authorization_code: SACAuthorizationCode
    ) -> OAuthToken:
        # PKCE + redirect_uri already verified by the SDK handler.
        store = get_store()
        store.auth.consume_code(authorization_code.code)
        access, refresh, expires_in = store.auth.create_token_pair(
            client.client_id,
            authorization_code.subject,
            authorization_code.agent_connection_id,
            list(authorization_code.scopes),
            authorization_code.resource,
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=expires_in,
            scope=" ".join(authorization_code.scopes),
            refresh_token=refresh,
        )

    # --- refresh ------------------------------------------------------------

    async def load_refresh_token(
        self, client, refresh_token: str
    ) -> SACRefreshToken | None:
        store = get_store()
        row = store.auth.load_token(refresh_token, "refresh")
        if row is None:
            # reuse detection: a presented-but-revoked refresh token → burn family
            stale = store.auth.get_token_row_any(refresh_token, "refresh")
            if stale is not None and stale["revoked_at"] is not None:
                store.auth.revoke_family(stale["family_id"])
            return None
        if row["client_id"] != client.client_id:
            return None
        return SACRefreshToken(
            token=refresh_token,
            client_id=row["client_id"],
            scopes=row["scopes"],
            expires_at=int(row["expires_at"].timestamp()),
            subject=row["user_id"],
            agent_connection_id=row["agent_connection_id"],
            family_id=row["family_id"],
            resource=row["resource"],
        )

    async def exchange_refresh_token(
        self, client, refresh_token: SACRefreshToken, scopes: list[str]
    ) -> OAuthToken:
        store = get_store()
        # rotate: revoke the presented token, mint a new pair in the same family
        store.auth.revoke_token_by_value(refresh_token.token)
        access, refresh, expires_in = store.auth.create_token_pair(
            client.client_id,
            refresh_token.subject,
            refresh_token.agent_connection_id,
            list(scopes),
            refresh_token.resource,
            family_id=refresh_token.family_id,
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=expires_in,
            scope=" ".join(scopes),
            refresh_token=refresh,
        )

    # --- verification / revocation ------------------------------------------

    async def load_access_token(self, token: str) -> AccessToken | None:
        store = get_store()
        row = store.auth.load_token(token, "access")
        if row is None:
            return None
        user = store.projects.get_user(row["user_id"])
        conn = store.projects.get_agent_connection(row["agent_connection_id"])
        return AccessToken(
            token=token,
            client_id=row["client_id"],
            scopes=list(row["scopes"]),
            expires_at=int(row["expires_at"].timestamp()),
            resource=row["resource"],
            subject=row["user_id"],
            claims={
                "agent_connection_id": row["agent_connection_id"],
                "user_id": row["user_id"],
                "user_email": user["email"] if user else None,
                "connection_label": conn["label"] if conn else "",
            },
        )

    async def revoke_token(self, token) -> None:
        get_store().auth.revoke_token_by_value(token.token)


# Fail closed: if the operator sets no allowlist we still refuse arbitrary
# redirect hosts rather than accepting anything (audit finding: the check
# previously failed open when the env var was unset).
DEFAULT_REDIRECT_HOSTS = (
    "claude.ai",
    "claude.com",
    "chatgpt.com",
    "openai.com",
    "localhost",
    "127.0.0.1",
)


def build_provider() -> SACAuthProvider:
    public_url = (os.getenv("SAC_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")

    def _hosts(name: str) -> tuple[str, ...]:
        raw = os.getenv(name, "")
        return tuple(h.strip() for h in raw.split(",") if h.strip())

    return SACAuthProvider(
        public_url=public_url,
        allowed_redirect_hosts=_hosts("SAC_ALLOWED_REDIRECT_HOSTS") or DEFAULT_REDIRECT_HOSTS,
        allowed_cimd_hosts=_hosts("SAC_CIMD_ALLOWED_HOSTS"),
    )
