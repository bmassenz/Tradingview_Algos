"""Download split-adjusted (not dividend-adjusted) daily bars, matching TradingView's default chart data.

Validated against TradingView's own feed (first open, high, low, last close) for AMEX:SPY,
NASDAQ:QQQ, NASDAQ:SMH and AMEX:IWM. History starts in 2000 so slow indicators
(including the weekly HTF WAE) are fully warmed up before the 2008 evaluation start.
"""
import os
import pandas as pd

SYMBOLS = {"SPY": "AMEX:SPY", "QQQ": "NASDAQ:QQQ", "SMH": "NASDAQ:SMH", "IWM": "AMEX:IWM"}
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def download(start="2000-01-01", end=None):
    import yfinance as yf
    os.makedirs(DATA_DIR, exist_ok=True)
    for s in SYMBOLS:
        d = yf.download(s, start=start, end=end, auto_adjust=False, progress=False, multi_level_index=False)
        d = d[["Open", "High", "Low", "Close", "Volume"]].dropna()
        d.index.name = "Date"
        d.to_csv(os.path.join(DATA_DIR, f"{s}.csv"))


def load(symbol):
    d = pd.read_csv(os.path.join(DATA_DIR, f"{symbol}.csv"), index_col=0, parse_dates=True)
    return d


if __name__ == "__main__":
    download()
    for s in SYMBOLS:
        d = load(s)
        print(s, len(d), d.index[0].date(), d.index[-1].date())
