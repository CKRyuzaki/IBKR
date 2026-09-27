"""Config models shared by every part of the desk (dashboard, archive jobs, strategies).

Kept dependency-free (pydantic only) so any module can import it without pulling in the app.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# IBKR paper accounts always start with "DU"; live accounts do not.
PAPER_ACCOUNT_PREFIX = "DU"


class ClientRole(IntEnum):
    """Every API client connected to one Gateway needs a distinct clientId. The value is the offset
    added to `IBKRConfig.client_id`, so all ids are defined here and can never silently collide."""

    DASHBOARD = 0
    TRADER = 1
    ARCHIVE = 2
    RESEARCH = 3
    ADHOC = 4


class IBKRConfig(BaseSettings):
    mode: Literal["paper", "live"] = "paper"
    host: str = "127.0.0.1"
    paper_port: int = 4002
    live_port: int = 4001
    client_id: int = 11  # base id; each ClientRole adds its offset
    account_id: str = ""
    readonly_api: bool = True  # applies to every role except TRADER, which needs to place orders
    allow_live: bool = False  # refuse to talk to a non-paper account unless explicitly enabled
    market_data_type: int = 1  # 1 live, 2 frozen, 3 delayed, 4 delayed-frozen
    historical_request_interval_s: float = 1.5  # min spacing between reqHistoricalData calls (pacing)
    reconnect_delay_seconds: int = 5
    timeout_seconds: int = 10

    @property
    def port(self) -> int:
        return self.paper_port if self.mode == "paper" else self.live_port

    def client_id_for(self, role: ClientRole) -> int:
        return self.client_id + int(role)

    def readonly_for(self, role: ClientRole) -> bool:
        return self.readonly_api and role is not ClientRole.TRADER


class PostgresConfig(BaseSettings):
    """Read from the standard libpq env vars (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE),
    typically set in the gitignored .env file."""

    model_config = SettingsConfigDict(env_prefix="PG", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 5432
    user: str = "postgres"
    password: SecretStr = SecretStr("")
    database: str = "marketdata"


class FutureSpec(BaseModel):
    """Contract reference data for one futures product. `dv01` is an approximation ($/bp per
    contract, CTD-based) -- refresh it from CME / your risk system."""

    exchange: str
    multiplier: float
    dv01: float
    tick: float
    tick_value: float


DEFAULT_TREASURY_FUTURES: dict[str, FutureSpec] = {
    "ZT": FutureSpec(exchange="CBOT", multiplier=2000, dv01=38.0, tick=0.00390625, tick_value=7.8125),
    "ZF": FutureSpec(exchange="CBOT", multiplier=1000, dv01=45.0, tick=0.0078125, tick_value=7.8125),
    "ZN": FutureSpec(exchange="CBOT", multiplier=1000, dv01=63.0, tick=0.015625, tick_value=15.625),
    "TN": FutureSpec(exchange="CBOT", multiplier=1000, dv01=75.0, tick=0.015625, tick_value=15.625),
    "ZB": FutureSpec(exchange="CBOT", multiplier=1000, dv01=155.0, tick=0.03125, tick_value=31.25),
}


class EquityArchiveConfig(BaseModel):
    symbols: list[str] = Field(
        default_factory=lambda: ["SPY", "QQQ", "IWM", "SHY", "IEF", "TLT", "TIP", "AGG", "LQD", "HYG"]
    )
    exchange: str = "SMART"
    duration: str = "10 Y"
