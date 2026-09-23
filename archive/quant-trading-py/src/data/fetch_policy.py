"""
政策公告抓取模块
证监会、央行、上交所、深交所
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import feedparser

from config import DATA_SOURCE_CONFIG

logger = logging.getLogger("quant_trading")
UA = DATA_SOURCE_CONFIG["policy"]["user_agent"]


class PolicyFetcher:
    """政策公告抓取器"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})

    def fetch_csrc(self, limit: int = 15) -> List[Dict[str, Any]]:
        """证监会最新政策"""
        try:
            url = "http://www.csrc.gov.cn/csrc/c100028/common_list.shtml"
            r = self.session.get(url, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")
            items = []
            for li in soup.select(".er_list li, .fl_list li, .er_right_list li")[:limit]:
                a = li.find("a")
                if not a:
                    continue
                items.append({
                    "title": a.get_text(strip=True),
                    "url": a.get("href", ""),
                    "source": "中国证监会",
                    "category": "监管政策",
                    "publish_time": li.find("span").get_text(strip=True) if li.find("span") else "",
                    "fetched_at": datetime.now().isoformat(),
                })
            return items
        except Exception as e:
            logger.warning(f"证监会抓取失败: {e}")
            return []

    def fetch_pbc(self, limit: int = 10) -> List[Dict[str, Any]]:
        """央行货币政策"""
        try:
            url = "http://www.pbc.gov.cn/zhengcehuobisi/11140/index.html"
            r = self.session.get(url, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")
            items = []
            for li in soup.select(".newslist li, .newsList li, .list li")[:limit]:
                a = li.find("a")
                if not a:
                    continue
                items.append({
                    "title": a.get_text(strip=True),
                    "url": a.get("href", ""),
                    "source": "中国人民银行",
                    "category": "货币政策",
                    "publish_time": li.find("span").get_text(strip=True) if li.find("span") else "",
                    "fetched_at": datetime.now().isoformat(),
                })
            return items
        except Exception as e:
            logger.warning(f"央行抓取失败: {e}")
            return []

    def fetch_sse(self, limit: int = 10) -> List[Dict[str, Any]]:
        """上交所公告"""
        try:
            feed = feedparser.parse("http://www.sse.com.cn/lawsregulations/lawsAndRegulations/news/")
            return [
                {
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "source": "上海证券交易所",
                    "category": "交易所公告",
                    "publish_time": entry.get("published", ""),
                    "fetched_at": datetime.now().isoformat(),
                }
                for entry in feed.entries[:limit]
            ]
        except Exception as e:
            logger.warning(f"上交所抓取失败: {e}")
            return []

    def fetch_szse(self, limit: int = 10) -> List[Dict[str, Any]]:
        """深交所公告"""
        try:
            url = "https://www.szse.cn/api/search/content"
            r = self.session.post(url, json={"keyword": "", "time": 7, "range": "title", "channelCode": []}, timeout=20)
            data = r.json()
            items = data.get("data", [])[:limit]
            return [
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "source": "深圳证券交易所",
                    "category": "交易所公告",
                    "publish_time": item.get("publishTime", ""),
                    "fetched_at": datetime.now().isoformat(),
                }
                for item in items
            ]
        except Exception as e:
            logger.warning(f"深交所抓取失败: {e}")
            return []

    def fetch_all_policies(self) -> List[Dict[str, Any]]:
        """批量抓取所有政策源"""
        results = []
        for fetcher in [self.fetch_csrc, self.fetch_pbc, self.fetch_sse, self.fetch_szse]:
            try:
                items = fetcher()
                results.extend(items)
            except Exception as e:
                logger.warning(f"政策源 {fetcher.__name__} 失败: {e}")
        results.sort(key=lambda x: x.get("publish_time", ""), reverse=True)
        logger.info(f"共抓取 {len(results)} 条政策")
        return results
