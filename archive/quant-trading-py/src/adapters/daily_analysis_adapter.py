"""
Daily Stock Analysis 适配器
设计用于接入 daily-stock-analysis 项目的数据流
GitHub: https://github.com/nickmancol/daily-stock-analysis

daily-stock-analysis 是一个每日股票分析工具，
主要功能是自动获取数据并生成技术分析报告。
本适配器提供策略和数据桥接能力。
"""
import logging
from typing import Dict, Any, List

logger = logging.getLogger("quant_trading")


class DailyAnalysisAdapter:
    """Daily Stock Analysis 适配器"""

    def __init__(self, project_path: str = ""):
        """
        Args:
            project_path: daily-stock-analysis 项目的本地路径
                         例如: /path/to/daily-stock-analysis
        """
        self.project_path = project_path
        self.enabled = bool(project_path)

    def is_enabled(self) -> bool:
        return self.enabled

    def get_daily_analysis_config(self) -> Dict[str, Any]:
        """生成 daily-stock-analysis 风格的配置"""
        return {
            "tickers": {
                "us": ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META"],
                "a_share": ["600519", "000858", "000333", "600036", "002594", "300750"],
            },
            "timeframe": "1d",
            "period": "6mo",
            "indicators": {
                "sma": [5, 20, 60],
                "ema": [12, 26],
                "rsi": {"period": 14, "overbought": 70, "oversold": 30},
                "macd": {"fast": 12, "slow": 26, "signal": 9},
                "bollinger": {"period": 20, "std": 2},
                "atr": {"period": 14},
            },
            "output": {
                "format": ["html", "json"],
                "charts": True,
                "send_email": False,
            },
        }

    def convert_to_daily_analysis_format(self, our_result: Dict[str, Any]) -> Dict[str, Any]:
        """将我们的分析结果转换为 daily-stock-analysis 兼容格式"""
        sig = our_result.get("signal", {})
        tech = our_result.get("technical", {})
        fund = our_result.get("fundamental", {})

        return {
            "ticker": our_result.get("code", ""),
            "name": our_result.get("name", ""),
            "market": our_result.get("market", ""),
            "date": our_result.get("date", ""),
            "price": tech.get("close"),
            "technical_analysis": {
                "rsi": tech.get("rsi"),
                "macd": tech.get("macd"),
                "macd_signal": tech.get("macd_signal"),
                "ma20": tech.get("ma20"),
                "ma60": tech.get("ma60"),
                "bb_upper": tech.get("bb_upper"),
                "bb_lower": tech.get("bb_lower"),
                "atr": tech.get("atr"),
            },
            "fundamental_analysis": {
                "score": fund.get("total_score"),
                "rating": fund.get("rating"),
                "pe": fund.get("raw", {}).get("pe_ttm"),
                "pb": fund.get("raw", {}).get("pb"),
                "roe": fund.get("raw", {}).get("roe"),
            },
            "trading_signal": {
                "action": sig.get("overall_signal", "HOLD"),
                "confidence": sig.get("overall_confidence", "LOW"),
                "stop_loss": sig.get("stop_loss"),
                "take_profit": sig.get("take_profit"),
                "reason": sig.get("overall_reason", ""),
            },
        }

    def merge_daily_analysis_result(self, our_result: Dict, daily_result: Dict) -> Dict[str, Any]:
        """合并 daily-stock-analysis 的分析结果到我们的结果中"""
        merged = dict(our_result)
        if "technical_analysis" in daily_result:
            # 可以取两者的平均或优先选择一方的指标
            merged["technical_extra"] = daily_result["technical_analysis"]
        if "trading_signal" in daily_result:
            # 交叉验证信号
            our_signal = merged.get("signal", {}).get("overall_signal", "HOLD")
            their_signal = daily_result["trading_signal"].get("action", "HOLD")
            if our_signal == their_signal:
                merged["signal_validation"] = "confirmed"
            else:
                merged["signal_validation"] = "divergent"
                merged["signal_divergence"] = {
                    "our_signal": our_signal,
                    "their_signal": their_signal,
                }
        return merged

    def export_strategy_rules(self) -> List[Dict[str, Any]]:
        """导出我们的策略规则供 daily-stock-analysis 使用"""
        return [
            {
                "name": "MACD Golden Cross",
                "type": "buy",
                "indicator": "macd",
                "condition": "macd_line crosses above signal_line",
                "weight": 0.25,
            },
            {
                "name": "RSI Oversold",
                "type": "buy",
                "indicator": "rsi",
                "condition": "rsi < 30",
                "weight": 0.15,
            },
            {
                "name": "MACD Death Cross",
                "type": "sell",
                "indicator": "macd",
                "condition": "macd_line crosses below signal_line",
                "weight": 0.25,
            },
            {
                "name": "RSI Overbought",
                "type": "sell",
                "indicator": "rsi",
                "condition": "rsi > 70",
                "weight": 0.15,
            },
            {
                "name": "Volume Spike",
                "type": "momentum",
                "indicator": "volume",
                "condition": "volume > volume_ma20 * 1.5",
                "weight": 0.20,
            },
        ]
