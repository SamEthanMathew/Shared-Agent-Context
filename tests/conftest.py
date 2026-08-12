"""Shared fixtures.

Seeds two users (alice, bob) in one project and a third (carol) in a separate
project, and returns ready-to-use identities. Identities are built directly, so
the whole suite is independent of the OAuth layer.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.identity import Principal, RequestIdentity
from app.models import READ_SCOPE, WRITE_SCOPE
from app.stores import SACStore


@dataclass
class Seed:
    store: SACStore
    alice: RequestIdentity  # owner of project P
    bob: RequestIdentity  # member of project P
    carol: RequestIdentity  # owner of a DIFFERENT project Q
    project_id: str
    other_project_id: str
    alice_user_id: str
    bob_user_id: str
    alice_conn: str
    bob_conn: str


def _principal(user_id: str, conn_id: str, label: str) -> Principal:
    return Principal(
        user_id=user_id,
        agent_connection_id=conn_id,
        scopes=(READ_SCOPE, WRITE_SCOPE),
        label=label,
    )


@pytest.fixture
def seed(tmp_path) -> Seed:
    store = SACStore(f"sqlite:///{tmp_path / 'sac_test.db'}")
    store.init()
    ps = store.projects

    alice_id = ps.create_user("alice@example.com", "Alice")
    bob_id = ps.create_user("bob@example.com", "Bob")
    carol_id = ps.create_user("carol@example.com", "Carol")

    project = ps.create_project("Shared Desktop App", owner_user_id=alice_id)
    ps.add_membership(project.id, bob_id, role="member")

    other = ps.create_project("Carol Solo Project", owner_user_id=carol_id)

    alice_conn = ps.create_agent_connection(alice_id, label="Alice / ChatGPT")
    bob_conn = ps.create_agent_connection(bob_id, label="Bob / Claude")
    carol_conn = ps.create_agent_connection(carol_id, label="Carol / Claude")

    alice = store.resolve_identity(_principal(alice_id, alice_conn, "Alice / ChatGPT"), project.id)
    bob = store.resolve_identity(_principal(bob_id, bob_conn, "Bob / Claude"), project.id)
    carol = store.resolve_identity(_principal(carol_id, carol_conn, "Carol / Claude"), other.id)

    return Seed(
        store=store,
        alice=alice,
        bob=bob,
        carol=carol,
        project_id=project.id,
        other_project_id=other.id,
        alice_user_id=alice_id,
        bob_user_id=bob_id,
        alice_conn=alice_conn,
        bob_conn=bob_conn,
    )
