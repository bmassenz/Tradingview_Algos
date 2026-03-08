# Multi-Timeframe Confluence Trading Strategy

A complete trading system combining TradingView Pine Script indicators with a Python backtesting and optimization framework. The strategy uses multi-timeframe confluence — aligning daily trend, 4-hour momentum, and chart-timeframe entry signals — to generate high-probability trade setups.

## Architecture

```
                    ┌─────────────────────────┐
                    │   Daily Timeframe       │
                    │   EMA 50/200 + Super-   │
                    │   trend + ADX Regime    │
                    └──────────┬──────────────┘
                               │ Trend Direction
                    ┌──────────▼──────────────┐
                    │   4-Hour Timeframe      │
                    │   RSI + MACD Crossover  │
                    │   Momentum Confirmation │
                    └──────────┬──────────────┘
                               │ Setup Signal
                    ┌──────────▼──────────────┐
                    │   Entry Timeframe       │
                    │   Stochastic + Volume   │
                    │   Entry Trigger         │
                    └──────────┬──────────────┘
                               │
                    ┌──────────▼──────────────┐
                    │   Risk Management       │
                    │   ATR Stops / Trailing  │
                    │   Position Sizing       │
                    └─────────────────────────┘
```

## Components

### Pine Script (TradingView)

| File | Description |
|------|-------------|
| `main_strategy.pine` | Core strategy with entry/exit logic, risk management, and on-chart dashboard |
| `alert_conditions.pine` | Alert indicator with 8 configurable alert types (entries, exits, regime changes, volatility) |
| `dashboard_indicator.pine` | Live dashboard overlay showing regime, signals, position size, and session status |
| `mtf_signals_lib.pine` | Reusable library exporting modular signal functions (`getTrend`, `getMomentum`, etc.) |

### Python (Backtesting & Optimization)

| File | Description |
|------|-------------|
| `strategy.py` | Python implementation of the MTF strategy, faithful to the Pine Script logic |
| `backtest_engine.py` | Vectorized backtesting engine with realistic commission, slippage, and position management |
| `optimizer.py` | Multi-stage optimization: grid search, Bayesian refinement, walk-forward validation, robustness analysis |

## Key Parameters

The strategy has 8 core free parameters:

| Parameter | Default | Range | Layer |
|-----------|---------|-------|-------|
| EMA Fast Length | 50 | 5–200 | Trend |
| EMA Slow Length | 200 | 50–500 | Trend |
| Supertrend Multiplier | 3.0 | 1.0–6.0 | Trend |
| RSI / Stoch Length | 14 | 5–30 | Setup |
| ADX Trend Threshold | 25 | 15–40 | Setup |
| ADX Range Threshold | 20 | 10–30 | Setup |
| ATR Multiplier (Stop) | 2.0 | — | Risk |
| Risk per Trade | 1% | — | Risk |

## Risk Management

- **ATR-based stops and take-profits** with configurable multipliers
- **Trailing stops** that lock in profits as price moves favorably
- **Max 3 concurrent positions** (pyramiding)
- **Drawdown-based size reduction** — position size cuts 50% after 5% equity drawdown
- **Session filtering** to avoid low-liquidity periods
- **Regime detection** via ADX to adapt behavior in trending vs ranging markets

## Getting Started

### TradingView

1. Open [TradingView](https://www.tradingview.com/) Pine Script Editor
2. Copy the contents of `main_strategy.pine` and add to your chart
3. Optionally add `dashboard_indicator.pine` and `alert_conditions.pine` as separate indicators
4. Adjust inputs to match your instrument and timeframe

### Python Backtesting

```bash
pip install -r requirements.txt
```

```python
from strategy import MTFStrategySignals, StrategyParams, run_backtest

# Run with default parameters
results = run_backtest(
    symbol="SPY",
    start_date="2020-01-01",
    end_date="2024-01-01"
)
```

### Optimization

```python
from optimizer import StrategyOptimizer

optimizer = StrategyOptimizer(
    symbol="SPY",
    start_date="2018-01-01",
    end_date="2024-01-01"
)
results = optimizer.run_full_optimization()
```

## License

Pine Script files are subject to the [Mozilla Public License 2.0](https://mozilla.org/MPL/2.0/).
