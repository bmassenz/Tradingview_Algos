# TradingView Strategy Tester vs Python replica (run of 2026-09-25)

`trend_core_wae_professional.pine` with its default inputs, added to a daily chart in TradingView's
Strategy Tester (Premium account, standard backtest on the full loaded history), compared with the
Python replica's FULL window (2008-01-01 to 2026-09-25) from `../results/r3_chosen_metrics.csv`.

Python reports P&L per year over 4,713 bars (18.70 years at 252 bars/yr), so "Python total" below is
P&L/yr x 18.70 and carries about +/-170 USD of rounding. Python's drawdown is the largest peak-to-trough
drop of daily-close equity as a percent of the fixed 26,000 USD book; the USD figure is that percent x
26,000. TradingView's "Max drawdown" is quoted in USD, as a percent of the equity peak, and (from
Growth and decline) as a percent of initial capital.

## SPY (chart AMEX:SPY, resolved by TradingView to BATS:SPY; bars from Jan 29, 1993)

| Metric | TradingView | Python FULL | Difference |
|---|---|---|---|
| Net profit | +34,595.77 USD (+133.06%) | 1,854 USD/yr = 34,673 USD | -0.2% |
| Total closed trades | 253 (162 winners / 91 losers) | 253 | exact |
| Percent profitable | 64.03% | 64.0% | match |
| Profit factor | 3.425 | 3.44 | -0.4% |
| Max drawdown | 2,879.09 USD (7.81% of peak, 11.07% of initial capital) | 24.9% of capital = 6,474 USD | TV is 44% of Python |
| Overlay P&L (tiers 1/2/3) | 203.81 / 332.76 / 464.04 = 1,000.61 USD | 1,008 USD | -0.7% |
| Core P&L | 33,592.30 USD | n/a | |
| Gross profit / loss | 45,191.54 / 13,195.76 USD | n/a | |
| First trade | Core Trend Entry May 5, 2008, 183 shares at 141.07 | 2008 window start | |

## QQQ (chart NASDAQ:QQQ, resolved to BATS:QQQ; bars from Mar 10, 1999)

| Metric | TradingView | Python FULL | Difference |
|---|---|---|---|
| Net profit | +63,231.68 USD (+243.20%) | 3,361 USD/yr = 62,857 USD | +0.6% |
| Total closed trades | 258 (155 / 103) | 258 | exact |
| Percent profitable | 60.08% | 58.9% | +1.2 pt (3 trades) |
| Profit factor | 4.911 | 4.85 | +1.3% |
| Max drawdown | 4,846.04 USD (15.11% of peak, 18.64% of initial capital) | 35.6% of capital = 9,256 USD | TV is 52% of Python |
| Overlay P&L (tiers 1/2/3) | 154.42 / 132.64 / 385.99 = 673.05 USD | 539 USD | +134 USD (+25%) |
| Core P&L | 62,555.66 USD | n/a | |
| Gross profit / loss | 74,110.48 / 15,089.60 USD | n/a | |
| First trade | Core Trend Entry Jan 3, 2008, 515 shares at 50.42 | 2008 window start | |

## SMH (chart NASDAQ:SMH, resolved to BATS:SMH; bars from May 5, 2000)

| Metric | TradingView | Python FULL | Difference |
|---|---|---|---|
| Net profit | +65,183.13 USD (+250.70%) | 3,487 USD/yr = 65,214 USD | -0.05% |
| Total closed trades | 232 (156 / 76) | 232 | exact |
| Percent profitable | 67.24% | 67.2% | match |
| Profit factor | 3.695 | 3.70 | match |
| Max drawdown | 7,039.10 USD (25.55% of peak, 27.07% of initial capital) | 47.7% of capital = 12,402 USD | TV is 57% of Python |
| Overlay P&L (tiers 1/2/3) | 325.37 / 357.74 / 569.86 = 1,252.97 USD | 1,248 USD | +0.4% |
| Core P&L | 63,927.49 USD | n/a | |
| Gross profit / loss | 87,436.46 / 23,666.17 USD | n/a | |
| First trade | Core Trend Entry May 15, 2008, 1.6K shares at 16.29 | 2008 window start | |

## IWM (chart AMEX:IWM, resolved to BATS:IWM; bars from May 26, 2000)

| Metric | TradingView | Python FULL | Difference |
|---|---|---|---|
| Net profit | +23,955.10 USD (+92.14%) | 1,281 USD/yr = 23,957 USD | match |
| Total closed trades | 231 (114 / 117) | 231 | exact |
| Percent profitable | 49.35% | 49.4% | match |
| Profit factor | 2.118 | 2.12 | match |
| Max drawdown | 5,909.02 USD (12.99% of peak, 22.73% of initial capital) | 39.5% of capital = 10,270 USD | TV is 58% of Python |
| Overlay P&L (tiers 1/2/3) | 48.27 / 121.32 / 29.73 = 199.32 USD | 198 USD | match |
| Core P&L | 23,753.13 USD | n/a | |
| Gross profit / loss | 44,087.85 / 20,818.95 USD | n/a | |
| First trade | Core Trend Entry May 30, 2008, 349 shares at 74.51 | 2008 window start | |

## Assessment

- **Trades and P&L agree.** Trade counts match exactly on all four ETFs. Net profit is within 0.6%,
  profit factor within 1.3%, and win rate within 1.2 points. Three of four overlay P&L figures are within
  1%; QQQ's overlay differs by 134 USD (three more winning trades in TradingView), which is small next
  to the 63k USD total. The Pine script and the Python replica are executing the same strategy on the
  same data.
- **Drawdown does not agree, and the two numbers are not the same measure.** TradingView's max drawdown
  is 44% to 58% of Python's on every symbol, even after converting both to USD. Python takes the
  largest drop of daily-close equity (open positions marked to market) as a share of the fixed 26k
  book; TradingView's Overview figure is smaller on every symbol, so it is not the same equity series.
  The trades match, so this is a metric-definition difference, not a signal difference. Until Python's
  drawdown is recomputed the way TradingView's report computes it (`metrics.py` already has a
  `tv_max_dd` field that is not exported), the drawdown gate G3 in `../README.md` should be read as a
  Python-only number.
- Sharpe and Sortino were not compared; the tester's Overview does not show them.
- Both engines start trading in 2008 (the "Trade From" default), and both data sets end on
  2026-09-25. TradingView loaded SPY from 1993 and the other three from their 1999/2000 inception,
  so the weekly WAE filter is fully warm by 2008. Python's data starts in 2000, which is also enough.
- TradingView resolved the AMEX/NASDAQ tickers to its BATS feed for this account; the chart header
  still labels them AMEX/NASDAQ. Python used consolidated daily bars. The exact trade-count match
  shows the daily OHLC is the same for this purpose.

## Run notes

- Screenshots: `tester_<SYMBOL>.png` (Key stats, Performance, Breakdown by signal),
  `tester_<SYMBOL>_trades_analysis.png` (trade distribution) and `tester_<SYMBOL>_list_of_trades.png`
  (oldest trades first).
- The run needed two fixes to the runner, both in `bridge.js` / `run_tester.js`: the container proxy
  rejects the Pine compile fetch because the script id in the URL path contains a `;`, and the
  tester only lists strategies that compiled, so the report would otherwise show whichever other
  strategy the layout holds. The runner now works in a layout it creates itself; the layouts made
  on 2026-09-25 are named `tv_verify Trend-Core WAE Professional` and `tv_verify runner check 2026-09-25`.
- The first attempts ran inside the account's last-used layout ("Trend-Core Intraday Four ETF
  2026-09-25 HOLD"). That layout showed a "Trend-Core WAE Equity Basket v6" strategy at the start of
  the session and no longer does; the automation never clicked a Remove control on it, but the layout
  was autosaving while the runner worked in it, and the account was also in use shortly before the
  session. The saved script "Trend-Core WAE Equity Basket v6" still exists in the account, so it can
  be re-added, but its per-layout input settings could not be recovered from here.

## Follow-up: the drawdown difference is reconciled

The gap is a definition difference, and the Python replica now reproduces TradingView's number.
TradingView's "Max drawdown" takes its peak from closed-trade equity only, takes its trough from
closed-trade equity plus any open loss at the bar's low, and never counts open profit. The Python
figure marks every open position to market at each close, so profit that is given back before a
trade closes counts as drawdown there. Both are correct for what they measure; the Python figure is
the larger and more conservative one, and it is what the G3 gate in `../README.md` uses.

Recomputing the Python drawdown with TradingView's definition (`metrics.py`, `tv_max_dd`):

| Symbol | TradingView | Python, TradingView definition | Python, marked to market |
|---|---|---|---|
| SPY | 2,879 USD (11.07% of capital) | 2,886 USD (11.1%) | 6,487 USD (24.9%) |
| QQQ | 4,846 USD (18.64%) | 4,862 USD (18.7%) | 9,267 USD (35.6%) |
| SMH | 7,039 USD (27.07%) | 7,046 USD (27.1%) | 12,395 USD (47.7%) |
| IWM | 5,909 USD (22.73%) | 5,902 USD (22.7%) | 10,270 USD (39.5%) |

With trade counts exact, net profit within 0.6%, and drawdown within 0.3% under a common
definition, the Pine script and the Python replica are executing the same strategy on the same data.
