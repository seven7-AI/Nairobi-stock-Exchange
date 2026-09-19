"""corporate companies and sightings

The canonical company universe of the corporate intelligence layer and the
append-only evidence rows its listing-status rules read.

Revision ID: 20260919_0015
Revises: 20260915_0014
Create Date: 2026-09-19 07:00:00.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0015"
down_revision: str | None = "20260915_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "corporate_companies",
        sa.Column("ticker_symbol", sa.String(length=24), nullable=False),
        sa.Column("canonical_name", sa.String(length=160), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=True),
        sa.Column("instrument_type", sa.String(length=16), nullable=False),
        sa.Column("sector_code", sa.String(length=32), nullable=True),
        sa.Column("home_country", sa.String(length=2), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=True),
        sa.Column("lei", sa.String(length=20), nullable=True),
        sa.Column("registration_number", sa.String(length=64), nullable=True),
        sa.Column("exchange_ids", sa.JSON(), nullable=False),
        sa.Column("website", sa.String(length=300), nullable=True),
        sa.Column("ir_url", sa.String(length=300), nullable=True),
        sa.Column("listing_status", sa.String(length=16), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("first_listed", sa.Date(), nullable=True),
        sa.Column("delisted_on", sa.Date(), nullable=True),
        sa.Column("name_history", sa.JSON(), nullable=False),
        sa.Column("status_history", sa.JSON(), nullable=False),
        sa.Column("field_sources", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corporate_companies")),
        sa.UniqueConstraint("ticker_symbol", name=op.f("uq_corporate_companies_ticker_symbol")),
    )
    with op.batch_alter_table("corporate_companies", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_corporate_companies_isin"), ["isin"], unique=False)
        batch_op.create_index(batch_op.f("ix_corporate_companies_lei"), ["lei"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_corporate_companies_listing_status"), ["listing_status"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_corporate_companies_sector_code"), ["sector_code"], unique=False
        )

    op.create_table(
        "corporate_sightings",
        sa.Column("ticker_symbol", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corporate_sightings")),
        sa.UniqueConstraint(
            "ticker_symbol",
            "source",
            "payload_hash",
            "seen_at",
            name="uq_corporate_sighting_identity",
        ),
    )
    with op.batch_alter_table("corporate_sightings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_corporate_sightings_seen_at"), ["seen_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_corporate_sightings_source"), ["source"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_corporate_sightings_ticker_symbol"), ["ticker_symbol"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("corporate_sightings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_corporate_sightings_ticker_symbol"))
        batch_op.drop_index(batch_op.f("ix_corporate_sightings_source"))
        batch_op.drop_index(batch_op.f("ix_corporate_sightings_seen_at"))
    op.drop_table("corporate_sightings")

    with op.batch_alter_table("corporate_companies", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_corporate_companies_sector_code"))
        batch_op.drop_index(batch_op.f("ix_corporate_companies_listing_status"))
        batch_op.drop_index(batch_op.f("ix_corporate_companies_lei"))
        batch_op.drop_index(batch_op.f("ix_corporate_companies_isin"))
    op.drop_table("corporate_companies")
