# Core rule experiments: EMA exit band and tightened trailing stop (2026-09-26)

Two candidate changes to the Core rules, tested on the Core-only strategy (`trend_core_professional.pine`,
overlay removed) with the Pine defaults, in the Python replica over every window and, for the winner,
in TradingView's Strategy Tester. Both rules are in `engine.py` and in the Pine script as inputs that
default to off; the defaults reproduce every previously committed number exactly. Sweep: `core_rules.py`,
results in `../results/core_rules.csv`.

- **EMA exit band.** Enter only when the close is `band`% above the trend EMA, exit only when it is
  `band`% below it. Bands tested: 0.5, 1, 1.5, 2, 3, 4, 5%.
- **Tightened trailing stop.** Once the highest high since entry is `trigger`% above the entry price,
  the trailing stop switches from 15.25% to `tight`%. Triggers 10, 20, 30, 50%; tight stops 5, 7.5, 10%.

## Result 1: the exit band is rejected

Every band setting raised the marked-to-market drawdown and lowered or held Sharpe, on all four ETFs
(FULL window, mean over SPY/QQQ/SMH/IWM; baseline first):

| Band | Mean Sharpe | Mean max DD | Worst max DD | Total P&L/yr | Trades |
|---|---|---|---|---|---|
| 0 (original) | 0.50 | 36.6% | 47.3% | 9,823 | 161 |
| 0.5% | 0.51 | 39.9% | 50.4% | 10,574 | 128 |
| 1% | 0.47 | 41.5% | 48.4% | 9,786 | 118 |
| 2% | 0.46 | 42.6% | 48.5% | 9,697 | 94 |
| 3% | 0.48 | 42.8% | 48.1% | 10,229 | 77 |
| 5% | 0.50 | 40.8% | 48.0% | 10,361 | 55 |

A band delays the EMA exit, so the trailing stop does more of the exiting, later and lower. The
whipsaw clusters it was meant to cut (2010, 2015-16, 2022) are already handled by the 12-bar cooldown.

## Result 2: the tightened trail helps QQQ and SMH, costs SPY

Best composite setting: trigger 30%, tightened stop 10%. FULL window, Python:

| Symbol | P&L/yr original | P&L/yr 30/10 | Sharpe orig | Sharpe 30/10 | Max DD orig | Max DD 30/10 | TV-definition DD orig | 30/10 |
|---|---|---|---|---|---|---|---|---|
| SPY | 1,800 | 1,628 | 0.54 | 0.50 | 24.5% | 28.2% | 11.2% | 14.6% |
| QQQ | 3,333 | 3,281 | 0.64 | 0.72 | 35.4% | 28.4% | 18.5% | 18.5% |
| SMH | 3,420 | 3,653 | 0.51 | 0.59 | 47.3% | 36.3% | 26.8% | 25.3% |
| IWM | 1,270 | 1,133 | 0.29 | 0.27 | 39.2% | 37.4% | 22.4% | 24.9% |

Mean drawdown falls from 36.6% to 32.6% of capital and the worst asset from 47.3% to 37.4%, at a
1.3% cost in total profit. But the gain is not uniform: SPY's drawdown rises 4 points and its Sharpe
falls, IWM gets slightly worse, and the improvement comes from QQQ and SMH, whose 2021 peaks are now
exited with a 10% trail instead of 15.25%. Out-of-sample, SPY's P&L/yr drops 25% (1,455 to 1,086) and
IWM's halves (1,263 to 669), while QQQ and SMH improve; the holdout is neutral to positive on all four.
No setting brings every asset under the 30% gate: SMH and IWM stay above it.

With about 40 trades per symbol, a change that moves the 2021 exit on two names is a handful of trades;
the per-window swings above are the size of that noise.

## TradingView parity for the 30/10 setting

`trend_core_professional.pine` with "Tighten Trail After Gain %" = 30 and "Tightened Trailing Stop %"
= 10, Strategy Tester, daily charts, full loaded history (`core_t30_results.json`, `core_t30_<SYMBOL>.png`):

| Symbol | TV net profit | Python total (P&L/yr x 18.70) | TV trades | Py trades | TV PF | Py PF | TV DD (of initial capital) | Py TV-definition DD |
|---|---|---|---|---|---|---|---|---|
| SPY | +30,380.45 | 30,447 | 39 | 39 | 3.145 | 3.16 | 14.62% | 14.6% |
| QQQ | +61,576.62 | 61,361 | 36 | 36 | 4.869 | 4.82 | 18.48% | 18.5% |
| SMH | +68,273.57 | 68,315 | 49 | 49 | 3.366 | 3.37 | 25.22% | 25.3% |
| IWM | +21,179.85 | 21,189 | 50 | 50 | 1.879 | 1.88 | 24.94% | 24.9% |

Trade counts exact, net profit within 0.4%, drawdown within 0.1 point. With both inputs at their
defaults the script reproduces the committed Core-only run (`CORE_ONLY.md`) to the cent on SPY and QQQ
(re-checked in the same session). The Pine implementation of both rules matches the replica.

## Recommendation

Keep both inputs off in the shipped defaults. The band is a clear loss. The tightened trail is a real
but asset-specific trade: it buys 7 to 11 points of drawdown on QQQ and SMH with a 4-point cost on SPY
and a weaker out-of-sample SPY and IWM, and it does not clear the 30% gate. If the basket is later cut
to QQQ and SMH, or the gate is set per asset, 30/10 is the setting to revisit. Both rules stay
available as inputs so that decision can be made without new code.
