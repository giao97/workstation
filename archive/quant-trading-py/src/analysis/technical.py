"""
技术分析引擎 - 纯 pandas/numpy 实现
"""
import logging
from typing import Dict, Any, Optional, Tuple

import pandas as pd
import numpy as np

from config import TECHNICAL_PARAMS

logger = logging.getLogger("quant_trading")


class TechnicalAnalyzer:
    """技术指标计算器"""

    def __init__(self, params: Dict = None):
        self.params = params or TECHNICAL_PARAMS

    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算所有技术指标并添加到 DataFrame"""
        df = df.copy()
        close = df["close"]
        high = df["high"] if "high" in df.columns else close
        low = df["low"] if "low" in df.columns else close
        volume = df["volume"] if "volume" in df.columns else pd.Series([0] * len(df), index=df.index)

        # 均线
        for p in self.params.get("ma_periods", [5, 10, 20, 60]):
            df[f"ma{p}"] = close.rolling(window=p).mean()

        # EMA
        for p in self.params.get("ema_periods", [12, 26]):
            df[f"ema{p}"] = close.ewm(span=p, adjust=False).mean()

        # RSI
        df["rsi"] = self._rsi(close, self.params.get("rsi_period", 14))

        # MACD
        macd, signal, hist = self._macd(close, self.params.get("macd_fast", 12), self.params.get("macd_slow", 26), self.params.get("macd_signal", 9))
        df["macd"] = macd
        df["macd_signal"] = signal
        df["macd_hist"] = hist

        # 布林带
        bb_upper, bb_middle, bb_lower = self._bollinger(close, self.params.get("bollinger_period", 20), self.params.get("bollinger_std", 2))
        df["bb_upper"] = bb_upper
        df["bb_middle"] = bb_middle
        df["bb_lower"] = bb_lower

        # KDJ
        k, d, j = self._kdj(high, low, close, self.params.get("kdj_k_period", 9), self.params.get("kdj_d_period", 3))
        df["kdj_k"] = k
        df["kdj_d"] = d
        df["kdj_j"] = j

        # ATR
        df["atr"] = self._atr(high, low, close, self.params.get("atr_period", 14))

        # OBV
        df["obv"] = self._obv(close, volume)

        # 成交量均线
        for p in self.params.get("volume_ma_periods", [5, 20]):
            df[f"vol_ma{p}"] = volume.rolling(window=p).mean()

        return df

    def _rsi(self, close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        loss_safe = loss.replace(0, np.nan)
        rs = gain / loss_safe
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.where(pd.notna(rs), 50.0)
        return rsi.mask(np.isinf(rs), 100.0)

    def _macd(self, close: pd.Series, fast: int, slow: int, signal: int) -> Tuple[pd.Series, pd.Series, pd.Series]:
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        hist = macd_line - signal_line
        return macd_line, signal_line, hist

    def _bollinger(self, close: pd.Series, period: int = 20, std_dev: int = 2) -> Tuple[pd.Series, pd.Series, pd.Series]:
        middle = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()
        upper = middle + std_dev * std
        lower = middle - std_dev * std
        return upper, middle, lower

    def _kdj(self, high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9, m: int = 3) -> Tuple[pd.Series, pd.Series, pd.Series]:
        lowest_low = low.rolling(window=n).min()
        highest_high = high.rolling(window=n).max()
        rsv = (close - lowest_low) / (highest_high - lowest_low) * 100
        rsv = rsv.fillna(50.0)
        k = rsv.ewm(com=m - 1, adjust=False).mean()
        d = k.ewm(com=m - 1, adjust=False).mean()
        j = 3 * k - 2 * d
        return k, d, j

    def _atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    def _obv(self, close: pd.Series, volume: pd.Series) -> pd.Series:
        if close.empty:
            return pd.Series(dtype=float)
        obv = [volume.iloc[0]]
        for i in range(1, len(close)):
            if close.iloc[i] > close.iloc[i - 1]:
                obv.append(obv[-1] + volume.iloc[i])
            elif close.iloc[i] < close.iloc[i - 1]:
                obv.append(obv[-1] - volume.iloc[i])
            else:
                obv.append(obv[-1])
        return pd.Series(obv, index=close.index)

    def get_latest_signals(self, df: pd.DataFrame) -> Dict[str, Any]:
        """获取最新行指标信号"""
        if df.empty:
            return {}
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last

        def num(value):
            return float(value) if pd.notna(value) else None

        signals = {
            "close": num(last.get("close")),
            "prev_close": num(prev.get("close")),
            "price_change_pct": (
                round((last.get("close") - prev.get("close")) / prev.get("close") * 100, 4)
                if pd.notna(last.get("close")) and pd.notna(prev.get("close")) and prev.get("close") != 0
                else None
            ),
            "ma5": num(last.get("ma5")),
            "ma20": num(last.get("ma20")),
            "ma60": num(last.get("ma60")),
            "rsi": num(last.get("rsi")),
            "macd": num(last.get("macd")),
            "macd_signal": num(last.get("macd_signal")),
            "bb_upper": num(last.get("bb_upper")),
            "bb_lower": num(last.get("bb_lower")),
            "kdj_k": num(last.get("kdj_k")),
            "kdj_d": num(last.get("kdj_d")),
            "kdj_j": num(last.get("kdj_j")),
            "atr": num(last.get("atr")),
            "volume": num(last.get("volume")),
            "vol_ma20": num(last.get("vol_ma20")),
        }

        # 交叉信号
        signals["macd_golden_cross"] = bool(
            signals["macd"] is not None
            and signals["macd_signal"] is not None
            and prev.get("macd", 0) <= prev.get("macd_signal", 0)
            and last["macd"] > last["macd_signal"]
        )
        signals["macd_death_cross"] = bool(
            signals["macd"] is not None
            and signals["macd_signal"] is not None
            and prev.get("macd", 0) >= prev.get("macd_signal", 0)
            and last["macd"] < last["macd_signal"]
        )
        signals["price_above_ma20"] = bool(
            signals["close"] is not None and signals["ma20"] is not None and signals["close"] > signals["ma20"]
        )
        signals["price_below_ma20"] = bool(
            signals["close"] is not None and signals["ma20"] is not None and signals["close"] < signals["ma20"]
        )
        signals["kdj_golden_cross"] = bool(
            signals["kdj_k"] is not None
            and signals["kdj_d"] is not None
            and prev.get("kdj_k", 0) <= prev.get("kdj_d", 0)
            and last["kdj_k"] > last["kdj_d"]
            and last["kdj_k"] < 50
        )
        signals["kdj_death_cross"] = bool(
            signals["kdj_k"] is not None
            and signals["kdj_d"] is not None
            and prev.get("kdj_k", 0) >= prev.get("kdj_d", 0)
            and last["kdj_k"] < last["kdj_d"]
            and last["kdj_k"] > 50
        )

        return signals
