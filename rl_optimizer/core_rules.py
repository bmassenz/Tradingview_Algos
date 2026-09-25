"""Core-only rule experiments: EMA exit band and tightened trailing stop after a gain.

Runs the replica with the overlay off and the Pine defaults, sweeping the two rules over every
window, and writes results/core_rules.csv. Usage: .venv/bin/python core_rules.py
"""
import itertools
import os

import numpy as np
import pandas as pd

from data_loader import SYMBOLS, load
from engine import Asset, backtest
from metrics import WINDOWS, window_metrics
from pine_defaults import load_defaults

W = dict(WINDOWS, RECENT=("2020-01-01", "2026-12-31"), FULL=("2008-01-01", "2026-12-31"))
OUT = os.path.join(os.path.dirname(__file__), "results", "core_rules.csv")


def run(assets, base, **over):
    p = dict(base); p.update(over)
    rows = []
    for s, a in assets.items():
        eq, _, tr = backtest(a, p)
        for w in ("IS", "OOS", "HOLDOUT", "RECENT", "FULL"):
            m = window_metrics(a, eq, tr, *W[w])
            rows.append(dict(asset=s, window=w, pnl_per_yr=round(m["pnl_annual"]), sharpe=round(m["sharpe"], 3),
                             sortino=round(m["sortino"], 3), max_dd_pct=round(100 * m["max_dd"], 1),
                             tv_dd_pct=round(100 * m["tv_max_dd"], 1), win=round(100 * m["win_rate"], 1),
                             pf=round(m["pf"], 2), trades=m["trades"], **over))
    return rows


def main():
    base = load_defaults(); base["enableOverlay"] = 0
    assets = {s: Asset(s, load(s)) for s in SYMBOLS}
    rows = []
    bands = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0]
    trigs = [0.0, 10.0, 20.0, 30.0, 50.0]
    tights = [5.0, 7.5, 10.0]
    for b in bands:
        rows += run(assets, base, emaExitBandPct=b, trailTightenTriggerPct=0.0, trailTightPct=15.25)
    for t, tp in itertools.product(trigs[1:], tights):
        rows += run(assets, base, emaExitBandPct=0.0, trailTightenTriggerPct=t, trailTightPct=tp)
    for b, t, tp in itertools.product([1.0, 2.0, 3.0], [20.0, 30.0], [7.5, 10.0]):
        rows += run(assets, base, emaExitBandPct=b, trailTightenTriggerPct=t, trailTightPct=tp)
    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)
    pd.set_option("display.width", 250)
    # summary: per setting, mean over assets of FULL Sharpe / max DD / pnl, worst asset DD, and the three-window minimum Sharpe
    key = ["emaExitBandPct", "trailTightenTriggerPct", "trailTightPct"]
    full = df[df.window == "FULL"].groupby(key).agg(sharpe=("sharpe", "mean"), max_dd=("max_dd_pct", "mean"),
                                                    worst_dd=("max_dd_pct", "max"), pnl=("pnl_per_yr", "sum"), trades=("trades", "sum"))
    oos = df[df.window.isin(["OOS", "HOLDOUT"])].groupby(key).agg(min_sharpe_oos_ho=("sharpe", "min"), min_pnl_oos_ho=("pnl_per_yr", "min"))
    summ = full.join(oos).reset_index().sort_values("max_dd")
    print(summ.round(2).to_string(index=False))
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
