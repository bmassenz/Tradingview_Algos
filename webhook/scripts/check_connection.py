"""Verify the tastytrade sandbox credentials and run one dry-run order. Usage: .venv/bin/python scripts/check_connection.py [SYMBOL]"""
import asyncio
import sys
from decimal import Decimal

sys.path.insert(0, ".")
from app.broker import TastytradeBroker  # noqa: E402
from app.config import Settings  # noqa: E402


async def main(symbol: str) -> None:
    s = Settings()
    b = TastytradeBroker(s)
    print("account snapshot:", await b.snapshot())
    print("position:", symbol, await b.position_qty(symbol))
    print("dry-run BUY_TO_OPEN 1", symbol, await b.place_market(symbol, Decimal(1), "BUY_TO_OPEN", dry_run=True))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "SPY"))
