"""
Tickflow Stock Panel 适配器
设计用于接入 tickflow-stock-panel 项目的数据流
GitHub: https://github.com/anthonychu/tickflow-stock-panel

tickflow-stock-panel 是一个基于 Azure Functions 的股票面板，
主要功能是实时显示股票价格。本适配器提供数据桥接能力。
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("quant_trading")


class TickflowAdapter:
    """Tickflow Stock Panel 适配器"""

    def __init__(self, api_base_url: str = ""):
        """
        Args:
            api_base_url: tickflow-stock-panel 的 API 端点基地址
                         例如: https://your-tickflow-app.azurewebsites.net/api
        """
        self.api_base = api_base_url.rstrip("/") if api_base_url else ""
        self.enabled = bool(self.api_base)

    def is_enabled(self) -> bool:
        return self.enabled

    def format_quote_for_tickflow(self, symbol: str, quote: Dict[str, Any]) -> Dict[str, Any]:
        """将我们的 quote 数据格式化为 tickflow 兼容格式"""
        return {
            "symbol": symbol,
            "price": quote.get("price", 0),
            "change": quote.get("change", 0),
            "changePercent": quote.get("change_pct", quote.get("changePercent", 0)),
            "volume": quote.get("volume", 0),
            "timestamp": quote.get("timestamp", ""),
            "signal": quote.get("overall_signal", quote.get("overallSignal", "HOLD")),
            "stopLoss": quote.get("stop_loss", quote.get("stopLoss")),
            "takeProfit": quote.get("take_profit", quote.get("takeProfit")),
        }

    def enrich_with_tickflow_data(self, symbol: str, tickflow_data: Dict) -> Dict[str, Any]:
        """
        从 tickflow-stock-panel 获取额外数据并合并
        tickflow 通常提供: 实时价格、涨跌幅、交易量
        """
        enriched = {
            "symbol": symbol,
            "source": "tickflow",
            "tickflow_price": tickflow_data.get("price"),
            "tickflow_change": tickflow_data.get("change"),
            "tickflow_volume": tickflow_data.get("volume"),
        }
        return enriched

    def export_signals_to_tickflow(self, signals: Dict[str, Any]) -> Dict[str, Any]:
        """将我们的交易信号导出为 tickflow 面板可展示的格式"""
        return {
            "type": "trading_signal",
            "symbol": signals.get("symbol", ""),
            "action": signals.get("overall_signal", signals.get("overallSignal", "HOLD")),
            "confidence": signals.get("overall_confidence", signals.get("overallConfidence", "LOW")),
            "reason": signals.get("overall_reason", signals.get("overallReason", "")),
            "levels": {
                "entry": signals.get("entry_price", signals.get("entryPrice")),
                "stop_loss": signals.get("stop_loss", signals.get("stopLoss")),
                "take_profit": signals.get("take_profit", signals.get("takeProfit")),
                "trailing_stop": signals.get("trailing_stop", signals.get("trailingStop")),
            },
            "timestamp": signals.get("timestamp", ""),
        }

    def get_tickflow_panel_config(self) -> Dict[str, Any]:
        """生成 tickflow 面板配置文件片段"""
        return {
            "name": "quant-trading-integration",
            "dataSources": [
                {"name": "yahoo", "type": "yahoo-finance"},
                {"name": "akshare", "type": "akshare-a-share"},
            ],
            "watchlist": {
                "us": ["AAPL", "TSLA", "NVDA", "MSFT", "GOOGL"],
                "a_share": ["600519", "000858", "002594", "300750"],
            },
            "features": {
                "showSignals": True,
                "showTechnicalIndicators": True,
                "showFundamentalScore": True,
            },
        }
