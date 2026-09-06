"""Read-only models for tables owned outside this repo.

Nothing here is Alembic-managed. See ``stockanalysis_stock`` for why.
"""

from app.web.db.models.external.stockanalysis_stock import (
    EXTERNAL_TABLE_INFO,
    StockAnalysisStock,
)

__all__ = ["EXTERNAL_TABLE_INFO", "StockAnalysisStock"]
