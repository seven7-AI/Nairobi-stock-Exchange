"""corporate sources, documents and extractions

The document-source registry, collected document versions (files live on disk),
and extraction attempts with the capabilities that were available.

Revision ID: 20260919_0017
Revises: 20260919_0016
Create Date: 2026-09-19 06:29:01.166528+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0017"
down_revision: str | None = "20260919_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "corporate_documents",
        sa.Column("ticker_symbol", sa.String(length=24), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("url", sa.String(length=600), nullable=False),
        sa.Column("final_url_host", sa.String(length=120), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("published_on", sa.Date(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=300), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_etag", sa.String(length=120), nullable=True),
        sa.Column("http_last_modified", sa.String(length=64), nullable=True),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("superseded_by_id", sa.Integer(), nullable=True),
        sa.Column("parse_status", sa.String(length=16), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("text_layer", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["corporate_documents.id"],
            name=op.f("fk_corporate_documents_superseded_by_id_corporate_documents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corporate_documents")),
        sa.UniqueConstraint("source", "url", "sha256", name="uq_corporate_document_version"),
    )
    with op.batch_alter_table("corporate_documents", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_corporate_documents_fiscal_year"), ["fiscal_year"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_corporate_documents_kind"), ["kind"], unique=False)
        batch_op.create_index(batch_op.f("ix_corporate_documents_sha256"), ["sha256"], unique=False)
        batch_op.create_index(batch_op.f("ix_corporate_documents_source"), ["source"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_corporate_documents_ticker_symbol"), ["ticker_symbol"], unique=False
        )

    op.create_table(
        "corporate_sources",
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("base_url", sa.String(length=300), nullable=False),
        sa.Column("ticker_symbol", sa.String(length=24), nullable=True),
        sa.Column("rules_path", sa.String(length=200), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("health", sa.String(length=12), nullable=False),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corporate_sources")),
        sa.UniqueConstraint("name", name=op.f("uq_corporate_sources_name")),
    )
    with op.batch_alter_table("corporate_sources", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_corporate_sources_ticker_symbol"), ["ticker_symbol"], unique=False
        )

    op.create_table(
        "corporate_extractions",
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("parser_version", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("pages_done", sa.Integer(), nullable=False),
        sa.Column("pages_total", sa.Integer(), nullable=True),
        sa.Column("tables_found", sa.Integer(), nullable=False),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.Column("facts_written", sa.Integer(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("calc_version_id", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["calc_version_id"],
            ["calc_versions.id"],
            name=op.f("fk_corporate_extractions_calc_version_id_calc_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["corporate_documents.id"],
            name=op.f("fk_corporate_extractions_document_id_corporate_documents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corporate_extractions")),
    )
    with op.batch_alter_table("corporate_extractions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_corporate_extractions_document_id"), ["document_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_corporate_extractions_parser_version"), ["parser_version"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("corporate_extractions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_corporate_extractions_parser_version"))
        batch_op.drop_index(batch_op.f("ix_corporate_extractions_document_id"))

    op.drop_table("corporate_extractions")
    with op.batch_alter_table("corporate_sources", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_corporate_sources_ticker_symbol"))

    op.drop_table("corporate_sources")
    with op.batch_alter_table("corporate_documents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_corporate_documents_ticker_symbol"))
        batch_op.drop_index(batch_op.f("ix_corporate_documents_source"))
        batch_op.drop_index(batch_op.f("ix_corporate_documents_sha256"))
        batch_op.drop_index(batch_op.f("ix_corporate_documents_kind"))
        batch_op.drop_index(batch_op.f("ix_corporate_documents_fiscal_year"))

    op.drop_table("corporate_documents")
