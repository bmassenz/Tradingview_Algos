# TradingView webhook for Trend-Core Professional on tastytrade

Receives the alerts that `trend_core_professional.pine` emits on order fills and places the matching
equity market orders on tastytrade. It trades your tastytrade **sandbox (certification) account** only,
which is the posture this estate allows for tastytrade: read, alert and simulate. The service refuses
to start with `TASTYTRADE_SANDBOX_MODE=false`; live order placement is not implemented and would need
the account model revised first.

## What it does

| Alert event from the script | Order |
|---|---|
| `core_entry` | BUY_TO_OPEN, market, day, qty from the alert |
| `core_ema_exit`, `core_stop` | SELL_TO_CLOSE, market, day, qty = min(alert qty, shares held) |

Every alert is checked for the shared secret, the symbol allow-list (`SPY,QQQ,SMH`), a per-order
quantity cap, and duplicates (same body within 15 minutes). An entry is ignored while a long position
already exists; an exit is ignored when nothing is held. Orders go through tastytrade's dry run first
and are submitted only when `DRY_RUN=false`. Everything is appended to `journal.jsonl`.

The strategy fills at the next bar's open, so entry and EMA-exit alerts arrive at the open of the
following session and the market order goes in right then; the trailing stop fills intrabar and its
alert arrives when TradingView registers the fill. With about two trades a year per symbol, expect a
quiet service.

## 1. Credentials (sandbox)

tastytrade uses OAuth. In tastytrade's web app open My Profile > API > OAuth applications, create an
application for the **sandbox (certification)** environment, and generate a personal grant. Put the
application secret, the refresh token and your sandbox account number in `.env` (copy `.env.example`),
together with a webhook secret (`openssl rand -hex 32`). Never commit `.env`.

```bash
cd webhook
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env    # then fill it in
.venv/bin/python scripts/check_connection.py SPY   # balances, positions, one dry-run order
.venv/bin/python -m pytest -q tests
```

## 2. Run it

```bash
.venv/bin/uvicorn app.server:create_app --factory --host 0.0.0.0 --port 8000
# or
docker build -t trendcore-webhook . && docker run --env-file .env -p 8000:8000 trendcore-webhook
```

TradingView only posts to public HTTPS URLs on ports 80 or 443. For a first paper run the simplest
route is a tunnel in front of the local server (for example `cloudflared tunnel --url http://localhost:8000`,
which prints a public URL); for anything longer than a test, deploy the container behind TLS on a host
that stays up during market hours.

Endpoints: `POST /tradingview` (the alert), `GET /health`, `GET /account` (sandbox balances and
positions), `GET /journal?n=50`.

## 3. The TradingView alert

On each symbol's chart with the strategy added and its per-symbol inputs set (see the Pine header):
create an alert, Condition = the strategy, trigger = **Order fills only**, Expiration = open-ended,
Notifications > Webhook URL = `https://<your host>/tradingview`, and the Message exactly:

```
{"secret":"<WEBHOOK_SECRET>","alert":{{strategy.order.alert_message}}}
```

TradingView replaces the placeholder with the JSON the script attached to the order, so the body
becomes `{"secret":"...","alert":{"event":"core_entry","symbol":"SPY",...}}`. One alert per chart;
three charts for the basket. Alerts stop if the chart's script is changed, so recreate them after
any edit.

## 4. Going from dry run to sandbox orders

Start with `DRY_RUN=true`: the journal shows every alert and tastytrade's dry-run verdict (buying
power effect, warnings, errors) without an order. When that looks right, set `DRY_RUN=false` and the
same alerts submit market orders to the sandbox account. Reconcile fills against TradingView's list
of trades after each one; the journal keeps the TradingView order id and fill price next to the
tastytrade order id.

## Safety summary

- Sandbox only, enforced in `app/config.py`; no code path reaches a live account.
- Secret in the body (TradingView cannot send headers), compared in constant time.
- Symbol allow-list, quantity cap, duplicate suppression, exits clamped to shares held.
- Two-stage placement (dry run, then submit); reads retried with backoff, order placement never retried.
