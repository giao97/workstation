"""Position sizing and portfolio-level risk summaries."""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

from config import POSITION_SIZING_CONFIG


class PositionSizer:
    """Fixed-fractional sizing constrained by per-symbol exposure."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.cfg = dict(POSITION_SIZING_CONFIG)
        if config:
            self.cfg.update(config)

    def suggest(
        self,
        price: float,
        atr: float,
        capital: Optional[float] = None,
        min_lot: int = 1,
        symbol: str = "",
    ) -> Dict[str, Any]:
        capital = float(capital or self.cfg["default_capital"])
        risk_per_trade = float(self.cfg["risk_per_trade"])
        max_position_pct = float(self.cfg["max_position_pct"])
        atr_multiplier = float(self.cfg["atr_stop_multiplier"])
        lot = max(1, int(min_lot))

        if price <= 0 or atr <= 0 or capital <= 0:
            return self._invalid(symbol, capital, price)

        risk_amount = capital * risk_per_trade
        risk_per_share = atr * atr_multiplier
        risk_limited_units = math.floor(risk_amount / risk_per_share / lot) * lot
        exposure_limited_units = math.floor(capital * max_position_pct / price / lot) * lot
        shares = min(risk_limited_units, exposure_limited_units)
        if shares <= 0:
            return self._invalid(symbol, capital, price)

        notional = shares * price
        return {
            "symbol": symbol,
            "shares": shares,
            "notional": round(notional, 2),
            "position_pct": round(notional / capital * 100, 2),
            "risk_amount": round(risk_amount, 2),
            "risk_per_share": round(risk_per_share, 4),
            "stop_loss": round(price - risk_per_share, 4),
            "max_loss_pct": round(risk_per_share / price * 100, 4),
            "status": "VALID",
        }

    @staticmethod
    def _invalid(symbol: str, capital: float, price: float) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "shares": 0,
            "notional": 0.0,
            "position_pct": 0.0,
            "risk_amount": 0.0,
            "risk_per_share": None,
            "stop_loss": None,
            "max_loss_pct": None,
            "status": "INVALID",
            "capital": capital,
            "price": price,
        }


class PortfolioRisk:
    """Compute concentration, exposure, and risk warnings for candidate positions."""

    def __init__(self, capital: Optional[float] = None):
        self.capital = float(capital or POSITION_SIZING_CONFIG["default_capital"])

    def summarize(self, positions: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        rows = list(positions)
        total_notional = sum(float(item.get("notional", 0.0)) for item in rows)
        weights = [
            float(item.get("notional", 0.0)) / total_notional
            for item in rows
            if total_notional > 0 and float(item.get("notional", 0.0)) > 0
        ]
        max_weight = max(weights, default=0.0)
        concentration_hhi = sum(weight**2 for weight in weights)

        sectors: Counter[str] = Counter()
        for item in rows:
            sector = str(item.get("sector") or "未分类")
            sectors[sector] += float(item.get("notional", 0.0))
        sector_weights = {
            sector: round(value / total_notional * 100, 2)
            for sector, value in sectors.most_common()
            if total_notional > 0
        }

        warnings = []
        if total_notional > self.capital:
            warnings.append("候选仓位总敞口超过可用资金")
        if max_weight > 0.3:
            warnings.append("单一标的名义权重超过30%")
        if concentration_hhi > 0.25:
            warnings.append("持仓集中度较高")
        if any(value > 40 for value in sector_weights.values()):
            warnings.append("单一行业敞口超过40%")

        return {
            "capital": round(self.capital, 2),
            "total_notional": round(total_notional, 2),
            "cash_remaining": round(max(0.0, self.capital - total_notional), 2),
            "gross_exposure_pct": round(total_notional / self.capital * 100, 2) if self.capital else 0.0,
            "max_weight_pct": round(max_weight * 100, 2),
            "concentration_hhi": round(concentration_hhi, 4),
            "sector_weights": sector_weights,
            "position_count": len(rows),
            "warnings": warnings,
        }

    @classmethod
    def from_signal_results(
        cls,
        results: Iterable[Dict[str, Any]],
        capital: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Build hypothetical long positions from BUY signals for report previews."""
        sizer = PositionSizer()
        positions: List[Dict[str, Any]] = []
        for result in results:
            signal = result.get("signal") or {}
            if signal.get("signal_direction") != "LONG":
                continue
            technical = result.get("technical") or {}
            fundamental = result.get("fundamental") or {}
            price = technical.get("close")
            atr = technical.get("atr")
            market = str(result.get("market", ""))
            min_lot = 100 if market in {"A股", "港股"} else 1
            suggestion = sizer.suggest(
                float(price or 0),
                float(atr or 0),
                capital=capital,
                min_lot=min_lot,
                symbol=str(result.get("code", "")),
            )
            suggestion["sector"] = (fundamental.get("raw") or {}).get("sector")
            positions.append(suggestion)
        return cls(capital=capital).summarize(positions)
