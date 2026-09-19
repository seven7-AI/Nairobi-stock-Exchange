"""corporate entities and relationships

Legal entities (listed groups, subsidiaries, associates, branches) and the
bitemporal ownership relationships between them.

Revision ID: 20260919_0016
Revises: 20260919_0015
Create Date: 2026-09-19 05:26:55.851566+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0016"
down_revision: str | None = "20260919_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "corporate_entities",
        sa.Column("entity_key", sa.String(length=64), nullable=False),
        sa.Column("canonical_key", sa.String(length=240), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("jurisdiction", sa.String(length=2), nullable=False),
        sa.Column("entity_type", sa.String(length=24), nullable=False),
        sa.Column("lei", sa.String(length=20), nullable=True),
        sa.Column("registration_number", sa.String(length=64), nullable=True),
        sa.Column("identifiers", sa.JSON(), nullable=False),
        sa.Column("listed_ticker", sa.String(length=24), nullable=True),
        sa.Column("group_ticker", sa.String(length=24), nullable=True),
        sa.Column("resolution_method", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("merged_into_id", sa.Integer(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
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
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["merged_into_id"],
            ["corporate_entities.id"],
            name=op.f("fk_corporate_entities_merged_into_id_corporate_entities"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corporate_entities")),
        sa.UniqueConstraint("entity_key", name=op.f("uq_corporate_entities_entity_key")),
        sa.UniqueConstraint("lei", name=op.f("uq_corporate_entities_lei")),
    )
    with op.batch_alter_table("corporate_entities", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_corporate_entities_group_ticker"), ["group_ticker"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_corporate_entities_jurisdiction"), ["jurisdiction"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_corporate_entities_listed_ticker"), ["listed_ticker"], unique=False
        )
        batch_op.create_index(
            "uq_corporate_entity_registration", ["registration_number", "jurisdiction"], unique=True
        )

    op.create_table(
        "corporate_relationships",
        sa.Column("parent_entity_id", sa.Integer(), nullable=False),
        sa.Column("child_entity_id", sa.Integer(), nullable=False),
        sa.Column("relationship_type", sa.String(length=24), nullable=False),
        sa.Column("ownership_pct_value", sa.Float(), nullable=True),
        sa.Column("ownership_pct_status", sa.String(length=16), nullable=False),
        sa.Column("ownership_pct_reason", sa.Text(), nullable=True),
        sa.Column("ownership_basis", sa.String(length=16), nullable=False),
        sa.Column("principal_activity", sa.String(length=200), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("table_ref", sa.String(length=24), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "superseded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("supersession_reason", sa.String(length=16), nullable=True),
        sa.Column("version_key", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("source_kind", sa.String(length=12), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("superseded_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["child_entity_id"],
            ["corporate_entities.id"],
            name=op.f("fk_corporate_relationships_child_entity_id_corporate_entities"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_entity_id"],
            ["corporate_entities.id"],
            name=op.f("fk_corporate_relationships_parent_entity_id_corporate_entities"),
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["corporate_relationships.id"],
            name=op.f("fk_corporate_relationships_superseded_by_id_corporate_relationships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corporate_relationships")),
    )
    with op.batch_alter_table("corporate_relationships", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_corporate_relationships_child_entity_id"),
            ["child_entity_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_corporate_relationships_effective_from"),
            ["effective_from"],
            unique=False,
        )
        batch_op.create_index(
            "ix_corporate_relationships_parent_current",
            ["parent_entity_id", "superseded_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_corporate_relationships_recorded_at"), ["recorded_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_corporate_relationships_source_id"), ["source_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_corporate_relationships_superseded_at"), ["superseded_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_corporate_relationships_version_key"), ["version_key"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("corporate_relationships", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_corporate_relationships_version_key"))
        batch_op.drop_index(batch_op.f("ix_corporate_relationships_superseded_at"))
        batch_op.drop_index(batch_op.f("ix_corporate_relationships_source_id"))
        batch_op.drop_index(batch_op.f("ix_corporate_relationships_recorded_at"))
        batch_op.drop_index("ix_corporate_relationships_parent_current")
        batch_op.drop_index(batch_op.f("ix_corporate_relationships_effective_from"))
        batch_op.drop_index(batch_op.f("ix_corporate_relationships_child_entity_id"))

    op.drop_table("corporate_relationships")
    with op.batch_alter_table("corporate_entities", schema=None) as batch_op:
        batch_op.drop_index("uq_corporate_entity_registration")
        batch_op.drop_index(batch_op.f("ix_corporate_entities_listed_ticker"))
        batch_op.drop_index(batch_op.f("ix_corporate_entities_jurisdiction"))
        batch_op.drop_index(batch_op.f("ix_corporate_entities_group_ticker"))

    op.drop_table("corporate_entities")
