"""analytics store bootstrap

First revision of the analytics chain: job state (job_runs), configuration
snapshots (calc_versions) and the model registry. Every later analytics table
references calc_versions so a result can always be tied to the configuration
that produced it.

Revision ID: 20260913_0001
Revises:
Create Date: 2026-09-13 08:31:03.062431+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calc_versions",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_versions")),
        sa.UniqueConstraint("name", "config_hash", name="uq_calc_version_name_hash"),
    )
    with op.batch_alter_table("calc_versions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_calc_versions_name"), ["name"], unique=False)

    op.create_table(
        "job_runs",
        sa.Column("job_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=True),
        sa.Column("watermark", sa.String(length=64), nullable=True),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("rows_skipped", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_runs")),
    )
    with op.batch_alter_table("job_runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_job_runs_job_name"), ["job_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_job_runs_started_at"), ["started_at"], unique=False)

    op.create_table(
        "model_registry",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("training_start", sa.Date(), nullable=True),
        sa.Column("training_end", sa.Date(), nullable=True),
        sa.Column("backtest_start", sa.Date(), nullable=True),
        sa.Column("backtest_end", sa.Date(), nullable=True),
        sa.Column("performance", sa.JSON(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_registry")),
        sa.UniqueConstraint("name", "version", name="uq_model_registry_name_version"),
    )
    with op.batch_alter_table("model_registry", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_model_registry_name"), ["name"], unique=False)
        batch_op.create_index(batch_op.f("ix_model_registry_status"), ["status"], unique=False)



def downgrade() -> None:
    with op.batch_alter_table("model_registry", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_model_registry_status"))
        batch_op.drop_index(batch_op.f("ix_model_registry_name"))

    op.drop_table("model_registry")
    with op.batch_alter_table("job_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_job_runs_started_at"))
        batch_op.drop_index(batch_op.f("ix_job_runs_job_name"))

    op.drop_table("job_runs")
    with op.batch_alter_table("calc_versions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_calc_versions_name"))

    op.drop_table("calc_versions")
