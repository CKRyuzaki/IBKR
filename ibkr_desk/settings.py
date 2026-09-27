"""Typed config loader: config/config.yaml (or config.example.yaml as a fallback) + .env.

This is the composition root: every sub-config lives next to the code that uses it
(core/config.py, strategies/*/config.py) and is assembled into one `Settings` here.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ibkr_desk.core.config import (
    DEFAULT_TREASURY_FUTURES,
    EquityArchiveConfig,
    FutureSpec,
    IBKRConfig,
    PostgresConfig,
)
from ibkr_desk.strategies.rates_rv.config import RatesRVConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config" / "config.example.yaml"


class BarBackfillDays(BaseSettings):
    intraday_1min: int = 2
    daily: int = 365


class StorageConfig(BaseSettings):
    sqlite_path: str = "data/market_data.db"
    bar_backfill_days: BarBackfillDays = Field(default_factory=BarBackfillDays)


class DashboardConfig(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8500
    update_throttle_ms: int = 250
    default_tab: str = "live"  # live | charts | portfolio | data | status


class Settings(BaseSettings):
    # Top-level scalar fields (e.g. instruments_dir) can still be overridden via
    # IBKR_DASHBOARD_* env vars. Nested fields (ibkr.*, storage.*, dashboard.*) are
    # sourced from config.yaml directly -- edit that file rather than relying on
    # env overrides for those, since pydantic-settings takes a whole nested block
    # from the highest-priority source rather than merging it field by field.
    model_config = SettingsConfigDict(env_prefix="IBKR_DASHBOARD_", extra="ignore")

    ibkr: IBKRConfig = Field(default_factory=IBKRConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    postgres: PostgresConfig = Field(default_factory=PostgresConfig)
    currencies: list[str] = Field(
        default_factory=lambda: ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK"]
    )
    instruments_dir: str = "config/instruments"
    data_dir: str = "data"

    # Rates / futures desk
    futures: dict[str, FutureSpec] = Field(default_factory=lambda: dict(DEFAULT_TREASURY_FUTURES))
    equities: EquityArchiveConfig = Field(default_factory=EquityArchiveConfig)
    rates_rv: RatesRVConfig = Field(default_factory=RatesRVConfig)

    @property
    def sqlite_path(self) -> Path:
        return self._resolve(self.storage.sqlite_path)

    @property
    def instruments_path(self) -> Path:
        return self._resolve(self.instruments_dir)

    @property
    def data_path(self) -> Path:
        return self._resolve(self.data_dir)

    @property
    def archive_path(self) -> Path:
        """CSV archive of raw daily bars (append-only backup of what is in Postgres)."""
        return self.data_path / "archive"

    @property
    def log_path(self) -> Path:
        return self._resolve(self.rates_rv.live.log_dir)

    @staticmethod
    def _resolve(p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else REPO_ROOT / path


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(config_path: Path | None = None) -> Settings:
    load_dotenv(REPO_ROOT / ".env")

    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        warnings.warn(
            f"{path} not found; falling back to {EXAMPLE_CONFIG_PATH}. "
            "Copy config.example.yaml to config.yaml and edit it for your setup "
            "(IBKR host/port, account id, etc).",
            stacklevel=2,
        )
        path = EXAMPLE_CONFIG_PATH

    raw = _load_yaml(path)
    return Settings(**raw)
