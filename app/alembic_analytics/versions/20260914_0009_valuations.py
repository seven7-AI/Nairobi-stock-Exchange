"""valuations

Fair-value rows per (ticker, as_of_date, method, calc_version): bear / base / bull per
share, the blended intrinsic value and range, upside, margin of safety, uncertainty and
the assumptions used.

Revision ID: 20260914_0009
Revises: 20260914_0008
Create Date: 2026-09-14 14:30:00.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0009"
down_revision: str | None = "20260914_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "valuations",
        sa.Column("ticker_symbol", sa.String(length=24), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("method", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("bear", sa.Float(), nullable=True),
        sa.Column("base", sa.Float(), nullable=True),
        sa.Column("bull", sa.Float(), nullable=True),
        sa.Column("fair_low", sa.Float(), nullable=True),
        sa.Column("fair_high", sa.Float(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("upside", sa.Float(), nullable=True),
        sa.Column("margin_of_safety", sa.Float(), nullable=True),
        sa.Column("uncertainty", sa.Float(), nullable=True),
        sa.Column("actionable", sa.Boolean(), nullable=True),
        sa.Column("assumptions", sa.JSON(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("calc_version_id", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["calc_version_id"],
            ["calc_versions.id"],
            name=op.f("fk_valuations_calc_version_id_calc_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_valuations")),
        sa.UniqueConstraint(
            "ticker_symbol",
            "as_of_date",
            "method",
            "calc_version_id",
            name="uq_valuation_identity",
        ),
    )
    with op.batch_alter_table("valuations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_valuations_as_of_date"), ["as_of_date"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_valuations_calc_version_id"), ["calc_version_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_valuations_method"), ["method"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_valuations_ticker_symbol"), ["ticker_symbol"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("valuations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_valuations_ticker_symbol"))
        batch_op.drop_index(batch_op.f("ix_valuations_method"))
        batch_op.drop_index(batch_op.f("ix_valuations_calc_version_id"))
        batch_op.drop_index(batch_op.f("ix_valuations_as_of_date"))

    op.drop_table("valuations")
