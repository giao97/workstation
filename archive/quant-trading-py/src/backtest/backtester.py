"""Event-driven daily backtester for the production SignalEngine rules."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from config import BACKTEST_CONFIG
from src.analysis.signals import SignalEngine
from src.analysis.technical import TechnicalAnalyzer
from src.data.schema import normalize_ohlcv


class DailyBacktester:
    """Backtest long-only BUY/SELL signals with next-open execution."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.cfg = dict(BACKTEST_CONFIG)
        if config:
            self.cfg.update(config)
        self.technical = TechnicalAnalyzer()
        self.signal_engine = SignalEngine()

    def run(
        self,
        data: pd.DataFrame,
        symbol: str = "",
        market: str = "",
        min_lot: int = 1,
    ) -> Dict[str, Any]:
        frame = normalize_ohlcv(data, symbol=symbol, source="backtest")
        warmup = max(2, int(self.cfg.get("warmup_days", 60)))
        if frame.empty or len(frame) <= warmup + 2:
            return self._empty_result(symbol, market)

        frame = self.technical.calculate_all(frame)
        capital = float(self.cfg["initial_capital"])
        cash = capital
        shares = 0
        entry_index: Optional[int] = None
        entry_price = 0.0
        stop_loss: Optional[float] = None
        take_profit: Optional[float] = None
        trades: List[Dict[str, Any]] = []
        equity_curve: List[Dict[str, Any]] = []

        benchmark_base = float(frame.iloc[warmup]["open"])
        benchmark_cost_ratio = 1.0 + float(self.cfg["commission_rate"]) + float(self.cfg["slippage_bps"]) / 10000

        for index in range(warmup, len(frame) - 1):
            signal = self._signal_at(frame, index)
            next_index = index + 1
            next_open = float(frame.iloc[next_index]["open"])
            current_close = float(frame.iloc[index]["close"])

            # Existing position exits are processed before a new entry.
            if shares > 0:
                can_sell = not bool(self.cfg.get("t_plus_one", True)) or entry_index is None or next_index > entry_index
                exit_price, exit_reason = self._determine_exit(
                    frame.iloc[next_index],
                    next_open,
                    stop_loss,
                    take_profit,
                    signal,
                    can_sell,
                )
                if exit_price is not None and can_sell:
                    cash += self._sell_proceeds(shares, exit_price)
                    pnl = self._sell_proceeds(shares, exit_price) - shares * entry_price
                    trades.append(
                        self._trade_record(
                            symbol,
                            market,
                            entry_index,
                            next_index,
                            entry_price,
                            exit_price,
                            shares,
                            pnl,
                            exit_reason,
                            frame,
                        )
                    )
                    shares = 0
                    entry_index = None
                    entry_price = 0.0
                    stop_loss = take_profit = None

            if shares == 0 and "BUY" in signal.get("overall_signal", ""):
                execution_price = next_open * (1 + float(self.cfg["slippage_bps"]) / 10000)
                quantity = self._position_quantity(cash, execution_price, min_lot)
                if quantity > 0:
                    commission = self._commission(execution_price * quantity)
                    total_cost = execution_price * quantity + commission
                    cash -= total_cost
                    shares = quantity
                    entry_index = next_index
                    entry_price = total_cost / quantity
                    stop_loss = signal.get("stop_loss")
                    take_profit = signal.get("take_profit")
                    if stop_loss is None and frame.iloc[next_index].get("atr") is not None:
                        atr = float(frame.iloc[next_index]["atr"])
                        raw_stop = execution_price - float(self.cfg["stop_loss_atr_multiplier"]) * atr
                        stop_loss = max(raw_stop, execution_price * 0.01, 0.0001)
                    if take_profit is None and frame.iloc[next_index].get("atr") is not None:
                        atr = float(frame.iloc[next_index]["atr"])
                        raw_take = execution_price + float(self.cfg["take_profit_atr_multiplier"]) * atr
                        take_profit = max(raw_take, execution_price * 1.01, (stop_loss or 0.0001) + 0.0001)

            mark_price = float(frame.iloc[next_index]["close"])
            equity = cash + shares * mark_price
            benchmark_equity = capital * (mark_price / benchmark_base) / benchmark_cost_ratio
            equity_curve.append(
                {
                    "date": pd.Timestamp(frame.iloc[next_index]["date"]).strftime("%Y-%m-%d"),
                    "equity": round(equity, 2),
                    "benchmark": round(benchmark_equity, 2),
                    "position_shares": shares,
                }
            )

        if shares > 0:
            final_price = max(
                0.0001,
                float(frame.iloc[-1]["close"]) * (1 - float(self.cfg["slippage_bps"]) / 10000),
            )
            proceeds = self._sell_proceeds(shares, final_price)
            pnl = proceeds - shares * entry_price
            cash = proceeds
            trades.append(
                self._trade_record(
                    symbol,
                    market,
                    entry_index,
                    len(frame) - 1,
                    entry_price,
                    final_price,
                    shares,
                    pnl,
                    "期末强制平仓",
                    frame,
                )
            )
            final_equity = cash
        else:
            final_equity = cash

        metrics = self._calculate_metrics(equity_curve, final_equity, trades, frame)
        return {
            "symbol": symbol,
            "market": market,
            "generated_at": datetime.now().isoformat(),
            "period_start": pd.Timestamp(frame.iloc[warmup]["date"]).strftime("%Y-%m-%d"),
            "period_end": pd.Timestamp(frame.iloc[-1]["date"]).strftime("%Y-%m-%d"),
            "metrics": metrics,
            "trades": trades,
            "equity_curve": equity_curve,
            "config": {
                "initial_capital": capital,
                "commission_rate": self.cfg["commission_rate"],
                "slippage_bps": self.cfg["slippage_bps"],
                "t_plus_one": self.cfg.get("t_plus_one", True),
            },
        }

    def _signal_at(self, frame: pd.DataFrame, index: int) -> Dict[str, Any]:
        last = frame.iloc[index]
        prev = frame.iloc[index - 1]
        prev_macd = self._number(prev.get("macd"))
        prev_macd_signal = self._number(prev.get("macd_signal"))
        last_macd = self._number(last.get("macd"))
        last_macd_signal = self._number(last.get("macd_signal"))
        prev_k = self._number(prev.get("kdj_k"))
        prev_d = self._number(prev.get("kdj_d"))
        last_k = self._number(last.get("kdj_k"))
        last_d = self._number(last.get("kdj_d"))
        rsi = self._number(last.get("rsi"))
        close = self._number(last.get("close"))
        prev_close = self._number(prev.get("close"))
        volume = self._number(last.get("volume"))
        volume_ma = self._number(last.get("vol_ma20"))
        price_change = (
            round((close - prev_close) / prev_close * 100, 4)
            if close is not None and prev_close not in (None, 0)
            else None
        )
        technical = {
            "close": close,
            "ma5": self._number(last.get("ma5")),
            "ma20": self._number(last.get("ma20")),
            "ma60": self._number(last.get("ma60")),
            "rsi": rsi,
            "macd": self._number(last.get("macd")),
            "macd_signal": self._number(last.get("macd_signal")),
            "bb_upper": self._number(last.get("bb_upper")),
            "bb_lower": self._number(last.get("bb_lower")),
            "kdj_k": self._number(last.get("kdj_k")),
            "kdj_d": self._number(last.get("kdj_d")),
            "atr": self._number(last.get("atr")),
            "volume": volume,
            "vol_ma20": volume_ma,
            "price_change_pct": price_change,
            "macd_golden_cross": bool(
                prev_macd is not None
                and prev_macd_signal is not None
                and last_macd is not None
                and last_macd_signal is not None
                and prev_macd <= prev_macd_signal
                and last_macd > last_macd_signal
            ),
            "macd_death_cross": bool(
                prev_macd is not None
                and prev_macd_signal is not None
                and last_macd is not None
                and last_macd_signal is not None
                and prev_macd >= prev_macd_signal
                and last_macd < last_macd_signal
            ),
            "price_above_ma20": bool(close is not None and self._number(last.get("ma20")) is not None and close > last["ma20"]),
            "price_below_ma20": bool(close is not None and self._number(last.get("ma20")) is not None and close < last["ma20"]),
            "kdj_golden_cross": bool(
                prev_k is not None
                and prev_d is not None
                and last_k is not None
                and last_d is not None
                and prev_k <= prev_d
                and last_k > last_d
                and last_k < 50
            ),
            "kdj_death_cross": bool(
                prev_k is not None
                and prev_d is not None
                and last_k is not None
                and last_d is not None
                and prev_k >= prev_d
                and last_k < last_d
                and last_k > 50
            ),
        }
        return self.signal_engine.generate_signal(technical, {}, {"combined_score": 0})

    def _determine_exit(
        self,
        row: pd.Series,
        open_price: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        signal: Dict[str, Any],
        can_sell: bool,
    ) -> tuple[Optional[float], str]:
        if not can_sell:
            return None, "T+1"
        low = self._number(row.get("low"))
        high = self._number(row.get("high"))
        if stop_loss is not None and low is not None and low <= stop_loss:
            exit_price = max(0.0001, min(open_price, stop_loss) * (1 - float(self.cfg["slippage_bps"]) / 10000))
            return exit_price, "止损"
        if take_profit is not None and high is not None and high >= take_profit:
            exit_price = max(0.0001, take_profit * (1 - float(self.cfg["slippage_bps"]) / 10000))
            return exit_price, "止盈"
        if signal.get("signal_direction") == "EXIT":
            return max(0.0001, open_price * (1 - float(self.cfg["slippage_bps"]) / 10000)), "卖出信号"
        return None, ""

    def _position_quantity(self, cash: float, price: float, min_lot: int) -> int:
        if price <= 0 or cash <= 0:
            return 0
        lot = max(1, min_lot)
        maximum = math.floor((cash - float(self.cfg["min_commission"])) / (price * (1 + float(self.cfg["commission_rate"]))) / lot) * lot
        return max(0, maximum)

    def _commission(self, gross_value: float) -> float:
        return max(float(self.cfg["min_commission"]), gross_value * float(self.cfg["commission_rate"]))

    def _sell_proceeds(self, shares: int, price: float) -> float:
        gross = shares * max(0.0, price)
        return gross - self._commission(gross)

    def _trade_record(
        self,
        symbol: str,
        market: str,
        entry_index: Optional[int],
        exit_index: int,
        entry_price: float,
        exit_price: float,
        shares: int,
        pnl: float,
        reason: str,
        frame: pd.DataFrame,
    ) -> Dict[str, Any]:
        entry_date = (
            pd.Timestamp(frame.iloc[entry_index]["date"]).strftime("%Y-%m-%d")
            if entry_index is not None
            else None
        )
        exit_date = pd.Timestamp(frame.iloc[exit_index]["date"]).strftime("%Y-%m-%d")
        return {
            "symbol": symbol,
            "market": market,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "entry_price": round(entry_price, 4),
            "exit_price": round(exit_price, 4),
            "shares": shares,
            "pnl": round(pnl, 2),
            "return_pct": round(pnl / (shares * entry_price) * 100, 4) if shares and entry_price else 0.0,
            "exit_reason": reason,
            "holding_days": int(exit_index - (entry_index or exit_index)),
        }

    def _calculate_metrics(
        self,
        equity_curve: List[Dict[str, Any]],
        final_equity: float,
        trades: List[Dict[str, Any]],
        frame: pd.DataFrame,
    ) -> Dict[str, Any]:
        initial_capital = float(self.cfg["initial_capital"])
        if not equity_curve:
            return self._empty_metrics(initial_capital)

        equity = pd.Series([item["equity"] for item in equity_curve], dtype=float)
        benchmark = pd.Series([item["benchmark"] for item in equity_curve], dtype=float)
        final_equity = max(final_equity, 0.0)
        total_return = final_equity / initial_capital - 1
        periods = max(1, len(equity_curve) - 1)
        annualized_return = (1 + total_return) ** (float(self.cfg["trading_days_per_year"]) / periods) - 1 if total_return > -1 else -1.0
        daily_returns = equity.pct_change().dropna()
        volatility = float(daily_returns.std(ddof=0) * math.sqrt(self.cfg["trading_days_per_year"])) if not daily_returns.empty else 0.0
        sharpe = (
            (annualized_return - float(self.cfg["risk_free_rate"])) / volatility
            if volatility > 0
            else 0.0
        )
        running_max = equity.cummax()
        drawdown = equity / running_max - 1
        max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
        benchmark_return = float(benchmark.iloc[-1] / initial_capital - 1) if not benchmark.empty else 0.0

        wins = [trade for trade in trades if trade["pnl"] > 0]
        losses = [trade for trade in trades if trade["pnl"] < 0]
        gross_profit = sum(trade["pnl"] for trade in wins)
        gross_loss = abs(sum(trade["pnl"] for trade in losses))
        win_rate = len(wins) / len(trades) if trades else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0)
        average_holding_days = sum(trade["holding_days"] for trade in trades) / len(trades) if trades else 0.0

        return {
            "initial_capital": initial_capital,
            "final_equity": round(final_equity, 2),
            "net_profit": round(final_equity - initial_capital, 2),
            "total_return_pct": round(total_return * 100, 2),
            "annualized_return_pct": round(annualized_return * 100, 2),
            "volatility_pct": round(volatility * 100, 2),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown_pct": round(max_drawdown * 100, 2),
            "benchmark_return_pct": round(benchmark_return * 100, 2),
            "trade_count": len(trades),
            "win_rate_pct": round(win_rate * 100, 2),
            "profit_factor": round(profit_factor, 3) if math.isfinite(profit_factor) else None,
            "average_holding_days": round(average_holding_days, 2),
            "open_position_at_end": bool(any(trade["exit_reason"] == "期末强制平仓" for trade in trades)),
        }

    def _empty_metrics(self, capital: float) -> Dict[str, Any]:
        return {
            "initial_capital": capital,
            "final_equity": capital,
            "net_profit": 0.0,
            "total_return_pct": 0.0,
            "annualized_return_pct": 0.0,
            "volatility_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "benchmark_return_pct": 0.0,
            "trade_count": 0,
            "win_rate_pct": 0.0,
            "profit_factor": None,
            "average_holding_days": 0.0,
            "open_position_at_end": False,
        }

    def _empty_result(self, symbol: str, market: str) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "market": market,
            "generated_at": datetime.now().isoformat(),
            "period_start": None,
            "period_end": None,
            "metrics": self._empty_metrics(float(self.cfg["initial_capital"])),
            "trades": [],
            "equity_curve": [],
            "config": self.cfg,
        }

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        if value is None or pd.isna(value):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
