"""Document sources, collected documents, and extraction runs.

``corporate_sources`` is the registry of where documents come from and how each
source is doing (health, last error). ``corporate_documents`` is one row per
distinct file version the collector fetched: identity is the source plus the
page-stable URL (for signed download links, the page URL and the link text - the
signed URL itself is a credential and is never stored); a changed file at the same
identity is a new row with ``version_no + 1`` and the previous row's
``superseded_by_id`` set. Files live on disk under ``CORPORATE_DOCUMENTS_DIR``;
``path`` is relative to it. ``corporate_extractions`` records every extraction
attempt with the capabilities that were available.

    codegraph explore "CorporateDocument CorporateSource collect_documents"
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import IntIdMixin, UTCDateTime, utcnow

DOCUMENT_KINDS: tuple[str, ...] = (
    "annual_report",
    "integrated_report",
    "results",
    "subsidiary_statements",
    "announcement",
    "circular",
    "agm_notice",
    "regulator_report",
    "prospectus",
    "other",
)
PARSE_STATUSES: tuple[str, ...] = (
    "pending",
    "text_ok",
    "tables_ok",
    "ocr_pending",
    "not_extractable",
    "failed",
    "extracted",
)
SOURCE_HEALTH: tuple[str, ...] = ("ok", "degraded", "down", "blocked", "untested", "disabled")


class CorporateSource(IntIdMixin, AnalyticsBase):
    __tablename__ = "corporate_sources"

    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    base_url: Mapped[str] = mapped_column(String(300), nullable=False)
    ticker_symbol: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    rules_path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    health: Mapped[str] = mapped_column(String(12), nullable=False, default="untested")
    last_ok_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return f"<CorporateSource {self.name} {self.health}>"


class CorporateDocument(IntIdMixin, AnalyticsBase):
    __tablename__ = "corporate_documents"
    __table_args__ = (
        UniqueConstraint("source", "url", "sha256", name="uq_corporate_document_version"),
    )

    ticker_symbol: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    #: Stable identity: the document URL, or ``<page url>#<link-text hash>`` for signed links.
    url: Mapped[str] = mapped_column(String(600), nullable=False)
    final_url_host: Mapped[str | None] = mapped_column(String(120), nullable=True)
    period_end: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    published_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Relative to ``Settings.corporate_documents_dir``; never served, never logged whole.
    path: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    http_etag: Mapped[str | None] = mapped_column(String(120), nullable=True)
    http_last_modified: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    superseded_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("corporate_documents.id"), nullable=True
    )
    parse_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_layer: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    def __repr__(self) -> str:
        return f"<CorporateDocument {self.id} {self.source} {self.title[:40]!r} v{self.version_no}>"


class CorporateExtraction(IntIdMixin, AnalyticsBase):
    __tablename__ = "corporate_extractions"

    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("corporate_documents.id"), nullable=False, index=True
    )
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    pages_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tables_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    facts_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    calc_version_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("calc_versions.id"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<CorporateExtraction doc={self.document_id} {self.method} {self.status}>"


__all__ = [
    "DOCUMENT_KINDS",
    "PARSE_STATUSES",
    "SOURCE_HEALTH",
    "CorporateDocument",
    "CorporateExtraction",
    "CorporateSource",
]
