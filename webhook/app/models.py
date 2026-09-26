"""Alert payloads from the Pine script and the order they map to."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ValidationError, field_validator

# Events the Pine script emits in strategy.entry / strategy.exit / strategy.close alert_message.
ENTRY_EVENTS = {"core_entry"}
EXIT_EVENTS = {"core_ema_exit", "core_stop"}


class Alert(BaseModel):
    event: str
    symbol: str
    id: str = ""
    action: str = ""
    qty: Decimal
    fill_price: Decimal | None = None

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, v: str) -> str:
        # {{ticker}} gives "SPY"; tolerate "AMEX:SPY" and lower case.
        return v.split(":")[-1].strip().upper()

    @field_validator("qty", mode="before")
    @classmethod
    def _qty(cls, v: Any) -> Decimal:
        try:
            d = Decimal(str(v))
        except (InvalidOperation, TypeError) as e:
            raise ValueError(f"qty is not a number: {v!r}") from e
        if d <= 0:
            raise ValueError(f"qty must be positive, got {d}")
        return d

    @field_validator("fill_price", mode="before")
    @classmethod
    def _price(cls, v: Any) -> Decimal | None:
        if v in (None, "", "NaN"):
            return None
        return Decimal(str(v))

    @property
    def side(self) -> Literal["entry", "exit"] | None:
        if self.event in ENTRY_EVENTS:
            return "entry"
        if self.event in EXIT_EVENTS:
            return "exit"
        return None


def parse_body(raw: bytes) -> tuple[str | None, Alert]:
    """Accepts {"secret": "...", "alert": {...}} or the alert fields at the top level with a "secret" key.

    TradingView cannot set headers, so the secret travels in the body. Returns (secret, alert).
    """
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"body is not JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("body must be a JSON object")
    secret = data.get("secret")
    inner: Any = data.get("alert", data)
    if isinstance(inner, str):  # alert_message pasted as a string
        try:
            inner = json.loads(inner)
        except json.JSONDecodeError as e:
            raise ValueError(f"alert is not JSON: {e}") from e
    if not isinstance(inner, dict):
        raise ValueError("alert must be a JSON object")
    try:
        alert = Alert(**{k: v for k, v in inner.items() if k != "secret"})
    except ValidationError as e:
        raise ValueError(f"alert fields invalid: {e.errors()[0].get('msg', e)}") from e
    return (secret if isinstance(secret, str) else None), alert
