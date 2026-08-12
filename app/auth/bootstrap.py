"""Admin bootstrap. No open signup — users are provisioned here or via the CLI."""
from __future__ import annotations

import os

from ..stores import SACStore


def bootstrap_admin(store: SACStore) -> str | None:
    """Create the admin user (and a starter project) from env if no users exist.

    Returns the created user id, or None if skipped. Safe to call on every
    startup; it only acts on an empty user table. Creating a starter project
    means the admin's first connected client resolves a project automatically
    (single-membership), with no manual CLI step.
    """
    if store.projects.count_users() > 0:
        return None
    email = (os.getenv("SAC_BOOTSTRAP_ADMIN_EMAIL") or "").strip().lower()
    password = os.getenv("SAC_BOOTSTRAP_ADMIN_PASSWORD") or ""
    if not email or not password:
        return None
    user_id = store.projects.create_user(email, display_name=email, is_admin=True)
    store.auth.set_password(user_id, password)
    project_name = os.getenv("SAC_BOOTSTRAP_PROJECT_NAME", "Shared Project")
    store.projects.create_project(project_name, owner_user_id=user_id)
    return user_id
