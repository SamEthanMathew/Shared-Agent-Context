"""Admin bootstrap. No open signup — users are provisioned here or via the CLI."""
from __future__ import annotations

import os

from ..stores import SACStore


def bootstrap_admin(store: SACStore) -> str | None:
    """Create the admin user from env if no users exist yet.

    Returns the created user id, or None if skipped. Safe to call on every
    startup; it only acts on an empty user table.
    """
    if store.projects.count_users() > 0:
        return None
    email = (os.getenv("SAC_BOOTSTRAP_ADMIN_EMAIL") or "").strip().lower()
    password = os.getenv("SAC_BOOTSTRAP_ADMIN_PASSWORD") or ""
    if not email or not password:
        return None
    user_id = store.projects.create_user(email, display_name=email, is_admin=True)
    store.auth.set_password(user_id, password)
    return user_id
