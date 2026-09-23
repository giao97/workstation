"""
Yahoo Finance 数据获取增强版
支持美股和A股(Yahoo格式)的历史数据、实时报价、增强基本面数据
"""
import logging
import time
from typing import Optional, Dict, Any

import yfinance as yf
import pandas as pd

from config import DATA_SOURCE_CONFIG
from src.data.schema import normalize_ohlcv

logger = logging.getLogger("quant_trading")


class YahooDataFetcher:
    """Yahoo Finance 数据获取器"""

    def __init__(self):
        self.proxy = DATA_SOURCE_CONFIG["yahoo"].get("proxy")
        self.timeout = DATA_SOURCE_CONFIG["yahoo"].get("timeout", 30)
        self.retry_times = DATA_SOURCE_CONFIG["yahoo"].get("retry_times", 3)
        if self.proxy:
            # yfinance 1.5+ uses global configuration instead of history(proxy=...).
            yf.set_config(proxy=self.proxy)

    def _get_ticker(self, symbol: str) -> yf.Ticker:
        return yf.Ticker(symbol, session=None)

    def get_history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> Optional[pd.DataFrame]:
        """获取历史K线数据"""
        for attempt in range(1, self.retry_times + 1):
            try:
                ticker = self._get_ticker(symbol)
                df = ticker.history(period=period, interval=interval)
                if df is not None and not df.empty:
                    df.reset_index(inplace=True)
                    df = normalize_ohlcv(df, symbol=symbol, source="yfinance")
                    logger.info(f"Yahoo {symbol} 历史数据获取成功，共 {len(df)} 条")
                    return df
                else:
                    logger.warning(f"Yahoo {symbol} 返回空数据")
            except Exception as e:
                logger.warning(f"Yahoo {symbol} 第{attempt}次获取失败: {e}")
                if "too many requests" in str(e).lower():
                    break
                if attempt < self.retry_times:
                    time.sleep(self._backoff_seconds(attempt, e))
        return self._get_sina_us_history(symbol)

    def _get_sina_us_history(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fallback to AKShare's Sina-backed US daily data when Yahoo is unavailable."""
        try:
            import akshare as ak

            df = ak.stock_us_daily(symbol=symbol, adjust="qfq")
            if df is None or df.empty:
                return None
            normalized = normalize_ohlcv(df, symbol=symbol, source="sina-us")
            logger.info(f"Yahoo {symbol} 使用新浪美股历史备用源，共 {len(normalized)} 条")
            return normalized
        except Exception as exc:
            logger.warning(f"Yahoo {symbol} 新浪美股备用源失败: {exc}")
            return None

    def get_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取增强版股票信息和基本面数据"""
        for attempt in range(1, self.retry_times + 1):
            try:
                ticker = self._get_ticker(symbol)
                info = ticker.info
                if not info:
                    return None

                result = {
                    "symbol": symbol,
                    "name": info.get("longName") or info.get("shortName"),
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                    "market_cap": info.get("marketCap"),
                    "pe_ratio": info.get("trailingPE"),
                    "forward_pe": info.get("forwardPE"),
                    "pb_ratio": info.get("priceToBook"),
                    "ps_ratio": info.get("priceToSalesTrailing12Months"),
                    "roe": info.get("returnOnEquity"),
                    "revenue_growth": info.get("revenueGrowth"),
                    "earnings_growth": info.get("earningsGrowth"),
                    "profit_margins": info.get("profitMargins"),
                    "dividend_yield": info.get("dividendYield"),
                    "beta": info.get("beta"),
                    "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                    "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                    "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                    "currency": info.get("currency"),
                    # 新增指标
                    "eps_growth": info.get("earningsGrowth"),
                    "free_cashflow": info.get("freeCashflow"),
                    "operating_cashflow": info.get("operatingCashflow"),
                    "debt_to_equity": info.get("debtToEquity"),
                    "total_debt": info.get("totalDebt"),
                    "total_equity": info.get("totalStockholderEquity"),
                    "recommendation": info.get("recommendationKey"),
                    "number_of_analysts": info.get("numberOfAnalystOpinions"),
                    "target_high": info.get("targetHighPrice"),
                    "target_low": info.get("targetLowPrice"),
                    "target_mean": info.get("targetMeanPrice"),
                }

                # 计算P/FCF
                if result.get("free_cashflow") and result.get("market_cap") and result["free_cashflow"] > 0:
                    result["p_fcf"] = round(result["market_cap"] / result["free_cashflow"], 2)

                logger.info(f"Yahoo {symbol} 基本面信息获取成功")
                return result
            except Exception as e:
                logger.warning(f"Yahoo {symbol} 基本面信息第{attempt}次获取失败: {e}")
                if "too many requests" in str(e).lower():
                    break
                if attempt < self.retry_times:
                    time.sleep(self._backoff_seconds(attempt, e))
        return None

    def get_realtime_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取实时报价"""
        try:
            ticker = self._get_ticker(symbol)
            info = ticker.info
            if not info:
                return None
            return {
                "symbol": symbol,
                "price": info.get("regularMarketPrice") or info.get("currentPrice"),
                "change": info.get("regularMarketChange"),
                "change_pct": info.get("regularMarketChangePercent"),
                "volume": info.get("regularMarketVolume"),
                "open": info.get("regularMarketOpen"),
                "high": info.get("regularMarketDayHigh"),
                "low": info.get("regularMarketDayLow"),
                "prev_close": info.get("regularMarketPreviousClose"),
                "timestamp": pd.Timestamp.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Yahoo {symbol} 实时报价获取失败: {e}")
            return None

    def get_financials(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取财务报表数据"""
        try:
            ticker = self._get_ticker(symbol)
            return {
                "income_stmt": ticker.income_stmt.to_dict() if hasattr(ticker.income_stmt, "to_dict") else None,
                "balance_sheet": ticker.balance_sheet.to_dict() if hasattr(ticker.balance_sheet, "to_dict") else None,
                "cashflow": ticker.cashflow.to_dict() if hasattr(ticker.cashflow, "to_dict") else None,
            }
        except Exception as e:
            logger.error(f"Yahoo {symbol} 财务报表获取失败: {e}")
            return None

    @staticmethod
    def _backoff_seconds(attempt: int, error: Exception) -> float:
        message = str(error).lower()
        if "too many requests" in message or "rate limit" in message or "rate limited" in message:
            return 5.0 * attempt
        return min(1.5 * attempt, 4.0)
