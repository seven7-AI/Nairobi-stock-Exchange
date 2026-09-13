"""classifications

Point-in-time sector/industry assignment per instrument: one row per validity
range, with the source and evidence behind it (sector files, curated map,
instrument type). Rebuilt wholesale by `nse-analysis analytics classify`.

Revision ID: 20260913_0002
Revises: 20260913_0001
Create Date: 2026-09-13 12:24:30.644364+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0002"
down_revision: str | None = "20260913_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "classifications",
        sa.Column("ticker_symbol", sa.String(length=24), nullable=False),
        sa.Column("sector_code", sa.String(length=32), nullable=False),
        sa.Column("sector_label", sa.String(length=64), nullable=False),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classifications")),
        sa.UniqueConstraint("ticker_symbol", "valid_from", name="uq_classification_ticker_from"),
    )
    with op.batch_alter_table("classifications", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_classifications_industry"), ["industry"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_classifications_sector_code"), ["sector_code"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_classifications_ticker_symbol"), ["ticker_symbol"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("classifications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_classifications_ticker_symbol"))
        batch_op.drop_index(batch_op.f("ix_classifications_sector_code"))
        batch_op.drop_index(batch_op.f("ix_classifications_industry"))

    op.drop_table("classifications")
