"""simulations and regimes

Monte Carlo horizon distributions and scenario outcomes per (ticker, as_of_date,
horizon, method, scenario, calc_version); the market-regime label per date with its
evidence and proposed weight overrides.

Revision ID: 20260914_0011
Revises: 20260914_0010
Create Date: 2026-09-14 18:00:00.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0011"
down_revision: str | None = "20260914_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "simulations",
        sa.Column("ticker_symbol", sa.String(length=24), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=24), nullable=False),
        sa.Column("scenario", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("n_paths", sa.Integer(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("mean_return", sa.Float(), nullable=True),
        sa.Column("q05", sa.Float(), nullable=True),
        sa.Column("q25", sa.Float(), nullable=True),
        sa.Column("q50", sa.Float(), nullable=True),
        sa.Column("q75", sa.Float(), nullable=True),
        sa.Column("q95", sa.Float(), nullable=True),
        sa.Column("p_positive", sa.Float(), nullable=True),
        sa.Column("p_return_above", sa.JSON(), nullable=True),
        sa.Column("p_drawdown_above", sa.JSON(), nullable=True),
        sa.Column("expected_max_drawdown", sa.Float(), nullable=True),
        sa.Column("implied_price", sa.Float(), nullable=True),
        sa.Column("assumptions", sa.JSON(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("calc_version_id", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["calc_version_id"],
            ["calc_versions.id"],
            name=op.f("fk_simulations_calc_version_id_calc_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_simulations")),
        sa.UniqueConstraint(
            "ticker_symbol",
            "as_of_date",
            "horizon_days",
            "method",
            "scenario",
            "calc_version_id",
            name="uq_simulation_identity",
        ),
    )
    with op.batch_alter_table("simulations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_simulations_as_of_date"), ["as_of_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_simulations_calc_version_id"), ["calc_version_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_simulations_method"), ["method"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_simulations_ticker_symbol"), ["ticker_symbol"], unique=False
        )

    op.create_table(
        "regimes",
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("index_symbol", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("trend", sa.String(length=16), nullable=True),
        sa.Column("volatility", sa.String(length=16), nullable=True),
        sa.Column("risk", sa.String(length=16), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("weight_overrides", sa.JSON(), nullable=True),
        sa.Column("calc_version_id", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["calc_version_id"],
            ["calc_versions.id"],
            name=op.f("fk_regimes_calc_version_id_calc_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regimes")),
        sa.UniqueConstraint(
            "as_of_date", "index_symbol", "calc_version_id", name="uq_regime_identity"
        ),
    )
    with op.batch_alter_table("regimes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_regimes_as_of_date"), ["as_of_date"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_regimes_calc_version_id"), ["calc_version_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_regimes_index_symbol"), ["index_symbol"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_regimes_trend"), ["trend"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("regimes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_regimes_trend"))
        batch_op.drop_index(batch_op.f("ix_regimes_index_symbol"))
        batch_op.drop_index(batch_op.f("ix_regimes_calc_version_id"))
        batch_op.drop_index(batch_op.f("ix_regimes_as_of_date"))

    op.drop_table("regimes")
    with op.batch_alter_table("simulations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_simulations_ticker_symbol"))
        batch_op.drop_index(batch_op.f("ix_simulations_method"))
        batch_op.drop_index(batch_op.f("ix_simulations_calc_version_id"))
        batch_op.drop_index(batch_op.f("ix_simulations_as_of_date"))

    op.drop_table("simulations")
