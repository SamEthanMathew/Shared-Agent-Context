"""relevance: precomputed search tokens, and full-text retrieval on Postgres

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-13

Adds ``memories.search_text`` — summary, tags and kind, tokenised once at write
time — and, on Postgres only, a GIN index over ``to_tsvector('english',
search_text)`` so the task-match retrieval channel is index-backed rather than a
scan.

Two decisions worth stating, because both were the alternative to something
more obvious:

**The index is an expression index, not a stored tsvector column.** A tsvector
column cannot live in ``app/db.py``'s shared metadata (SQLite has no such type),
so it would exist only here — and a Postgres database created by
``metadata.create_all`` before migrating would then be missing a column the
query names, turning every sync into an error. With an expression index, the
query is ``to_tsvector('english', search_text) @@ ...`` either way: correct
without the index, merely slower. Nothing about correctness depends on this
migration having run, which is the property that makes it safe to deploy.

**The backfill calls the application's own builder** rather than a copy frozen
here. A copy is the usual Alembic hygiene, but it would mean rows written before
this migration are searchable by slightly different rules than rows written
after — a difference nobody would ever see reported, and which would surface as
"search finds the new ones but not the old ones". One tokeniser, one meaning.

Additive and inert on arrival: existing rows keep every value they have and gain
a derived one. NOT NULL carries a server_default so the ALTER succeeds on a
populated table, and every object is guarded, since ``metadata.create_all`` at
startup may already have created the column on a database that booted before
migrating.
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# Rows per round trip during the backfill. Small enough that a large table does
# not build one enormous transaction, large enough that the migration is not
# dominated by round trips.
BATCH = 500

FTS_INDEX = "ix_memories_search_fts"


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in set(insp.get_table_names()):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _indexes(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in set(insp.get_table_names()):
        return set()
    return {i["name"] for i in insp.get_indexes(table) if i.get("name")}


def _backfill(conn) -> None:
    """Derive search_text for every existing row, in id order, in batches.

    Keyed on id rather than on ``search_text = ''`` so the loop always advances:
    a memory whose summary is entirely stopwords legitimately derives to the
    empty string, and a "find the unfilled rows" loop would never terminate on
    one.
    """
    from app.stores.memories import build_search_text

    last = ""
    while True:
        rows = conn.execute(
            sa.text(
                "SELECT id, summary, tags, kind FROM memories "
                "WHERE id > :last ORDER BY id LIMIT :n"
            ),
            {"last": last, "n": BATCH},
        ).fetchall()
        if not rows:
            return
        for row in rows:
            conn.execute(
                sa.text("UPDATE memories SET search_text = :s WHERE id = :i"),
                {
                    "s": build_search_text(row[1] or "", row[2] or "", row[3] or ""),
                    "i": row[0],
                },
            )
        last = rows[-1][0]


def upgrade() -> None:
    conn = op.get_bind()
    if "memories" not in set(sa.inspect(conn).get_table_names()):
        return

    if "search_text" not in _columns("memories"):
        op.add_column(
            "memories",
            sa.Column("search_text", sa.Text, nullable=False, server_default=""),
        )

    _backfill(conn)

    # Postgres only: SQLite has no tsvector, and the match channel falls back to
    # scanning search_text there — acceptable because SQLite is the test and
    # local-dev database, never production.
    if conn.dialect.name == "postgresql" and FTS_INDEX not in _indexes("memories"):
        op.execute(
            f"CREATE INDEX {FTS_INDEX} ON memories "
            "USING gin (to_tsvector('english', search_text))"
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql" and FTS_INDEX in _indexes("memories"):
        op.execute(f"DROP INDEX {FTS_INDEX}")
    if "search_text" in _columns("memories"):
        op.drop_column("memories", "search_text")
