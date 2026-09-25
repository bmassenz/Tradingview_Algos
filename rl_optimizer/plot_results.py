"""Equity curves per asset: optimized vs original parameters vs buy-and-hold, with window shading."""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from data_loader import SYMBOLS, load
from engine import CAPITAL, Asset, backtest
from metrics import WINDOWS
from space import ORIGINAL_RAW, to_strategy

OUT = os.path.join(os.path.dirname(__file__), "results")


def main(tag):
    sel = json.load(open(os.path.join(OUT, f"{tag}_selection.json")))
    p_best = to_strategy(sel["chosen_raw"]); p_best.pop("_raw")
    p_orig = to_strategy(ORIGINAL_RAW); p_orig.pop("_raw")
    fig, axes = plt.subplots(2, 2, figsize=(14, 8), sharex=True)
    for ax, s in zip(axes.flat, SYMBOLS):
        a = Asset(s, load(s))
        i0 = a.idx("2008-01-01")
        d = a.dates[i0 - 1:]
        for p, lab, col in ((p_best, "PPO-optimized", "#1f6feb"), (p_orig, "Original defaults", "#9a6700")):
            eq, _, _ = backtest(a, p)
            ax.plot(d, (eq[i0 - 1:] - eq[i0 - 1]) / 1000, label=lab, color=col, lw=1.3)
        px = a.c[i0 - 1:]
        ax.plot(d, np.floor(CAPITAL / px[0]) * (px - px[0]) / 1000, label="Buy & hold ($26k)", color="#8c8c8c", lw=1)
        for w, col in (("OOS", "#fff4d6"), ("HOLDOUT", "#e6f4ea")):
            ax.axvspan(np.datetime64(WINDOWS[w][0]), d[-1] if w == "HOLDOUT" else np.datetime64(WINDOWS[w][1]), color=col, zorder=0)
        ax.set_title(s)
        ax.set_ylabel("Cumulative P&L ($k)")
        ax.grid(alpha=0.3)
    axes[0, 0].legend(loc="upper left", fontsize=8)
    fig.suptitle("Trend-Core WAE: fixed $26k sizing, next-open fills, costs included\n"
                 "white = in-sample 2008-19, yellow = OOS 2020-22, green = holdout 2023-26")
    fig.tight_layout()
    path = os.path.join(OUT, f"{tag}_equity_curves.png")
    fig.savefig(path, dpi=110)
    print(path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "r1")
