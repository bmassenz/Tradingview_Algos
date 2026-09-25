"""Regenerate the per-window metrics tables (adds TradingView-definition drawdown) without re-running selection."""
import json
import os

import pandas as pd

from data_loader import SYMBOLS, load
from engine import Asset
from select_and_report import OUT, evaluate, table
from space import ORIGINAL_RAW, to_strategy


def main(tag="r3"):
    sel = json.load(open(os.path.join(OUT, f"{tag}_selection.json")))
    assets = {s: Asset(s, load(s)) for s in SYMBOLS}
    wins = ("IS", "OOS", "HOLDOUT", "FULL")
    for name, raw in (("chosen", sel["chosen_raw"]), ("original", ORIGINAL_RAW)):
        p = to_strategy(raw)
        p.pop("_raw")
        t = table(evaluate(assets, p, wins))
        t.to_csv(os.path.join(OUT, f"{tag}_{name}_metrics.csv"), index=False)
        pd.set_option("display.width", 250)
        print(name)
        print(t[["asset", "window", "pnl_per_yr", "sharpe", "max_dd_pct", "tv_dd_pct", "trades", "pf"]].to_string(index=False))


if __name__ == "__main__":
    main()
