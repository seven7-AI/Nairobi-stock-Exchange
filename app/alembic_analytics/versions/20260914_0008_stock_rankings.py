"""stock rankings

The composite model output per (ticker, as_of_date, model, calc_version): overall
score, per-factor percentiles, ranks, classification, value-trap risk, compounder
score and the explanation JSON.

Revision ID: 20260914_0008
Revises: 20260914_0007
Create Date: 2026-09-14 09:40:00.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0008"
down_revision: str | None = "20260914_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_rankings",
        sa.Column("ticker_symbol", sa.String(length=24), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("classification", sa.String(length=24), nullable=True),
        sa.Column("value_score", sa.Float(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("growth_score", sa.Float(), nullable=True),
        sa.Column("momentum_score", sa.Float(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("dividend_score", sa.Float(), nullable=True),
        sa.Column("liquidity_score", sa.Float(), nullable=True),
        sa.Column("market_rank", sa.Integer(), nullable=True),
        sa.Column("sector_rank", sa.Integer(), nullable=True),
        sa.Column("industry_rank", sa.Integer(), nullable=True),
        sa.Column("value_trap_risk", sa.Integer(), nullable=True),
        sa.Column("compounder_score", sa.Float(), nullable=True),
        sa.Column("explanation", sa.JSON(), nullable=False),
        sa.Column("calc_version_id", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["calc_version_id"],
            ["calc_versions.id"],
            name=op.f("fk_stock_rankings_calc_version_id_calc_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_rankings")),
        sa.UniqueConstraint(
            "ticker_symbol",
            "as_of_date",
            "model_name",
            "model_version",
            "calc_version_id",
            name="uq_stock_ranking_identity",
        ),
    )
    with op.batch_alter_table("stock_rankings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_stock_rankings_as_of_date"), ["as_of_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_stock_rankings_calc_version_id"), ["calc_version_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_stock_rankings_classification"), ["classification"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_stock_rankings_ticker_symbol"), ["ticker_symbol"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("stock_rankings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_stock_rankings_ticker_symbol"))
        batch_op.drop_index(batch_op.f("ix_stock_rankings_classification"))
        batch_op.drop_index(batch_op.f("ix_stock_rankings_calc_version_id"))
        batch_op.drop_index(batch_op.f("ix_stock_rankings_as_of_date"))

    op.drop_table("stock_rankings")
