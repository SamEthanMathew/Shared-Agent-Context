"""Storage for the OAuth layer: clients, transactions, codes, tokens, sessions.

Tokens and codes are stored only as SHA-256 hashes. Passwords use bcrypt.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any

import bcrypt
from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from ..db import (
    auth_transactions,
    authorization_codes,
    ensure_aware,
    login_sessions,
    oauth_clients,
    oauth_tokens,
    users,
    utcnow,
)

ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)
CODE_TTL = timedelta(minutes=5)
TXN_TTL = timedelta(minutes=10)
LOGIN_TTL = timedelta(hours=12)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_token(prefix: str) -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


class AuthStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # --- users / passwords --------------------------------------------------

    def set_password(self, user_id: str, password: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(users).where(users.c.id == user_id).values(
                    password_hash=hash_password(password)
                )
            )

    def verify_login(self, email: str, password: str) -> dict[str, Any] | None:
        email = (email or "").strip().lower()
        with self.engine.begin() as conn:
            row = conn.execute(select(users).where(users.c.email == email)).first()
        if not row:
            return None
        m = dict(row._mapping)
        if m.get("disabled_at") is not None:
            return None
        if not verify_password(password, m.get("password_hash")):
            return None
        return m

    # --- login sessions (control-plane cookie) ------------------------------

    def create_login_session(self, user_id: str) -> str:
        sid = secrets.token_urlsafe(32)
        now = utcnow()
        with self.engine.begin() as conn:
            conn.execute(
                login_sessions.insert().values(
                    sid_hash=sha256(sid),
                    user_id=user_id,
                    created_at=now,
                    expires_at=now + LOGIN_TTL,
                )
            )
        return sid

    def get_login_user(self, sid: str | None) -> str | None:
        if not sid:
            return None
        with self.engine.begin() as conn:
            row = conn.execute(
                select(login_sessions).where(login_sessions.c.sid_hash == sha256(sid))
            ).first()
        if not row:
            return None
        m = row._mapping
        if m["revoked_at"] is not None or ensure_aware(m["expires_at"]) <= utcnow():
            return None
        return m["user_id"]

    def revoke_login_session(self, sid: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(login_sessions)
                .where(login_sessions.c.sid_hash == sha256(sid))
                .values(revoked_at=utcnow())
            )

    # --- oauth clients ------------------------------------------------------

    def upsert_client(self, info: dict[str, Any]) -> None:
        now = utcnow()
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(oauth_clients.c.client_id).where(
                    oauth_clients.c.client_id == info["client_id"]
                )
            ).first()
            values = dict(info)
            values["updated_at"] = now
            if existing:
                conn.execute(
                    update(oauth_clients)
                    .where(oauth_clients.c.client_id == info["client_id"])
                    .values(**values)
                )
            else:
                values["created_at"] = now
                conn.execute(oauth_clients.insert().values(**values))

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(oauth_clients).where(oauth_clients.c.client_id == client_id)
            ).first()
        return dict(row._mapping) if row else None

    # --- authorization transactions (pending /authorize) --------------------

    def create_transaction(self, **kwargs: Any) -> str:
        txn_id = secrets.token_urlsafe(24)
        now = utcnow()
        with self.engine.begin() as conn:
            conn.execute(
                auth_transactions.insert().values(
                    txn_id=txn_id, created_at=now, expires_at=now + TXN_TTL, **kwargs
                )
            )
        return txn_id

    def get_transaction(self, txn_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(auth_transactions).where(auth_transactions.c.txn_id == txn_id)
            ).first()
        if not row:
            return None
        m = dict(row._mapping)
        if ensure_aware(m["expires_at"]) <= utcnow() or m["completed_at"] is not None:
            return None
        return m

    def complete_transaction(self, txn_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(auth_transactions)
                .where(auth_transactions.c.txn_id == txn_id)
                .values(completed_at=utcnow())
            )

    # --- authorization codes ------------------------------------------------

    def create_code(self, **kwargs: Any) -> str:
        code = new_token("sac_ac_")
        now = utcnow()
        with self.engine.begin() as conn:
            conn.execute(
                authorization_codes.insert().values(
                    code_hash=sha256(code), created_at=now,
                    expires_at=now + CODE_TTL, **kwargs
                )
            )
        return code

    def get_code(self, code: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(authorization_codes).where(
                    authorization_codes.c.code_hash == sha256(code)
                )
            ).first()
        if not row:
            return None
        m = dict(row._mapping)
        if m["used_at"] is not None or ensure_aware(m["expires_at"]) <= utcnow():
            return None
        return m

    def consume_code(self, code: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(authorization_codes)
                .where(authorization_codes.c.code_hash == sha256(code))
                .values(used_at=utcnow())
            )

    # --- tokens -------------------------------------------------------------

    def create_token_pair(
        self,
        client_id: str,
        user_id: str,
        agent_connection_id: str,
        scopes: list[str],
        resource: str | None,
        family_id: str | None = None,
    ) -> tuple[str, str, int]:
        access = new_token("sac_at_")
        refresh = new_token("sac_rt_")
        family_id = family_id or str(uuid.uuid4())
        now = utcnow()
        access_exp = now + ACCESS_TTL
        with self.engine.begin() as conn:
            conn.execute(
                oauth_tokens.insert().values(
                    id=str(uuid.uuid4()), token_hash=sha256(access), kind="access",
                    client_id=client_id, user_id=user_id,
                    agent_connection_id=agent_connection_id, scopes=scopes,
                    resource=resource, family_id=family_id, parent_id=None,
                    expires_at=access_exp, created_at=now,
                )
            )
            conn.execute(
                oauth_tokens.insert().values(
                    id=str(uuid.uuid4()), token_hash=sha256(refresh), kind="refresh",
                    client_id=client_id, user_id=user_id,
                    agent_connection_id=agent_connection_id, scopes=scopes,
                    resource=resource, family_id=family_id, parent_id=None,
                    expires_at=now + REFRESH_TTL, created_at=now,
                )
            )
        return access, refresh, int(ACCESS_TTL.total_seconds())

    def load_token(self, token: str, kind: str) -> dict[str, Any] | None:
        """Return a live token row, or None if expired/revoked/connection-revoked."""
        with self.engine.begin() as conn:
            row = conn.execute(
                select(oauth_tokens).where(
                    oauth_tokens.c.token_hash == sha256(token),
                    oauth_tokens.c.kind == kind,
                )
            ).first()
            if not row:
                return None
            m = dict(row._mapping)
            if m["revoked_at"] is not None or ensure_aware(m["expires_at"]) <= utcnow():
                return None
            # connection revocation kills all its tokens immediately
            from ..db import agent_connections

            conn_row = conn.execute(
                select(agent_connections.c.revoked_at).where(
                    agent_connections.c.id == m["agent_connection_id"]
                )
            ).first()
            if conn_row is not None and conn_row.revoked_at is not None:
                return None
            user_row = conn.execute(
                select(users.c.disabled_at).where(users.c.id == m["user_id"])
            ).first()
            if user_row is not None and user_row.disabled_at is not None:
                return None
        return m

    def get_token_row_any(self, token: str, kind: str) -> dict[str, Any] | None:
        """Return the token row even if revoked/expired — for reuse detection."""
        with self.engine.begin() as conn:
            row = conn.execute(
                select(oauth_tokens).where(
                    oauth_tokens.c.token_hash == sha256(token),
                    oauth_tokens.c.kind == kind,
                )
            ).first()
        return dict(row._mapping) if row else None

    def revoke_token_by_value(self, token: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(oauth_tokens)
                .where(oauth_tokens.c.token_hash == sha256(token))
                .values(revoked_at=utcnow())
            )

    def revoke_family(self, family_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(oauth_tokens)
                .where(
                    oauth_tokens.c.family_id == family_id,
                    oauth_tokens.c.revoked_at.is_(None),
                )
                .values(revoked_at=utcnow())
            )
