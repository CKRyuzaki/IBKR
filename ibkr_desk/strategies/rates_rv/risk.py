"""Pre-trade risk limits and kill switch."""

from __future__ import annotations

from pathlib import Path

from ibkr_desk.core.config import FutureSpec
from ibkr_desk.strategies.rates_rv.config import RiskConfig


class RiskManager:
    def __init__(self, cfg: RiskConfig, products: dict[str, FutureSpec], root: Path):
        self.cfg = cfg
        self.products = products
        self.kill_path = root / cfg.kill_file

    def killed(self) -> bool:
        return self.kill_path.exists()

    def daily_loss_breached(self, daily_pnl: float | None) -> bool:
        return daily_pnl is not None and daily_pnl <= -self.cfg.max_daily_loss

    def clip_targets(self, targets: dict[str, int]) -> dict[str, int]:
        """Clip per-leg size, then scale everything down if total |DV01| exceeds the cap."""
        lim = self.cfg.max_contracts_per_leg
        out = {p: int(max(-lim, min(lim, q))) for p, q in targets.items()}
        dv01 = sum(abs(q) * self.products[p].dv01 for p, q in out.items())
        if dv01 > self.cfg.max_total_abs_dv01:
            k = self.cfg.max_total_abs_dv01 / dv01
            out = {p: int(q * k) for p, q in out.items()}
        return out
