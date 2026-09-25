# Core only: `trend_core_professional.pine` vs the full script (run of 2026-09-25)

`trend_core_professional.pine` is the Core position of `trend_core_wae_professional.pine` with the
three-tier WAE overlay removed: same Core rules, defaults, execution settings and alert payloads;
no overlay inputs, WAE/HTF/RSI filters or event guards. It was run in TradingView's Strategy Tester
on daily SPY, QQQ, SMH and IWM with the runner (`TV_SCRIPT=... TV_OUT_PREFIX=core_only_`), and the
Python replica was run with the overlay disabled (`core_only_python.csv`, both settings, every window).
Screenshots: `core_only_<SYMBOL>.png` and `core_only_<SYMBOL>_list_of_trades.png`; parsed report:
`core_only_results.json`. Windows and conventions are as in `RESULTS.md` (FULL = 2008-01-01 to
2026-09-25, Python totals = P&L/yr x 18.70).

## TradingView, Core only vs Python, Core only

| Symbol | TV net profit | Python total | TV trades (W/L) | Python trades | TV win % | Py win % | TV PF | Py PF | TV max DD (of initial capital) | Py TV-definition DD |
|---|---|---|---|---|---|---|---|---|---|---|
| SPY | +33,595.16 | 33,664 | 37 (16/21) | 37 | 43.24 | 43.2 | 3.606 | 3.63 | 2,906 USD (11.18%) | 11.2% |
| QQQ | +62,558.64 | 62,335 | 33 (12/21) | 33 | 36.36 | 36.4 | 5.320 | 5.27 | 4,806 USD (18.48%) | 18.5% |
| SMH | +63,930.16 | 63,962 | 46 (18/28) | 46 | 39.13 | 39.1 | 3.748 | 3.75 | 6,971 USD (26.81%) | 26.8% |
| IWM | +23,755.78 | 23,752 | 45 (12/33) | 45 | 26.67 | 26.7 | 2.184 | 2.18 | 5,821 USD (22.39%) | 22.4% |

Trade counts match exactly, net profit within 0.4%, profit factor within 1%, win rate within 0.1
point, drawdown within 0.1 point. First trades: SPY May 5 2008, QQQ Jan 3 2008, SMH May 15 2008,
IWM May 30 2008, the same dates as the full script's first Core trades.

TradingView's Core-only net profit also equals the "Core Trend Entry" line of the full script's
report to within 3 USD (SPY 33,592.30, QQQ 62,555.66, SMH 63,927.49, IWM 23,753.13), so removing
the overlay did not change a single Core trade.

## What the overlay was worth (TradingView, 2008-2026)

| Symbol | Full script net profit | Core only | Given up | Share |
|---|---|---|---|---|
| SPY | +34,595.77 | +33,595.16 | 1,001 USD | 2.9% |
| QQQ | +63,231.68 | +62,558.64 | 673 USD | 1.1% |
| SMH | +65,183.13 | +63,930.16 | 1,253 USD | 1.9% |
| IWM | +23,955.10 | +23,755.78 | 199 USD | 0.8% |

Python, FULL window, overlay on vs off: Sharpe 0.54/0.54 (SPY), 0.64/0.64 (QQQ), 0.52/0.51 (SMH),
0.29/0.29 (IWM); marked-to-market max drawdown 24.9/24.5, 35.6/35.4, 47.7/47.3, 39.5/39.2 percent
of capital. The overlay's risk and return were both too small to move either number. The win rate
falls from about 60% to 27-43% because the overlay's many small winners are gone; profit factor
rises on every symbol.

## Assessment

The Core alone reproduces the full script's risk and return to within 3% of profit with 37 to 46
trades instead of 231 to 258, one order type instead of five, and about 240 lines of Pine instead
of 745. The Core-only script is the one to ship. The full script stays in the repository as the
research reference for the overlay.

Open items are unchanged by this: the marked-to-market drawdown (24% to 47% of capital) and IWM's
Sharpe of 0.29 are Core properties, so the gate failures in `../README.md` now have exactly one place
to be addressed: the Core entry and exit rules.
