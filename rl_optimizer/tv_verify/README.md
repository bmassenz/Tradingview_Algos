# TradingView Strategy Tester automation

`run_tester.js` opens TradingView in headless Chromium, pastes `trend_core_wae_professional.pine`
into the Pine Editor, adds it to a daily chart, and prints the Strategy Tester panel for
SPY, QQQ, SMH and IWM (screenshots land next to the script).

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
apt-get install -y libnss3-tools                       # certutil, so Chromium trusts the container proxy
certutil -A -d sql:$HOME/.pki/nssdb -n ccr-agent-proxy -t "C,," -i /root/.ccr/agent-proxy-ca.crt
cd rl_optimizer/tv_verify && npm i playwright@1.56 ws@8
```

## 3. Run

```bash
CHROME=/opt/pw-browsers/chromium-1194/chrome-linux/chrome node run_tester.js   # in the Claude container
node run_tester.js                                                              # elsewhere, with Playwright's Chromium
TV_SYMBOLS=AMEX:SPY node run_tester.js                                          # one symbol
```

Compare the printed Strategy Tester numbers with `../README.md`. Load history from 2006 or earlier
so the weekly WAE filter is warm by 2008; the strategy's "Trade From" input defaults to 2008-01-01.

## How it gets past the container proxy

`bridge.js` routes the chart's websockets through the container's HTTPS proxy via Playwright's
`routeWebSocket` and a Node `ws` client over a CONNECT tunnel. Chromium's own websocket
handshakes come back downgraded (426/400) through that proxy, while a plain client's succeed.
Without `HTTPS_PROXY` set, the bridge is not installed.
