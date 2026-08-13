"""Invites — sharing a context with someone who may not have an account yet.

Codes are stored hashed, like tokens. An invite is redeemable until it expires,
is revoked, or hits max_uses.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from ..auth.store import sha256
from ..db import ensure_aware, invites, projects, utcnow

INVITE_TTL = timedelta(days=14)


class InviteStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create(
        self,
        project_id: str,
        role: str,
        created_by_user_id: str,
        email: str | None = None,
        max_uses: int = 1,
        ttl: timedelta = INVITE_TTL,
    ) -> tuple[str, str]:
        """Create an invite. Returns (invite_id, plaintext code).

        The plaintext code is returned once and never stored.
        """
        code = secrets.token_urlsafe(24)
        invite_id = str(uuid.uuid4())
        now = utcnow()
        with self.engine.begin() as conn:
            conn.execute(
                invites.insert().values(
                    id=invite_id,
                    project_id=project_id,
                    email=(email or "").strip().lower() or None,
                    code_hash=sha256(code),
                    role=role,
                    created_by_user_id=created_by_user_id,
                    expires_at=now + ttl,
                    max_uses=max_uses,
                    used_count=0,
                    created_at=now,
                )
            )
        return invite_id, code

    def get_by_code(self, code: str) -> dict[str, Any] | None:
        """A redeemable invite, or None if missing/expired/revoked/used up."""
        with self.engine.begin() as conn:
            row = conn.execute(
                select(invites).where(invites.c.code_hash == sha256(code))
            ).first()
        if not row:
            return None
        m = dict(row._mapping)
        if m["revoked_at"] is not None:
            return None
        if ensure_aware(m["expires_at"]) <= utcnow():
            return None
        if int(m["used_count"]) >= int(m["max_uses"]):
            return None
        return m

    def redeem(self, invite_id: str, user_id: str) -> None:
        now = utcnow()
        with self.engine.begin() as conn:
            row = conn.execute(
                select(invites.c.used_count).where(invites.c.id == invite_id)
            ).first()
            used = int(row.used_count) + 1 if row else 1
            conn.execute(
                update(invites)
                .where(invites.c.id == invite_id)
                .values(
                    used_count=used,
                    accepted_at=now,
                    accepted_by_user_id=user_id,
                )
            )

    def revoke(self, invite_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(invites)
                .where(invites.c.id == invite_id)
                .values(revoked_at=utcnow())
            )

    def list_pending(self, project_id: str) -> list[dict[str, Any]]:
        now = utcnow()
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(invites)
                .where(
                    invites.c.project_id == project_id,
                    invites.c.revoked_at.is_(None),
                )
                .order_by(invites.c.created_at.desc())
            ).all()
        out = []
        for r in rows:
            m = dict(r._mapping)
            if ensure_aware(m["expires_at"]) <= now:
                continue
            if int(m["used_count"]) >= int(m["max_uses"]):
                continue
            out.append(m)
        return out

    def get_project_name(self, project_id: str) -> str:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(projects.c.name).where(projects.c.id == project_id)
            ).first()
        return row.name if row else ""
