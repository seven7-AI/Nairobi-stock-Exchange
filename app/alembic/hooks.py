"""Autogenerate hooks.

Kept out of ``env.py`` so they can be imported and tested directly — ``env.py``
executes a migration context at import time and cannot be imported by a test.

    codegraph explore "include_object skip_autogenerate StockAnalysisStock"
"""

from __future__ import annotations

from typing import Any


def include_object(
    obj: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Exclude tables this repository does not own from autogenerate.

    A table opts out by carrying ``info={"skip_autogenerate": True}`` — see
    ``app/web/db/models/external/stockanalysis_stock.py``. Columns, indexes and
    constraints belonging to such a table are excluded too, so a diff cannot
    leak in through a child object.

    Returning ``False`` here is what keeps Alembic from ever emitting DDL
    against the externally-owned ``stockanalysis_stocks`` table.
    """
    if type_ == "table" and obj.info.get("skip_autogenerate", False):
        return False
    parent_table = getattr(obj, "table", None)
    return not (parent_table is not None and parent_table.info.get("skip_autogenerate", False))
