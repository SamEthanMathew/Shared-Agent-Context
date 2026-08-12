"""Admin CLI: provision users, projects, memberships, and smoke-test tokens.

Runs against the configured DATABASE_URL (Render shell or locally). Examples:

    python -m app.auth.cli add-user --email bob@x.com --password secret --name Bob
    python -m app.auth.cli add-project --owner alice@x.com --name "Desktop App"
    python -m app.auth.cli add-member --project <id> --email bob@x.com --role member
    python -m app.auth.cli mint-token --email alice@x.com --project <id>
"""
from __future__ import annotations

import argparse
import sys

from ..stores import SACStore


def _store() -> SACStore:
    store = SACStore()
    store.init()
    return store


def cmd_add_user(args) -> int:
    store = _store()
    if store.projects.get_user_by_email(args.email):
        print(f"user already exists: {args.email}")
        return 1
    uid = store.projects.create_user(args.email, args.name or args.email, is_admin=args.admin)
    store.auth.set_password(uid, args.password)
    print(f"created user {args.email} ({uid})")
    return 0


def cmd_add_project(args) -> int:
    store = _store()
    owner = store.projects.get_user_by_email(args.owner)
    if not owner:
        print(f"unknown owner: {args.owner}")
        return 1
    project = store.projects.create_project(args.name, owner_user_id=owner["id"])
    print(f"created project {project.name} ({project.id})")
    return 0


def cmd_add_member(args) -> int:
    store = _store()
    user = store.projects.get_user_by_email(args.email)
    if not user:
        print(f"unknown user: {args.email}")
        return 1
    store.projects.add_membership(args.project, user["id"], role=args.role)
    print(f"added {args.email} to {args.project} as {args.role}")
    return 0


def cmd_mint_token(args) -> int:
    """Mint an access+refresh token for post-deploy smoke tests."""
    store = _store()
    user = store.projects.get_user_by_email(args.email)
    if not user:
        print(f"unknown user: {args.email}")
        return 1
    conn_id = store.projects.create_agent_connection(
        user["id"], oauth_client_id="cli", label="CLI smoke token",
        provider_hint="cli", granted_scopes=["sac.read", "sac.write"],
    )
    resource = (args.resource or "").rstrip("/") or None
    access, refresh, expires_in = store.auth.create_token_pair(
        "cli", user["id"], conn_id, ["sac.read", "sac.write"], resource
    )
    print(f"access_token: {access}")
    print(f"refresh_token: {refresh}")
    print(f"expires_in: {expires_in}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.auth.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add-user")
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--admin", action="store_true")
    p.set_defaults(func=cmd_add_user)

    p = sub.add_parser("add-project")
    p.add_argument("--owner", required=True)
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_add_project)

    p = sub.add_parser("add-member")
    p.add_argument("--project", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--role", default="member")
    p.set_defaults(func=cmd_add_member)

    p = sub.add_parser("mint-token")
    p.add_argument("--email", required=True)
    p.add_argument("--project", default="")
    p.add_argument("--resource", default="")
    p.set_defaults(func=cmd_mint_token)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
