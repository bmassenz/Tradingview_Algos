# TradingView Strategy Tester automation

`run_tester.js` opens TradingView in headless Chromium, creates a fresh chart layout, pastes
`trend_core_wae_professional.pine` into the Pine Editor, adds it to a daily chart, and reads the
Strategy Tester report for SPY, QQQ, SMH and IWM. It writes `tester_results.json` and two screenshots
per symbol (`tester_<SYMBOL>.png`, `tester_<SYMBOL>_list_of_trades.png`) next to the script.
`RESULTS.md` holds the 2026-09-25 run compared with the Python replica.

## 1. Supply a signed-in TradingView session

Adding a script to a chart requires a signed-in account. The runner reads the browser session
cookies from two environment variables:

| Variable | Cookie |
|---|---|
| `TV_SESSIONID` | `sessionid` |
| `TV_SESSIONID_SIGN` | `sessionid_sign` |

To find them: sign in to tradingview.com in Chrome, open DevTools (F12), go to
Application > Storage > Cookies > `https://www.tradingview.com`, and copy the two values.
In a Claude cloud session, add them in the environment's settings (cloud environment menu in
the session title bar, then Edit) as environment variables; a new session picks them up.
Never paste them into a chat. They are full-account credentials: sign out of TradingView
afterwards to invalidate them.

## 2. Prepare the container (Claude cloud environment)

```bash
apt-get update && apt-get install -y libnss3-tools          # certutil, so Chromium trusts the container proxy
certutil -N -d sql:$HOME/.pki/nssdb --empty-password         # only if $HOME/.pki/nssdb does not exist yet
certutil -A -d sql:$HOME/.pki/nssdb -n ccr-agent-proxy -t "C,," -i /root/.ccr/agent-proxy-ca.crt
cd rl_optimizer/tv_verify && npm i playwright@1.56 ws@8
```

## 3. Run

```bash
CHROME=/opt/pw-browsers/chromium-1194/chrome-linux/chrome node run_tester.js   # in the Claude container
node run_tester.js                                                              # elsewhere, with Playwright's Chromium
TV_SYMBOLS=AMEX:SPY node run_tester.js                                          # one symbol
TV_LAYOUT_NAME="my check" node run_tester.js                                    # name of the layout it creates
```

Run it in the background with the output in a log file; a full run takes about five minutes.
The log prints `signed in: true|false`, the chart legend with the strategy's status, and one
`TESTER <symbol>: {...}` line per symbol. If "signed in" is false, the cookies are stale.

## What the run touches in the account

- It creates one chart layout per run, named `tv_verify <date>` unless `TV_LAYOUT_NAME` is set, and
  works only inside it. Delete it from Manage layouts afterwards. It never opens a saved layout.
- "Add to chart" stores the pasted source as the account's unsaved Pine Editor draft (TradingView
  does this for any unsaved script). No saved script is created or changed.
- The strategy runs with the defaults from the `.pine` file. Nothing is changed in the inputs.

## How it gets past the container proxy

- `bridge.js` `install` routes the chart's websockets through the container's HTTPS proxy via
  Playwright's `routeWebSocket` and a Node `ws` client over a CONNECT tunnel. Chromium's own websocket
  handshakes come back downgraded (426/400) through that proxy, while a plain client's succeed.
- `bridge.js` `installRestFix` serves the Pine-facade REST calls whose path contains a `;`
  (`/pine-facade/translate/USER;<hash>/...`) through the same tunnel. The proxy rejects those
  requests from Chromium with `403 request rejected: path contains matrix parameter separator`;
  without the fix the compiled script never reaches the chart and the strategy shows
  "Error: cannot compile script" in the legend, so the tester keeps reporting another strategy.
- Without `HTTPS_PROXY` set, neither piece is installed.

## Reading the report

The tester's Overview is a single scrolling page: Key stats (Total PnL, Max drawdown, Profitable
trades, Profit factor), Performance analysis (Breakdown with P&L by signal, Growth and decline with
max drawdown as % of initial capital), and Trades analysis (total trades, winners, losers). The
second header icon switches to the List of trades, oldest first, which gives the first trade date.
The date range button in the report header shows the first bar the chart loaded; a Premium account
loads SPY from 1993, so the weekly WAE filter is warm long before the 2008-01-01 "Trade From" default.
