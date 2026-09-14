"""fundamental metrics

Statement-derived metrics (ROE, margins, leverage, cash flow, trends, growth,
CAGRs, sector-relative growth) per (ticker, as_of_date, metric, calc_version),
with the fiscal period each value describes.

Revision ID: 20260914_0006
Revises: 20260914_0005
Create Date: 2026-09-14 06:45:10.244052+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0006"
down_revision: str | None = "20260914_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fundamental_metrics",
        sa.Column("ticker_symbol", sa.String(length=24), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("metric", sa.String(length=48), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("period_type", sa.String(length=12), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
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
            name=op.f("fk_fundamental_metrics_calc_version_id_calc_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fundamental_metrics")),
        sa.UniqueConstraint(
            "ticker_symbol",
            "as_of_date",
            "metric",
            "calc_version_id",
            name="uq_fundamental_metric_identity",
        ),
    )
    with op.batch_alter_table("fundamental_metrics", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_fundamental_metrics_as_of_date"), ["as_of_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_fundamental_metrics_calc_version_id"), ["calc_version_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_fundamental_metrics_metric"), ["metric"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_fundamental_metrics_ticker_symbol"), ["ticker_symbol"], unique=False
        )



def downgrade() -> None:
    with op.batch_alter_table("fundamental_metrics", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_fundamental_metrics_ticker_symbol"))
        batch_op.drop_index(batch_op.f("ix_fundamental_metrics_metric"))
        batch_op.drop_index(batch_op.f("ix_fundamental_metrics_calc_version_id"))
        batch_op.drop_index(batch_op.f("ix_fundamental_metrics_as_of_date"))

    op.drop_table("fundamental_metrics")
