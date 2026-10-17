"""Initial application schema; graph checkpoint setup is an explicit CLI step."""

from alembic import op
from app.db import Base, Meta

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind)
    bind.execute(Meta.__table__.insert().values(id=1, policy=1, corpus=1))


def downgrade():
    Base.metadata.drop_all(op.get_bind())
