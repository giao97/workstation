"""
信号引擎 - 综合技术面+基本面+消息面生成交易信号
"""
import logging
from typing import Dict, Any

from config import SIGNAL_THRESHOLDS

logger = logging.getLogger("quant_trading")


class SignalEngine:
    """信号生成引擎"""

    def __init__(self):
        self.cfg = SIGNAL_THRESHOLDS
        self.confidence_weight = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

    def generate_signal(self, technical: Dict, fundamental: Dict, sentiment: Dict) -> Dict[str, Any]:
        """生成综合交易信号"""
        signals = []
        tech_signals = self._tech_signals(technical)
        fund_signals = self._fund_signals(fundamental)
        sent_signals = self._sent_signals(sentiment)
        signals.extend(tech_signals + fund_signals + sent_signals)

        price = technical.get("close") or 0
        atr = technical.get("atr")

        buys = [s for s in signals if s["type"] == "BUY"]
        sells = [s for s in signals if s["type"] == "SELL"]

        buy_score, sell_score, active_sources = self._aggregate_score(signals)
        has_meaningful_buy = buy_score >= 2
        has_meaningful_sell = sell_score >= 2

        if has_meaningful_buy and has_meaningful_sell:
            overall, conf, reason = "HOLD", "LOW", "多空信号冲突，等待共振确认"
        elif buy_score >= 6:
            overall, conf, reason = "STRONG_BUY", "HIGH", f"{'、'.join(active_sources)}多维度共振看多"
        elif buy_score >= 3:
            overall, conf, reason = "BUY", "MEDIUM", f"{'、'.join(active_sources)}出现看多信号"
        elif sell_score >= 6:
            overall, conf, reason = "STRONG_SELL", "HIGH", f"{'、'.join(active_sources)}多维度共振看空"
        elif sell_score >= 3:
            overall, conf, reason = "SELL", "MEDIUM", f"{'、'.join(active_sources)}出现看空信号"
        else:
            overall, conf, reason = "HOLD", "LOW", "暂无明确信号，观望"

        stop_loss = take_profit = trailing = rr = None
        if "BUY" in overall and price > 0:
            if atr:
                raw_stop = price - 2 * atr
                stop_loss = round(max(raw_stop, price * 0.02, 0.0001), 4)
                raw_take = price + 3 * atr
                take_profit = round(max(raw_take, price * 1.01, stop_loss + 0.0001), 4)
            else:
                stop_loss = round(max(price * (1 - self.cfg["stop_loss_pct"]), 0.0001), 4)
                take_profit = round(max(price * (1 + self.cfg["take_profit_pct"]), stop_loss + 0.0001), 4)

            trailing = round(technical.get("ma20") or price * 0.98, 2)
            if stop_loss and take_profit and price > stop_loss:
                rr = round((take_profit - price) / (price - stop_loss), 2)

        direction = "LONG" if "BUY" in overall else "EXIT" if "SELL" in overall else "HOLD"

        return {
            "signals": signals,
            "buy_count": len(buys),
            "sell_count": len(sells),
            "overall_signal": overall,
            "overall_confidence": conf,
            "overall_reason": reason,
            "signal_direction": direction,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "trailing_stop": trailing,
            "risk_reward_ratio": rr,
            "score": {
                "buy": buy_score,
                "sell": sell_score,
                "net": buy_score - sell_score,
            },
        }

    def _aggregate_score(self, signals: list) -> tuple[int, int, list[str]]:
        """Aggregate one bounded score per data source to avoid one indicator dominating."""
        grouped = {}
        for signal in signals:
            source = signal.get("source", "unknown")
            group = grouped.setdefault(source, {"BUY": 0, "SELL": 0})
            weight = self.confidence_weight.get(signal.get("confidence", "LOW"), 1)
            group[signal["type"]] += weight

        buy_score = 0
        sell_score = 0
        active_sources = []
        for source, values in grouped.items():
            source_buy = min(values["BUY"], 4)
            source_sell = min(values["SELL"], 4)
            if source_buy or source_sell:
                active_sources.append(source)
            buy_score += source_buy
            sell_score += source_sell

        return min(buy_score, 8), min(sell_score, 8), active_sources

    def _tech_signals(self, t: Dict) -> list:
        s = []
        if t.get("macd_golden_cross"):
            s.append({"type": "BUY", "source": "技术面", "confidence": "HIGH", "reason": "MACD金叉，动能转强"})
        if t.get("macd_death_cross"):
            s.append({"type": "SELL", "source": "技术面", "confidence": "HIGH", "reason": "MACD死叉，动能减弱"})
        rsi = t.get("rsi")
        if rsi is not None:
            if rsi < self.cfg["rsi_oversold"]:
                s.append({"type": "BUY", "source": "技术面", "confidence": "MEDIUM", "reason": f"RSI {rsi:.1f} 超卖"})
            if rsi > self.cfg["rsi_overbought"]:
                s.append({"type": "SELL", "source": "技术面", "confidence": "MEDIUM", "reason": f"RSI {rsi:.1f} 超买"})
        if t.get("kdj_golden_cross"):
            s.append({"type": "BUY", "source": "技术面", "confidence": "MEDIUM", "reason": "KDJ低位金叉"})
        if t.get("kdj_death_cross"):
            s.append({"type": "SELL", "source": "技术面", "confidence": "MEDIUM", "reason": "KDJ高位死叉"})
        if t.get("price_above_ma20"):
            s.append({"type": "BUY", "source": "技术面", "confidence": "LOW", "reason": "价格站上MA20"})
        if t.get("price_below_ma20"):
            s.append({"type": "SELL", "source": "技术面", "confidence": "LOW", "reason": "价格跌破MA20"})
        vol = t.get("volume")
        vol_ma = t.get("vol_ma20")
        price_change = t.get("price_change_pct")
        if vol and vol_ma and price_change is not None and vol > vol_ma * self.cfg["volume_spike_ratio"]:
            if price_change > 0:
                s.append({"type": "BUY", "source": "技术面", "confidence": "MEDIUM", "reason": "放量上涨"})
            elif price_change < 0:
                s.append({"type": "SELL", "source": "技术面", "confidence": "MEDIUM", "reason": "放量下跌"})
        return s

    def _fund_signals(self, f: Dict) -> list:
        s = []
        f = f or {}
        score = f.get("total_score")
        if not f.get("available", True) or score is None:
            return s
        if score >= 75:
            s.append({"type": "BUY", "source": "基本面", "confidence": "MEDIUM", "reason": f"基本面评分 {score} 优秀"})
        if score <= 35:
            s.append({"type": "SELL", "source": "基本面", "confidence": "MEDIUM", "reason": f"基本面评分 {score} 较差"})
        for flag in (f.get("flags") or [])[:2]:
            if any(k in flag for k in ["优秀", "良好", "偏低", "安全"]):
                s.append({"type": "BUY", "source": "基本面", "confidence": "LOW", "reason": flag})
        for risk in (f.get("risks") or [])[:2]:
            s.append({"type": "SELL", "source": "基本面", "confidence": "LOW", "reason": risk})
        return s

    def _sent_signals(self, sent: Dict) -> list:
        s = []
        sent = sent or {}
        cs = sent.get("combined_score", 0)
        if cs >= 2:
            s.append({"type": "BUY", "source": "消息面", "confidence": "MEDIUM", "reason": f"市场情绪偏正面 ({cs})"})
        if cs <= -2:
            s.append({"type": "SELL", "source": "消息面", "confidence": "MEDIUM", "reason": f"市场情绪偏负面 ({cs})"})
        return s
