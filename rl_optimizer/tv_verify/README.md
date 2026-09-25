# TradingView Strategy Tester automation

`run_tester.js` opens TradingView in headless Chromium, pastes `trend_core_wae_professional.pine`
into the Pine Editor, adds it to a daily chart, and prints the Strategy Tester panel for
SPY, QQQ, SMH and IWM.

Adding a script to a chart requires a signed-in TradingView account. Supply the browser
session cookies as environment variables `TV_SESSIONID` and `TV_SESSIONID_SIGN`. They are
full-account credentials: treat them like a password and rotate them by signing out afterwards.

```bash
cd rl_optimizer/tv_verify && npm i playwright@1.56 ws@8
CHROME=/opt/pw-browsers/chromium-1194/chrome-linux/chrome node run_tester.js   # inside the Claude container
node run_tester.js                                                              # elsewhere, with Playwright's Chromium
```

`bridge.js` routes the chart's websockets through the container's HTTPS proxy via Playwright's
`routeWebSocket`, because Chromium's own websocket handshakes are downgraded by that proxy.
Without `HTTPS_PROXY` set, the bridge is not installed.
