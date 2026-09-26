import json
import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("WEBHOOK_SECRET", "test-secret-0123456789")
os.environ["WEBHOOK_ENV_FILE"] = "/nonexistent"

from app.broker import OrderResult  # noqa: E402
from app.config import Settings  # noqa: E402
from app.server import create_app  # noqa: E402

SECRET = "test-secret-0123456789"


class FakeBroker:
    def __init__(self, held=None):
        self.held = held or {}
        self.orders = []

    async def position_qty(self, symbol):
        return Decimal(self.held.get(symbol, 0))

    async def place_market(self, symbol, qty, action, dry_run):
        self.orders.append((symbol, qty, action, dry_run))
        return OrderResult(not dry_run, None if dry_run else "42", None if dry_run else "Received", "-1000", [], [])

    async def snapshot(self):
        return {"account": "TEST", "sandbox": True, "positions": []}


def make(tmp_path, held=None, **over):
    s = Settings(webhook_secret=SECRET, tastytrade_account_number="TEST", journal_path=str(tmp_path / "j.jsonl"), **over)
    b = FakeBroker(held)
    return TestClient(create_app(s, b)), b


def alert(event="core_entry", symbol="SPY", qty=34, nested=True, secret=SECRET):
    inner = {"event": event, "symbol": symbol, "id": "Core", "action": "buy", "qty": str(qty), "fill_price": "771.35"}
    return json.dumps({"secret": secret, "alert": inner} if nested else {"secret": secret, **inner})


def test_entry_dry_run(tmp_path):
    c, b = make(tmp_path)
    r = c.post("/tradingview", content=alert())
    assert r.status_code == 200 and r.json()["accepted"] and r.json()["note"] == "dry run only"
    assert b.orders == [("SPY", Decimal(34), "BUY_TO_OPEN", True)]


def test_entry_submits_when_dry_run_off(tmp_path):
    c, b = make(tmp_path, dry_run=False)
    r = c.post("/tradingview", content=alert(nested=False))
    assert r.json()["submitted"] and r.json()["order_id"] == "42"
    assert b.orders[0][3] is False


def test_bad_secret(tmp_path):
    c, b = make(tmp_path)
    assert c.post("/tradingview", content=alert(secret="wrong")).status_code == 401
    assert c.post("/tradingview", content=json.dumps({"alert": {"event": "core_entry", "symbol": "SPY", "qty": 1}})).status_code == 401
    assert b.orders == []


def test_exit_clamps_to_held(tmp_path):
    c, b = make(tmp_path, held={"QQQ": 30}, dry_run=False)
    r = c.post("/tradingview", content=alert("core_stop", "QQQ", qty=36))
    assert r.json()["qty"] == "30" and b.orders == [("QQQ", Decimal(30), "SELL_TO_CLOSE", False)]


def test_exit_without_position_is_ignored(tmp_path):
    c, b = make(tmp_path)
    r = c.post("/tradingview", content=alert("core_ema_exit", "SMH", qty=49))
    assert r.status_code == 200 and not r.json()["accepted"] and "no long position" in r.json()["note"] and b.orders == []


def test_entry_when_already_long_is_ignored(tmp_path):
    c, b = make(tmp_path, held={"SPY": 34})
    r = c.post("/tradingview", content=alert())
    assert not r.json()["accepted"] and "already long" in r.json()["note"] and b.orders == []


def test_duplicate_alert_ignored(tmp_path):
    c, b = make(tmp_path)
    body = alert()
    assert c.post("/tradingview", content=body).json()["accepted"]
    assert c.post("/tradingview", content=body).json()["note"] == "duplicate alert"
    assert len(b.orders) == 1


def test_symbol_not_allowed_and_unknown_event(tmp_path):
    c, b = make(tmp_path)
    assert "not in ALLOWED_SYMBOLS" in c.post("/tradingview", content=alert(symbol="IWM")).json()["note"]
    assert "not handled" in c.post("/tradingview", content=alert(event="overlay_t1_entry")).json()["note"]
    assert b.orders == []


def test_qty_cap_and_bad_body(tmp_path):
    c, b = make(tmp_path, max_qty_per_order=100)
    assert c.post("/tradingview", content=alert(qty=101)).status_code == 422
    assert c.post("/tradingview", content=b"not json").status_code == 400
    assert c.post("/tradingview", content=json.dumps({"secret": SECRET, "alert": {"event": "core_entry", "symbol": "SPY", "qty": "-3"}})).status_code == 400
    assert b.orders == []


def test_exchange_prefixed_symbol_and_string_alert(tmp_path):
    c, b = make(tmp_path)
    body = json.dumps({"secret": SECRET, "alert": json.dumps({"event": "core_entry", "symbol": "AMEX:spy", "qty": 5})})
    assert c.post("/tradingview", content=body).json()["symbol"] == "SPY"


def test_journal_and_health(tmp_path):
    c, b = make(tmp_path)
    c.post("/tradingview", content=alert())
    j = c.get("/journal").json()
    assert j and j[-1]["kind"] == "order" and j[-1]["symbol"] == "SPY"
    assert c.get("/health").json() == {"ok": True, "sandbox": True, "dry_run": True, "symbols": ["QQQ", "SMH", "SPY"]}


def test_live_mode_is_refused():
    with pytest.raises(Exception):
        Settings(webhook_secret=SECRET, tastytrade_account_number="TEST", tastytrade_sandbox_mode=False)
