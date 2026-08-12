"""Process-wide SAC store singleton.

Surfaces reference ``runtime.get_store()`` at call time (not import time) so
tests can swap in a seeded test store before exercising the REST/MCP layers.
"""
from __future__ import annotations

from .stores import SACStore

store: SACStore | None = None


def get_store() -> SACStore:
    global store
    if store is None:
        store = SACStore()
        store.init()
    return store


def set_store(new_store: SACStore) -> None:
    global store
    store = new_store
