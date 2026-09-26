"""Settings, loaded from the environment or a .env file next to this package."""
from __future__ import annotations

import os

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=os.environ.get("WEBHOOK_ENV_FILE", ".env"), extra="ignore")

    webhook_secret: str = Field(min_length=16, description="Shared secret TradingView puts in the alert body")
    tastytrade_provider_secret: str = Field(default="", description="OAuth provider secret (TT_SECRET)")
    tastytrade_refresh_token: str = Field(default="", description="OAuth refresh token (TT_REFRESH)")
    tastytrade_account_number: str = Field(min_length=1, description="The sandbox account number from your account model")
    tastytrade_sandbox_mode: bool = True
    dry_run: bool = True  # validate orders with the broker but never submit them
    allowed_symbols: str = "SPY,QQQ,SMH"
    max_qty_per_order: int = 500
    journal_path: str = "journal.jsonl"
    dedupe_window_seconds: int = 900
    host: str = "0.0.0.0"
    port: int = 8000

    @field_validator("tastytrade_sandbox_mode")
    @classmethod
    def _sandbox_only(cls, v: bool) -> bool:
        if not v:
            raise ValueError(
                "TASTYTRADE_SANDBOX_MODE=false is refused: the tastytrade estate is read, alert and "
                "simulate only (shared sandbox account). Live order placement needs the account model "
                "revised first; this service does not implement it."
            )
        return v

    @property
    def symbols(self) -> set[str]:
        return {s.strip().upper() for s in self.allowed_symbols.split(",") if s.strip()}
