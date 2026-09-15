"""portfolio analyses

One row per analysed hypothetical portfolio: weights, metrics (as Measure JSON),
exposures, correlation, liquidity, warnings.

Revision ID: 20260914_0012
Revises: 20260914_0011
Create Date: 2026-09-14 20:00:00.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0012"
down_revision: str | None = "20260914_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_analyses",
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("weights", sa.JSON(), nullable=False),
        sa.Column("notional", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("sector_exposure", sa.JSON(), nullable=False),
        sa.Column("industry_exposure", sa.JSON(), nullable=False),
        sa.Column("correlation", sa.JSON(), nullable=True),
        sa.Column("days_to_liquidate", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=True),
        sa.Column("calc_version_id", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["calc_version_id"],
            ["calc_versions.id"],
            name=op.f("fk_portfolio_analyses_calc_version_id_calc_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_analyses")),
    )
    with op.batch_alter_table("portfolio_analyses", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_portfolio_analyses_as_of_date"), ["as_of_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_portfolio_analyses_calc_version_id"), ["calc_version_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_portfolio_analyses_name"), ["name"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("portfolio_analyses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_portfolio_analyses_name"))
        batch_op.drop_index(batch_op.f("ix_portfolio_analyses_calc_version_id"))
        batch_op.drop_index(batch_op.f("ix_portfolio_analyses_as_of_date"))

    op.drop_table("portfolio_analyses")
