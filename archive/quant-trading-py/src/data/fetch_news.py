"""
新闻采集模块 - 支持多源新闻抓取与个股关联
支持东方财富、财联社、雪球、新浪财经、CNBC、Reuters、Yahoo Finance
"""
import logging
import time
import json
import re
import hashlib
import os
import tempfile
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests
import feedparser
from bs4 import BeautifulSoup

from config import (
    DATA_SOURCE_CONFIG,
    DATA_DIR,
    STOCK_ALIASES,
    A_STOCK_WATCHLIST,
    HK_STOCK_WATCHLIST,
    US_STOCK_WATCHLIST,
    SENTIMENT_KEYWORDS,
    EVENT_KEYWORDS,
    OFFICIAL_NEWS_CONFIG,
)

logger = logging.getLogger("quant_trading")
UA = DATA_SOURCE_CONFIG["news"]["user_agent"]


class NewsFetcher:
    """新闻采集器 - 支持多源抓取与个股关联"""

    def __init__(self, seen_file: Path = None):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})
        self.official = dict(OFFICIAL_NEWS_CONFIG)
        self.all_aliases = self._build_alias_index()
        self.seen_file = Path(seen_file) if seen_file else Path(DATA_DIR) / "news" / "seen_news.json"
        self.a_codes = set(A_STOCK_WATCHLIST)
        self.hk_codes = set(HK_STOCK_WATCHLIST)
        self.us_codes = set(US_STOCK_WATCHLIST)

    def _build_alias_index(self) -> Dict[str, str]:
        """构建别名到股票代码的反向索引"""
        index = {}
        for code, aliases in STOCK_ALIASES.items():
            for alias in aliases:
                index.setdefault(alias.lower(), []).append(code)
        return index

    def _filter_symbol_candidates(self, candidates: List[str], text: str) -> List[str]:
        """Disambiguate cross-listed aliases using explicit market clues."""
        if len(candidates) <= 1:
            return candidates

        text_lower = text.lower()
        hk_hint = any(word in text_lower for word in ("港股", "香港", "hong kong", "hk stock"))
        us_hint = any(word in text_lower for word in ("美股", "美国股市", "nasdaq", "nyse", "us-listed", "adr"))
        a_hint = any(word in text_lower for word in ("a股", "沪市", "深市", "上交所", "深交所", "沪深"))

        if hk_hint and not us_hint:
            hk_candidates = [code for code in candidates if code in self.hk_codes]
            if hk_candidates:
                return hk_candidates
        if us_hint and not hk_hint:
            us_candidates = [code for code in candidates if code in self.us_codes]
            if us_candidates:
                return us_candidates
        if a_hint:
            a_candidates = [code for code in candidates if code in self.a_codes]
            if a_candidates:
                return a_candidates

        exact_matches = [code for code in candidates if code.lower() in text_lower]
        if exact_matches:
            return exact_matches
        return candidates

    def _match_stock_symbols(self, text: str) -> List[str]:
        """从文本中匹配关联的股票代码，并尽量消除跨市场歧义。"""
        text_lower = text.lower()
        matched = set()
        for alias, code in self.all_aliases.items():
            if alias in text_lower:
                candidates = self._filter_symbol_candidates(code, text)
                matched.update(candidates)
        return list(matched)

    def _news_item_id(self, item: Dict[str, Any]) -> str:
        key = "|".join(
            [
                str(item.get("title", "")).strip(),
                str(item.get("publish_time", "")).strip(),
                str(item.get("source", "")).strip(),
            ]
        ).lower()
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _load_seen_ids(self) -> Dict[str, str]:
        if not self.seen_file.exists():
            return {}
        try:
            data = json.loads(self.seen_file.read_text(encoding="utf-8"))
            return data.get("ids", {})
        except (OSError, ValueError):
            logger.warning("无法读取新闻去重文件，将重新开始记录")
            return {}

    def _save_seen_ids(self, seen_ids: Dict[str, str]) -> None:
        self.seen_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "ids": seen_ids}
        fd, temp_name = tempfile.mkstemp(prefix=".seen_news_", suffix=".json", dir=self.seen_file.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(temp_name, self.seen_file)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def _calc_sentiment_score(self, text: str) -> int:
        """计算文本情绪得分"""
        text_lower = text.lower()
        score = 0
        for w in SENTIMENT_KEYWORDS.get("positive", []):
            if w.lower() in text_lower:
                score += 1
        for w in SENTIMENT_KEYWORDS.get("negative", []):
            if w.lower() in text_lower:
                score -= 1
        return score

    def _calc_impact_score(self, text: str) -> int:
        """计算事件重要性得分"""
        text_lower = text.lower()
        score = 0
        for w in EVENT_KEYWORDS.get("high_impact", []):
            if w.lower() in text_lower:
                score += 3
        for w in EVENT_KEYWORDS.get("medium_impact", []):
            if w.lower() in text_lower:
                score += 1
        return score

    def _normalize_news_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """标准化新闻条目，添加个股关联和情绪/重要性评分"""
        text = f"{item.get('title', '')} {item.get('summary', '')}"
        related_symbols = self._match_stock_symbols(text)
        item["news_id"] = self._news_item_id(item)
        item["related_symbols"] = related_symbols
        item["related_symbol_details"] = [
            {
                "symbol": symbol,
                "method": "alias-rule",
                "ambiguous": self.all_aliases.get(self._first_matching_alias(text, symbol), [symbol]) != [symbol],
            }
            for symbol in related_symbols
        ]
        item["sentiment_score"] = self._calc_sentiment_score(text)
        item["impact_score"] = self._calc_impact_score(text)
        item["fetched_at"] = datetime.now().isoformat()
        return item

    def _first_matching_alias(self, text: str, symbol: str) -> str:
        text_lower = text.lower()
        for alias, symbols in self.all_aliases.items():
            if symbol in symbols and alias in text_lower:
                return alias
        return symbol

    # ========== 中文新闻源 ==========

    def fetch_eastmoney(self, limit: int = 30) -> List[Dict[str, Any]]:
        """抓取东方财富要闻"""
        try:
            url = "https://www.eastmoney.com/api/news"
            r = self.session.get(url, params={"type": "cywjh", "pageSize": limit}, timeout=20)
            data = r.json()
            items = data.get("result", {}).get("data", [])
            return [
                self._normalize_news_item({
                    "title": item.get("title", ""),
                    "summary": item.get("summary", "")[:200],
                    "url": item.get("url", ""),
                    "source": "东方财富",
                    "category": "财经要闻",
                    "publish_time": item.get("showTime", ""),
                })
                for item in items
            ]
        except Exception as e:
            logger.warning(f"东方财富新闻抓取失败: {e}")
            return []

    def fetch_cls(self, limit: int = 30) -> List[Dict[str, Any]]:
        """抓取财联社电报"""
        try:
            url = "https://www.cls.cn/api/sw"
            params = {"app": "CailianpressWeb", "os": "web", "sv": "8.4.6", "sign": ""}
            payload = {"channelId": "telegraph", "page": 1, "limit": limit}
            r = self.session.post(url, params=params, json=payload, timeout=20)
            data = r.json()
            items = data.get("data", {}).get("roll_data", [])
            return [
                self._normalize_news_item({
                    "title": item.get("title", ""),
                    "summary": item.get("content", "")[:300],
                    "url": item.get("shareurl", ""),
                    "source": "财联社",
                    "category": "市场电报",
                    "publish_time": item.get("ctime", ""),
                })
                for item in items
            ]
        except Exception as e:
            logger.warning(f"财联社抓取失败: {e}")
            return []

    def fetch_xueqiu_hots(self, limit: int = 20) -> List[Dict[str, Any]]:
        """抓取雪球热帖"""
        try:
            url = "https://xueqiu.com/statuses/hots.json"
            params = {"a": "1", "count": limit, "page": 1, "type": "normal", "meida": "weibo"}
            r = self.session.get(url, params=params, timeout=20)
            data = r.json()
            items = data.get("statuses", [])
            return [
                self._normalize_news_item({
                    "title": item.get("title", item.get("description", "")[:60]),
                    "summary": item.get("description", "")[:300],
                    "url": f"https://xueqiu.com{item.get('target', '')}",
                    "source": "雪球",
                    "category": "社区热帖",
                    "publish_time": item.get("created_at", ""),
                })
                for item in items
            ]
        except Exception as e:
            logger.warning(f"雪球热帖抓取失败: {e}")
            return []

    def fetch_sina_finance(self, limit: int = 20) -> List[Dict[str, Any]]:
        """抓取新浪财经"""
        try:
            url = "https://feed.sina.com.cn/api/roll/get"
            params = {"pageid": 153, "lid": 2516, "num": 50, "page": 1}
            r = self.session.get(url, params=params, timeout=20)
            data = r.json()
            items = data.get("result", {}).get("data", [])[:limit]
            return [
                self._normalize_news_item({
                    "title": item.get("title", ""),
                    "summary": item.get("summary", "")[:200],
                    "url": item.get("url", ""),
                    "source": "新浪财经",
                    "category": "市场资讯",
                    "publish_time": self._normalize_publish_time(item.get("ctime")),
                })
                for item in items
            ]
        except Exception as e:
            logger.warning(f"新浪财经抓取失败: {e}")
            return []

    @staticmethod
    def _normalize_publish_time(value) -> str:
        if value in (None, ""):
            return ""
        try:
            timestamp = float(value)
            return datetime.fromtimestamp(timestamp).isoformat()
        except (TypeError, ValueError, OSError):
            return str(value)

    # ========== 英文新闻源 ==========

    def fetch_cnbc(self, limit: int = 20) -> List[Dict[str, Any]]:
        """抓取 CNBC RSS"""
        try:
            feed = self._parse_feed("https://www.cnbc.com/id/100003114/device/rss/rss.html")
            return [
                self._normalize_news_item({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:300],
                    "url": entry.get("link", ""),
                    "source": "CNBC",
                    "category": "Global Markets",
                    "publish_time": entry.get("published", ""),
                })
                for entry in feed.entries[:limit]
            ]
        except Exception as e:
            logger.warning(f"CNBC RSS抓取失败: {e}")
            return []

    def fetch_reuters(self, limit: int = 20) -> List[Dict[str, Any]]:
        """抓取 Reuters RSS"""
        try:
            feed = self._parse_feed("https://www.reutersagency.com/feed/?best-topics=business-finance")
            return [
                self._normalize_news_item({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:300],
                    "url": entry.get("link", ""),
                    "source": "Reuters",
                    "category": "Business",
                    "publish_time": entry.get("published", ""),
                })
                for entry in feed.entries[:limit]
            ]
        except Exception as e:
            logger.warning(f"Reuters RSS抓取失败: {e}")
            return []

    def fetch_yahoo_finance_news(self, symbols: List[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """抓取 Yahoo Finance 个股新闻"""
        if not symbols:
            symbols = list(US_STOCK_WATCHLIST.keys())[:10]
        all_news = []
        for sym in symbols[:5]:  # 限制请求数量避免被封
            try:
                feed_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region=US&lang=en-US"
                feed = self._parse_feed(feed_url)
                for entry in feed.entries[:limit]:
                    all_news.append(self._normalize_news_item({
                        "title": entry.get("title", ""),
                        "summary": entry.get("summary", "")[:300],
                        "url": entry.get("link", ""),
                        "source": "Yahoo Finance",
                        "category": f"Stock:{sym}",
                        "publish_time": entry.get("published", ""),
                    }))
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"Yahoo Finance {sym} 新闻抓取失败: {e}")
        return all_news

    def _parse_feed(self, url: str):
        """抓取 RSS/Atom，带超时和 UA，避免无超时挂起。"""
        response = self.session.get(
            url,
            timeout=float(DATA_SOURCE_CONFIG["news"]["rss_timeout"]),
        )
        response.raise_for_status()
        return feedparser.parse(response.content)

    # ========== 官方新闻源 ==========

    def fetch_official_news(self, limit: int = 20) -> List[Dict[str, Any]]:
        """官方新闻源：NewsAPI + Tushare Pro，未配置时返回空。"""
        results = []
        if self.official.get("newsapi_key"):
            results.extend(self.fetch_newsapi(limit=limit))
        if self.official.get("tushare_token"):
            results.extend(self.fetch_tushare(limit=limit))
        return results

    def fetch_newsapi(self, limit: int = 20) -> List[Dict[str, Any]]:
        """NewsAPI 官方接口抓取全球财经新闻。"""
        try:
            url = "https://newsapi.org/v2/top-headlines"
            params = {
                "category": self.official.get("newsapi_category", "business"),
                "language": self.official.get("newsapi_language", "en"),
                "pageSize": max(1, min(int(limit), 100)),
                "apiKey": self.official["newsapi_key"],
            }
            response = self.session.get(url, params=params, timeout=20)
            data = response.json()
            if data.get("status") != "ok":
                logger.warning(f"NewsAPI 返回异常: {data.get('code', 'unknown')}")
                return []
            return [
                self._normalize_news_item({
                    "title": item.get("title", ""),
                    "summary": item.get("description", "")[:300],
                    "url": item.get("url", ""),
                    "source": (item.get("source") or {}).get("name", "NewsAPI"),
                    "category": "Global News",
                    "publish_time": item.get("publishedAt", ""),
                })
                for item in data.get("articles", [])[:limit]
            ]
        except Exception as e:
            logger.warning(f"NewsAPI 抓取失败: {e}")
            return []

    def fetch_tushare(self, limit: int = 20, pro=None) -> List[Dict[str, Any]]:
        """Tushare Pro 官方 SDK 抓取财经快讯，需要 token 和积分。"""
        try:
            if pro is None:
                import tushare as ts

                pro = ts.pro_api(self.official["tushare_token"])
            today = datetime.now()
            df = pro.news(
                src="",
                start_date=today.strftime("%Y-%m-%d 00:00:00"),
                end_date=today.strftime("%Y-%m-%d %H:%M:%S"),
                page_no=1,
                page_size=int(limit),
            )
            if df is None or df.empty:
                logger.info("Tushare 新闻接口无数据")
                return []
            return [
                self._normalize_news_item({
                    "title": str(row.get("title", "")),
                    "summary": str(row.get("content", ""))[:300],
                    "url": "",
                    "source": f"Tushare-{str(row.get('src', '快讯'))}",
                    "category": "A股快讯",
                    "publish_time": str(row.get("datetime", "")),
                })
                for _, row in df.iterrows()
            ]
        except Exception as e:
            logger.warning(f"Tushare 新闻抓取失败: {e}")
            return []

    # ========== 汇总接口 ==========

    def fetch_all_news(self, per_source_limit: int = 20) -> List[Dict[str, Any]]:
        """聚合抓取新闻源：优先官方 API，未配置或失败时回退到页面抓取。"""
        seen_ids = self._load_seen_ids()
        results = []

        official_items = self.fetch_official_news(limit=per_source_limit)
        results.extend(official_items)
        use_official_only = bool(official_items) and self.official.get("official_first", True)

        if use_official_only:
            logger.info(f"官方新闻源可用，跳过页面抓取，共 {len(official_items)} 条")
        else:
            fetchers = [
                self.fetch_eastmoney,
                self.fetch_cls,
                self.fetch_sina_finance,
                self.fetch_xueqiu_hots,
                self.fetch_cnbc,
                self.fetch_reuters,
            ]
            for fetcher in fetchers:
                try:
                    items = fetcher(limit=per_source_limit)
                    results.extend(items)
                    time.sleep(0.3)
                except Exception as e:
                    logger.warning(f"新闻源 {fetcher.__name__} 失败: {e}")

            # Yahoo Finance 个股新闻
            try:
                yahoo_news = self.fetch_yahoo_finance_news(limit=per_source_limit)
                results.extend(yahoo_news)
            except Exception as e:
                logger.warning(f"Yahoo Finance 新闻失败: {e}")

        # 去重，并过滤此前已经处理过的新闻。
        seen = set()
        unique = []
        for item in results:
            key = item["title"].strip()
            news_id = item.get("news_id")
            if key and key not in seen and news_id not in seen_ids:
                seen.add(key)
                seen_ids[news_id] = datetime.now().isoformat()
                unique.append(item)

        self._save_seen_ids(seen_ids)

        # 按重要性+时间排序
        unique.sort(key=lambda x: (x.get("impact_score", 0), x.get("publish_time", "")), reverse=True)
        logger.info(f"共抓取 {len(unique)} 条新闻")
        return unique

    def get_stock_related_news(self, news: List[Dict[str, Any]], symbol: str) -> List[Dict[str, Any]]:
        """获取与特定股票相关的新闻"""
        related = [n for n in news if symbol in n.get("related_symbols", [])]
        related.sort(key=lambda x: x.get("impact_score", 0), reverse=True)
        return related

    def generate_daily_summary(self, news: List[Dict[str, Any]]) -> Dict[str, Any]:
        """生成每日新闻总结"""
        # 按股票分组
        stock_news_map = {}
        for item in news:
            for sym in item.get("related_symbols", []):
                if sym not in stock_news_map:
                    stock_news_map[sym] = []
                stock_news_map[sym].append(item)

        # 全局要闻 (高重要性且未关联到个股)
        global_news = [n for n in news if not n.get("related_symbols") and n.get("impact_score", 0) > 0]
        global_news.sort(key=lambda x: x.get("impact_score", 0), reverse=True)

        # 每只股票的摘要
        stock_summaries = {}
        for sym, items in stock_news_map.items():
            items_sorted = sorted(items, key=lambda x: x.get("impact_score", 0), reverse=True)
            pos_count = sum(1 for i in items_sorted if i.get("sentiment_score", 0) > 0)
            neg_count = sum(1 for i in items_sorted if i.get("sentiment_score", 0) < 0)
            total_sentiment = sum(i.get("sentiment_score", 0) for i in items_sorted)
            top_titles = [i["title"] for i in items_sorted[:3]]
            stock_summaries[sym] = {
                "news_count": len(items_sorted),
                "positive_count": pos_count,
                "negative_count": neg_count,
                "total_sentiment": total_sentiment,
                "top_news": items_sorted[:5],
                "summary": "; ".join(top_titles) if top_titles else "今日无重要消息",
            }

        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "total_news": len(news),
            "global_headlines": global_news[:10],
            "stock_summaries": stock_summaries,
        }
