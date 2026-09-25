"""Per-window metrics and the cross-asset composite reward."""
import numpy as np

from engine import CAPITAL

WINDOWS = {
    # In-sample: covers the 2008 crash, 2011, 2015-16 and 2018 drawdowns
    "IS": ("2008-01-01", "2019-12-31"),
    # Out-of-sample used inside the reward (COVID crash, 2021 melt-up, 2022 bear)
    "OOS": ("2020-01-01", "2022-12-31"),
    # Final holdout: never seen by the optimizer, only reported
    "HOLDOUT": ("2023-01-01", "2026-12-31"),
}

SHARPE_CAP = 3.0
SORTINO_CAP = 5.0
PF_CAP = 10.0


def window_metrics(asset, eq, trades, start, end):
    a = asset.idx(start)
    b = int(np.searchsorted(asset.dates.values, np.datetime64(end), side="right"))
    seg = eq[a - 1:b]
    pnl_daily = np.diff(seg)
    r = pnl_daily / CAPITAL
    years = max(len(r) / 252.0, 1e-9)
    total_pnl = seg[-1] - seg[0]
    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    sharpe = r.mean() / sd * np.sqrt(252) if sd > 0 else 0.0
    dd_dev = np.sqrt(np.mean(np.minimum(r, 0.0) ** 2))
    sortino = r.mean() / dd_dev * np.sqrt(252) if dd_dev > 0 else 0.0
    peak = np.maximum.accumulate(seg)
    max_dd = float(np.max(peak - seg)) / CAPITAL  # drawdown of the fixed-size book, marked to market daily
    # TradingView's "Max drawdown", reproduced to within 0.1% on SPY/QQQ/SMH/IWM (tv_verify/RESULTS.md):
    # the peak is the running high of closed-trade equity, the trough is closed-trade equity plus any
    # open LOSS at the bar's low, and open profit is never counted. max_dd above also counts open
    # profit that is given back before a trade closes, so it is the larger and more conservative number.
    n = len(asset.c)
    realized = np.zeros(n)
    open_low = np.zeros(n)
    for e, x, q, px, pl in zip(trades.entry_idx.to_numpy(), trades.exit_idx.to_numpy(), trades.qty.to_numpy(),
                               trades.entry_px.to_numpy(), trades.pnl.to_numpy()):
        realized[x:] += pl
        if x > e:
            open_low[e:x] += (asset.l[e:x] - px) * q
    rs = realized[a - 1:b]
    tv_dd_usd = float(np.max(np.maximum.accumulate(rs) - (rs + np.minimum(open_low[a - 1:b], 0.0))))
    t = trades[(trades.exit_idx >= a) & (trades.exit_idx < b)]
    ov = t[t.kind > 0]
    wins = t.pnl[t.pnl > 0].sum()
    losses = -t.pnl[t.pnl <= 0].sum()
    pf = PF_CAP if losses <= 0 and wins > 0 else (wins / losses if losses > 0 else 0.0)
    ov_w = ov.pnl[ov.pnl > 0].sum()
    ov_l = -ov.pnl[ov.pnl <= 0].sum()
    return dict(
        pnl=total_pnl,
        pnl_annual=total_pnl / years,
        cagr_on_capital=total_pnl / CAPITAL / years,
        sharpe=float(sharpe),
        sortino=float(sortino),
        max_dd=max_dd,
        tv_max_dd=tv_dd_usd / CAPITAL,
        tv_max_dd_usd=tv_dd_usd,
        trades=int(len(t)),
        win_rate=float((t.pnl > 0).mean()) if len(t) else 0.0,
        pf=float(min(pf, PF_CAP)),
        overlay_trades=int(len(ov)),
        overlay_campaigns=int(ov.entry_idx.nunique()),
        overlay_pnl=float(ov.pnl.sum()),
        overlay_pf=float(min(ov_w / ov_l, PF_CAP)) if ov_l > 0 else (PF_CAP if ov_w > 0 else 0.0),
        overlay_win_rate=float((ov.pnl > 0).mean()) if len(ov) else 0.0,
        years=years,
    )


def asset_reward(m):
    """User's composite, with signs corrected so better performance raises the reward."""
    return (
        m["pnl_annual"] / 4000.0
        + min(m["sharpe"], SHARPE_CAP) / 2.0
        + min(m["sortino"], SORTINO_CAP) / 2.0
        + m["win_rate"] / 0.60
        + min(m["pf"], PF_CAP) / 10.0
        - m["max_dd"] / 0.30 * 2.0
    )


def composite_reward(per_asset, min_campaigns_is=10):
    """per_asset: {sym: {"IS": metrics, "OOS": metrics}} -> (reward, breakdown)."""
    syms = list(per_asset)
    r_is = np.array([asset_reward(per_asset[s]["IS"]) for s in syms])
    r_oos = np.array([asset_reward(per_asset[s]["OOS"]) for s in syms])
    base = r_is.mean()
    # OOS penalty: degradation from IS to OOS, plus a hard hit for any asset losing money OOS
    oos_pen = 0.5 * max(0.0, r_is.mean() - r_oos.mean())
    oos_pen += sum(1.0 for s in syms if per_asset[s]["OOS"]["pnl"] < 0)
    oos_pen += 0.5 * max(0.0, -r_oos.min())
    # Cross-asset dispersion: spread of rewards plus the worst asset's shortfall from the mean
    disp_pen = 0.5 * r_is.std() + 0.5 * r_oos.std()
    disp_pen += 0.5 * (r_is.mean() - r_is.min()) + 0.5 * (r_oos.mean() - r_oos.min())
    # Keep the overlay a live part of the strategy: require a minimum number of campaigns per asset
    act_pen = sum(0.05 * max(0, min_campaigns_is - per_asset[s]["IS"]["overlay_campaigns"]) for s in syms)
    # Overlay expectancy: the win-rate term alone rewards tiny targets with negative expectancy
    # after costs, so any asset whose overlay loses money IS or OOS is penalised.
    ov_pen = sum(0.5 for s in syms for w in ("IS", "OOS") if per_asset[s][w]["overlay_pnl"] < 0)
    reward = base - oos_pen - disp_pen - act_pen - ov_pen
    return float(reward), dict(base=float(base), oos_pen=float(oos_pen), disp_pen=float(disp_pen),
                               act_pen=float(act_pen), ov_pen=float(ov_pen), r_is=r_is.tolist(), r_oos=r_oos.tolist())
