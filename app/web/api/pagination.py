"""Cursor pagination.

Every list endpoint in this service is paginated, cursor-based. Offset paging
drifts when rows are inserted mid-scan, and on ``price_bars`` — millions of
rows — a large OFFSET forces the database to walk everything it skips.

A cursor is an opaque base64 token wrapping the sort key of the last row
returned. Clients must treat it as opaque; the encoding is free to change.

    codegraph explore "CursorPage encode_cursor paginate_query"
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Annotated, Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

from app.web.core.exceptions import DataValidationError

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

PageSize = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="Rows per page")]
Cursor = Annotated[str | None, Query(description="Opaque cursor from a previous page")]


def encode_cursor(payload: dict[str, Any]) -> str:
    """Encode a sort key into an opaque token."""
    raw = json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode a cursor, or raise ``DataValidationError`` if it is malformed."""
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataValidationError("Malformed pagination cursor.") from exc
    if not isinstance(decoded, dict):
        raise DataValidationError("Malformed pagination cursor.")
    return decoded


class CursorPage(BaseModel, Generic[T]):
    """One page of results plus the cursor for the next one."""

    items: list[T]
    next_cursor: str | None = Field(
        default=None, description="Pass back as `cursor` to fetch the next page."
    )
    has_more: bool = False
    page_size: int = DEFAULT_PAGE_SIZE

    @classmethod
    def build(
        cls,
        rows: list[T],
        *,
        page_size: int,
        cursor_for: Any = None,
    ) -> CursorPage[T]:
        """Build a page from ``page_size + 1`` fetched rows.

        Fetching one extra row is how ``has_more`` is known without a COUNT.
        """
        has_more = len(rows) > page_size
        items = rows[:page_size]
        next_cursor = (
            encode_cursor(cursor_for(items[-1])) if has_more and items and cursor_for else None
        )
        return cls(
            items=items, next_cursor=next_cursor, has_more=has_more, page_size=page_size
        )


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "Cursor",
    "CursorPage",
    "PageSize",
    "decode_cursor",
    "encode_cursor",
]
