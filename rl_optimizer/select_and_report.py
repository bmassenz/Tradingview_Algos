"""Pick a robust parameter set from PPO logs, then score it on every window, including the holdout.

Selection never looks at the HOLDOUT window: candidates are ranked by their composite
reward averaged over a neighbourhood of perturbed parameters (penalising sharp optima).
"""
import argparse
import glob
import json
import os

import numpy as np
import pandas as pd

from data_loader import SYMBOLS, load
from engine import CAPITAL, Asset, backtest
from metrics import WINDOWS, composite_reward, window_metrics
from space import ORIGINAL_RAW, SPACE, decode, encode, to_strategy

OUT = os.path.join(os.path.dirname(__file__), "results")
ALL_WINDOWS = dict(WINDOWS, RECENT=("2020-01-01", "2026-12-31"), FULL=("2008-01-01", "2026-12-31"))


def evaluate(assets, p, windows):
    per = {}
    for s, a in assets.items():
        eq, _, tr = backtest(a, p)
        per[s] = {w: window_metrics(a, eq, tr, *ALL_WINDOWS[w]) for w in windows}
    return per


def neighbourhood_score(assets, raw, rng, n=24, sigma=0.08):
    x0 = encode(raw)
    bool_mask = np.array([k == "bool" for *_, k in SPACE])
    scores = []
    for _ in range(n):
        x = x0 + rng.normal(0, sigma, x0.size)
        x[bool_mask] = x0[bool_mask]
        p = decode(x)
        p.pop("_raw")
        scores.append(composite_reward(evaluate(assets, p, ("IS", "OOS")))[0])
    return float(np.mean(scores)), float(np.std(scores))


def buy_and_hold(asset, start, end):
    a = asset.idx(start)
    b = int(np.searchsorted(asset.dates.values, np.datetime64(end), side="right"))
    # Constant $26k exposure (daily rebalanced), matching the strategy's fixed paper sizing
    px = asset.c[a - 1:b]
    r = np.diff(px) / px[:-1]
    eq = CAPITAL + np.concatenate([[0.0], np.cumsum(r * CAPITAL)])
    peak = np.maximum.accumulate(eq)
    return dict(pnl_annual=(eq[-1] - eq[0]) / (len(r) / 252), sharpe=r.mean() / r.std(ddof=1) * np.sqrt(252),
                max_dd=float(np.max(peak - eq)) / CAPITAL)


def gates(per):
    g = {}
    syms = list(per)
    g["G1 PnL>0 in IS/OOS/HOLDOUT, every asset"] = all(per[s][w]["pnl"] > 0 for s in syms for w in ("IS", "OOS", "HOLDOUT"))
    g["G2 PF>=1.2 in every window, every asset"] = all(per[s][w]["pf"] >= 1.2 for s in syms for w in ("IS", "OOS", "HOLDOUT"))
    g["G3 MaxDD<=30% of capital in every window"] = all(per[s][w]["max_dd"] <= 0.30 for s in syms for w in ("IS", "OOS", "HOLDOUT"))
    g["G4 Sharpe>=0.4 IS and 2020-26, every asset"] = all(per[s][w]["sharpe"] >= 0.4 for s in syms for w in ("IS", "RECENT"))
    sh = np.array([per[s]["RECENT"]["sharpe"] for s in syms])
    g["G5 worst 2020-26 Sharpe >= 0.4 x median"] = bool(sh.min() >= 0.4 * np.median(sh))
    g["G6 overlay PnL>0 over 2008-26, every asset"] = all(per[s]["FULL"]["overlay_pnl"] > 0 for s in syms)
    return g


def table(per):
    rows = []
    for s in per:
        for w in ("IS", "OOS", "HOLDOUT", "FULL"):
            m = per[s][w]
            rows.append(dict(asset=s, window=w, pnl_per_yr=round(m["pnl_annual"]), sharpe=round(m["sharpe"], 2),
                             sortino=round(m["sortino"], 2), max_dd_pct=round(100 * m["max_dd"], 1), tv_dd_pct=round(100 * m["tv_max_dd"], 1),
                             win_rate=round(100 * m["win_rate"], 1), pf=round(m["pf"], 2), trades=m["trades"],
                             ov_campaigns=m["overlay_campaigns"], ov_pnl=round(m["overlay_pnl"]),
                             ov_pf=round(m["overlay_pf"], 2)))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="r1")
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()
    recs = []
    for f in glob.glob(os.path.join(OUT, f"{args.tag}_s*_w*.jsonl")):
        for line in open(f):
            r = json.loads(line)
            if "error" not in r["breakdown"]:
                recs.append(r)
    recs.sort(key=lambda r: -r["reward"])
    print("evaluations:", len(recs), "best raw reward:", round(recs[0]["reward"], 3))
    # de-duplicate near-identical candidates
    top, seen = [], set()
    for r in recs:
        key = tuple(np.round(encode(r["raw"]), 1))
        if key in seen:
            continue
        seen.add(key)
        top.append(r)
        if len(top) >= args.top:
            break
    assets = {s: Asset(s, load(s)) for s in SYMBOLS}
    rng = np.random.default_rng(7)
    for r in top:
        r["nb_mean"], r["nb_std"] = neighbourhood_score(assets, r["raw"], rng)
        r["robust"] = r["nb_mean"] - 0.5 * r["nb_std"]
    top.sort(key=lambda r: -r["robust"])
    best = top[0]
    print("chosen: reward %.3f  neighbourhood mean %.3f std %.3f" % (best["reward"], best["nb_mean"], best["nb_std"]))

    wins = ("IS", "OOS", "HOLDOUT", "RECENT", "FULL")
    p_best = to_strategy(best["raw"]); p_best.pop("_raw")
    p_orig = to_strategy(ORIGINAL_RAW); p_orig.pop("_raw")
    per_best = evaluate(assets, p_best, wins)
    per_orig = evaluate(assets, p_orig, wins)
    bh = {s: {w: buy_and_hold(assets[s], *ALL_WINDOWS[w]) for w in ("IS", "OOS", "HOLDOUT", "FULL")} for s in SYMBOLS}
    out = dict(
        tag=args.tag, evaluations=len(recs), chosen_raw=best["raw"], chosen_params=p_best,
        chosen_reward=best["reward"], chosen_neighbourhood=[best["nb_mean"], best["nb_std"]],
        reward_breakdown=composite_reward({s: per_best[s] for s in per_best})[1],
        original_reward=composite_reward({s: per_orig[s] for s in per_orig})[0],
        gates_chosen=gates(per_best), gates_original=gates(per_orig),
        top_candidates=[dict(reward=r["reward"], robust=r["robust"], raw=r["raw"]) for r in top[:10]],
        buy_and_hold=bh,
    )
    json.dump(out, open(os.path.join(OUT, f"{args.tag}_selection.json"), "w"), indent=1, default=float)
    tb, to = table(per_best), table(per_orig)
    tb.to_csv(os.path.join(OUT, f"{args.tag}_chosen_metrics.csv"), index=False)
    to.to_csv(os.path.join(OUT, f"{args.tag}_original_metrics.csv"), index=False)
    pd.set_option("display.width", 250)
    print("\nCHOSEN\n", tb.to_string(index=False))
    print("\nORIGINAL (audited execution)\n", to.to_string(index=False))
    print("\nGates chosen:", json.dumps(out["gates_chosen"], indent=1))
    print("Gates original:", json.dumps(out["gates_original"], indent=1))
    print("\nChosen params:", json.dumps(p_best, indent=1))


if __name__ == "__main__":
    main()
