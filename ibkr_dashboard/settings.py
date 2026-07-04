"""Typed config loader: config/config.yaml (or config.example.yaml as a fallback) + .env."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config" / "config.example.yaml"


class IBKRConfig(BaseSettings):
    mode: Literal["paper", "live"] = "paper"
    host: str = "127.0.0.1"
    paper_port: int = 4002
    live_port: int = 4001
    client_id: int = 11
    account_id: str = ""
    readonly_api: bool = True
    reconnect_delay_seconds: int = 5
    timeout_seconds: int = 10

    @property
    def port(self) -> int:
        return self.paper_port if self.mode == "paper" else self.live_port


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
    currencies: list[str] = Field(
        default_factory=lambda: ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK"]
    )
    instruments_dir: str = "config/instruments"

    @property
    def sqlite_path(self) -> Path:
        p = Path(self.storage.sqlite_path)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def instruments_path(self) -> Path:
        p = Path(self.instruments_dir)
        return p if p.is_absolute() else REPO_ROOT / p


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
