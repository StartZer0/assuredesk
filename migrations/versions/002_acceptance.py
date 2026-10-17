"""Add provenance, revision history, stage replay and operational records."""

from alembic import op
import sqlalchemy as sa
from app.db import Base

revision = "002"
down_revision = "001"
branch_labels = depends_on = None


def upgrade():
    # 001 historically used current metadata; tolerate both existing and fresh installations.
    additions = {
        "sources": [
            ("pipeline", sa.JSON(), "'{}'"),
            ("created", sa.Float(), "0"),
            ("generation", sa.String(64), "'legacy'"),
        ],
        "chunks": [("metadata_record", sa.JSON(), "'{}'")],
        "workbooks": [("created", sa.Float(), "0")],
        "drafts": [("claims", sa.JSON(), "'[]'")],
        "approvals": [("support_review", sa.JSON(), "'{}'")],
        "jobs": [("created", sa.Float(), "0")],
        "attempts": [("details", sa.JSON(), "'{}'")],
        "events": [("details", sa.JSON(), "'{}'")],
        "request_keys": [("created", sa.Float(), "0")],
    }
    bind = op.get_bind()
    for table, columns in additions.items():
        existing = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        for name, typ, default in columns:
            if name not in existing:
                op.add_column(table, sa.Column(name, typ, nullable=False, server_default=sa.text(default)))
                op.alter_column(table, name, server_default=None)
    for table in ("question_versions", "stages", "operational_state"):
        Base.metadata.tables[table].create(bind, checkfirst=True)
    # Existing records start their retention clock at migration, never delete them accidentally.
    for table in ("sources", "workbooks", "jobs", "request_keys"):
        op.execute(sa.text(f"UPDATE {table} SET created=EXTRACT(EPOCH FROM now()) WHERE created=0"))
    op.execute("UPDATE meta SET policy=policy+1, corpus=corpus+1 WHERE id=1")


def downgrade():
    raise RuntimeError("Restore the pre-migration backup; never silently discard audit history")
