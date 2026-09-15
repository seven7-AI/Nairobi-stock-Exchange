"""Persist and query portfolio analyses. No business rules here.

codegraph explore "save_portfolio_analysis load_portfolio_analyses"
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.web.db.analytics.models import PortfolioAnalysis

if TYPE_CHECKING:
    from app.web.services.analytics.portfolio.engine import PortfolioAnalysis as AnalysisResult


def save_portfolio_analysis(
    session: Session,
    result: AnalysisResult,
    *,
    name: str,
    as_of_date: date,
    notional: float,
    calc_version_id: int,
) -> PortfolioAnalysis:
    row = PortfolioAnalysis(
        as_of_date=as_of_date,
        name=name,
        weights=result.weights,
        notional=notional,
        status=result.expected_return.status.value,
        reason=result.expected_return.reason,
        coverage=result.coverage,
        metrics={
            "expected_return": result.expected_return.as_dict(),
            "volatility": result.volatility.as_dict(),
            "sharpe": result.sharpe.as_dict(),
            "max_drawdown": result.max_drawdown.as_dict(),
            "beta": result.beta.as_dict(),
            "average_correlation": result.average_correlation.as_dict(),
            "hhi": result.hhi,
            "effective_positions": result.effective_positions,
            "top_n_weight": result.top_n_weight,
        },
        sector_exposure=result.sector_exposure,
        industry_exposure=result.industry_exposure,
        correlation=result.correlation or None,
        days_to_liquidate=result.days_to_liquidate,
        warnings=list(result.warnings),
        inputs=result.inputs or None,
        calc_version_id=calc_version_id,
    )
    session.add(row)
    session.flush()
    return row


def load_portfolio_analyses(
    session: Session, *, name: str | None = None, as_of_date: date | None = None
) -> list[PortfolioAnalysis]:
    stmt = select(PortfolioAnalysis)
    if name is not None:
        stmt = stmt.where(PortfolioAnalysis.name == name)
    if as_of_date is not None:
        stmt = stmt.where(PortfolioAnalysis.as_of_date == as_of_date)
    return list(
        session.execute(stmt.order_by(PortfolioAnalysis.as_of_date, PortfolioAnalysis.id)).scalars()
    )


__all__ = ["load_portfolio_analyses", "save_portfolio_analysis"]
