"""
Backtesting Engine for MTF Trading Strategy
Uses vectorized operations for speed with event-driven position management.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
from datetime import datetime, timedelta
import os
import warnings

warnings.filterwarnings('ignore', category=FutureWarning)


class DataFetcher:
    """Fetch and prepare OHLCV data from yfinance."""

    @staticmethod
    def fetch(symbol: str, period: str = '10y', interval: str = '1d') -> pd.DataFrame:
        """Fetch data with error handling and NaN cleanup."""
        ticker = yf.Ticker(symbol)
        try:
            df = ticker.history(period=period, interval=interval)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch data for {symbol}: {e}")

        if df is None or df.empty:
            raise ValueError(f"No data returned for {symbol} with period={period}, interval={interval}")

        # Drop any rows where OHLC are all NaN
        df = df.dropna(subset=['Open', 'High', 'Low', 'Close'], how='all')

        # Forward-fill small gaps (up to 3 consecutive NaNs)
        df = df.ffill(limit=3)

        # Drop any remaining NaN rows
        df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])

        # Ensure volume is filled
        if 'Volume' in df.columns:
            df['Volume'] = df['Volume'].fillna(0).astype(float)

        # Ensure index is DatetimeIndex and timezone-naive for consistency
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        df.index.name = 'Date'
        return df

    @staticmethod
    def fetch_multi_timeframe(symbol: str, years: int = 10) -> Dict[str, pd.DataFrame]:
        """Fetch daily data and resample to weekly for HTF relationship."""
        daily = DataFetcher.fetch(symbol, period=f'{years}y', interval='1d')

        # Resample daily to weekly for higher-timeframe analysis
        weekly = daily.resample('W').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum',
        }).dropna()

        result = {'daily': daily, 'weekly': weekly}

        # Attempt to fetch intraday data (limited to ~60 days on yfinance)
        try:
            hourly = DataFetcher.fetch(symbol, period='60d', interval='1h')
            if not hourly.empty:
                result['1h'] = hourly
        except Exception:
            pass

        return result

    @staticmethod
    def validate_data(df: pd.DataFrame) -> pd.DataFrame:
        """Check for gaps, NaNs, timezone issues. Forward-fill small gaps."""
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # Detect large gaps (more than 5 business days)
        if len(df) > 1:
            deltas = pd.Series(df.index).diff().dropna()
            large_gaps = deltas[deltas > pd.Timedelta(days=7)]
            if len(large_gaps) > 0:
                print(f"Warning: {len(large_gaps)} gaps > 7 days detected in data.")

        # Forward-fill small gaps
        df = df.ffill(limit=3)

        # Check for remaining NaNs
        nan_counts = df[['Open', 'High', 'Low', 'Close']].isna().sum()
        if nan_counts.any():
            print(f"Warning: Remaining NaNs after cleanup: {nan_counts.to_dict()}")
            df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])

        # Validate OHLC consistency
        mask_invalid = (df['High'] < df['Low']) | (df['Open'] <= 0) | (df['Close'] <= 0)
        if mask_invalid.any():
            print(f"Warning: {mask_invalid.sum()} bars with invalid OHLC removed.")
            df = df[~mask_invalid]

        return df


class BacktestEngine:
    """
    Main backtesting engine with realistic execution simulation.
    Handles commission (0.1%), slippage (2 pts), and position management.
    """

    def __init__(self, initial_capital: float = 100000.0, commission_pct: float = 0.001,
                 slippage_pts: float = 2.0):
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pts = slippage_pts

    def run(self, signals: pd.DataFrame, prices: pd.DataFrame) -> dict:
        """
        Execute backtest given signals and price data.

        signals DataFrame must have columns: signal (1/-1/0), stop_loss, take_profit, position_size
        prices DataFrame must have: Open, High, Low, Close, Volume

        Returns dict with:
        - equity_curve: pd.Series
        - trades: pd.DataFrame
        - daily_returns: pd.Series
        - monthly_returns: pd.DataFrame
        - drawdown_series: pd.Series
        - metrics: dict of all performance metrics
        """
        # Align signals and prices on the same index
        common_idx = signals.index.intersection(prices.index)
        signals = signals.loc[common_idx]
        prices = prices.loc[common_idx]

        capital = self.initial_capital
        equity_values = []
        equity_dates = []
        trades: List[dict] = []
        position: Optional[dict] = None

        for i in range(len(common_idx)):
            date = common_idx[i]
            bar_open = prices.iloc[i]['Open']
            bar_high = prices.iloc[i]['High']
            bar_low = prices.iloc[i]['Low']
            bar_close = prices.iloc[i]['Close']
            sig = signals.iloc[i]
            signal_val = sig.get('signal', 0)
            sl = sig.get('stop_loss', np.nan)
            tp = sig.get('take_profit', np.nan)
            pos_size = sig.get('position_size', 1.0)

            # --- Check existing position for SL/TP hits using intra-bar High/Low ---
            if position is not None:
                exit_reason = self._check_stops(position, bar_high, bar_low)

                if exit_reason is not None:
                    # Determine exit price based on reason
                    if exit_reason == 'stop_loss':
                        exit_price = position['stop_loss']
                    elif exit_reason == 'take_profit':
                        exit_price = position['take_profit']
                    else:
                        exit_price = bar_close

                    # Apply slippage on exit (adverse direction)
                    exit_price = self._apply_slippage(exit_price, -position['direction'])

                    # Calculate P&L
                    price_diff = (exit_price - position['entry_price']) * position['direction']
                    gross_pnl = price_diff * position['shares']
                    commission_exit = self._apply_commission(exit_price * position['shares'])
                    net_pnl = gross_pnl - commission_exit

                    capital += position['allocated_capital'] + net_pnl
                    pnl_pct = net_pnl / position['allocated_capital'] if position['allocated_capital'] != 0 else 0.0

                    trades.append({
                        'entry_date': position['entry_date'],
                        'exit_date': date,
                        'direction': 'LONG' if position['direction'] == 1 else 'SHORT',
                        'entry_price': position['entry_price'],
                        'exit_price': exit_price,
                        'shares': position['shares'],
                        'pnl': net_pnl,
                        'pnl_pct': pnl_pct,
                        'duration': (date - position['entry_date']).days,
                        'exit_reason': exit_reason,
                    })
                    position = None

                # If signal flips, close position at open
                elif signal_val != 0 and signal_val != position['direction']:
                    exit_price = self._apply_slippage(bar_open, -position['direction'])
                    price_diff = (exit_price - position['entry_price']) * position['direction']
                    gross_pnl = price_diff * position['shares']
                    commission_exit = self._apply_commission(exit_price * position['shares'])
                    net_pnl = gross_pnl - commission_exit

                    capital += position['allocated_capital'] + net_pnl
                    pnl_pct = net_pnl / position['allocated_capital'] if position['allocated_capital'] != 0 else 0.0

                    trades.append({
                        'entry_date': position['entry_date'],
                        'exit_date': date,
                        'direction': 'LONG' if position['direction'] == 1 else 'SHORT',
                        'entry_price': position['entry_price'],
                        'exit_price': exit_price,
                        'shares': position['shares'],
                        'pnl': net_pnl,
                        'pnl_pct': pnl_pct,
                        'duration': (date - position['entry_date']).days,
                        'exit_reason': 'signal_reversal',
                    })
                    position = None

            # --- Open new position if signal and no current position ---
            if position is None and signal_val != 0:
                direction = int(signal_val)
                entry_price = self._apply_slippage(bar_open, direction)
                alloc = capital * pos_size
                commission_entry = self._apply_commission(alloc)
                investable = alloc - commission_entry
                shares = investable / entry_price if entry_price > 0 else 0

                if shares > 0:
                    capital -= alloc
                    position = {
                        'entry_date': date,
                        'entry_price': entry_price,
                        'direction': direction,
                        'shares': shares,
                        'allocated_capital': alloc,
                        'stop_loss': sl if not np.isnan(sl) else None,
                        'take_profit': tp if not np.isnan(tp) else None,
                    }

            # --- Compute equity at end of bar ---
            if position is not None:
                unrealized = (bar_close - position['entry_price']) * position['direction'] * position['shares']
                equity = capital + position['allocated_capital'] + unrealized
            else:
                equity = capital

            equity_values.append(equity)
            equity_dates.append(date)

        # Close any open position at last bar's close
        if position is not None:
            last_close = prices.iloc[-1]['Close']
            exit_price = self._apply_slippage(last_close, -position['direction'])
            price_diff = (exit_price - position['entry_price']) * position['direction']
            gross_pnl = price_diff * position['shares']
            commission_exit = self._apply_commission(exit_price * position['shares'])
            net_pnl = gross_pnl - commission_exit
            capital += position['allocated_capital'] + net_pnl
            pnl_pct = net_pnl / position['allocated_capital'] if position['allocated_capital'] != 0 else 0.0

            trades.append({
                'entry_date': position['entry_date'],
                'exit_date': common_idx[-1],
                'direction': 'LONG' if position['direction'] == 1 else 'SHORT',
                'entry_price': position['entry_price'],
                'exit_price': exit_price,
                'shares': position['shares'],
                'pnl': net_pnl,
                'pnl_pct': pnl_pct,
                'duration': (common_idx[-1] - position['entry_date']).days,
                'exit_reason': 'end_of_data',
            })
            equity_values[-1] = capital
            position = None

        equity_curve = pd.Series(equity_values, index=equity_dates, name='Equity')
        trades_df = pd.DataFrame(trades) if trades else pd.DataFrame(
            columns=['entry_date', 'exit_date', 'direction', 'entry_price', 'exit_price',
                     'shares', 'pnl', 'pnl_pct', 'duration', 'exit_reason'])

        daily_returns = equity_curve.pct_change().fillna(0.0)
        monthly_returns = PerformanceCalculator.calculate_monthly_returns(equity_curve)
        drawdown_series = PerformanceCalculator.calculate_drawdown_series(equity_curve)

        # Buy & hold benchmark
        benchmark_curve = (prices['Close'] / prices['Close'].iloc[0]) * self.initial_capital
        benchmark_curve.name = 'Benchmark'

        metrics = PerformanceCalculator.calculate_all(equity_curve, trades_df,
                                                      benchmark_curve, risk_free_rate=0.04)

        return {
            'equity_curve': equity_curve,
            'benchmark_curve': benchmark_curve,
            'trades': trades_df,
            'daily_returns': daily_returns,
            'monthly_returns': monthly_returns,
            'drawdown_series': drawdown_series,
            'metrics': metrics,
        }

    def _apply_slippage(self, price: float, direction: int) -> float:
        """Apply slippage to execution price. Buys fill higher, sells fill lower."""
        return price + self.slippage_pts * direction

    def _apply_commission(self, trade_value: float) -> float:
        """Calculate commission cost."""
        return abs(trade_value) * self.commission_pct

    def _check_stops(self, position: dict, high: float, low: float) -> Optional[str]:
        """Check if SL/TP is hit using intra-bar High/Low. Returns exit reason or None."""
        direction = position['direction']
        sl = position.get('stop_loss')
        tp = position.get('take_profit')

        if direction == 1:  # LONG
            # Stop loss hit if low <= SL
            if sl is not None and low <= sl:
                return 'stop_loss'
            # Take profit hit if high >= TP
            if tp is not None and high >= tp:
                return 'take_profit'
        else:  # SHORT
            # Stop loss hit if high >= SL
            if sl is not None and high >= sl:
                return 'stop_loss'
            # Take profit hit if low <= TP
            if tp is not None and low <= tp:
                return 'take_profit'

        return None


class PerformanceCalculator:
    """Calculate all required performance metrics."""

    @staticmethod
    def calculate_all(equity_curve: pd.Series, trades: pd.DataFrame,
                      benchmark_curve: pd.Series, risk_free_rate: float = 0.04) -> dict:
        """
        Calculate ALL performance metrics.
        """
        daily_returns = equity_curve.pct_change().dropna()
        trading_days = len(daily_returns)

        if trading_days == 0:
            return {k: 0.0 for k in [
                'total_return', 'cagr', 'sharpe_ratio', 'sortino_ratio',
                'max_drawdown', 'calmar_ratio', 'win_rate', 'profit_factor',
                'recovery_factor', 'avg_trade_duration', 'best_trade', 'worst_trade',
                'benchmark_return', 'benchmark_cagr', 'alpha_annualized',
                'total_trades', 'avg_win', 'avg_loss', 'expectancy',
            ]}

        initial = equity_curve.iloc[0]
        final = equity_curve.iloc[-1]

        # Total return
        total_return = (final - initial) / initial

        # CAGR
        years = trading_days / 252.0
        cagr = (final / initial) ** (1.0 / years) - 1.0 if years > 0 and initial > 0 else 0.0

        # Daily risk-free rate
        rf_daily = (1.0 + risk_free_rate) ** (1.0 / 252.0) - 1.0

        # Sharpe ratio
        excess = daily_returns - rf_daily
        std_daily = daily_returns.std()
        sharpe_ratio = (excess.mean() / std_daily * np.sqrt(252)) if std_daily > 0 else 0.0

        # Sortino ratio
        downside = daily_returns[daily_returns < rf_daily] - rf_daily
        downside_std = np.sqrt((downside ** 2).mean()) if len(downside) > 0 else 0.0
        sortino_ratio = (excess.mean() / downside_std * np.sqrt(252)) if downside_std > 0 else 0.0

        # Max drawdown
        dd_series = PerformanceCalculator.calculate_drawdown_series(equity_curve)
        max_drawdown = dd_series.min()  # Most negative value

        # Calmar ratio
        calmar_ratio = cagr / abs(max_drawdown) if max_drawdown != 0 else 0.0

        # Trade-based metrics
        total_trades = len(trades)
        if total_trades > 0:
            winners = trades[trades['pnl'] > 0]
            losers = trades[trades['pnl'] <= 0]
            win_rate = len(winners) / total_trades

            gross_profits = winners['pnl'].sum() if len(winners) > 0 else 0.0
            gross_losses = abs(losers['pnl'].sum()) if len(losers) > 0 else 0.0
            profit_factor = gross_profits / gross_losses if gross_losses > 0 else float('inf')

            avg_win = winners['pnl'].mean() if len(winners) > 0 else 0.0
            avg_loss = losers['pnl'].mean() if len(losers) > 0 else 0.0
            expectancy = trades['pnl'].mean()

            best_trade = trades['pnl_pct'].max()
            worst_trade = trades['pnl_pct'].min()
            avg_trade_duration = trades['duration'].mean()

            # Recovery factor: net profit / max drawdown
            net_profit = final - initial
            recovery_factor = net_profit / abs(max_drawdown * initial) if max_drawdown != 0 else 0.0
        else:
            win_rate = 0.0
            profit_factor = 0.0
            avg_win = 0.0
            avg_loss = 0.0
            expectancy = 0.0
            best_trade = 0.0
            worst_trade = 0.0
            avg_trade_duration = 0.0
            recovery_factor = 0.0

        # Benchmark metrics
        bench_initial = benchmark_curve.iloc[0]
        bench_final = benchmark_curve.iloc[-1]
        benchmark_return = (bench_final - bench_initial) / bench_initial if bench_initial > 0 else 0.0
        benchmark_cagr = (bench_final / bench_initial) ** (1.0 / years) - 1.0 if years > 0 and bench_initial > 0 else 0.0
        alpha_annualized = cagr - benchmark_cagr

        return {
            'total_return': total_return,
            'cagr': cagr,
            'sharpe_ratio': sharpe_ratio,
            'sortino_ratio': sortino_ratio,
            'max_drawdown': max_drawdown,
            'calmar_ratio': calmar_ratio,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'recovery_factor': recovery_factor,
            'avg_trade_duration': avg_trade_duration,
            'best_trade': best_trade,
            'worst_trade': worst_trade,
            'benchmark_return': benchmark_return,
            'benchmark_cagr': benchmark_cagr,
            'alpha_annualized': alpha_annualized,
            'total_trades': total_trades,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'expectancy': expectancy,
        }

    @staticmethod
    def calculate_monthly_returns(equity_curve: pd.Series) -> pd.DataFrame:
        """Calculate year x month return matrix."""
        # Resample to month-end equity
        monthly_equity = equity_curve.resample('ME').last()
        monthly_ret = monthly_equity.pct_change().dropna()

        # Build year x month pivot
        df = pd.DataFrame({
            'Year': monthly_ret.index.year,
            'Month': monthly_ret.index.month,
            'Return': monthly_ret.values,
        })
        pivot = df.pivot_table(index='Year', columns='Month', values='Return', aggfunc='sum')
        pivot.columns = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                         'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][:len(pivot.columns)]

        # Add yearly total
        pivot['Year Total'] = pivot.sum(axis=1)
        return pivot

    @staticmethod
    def calculate_drawdown_series(equity_curve: pd.Series) -> pd.Series:
        """Calculate underwater equity (drawdown at each point as fraction)."""
        running_max = equity_curve.expanding().max()
        drawdown = (equity_curve - running_max) / running_max
        drawdown.name = 'Drawdown'
        return drawdown

    @staticmethod
    def monte_carlo_simulation(trades: pd.DataFrame, n_simulations: int = 1000,
                               n_periods: int = 252, initial_capital: float = 100000.0) -> pd.DataFrame:
        """
        Run Monte Carlo by resampling trades with replacement.
        Returns DataFrame of simulated equity curves (columns = simulation index).
        """
        if trades.empty:
            return pd.DataFrame()

        trade_returns = trades['pnl_pct'].values
        n_trades = len(trade_returns)

        simulations = np.zeros((n_periods + 1, n_simulations))
        simulations[0, :] = initial_capital

        for sim in range(n_simulations):
            # Resample trade returns with replacement
            sampled = np.random.choice(trade_returns, size=n_periods, replace=True)
            cumulative = np.cumprod(1.0 + sampled)
            simulations[1:, sim] = initial_capital * cumulative

        return pd.DataFrame(simulations, columns=[f'sim_{i}' for i in range(n_simulations)])


class ChartGenerator:
    """Generate all 6 required performance charts."""

    STYLE = 'seaborn-v0_8-darkgrid'

    def __init__(self, output_dir: str = './charts/'):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        try:
            plt.style.use(self.STYLE)
        except OSError:
            plt.style.use('ggplot')

    def generate_all(self, equity_curve, benchmark_curve, trades,
                     monthly_returns, drawdown_series, walk_forward_results,
                     param_sensitivity, metrics):
        """Generate all 6 charts."""
        self.chart1_equity_curve(equity_curve, benchmark_curve, drawdown_series)
        self.chart2_monthly_heatmap(monthly_returns)
        benchmark_dd = PerformanceCalculator.calculate_drawdown_series(benchmark_curve)
        self.chart3_drawdown_analysis(drawdown_series, benchmark_dd)
        self.chart4_trade_distribution(trades)
        self.chart5_walk_forward(walk_forward_results)
        self.chart6_sensitivity_heatmap(param_sensitivity)

    def chart1_equity_curve(self, equity: pd.Series, benchmark: pd.Series,
                            drawdown: pd.Series):
        """Strategy vs B&H equity curve with drawdown shading, log scale."""
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), height_ratios=[3, 1],
                                        sharex=True)

        # Upper panel: equity curves on log scale
        ax1.semilogy(equity.index, equity.values, label='Strategy', color='#2196F3',
                     linewidth=1.5)
        ax1.semilogy(benchmark.index, benchmark.values, label='Buy & Hold', color='#9E9E9E',
                     linewidth=1.0, alpha=0.8)
        ax1.fill_between(equity.index, equity.values, benchmark.values,
                         where=equity.values >= benchmark.values,
                         alpha=0.1, color='green', interpolate=True)
        ax1.fill_between(equity.index, equity.values, benchmark.values,
                         where=equity.values < benchmark.values,
                         alpha=0.1, color='red', interpolate=True)
        ax1.set_ylabel('Portfolio Value (log scale)', fontsize=12)
        ax1.set_title('Equity Curve: Strategy vs Buy & Hold', fontsize=14, fontweight='bold')
        ax1.legend(loc='upper left', fontsize=11)
        ax1.grid(True, alpha=0.3)

        # Annotate final values
        ax1.annotate(f'${equity.iloc[-1]:,.0f}',
                     xy=(equity.index[-1], equity.iloc[-1]),
                     fontsize=10, color='#2196F3', fontweight='bold',
                     xytext=(10, 0), textcoords='offset points')

        # Lower panel: drawdown
        ax2.fill_between(drawdown.index, drawdown.values, 0, color='#F44336', alpha=0.4)
        ax2.plot(drawdown.index, drawdown.values, color='#D32F2F', linewidth=0.8)
        ax2.set_ylabel('Drawdown', fontsize=12)
        ax2.set_xlabel('Date', fontsize=12)
        ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f'{y:.0%}'))
        ax2.set_title('Underwater Equity (Drawdown)', fontsize=12)
        ax2.grid(True, alpha=0.3)

        # Mark max drawdown point
        if len(drawdown) > 0:
            max_dd_idx = drawdown.idxmin()
            max_dd_val = drawdown.min()
            ax2.annotate(f'Max DD: {max_dd_val:.1%}',
                         xy=(max_dd_idx, max_dd_val),
                         fontsize=9, color='darkred', fontweight='bold',
                         xytext=(20, -15), textcoords='offset points',
                         arrowprops=dict(arrowstyle='->', color='darkred'))

        fig.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'chart1_equity_curve.png'),
                    dpi=150, bbox_inches='tight')
        plt.close(fig)

    def chart2_monthly_heatmap(self, monthly_returns: pd.DataFrame):
        """Year x Month heatmap with seaborn, green/red coloring."""
        fig, ax = plt.subplots(figsize=(14, 8))

        # Drop the Year Total column for the heatmap
        display_data = monthly_returns.drop(columns=['Year Total'], errors='ignore')

        # Custom red-green colormap centered at 0
        cmap = sns.diverging_palette(10, 130, as_cmap=True)

        sns.heatmap(display_data, annot=True, fmt='.1%', cmap=cmap, center=0,
                    linewidths=0.5, linecolor='white', ax=ax,
                    cbar_kws={'label': 'Monthly Return', 'format': '%.1%%'})

        ax.set_title('Monthly Returns Heatmap', fontsize=14, fontweight='bold')
        ax.set_ylabel('Year', fontsize=12)
        ax.set_xlabel('Month', fontsize=12)

        fig.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'chart2_monthly_heatmap.png'),
                    dpi=150, bbox_inches='tight')
        plt.close(fig)

    def chart3_drawdown_analysis(self, drawdown: pd.Series, benchmark_dd: pd.Series):
        """Underwater equity curve, mark top 5 worst drawdowns."""
        fig, ax = plt.subplots(figsize=(16, 8))

        ax.fill_between(drawdown.index, drawdown.values, 0,
                        color='#F44336', alpha=0.3, label='Strategy DD')
        ax.plot(drawdown.index, drawdown.values, color='#D32F2F', linewidth=0.8)

        ax.plot(benchmark_dd.index, benchmark_dd.values, color='#9E9E9E',
                linewidth=0.8, alpha=0.7, label='Benchmark DD')

        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f'{y:.0%}'))
        ax.set_title('Drawdown Analysis', fontsize=14, fontweight='bold')
        ax.set_ylabel('Drawdown', fontsize=12)
        ax.set_xlabel('Date', fontsize=12)
        ax.legend(fontsize=11)
        ax.grid(True, alpha=0.3)

        # Identify and annotate top 5 worst drawdown troughs
        if len(drawdown) > 0:
            dd_troughs = []
            in_dd = False
            trough_val = 0.0
            trough_idx = drawdown.index[0]

            for idx, val in drawdown.items():
                if val < 0:
                    if not in_dd:
                        in_dd = True
                        trough_val = val
                        trough_idx = idx
                    elif val < trough_val:
                        trough_val = val
                        trough_idx = idx
                else:
                    if in_dd:
                        dd_troughs.append((trough_idx, trough_val))
                        in_dd = False
                        trough_val = 0.0
            # Handle case where DD continues to end of series
            if in_dd:
                dd_troughs.append((trough_idx, trough_val))

            # Sort by severity (most negative first) and take top 5
            dd_troughs.sort(key=lambda x: x[1])
            for rank, (t_idx, t_val) in enumerate(dd_troughs[:5], 1):
                ax.annotate(f'#{rank}: {t_val:.1%}',
                            xy=(t_idx, t_val),
                            fontsize=8, color='darkred', fontweight='bold',
                            xytext=(10, -10 - rank * 8), textcoords='offset points',
                            arrowprops=dict(arrowstyle='->', color='darkred', lw=0.8))

        fig.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'chart3_drawdown_analysis.png'),
                    dpi=150, bbox_inches='tight')
        plt.close(fig)

    def chart4_trade_distribution(self, trades: pd.DataFrame):
        """Histogram of trade P&L with normal overlay, stats annotations."""
        fig, axes = plt.subplots(1, 2, figsize=(16, 8))

        if trades.empty:
            for ax in axes:
                ax.text(0.5, 0.5, 'No trades to display', transform=ax.transAxes,
                        ha='center', va='center', fontsize=14)
            fig.savefig(os.path.join(self.output_dir, 'chart4_trade_distribution.png'),
                        dpi=150, bbox_inches='tight')
            plt.close(fig)
            return

        # Left panel: P&L distribution in percentage
        pnl_pct = trades['pnl_pct'].values * 100  # Convert to percentage
        ax1 = axes[0]

        n_bins = min(50, max(10, len(pnl_pct) // 3))
        counts, bins, patches = ax1.hist(pnl_pct, bins=n_bins, edgecolor='white',
                                          alpha=0.7, density=True)

        # Color bars: green for positive, red for negative
        for patch, left_edge in zip(patches, bins[:-1]):
            if left_edge >= 0:
                patch.set_facecolor('#4CAF50')
            else:
                patch.set_facecolor('#F44336')

        # Normal distribution overlay
        mu, sigma = np.mean(pnl_pct), np.std(pnl_pct)
        if sigma > 0:
            x = np.linspace(mu - 4 * sigma, mu + 4 * sigma, 200)
            normal_pdf = (1.0 / (sigma * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x - mu) / sigma) ** 2)
            ax1.plot(x, normal_pdf, 'k--', linewidth=1.5, label='Normal fit')

        ax1.axvline(x=0, color='black', linewidth=1, linestyle='-', alpha=0.5)
        ax1.axvline(x=mu, color='blue', linewidth=1, linestyle='--', alpha=0.7, label=f'Mean: {mu:.2f}%')
        ax1.set_title('Trade Return Distribution', fontsize=13, fontweight='bold')
        ax1.set_xlabel('Trade Return (%)', fontsize=11)
        ax1.set_ylabel('Density', fontsize=11)
        ax1.legend(fontsize=10)

        # Stats text box
        win_rate = (trades['pnl'] > 0).mean() * 100
        stats_text = (f'Trades: {len(trades)}\n'
                      f'Win Rate: {win_rate:.1f}%\n'
                      f'Mean: {mu:.2f}%\n'
                      f'Std: {sigma:.2f}%\n'
                      f'Skew: {pd.Series(pnl_pct).skew():.2f}\n'
                      f'Kurt: {pd.Series(pnl_pct).kurtosis():.2f}')
        ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes, fontsize=9,
                 verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

        # Right panel: cumulative P&L
        ax2 = axes[1]
        cum_pnl = trades['pnl'].cumsum()
        colors = ['#4CAF50' if p > 0 else '#F44336' for p in trades['pnl'].values]
        ax2.bar(range(len(cum_pnl)), cum_pnl.values, color='#2196F3', alpha=0.7, width=1.0)
        ax2.plot(range(len(cum_pnl)), cum_pnl.values, color='#1565C0', linewidth=1.5)
        ax2.axhline(y=0, color='black', linewidth=0.8, linestyle='-')
        ax2.set_title('Cumulative P&L by Trade', fontsize=13, fontweight='bold')
        ax2.set_xlabel('Trade Number', fontsize=11)
        ax2.set_ylabel('Cumulative P&L ($)', fontsize=11)
        ax2.grid(True, alpha=0.3)

        fig.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'chart4_trade_distribution.png'),
                    dpi=150, bbox_inches='tight')
        plt.close(fig)

    def chart5_walk_forward(self, wf_results: dict):
        """Rolling Sharpe, IS vs OOS windows, regime overlay."""
        fig, axes = plt.subplots(3, 1, figsize=(16, 12), sharex=True)

        if wf_results is None or not wf_results:
            for ax in axes:
                ax.text(0.5, 0.5, 'No walk-forward data available', transform=ax.transAxes,
                        ha='center', va='center', fontsize=14)
            fig.savefig(os.path.join(self.output_dir, 'chart5_walk_forward.png'),
                        dpi=150, bbox_inches='tight')
            plt.close(fig)
            return

        # Panel 1: Rolling Sharpe ratio
        ax1 = axes[0]
        rolling_sharpe = wf_results.get('rolling_sharpe', pd.Series(dtype=float))
        if not rolling_sharpe.empty:
            ax1.plot(rolling_sharpe.index, rolling_sharpe.values, color='#2196F3', linewidth=1.2)
            ax1.axhline(y=0, color='black', linewidth=0.8, linestyle='-')
            ax1.axhline(y=1.0, color='green', linewidth=0.8, linestyle='--', alpha=0.5, label='Sharpe=1')
            ax1.axhline(y=-1.0, color='red', linewidth=0.8, linestyle='--', alpha=0.5, label='Sharpe=-1')
            ax1.fill_between(rolling_sharpe.index, rolling_sharpe.values, 0,
                             where=rolling_sharpe.values >= 0, alpha=0.2, color='green')
            ax1.fill_between(rolling_sharpe.index, rolling_sharpe.values, 0,
                             where=rolling_sharpe.values < 0, alpha=0.2, color='red')
        ax1.set_title('Rolling 63-Day Sharpe Ratio', fontsize=13, fontweight='bold')
        ax1.set_ylabel('Sharpe Ratio', fontsize=11)
        ax1.legend(fontsize=9)
        ax1.grid(True, alpha=0.3)

        # Panel 2: IS vs OOS Sharpe comparison
        ax2 = axes[1]
        is_sharpe = wf_results.get('is_sharpe', [])
        oos_sharpe = wf_results.get('oos_sharpe', [])
        window_labels = wf_results.get('window_labels', [])

        if is_sharpe and oos_sharpe:
            x = np.arange(len(is_sharpe))
            width = 0.35
            ax2.bar(x - width / 2, is_sharpe, width, label='In-Sample', color='#2196F3', alpha=0.8)
            ax2.bar(x + width / 2, oos_sharpe, width, label='Out-of-Sample', color='#FF9800', alpha=0.8)
            ax2.set_xticks(x)
            if window_labels:
                ax2.set_xticklabels(window_labels, rotation=45, ha='right', fontsize=8)
            ax2.axhline(y=0, color='black', linewidth=0.8)
        ax2.set_title('In-Sample vs Out-of-Sample Sharpe', fontsize=13, fontweight='bold')
        ax2.set_ylabel('Sharpe Ratio', fontsize=11)
        ax2.legend(fontsize=10)
        ax2.grid(True, alpha=0.3)

        # Panel 3: Market regime overlay (volatility regime)
        ax3 = axes[2]
        regime = wf_results.get('regime', pd.Series(dtype=float))
        if not regime.empty:
            ax3.fill_between(regime.index, regime.values, alpha=0.4, color='#9C27B0',
                             label='Realized Vol (21d)')
            ax3.plot(regime.index, regime.values, color='#7B1FA2', linewidth=0.8)
            if len(regime) > 0:
                median_vol = regime.median()
                ax3.axhline(y=median_vol, color='orange', linewidth=1, linestyle='--',
                            label=f'Median Vol: {median_vol:.1%}')
        ax3.set_title('Market Regime (Realized Volatility)', fontsize=13, fontweight='bold')
        ax3.set_ylabel('Annualized Vol', fontsize=11)
        ax3.set_xlabel('Date', fontsize=11)
        ax3.legend(fontsize=10)
        ax3.grid(True, alpha=0.3)

        fig.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'chart5_walk_forward.png'),
                    dpi=150, bbox_inches='tight')
        plt.close(fig)

    def chart6_sensitivity_heatmap(self, sensitivity_data: dict):
        """2D heatmap of Sharpe vs 2 most sensitive params."""
        fig, ax = plt.subplots(figsize=(12, 8))

        if sensitivity_data is None or not sensitivity_data:
            ax.text(0.5, 0.5, 'No sensitivity data available', transform=ax.transAxes,
                    ha='center', va='center', fontsize=14)
            fig.savefig(os.path.join(self.output_dir, 'chart6_sensitivity_heatmap.png'),
                        dpi=150, bbox_inches='tight')
            plt.close(fig)
            return

        # Expected keys: 'param1_name', 'param2_name', 'param1_values', 'param2_values', 'sharpe_matrix'
        param1_name = sensitivity_data.get('param1_name', 'Param 1')
        param2_name = sensitivity_data.get('param2_name', 'Param 2')
        param1_vals = sensitivity_data.get('param1_values', [])
        param2_vals = sensitivity_data.get('param2_values', [])
        sharpe_matrix = sensitivity_data.get('sharpe_matrix', np.array([[]]))

        if isinstance(sharpe_matrix, np.ndarray) and sharpe_matrix.size > 0:
            df_heatmap = pd.DataFrame(sharpe_matrix,
                                      index=[f'{v:.2g}' for v in param1_vals],
                                      columns=[f'{v:.2g}' for v in param2_vals])

            cmap = sns.diverging_palette(10, 130, as_cmap=True)
            sns.heatmap(df_heatmap, annot=True, fmt='.2f', cmap=cmap, center=0,
                        linewidths=0.5, linecolor='white', ax=ax,
                        cbar_kws={'label': 'Sharpe Ratio'})

            # Mark the best cell
            best_idx = np.unravel_index(np.argmax(sharpe_matrix), sharpe_matrix.shape)
            ax.add_patch(plt.Rectangle((best_idx[1], best_idx[0]), 1, 1,
                                        fill=False, edgecolor='gold', linewidth=3))

        ax.set_title(f'Parameter Sensitivity: Sharpe Ratio\n{param1_name} vs {param2_name}',
                     fontsize=14, fontweight='bold')
        ax.set_ylabel(param1_name, fontsize=12)
        ax.set_xlabel(param2_name, fontsize=12)

        fig.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'chart6_sensitivity_heatmap.png'),
                    dpi=150, bbox_inches='tight')
        plt.close(fig)


class WalkForwardAnalyzer:
    """Walk-forward analysis with rolling windows."""

    def __init__(self, is_window: int = 252, oos_window: int = 63):
        self.is_window = is_window
        self.oos_window = oos_window

    def analyze(self, daily_returns: pd.Series, risk_free_rate: float = 0.04) -> dict:
        """
        Perform walk-forward analysis on daily returns.
        Returns dict suitable for ChartGenerator.chart5_walk_forward().
        """
        rf_daily = (1.0 + risk_free_rate) ** (1.0 / 252.0) - 1.0

        # Rolling Sharpe (63-day window)
        rolling_excess = daily_returns - rf_daily
        rolling_mean = rolling_excess.rolling(63).mean()
        rolling_std = daily_returns.rolling(63).std()
        rolling_sharpe = (rolling_mean / rolling_std * np.sqrt(252)).dropna()

        # IS vs OOS windows
        total_len = len(daily_returns)
        step = self.oos_window
        is_sharpe_list = []
        oos_sharpe_list = []
        window_labels = []

        start = 0
        while start + self.is_window + self.oos_window <= total_len:
            is_end = start + self.is_window
            oos_end = is_end + self.oos_window

            is_ret = daily_returns.iloc[start:is_end]
            oos_ret = daily_returns.iloc[is_end:oos_end]

            is_excess = is_ret - rf_daily
            oos_excess = oos_ret - rf_daily

            is_std = is_ret.std()
            oos_std = oos_ret.std()

            is_sr = (is_excess.mean() / is_std * np.sqrt(252)) if is_std > 0 else 0.0
            oos_sr = (oos_excess.mean() / oos_std * np.sqrt(252)) if oos_std > 0 else 0.0

            is_sharpe_list.append(is_sr)
            oos_sharpe_list.append(oos_sr)

            is_start_date = daily_returns.index[start].strftime('%Y-%m')
            oos_end_date = daily_returns.index[min(oos_end - 1, total_len - 1)].strftime('%Y-%m')
            window_labels.append(f'{is_start_date} to {oos_end_date}')

            start += step

        # Market regime: 21-day realized volatility annualized
        regime = daily_returns.rolling(21).std() * np.sqrt(252)
        regime = regime.dropna()

        return {
            'rolling_sharpe': rolling_sharpe,
            'is_sharpe': is_sharpe_list,
            'oos_sharpe': oos_sharpe_list,
            'window_labels': window_labels,
            'regime': regime,
        }


if __name__ == '__main__':
    # Example usage demonstrating the full pipeline
    print("=== Backtesting Engine Demo ===\n")

    # 1. Fetch data
    print("Fetching SPY data...")
    try:
        prices = DataFetcher.fetch('SPY', period='5y', interval='1d')
        prices = DataFetcher.validate_data(prices)
        print(f"  Loaded {len(prices)} bars from {prices.index[0].date()} to {prices.index[-1].date()}")
    except Exception as e:
        print(f"  Could not fetch live data ({e}), generating synthetic data...")
        dates = pd.bdate_range(start='2019-01-01', periods=1260)
        np.random.seed(42)
        close = 280.0 * np.cumprod(1 + np.random.normal(0.0003, 0.012, len(dates)))
        prices = pd.DataFrame({
            'Open': close * (1 + np.random.normal(0, 0.002, len(dates))),
            'High': close * (1 + np.abs(np.random.normal(0, 0.008, len(dates)))),
            'Low': close * (1 - np.abs(np.random.normal(0, 0.008, len(dates)))),
            'Close': close,
            'Volume': np.random.randint(50_000_000, 200_000_000, len(dates)).astype(float),
        }, index=dates)
        print(f"  Generated {len(prices)} synthetic bars")

    # 2. Generate simple moving-average crossover signals
    print("Generating SMA crossover signals...")
    sma_fast = prices['Close'].rolling(20).mean()
    sma_slow = prices['Close'].rolling(50).mean()

    signal_values = np.where(sma_fast > sma_slow, 1, np.where(sma_fast < sma_slow, -1, 0))
    atr = (prices['High'] - prices['Low']).rolling(14).mean()

    signals = pd.DataFrame({
        'signal': signal_values,
        'stop_loss': np.where(signal_values == 1,
                              prices['Close'] - 2 * atr,
                              np.where(signal_values == -1,
                                       prices['Close'] + 2 * atr, np.nan)),
        'take_profit': np.where(signal_values == 1,
                                prices['Close'] + 3 * atr,
                                np.where(signal_values == -1,
                                         prices['Close'] - 3 * atr, np.nan)),
        'position_size': 0.95,
    }, index=prices.index)

    # Drop rows before indicators are ready
    signals = signals.iloc[50:]
    prices_trimmed = prices.loc[signals.index]

    # 3. Run backtest
    print("Running backtest...")
    engine = BacktestEngine(initial_capital=100_000, commission_pct=0.001, slippage_pts=0.5)
    results = engine.run(signals, prices_trimmed)

    # 4. Print metrics
    print("\n--- Performance Metrics ---")
    for key, val in results['metrics'].items():
        if isinstance(val, float):
            if 'rate' in key or 'return' in key or 'cagr' in key or 'drawdown' in key or 'alpha' in key:
                print(f"  {key:>25s}: {val:>10.2%}")
            else:
                print(f"  {key:>25s}: {val:>10.4f}")
        else:
            print(f"  {key:>25s}: {val}")

    print(f"\n  Total trades: {len(results['trades'])}")
    if not results['trades'].empty:
        print(f"  Exit reasons: {results['trades']['exit_reason'].value_counts().to_dict()}")

    # 5. Walk-forward analysis
    print("\nRunning walk-forward analysis...")
    wfa = WalkForwardAnalyzer(is_window=252, oos_window=63)
    wf_results = wfa.analyze(results['daily_returns'])
    print(f"  Rolling Sharpe points: {len(wf_results['rolling_sharpe'])}")
    print(f"  Walk-forward windows: {len(wf_results['is_sharpe'])}")

    # 6. Generate charts
    print("\nGenerating charts...")
    charts = ChartGenerator(output_dir='./charts/')
    charts.generate_all(
        equity_curve=results['equity_curve'],
        benchmark_curve=results['benchmark_curve'],
        trades=results['trades'],
        monthly_returns=results['monthly_returns'],
        drawdown_series=results['drawdown_series'],
        walk_forward_results=wf_results,
        param_sensitivity=None,
        metrics=results['metrics'],
    )
    print(f"  Charts saved to ./charts/")

    # 7. Monte Carlo
    print("\nRunning Monte Carlo simulation (1000 paths)...")
    mc = PerformanceCalculator.monte_carlo_simulation(results['trades'], n_simulations=1000)
    if not mc.empty:
        final_values = mc.iloc[-1]
        print(f"  Median final equity: ${final_values.median():,.0f}")
        print(f"  5th percentile:      ${final_values.quantile(0.05):,.0f}")
        print(f"  95th percentile:     ${final_values.quantile(0.95):,.0f}")

    print("\n=== Done ===")
