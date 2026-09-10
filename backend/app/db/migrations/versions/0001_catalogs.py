"""Immutable catalogs, synthetic cases, trial evidence and completed API operations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_catalogs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ctr_catalogs",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
    )
    for name, size in (("ctr_cases", 120), ("ctr_trials", 11)):
        op.create_table(
            name,
            sa.Column(
                "catalog_id", sa.String(80), sa.ForeignKey("ctr_catalogs.id"), primary_key=True
            ),
            sa.Column("id", sa.String(size), primary_key=True),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("payload", JSONB, nullable=False),
        )
    op.create_table(
        "ctr_operations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("catalog_id", sa.String(80), sa.ForeignKey("ctr_catalogs.id"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("request", JSONB, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_ctr_operations_catalog_kind", "ctr_operations", ["catalog_id", "kind"])


def downgrade():
    # Only explicit operator invocation can remove this research schema.
    op.drop_table("ctr_operations")
    op.drop_table("ctr_trials")
    op.drop_table("ctr_cases")
    op.drop_table("ctr_catalogs")
