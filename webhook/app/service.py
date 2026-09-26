"""Turn a verified alert into a sandbox order, with idempotency and a JSONL journal."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

from .broker import Broker
from .config import Settings
from .models import Alert, parse_body

log = logging.getLogger("webhook.service")


class Rejected(Exception):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


@dataclass
class Outcome:
    accepted: bool
    action: str | None = None
    symbol: str | None = None
    qty: str | None = None
    submitted: bool = False
    order_id: str | None = None
    status: str | None = None
    note: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class AlertService:
    def __init__(self, settings: Settings, broker: Broker):
        self.s = settings
        self.broker = broker
        self._seen: dict[str, float] = {}

    # ---------------- journal ----------------
    def journal(self, kind: str, **data) -> None:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kind": kind, **data}
        with Path(self.s.journal_path).open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    # ---------------- idempotency ----------------
    def _duplicate(self, raw: bytes) -> bool:
        now = time.time()
        for k, t in list(self._seen.items()):
            if now - t > self.s.dedupe_window_seconds:
                del self._seen[k]
        key = hashlib.sha256(raw).hexdigest()
        if key in self._seen:
            return True
        self._seen[key] = now
        return False

    # ---------------- main path ----------------
    async def handle(self, raw: bytes) -> Outcome:
        try:
            secret, alert = parse_body(raw)
        except ValueError as e:
            self.journal("rejected", reason=str(e), body=raw[:500].decode("utf-8", "replace"))
            raise Rejected(400, str(e)) from e
        if not secret or not hmac.compare_digest(secret, self.s.webhook_secret):
            self.journal("rejected", reason="bad secret", symbol=alert.symbol, event=alert.event)
            raise Rejected(401, "bad secret")
        if alert.symbol not in self.s.symbols:
            self.journal("ignored", reason="symbol not allowed", symbol=alert.symbol, event=alert.event)
            return Outcome(False, symbol=alert.symbol, note=f"symbol {alert.symbol} not in ALLOWED_SYMBOLS")
        if alert.side is None:
            self.journal("ignored", reason="unknown event", symbol=alert.symbol, event=alert.event)
            return Outcome(False, symbol=alert.symbol, note=f"event {alert.event} not handled")
        if self._duplicate(raw):
            self.journal("ignored", reason="duplicate", symbol=alert.symbol, event=alert.event)
            return Outcome(False, symbol=alert.symbol, note="duplicate alert")
        return await self._route(alert)

    async def _route(self, alert: Alert) -> Outcome:
        qty = alert.qty
        held = await self.broker.position_qty(alert.symbol)
        if alert.side == "entry":
            if held > 0:
                self.journal("ignored", reason="already long", symbol=alert.symbol, held=str(held))
                return Outcome(False, "BUY_TO_OPEN", alert.symbol, str(qty), note=f"already long {held}")
            action = "BUY_TO_OPEN"
        else:
            if held <= 0:
                self.journal("ignored", reason="no position to close", symbol=alert.symbol, held=str(held))
                return Outcome(False, "SELL_TO_CLOSE", alert.symbol, str(qty), note="no long position to close")
            action = "SELL_TO_CLOSE"
            qty = min(qty, held)  # never sell more than the broker says we hold
        if qty > self.s.max_qty_per_order:
            self.journal("rejected", reason="qty above MAX_QTY_PER_ORDER", symbol=alert.symbol, qty=str(qty))
            raise Rejected(422, f"qty {qty} above MAX_QTY_PER_ORDER={self.s.max_qty_per_order}")
        qty = Decimal(int(qty))  # whole shares
        res = await self.broker.place_market(alert.symbol, qty, action, dry_run=self.s.dry_run)
        out = Outcome(not res.errors, action, alert.symbol, str(qty), res.submitted, res.order_id, res.status,
                      "dry run only" if self.s.dry_run else None, res.warnings, res.errors)
        self.journal("order", event=alert.event, tv_order_id=alert.id, tv_fill_price=str(alert.fill_price), **asdict(out))
        log.info("%s %s %s -> submitted=%s id=%s status=%s errors=%s", action, qty, alert.symbol, res.submitted, res.order_id, res.status, res.errors)
        return out
