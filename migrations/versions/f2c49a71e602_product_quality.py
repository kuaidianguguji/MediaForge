"""Persist segment quality reports, previous versions, and submission counts."""
from alembic import op
import sqlalchemy as sa

revision = "f2c49a71e602"
down_revision = "db5e064bd317"
branch_labels = None
depends_on = None


def upgrade():
    # Defaults backfill existing rows without rebuilding the SQLite assets table.
    op.add_column("segments", sa.Column("quality", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("segments", sa.Column("history", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("segments", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    # Recorded submissions already used an attempt before this counter existed.
    op.execute("UPDATE segments SET attempts = 1 WHERE remote_id IS NOT NULL OR asset_id IS NOT NULL OR status = 'submitting'")


def downgrade():
    with op.batch_alter_table("segments") as batch:
        batch.drop_column("attempts")
        batch.drop_column("history")
        batch.drop_column("quality")
