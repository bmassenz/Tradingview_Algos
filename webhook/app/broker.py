"""tastytrade access: one session with TTL refresh, cached account, equity market orders placed in two stages."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from .config import Settings

log = logging.getLogger("webhook.broker")

SESSION_TTL_SECONDS = 3600


@dataclass
class OrderResult:
    submitted: bool  # False when only the dry run ran
    order_id: str | None
    status: str | None
    buying_power_effect: str | None
    warnings: list[str]
    errors: list[str]


class Broker(Protocol):
    async def position_qty(self, symbol: str) -> Decimal: ...
    async def place_market(self, symbol: str, qty: Decimal, action: str, dry_run: bool) -> OrderResult: ...
    async def snapshot(self) -> dict: ...


def _retryable():
    from tastytrade.utils import TastytradeError

    return retry_if_exception_type((TastytradeError, httpx.TimeoutException, httpx.ConnectError, ConnectionResetError))


class TastytradeBroker:
    """Real broker. The session is always a sandbox session (Settings refuses anything else)."""

    def __init__(self, settings: Settings):
        self.s = settings
        self._session = None
        self._account = None
        self._session_created = 0.0
        self._lock = asyncio.Lock()

    async def _get_session(self):
        from tastytrade import Account, Session

        async with self._lock:
            now = time.time()
            if self._session is None or now - self._session_created > SESSION_TTL_SECONDS:
                self._session = Session(
                    provider_secret=self.s.tastytrade_provider_secret or None,
                    refresh_token=self.s.tastytrade_refresh_token or None,
                    is_test=self.s.tastytrade_sandbox_mode,
                )
                await self._session.refresh()
                self._session_created = now
                self._account = await Account.get(self._session, self.s.tastytrade_account_number)
                log.info("tastytrade session opened (sandbox=%s, account=%s)", self.s.tastytrade_sandbox_mode, self.s.tastytrade_account_number)
            return self._session, self._account

    @retry(retry=_retryable(), stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=8), reraise=True)
    async def position_qty(self, symbol: str) -> Decimal:
        session, account = await self._get_session()
        positions = await account.get_positions(session, underlying_symbols=[symbol])
        qty = Decimal("0")
        for p in positions:
            if p.symbol == symbol and str(p.instrument_type) in ("InstrumentType.EQUITY", "Equity"):
                q = Decimal(str(p.quantity))
                qty += q if str(p.quantity_direction).lower().endswith("long") else -q
        return qty

    @retry(retry=_retryable(), stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=8), reraise=True)
    async def snapshot(self) -> dict:
        session, account = await self._get_session()
        bal = await account.get_balances(session)
        positions = await account.get_positions(session)
        return {
            "account": account.account_number,
            "sandbox": session.is_test,
            "net_liquidating_value": str(bal.net_liquidating_value),
            "cash_balance": str(bal.cash_balance),
            "positions": [{"symbol": p.symbol, "qty": str(p.quantity), "direction": str(p.quantity_direction)} for p in positions],
        }

    async def place_market(self, symbol: str, qty: Decimal, action: str, dry_run: bool) -> OrderResult:
        """Stage 1 always validates with dry_run=True. Stage 2 submits only when dry_run is False."""
        from tastytrade.instruments import Equity
        from tastytrade.order import NewOrder, OrderAction, OrderTimeInForce, OrderType

        session, account = await self._get_session()
        equity = await Equity.get(session, symbol)
        order_action = {"BUY_TO_OPEN": OrderAction.BUY_TO_OPEN, "SELL_TO_CLOSE": OrderAction.SELL_TO_CLOSE}[action]
        order = NewOrder(time_in_force=OrderTimeInForce.DAY, order_type=OrderType.MARKET, legs=[equity.build_leg(qty, order_action)])
        check = await account.place_order(session, order, dry_run=True)  # one attempt, no retry on placement
        result = OrderResult(False, None, None, str(check.buying_power_effect.change_in_buying_power) if check.buying_power_effect else None,
                             [str(w) for w in (check.warnings or [])], [str(e) for e in (check.errors or [])])
        if result.errors or dry_run:
            return result
        placed = await account.place_order(session, order, dry_run=False)
        return OrderResult(True, str(getattr(placed.order, "id", None)), str(getattr(placed.order, "status", None)),
                           result.buying_power_effect, [str(w) for w in (placed.warnings or [])], [str(e) for e in (placed.errors or [])])
