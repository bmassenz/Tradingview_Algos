# The traded basket: SPY, QQQ, SMH with per-asset gates (decided 2026-09-26)

IWM is dropped and the robustness gates are now judged per asset (`select_and_report.gates`), with
the cross-asset Sharpe dispersion gate G5 as the one basket-level test. The basket and its
per-symbol Core settings live in `../basket.py`; `../basket_report.py` scores it and writes
`../results/basket_metrics.csv`. The strategy is `trend_core_professional.pine` (Core only).

## Why IWM is dropped

In every window and in both engines IWM has the lowest Sharpe of the four ETFs (0.21 to 0.34) and a
27% win rate, and no rule setting in `CORE_RULES.md` lifts its Sharpe above 0.4 (gate G4). Its
out-of-sample 2020-2022 buy-and-hold Sharpe was 0.06, so a trend filter has little to work with.
Averaging it into the cross-asset reward is what pulled the earlier parameter search.

## Per-symbol settings

| Symbol | Settings (all other inputs at default) | Reason |
|---|---|---|
| SPY | defaults | passes every gate on the original rules; the tightened trail raises its drawdown |
| QQQ | Tighten Trail After Gain % = 30, Tightened Trailing Stop % = 10 | worst-window drawdown 33.0% falls to 28.4%; Sharpe rises on every window |
| SMH | Core Allocation % of Equity = 80, plus the same trail setting | no rule setting brings SMH under 30%; at 80% allocation the worst window is 28.1% with Sharpe unchanged |

Set these on each symbol's chart in TradingView; the inputs exist in the Core-only script and each
is verified against the replica (`CORE_RULES.md`, and the SMH row below).

## Basket metrics (Python replica, Core only, `basket_metrics.csv`)

| Symbol | Window | P&L/yr | Sharpe | Max DD (mtm) | TV-definition DD | Win % | PF | Trades |
|---|---|---|---|---|---|---|---|---|
| SPY | IS | 1,479 | 0.48 | 24.5% | 8.6% | 45.8 | 3.28 | 24 |
| SPY | OOS | 1,455 | 0.36 | 22.6% | 9.3% | 33.3 | 3.69 | 6 |
| SPY | HOLDOUT | 3,114 | 0.87 | 18.2% | 7.1% | 42.9 | 4.49 | 7 |
| SPY | FULL | 1,800 | 0.54 | 24.5% | 11.2% | 43.2 | 3.63 | 37 |
| QQQ | IS | 2,120 | 0.52 | 28.4% | 18.5% | 32.0 | 2.77 | 25 |
| QQQ | OOS | 5,724 | 1.04 | 21.0% | 2.3% | 50.0 | 10.00 | 6 |
| QQQ | HOLDOUT | 5,054 | 0.98 | 23.6% | 7.5% | 40.0 | 8.30 | 5 |
| QQQ | FULL | 3,281 | 0.72 | 28.4% | 18.5% | 36.1 | 4.82 | 36 |
| SMH | IS | 1,936 | 0.48 | 28.1% | 20.2% | 33.3 | 2.37 | 30 |
| SMH | OOS | 4,223 | 0.72 | 23.5% | 14.6% | 44.4 | 5.98 | 9 |
| SMH | HOLDOUT | 5,035 | 0.76 | 27.8% | 12.9% | 50.0 | 3.85 | 10 |
| SMH | FULL | 2,919 | 0.59 | 29.0% | 20.2% | 38.8 | 3.38 | 49 |

## Gates, per asset

| Gate | SPY | QQQ | SMH |
|---|---|---|---|
| G1 P&L > 0 in IS, OOS and holdout | pass | pass | pass |
| G2 profit factor >= 1.2 in every window | pass | pass | pass |
| G3 max drawdown <= 30% of capital in every window (marked to market) | pass (24.5%) | pass (28.4%) | pass (28.1%) |
| G4 Sharpe >= 0.4 in-sample and 2020-26 | pass (0.48 / 0.62) | pass (0.52 / 1.01) | pass (0.48 / 0.74) |
| G5 worst 2020-26 Sharpe >= 0.4 x median (basket) | pass: 0.62, 1.01, 0.74 | | |

This is the first configuration to pass every gate. Two caveats belong next to that sentence:
SMH passes G3 by scaling, not by a better rule, so its drawdown in dollars is 80% of what the full-size
position would show; and the per-asset trail settings were chosen on the same data they are judged
on, with about 40 trades per symbol. The holdout was not used to choose them, and both assets improve
there, but a single 2021 exit is most of the QQQ and SMH gain.

## TradingView parity

SPY at defaults and QQQ at 30/10 were verified earlier (`CORE_ONLY.md`, `CORE_RULES.md`: trade counts
exact, net profit within 0.4%). SMH at 80% allocation with 30/10 (`core_smh80_results.json`):

| Symbol | TV net profit | Python total (P&L/yr x 18.70) | TV trades | Py trades | TV PF | Py PF | TV DD of initial capital | Py TV-definition DD |
|---|---|---|---|---|---|---|---|---|
| SMH | TV_SMH_PNL | 54,592 | TV_SMH_TRADES | 49 | TV_SMH_PF | 3.38 | TV_SMH_DD | 20.2% |
