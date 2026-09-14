"""factor scores

Cross-sectional factor z-scores with market/sector/industry percentiles,
coverage and the per-input breakdown, per (ticker, as_of_date, factor,
calc_version).

Revision ID: 20260914_0007
Revises: 20260914_0006
Create Date: 2026-09-14 07:52:36.165201+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0007"
down_revision: str | None = "20260914_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "factor_scores",
        sa.Column("ticker_symbol", sa.String(length=24), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("factor", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=False),
        sa.Column("percentile_market", sa.Float(), nullable=True),
        sa.Column("percentile_sector", sa.Float(), nullable=True),
        sa.Column("percentile_industry", sa.Float(), nullable=True),
        sa.Column("group_sizes", sa.JSON(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=True),
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
            name=op.f("fk_factor_scores_calc_version_id_calc_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_factor_scores")),
        sa.UniqueConstraint(
            "ticker_symbol",
            "as_of_date",
            "factor",
            "calc_version_id",
            name="uq_factor_score_identity",
        ),
    )
    with op.batch_alter_table("factor_scores", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_factor_scores_as_of_date"), ["as_of_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_factor_scores_calc_version_id"), ["calc_version_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_factor_scores_factor"), ["factor"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_factor_scores_ticker_symbol"), ["ticker_symbol"], unique=False
        )



def downgrade() -> None:
    with op.batch_alter_table("factor_scores", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_factor_scores_ticker_symbol"))
        batch_op.drop_index(batch_op.f("ix_factor_scores_factor"))
        batch_op.drop_index(batch_op.f("ix_factor_scores_calc_version_id"))
        batch_op.drop_index(batch_op.f("ix_factor_scores_as_of_date"))

    op.drop_table("factor_scores")
