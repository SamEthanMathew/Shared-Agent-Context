"""Full OAuth 2.1 dance + authenticated MCP call over HTTP.

Drives an auth-mode SAC server: unauthenticated 401 → dynamic client
registration → authorize → login → consent → PKCE token exchange →
authenticated MCP initialize + tool call. Run against a local auth-mode uvicorn
(CI) or a deployed instance via SAC_BASE_URL. Requires the target to be seeded
with the admin user (SAC_E2E_EMAIL/PASSWORD) and a project.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sys
from urllib.parse import parse_qs, urlparse

import httpx

BASE = os.getenv("SAC_BASE_URL", "http://127.0.0.1:8766").rstrip("/")
REDIRECT = os.getenv("SAC_E2E_REDIRECT", "http://127.0.0.1:9999/cb")
EMAIL = os.getenv("SAC_E2E_EMAIL", "admin@example.com")
PASSWORD = os.getenv("SAC_E2E_PASSWORD", os.getenv("SAC_BOOTSTRAP_ADMIN_PASSWORD", "ci-admin-pw"))


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


def main() -> int:
    verifier, challenge = _pkce()
    c = httpx.Client(follow_redirects=False, timeout=15)

    r = c.post(f"{BASE}/mcp", headers={"Accept": "application/json, text/event-stream"},
               json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "x", "version": "1"}}})
    assert r.status_code == 401, f"unauth /mcp expected 401, got {r.status_code}"
    print("[ok] unauthenticated /mcp -> 401")

    r = c.post(f"{BASE}/register", json={
        "redirect_uris": [REDIRECT], "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"], "scope": "sac.read sac.write",
        "client_name": "E2E Test Client"})
    assert r.status_code in (200, 201), r.text
    client_id = r.json()["client_id"]
    print("[ok] DCR registered")

    r = c.get(f"{BASE}/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
        "code_challenge": challenge, "code_challenge_method": "S256",
        "state": "st8", "scope": "sac.read sac.write", "resource": f"{BASE}/mcp"})
    assert r.status_code in (302, 303, 307), f"authorize -> {r.status_code}: {r.text[:200]}"
    txn = parse_qs(urlparse(r.headers["location"]).query)["txn"][0]
    print("[ok] authorize -> login")

    r = c.post(f"{BASE}/auth/login", data={"email": EMAIL, "password": PASSWORD, "txn": txn})
    assert r.status_code == 303, r.text
    r = c.post(f"{BASE}/auth/consent", data={"txn": txn, "decision": "approve"})
    assert r.status_code == 303, r.text
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q.get("state") == ["st8"]
    code = q["code"][0]
    print("[ok] login + consent -> code")

    r = c.post(f"{BASE}/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
        "client_id": client_id, "code_verifier": verifier})
    assert r.status_code == 200, r.text
    access = r.json()["access_token"]
    assert access.startswith("sac_at_")
    print("[ok] PKCE token exchange")

    auth = {"Authorization": f"Bearer {access}",
            "Accept": "application/json, text/event-stream"}
    r = c.post(f"{BASE}/mcp", headers=auth, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "e2e", "version": "1"}}})
    assert r.status_code == 200, f"authed init -> {r.status_code}: {r.text[:300]}"
    hdr = dict(auth)
    sid = r.headers.get("mcp-session-id")
    if sid:
        hdr["mcp-session-id"] = sid
    c.post(f"{BASE}/mcp", headers=hdr,
           json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    r = c.post(f"{BASE}/mcp", headers=hdr, json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "sac_status", "arguments": {}}})
    assert r.status_code == 200, r.text
    assert "v1_core_engine" in r.text
    print("[ok] authenticated MCP initialize + sac_status")
    print("\nALL OAUTH E2E CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
