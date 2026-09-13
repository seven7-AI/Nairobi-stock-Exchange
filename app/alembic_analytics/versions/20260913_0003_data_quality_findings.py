"""data quality findings

Findings from the automated data-quality checks, identified by
(check, ticker, trade_date, detail_hash) and tracked across runs: first seen,
last seen, resolved. Never deleted.

Revision ID: 20260913_0003
Revises: 20260913_0002
Create Date: 2026-09-13 14:03:31.636046+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0003"
down_revision: str | None = "20260913_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_quality_findings",
        sa.Column("check_name", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("ticker_symbol", sa.String(length=24), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("detail_hash", sa.String(length=64), nullable=False),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("first_seen_run_id", sa.Integer(), nullable=True),
        sa.Column("last_seen_run_id", sa.Integer(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_quality_findings")),
        sa.UniqueConstraint(
            "check_name",
            "ticker_symbol",
            "trade_date",
            "detail_hash",
            name="uq_dq_finding_identity",
        ),
    )
    with op.batch_alter_table("data_quality_findings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_data_quality_findings_check_name"), ["check_name"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_data_quality_findings_resolved_at"), ["resolved_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_data_quality_findings_severity"), ["severity"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_data_quality_findings_ticker_symbol"), ["ticker_symbol"], unique=False
        )



def downgrade() -> None:
    with op.batch_alter_table("data_quality_findings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_data_quality_findings_ticker_symbol"))
        batch_op.drop_index(batch_op.f("ix_data_quality_findings_severity"))
        batch_op.drop_index(batch_op.f("ix_data_quality_findings_resolved_at"))
        batch_op.drop_index(batch_op.f("ix_data_quality_findings_check_name"))

    op.drop_table("data_quality_findings")
