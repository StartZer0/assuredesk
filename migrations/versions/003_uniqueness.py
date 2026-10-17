"""Enforce artifact uniqueness at the database boundary."""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    for table, name, columns in [
        ("questions", "uq_question_row", ["workbook_id", "row"]),
        ("drafts", "uq_draft_revision", ["question_id", "revision"]),
        ("exports", "uq_export_revision", ["workbook_id", "fingerprint"]),
    ]:
        if name not in {c["name"] for c in sa.inspect(bind).get_unique_constraints(table)}:
            op.create_unique_constraint(name, table, columns)
    if "uq_source_generation" not in {i["name"] for i in sa.inspect(bind).get_indexes("sources")}:
        op.create_index(
            "uq_source_generation",
            "sources",
            ["generation"],
            unique=True,
            postgresql_where=sa.text("generation != 'legacy'"),
        )


def downgrade():
    raise RuntimeError("Restore the verified pre-migration snapshot")
