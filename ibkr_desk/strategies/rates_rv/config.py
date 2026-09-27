"""Config for the Treasury-futures curve relative-value strategy."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FlyConfig(BaseModel):
    """DV01-neutral butterfly: pos=+1 is long both wings / short belly, wings at 0.5x belly DV01 each."""

    name: str
    short_wing: str
    belly: str
    long_wing: str

    @property
    def legs(self) -> tuple[str, str, str]:
        return (self.short_wing, self.belly, self.long_wing)


class StrategyParams(BaseModel):
    z_window: int = 60
    entry_z: float = 2.0
    exit_z: float = 0.5
    stop_z: float = 4.0
    max_hold_days: int = 30
    vol_window: int = 60
    target_daily_vol: float = 1500  # USD daily vol target per fly
    max_belly_dv01: float = 5000  # cap on belly DV01 (USD/bp) per fly
    exec_lag: int = 1  # backtest: trade at close t+1 on a signal from close t


class CostsConfig(BaseModel):
    commission_per_contract: float = 0.85  # per side, incl. exchange/regulatory fees (approx)
    slippage_ticks: float = 0.5  # per side


class RollConfig(BaseModel):
    days_before_month_start: int = 10  # roll ~10 days before the contract month starts (before first notice)


class RiskConfig(BaseModel):
    max_contracts_per_leg: int = 50
    max_total_abs_dv01: float = 15000
    max_daily_loss: float = 3000  # USD; breach => flatten and stop
    kill_file: str = "KILL"  # create this file to flatten everything and halt


class LiveConfig(BaseModel):
    lookback_years: int = 3
    order_timeout_s: int = 60
    interval_min: int = 15
    log_dir: str = "logs"


class RatesRVConfig(BaseModel):
    flies: list[FlyConfig] = Field(
        default_factory=lambda: [
            FlyConfig(name="2s5s10s", short_wing="ZT", belly="ZF", long_wing="ZN"),
            FlyConfig(name="5s10s30s", short_wing="ZF", belly="ZN", long_wing="ZB"),
        ]
    )
    strategy: StrategyParams = Field(default_factory=StrategyParams)
    costs: CostsConfig = Field(default_factory=CostsConfig)
    roll: RollConfig = Field(default_factory=RollConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    live: LiveConfig = Field(default_factory=LiveConfig)
