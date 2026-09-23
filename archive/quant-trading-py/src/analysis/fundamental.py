"""
基本面分析增强版 - 估值/质量/成长/风险/现金流 五维评分
支持A股(akshare)和美股(Yahoo Finance)的深入基本面分析
"""
import logging
from typing import Dict, Any, Optional

from config import FUNDAMENTAL_WEIGHTS

logger = logging.getLogger("quant_trading")


class FundamentalAnalyzer:
    """基本面分析器 - 五维评分体系"""

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """分析A股基本面数据"""
        if not data:
            return self.missing_result()

        scores = {"valuation": 50, "quality": 50, "growth": 50, "risk": 50, "cashflow": 50}
        flags = []
        risks = []

        pe = data.get("pe_ttm")
        pb = data.get("pb")
        ps = data.get("ps_ttm")
        roe = data.get("roe")
        gross = data.get("gross_margin")
        net = data.get("net_margin")
        rev_growth = data.get("revenue_growth")
        profit_growth = data.get("net_profit_growth")
        debt_ratio = data.get("debt_ratio")
        ocf = data.get("operating_cashflow")
        peg = data.get("peg")
        pe_percentile = data.get("pe_percentile")
        pb_percentile = data.get("pb_percentile")

        # === 估值维度 ===
        if pe is not None and pe > 0:
            if pe > 60:
                scores["valuation"] -= 25
                risks.append(f"PE {pe:.1f} 过高，估值泡沫风险")
            elif pe > 40:
                scores["valuation"] -= 15
                risks.append(f"PE {pe:.1f} 偏高，注意估值风险")
            elif pe < 15:
                scores["valuation"] += 20
                flags.append(f"PE {pe:.1f} 偏低，估值安全边际高")
            elif pe < 25:
                scores["valuation"] += 10
                flags.append(f"PE {pe:.1f} 合理")

        if pb is not None and pb > 0:
            if pb < 1.5:
                scores["valuation"] += 10
            elif pb > 5:
                scores["valuation"] -= 10
                risks.append(f"PB {pb:.1f} 偏高")

        if ps is not None and ps > 0 and ps > 10:
            scores["valuation"] -= 5

        if peg is not None and peg > 0:
            if peg < 1:
                scores["valuation"] += 15
                flags.append(f"PEG {peg:.2f} < 1，成长性价比优秀")
            elif peg > 2:
                scores["valuation"] -= 10
                risks.append(f"PEG {peg:.2f} > 2，成长性价比一般")

        if pe_percentile is not None:
            if pe_percentile < 30:
                scores["valuation"] += 10
                flags.append(f"PE处于近5年{pe_percentile:.0f}%分位，估值偏低")
            elif pe_percentile > 70:
                scores["valuation"] -= 10
                risks.append(f"PE处于近5年{pe_percentile:.0f}%分位，估值偏高")

        if pb_percentile is not None:
            if pb_percentile < 30:
                scores["valuation"] += 5
            elif pb_percentile > 70:
                scores["valuation"] -= 5

        # === 质量维度 ===
        if roe is not None:
            if roe > 20:
                scores["quality"] += 20
                flags.append(f"ROE {roe:.1f}% 优秀")
            elif roe > 15:
                scores["quality"] += 10
                flags.append(f"ROE {roe:.1f}% 良好")
            elif roe > 10:
                scores["quality"] += 5
            elif roe < 5:
                scores["quality"] -= 15
                risks.append(f"ROE {roe:.1f}% 偏低")

        if gross is not None:
            if gross > 40:
                scores["quality"] += 10
                flags.append(f"毛利率 {gross:.1f}% 优秀")
            elif gross > 25:
                scores["quality"] += 5
            elif gross < 10:
                scores["quality"] -= 10
                risks.append(f"毛利率 {gross:.1f}% 偏低")

        if net is not None:
            if net > 20:
                scores["quality"] += 10
            elif net < 5:
                scores["quality"] -= 5

        # === 成长维度 ===
        if rev_growth is not None:
            if rev_growth > 30:
                scores["growth"] += 20
                flags.append(f"营收增长 {rev_growth:.1f}% 强劲")
            elif rev_growth > 15:
                scores["growth"] += 10
                flags.append(f"营收增长 {rev_growth:.1f}% 良好")
            elif rev_growth > 0:
                scores["growth"] += 5
            else:
                scores["growth"] -= 15
                risks.append(f"营收增长 {rev_growth:.1f}% 下滑")

        if profit_growth is not None:
            if profit_growth > 30:
                scores["growth"] += 10
                flags.append(f"净利润增长 {profit_growth:.1f}% 强劲")
            elif profit_growth > 15:
                scores["growth"] += 5
            elif profit_growth < 0:
                scores["growth"] -= 10
                risks.append(f"净利润增长 {profit_growth:.1f}% 下滑")

        # === 风险维度 ===
        if debt_ratio is not None:
            if debt_ratio > 80:
                scores["risk"] -= 25
                risks.append(f"资产负债率 {debt_ratio:.1f}% 过高，偿债风险")
            elif debt_ratio > 70:
                scores["risk"] -= 15
                risks.append(f"资产负债率 {debt_ratio:.1f}% 偏高")
            elif debt_ratio < 40:
                scores["risk"] += 15
                flags.append(f"资产负债率 {debt_ratio:.1f}% 较低")
            elif debt_ratio < 60:
                scores["risk"] += 5

        # === 现金流维度 ===
        if ocf is not None:
            if ocf > 0:
                scores["cashflow"] += 15
                flags.append("经营现金流为正")
            else:
                scores["cashflow"] -= 15
                risks.append("经营现金流为负")

        # 限制分数范围
        for k in scores:
            scores[k] = max(0, min(100, scores[k]))

        total = round(sum(scores[k] * FUNDAMENTAL_WEIGHTS[k] for k in scores))
        rating = self._rating(total)

        return {
            "scores": scores,
            "total_score": total,
            "rating": rating,
            "flags": flags[:6],
            "risks": risks[:6],
            "raw": data,
            "available": True,
        }

    def analyze_us(self, info: Dict[str, Any]) -> Dict[str, Any]:
        """分析美股基本面数据 (Yahoo info格式)"""
        if not info:
            return self.missing_result()

        scores = {"valuation": 50, "quality": 50, "growth": 50, "risk": 50, "cashflow": 50}
        flags = []
        risks = []

        pe = info.get("pe_ratio")
        pb = info.get("pb_ratio")
        forward_pe = info.get("forward_pe")
        roe = info.get("roe")
        rev_growth = info.get("revenue_growth")
        earnings_growth = info.get("earnings_growth")
        profit_margin = info.get("profit_margins")
        debt_to_equity = info.get("debt_to_equity")
        free_cashflow = info.get("free_cashflow")
        operating_cashflow = info.get("operating_cashflow")
        eps_growth = info.get("eps_growth")
        rec = info.get("recommendation")

        # === 估值 ===
        if pe is not None and pe > 0:
            if pe > 60:
                scores["valuation"] -= 25
                risks.append(f"PE {pe:.1f} 过高，估值泡沫风险")
            elif pe > 40:
                scores["valuation"] -= 15
                risks.append(f"PE {pe:.1f} 偏高，注意估值风险")
            elif pe < 15:
                scores["valuation"] += 20
                flags.append(f"PE {pe:.1f} 偏低")
        if forward_pe and pe and forward_pe < pe * 0.85:
            scores["growth"] += 10
            flags.append("远期PE低于当前PE，盈利预期改善")

        # === 质量 ===
        if roe is not None:
            if roe > 0.20:
                scores["quality"] += 20
                flags.append(f"ROE {roe*100:.1f}% 优秀")
            elif roe > 0.15:
                scores["quality"] += 10
            elif roe < 0.05:
                scores["quality"] -= 15
                risks.append(f"ROE {roe*100:.1f}% 偏低")

        if profit_margin is not None:
            if profit_margin > 0.20:
                scores["quality"] += 10
            elif profit_margin < 0.05:
                scores["quality"] -= 10
                risks.append(f"利润率 {profit_margin*100:.1f}% 偏低")

        # === 成长 ===
        if rev_growth is not None:
            if rev_growth > 0.30:
                scores["growth"] += 20
                flags.append(f"营收增长 {rev_growth*100:.1f}% 强劲")
            elif rev_growth > 0.15:
                scores["growth"] += 10
            elif rev_growth < 0:
                scores["growth"] -= 15
                risks.append("营收下滑")

        if earnings_growth is not None:
            if earnings_growth > 0.30:
                scores["growth"] += 10
            elif earnings_growth < 0:
                scores["growth"] -= 10
                risks.append("盈利下滑")

        if eps_growth is not None:
            if eps_growth > 0.20:
                scores["growth"] += 5

        # === 风险 ===
        if debt_to_equity is not None:
            if debt_to_equity < 0.5:
                scores["risk"] += 15
                flags.append("债务水平较低")
            elif debt_to_equity > 1.0:
                scores["risk"] -= 15
                risks.append("债务股本比偏高")

        # === 现金流 ===
        if free_cashflow is not None:
            if free_cashflow > 0:
                scores["cashflow"] += 15
                flags.append("自由现金流为正")
            else:
                scores["cashflow"] -= 10
        elif operating_cashflow is not None:
            if operating_cashflow > 0:
                scores["cashflow"] += 10
            else:
                scores["cashflow"] -= 10

        if rec:
            rec_map = {"strong_buy": 15, "buy": 10, "hold": 0, "sell": -10, "strong_sell": -15}
            scores["valuation"] += rec_map.get(rec, 0)
            flags.append(f"分析师共识: {rec}")

        for k in scores:
            scores[k] = max(0, min(100, scores[k]))

        total = round(sum(scores[k] * FUNDAMENTAL_WEIGHTS[k] for k in scores))
        rating = self._rating(total)

        return {
            "scores": scores,
            "total_score": total,
            "rating": rating,
            "flags": flags[:6],
            "risks": risks[:6],
            "raw": info,
            "available": True,
        }

    def _rating(self, total: int) -> str:
        if total >= 80:
            return "优秀"
        elif total >= 65:
            return "良好"
        elif total >= 50:
            return "一般"
        elif total >= 35:
            return "较差"
        else:
            return "危险"

    def missing_result(self) -> Dict[str, Any]:
        return {
            "scores": {},
            "total_score": None,
            "rating": "数据不足",
            "flags": [],
            "risks": [],
            "raw": {},
            "available": False,
        }
