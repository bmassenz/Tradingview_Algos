"""FastAPI app. POST /tradingview receives the alert; GET /health, /account and /journal for checks.

Run with: uvicorn app.server:create_app --factory --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import json
import logging
from collections import deque
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .broker import TastytradeBroker
from .config import Settings
from .service import AlertService, Rejected

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


def create_app(settings: Settings | None = None, broker=None) -> FastAPI:
    settings = settings or Settings()
    broker = broker or TastytradeBroker(settings)
    service = AlertService(settings, broker)
    app = FastAPI(title="Trend-Core webhook", docs_url=None, redoc_url=None)
    app.state.service = service

    @app.post("/tradingview")
    async def tradingview(request: Request):
        raw = await request.body()
        try:
            out = await service.handle(raw)
        except Rejected as e:
            return JSONResponse({"accepted": False, "reason": e.reason}, status_code=e.status)
        return JSONResponse(out.__dict__, status_code=200 if out.accepted or out.note else 502)

    @app.get("/health")
    async def health():
        return {"ok": True, "sandbox": settings.tastytrade_sandbox_mode, "dry_run": settings.dry_run, "symbols": sorted(settings.symbols)}

    @app.get("/account")
    async def account():
        return await broker.snapshot()

    @app.get("/journal")
    async def journal(n: int = 50):
        p = Path(settings.journal_path)
        if not p.exists():
            return []
        with p.open() as f:
            return [json.loads(line) for line in deque(f, maxlen=max(1, min(n, 500)))]

    return app


