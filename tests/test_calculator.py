import pandas as pd

from nse_analysis.indicators.calculator import calculate_batch, classify_market_insights


def test_calculate_batch_with_history() -> None:
    rows = [{"ticker_symbol": "KCB", "stock_name": "KCB Group Plc", "stock_price": 22.0, "stock_change": 0.2}]
    history = pd.DataFrame(
        {
            "ticker_symbol": ["KCB"] * 30,
            "date": pd.date_range("2025-01-01", periods=30, freq="D"),
            "stock_price": [20 + i * 0.1 for i in range(30)],
        }
    )
    output = calculate_batch(rows, history)
    assert len(output) == 1
    assert output[0]["ticker_symbol"] == "KCB"
    assert "moving_average_20d" in output[0]


def test_market_insights_outputs_leaders() -> None:
    indicator_rows = [
        {"ticker_symbol": "A", "price_change_1d_pct": 1.1, "stock_price": 10},
        {"ticker_symbol": "B", "price_change_1d_pct": -2.3, "stock_price": 8},
        {"ticker_symbol": "C", "price_change_1d_pct": 0.3, "stock_price": 5},
    ]
    insights = classify_market_insights(indicator_rows)
    assert insights["market_trend"] in {"bullish", "bearish", "flat"}
    assert len(insights["top_gainers"]) > 0
