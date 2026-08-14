"""Admin CLI: provision users, projects, memberships, and smoke-test tokens.

Runs against the configured DATABASE_URL (Render shell or locally). Examples:

    python -m app.auth.cli add-user --email bob@x.com --password secret --name Bob
    python -m app.auth.cli add-project --owner alice@x.com --name "Desktop App"
    python -m app.auth.cli add-member --project <id> --email bob@x.com --role member
    python -m app.auth.cli mint-token --email alice@x.com --project <id>
    python -m app.auth.cli delete-user bob@x.com          # survey only
    python -m app.auth.cli delete-user bob@x.com --yes    # actually delete
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.engine import Connection

from ..db import (
    agent_connections,
    audit_events,
    authorization_codes,
    billing_events,
    context_bindings,
    context_snapshots,
    email_tokens,
    evidence_events,
    invites,
    login_sessions,
    memberships,
    memories,
    memory_relations,
    memory_versions,
    oauth_tokens,
    org_members,
    organisations,
    projects,
    rate_events,
    sessions,
    sso_identities,
    usage_daily,
    users,
    utcnow,
)
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


# --- account deletion -------------------------------------------------------
#
# website/site/privacy.html:269 and website/site/terms.html:235 tell people to
# email privacy@withosmos.com to have their account closed and its contents
# deleted, and say a person does it by hand. Until this subcommand existed the
# only hands available could add users, not remove them — the product made a
# promise the operator could not physically keep. This is that hand.
#
# It lives in the CLI rather than in a store on purpose. A primitive that erases
# a person across twenty-odd tables should not be importable by the request
# handlers; the only way to reach it is a shell on the box, which is also the
# only place the emailed request can be verified as genuine.
#
# Two policy decisions are settled below, and both are settled by what the
# privacy page already promises, not by what was convenient to implement.
#
# **1. A context this account solely owns, that other people still belong to,
# blocks the deletion.** The page makes two promises that collide over exactly
# this row: "deleting an account removes the account and the contexts you own"
# and "memory you published into someone else's shared context stays there,
# because it is part of a project that is not only yours". For a context Alice
# owns and Bob works in, honouring the first destroys Bob's memory and honouring
# the second leaves a context whose owner no longer exists — nobody can share it,
# rename it, or delete it, because every one of those paths resolves ownership
# through projects.owner_user_id. Guessing wrong is unrecoverable in one
# direction and unadministrable in the other, so the tool refuses, names the
# contexts, and asks for the ownership transfer that makes the answer
# unambiguous. Refusing costs an email round-trip; the alternatives cost someone
# else's work. The same reasoning covers an organisation whose last owner this
# is — app/stores/orgs.py:224 already refuses to remove that person through the
# normal path, and deleting their account must not be the way around it.
#
# **2. The access history survives, actor id and all.** app/retention.py:250
# keeps audit_events out of the reaper deliberately, and privacy.html:241
# publishes that choice: "Access history — indefinitely ... the only way to
# answer who could see what, and when." Those rows exist for the *other* members
# of a shared context, whose right to know who could read their memory does not
# lapse because the other party left; nulling the actor turns every entry into
# "someone" and destroys the one property the page promises. So rows attached to
# a context that survives are kept untouched. Rows attached to a context being
# deleted, and account-level rows with no context at all, go — their only
# possible subject is the departing account, so there is no one left for them to
# answer to, and the erasure side of the balance wins where the answerability
# side has no claimant. What is left behind is a user id that resolves to
# nothing, which is a correlation handle inside an already context-scoped log
# rather than a fact about a person.
#
# Note audit_events.actor_user_id carries no ForeignKey (app/db.py:503), so this
# was a free choice. The column that forced a decision is
# evidence_events.actor_user_id (app/db.py:369) — NOT NULL and a real FK — which
# is why surviving content needs the placeholder below rather than a null.

# Content that the privacy page says stays put outlives the person who wrote it,
# but memories.created_by_user_id and evidence_events.actor_user_id are NOT NULL
# foreign keys, so "keep the memory, forget the author" has nowhere to point. A
# single reserved row is that somewhere. It is preferred over widening those
# columns to nullable because every read path — provenance rendering in
# app/stores/projects.py:81, the history tab, the members list — keeps working
# unchanged and renders a neutral label, where a null would need handling at each
# of them and would show up as a blank until it was.
#
# It can never be signed into: no password hash, no SSO identity, and
# disabled_at set, which app/auth/store.py:101 and :383 refuse. The id is the
# all-zero UUID, which uuid4() cannot produce, so it cannot collide with a real
# account.
TOMBSTONE_USER_ID = "00000000-0000-0000-0000-000000000000"
TOMBSTONE_EMAIL = "deleted-account@osmos.invalid"

# Every surviving reference to a deleted person, and the column it lives in.
# Each one is authorship of something the privacy page says remains readable by
# other people; none of them confers any authority, which is what makes handing
# them to a placeholder safe. Ownership *is* authority, and is never reattributed
# — a context or organisation the account controlled is either deleted with it or
# blocks the deletion outright.
REATTRIBUTED: list[tuple] = [
    (memories, "created_by_user_id"),
    (memory_versions, "created_by_user_id"),
    (memory_relations, "created_by_user_id"),
    (memory_relations, "resolved_by_user_id"),
    (evidence_events, "actor_user_id"),
    (invites, "accepted_by_user_id"),
    (organisations, "created_by_user_id"),
]


@dataclass
class _Plan:
    """What deleting one account would do, before any of it is done."""

    user_id: str
    email: str
    dead_projects: list[tuple[str, str]] = field(default_factory=list)
    dead_orgs: list[tuple[str, str]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    # (label, table, predicate), in the order the deletes must run.
    steps: list[tuple] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    reattributions: dict[str, int] = field(default_factory=dict)
    kept_audit: int = 0

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _count(conn: Connection, table, predicate) -> int:
    return int(
        conn.execute(select(func.count()).select_from(table).where(predicate)).scalar_one()
    )


def _like_suffix(value: str) -> str:
    """LIKE pattern for a rate-limit key ending in `value`.

    Escaped because an email address may legitimately contain `_`, which LIKE
    reads as a single-character wildcard — unescaped, deleting one person's
    counters would delete a stranger's alongside them.
    """
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%:{escaped}"


def _survey(conn: Connection, user: dict) -> _Plan:
    """Work out what would go, and what stands in the way, changing nothing."""
    uid = user["id"]
    plan = _Plan(user_id=uid, email=user["email"])

    # Contexts this account owns. Ownership is projects.owner_user_id; the
    # memberships row with role='owner' is a mirror of it (app/stores/projects.py:132)
    # and is not consulted here, because a context with a stale mirror would
    # otherwise be silently skipped.
    owned = conn.execute(
        select(projects.c.id, projects.c.name).where(projects.c.owner_user_id == uid)
    ).all()
    for pid, name in owned:
        others = _count(
            conn,
            memberships,
            (memberships.c.project_id == pid) & (memberships.c.user_id != uid),
        )
        if others:
            plan.blockers.append(
                f"  context {name!r} ({pid}) is solely owned by this account and "
                f"{others} other person(s) still work in it"
            )
        else:
            plan.dead_projects.append((pid, name))
    dead_pids = [pid for pid, _ in plan.dead_projects]

    # Organisations. One dies only when this account is its last member *and*
    # every context inside it is already going: deleting an organisation that
    # still owns a live context would break projects.org_id.
    for org_id, org_role in conn.execute(
        select(org_members.c.org_id, org_members.c.org_role).where(
            org_members.c.user_id == uid
        )
    ).all():
        org = conn.execute(
            select(organisations.c.name, organisations.c.stripe_subscription_id,
                   organisations.c.subscription_status)
            .where(organisations.c.id == org_id)
        ).first()
        name = org.name if org else org_id
        members = _count(conn, org_members, org_members.c.org_id == org_id)
        strays = conn.execute(
            select(projects.c.name).where(
                projects.c.org_id == org_id, projects.c.id.notin_(dead_pids or [""])
            )
        ).all()
        if members == 1 and not strays:
            # Deleting the workspace row while Stripe still has a live
            # subscription against it throws away the only pointer we hold to
            # that subscription, and the customer keeps being charged for an
            # account they asked us to close. Cancelling needs a network call to
            # Stripe, which cannot join this transaction, so it stays a
            # precondition the operator satisfies rather than something this
            # command half-does.
            live_subscription = bool(
                org
                and org.stripe_subscription_id
                and org.subscription_status != "canceled"
            )
            if live_subscription:
                plan.blockers.append(
                    f"  organisation {name!r} ({org_id}) still has an active Stripe "
                    f"subscription ({org.subscription_status or 'unknown status'})"
                )
            else:
                plan.dead_orgs.append((org_id, name))
        elif org_role == "owner" and _count(
            conn,
            org_members,
            (org_members.c.org_id == org_id) & (org_members.c.org_role == "owner"),
        ) <= 1:
            plan.blockers.append(
                f"  organisation {name!r} ({org_id}) would be left with no owner"
            )
    dead_oids = [oid for oid, _ in plan.dead_orgs]

    # Memories that go: everything inside a context being deleted, plus this
    # account's private notes wherever they live. Private memory is readable by
    # nobody else (app/db.py:422 ties scope='private' to an owner), so removing
    # it from a context that survives takes nothing away from anyone.
    dead_memories = select(memories.c.id).where(
        or_(memories.c.project_id.in_(dead_pids), memories.c.owner_user_id == uid)
    )
    plan.steps = _deletion_steps(uid, user["email"], dead_pids, dead_oids, dead_memories)
    return plan


def _apply(conn: Connection, plan: _Plan) -> None:
    """Carry the plan out, recording what each statement actually touched.

    The counts come from the statements themselves rather than from a matching
    set of SELECTs run beforehand, so the inventory cannot describe anything but
    what happened. `_survey` deliberately counts nothing for the same reason.

    Reattribution runs after the deletes and before the users row goes, which is
    the only order that gets both halves right: a memory inside a context being
    deleted must not be reported as content someone else keeps, and the users row
    cannot go while a NOT NULL foreign key still points at it.
    """
    uid = plan.user_id
    for label, table, predicate in plan.steps:
        n = conn.execute(delete(table).where(predicate)).rowcount or 0
        if n:
            plan.counts[label] = n

    survivors = [(t, c) for t, c in REATTRIBUTED if _count(conn, t, t.c[c] == uid)]
    if survivors:
        tomb = _tombstone(conn)
        for table, column in survivors:
            n = conn.execute(
                update(table).where(table.c[column] == uid).values(**{column: tomb})
            ).rowcount or 0
            if n:
                plan.reattributions[f"{table.name}.{column}"] = n

    plan.counts["users"] = (
        conn.execute(delete(users).where(users.c.id == uid)).rowcount or 0
    )
    plan.kept_audit = _count(conn, audit_events, audit_events.c.actor_user_id == uid)


def _deletion_steps(
    uid: str, email: str, dead_pids: list[str], dead_oids: list[str], dead_memories
) -> list[tuple]:
    """The delete list, ordered so no statement ever orphans the next one.

    Order is foreign-key order, child before parent: relations and versions
    before the memories they hang off, everything project-scoped before the
    project, sessions before the agent_connections they cite. SQLite does not
    enforce foreign keys unless asked (this codebase never asks), so getting this
    wrong would pass every local test and then fail mid-transaction on Postgres
    against a real person's request.

    The users row is not here. It goes last of all, in `_apply`, once surviving
    content has been handed to the placeholder and nothing points at it.

    Two tables that look like they belong are deliberately absent. oauth_clients
    and auth_transactions carry no user column at all (app/db.py:515, :535) —
    they describe a *client* registration, which is shared across everyone who
    connected that assistant, so deleting one because this account used it would
    revoke strangers' connectors. A registration left unreferenced by this
    deletion is picked up by app/retention.py:229 on its next run, which is
    already the code that decides an abandoned client is abandoned.
    """
    return [
        ("memory_relations", memory_relations, or_(
            memory_relations.c.project_id.in_(dead_pids),
            memory_relations.c.from_memory_id.in_(dead_memories),
            memory_relations.c.to_memory_id.in_(dead_memories),
        )),
        ("memory_versions", memory_versions,
         memory_versions.c.memory_id.in_(dead_memories)),
        ("memories", memories, or_(
            memories.c.project_id.in_(dead_pids), memories.c.owner_user_id == uid
        )),
        # "What AI saw" enumerates what one person's assistant was shown,
        # including their own private notes (privacy.html:246), so every record
        # of theirs goes even where the context survives.
        ("context_snapshots", context_snapshots, or_(
            context_snapshots.c.project_id.in_(dead_pids),
            context_snapshots.c.user_id == uid,
        )),
        ("evidence_events", evidence_events, or_(
            evidence_events.c.project_id.in_(dead_pids),
            evidence_events.c.owner_user_id == uid,
        )),
        ("sessions", sessions, or_(
            sessions.c.project_id.in_(dead_pids), sessions.c.user_id == uid
        )),
        # Invites are live access machinery, not history: a code this account
        # minted must stop being redeemable the moment the account is gone.
        # Losing the row costs nothing, because who was invited to what is
        # exactly what the audit trail retains.
        ("invites", invites, or_(
            invites.c.project_id.in_(dead_pids), invites.c.created_by_user_id == uid
        )),
        ("context_bindings", context_bindings, or_(
            context_bindings.c.project_id.in_(dead_pids),
            context_bindings.c.user_id == uid,
        )),
        ("memberships", memberships, or_(
            memberships.c.project_id.in_(dead_pids), memberships.c.user_id == uid
        )),
        ("audit_events", audit_events, or_(
            audit_events.c.project_id.in_(dead_pids),
            (audit_events.c.actor_user_id == uid) & audit_events.c.project_id.is_(None),
        )),
        ("agent_connections", agent_connections, agent_connections.c.user_id == uid),
        ("oauth_tokens", oauth_tokens, oauth_tokens.c.user_id == uid),
        ("authorization_codes", authorization_codes,
         authorization_codes.c.user_id == uid),
        ("login_sessions", login_sessions, login_sessions.c.user_id == uid),
        ("email_tokens", email_tokens, email_tokens.c.user_id == uid),
        ("sso_identities", sso_identities, sso_identities.c.user_id == uid),
        ("usage_daily", usage_daily, or_(
            usage_daily.c.user_id == uid, usage_daily.c.org_id.in_(dead_oids)
        )),
        # The rate-limit key is "{bucket}:{ip}:{email}" (app/auth/web.py:36), so
        # this table holds the address itself next to the IP that typed it. The
        # daily purge would clear it eventually; a deletion request should not
        # have to wait for a cron job.
        ("rate_events", rate_events, or_(
            rate_events.c.key.like(_like_suffix(email), escape="\\"),
            rate_events.c.key.like(_like_suffix(uid), escape="\\"),
        )),
        # Raw Stripe webhook payloads carry the billing email verbatim, so they
        # are personal data and not only accounting data. They go with the
        # workspace they describe; the workspaces that survive keep theirs.
        ("billing_events", billing_events, billing_events.c.org_id.in_(dead_oids)),
        ("projects", projects, projects.c.id.in_(dead_pids)),
        ("org_members", org_members, or_(
            org_members.c.user_id == uid, org_members.c.org_id.in_(dead_oids)
        )),
        ("organisations", organisations, organisations.c.id.in_(dead_oids)),
    ]


def _tombstone(conn: Connection) -> str:
    """Return the placeholder id, creating the row the first time it is needed.

    Created lazily so a deployment where every deletion was self-contained never
    grows a phantom account it has no use for.
    """
    if conn.execute(
        select(users.c.id).where(users.c.id == TOMBSTONE_USER_ID)
    ).first() is None:
        now = utcnow()
        conn.execute(
            users.insert().values(
                id=TOMBSTONE_USER_ID,
                email=TOMBSTONE_EMAIL,
                display_name="Deleted account",
                password_hash=None,
                is_admin=0,
                created_at=now,
                disabled_at=now,
                failed_login_count=0,
            )
        )
    return TOMBSTONE_USER_ID


def _describe(plan: _Plan) -> None:
    print(f"account: {plan.email} ({plan.user_id})")
    if plan.dead_projects:
        print(f"contexts to delete ({len(plan.dead_projects)}):")
        for pid, name in plan.dead_projects:
            print(f"  {name} ({pid})")
    if plan.dead_orgs:
        print(f"organisations to delete ({len(plan.dead_orgs)}):")
        for oid, name in plan.dead_orgs:
            print(f"  {name} ({oid})")
    print(f"rows to delete ({plan.total}):")
    for label, n in sorted(plan.counts.items()):
        print(f"  {label}: {n}")
    if plan.reattributions:
        print("rows to reattribute to a deleted-account placeholder:")
        for label, n in sorted(plan.reattributions.items()):
            print(f"  {label}: {n}")
    if plan.kept_audit:
        print(
            f"audit rows kept: {plan.kept_audit} "
            f"(access history in contexts that survive)"
        )


def cmd_delete_user(args) -> int:
    """Close an account and delete what it holds, on emailed request.

    The default does not delete. A tool driven by an email someone else wrote,
    whose effect cannot be undone, must make the operator say the irreversible
    thing out loud — so --yes is the only path to a commit.

    It is one transaction either way: the dry run performs the deletion in full
    and then rolls it back. That costs a transaction nobody keeps and buys two
    things a set of counting SELECTs cannot. The numbers are the rowcounts of the
    real statements, so the inventory is not a prediction of what would happen
    but a record of what did. And every foreign key is exercised, so an ordering
    mistake surfaces on the rehearsal rather than halfway through a real
    person's request. The same transaction is why any failure leaves nothing
    behind — half a deleted account is worse than none, because the person is
    still there, pieces of them are not, and nothing records which.
    """
    store = _store()
    user = store.projects.get_user_by_email(args.email)
    if not user:
        print(f"unknown user: {args.email}")
        return 1
    if user["id"] == TOMBSTONE_USER_ID:
        # Deleting the placeholder would break the foreign keys of every piece of
        # content that was reattributed to it — the exact rows the privacy page
        # promises other people get to keep.
        print("refusing: that is the reserved deleted-account placeholder")
        return 1

    with store.engine.connect() as conn:
        txn = conn.begin()
        plan = _survey(conn, user)
        if plan.blockers:
            txn.rollback()
            print(f"account: {plan.email} ({plan.user_id})")
            print(f"refusing to delete {plan.email}:")
            for line in plan.blockers:
                print(line)
            print(
                "transfer ownership to someone who stays (or remove the other "
                "members), then re-run."
            )
            return 1

        _apply(conn, plan)
        _describe(plan)
        if not args.yes:
            txn.rollback()
            print("\ndry run: nothing was deleted. re-run with --yes to delete.")
            return 0

        # Proof the request was honoured, and the only thing that explains why
        # ids elsewhere in the trail no longer resolve. Deliberately carries the
        # counts and not the address: re-recording the identity in the act of
        # erasing it would defeat the request.
        store.audit.emit(
            "user.deleted",
            "user",
            plan.user_id,
            meta={"tables": plan.counts, "reattributed": plan.reattributions},
            conn=conn,
        )
        txn.commit()

    print(f"\ndeleted {plan.email} ({plan.total} rows)")
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

    p = sub.add_parser("delete-user")
    p.add_argument("email")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_delete_user)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
