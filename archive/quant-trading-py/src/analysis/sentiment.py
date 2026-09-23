"""
情绪分析增强版 - 支持个股级情绪分析与市场整体情绪
"""
import logging
import re
from typing import List, Dict, Any

from config import SENTIMENT_KEYWORDS, EVENT_KEYWORDS, STOCK_ALIASES

logger = logging.getLogger("quant_trading")


class SentimentAnalyzer:
    """情绪分析器 - 支持个股级与市场级分析"""

    negators = (
        "不",
        "没",
        "未",
        "否",
        "无",
        "缺乏",
        "难以",
        "不会",
        "没有",
        "并无",
        "并未",
        "not",
        "no",
        "without",
        "never",
        "fails",
        "failed",
    )

    def __init__(self):
        self.pos_words = [w.lower() for w in SENTIMENT_KEYWORDS.get("positive", [])]
        self.neg_words = [w.lower() for w in SENTIMENT_KEYWORDS.get("negative", [])]
        self.high_impact = [w.lower() for w in EVENT_KEYWORDS.get("high_impact", [])]
        self.medium_impact = [w.lower() for w in EVENT_KEYWORDS.get("medium_impact", [])]

    def analyze_item(self, item: Dict[str, Any], symbol: str = None) -> Dict[str, Any]:
        """分析单条新闻/政策的情绪"""
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        score = 0
        matched_pos = set()
        matched_neg = set()

        score += self._weighted_keyword_score(text, self.pos_words, direction=1, matched=matched_pos)
        score += self._weighted_keyword_score(text, self.neg_words, direction=-1, matched=matched_neg)

        # 关联度加权
        relevance = 1
        if symbol:
            aliases = STOCK_ALIASES.get(symbol, [symbol])
            if any(alias.lower() in text for alias in aliases):
                relevance = 3

        final = score * relevance
        sentiment = self._label(final)

        return {
            **item,
            "sentiment_score": final,
            "sentiment": sentiment,
            "matched_positive": sorted(matched_pos),
            "matched_negative": sorted(matched_neg),
            "relevance": relevance,
            "analysis_method": "rule-keyword-with-negation",
        }

    def _weighted_keyword_score(self, text: str, words: List[str], direction: int, matched: set) -> int:
        score = 0
        for word in words:
            matches = list(self._find_keyword(text, word))
            if not matches:
                continue

            positive_count = 0
            negative_count = 0
            for start in matches:
                if self._is_negated(text, start):
                    negative_count += 1
                else:
                    positive_count += 1

            net_count = positive_count - negative_count
            if net_count:
                matched.add(word)
                score += direction * net_count
        return score

    def _find_keyword(self, text: str, word: str) -> list[int]:
        word = word.lower()
        if not word:
            return []
        if re.fullmatch(r"[a-z0-9 .%/-]+", word):
            pattern = rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])"
        else:
            pattern = re.escape(word)
        return [match.start() for match in re.finditer(pattern, text)]

    def _is_negated(self, text: str, keyword_start: int) -> bool:
        prefix = text[max(0, keyword_start - 8):keyword_start]
        return any(negator in prefix for negator in self.negators)

    def analyze_news_and_policies(self, news: List[Dict], policies: List[Dict]) -> Dict[str, Any]:
        """分析全局市场情绪"""
        news_analyzed = [self.analyze_item(n) for n in news]
        policy_analyzed = [self.analyze_item(p) for p in policies]

        news_score = sum(n["sentiment_score"] for n in news_analyzed) / max(len(news_analyzed), 1)
        policy_score = sum(p["sentiment_score"] for p in policy_analyzed) / max(len(policy_analyzed), 1)
        combined = news_score * 0.4 + policy_score * 0.6

        overall = self._market_label(combined)

        pos_news = sorted([n for n in news_analyzed if n["sentiment_score"] > 0], key=lambda x: x["sentiment_score"], reverse=True)[:5]
        neg_news = sorted([n for n in news_analyzed if n["sentiment_score"] < 0], key=lambda x: x["sentiment_score"])[:5]

        summary_parts = [f"当前市场情绪综合判断: {overall}"]
        if pos_news:
            summary_parts.append(f"主要利好: {', '.join(n['title'][:30] for n in pos_news[:3])}")
        if neg_news:
            summary_parts.append(f"主要利空: {', '.join(n['title'][:30] for n in neg_news[:3])}")

        return {
            "overall": overall,
            "combined_score": round(combined, 2),
            "news_score": round(news_score, 2),
            "policy_score": round(policy_score, 2),
            "top_positive": pos_news,
            "top_negative": neg_news,
            "summary": "\n".join(summary_parts),
            "news_analyzed": news_analyzed,
            "policy_analyzed": policy_analyzed,
        }

    def analyze_stock_sentiment(self, news: List[Dict], symbol: str) -> Dict[str, Any]:
        """分析单只股票的情绪"""
        related = [n for n in news if symbol in n.get("related_symbols", [])]
        if not related:
            return {
                "symbol": symbol,
                "news_count": 0,
                "sentiment_score": 0,
                "sentiment": "中性",
                "top_news": [],
                "summary": "今日无相关消息",
            }

        analyzed = [self.analyze_item(n, symbol) for n in related]
        avg_score = sum(a["sentiment_score"] for a in analyzed) / len(analyzed)

        pos = [a for a in analyzed if a["sentiment_score"] > 0]
        neg = [a for a in analyzed if a["sentiment_score"] < 0]

        top = sorted(analyzed, key=lambda x: abs(x.get("sentiment_score", 0)) + x.get("impact_score", 0), reverse=True)[:5]

        summary = f"今日{len(related)}条相关消息，"
        if avg_score > 1:
            summary += f"整体偏正面({avg_score:.1f})"
        elif avg_score < -1:
            summary += f"整体偏负面({avg_score:.1f})"
        else:
            summary += "整体中性"

        if pos:
            summary += f"，利好{len(pos)}条"
        if neg:
            summary += f"，利空{len(neg)}条"

        return {
            "symbol": symbol,
            "news_count": len(related),
            "sentiment_score": round(avg_score, 2),
            "sentiment": self._label(avg_score),
            "positive_count": len(pos),
            "negative_count": len(neg),
            "top_news": top,
            "summary": summary,
        }

    def _label(self, score: float) -> str:
        if score >= 3:
            return "强正面"
        elif score >= 1:
            return "正面"
        elif score <= -3:
            return "强负面"
        elif score <= -1:
            return "负面"
        else:
            return "中性"

    def _market_label(self, score: float) -> str:
        if score >= 2.5:
            return "极度乐观"
        elif score >= 1:
            return "偏乐观"
        elif score <= -2.5:
            return "极度悲观"
        elif score <= -1:
            return "偏悲观"
        else:
            return "中性观望"
