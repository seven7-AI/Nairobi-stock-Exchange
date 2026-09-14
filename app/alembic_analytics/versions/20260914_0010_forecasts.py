"""forecasts and forecast evaluations

Return-forecast distributions per (ticker, origin, horizon, model, version,
calc_version) and the realised-outcome row written once the horizon has elapsed.

Revision ID: 20260914_0010
Revises: 20260914_0009
Create Date: 2026-09-14 16:00:00.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0010"
down_revision: str | None = "20260914_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forecasts",
        sa.Column("ticker_symbol", sa.String(length=24), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("horizon_months", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=32), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("expected_return", sa.Float(), nullable=True),
        sa.Column("mean_log", sa.Float(), nullable=True),
        sa.Column("sd_log", sa.Float(), nullable=True),
        sa.Column("q05", sa.Float(), nullable=True),
        sa.Column("q25", sa.Float(), nullable=True),
        sa.Column("q50", sa.Float(), nullable=True),
        sa.Column("q75", sa.Float(), nullable=True),
        sa.Column("q95", sa.Float(), nullable=True),
        sa.Column("p_positive", sa.Float(), nullable=True),
        sa.Column("p_outperform", sa.Float(), nullable=True),
        sa.Column("expected_vol", sa.Float(), nullable=True),
        sa.Column("p_drawdown", sa.Float(), nullable=True),
        sa.Column("drawdown_threshold", sa.Float(), nullable=True),
        sa.Column("benchmark", sa.String(length=24), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("calc_version_id", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["calc_version_id"],
            ["calc_versions.id"],
            name=op.f("fk_forecasts_calc_version_id_calc_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecasts")),
        sa.UniqueConstraint(
            "ticker_symbol",
            "as_of_date",
            "horizon_months",
            "model",
            "model_version",
            "calc_version_id",
            name="uq_forecast_identity",
        ),
    )
    with op.batch_alter_table("forecasts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_forecasts_as_of_date"), ["as_of_date"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_forecasts_calc_version_id"), ["calc_version_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_forecasts_model"), ["model"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_forecasts_ticker_symbol"), ["ticker_symbol"], unique=False
        )

    op.create_table(
        "forecast_evaluations",
        sa.Column("forecast_id", sa.Integer(), nullable=False),
        sa.Column("realised_return", sa.Float(), nullable=False),
        sa.Column("realised_benchmark_return", sa.Float(), nullable=True),
        sa.Column("realised_end_date", sa.Date(), nullable=False),
        sa.Column("error", sa.Float(), nullable=False),
        sa.Column("directional_hit", sa.Boolean(), nullable=False),
        sa.Column("benchmark_hit", sa.Boolean(), nullable=True),
        sa.Column("within_interval", sa.Boolean(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["forecast_id"],
            ["forecasts.id"],
            name=op.f("fk_forecast_evaluations_forecast_id_forecasts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecast_evaluations")),
        sa.UniqueConstraint("forecast_id", name="uq_forecast_evaluation_forecast"),
    )
    with op.batch_alter_table("forecast_evaluations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_forecast_evaluations_forecast_id"), ["forecast_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("forecast_evaluations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_forecast_evaluations_forecast_id"))

    op.drop_table("forecast_evaluations")
    with op.batch_alter_table("forecasts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_forecasts_ticker_symbol"))
        batch_op.drop_index(batch_op.f("ix_forecasts_model"))
        batch_op.drop_index(batch_op.f("ix_forecasts_calc_version_id"))
        batch_op.drop_index(batch_op.f("ix_forecasts_as_of_date"))

    op.drop_table("forecasts")
