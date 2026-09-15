"""backtests

Runs, per-segment / per-series results, every trade and the daily equity curve of
the ranking-model simulations.

Revision ID: 20260915_0013
Revises: 20260914_0012
Create Date: 2026-09-15 07:00:00.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_0013"
down_revision: str | None = "20260914_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("top_n", sa.Integer(), nullable=False),
        sa.Column("weights", sa.JSON(), nullable=False),
        sa.Column("costs", sa.JSON(), nullable=False),
        sa.Column("benchmarks", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("segments", sa.Integer(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("calc_version_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["calc_version_id"],
            ["calc_versions.id"],
            name=op.f("fk_backtest_runs_calc_version_id_calc_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_runs")),
    )
    with op.batch_alter_table("backtest_runs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_backtest_runs_calc_version_id"), ["calc_version_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_backtest_runs_name"), ["name"], unique=False)
        batch_op.create_index(batch_op.f("ix_backtest_runs_purpose"), ["purpose"], unique=False)

    op.create_table(
        "backtest_results",
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("segment", sa.String(length=16), nullable=False),
        sa.Column("series", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.String(length=48), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["backtest_runs.id"], name=op.f("fk_backtest_results_run_id_backtest_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_results")),
        sa.UniqueConstraint("run_id", "segment", "series", "metric", name="uq_backtest_result"),
    )
    with op.batch_alter_table("backtest_results", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_backtest_results_run_id"), ["run_id"], unique=False)

    op.create_table(
        "backtest_positions",
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("segment", sa.String(length=16), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("ticker_symbol", sa.String(length=24), nullable=False),
        sa.Column("action", sa.String(length=8), nullable=False),
        sa.Column("shares", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["backtest_runs.id"],
            name=op.f("fk_backtest_positions_run_id_backtest_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_positions")),
    )
    with op.batch_alter_table("backtest_positions", schema=None) as batch_op:
        batch_op.create_index("ix_backtest_positions_run_day", ["run_id", "day"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_backtest_positions_run_id"), ["run_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_backtest_positions_ticker_symbol"), ["ticker_symbol"], unique=False
        )

    op.create_table(
        "backtest_equity",
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("segment", sa.String(length=16), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("benchmarks", sa.JSON(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["backtest_runs.id"], name=op.f("fk_backtest_equity_run_id_backtest_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_equity")),
        sa.UniqueConstraint("run_id", "day", name="uq_backtest_equity_day"),
    )
    with op.batch_alter_table("backtest_equity", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_backtest_equity_run_id"), ["run_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("backtest_equity", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_backtest_equity_run_id"))
    op.drop_table("backtest_equity")
    with op.batch_alter_table("backtest_positions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_backtest_positions_ticker_symbol"))
        batch_op.drop_index(batch_op.f("ix_backtest_positions_run_id"))
        batch_op.drop_index("ix_backtest_positions_run_day")
    op.drop_table("backtest_positions")
    with op.batch_alter_table("backtest_results", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_backtest_results_run_id"))
    op.drop_table("backtest_results")
    with op.batch_alter_table("backtest_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_backtest_runs_purpose"))
        batch_op.drop_index(batch_op.f("ix_backtest_runs_name"))
        batch_op.drop_index(batch_op.f("ix_backtest_runs_calc_version_id"))
    op.drop_table("backtest_runs")
