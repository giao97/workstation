"""
AKShare A股数据获取增强版
支持 K线、实时行情、增强基本面数据(增长率/现金流/负债率/估值分位)
"""
import logging
import time
from typing import Optional, Dict, Any
from datetime import datetime

import akshare as ak
import pandas as pd

from src.data.schema import normalize_ohlcv

logger = logging.getLogger("quant_trading")


class AkshareDataFetcher:
    """AKShare A股数据获取器"""

    @staticmethod
    def _normalize_kline_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Map AKShare's Chinese K-line columns to the analyzer's English schema."""
        return normalize_ohlcv(df, source="akshare")

    @staticmethod
    def normalize_hk_symbol(code: str) -> str:
        """Convert user-facing HK ticker like 0700.HK to AKShare's 5-digit code."""
        raw = code.split(".", 1)[0].strip()
        return raw.zfill(5)

    @staticmethod
    def _sina_stock_code(code: str) -> str:
        """Build the sh/sz-prefixed code expected by Sina financial endpoints."""
        if code.startswith(("6", "9")):
            return f"sh{code}"
        return f"sz{code}"

    def get_daily_kline(self, code: str, period: str = "daily", start_date: str = "", end_date: str = "") -> Optional[pd.DataFrame]:
        """获取A股日线数据"""
        df = self._retry_call(
            lambda: ak.stock_zh_a_hist(
                symbol=code,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            ),
            label=f"{code} K线",
            attempts=3,
        )
        if df is None or df.empty:
            df = self._retry_call(
                lambda: ak.stock_zh_a_daily(
                    symbol=self._sina_stock_code(code),
                    start_date=start_date.replace("-", "") if start_date else "19900101",
                    end_date=end_date.replace("-", "") if end_date else "21000118",
                    adjust="qfq",
                ),
                label=f"{code} 新浪K线备用源",
                attempts=2,
            )
        if df is None or df.empty:
            return None
        normalized = self._normalize_kline_columns(df)
        logger.info(f"AKShare {code} K线获取成功，共 {len(normalized)} 条")
        return normalized

    def get_hk_daily_kline(self, code: str, period: str = "daily", start_date: str = "", end_date: str = "") -> Optional[pd.DataFrame]:
        """获取港股日线数据"""
        symbol = self.normalize_hk_symbol(code)
        df = self._retry_call(
            lambda: ak.stock_hk_hist(
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            ),
            label=f"{code} 港股K线",
            attempts=3,
        )
        if df is None or df.empty:
            df = self._retry_call(
                lambda: ak.stock_hk_daily(symbol=symbol, adjust="qfq"),
                label=f"{code} 新浪港股K线备用源",
                attempts=2,
            )
        if df is None or df.empty:
            return None
        normalized = self._normalize_kline_columns(df)
        logger.info(f"AKShare {code} 港股K线获取成功，共 {len(normalized)} 条")
        return normalized

    def get_realtime_quote(self, code: str) -> Optional[Dict[str, Any]]:
        """获取A股实时行情"""
        try:
            return self.get_a_spot_quotes([code]).get(code)
        except Exception as e:
            logger.error(f"AKShare {code} 实时行情获取失败: {e}")
            return None

    def get_a_spot_quotes(self, codes) -> Dict[str, Dict[str, Any]]:
        """Fetch the A-share spot table once and return only the requested codes."""
        df = self._retry_call(ak.stock_zh_a_spot_em, label="A股实时行情", attempts=2)
        if df is None or df.empty:
            return {}
        df = df.copy()
        df["代码"] = df["代码"].astype(str).str.replace(r"^(sh|sz|bj)", "", regex=True).str.split(".", n=1).str[0].str.zfill(6)

        quotes = {}
        for code in codes:
            row = df[df["代码"] == code]
            if row.empty:
                continue
            r = row.iloc[0]
            quotes[code] = {
                "code": code,
                "name": r.get("名称"),
                "price": self._to_float(r.get("最新价")),
                "change": self._to_float(r.get("涨跌幅")),
                "change_amount": self._to_float(r.get("涨跌额")),
                "volume": self._to_int(r.get("成交量")),
                "amount": self._to_float(r.get("成交额")),
                "open": self._to_float(r.get("今开")),
                "high": self._to_float(r.get("最高")),
                "low": self._to_float(r.get("最低")),
                "pre_close": self._to_float(r.get("昨收")),
                "pe_ttm": self._to_float(r.get("市盈率-动态")),
                "pb": self._to_float(r.get("市净率")),
                "turnover": self._to_float(r.get("换手率")),
                "market_cap": self._to_float(r.get("总市值")),
                "timestamp": pd.Timestamp.now().isoformat(),
            }
        return quotes

    def get_hk_spot_quotes(self, codes) -> Dict[str, Dict[str, Any]]:
        """Fetch the Hong Kong spot table once and return only the requested codes."""
        df = self._retry_call(ak.stock_hk_spot_em, label="港股实时行情", attempts=2)
        if df is None or df.empty:
            return {}

        by_code = {}
        for _, row in df.iterrows():
            raw_code = self.normalize_hk_symbol(str(row.get("代码", "")))
            by_code[raw_code] = row

        quotes = {}
        for code in codes:
            symbol = self.normalize_hk_symbol(code)
            r = by_code.get(symbol)
            if r is None:
                continue
            quotes[code] = {
                "code": code,
                "name": r.get("名称"),
                "price": self._to_float(r.get("最新价")),
                "change": self._to_float(r.get("涨跌幅")),
                "change_amount": self._to_float(r.get("涨跌额")),
                "volume": self._to_int(r.get("成交量")),
                "amount": self._to_float(r.get("成交额")),
                "open": self._to_float(r.get("今开")),
                "high": self._to_float(r.get("最高")),
                "low": self._to_float(r.get("最低")),
                "pre_close": self._to_float(r.get("昨收")),
                "timestamp": pd.Timestamp.now().isoformat(),
            }
        return quotes

    def get_fundamental(self, code: str) -> Optional[Dict[str, Any]]:
        """获取A股增强基本面数据"""
        result = {"code": code}
        sina_code = self._sina_stock_code(code)
        try:
            # === 盈利能力 ===
            try:
                df = ak.stock_financial_report_sina(stock=sina_code, symbol="利润表")
                if df is not None and not df.empty:
                    # 取最近两期计算增长率
                    latest = df.iloc[0] if len(df) > 0 else None
                    prev = df.iloc[1] if len(df) > 1 else None
                    if latest is not None:
                        revenue = self._parse_value(latest, "营业收入")
                        net_profit = self._parse_value(latest, "净利润")
                        result["revenue"] = revenue
                        result["net_profit"] = net_profit
                        if prev is not None:
                            prev_revenue = self._parse_value(prev, "营业收入")
                            prev_profit = self._parse_value(prev, "净利润")
                            if revenue is not None and prev_revenue and prev_revenue > 0:
                                result["revenue_growth"] = round((revenue - prev_revenue) / prev_revenue * 100, 2)
                            if net_profit is not None and prev_profit and prev_profit != 0:
                                result["net_profit_growth"] = round((net_profit - prev_profit) / abs(prev_profit) * 100, 2)
            except Exception as e:
                logger.warning(f"{code} 利润表获取失败: {e}")

            # === 资产负债表 ===
            try:
                df = ak.stock_financial_report_sina(stock=sina_code, symbol="资产负债表")
                if df is not None and not df.empty:
                    latest = df.iloc[0]
                    total_assets = self._parse_value(latest, "资产总计")
                    total_liabilities = self._parse_value(latest, "负债合计")
                    if total_assets and total_assets > 0 and total_liabilities is not None:
                        result["debt_ratio"] = round(total_liabilities / total_assets * 100, 2)
            except Exception as e:
                logger.warning(f"{code} 资产负债表获取失败: {e}")

            # === 现金流量表 ===
            try:
                df = ak.stock_financial_report_sina(stock=sina_code, symbol="现金流量表")
                if df is not None and not df.empty:
                    latest = df.iloc[0]
                    result["operating_cashflow"] = self._parse_value(latest, "经营活动产生的现金流量净额")
            except Exception as e:
                logger.warning(f"{code} 现金流量表获取失败: {e}")

            # === 主要指标 ===
            try:
                df = ak.stock_financial_analysis_indicator(symbol=code, start_year=str(datetime.now().year - 4))
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    result["roe"] = self._parse_value(latest, "净资产收益率")
                    result["gross_margin"] = self._parse_value(latest, "毛利率")
                    result["net_margin"] = self._parse_value(latest, "净利率")
            except Exception as e:
                logger.warning(f"{code} 主要指标获取失败: {e}")

            # === 估值指标 ===
            try:
                val_df = ak.stock_value_em(symbol=code)
                if val_df is not None and not val_df.empty:
                    v = val_df.iloc[-1]
                    result["pe_ttm"] = self._to_float(v.get("PE(TTM)"))
                    result["pb"] = self._to_float(v.get("市净率"))
                    result["ps_ttm"] = self._to_float(v.get("市销率"))
                    result["peg"] = self._to_float(v.get("PEG值"))

                    # 计算PEG
                    if result.get("pe_ttm") and result.get("net_profit_growth"):
                        if result["net_profit_growth"] > 0:
                            result["peg"] = round(result["pe_ttm"] / result["net_profit_growth"], 2)

                    pe_series = pd.to_numeric(val_df.get("PE(TTM)", pd.Series(dtype=float)), errors="coerce").dropna()
                    if not pe_series.empty and result.get("pe_ttm") is not None:
                        result["pe_percentile"] = round(float((pe_series < result["pe_ttm"]).mean() * 100), 1)

                    pb_series = pd.to_numeric(val_df.get("市净率", pd.Series(dtype=float)), errors="coerce").dropna()
                    if not pb_series.empty and result.get("pb") is not None:
                        result["pb_percentile"] = round(float((pb_series < result["pb"]).mean() * 100), 1)
            except Exception as e:
                logger.warning(f"{code} 估值指标获取失败: {e}")

            logger.info(f"AKShare {code} 基本面数据获取成功")
            return result
        except Exception as e:
            logger.error(f"AKShare {code} 基本面获取失败: {e}")
            return result if result != {"code": code} else None

    def _parse_value(self, row, key_contains: str):
        """从DataFrame行中解析数值"""
        for col in row.index:
            if key_contains in str(col):
                val = row[col]
                if pd.notna(val):
                    try:
                        return float(val)
                    except:
                        return None
        return None

    @staticmethod
    def _to_float(value) -> Optional[float]:
        try:
            if value is None or pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value) -> Optional[int]:
        try:
            if value is None or pd.isna(value):
                return None
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def get_sector_flow(self) -> Optional[pd.DataFrame]:
        """获取行业资金流向"""
        try:
            df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
            return df
        except Exception as e:
            logger.error(f"行业资金流向获取失败: {e}")
            return None

    def _retry_call(self, callable_obj, label: str, attempts: int = 3):
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                return callable_obj()
            except Exception as exc:
                last_error = exc
                logger.warning(f"AKShare {label} 第{attempt}次失败: {exc}")
                if attempt < attempts:
                    time.sleep(1.5 * attempt)
        logger.error(f"AKShare {label} 最终失败: {last_error}")
        return None
