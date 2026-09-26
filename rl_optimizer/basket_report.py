"""Score the traded basket (basket.py) per window and judge the per-asset gates.

Writes results/basket_metrics.csv. Usage: .venv/bin/python basket_report.py
"""
import os

import numpy as np
import pandas as pd

from basket import BASKET
from data_loader import load
from engine import Asset, backtest
from metrics import WINDOWS, window_metrics
from pine_defaults import load_defaults
from select_and_report import gates

W = dict(WINDOWS, RECENT=("2020-01-01", "2026-12-31"), FULL=("2008-01-01", "2026-12-31"))
OUT = os.path.join(os.path.dirname(__file__), "results", "basket_metrics.csv")


def main():
    base = load_defaults(); base["enableOverlay"] = 0
    per, rows = {}, []
    for s, over in BASKET.items():
        a = Asset(s, load(s)); p = dict(base); p.update(over)
        eq, _, tr = backtest(a, p)
        per[s] = {w: window_metrics(a, eq, tr, *W[w]) for w in W}
        for w in ("IS", "OOS", "HOLDOUT", "RECENT", "FULL"):
            m = per[s][w]
            rows.append(dict(asset=s, window=w, settings=" ".join(f"{k}={v:g}" for k, v in over.items()) or "defaults",
                             pnl_per_yr=round(m["pnl_annual"]), sharpe=round(m["sharpe"], 2), sortino=round(m["sortino"], 2),
                             max_dd_pct=round(100 * m["max_dd"], 1), tv_dd_pct=round(100 * m["tv_max_dd"], 1),
                             win_rate=round(100 * m["win_rate"], 1), pf=round(m["pf"], 2), trades=m["trades"]))
    df = pd.DataFrame(rows); df.to_csv(OUT, index=False)
    pd.set_option("display.width", 250); print(df.to_string(index=False)); print()
    for k, v in gates(per).items():
        print(("PASS" if v else "FAIL"), k)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
