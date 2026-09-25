# Indicator parity: Python replica vs TradingView (2026-09-25 daily close)

TradingView values come from TradingView's screener (via the TradingView MCP connector).
Python values come from `engine.py` on the committed daily CSVs. The last-bar close in the
CSVs differs by one cent on SPY and IWM (delayed feed), which explains the residual RSI gap.

| Symbol | Indicator | TradingView | Python | Diff |
|---|---|---|---|---|
| SPY | EMA20 / EMA100 / EMA200 | 765.832 / 747.880 / 722.333 | 765.833 / 747.880 / 722.333 | < 0.001% |
| SPY | ATR14 / RSI14 | 6.637 / 55.890 | 6.637 / 55.898 | 0.004% / 0.014% |
| QQQ | EMA20 / EMA100 / EMA200 | 725.130 / 702.988 / 672.313 | identical | < 0.001% |
| QQQ | ATR14 / RSI14 | 9.544 / 64.687 | 9.544 / 64.687 | < 0.001% |
| SMH | EMA20 / EMA100 / EMA200 | 576.887 / 554.012 / 502.422 | identical | < 0.001% |
| SMH | ATR14 / RSI14 | 16.087 / 62.720 | 16.087 / 62.720 | 0.002% / < 0.001% |
| IWM | EMA20 / EMA100 / EMA200 | 288.005 / 287.903 / 276.435 | 288.004 / 287.903 / 276.435 | < 0.001% |
| IWM | ATR14 / RSI14 | 3.513 / 34.857 | 3.513 / 34.832 | 0.015% / 0.070% |

Price data: first open, period high/low and last close match TradingView's own OHLCV feed
for AMEX:SPY, NASDAQ:QQQ, NASDAQ:SMH and AMEX:IWM (split-adjusted, not dividend-adjusted).
