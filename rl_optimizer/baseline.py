import time, json
import pandas as pd
from data_loader import load, SYMBOLS
from engine import Asset, backtest
from metrics import WINDOWS, window_metrics, composite_reward

def evaluate(assets, p, windows=("IS", "OOS", "HOLDOUT")):
    out = {}
    for s, a in assets.items():
        eq, expo, tr = backtest(a, p)
        out[s] = {w: window_metrics(a, eq, tr, *WINDOWS[w]) for w in windows}
    return out

if __name__ == "__main__":
    assets = {s: Asset(s, load(s)) for s in SYMBOLS}
    t = time.time(); res = evaluate(assets, {}); print("first eval (jit) %.1fs" % (time.time() - t))
    t = time.time(); res = evaluate(assets, {}); print("eval %.3fs" % (time.time() - t))
    rows = []
    for s in res:
        for w in res[s]:
            m = res[s][w]; rows.append(dict(sym=s, win=w, **{k: round(v, 3) for k, v in m.items()}))
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(df[["sym","win","pnl_annual","sharpe","sortino","max_dd","win_rate","pf","trades","overlay_campaigns","overlay_pnl","overlay_pf"]].to_string(index=False))
    print(composite_reward(res))
