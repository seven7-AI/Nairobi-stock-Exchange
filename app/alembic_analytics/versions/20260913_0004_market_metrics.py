"""market metrics

Price-derived metrics (returns now; momentum, risk, liquidity next), one row per
(ticker, as_of_date, metric, calc_version). value is NULL whenever status is not
known/zero and reason says why.

Revision ID: 20260913_0004
Revises: 20260913_0003
Create Date: 2026-09-13 14:51:43.748064+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0004"
down_revision: str | None = "20260913_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_metrics",
        sa.Column("ticker_symbol", sa.String(length=24), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("metric", sa.String(length=48), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("contains_flagged", sa.Boolean(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("calc_version_id", sa.Integer(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["calc_version_id"],
            ["calc_versions.id"],
            name=op.f("fk_market_metrics_calc_version_id_calc_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_metrics")),
        sa.UniqueConstraint(
            "ticker_symbol",
            "as_of_date",
            "metric",
            "calc_version_id",
            name="uq_market_metric_identity",
        ),
    )
    with op.batch_alter_table("market_metrics", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_market_metrics_as_of_date"), ["as_of_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_market_metrics_calc_version_id"), ["calc_version_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_market_metrics_metric"), ["metric"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_market_metrics_ticker_symbol"), ["ticker_symbol"], unique=False
        )



def downgrade() -> None:
    with op.batch_alter_table("market_metrics", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_market_metrics_ticker_symbol"))
        batch_op.drop_index(batch_op.f("ix_market_metrics_metric"))
        batch_op.drop_index(batch_op.f("ix_market_metrics_calc_version_id"))
        batch_op.drop_index(batch_op.f("ix_market_metrics_as_of_date"))

    op.drop_table("market_metrics")
