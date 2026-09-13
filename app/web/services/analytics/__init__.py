"""The quantitative research engine.

Pure calculation engines (returns, momentum, risk, liquidity, fundamentals,
factors, ranking, valuation, forecasting, backtesting) live in sub-packages;
each takes plain data in and returns ``Measure``-typed results out, with no
I/O. Writers persist those results to the analytics store with a
``calc_version`` so every number stays reproducible.

    codegraph explore "app/web/services/analytics store.py"
"""
