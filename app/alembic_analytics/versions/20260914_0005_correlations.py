"""correlations

Pairwise daily-return correlations (upper triangle) per (as_of_date, window,
calc_version) - the stock-to-stock matrix for the portfolio engine.

Revision ID: 20260914_0005
Revises: 20260913_0004
Create Date: 2026-09-14 05:32:40.539271+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0005"
down_revision: str | None = "20260913_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "correlations",
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("window", sa.String(length=8), nullable=False),
        sa.Column("ticker_a", sa.String(length=24), nullable=False),
        sa.Column("ticker_b", sa.String(length=24), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("n_obs", sa.Integer(), nullable=False),
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
            name=op.f("fk_correlations_calc_version_id_calc_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_correlations")),
        sa.UniqueConstraint(
            "as_of_date",
            "window",
            "ticker_a",
            "ticker_b",
            "calc_version_id",
            name="uq_correlation_identity",
        ),
    )
    with op.batch_alter_table("correlations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_correlations_as_of_date"), ["as_of_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_correlations_calc_version_id"), ["calc_version_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_correlations_ticker_a"), ["ticker_a"], unique=False)
        batch_op.create_index(batch_op.f("ix_correlations_ticker_b"), ["ticker_b"], unique=False)



def downgrade() -> None:
    with op.batch_alter_table("correlations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_correlations_ticker_b"))
        batch_op.drop_index(batch_op.f("ix_correlations_ticker_a"))
        batch_op.drop_index(batch_op.f("ix_correlations_calc_version_id"))
        batch_op.drop_index(batch_op.f("ix_correlations_as_of_date"))

    op.drop_table("correlations")
