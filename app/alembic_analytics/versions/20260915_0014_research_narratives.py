"""research narratives

Generated (or rejected) AI narratives over the research profile, keyed by the
context the model saw.

Revision ID: 20260915_0014
Revises: 20260915_0013
Create Date: 2026-09-15 11:00:00.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_0014"
down_revision: str | None = "20260915_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_narratives",
        sa.Column("ticker_symbol", sa.String(length=24), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=False),
        sa.Column("context_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_narratives")),
    )
    with op.batch_alter_table("research_narratives", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_research_narratives_as_of_date"), ["as_of_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_research_narratives_context_hash"), ["context_hash"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_research_narratives_ticker_symbol"), ["ticker_symbol"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("research_narratives", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_research_narratives_ticker_symbol"))
        batch_op.drop_index(batch_op.f("ix_research_narratives_context_hash"))
        batch_op.drop_index(batch_op.f("ix_research_narratives_as_of_date"))

    op.drop_table("research_narratives")
