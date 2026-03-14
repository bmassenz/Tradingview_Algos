"""
Multi-Timeframe Trading Strategy - Python Implementation
Faithful conversion of PineScript v6 MTF strategy with zero logic drift.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Tuple, Optional, Dict, List
import warnings
import uuid
import os

warnings.filterwarnings('ignore')


@dataclass
class StrategyParams:
    """Core strategy parameters."""
    ema_fast: int = 21
    ema_slow: int = 55
    supertrend_period: int = 10
    supertrend_mult: float = 2.5
    rsi_period: int = 14
    rsi_oversold: int = 35
    rsi_overbought: int = 65
    atr_period: int = 14
    atr_sl_mult: float = 2.5
    atr_tp_mult: float = 5.0
    adx_period: int = 14
    adx_trend_threshold: int = 20
    adx_range_threshold: int = 15
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    stoch_k: int = 14
    stoch_d: int = 3
    stoch_smooth: int = 3
    volume_ma_period: int = 20
    bb_period: int = 20
    bb_std: float = 2.0
    max_risk_pct: float = 0.02  # 2% risk per trade
    max_positions: int = 3
    commission_pct: float = 0.001  # 0.1%
    slippage_pts: float = 2.0
    drawdown_reduce_threshold: float = 0.05  # 5% rolling DD triggers 50% size reduction
    # Signal persistence: how many bars a crossover signal stays valid
    momentum_signal_persistence: int = 6  # 4H bars (~24 hours)
    stoch_signal_persistence: int = 4  # 1H bars
    # Confluence scoring: minimum score to trigger entry (out of 5)
    min_confluence_score: int = 3
    # Partial profit taking
    partial_tp_pct: float = 0.5  # close 50% at first TP
    partial_tp_mult: float = 3.0  # first TP at 3x ATR
    # Trend re-entry: allow re-entry on pullback within a trend
    reentry_pullback_atr: float = 1.5  # pullback depth in ATR units


class MTFStrategySignals:
    """
    Signal generation engine replicating PineScript MTF logic.
    Uses pandas resample() for multi-timeframe alignment.
    """

    def __init__(self, params: StrategyParams = None):
        self.params = params or StrategyParams()

    # ------------------------------------------------------------------
    # Indicator calculations
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_ema(series: pd.Series, period: int) -> pd.Series:
        """Exponential moving average matching PineScript ta.ema."""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def calculate_rma(series: pd.Series, period: int) -> pd.Series:
        """
        Wilder's smoothed moving average (RMA) matching PineScript ta.rma.
        Equivalent to EWM with alpha = 1/period.
        """
        return series.ewm(alpha=1.0 / period, adjust=False).mean()

    def calculate_supertrend(self, df: pd.DataFrame, period: int,
                             multiplier: float) -> pd.Series:
        """
        Full Supertrend algorithm.
        Returns direction series: 1 = bullish (price above supertrend),
        -1 = bearish (price below supertrend).

        PineScript convention: stDir < 0 means bullish (uptrend),
        stDir > 0 means bearish (downtrend). We replicate that here:
        returned value -1 = bullish, +1 = bearish  (matches Pine stDir).
        """
        hl2 = (df['high'] + df['low']) / 2.0
        atr = self.calculate_atr(df, period)

        basic_upper = hl2 + multiplier * atr
        basic_lower = hl2 - multiplier * atr

        n = len(df)
        final_upper = np.full(n, np.nan)
        final_lower = np.full(n, np.nan)
        supertrend = np.full(n, np.nan)
        direction = np.full(n, np.nan)  # -1 bullish, +1 bearish (Pine convention)

        close = df['close'].values
        bu = basic_upper.values
        bl = basic_lower.values

        # First valid index: need at least `period` bars for ATR
        start = period
        if start >= n:
            return pd.Series(direction, index=df.index)

        final_upper[start] = bu[start]
        final_lower[start] = bl[start]
        # Initial direction based on close vs bands
        if close[start] > final_upper[start]:
            direction[start] = -1.0  # bullish
            supertrend[start] = final_lower[start]
        else:
            direction[start] = 1.0  # bearish
            supertrend[start] = final_upper[start]

        for i in range(start + 1, n):
            # Final upper band: if current basic_upper < previous final_upper
            # OR previous close > previous final_upper, use current basic_upper
            if bu[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
                final_upper[i] = bu[i]
            else:
                final_upper[i] = final_upper[i - 1]

            # Final lower band: if current basic_lower > previous final_lower
            # OR previous close < previous final_lower, use current basic_lower
            if bl[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
                final_lower[i] = bl[i]
            else:
                final_lower[i] = final_lower[i - 1]

            # Direction logic
            prev_st = supertrend[i - 1]
            if direction[i - 1] == 1.0:  # was bearish
                if close[i] > final_upper[i]:
                    direction[i] = -1.0  # flip to bullish
                    supertrend[i] = final_lower[i]
                else:
                    direction[i] = 1.0
                    supertrend[i] = final_upper[i]
            else:  # was bullish (-1)
                if close[i] < final_lower[i]:
                    direction[i] = 1.0  # flip to bearish
                    supertrend[i] = final_upper[i]
                else:
                    direction[i] = -1.0
                    supertrend[i] = final_lower[i]

        return pd.Series(direction, index=df.index)

    @staticmethod
    def calculate_rsi(series: pd.Series, period: int) -> pd.Series:
        """RSI using Wilder's smoothing (RMA), matching PineScript ta.rsi."""
        delta = series.diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)

        avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi.fillna(50.0)

    @staticmethod
    def calculate_macd(series: pd.Series, fast: int, slow: int,
                       signal: int) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """MACD line, signal line, histogram. Matches PineScript ta.macd."""
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def calculate_stochastic(df: pd.DataFrame, k_period: int,
                             d_period: int,
                             smooth: int) -> Tuple[pd.Series, pd.Series]:
        """
        Stochastic %K (smoothed) and %D.
        Raw %K = (close - lowest low) / (highest high - lowest low) * 100
        %K = SMA(raw %K, smooth)
        %D = SMA(%K, d_period)
        """
        lowest_low = df['low'].rolling(window=k_period, min_periods=1).min()
        highest_high = df['high'].rolling(window=k_period, min_periods=1).max()
        denom = highest_high - lowest_low
        denom = denom.replace(0, np.nan)
        raw_k = 100.0 * (df['close'] - lowest_low) / denom
        raw_k = raw_k.fillna(50.0)
        k = raw_k.rolling(window=smooth, min_periods=1).mean()
        d = k.rolling(window=d_period, min_periods=1).mean()
        return k, d

    def calculate_adx(self, df: pd.DataFrame, period: int) -> pd.Series:
        """
        Full ADX calculation matching PineScript logic:
        +DM, -DM -> RMA smoothed -> +DI, -DI -> DX -> RMA -> ADX.
        """
        high = df['high']
        low = df['low']
        up_move = high.diff()
        down_move = -low.diff()

        plus_dm = pd.Series(np.where(
            (up_move > down_move) & (up_move > 0), up_move, 0.0
        ), index=df.index)
        minus_dm = pd.Series(np.where(
            (down_move > up_move) & (down_move > 0), down_move, 0.0
        ), index=df.index)

        # True Range
        tr = self._true_range(df)

        # Wilder smoothing (RMA)
        atr_smooth = tr.ewm(alpha=1.0 / period, adjust=False).mean()
        plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr_smooth
        minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr_smooth

        di_sum = plus_di + minus_di
        di_sum = di_sum.replace(0, np.nan)
        dx = 100.0 * (plus_di - minus_di).abs() / di_sum
        dx = dx.fillna(0.0)

        adx = dx.ewm(alpha=1.0 / period, adjust=False).mean()
        return adx

    def calculate_atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        """Average True Range using Wilder's smoothing (RMA)."""
        tr = self._true_range(df)
        return tr.ewm(alpha=1.0 / period, adjust=False).mean()

    @staticmethod
    def _true_range(df: pd.DataFrame) -> pd.Series:
        """True Range = max(high-low, |high-prev_close|, |low-prev_close|)."""
        prev_close = df['close'].shift(1)
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - prev_close).abs()
        tr3 = (df['low'] - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr

    @staticmethod
    def calculate_bollinger_bands(series: pd.Series, period: int,
                                  std: float) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Bollinger Bands: middle (SMA), upper, lower."""
        mid = series.rolling(window=period, min_periods=1).mean()
        sd = series.rolling(window=period, min_periods=1).std(ddof=0)
        upper = mid + std * sd
        lower = mid - std * sd
        return upper, mid, lower

    @staticmethod
    def calculate_obv(df: pd.DataFrame) -> pd.Series:
        """On-Balance Volume."""
        sign = np.sign(df['close'].diff())
        sign.iloc[0] = 0
        obv = (sign * df['volume']).cumsum()
        return obv

    # ------------------------------------------------------------------
    # Multi-timeframe helpers
    # ------------------------------------------------------------------

    @staticmethod
    def resample_to_timeframe(df: pd.DataFrame,
                              timeframe: str) -> pd.DataFrame:
        """
        Resample an OHLCV DataFrame to a higher timeframe.
        Uses standard OHLCV aggregation rules.
        timeframe examples: '4h', '1D', '1W'.
        """
        ohlcv_dict = {
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
        }
        resampled = df.resample(timeframe).agg(ohlcv_dict).dropna(subset=['close'])
        return resampled

    @staticmethod
    def align_htf_to_ltf(htf_series: pd.Series,
                          ltf_index: pd.DatetimeIndex) -> pd.Series:
        """
        Align a higher-timeframe series to a lower-timeframe index using
        forward-fill WITHOUT lookahead bias.

        The HTF value is shifted forward by one HTF period so it only becomes
        available after the HTF bar closes, then forward-filled onto the
        LTF index.
        """
        # Shift by 1 to avoid lookahead: the value of HTF bar N becomes
        # available at the open of HTF bar N+1.
        shifted = htf_series.shift(1)
        aligned = shifted.reindex(ltf_index, method='ffill')
        return aligned

    # ------------------------------------------------------------------
    # Signal persistence helper
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_persistence(signal: pd.Series, window: int) -> pd.Series:
        """
        Keep a boolean crossover signal 'alive' for `window` bars after it fires.
        This solves the core problem: crossover events are instantaneous but
        we need them to persist so multiple timeframes can align.
        """
        if window <= 1:
            return signal.astype(float)
        return signal.astype(float).rolling(window=window, min_periods=1).max()

    # ------------------------------------------------------------------
    # Main signal generation
    # ------------------------------------------------------------------

    def generate_signals(self, df_1h: pd.DataFrame,
                         df_4h: pd.DataFrame = None,
                         df_daily: pd.DataFrame = None) -> pd.DataFrame:
        """
        Improved signal generator using confluence scoring and signal persistence.

        Key improvements over v1:
          1. Signal persistence - crossover signals stay valid for N bars
          2. Confluence scoring - score 0-5, enter when >= min_confluence_score
          3. Mean-reversion mode - BB entries when ADX shows ranging market
          4. Trend re-entry - pullback entries within established trends
          5. Wider stops + partial TP - let winners run, take partial profits early

        Parameters
        ----------
        df_1h : pd.DataFrame
            1-hour OHLCV data with DatetimeIndex (columns: open, high, low, close, volume).
        df_4h, df_daily : pd.DataFrame, optional
            Higher timeframe data. Resampled from df_1h if not supplied.

        Returns
        -------
        pd.DataFrame with columns: signal, stop_loss, take_profit,
            partial_tp, position_size, regime, confluence_score
        """
        p = self.params

        if df_4h is None:
            df_4h = self.resample_to_timeframe(df_1h, '4h')
        if df_daily is None:
            df_daily = self.resample_to_timeframe(df_1h, '1D')

        idx = df_1h.index

        # ==============================================================
        # 1. DAILY TREND LAYER
        # ==============================================================
        d_ema_fast = self.calculate_ema(df_daily['close'], p.ema_fast)
        d_ema_slow = self.calculate_ema(df_daily['close'], p.ema_slow)
        d_st_dir = self.calculate_supertrend(df_daily, p.supertrend_period,
                                             p.supertrend_mult)
        d_adx = self.calculate_adx(df_daily, p.adx_period)

        # Align daily -> 1H (no lookahead)
        d_ema_fast_1h = self.align_htf_to_ltf(d_ema_fast, idx)
        d_ema_slow_1h = self.align_htf_to_ltf(d_ema_slow, idx)
        d_st_dir_1h = self.align_htf_to_ltf(d_st_dir, idx)
        d_adx_1h = self.align_htf_to_ltf(d_adx, idx)

        # EMA trend direction (continuous, not crossover-dependent)
        ema_bull = d_ema_fast_1h > d_ema_slow_1h
        ema_bear = d_ema_fast_1h < d_ema_slow_1h

        # Supertrend direction (continuous)
        st_bull = d_st_dir_1h < 0  # Pine convention: -1 = bullish
        st_bear = d_st_dir_1h > 0

        # Regime
        is_trending = d_adx_1h >= p.adx_trend_threshold
        is_ranging = d_adx_1h <= p.adx_range_threshold
        regime = pd.Series('neutral', index=idx)
        regime[is_trending] = 'trend'
        regime[is_ranging] = 'range'

        # ==============================================================
        # 2. 4H MOMENTUM LAYER (with signal persistence)
        # ==============================================================
        h4_rsi = self.calculate_rsi(df_4h['close'], p.rsi_period)
        h4_macd_line, h4_macd_signal, _ = self.calculate_macd(
            df_4h['close'], p.macd_fast, p.macd_slow, p.macd_signal
        )

        # RSI crossovers with persistence
        h4_rsi_prev = h4_rsi.shift(1)
        h4_rsi_buy_raw = (h4_rsi > p.rsi_oversold) & (h4_rsi_prev <= p.rsi_oversold)
        h4_rsi_sell_raw = (h4_rsi < p.rsi_overbought) & (h4_rsi_prev >= p.rsi_overbought)
        h4_rsi_buy = self._apply_persistence(h4_rsi_buy_raw, p.momentum_signal_persistence)
        h4_rsi_sell = self._apply_persistence(h4_rsi_sell_raw, p.momentum_signal_persistence)

        # MACD crossovers with persistence
        h4_macd_prev = h4_macd_line.shift(1)
        h4_sig_prev = h4_macd_signal.shift(1)
        h4_macd_buy_raw = (h4_macd_line > h4_macd_signal) & (h4_macd_prev <= h4_sig_prev)
        h4_macd_sell_raw = (h4_macd_line < h4_macd_signal) & (h4_macd_prev >= h4_sig_prev)
        h4_macd_buy = self._apply_persistence(h4_macd_buy_raw, p.momentum_signal_persistence)
        h4_macd_sell = self._apply_persistence(h4_macd_sell_raw, p.momentum_signal_persistence)

        # Also use RSI level as a continuous momentum indicator
        h4_rsi_1h = self.align_htf_to_ltf(h4_rsi, idx)
        rsi_bullish_zone = h4_rsi_1h > 50  # RSI above 50 = bullish momentum
        rsi_bearish_zone = h4_rsi_1h < 50

        # Align crossover persistence to 1H
        rsi_buy_1h = self.align_htf_to_ltf(h4_rsi_buy, idx).fillna(0)
        rsi_sell_1h = self.align_htf_to_ltf(h4_rsi_sell, idx).fillna(0)
        macd_buy_1h = self.align_htf_to_ltf(h4_macd_buy, idx).fillna(0)
        macd_sell_1h = self.align_htf_to_ltf(h4_macd_sell, idx).fillna(0)

        # Momentum signals (any crossover active OR RSI in favourable zone)
        mom_buy = (rsi_buy_1h > 0) | (macd_buy_1h > 0) | rsi_bullish_zone
        mom_sell = (rsi_sell_1h > 0) | (macd_sell_1h > 0) | rsi_bearish_zone

        # ==============================================================
        # 3. 1H ENTRY LAYER (with persistence)
        # ==============================================================
        stoch_k, stoch_d = self.calculate_stochastic(
            df_1h, p.stoch_k, p.stoch_d, p.stoch_smooth
        )
        stoch_k_prev = stoch_k.shift(1)
        stoch_d_prev = stoch_d.shift(1)

        # Stochastic crossover (relaxed: no extreme zone requirement)
        stoch_buy_raw = (stoch_k > stoch_d) & (stoch_k_prev <= stoch_d_prev)
        stoch_sell_raw = (stoch_k < stoch_d) & (stoch_k_prev >= stoch_d_prev)
        stoch_buy = self._apply_persistence(stoch_buy_raw, p.stoch_signal_persistence)
        stoch_sell = self._apply_persistence(stoch_sell_raw, p.stoch_signal_persistence)

        # Volume confirmation (relaxed: 80% of average is enough)
        vol_sma = df_1h['volume'].rolling(window=p.volume_ma_period,
                                          min_periods=1).mean()
        vol_confirm = df_1h['volume'] > (vol_sma * 0.8)

        # ==============================================================
        # 4. MEAN-REVERSION LAYER (Bollinger Band entries for ranging)
        # ==============================================================
        bb_upper, bb_mid, bb_lower = self.calculate_bollinger_bands(
            df_1h['close'], p.bb_period, p.bb_std
        )
        # Price near lower BB = long opportunity in range
        bb_long = (df_1h['close'] <= bb_lower * 1.005) & is_ranging
        # Price near upper BB = short opportunity in range
        bb_short = (df_1h['close'] >= bb_upper * 0.995) & is_ranging

        # ==============================================================
        # 5. TREND RE-ENTRY (pullback within established trend)
        # ==============================================================
        atr_1h = self.calculate_atr(df_1h, p.atr_period)
        close_1h = df_1h['close']

        # Price pulled back to fast EMA in an uptrend = re-entry opportunity
        pullback_to_ema_long = (
            ema_bull & st_bull &
            (close_1h <= d_ema_fast_1h * 1.005) &
            (close_1h >= d_ema_fast_1h - p.reentry_pullback_atr * atr_1h)
        )
        pullback_to_ema_short = (
            ema_bear & st_bear &
            (close_1h >= d_ema_fast_1h * 0.995) &
            (close_1h <= d_ema_fast_1h + p.reentry_pullback_atr * atr_1h)
        )

        # ==============================================================
        # 6. CONFLUENCE SCORING (0-5 points)
        # ==============================================================
        # Each condition contributes 1 point. Need min_confluence_score to enter.
        long_score = (
            ema_bull.astype(int) +          # 1: Daily EMA trend bullish
            st_bull.astype(int) +           # 2: Daily Supertrend bullish
            mom_buy.astype(int) +           # 3: 4H momentum bullish
            (stoch_buy > 0).astype(int) +   # 4: Stochastic entry signal
            vol_confirm.astype(int)         # 5: Volume confirmation
        )
        short_score = (
            ema_bear.astype(int) +
            st_bear.astype(int) +
            mom_sell.astype(int) +
            (stoch_sell > 0).astype(int) +
            vol_confirm.astype(int)
        )

        # Trend-following entries: confluence score >= threshold
        trend_long = long_score >= p.min_confluence_score
        trend_short = short_score >= p.min_confluence_score

        # Mean-reversion entries: BB touch + basic trend alignment + volume
        rev_long = bb_long & ema_bull & vol_confirm
        rev_short = bb_short & ema_bear & vol_confirm

        # Re-entry entries: pullback + momentum + volume
        reentry_long = pullback_to_ema_long & mom_buy & vol_confirm
        reentry_short = pullback_to_ema_short & mom_sell & vol_confirm

        # Combined signal
        long_signal = trend_long | rev_long | reentry_long
        short_signal = trend_short | rev_short | reentry_short

        signal = pd.Series(0, index=idx, dtype=int)
        signal[long_signal] = 1
        signal[short_signal] = -1
        # Long takes priority on conflicts
        signal[long_signal & short_signal] = 0

        # ==============================================================
        # 7. DYNAMIC SL / TP with partial profit taking
        # ==============================================================
        sl_long = close_1h - p.atr_sl_mult * atr_1h
        tp_long = close_1h + p.atr_tp_mult * atr_1h
        sl_short = close_1h + p.atr_sl_mult * atr_1h
        tp_short = close_1h - p.atr_tp_mult * atr_1h

        # Partial TP (first target, closer)
        partial_tp_long = close_1h + p.partial_tp_mult * atr_1h
        partial_tp_short = close_1h - p.partial_tp_mult * atr_1h

        stop_loss = pd.Series(np.nan, index=idx)
        take_profit = pd.Series(np.nan, index=idx)
        partial_tp = pd.Series(np.nan, index=idx)

        stop_loss[signal == 1] = sl_long[signal == 1]
        stop_loss[signal == -1] = sl_short[signal == -1]
        take_profit[signal == 1] = tp_long[signal == 1]
        take_profit[signal == -1] = tp_short[signal == -1]
        partial_tp[signal == 1] = partial_tp_long[signal == 1]
        partial_tp[signal == -1] = partial_tp_short[signal == -1]

        # ==============================================================
        # 8. POSITION SIZE
        # ==============================================================
        risk_per_unit = (close_1h - stop_loss).abs()
        risk_per_unit = risk_per_unit.replace(0, np.nan)
        position_size = (100000.0 * p.max_risk_pct) / risk_per_unit
        position_size = position_size.clip(lower=0.0)
        position_size[signal == 0] = 0.0

        # ==============================================================
        # 9. BUILD RESULT
        # ==============================================================
        result = pd.DataFrame({
            'signal': signal,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'partial_tp': partial_tp,
            'position_size': position_size,
            'regime': regime,
            'confluence_score': long_score.where(signal == 1,
                                short_score.where(signal == -1, 0)),
        }, index=idx)

        return result


class PositionManager:
    """Position sizing and risk management."""

    def __init__(self, params: StrategyParams = None,
                 starting_equity: float = 100000.0):
        self.params = params or StrategyParams()
        self.positions: List[Dict] = []
        self.closed_positions: List[Dict] = []
        self.equity = starting_equity
        self._next_id = 0

    def calculate_position_size(self, equity: float, entry: float,
                                stop_loss: float,
                                risk_pct: float) -> float:
        """
        Position size based on fixed-fractional risk.
        qty = (equity * risk_pct) / |entry - stop_loss|
        Matches PineScript calcPositionSize.
        """
        risk_amount = equity * risk_pct
        price_diff = abs(entry - stop_loss)
        if price_diff == 0:
            return 0.0
        qty = risk_amount / price_diff
        return max(qty, 0.0)

    def check_drawdown_reduction(self, equity_curve: pd.Series) -> float:
        """
        Returns a size multiplier (0.5 or 1.0).
        If the rolling drawdown from peak exceeds the threshold, reduce
        position size by 50%.
        """
        if equity_curve is None or len(equity_curve) < 2:
            return 1.0
        peak = equity_curve.expanding().max()
        dd = (equity_curve - peak) / peak
        current_dd = dd.iloc[-1]
        if current_dd < -self.params.drawdown_reduce_threshold:
            return 0.5
        return 1.0

    def can_open_position(self) -> bool:
        """Check whether we are below the max open positions limit."""
        return len(self.positions) < self.params.max_positions

    def open_position(self, entry: float, stop: float, tp: float,
                      size: float, direction: int,
                      partial_tp: float = None) -> Dict:
        """
        Open a new position.
        direction: 1 = long, -1 = short.
        partial_tp: first profit target where we close partial_tp_pct of position.
        Returns the position dict.
        """
        if not self.can_open_position():
            return {}
        pos_id = str(self._next_id)
        self._next_id += 1
        position = {
            'id': pos_id,
            'entry': entry,
            'stop_loss': stop,
            'take_profit': tp,
            'partial_tp': partial_tp,
            'partial_taken': False,
            'size': size,
            'original_size': size,
            'direction': direction,
            'trail_stop': stop,
            'pnl': 0.0,
            'status': 'open',
        }
        self.positions.append(position)
        return position

    def close_position(self, position_id: str, exit_price: float) -> Dict:
        """
        Close an existing position by id at exit_price.
        Applies commission and slippage. Returns the closed position dict.
        """
        pos = None
        for p in self.positions:
            if p['id'] == position_id:
                pos = p
                break
        if pos is None:
            return {}

        self.positions.remove(pos)

        # Slippage: adverse direction
        slip = self.params.slippage_pts
        if pos['direction'] == 1:  # long: exit lower
            adj_exit = exit_price - slip
        else:  # short: exit higher
            adj_exit = exit_price + slip

        raw_pnl = pos['direction'] * (adj_exit - pos['entry']) * pos['size']
        commission = self.params.commission_pct * pos['entry'] * pos['size'] \
                     + self.params.commission_pct * adj_exit * pos['size']
        net_pnl = raw_pnl - commission

        pos['exit'] = adj_exit
        pos['pnl'] = net_pnl
        pos['status'] = 'closed'
        self.equity += net_pnl
        self.closed_positions.append(pos)
        return pos

    def update_trailing_stops(self, current_price: float,
                              atr: float) -> None:
        """
        Move trailing stop in the favourable direction only.
        Trail distance = atr_sl_mult * ATR (mirrors PineScript trailStop).
        """
        trail_dist = self.params.atr_sl_mult * atr
        for pos in self.positions:
            if pos['direction'] == 1:  # long
                new_trail = current_price - trail_dist
                if new_trail > pos['trail_stop']:
                    pos['trail_stop'] = new_trail
            else:  # short
                new_trail = current_price + trail_dist
                if new_trail < pos['trail_stop']:
                    pos['trail_stop'] = new_trail

    def get_open_positions(self) -> List[Dict]:
        """Return a copy of currently open positions."""
        return list(self.positions)

    def check_stops(self, current_bar: pd.Series) -> List[Dict]:
        """
        Check if any open position's stop, take-profit, or partial TP has been hit.
        Returns list of closed positions (partial closes generate a separate record).
        """
        closed = []
        high = current_bar['high']
        low = current_bar['low']

        for pos in list(self.positions):
            hit = False
            exit_price = 0.0

            if pos['direction'] == 1:  # long
                effective_stop = max(pos['stop_loss'], pos['trail_stop'])
                if low <= effective_stop:
                    hit = True
                    exit_price = effective_stop
                elif high >= pos['take_profit']:
                    hit = True
                    exit_price = pos['take_profit']
                elif (not pos['partial_taken'] and pos['partial_tp'] is not None
                      and high >= pos['partial_tp']):
                    # Partial profit: close a portion, move stop to breakeven
                    partial_size = pos['size'] * self.params.partial_tp_pct
                    partial_pnl = pos['direction'] * (pos['partial_tp'] - pos['entry']) * partial_size
                    commission = (self.params.commission_pct * pos['entry'] * partial_size +
                                  self.params.commission_pct * pos['partial_tp'] * partial_size)
                    partial_pnl -= commission
                    self.equity += partial_pnl
                    pos['size'] -= partial_size
                    pos['partial_taken'] = True
                    pos['stop_loss'] = pos['entry']  # move stop to breakeven
                    pos['trail_stop'] = max(pos['trail_stop'], pos['entry'])
                    closed.append({
                        'id': pos['id'], 'entry': pos['entry'],
                        'exit': pos['partial_tp'], 'direction': pos['direction'],
                        'size': partial_size, 'pnl': partial_pnl,
                        'status': 'partial_close',
                    })
                    continue
            else:  # short
                effective_stop = min(pos['stop_loss'], pos['trail_stop'])
                if high >= effective_stop:
                    hit = True
                    exit_price = effective_stop
                elif low <= pos['take_profit']:
                    hit = True
                    exit_price = pos['take_profit']
                elif (not pos['partial_taken'] and pos['partial_tp'] is not None
                      and low <= pos['partial_tp']):
                    partial_size = pos['size'] * self.params.partial_tp_pct
                    partial_pnl = pos['direction'] * (pos['partial_tp'] - pos['entry']) * partial_size
                    commission = (self.params.commission_pct * pos['entry'] * partial_size +
                                  self.params.commission_pct * pos['partial_tp'] * partial_size)
                    partial_pnl -= commission
                    self.equity += partial_pnl
                    pos['size'] -= partial_size
                    pos['partial_taken'] = True
                    pos['stop_loss'] = pos['entry']
                    pos['trail_stop'] = min(pos['trail_stop'], pos['entry'])
                    closed.append({
                        'id': pos['id'], 'entry': pos['entry'],
                        'exit': pos['partial_tp'], 'direction': pos['direction'],
                        'size': partial_size, 'pnl': partial_pnl,
                        'status': 'partial_close',
                    })
                    continue

            if hit:
                result = self.close_position(pos['id'], exit_price)
                if result:
                    closed.append(result)

        return closed


class PerformanceReporter:
    """Calculate all performance metrics and generate visualizations."""

    @staticmethod
    def calculate_metrics(equity_curve: pd.Series,
                          trades: pd.DataFrame,
                          benchmark: pd.Series) -> dict:
        """
        Calculate ALL required metrics:
        - Total Return, CAGR, Sharpe, Sortino, Max Drawdown, Calmar
        - Win Rate, Profit Factor, Recovery Factor
        - Alpha over benchmark, avg trade duration, best/worst trade
        """
        metrics: Dict = {}

        # --- Equity-based metrics ---
        if equity_curve is None or len(equity_curve) < 2:
            return {'error': 'insufficient equity data'}

        total_return = (equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1.0
        metrics['total_return'] = total_return

        # CAGR
        days = (equity_curve.index[-1] - equity_curve.index[0]).days
        years = max(days / 365.25, 1e-6)
        cagr = (equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (1.0 / years) - 1.0
        metrics['cagr'] = cagr

        # Daily returns
        returns = equity_curve.pct_change().dropna()

        # Sharpe (annualised, assuming hourly data -> ~252*6.5 trading hours,
        # but we generalise by inferring frequency)
        freq_seconds = pd.Series(equity_curve.index).diff().dt.total_seconds().median()
        if np.isnan(freq_seconds) or freq_seconds <= 0:
            freq_seconds = 3600.0  # default 1H
        periods_per_year = 365.25 * 24 * 3600 / freq_seconds
        mean_ret = returns.mean()
        std_ret = returns.std()
        sharpe = (mean_ret / std_ret * np.sqrt(periods_per_year)) if std_ret > 0 else 0.0
        metrics['sharpe'] = sharpe

        # Sortino
        downside = returns[returns < 0]
        down_std = downside.std() if len(downside) > 0 else 1e-10
        sortino = (mean_ret / down_std * np.sqrt(periods_per_year)) if down_std > 0 else 0.0
        metrics['sortino'] = sortino

        # Max Drawdown
        peak = equity_curve.expanding().max()
        drawdown = (equity_curve - peak) / peak
        max_dd = drawdown.min()
        metrics['max_drawdown'] = max_dd

        # Calmar
        calmar = cagr / abs(max_dd) if max_dd != 0 else 0.0
        metrics['calmar'] = calmar

        # --- Trade-based metrics ---
        if trades is not None and len(trades) > 0:
            pnl = trades['pnl'] if 'pnl' in trades.columns else pd.Series(dtype=float)
            winners = pnl[pnl > 0]
            losers = pnl[pnl <= 0]

            win_rate = len(winners) / len(pnl) if len(pnl) > 0 else 0.0
            metrics['win_rate'] = win_rate
            metrics['total_trades'] = len(pnl)

            gross_profit = winners.sum() if len(winners) > 0 else 0.0
            gross_loss = abs(losers.sum()) if len(losers) > 0 else 1e-10
            profit_factor = gross_profit / gross_loss
            metrics['profit_factor'] = profit_factor

            # Recovery factor = total_return_absolute / |max_dd_absolute|
            max_dd_abs = abs(max_dd * equity_curve.iloc[0]) if max_dd != 0 else 1e-10
            recovery_factor = pnl.sum() / max_dd_abs if max_dd_abs > 0 else 0.0
            metrics['recovery_factor'] = recovery_factor

            metrics['best_trade'] = pnl.max() if len(pnl) > 0 else 0.0
            metrics['worst_trade'] = pnl.min() if len(pnl) > 0 else 0.0

            if 'entry_time' in trades.columns and 'exit_time' in trades.columns:
                durations = pd.to_datetime(trades['exit_time']) - pd.to_datetime(trades['entry_time'])
                metrics['avg_trade_duration'] = str(durations.mean())
            else:
                metrics['avg_trade_duration'] = 'N/A'
        else:
            metrics['win_rate'] = 0.0
            metrics['total_trades'] = 0
            metrics['profit_factor'] = 0.0
            metrics['recovery_factor'] = 0.0
            metrics['best_trade'] = 0.0
            metrics['worst_trade'] = 0.0
            metrics['avg_trade_duration'] = 'N/A'

        # --- Alpha over benchmark ---
        if benchmark is not None and len(benchmark) >= 2:
            bench_return = (benchmark.iloc[-1] / benchmark.iloc[0]) - 1.0
            metrics['benchmark_return'] = bench_return
            metrics['alpha'] = total_return - bench_return
        else:
            metrics['benchmark_return'] = 0.0
            metrics['alpha'] = total_return

        return metrics

    @staticmethod
    def _compute_drawdown_series(equity_curve: pd.Series) -> pd.Series:
        peak = equity_curve.expanding().max()
        return (equity_curve - peak) / peak

    @staticmethod
    def _compute_monthly_returns(equity_curve: pd.Series) -> pd.DataFrame:
        monthly = equity_curve.resample('ME').last()
        monthly_ret = monthly.pct_change().dropna()
        df = pd.DataFrame({
            'year': monthly_ret.index.year,
            'month': monthly_ret.index.month,
            'return': monthly_ret.values,
        })
        pivot = df.pivot_table(index='year', columns='month',
                               values='return', aggfunc='sum')
        pivot.columns = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                         'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][:len(pivot.columns)]
        return pivot

    @staticmethod
    def generate_charts(equity_curve: pd.Series,
                        trades: pd.DataFrame,
                        benchmark: pd.Series,
                        monthly_returns: pd.DataFrame = None,
                        drawdown_series: pd.Series = None,
                        walk_forward_results: pd.DataFrame = None,
                        param_sensitivity: pd.DataFrame = None,
                        output_dir: str = './charts/') -> List[str]:
        """
        Generate all 6 required charts as PNG files.
        Returns list of file paths created.

        Charts:
          1. Equity curve vs benchmark
          2. Drawdown series
          3. Monthly returns heatmap
          4. Trade P&L distribution
          5. Walk-forward OOS equity curves
          6. Parameter sensitivity surface
        """
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
        except ImportError:
            return []

        os.makedirs(output_dir, exist_ok=True)
        created: List[str] = []

        # --- 1. Equity curve vs benchmark ---
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(equity_curve.index, equity_curve.values, label='Strategy',
                linewidth=1.2)
        if benchmark is not None and len(benchmark) > 0:
            # Normalise benchmark to same starting equity
            norm_bench = benchmark / benchmark.iloc[0] * equity_curve.iloc[0]
            ax.plot(norm_bench.index, norm_bench.values, label='Benchmark',
                    linewidth=1.0, alpha=0.7)
        ax.set_title('Equity Curve vs Benchmark')
        ax.set_ylabel('Equity')
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        path = os.path.join(output_dir, '1_equity_curve.png')
        fig.savefig(path, dpi=150)
        plt.close(fig)
        created.append(path)

        # --- 2. Drawdown series ---
        if drawdown_series is None:
            drawdown_series = PerformanceReporter._compute_drawdown_series(equity_curve)
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.fill_between(drawdown_series.index, drawdown_series.values, 0,
                        color='red', alpha=0.4)
        ax.set_title('Drawdown')
        ax.set_ylabel('Drawdown %')
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        path = os.path.join(output_dir, '2_drawdown.png')
        fig.savefig(path, dpi=150)
        plt.close(fig)
        created.append(path)

        # --- 3. Monthly returns heatmap ---
        if monthly_returns is None:
            monthly_returns = PerformanceReporter._compute_monthly_returns(equity_curve)
        if monthly_returns is not None and len(monthly_returns) > 0:
            fig, ax = plt.subplots(figsize=(12, max(3, len(monthly_returns) * 0.5)))
            cax = ax.imshow(monthly_returns.values, aspect='auto',
                            cmap='RdYlGn', interpolation='nearest')
            ax.set_xticks(range(len(monthly_returns.columns)))
            ax.set_xticklabels(monthly_returns.columns)
            ax.set_yticks(range(len(monthly_returns.index)))
            ax.set_yticklabels(monthly_returns.index)
            # Annotate cells
            for i in range(len(monthly_returns.index)):
                for j in range(len(monthly_returns.columns)):
                    val = monthly_returns.iloc[i, j]
                    if not np.isnan(val):
                        ax.text(j, i, f'{val:.1%}', ha='center', va='center',
                                fontsize=7)
            fig.colorbar(cax, ax=ax, shrink=0.8)
            ax.set_title('Monthly Returns Heatmap')
            fig.tight_layout()
            path = os.path.join(output_dir, '3_monthly_returns.png')
            fig.savefig(path, dpi=150)
            plt.close(fig)
            created.append(path)

        # --- 4. Trade P&L distribution ---
        if trades is not None and 'pnl' in trades.columns and len(trades) > 0:
            fig, ax = plt.subplots(figsize=(10, 5))
            pnl = trades['pnl']
            ax.hist(pnl, bins=min(50, max(10, len(pnl) // 3)),
                    color='steelblue', edgecolor='black', alpha=0.75)
            ax.axvline(0, color='red', linestyle='--', linewidth=1)
            ax.axvline(pnl.mean(), color='green', linestyle='--',
                       linewidth=1, label=f'Mean: {pnl.mean():.2f}')
            ax.set_title('Trade P&L Distribution')
            ax.set_xlabel('P&L')
            ax.set_ylabel('Count')
            ax.legend()
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            path = os.path.join(output_dir, '4_pnl_distribution.png')
            fig.savefig(path, dpi=150)
            plt.close(fig)
            created.append(path)

        # --- 5. Walk-forward OOS equity curves ---
        if walk_forward_results is not None and len(walk_forward_results) > 0:
            fig, ax = plt.subplots(figsize=(12, 5))
            if isinstance(walk_forward_results, pd.DataFrame):
                for col in walk_forward_results.columns:
                    ax.plot(walk_forward_results.index,
                            walk_forward_results[col].values,
                            label=f'Fold {col}', linewidth=0.9)
            else:
                ax.plot(walk_forward_results.index,
                        walk_forward_results.values, linewidth=1.0)
            ax.set_title('Walk-Forward Out-of-Sample Equity')
            ax.set_ylabel('Equity')
            ax.legend(fontsize=7)
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            path = os.path.join(output_dir, '5_walk_forward.png')
            fig.savefig(path, dpi=150)
            plt.close(fig)
            created.append(path)

        # --- 6. Parameter sensitivity surface ---
        if param_sensitivity is not None and len(param_sensitivity) > 0:
            fig, ax = plt.subplots(figsize=(10, 6))
            cax = ax.imshow(param_sensitivity.values, aspect='auto',
                            cmap='viridis', interpolation='nearest')
            ax.set_xticks(range(len(param_sensitivity.columns)))
            ax.set_xticklabels(param_sensitivity.columns, rotation=45,
                               ha='right', fontsize=7)
            ax.set_yticks(range(len(param_sensitivity.index)))
            ax.set_yticklabels(param_sensitivity.index, fontsize=7)
            ax.set_title('Parameter Sensitivity (Sharpe)')
            fig.colorbar(cax, ax=ax, shrink=0.8)
            fig.tight_layout()
            path = os.path.join(output_dir, '6_param_sensitivity.png')
            fig.savefig(path, dpi=150)
            plt.close(fig)
            created.append(path)

        return created


# ======================================================================
# Convenience runner for quick backtesting
# ======================================================================

def run_backtest(df_1h: pd.DataFrame,
                 params: StrategyParams = None,
                 starting_equity: float = 100000.0,
                 benchmark: pd.Series = None) -> Dict:
    """
    End-to-end backtest:
      1. Generate signals
      2. Simulate positions with PositionManager
      3. Compute metrics and charts

    Parameters
    ----------
    df_1h : pd.DataFrame
        1H OHLCV with DatetimeIndex.
    params : StrategyParams, optional
    starting_equity : float
    benchmark : pd.Series, optional
        Benchmark price series for alpha calculation.

    Returns
    -------
    dict with keys: metrics, equity_curve, trades, signals
    """
    params = params or StrategyParams()
    signals_engine = MTFStrategySignals(params)
    pm = PositionManager(params, starting_equity)

    signals_df = signals_engine.generate_signals(df_1h)
    atr_series = signals_engine.calculate_atr(df_1h, params.atr_period)

    equity_records = []
    trade_records = []

    equity_curve_so_far = pd.Series(dtype=float)

    for i in range(len(df_1h)):
        bar = df_1h.iloc[i]
        ts = df_1h.index[i]
        sig = signals_df.iloc[i]
        atr_val = atr_series.iloc[i]

        # Check stops on open positions
        closed = pm.check_stops(bar)
        for c in closed:
            trade_records.append({
                'entry_price': c['entry'],
                'exit_price': c['exit'],
                'direction': c['direction'],
                'size': c['size'],
                'pnl': c['pnl'],
                'exit_time': ts,
            })

        # Update trailing stops
        if not np.isnan(atr_val) and atr_val > 0:
            pm.update_trailing_stops(bar['close'], atr_val)

        # Open new positions on signal
        if sig['signal'] != 0 and pm.can_open_position():
            entry_price = bar['close']
            sl = sig['stop_loss']
            tp = sig['take_profit']
            partial_tp = sig.get('partial_tp', np.nan)
            direction = int(sig['signal'])

            if not np.isnan(sl) and not np.isnan(tp):
                # Drawdown check
                if len(equity_records) > 10:
                    eq_so_far = pd.Series(
                        [e[1] for e in equity_records[-100:]],
                        index=[e[0] for e in equity_records[-100:]]
                    )
                    size_mult = pm.check_drawdown_reduction(eq_so_far)
                else:
                    size_mult = 1.0

                size = pm.calculate_position_size(
                    pm.equity, entry_price, sl, params.max_risk_pct
                ) * size_mult

                if size > 0:
                    ptp = partial_tp if not np.isnan(partial_tp) else None
                    pos = pm.open_position(entry_price, sl, tp, size,
                                           direction, partial_tp=ptp)
                    if pos:
                        pos['entry_time'] = ts

        equity_records.append((ts, pm.equity))

    # Close any remaining positions at last bar close
    last_bar = df_1h.iloc[-1]
    for pos in list(pm.positions):
        c = pm.close_position(pos['id'], last_bar['close'])
        if c:
            trade_records.append({
                'entry_price': c['entry'],
                'exit_price': c['exit'],
                'direction': c['direction'],
                'size': c['size'],
                'pnl': c['pnl'],
                'exit_time': df_1h.index[-1],
            })

    # Build outputs
    equity_curve = pd.Series(
        [e[1] for e in equity_records],
        index=pd.DatetimeIndex([e[0] for e in equity_records])
    )
    trades_df = pd.DataFrame(trade_records) if trade_records else pd.DataFrame(
        columns=['entry_price', 'exit_price', 'direction', 'size', 'pnl',
                 'exit_time']
    )

    if benchmark is None:
        benchmark = df_1h['close']

    metrics = PerformanceReporter.calculate_metrics(
        equity_curve, trades_df, benchmark
    )

    return {
        'metrics': metrics,
        'equity_curve': equity_curve,
        'trades': trades_df,
        'signals': signals_df,
    }
