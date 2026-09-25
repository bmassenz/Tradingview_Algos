"""Bar-by-bar Python replica of trend_core_wae_professional.pine (daily chart).

Mirrors the TradingView broker emulator as configured in the script:
  * signals on confirmed closes, market orders fill at the next bar's open
  * brackets (stop / limit) are live from the fill bar; gap-through fills at the open
  * intrabar path: open->high->low->close when the high is closer to the open, else open->low->high->close
  * slippage 2 ticks on market and stop fills, none on limit fills; commission 0.01% per side
  * fixed paper sizing capital, whole shares
Indicators follow Pine's definitions (SMA-seeded EMA/RMA, population stdev, RMA RSI/ATR).
"""
import math
import numpy as np
import pandas as pd
from numba import njit

TICK = 0.01
SLIP_TICKS = 2
COMMISSION = 0.0001
CAPITAL = 26000.0

# ---------------------------------------------------------------------------
# Pine-equivalent indicators
# ---------------------------------------------------------------------------


@njit(cache=True)
def ema(src, n):
    out = np.full(src.size, np.nan)
    alpha = 2.0 / (n + 1.0)
    s = 0.0
    cnt = 0
    prev = np.nan
    for i in range(src.size):
        x = src[i]
        if np.isnan(x):
            continue
        if np.isnan(prev):
            s += x
            cnt += 1
            if cnt == n:
                prev = s / n
                out[i] = prev
        else:
            prev = alpha * x + (1.0 - alpha) * prev
            out[i] = prev
    return out


@njit(cache=True)
def rma(src, n):
    out = np.full(src.size, np.nan)
    alpha = 1.0 / n
    s = 0.0
    cnt = 0
    prev = np.nan
    for i in range(src.size):
        x = src[i]
        if np.isnan(x):
            continue
        if np.isnan(prev):
            s += x
            cnt += 1
            if cnt == n:
                prev = s / n
                out[i] = prev
        else:
            prev = alpha * x + (1.0 - alpha) * prev
            out[i] = prev
    return out


@njit(cache=True)
def stdev(src, n):
    out = np.full(src.size, np.nan)
    for i in range(n - 1, src.size):
        m = 0.0
        for j in range(i - n + 1, i + 1):
            m += src[j]
        m /= n
        v = 0.0
        for j in range(i - n + 1, i + 1):
            d = src[j] - m
            v += d * d
        out[i] = math.sqrt(v / n)
    return out


@njit(cache=True)
def atr(h, l, c, n):
    tr = np.empty(c.size)
    tr[0] = h[0] - l[0]
    for i in range(1, c.size):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    return rma(tr, n)


@njit(cache=True)
def rsi(c, n):
    up = np.full(c.size, np.nan)
    dn = np.full(c.size, np.nan)
    for i in range(1, c.size):
        ch = c[i] - c[i - 1]
        up[i] = max(ch, 0.0)
        dn[i] = max(-ch, 0.0)
    ru = rma(up, n)
    rd = rma(dn, n)
    out = np.full(c.size, np.nan)
    for i in range(c.size):
        if np.isnan(ru[i]) or np.isnan(rd[i]):
            continue
        if rd[i] == 0.0:
            out[i] = 100.0
        elif ru[i] == 0.0:
            out[i] = 0.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + ru[i] / rd[i])
    return out


@njit(cache=True)
def wae_signals(c, fast, slow, bblen, expl, dead):
    """Returns (waeLongOK, waeDownDominant) exactly as in the Pine script."""
    m = ema(c, fast) - ema(c, slow)
    dev = stdev(c, bblen)
    n = c.size
    ok = np.zeros(n, np.bool_)
    down_dom = np.zeros(n, np.bool_)
    for i in range(2, n):
        hist = m[i] - m[i - 1]
        hist1 = m[i - 1] - m[i - 2]
        if np.isnan(hist) or np.isnan(hist1) or np.isnan(dev[i]) or np.isnan(dev[i - 1]):
            continue
        d0 = max(dev[i], TICK)
        d1 = max(dev[i - 1], TICK)
        upn = max(hist, 0.0) / d0
        upp = max(hist1, 0.0) / d1
        ok[i] = upn > expl and upn > dead and upn > upp
        up = max(hist, 0.0)
        down = max(-hist, 0.0)
        down1 = max(-hist1, 0.0)
        down_dom[i] = down > up and down > down1
    return ok, down_dom


# ---------------------------------------------------------------------------
# Asset container with parameter-independent preprocessing
# ---------------------------------------------------------------------------


class Asset:
    def __init__(self, symbol, df):
        self.symbol = symbol
        self.dates = df.index
        self.o = df["Open"].to_numpy(np.float64)
        self.h = df["High"].to_numpy(np.float64)
        self.l = df["Low"].to_numpy(np.float64)
        self.c = df["Close"].to_numpy(np.float64)
        # Weekly bars (Mon-Fri) for the HTF WAE. Day d may only use the latest week
        # whose final trading day is <= d-1 (completed-bar semantics, no lookahead).
        wk = df.index.to_period("W-FRI")
        codes, uniq = pd.factorize(wk)
        self.week_of_day = codes
        last_idx = pd.Series(np.arange(len(df))).groupby(codes).max().to_numpy()
        self.week_close = self.c[last_idx]
        n = len(df)
        m = np.full(n, -1, np.int64)
        for d in range(1, n):
            w = codes[d - 1]
            m[d] = w if last_idx[w] == d - 1 else w - 1
        self.day_to_completed_week = m
        self._cache = {}

    def idx(self, date):
        return int(np.searchsorted(self.dates.values, np.datetime64(pd.Timestamp(date))))

    def cached(self, key, fn):
        v = self._cache.get(key)
        if v is None:
            v = fn()
            if len(self._cache) > 4000:
                self._cache.clear()
            self._cache[key] = v
        return v


# Parameter vector layout (floats) passed to the numba engine
P_KEYS = [
    "coreAllocationPct", "coreTrailPct", "coreReentryCooldown", "atrStopMult",
    "tier1R", "tier2R", "tier3R", "useBreakEven", "breakEvenTriggerR", "trailStartR",
    "atrTrailMult", "hardExitOnMomentumLoss", "hardExitOnTrendLoss", "rsiHardExitThreshold",
    "rsiEntryThreshold", "useRSIFilter", "useEMASlopeFilter", "useHTFWAE",
    "useVolShockFilter", "volSpikeMax", "useGapFilter", "gapAtrMax",
    "overlayRiskPct", "maxOverlayRiskCash", "maxOverlayNotionalPct", "maxGrossExposurePct",
    "enableOverlay", "flattenOverlayWithoutCore", "minOverlayQty",
]

DEFAULTS = dict(
    # Original script defaults (overlay/core logic), audited execution model
    emaLen=150, coreAllocationPct=100.0, coreTrailPct=5.0, coreReentryCooldown=0,
    fastLen=30, slowLen=90, waeBBLen=20, waeBBMult=0.05, deadMult=0.02,
    rsiLen=14, rsiEntryThreshold=60.0, rsiHardExitThreshold=48.0, useRSIFilter=1,
    useEMASlopeFilter=1, useHTFWAE=1, atrLen=21, atrStopMult=1.5,
    tier1R=1.0, tier2R=2.0, tier3R=4.0, useBreakEven=1, breakEvenTriggerR=0.75,
    trailStartR=2.0, atrTrailMult=1.0, hardExitOnMomentumLoss=1, hardExitOnTrendLoss=1,
    useVolShockFilter=0, volFastLen=5, volSlowLen=63, volSpikeMax=1.6,
    useGapFilter=0, gapAtrMax=1.0,
    overlayRiskPct=0.25, maxOverlayRiskCash=65.0, maxOverlayNotionalPct=25.0,
    maxGrossExposurePct=125.0, enableOverlay=1, flattenOverlayWithoutCore=1, minOverlayQty=3.0,
)


def indicators(asset, p):
    c, h, l, o = asset.c, asset.h, asset.l, asset.o
    e = asset.cached(("ema", p["emaLen"]), lambda: ema(c, int(p["emaLen"])))
    a = asset.cached(("atr", p["atrLen"]), lambda: atr(h, l, c, int(p["atrLen"])))
    r = asset.cached(("rsi", p["rsiLen"]), lambda: rsi(c, int(p["rsiLen"])))
    wk = (p["fastLen"], p["slowLen"], p["waeBBLen"], round(p["waeBBMult"], 6), round(p["deadMult"], 6))
    wae_ok, wae_dd = asset.cached(("wae",) + wk, lambda: wae_signals(c, int(wk[0]), int(wk[1]), int(wk[2]), wk[3], wk[4]))

    def _htf():
        wok, _ = wae_signals(asset.week_close, int(wk[0]), int(wk[1]), int(wk[2]), wk[3], wk[4])
        mp = asset.day_to_completed_week
        out = np.zeros(c.size, np.bool_)
        valid = mp >= 0
        out[valid] = wok[mp[valid]]
        return out

    htf = asset.cached(("htf",) + wk, _htf)
    vk = (p["volFastLen"], p["volSlowLen"])

    def _vol():
        return atr(h, l, c, int(vk[0])) / atr(h, l, c, int(vk[1]))

    vr = asset.cached(("vol",) + vk, _vol)
    gap = np.full(c.size, np.nan)
    gap[1:] = np.abs(o[1:] - c[:-1]) / a[:-1]
    return e, a, r, wae_ok, wae_dd, htf, vr, gap


@njit(cache=True)
def _exit_long(o, h, l, stop, limit, slip):
    """Returns (filled, price, is_stop) for a long position's bracket during one bar."""
    has_lim = not np.isnan(limit)
    has_stop = not np.isnan(stop)
    if has_stop and o <= stop:
        return True, o - slip, True
    if has_lim and o >= limit:
        return True, o, False
    high_first = (h - o) < (o - l)
    if high_first:
        if has_lim and h >= limit:
            return True, limit, False
        if has_stop and l <= stop:
            return True, stop - slip, True
    else:
        if has_stop and l <= stop:
            return True, stop - slip, True
        if has_lim and h >= limit:
            return True, limit, False
    return False, 0.0, False


@njit(cache=True)
def run_engine(o, h, l, c, ema_v, atr_v, rsi_v, wae_ok, wae_dd, htf_ok, vol_r, gap_atr, start, P, capital):
    n = c.size
    slip = SLIP_TICKS * TICK
    (alloc, trail, cooldown, atr_stop_mult, t1r, t2r, t3r, use_be, be_r, trail_start_r,
     atr_trail_mult, hx_mom, hx_trend, rsi_hx, rsi_entry, use_rsi, use_slope, use_htf,
     use_vol, vol_max, use_gap, gap_max, risk_pct, risk_cap, notional_pct, gross_pct,
     enable_ov, flatten_orphan, min_ov_qty) = (P[0], P[1], P[2], P[3], P[4], P[5], P[6], P[7], P[8],
                                               P[9], P[10], P[11], P[12], P[13], P[14], P[15], P[16], P[17],
                                               P[18], P[19], P[20], P[21], P[22], P[23], P[24], P[25],
                                               P[26], P[27], P[28])

    equity = np.full(n, capital)
    exposure = np.zeros(n)
    # trade log: kind(0 core,1..3 tier), entry_idx, exit_idx, qty, entry_px, exit_px, pnl
    max_tr = 20000
    tr_kind = np.zeros(max_tr, np.int64)
    tr_ei = np.zeros(max_tr, np.int64)
    tr_xi = np.zeros(max_tr, np.int64)
    tr_qty = np.zeros(max_tr)
    tr_epx = np.zeros(max_tr)
    tr_xpx = np.zeros(max_tr)
    tr_pnl = np.zeros(max_tr)
    ntr = 0

    cash = 0.0  # realized PnL net of commissions

    # core state
    core_qty = 0.0
    core_px = 0.0
    core_ei = -1
    core_comm_in = 0.0
    core_peak = np.nan
    core_stop = np.nan
    core_pend_entry = False
    core_pend_qty = 0.0
    core_pend_close = False
    core_open_prev = False
    cooldown_until = -1

    # overlay state (3 tiers)
    t_qty = np.zeros(3)
    t_px = np.zeros(3)
    t_ei = np.zeros(3, np.int64)
    t_comm = np.zeros(3)
    t_pend = np.zeros(3, np.bool_)
    t_pend_qty = np.zeros(3)
    t_pend_close = np.zeros(3, np.bool_)
    t_stop = np.full(3, np.nan)
    t_lim = np.full(3, np.nan)
    ov_entry = np.nan
    ov_risk = np.nan
    ov_init_stop = np.nan
    ov_t3_stop = np.nan
    ov_entry_bar = -1
    ov_hx_sent = False
    be_armed = False
    trailing = False

    for i in range(1, n):
        oi, hi, li, ci = o[i], h[i], l[i], c[i]
        # ---------------- fills at the open (orders placed at close of i-1) ----------------
        if core_pend_close and core_qty > 0:
            px = oi - slip
            comm = px * core_qty * COMMISSION
            pnl = (px - core_px) * core_qty - comm - core_comm_in
            cash += (px - core_px) * core_qty - comm
            tr_kind[ntr] = 0; tr_ei[ntr] = core_ei; tr_xi[ntr] = i; tr_qty[ntr] = core_qty
            tr_epx[ntr] = core_px; tr_xpx[ntr] = px; tr_pnl[ntr] = pnl; ntr += 1
            core_qty = 0.0
        core_pend_close = False
        if core_pend_entry:
            core_px = oi + slip
            core_qty = core_pend_qty
            core_ei = i
            core_comm_in = core_px * core_qty * COMMISSION
            cash -= core_comm_in
        core_pend_entry = False
        for k in range(3):
            if t_pend_close[k] and t_qty[k] > 0:
                px = oi - slip
                comm = px * t_qty[k] * COMMISSION
                pnl = (px - t_px[k]) * t_qty[k] - comm - t_comm[k]
                cash += (px - t_px[k]) * t_qty[k] - comm
                tr_kind[ntr] = k + 1; tr_ei[ntr] = t_ei[k]; tr_xi[ntr] = i; tr_qty[ntr] = t_qty[k]
                tr_epx[ntr] = t_px[k]; tr_xpx[ntr] = px; tr_pnl[ntr] = pnl; ntr += 1
                t_qty[k] = 0.0
            t_pend_close[k] = False
            if t_pend[k]:
                t_px[k] = oi + slip
                t_qty[k] = t_pend_qty[k]
                t_ei[k] = i
                t_comm[k] = t_px[k] * t_qty[k] * COMMISSION
                cash -= t_comm[k]
            t_pend[k] = False
        # ---------------- intrabar bracket fills ----------------
        if core_qty > 0 and not np.isnan(core_stop):
            f, px, _ = _exit_long(oi, hi, li, core_stop, np.nan, slip)
            if f:
                comm = px * core_qty * COMMISSION
                pnl = (px - core_px) * core_qty - comm - core_comm_in
                cash += (px - core_px) * core_qty - comm
                tr_kind[ntr] = 0; tr_ei[ntr] = core_ei; tr_xi[ntr] = i; tr_qty[ntr] = core_qty
                tr_epx[ntr] = core_px; tr_xpx[ntr] = px; tr_pnl[ntr] = pnl; ntr += 1
                core_qty = 0.0
        for k in range(3):
            if t_qty[k] > 0:
                f, px, _ = _exit_long(oi, hi, li, t_stop[k], t_lim[k], slip)
                if f:
                    comm = px * t_qty[k] * COMMISSION
                    pnl = (px - t_px[k]) * t_qty[k] - comm - t_comm[k]
                    cash += (px - t_px[k]) * t_qty[k] - comm
                    tr_kind[ntr] = k + 1; tr_ei[ntr] = t_ei[k]; tr_xi[ntr] = i; tr_qty[ntr] = t_qty[k]
                    tr_epx[ntr] = t_px[k]; tr_xpx[ntr] = px; tr_pnl[ntr] = pnl; ntr += 1
                    t_qty[k] = 0.0

        # ---------------- mark to market at the close ----------------
        unreal = 0.0
        expo = 0.0
        if core_qty > 0:
            unreal += (ci - core_px) * core_qty
            expo += ci * core_qty
        for k in range(3):
            if t_qty[k] > 0:
                unreal += (ci - t_px[k]) * t_qty[k]
                expo += ci * t_qty[k]
        equity[i] = capital + cash + unreal
        exposure[i] = expo

        # ---------------- script logic on the confirmed close ----------------
        trend_ok = (not np.isnan(ema_v[i])) and ci > ema_v[i]
        core_open = core_qty > 0
        if core_open:
            if not core_open_prev:
                core_peak = max(core_px, hi)
            else:
                core_peak = max(core_peak, hi)
            core_stop = core_peak * (1.0 - trail / 100.0)
            if not trend_ok:
                core_pend_close = True
        else:
            if core_open_prev:
                cooldown_until = i + int(cooldown)
            core_peak = np.nan
            core_stop = np.nan
        cooldown_ok = cooldown_until < 0 or i >= cooldown_until
        if i >= start and trend_ok and (not core_open) and cooldown_ok:
            q = math.floor((capital * alloc / 100.0) / ci)
            if q >= 1:
                core_pend_entry = True
                core_pend_qty = q
                core_stop = ci * (1.0 - trail / 100.0)

        # overlay
        ov_open = t_qty[0] > 0 or t_qty[1] > 0 or t_qty[2] > 0
        if not ov_open:
            ov_hx_sent = False
            be_armed = False
            trailing = False
            ov_entry = np.nan
            ov_risk = np.nan
            ov_init_stop = np.nan
            ov_t3_stop = np.nan
            ov_entry_bar = -1
        campaign_live = ov_open

        rsi_ok = (use_rsi < 0.5) or ((not np.isnan(rsi_v[i])) and rsi_v[i] >= rsi_entry)
        htf_pass = (use_htf < 0.5) or htf_ok[i]
        slope_ok = (use_slope < 0.5) or ((not np.isnan(ema_v[i - 1])) and ema_v[i] > ema_v[i - 1])
        vol_ok = (use_vol < 0.5) or ((not np.isnan(vol_r[i])) and vol_r[i] <= vol_max)
        gap_ok = (use_gap < 0.5) or ((not np.isnan(gap_atr[i])) and gap_atr[i] <= gap_max)

        signal = (i >= start and enable_ov > 0.5 and core_open and trend_ok and wae_ok[i] and rsi_ok
                  and htf_pass and slope_ok and vol_ok and gap_ok and not campaign_live)
        if signal:
            a_i = atr_v[i] if not np.isnan(atr_v[i]) else 0.0
            risk_dist = max(a_i * atr_stop_mult, TICK)
            risk_cash = min(capital * risk_pct / 100.0, risk_cap)
            core_cost = core_qty * core_px if core_open else 0.0
            gross_room = max(capital * gross_pct / 100.0 - core_cost, 0.0)
            budget = min(capital * notional_pct / 100.0, gross_room)
            q = math.floor(min(risk_cash / risk_dist, budget / ci))
            q1 = math.floor(q / 3.0)
            q3 = q - 2 * q1
            if q >= min_ov_qty and q1 >= 1 and q3 >= 1:
                ov_entry = ci
                ov_risk = risk_dist
                ov_init_stop = ci - risk_dist
                ov_t3_stop = ov_init_stop
                ov_entry_bar = i
                ov_hx_sent = False
                be_armed = False
                trailing = False
                t_pend[0] = True; t_pend[1] = True; t_pend[2] = True
                t_pend_qty[0] = q1; t_pend_qty[1] = q1; t_pend_qty[2] = q3
                t_stop[0] = ov_init_stop; t_stop[1] = ov_init_stop; t_stop[2] = ov_init_stop
                t_lim[0] = ci + risk_dist * t1r
                t_lim[1] = ci + risk_dist * t2r
                t_lim[2] = ci + risk_dist * t3r

        if campaign_live and (not np.isnan(ov_entry)) and not ov_hx_sent:
            if t_qty[2] > 0 and i > ov_entry_bar:
                if use_be > 0.5 and hi >= ov_entry + ov_risk * be_r:
                    be_armed = True
                    ov_t3_stop = max(ov_t3_stop, ov_entry)
                if hi >= ov_entry + ov_risk * trail_start_r:
                    trailing = True
                if trailing:
                    ov_t3_stop = max(ov_t3_stop, hi - atr_v[i] * atr_trail_mult)
                t_stop[2] = ov_t3_stop

        trend_hx = hx_trend > 0.5 and not trend_ok
        mom_hx = hx_mom > 0.5 and (wae_dd[i] or ((not np.isnan(rsi_v[i])) and rsi_v[i] <= rsi_hx))
        orphan_hx = flatten_orphan > 0.5 and ov_open and not core_open
        if ov_open and (not ov_hx_sent) and (trend_hx or mom_hx or orphan_hx):
            for k in range(3):
                if t_qty[k] > 0:
                    t_pend_close[k] = True
                t_stop[k] = np.nan
                t_lim[k] = np.nan
            ov_hx_sent = True

        core_open_prev = core_qty > 0

    return (equity, exposure, tr_kind[:ntr], tr_ei[:ntr], tr_xi[:ntr], tr_qty[:ntr],
            tr_epx[:ntr], tr_xpx[:ntr], tr_pnl[:ntr])


def full_params(p):
    q = dict(DEFAULTS)
    q.update(p)
    return q


def backtest(asset, p, start_date="2008-01-01"):
    p = full_params(p)
    e, a, r, wok, wdd, htf, vr, gap = indicators(asset, p)
    P = np.array([float(p[k]) for k in P_KEYS])
    res = run_engine(asset.o, asset.h, asset.l, asset.c, e, a, r, wok, wdd, htf, vr, gap,
                     asset.idx(start_date), P, CAPITAL)
    eq, expo, kind, ei, xi, qty, epx, xpx, pnl = res
    trades = pd.DataFrame(dict(kind=kind, entry_idx=ei, exit_idx=xi, qty=qty, entry_px=epx,
                               exit_px=xpx, pnl=pnl))
    return eq, expo, trades
