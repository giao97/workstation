"""新闻中文翻译 - 使用 OpenAI API，未配置 Key 时原样返回。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from config import OPENAI_CONFIG

logger = logging.getLogger("quant_trading")


def _is_latin_text(text: str) -> bool:
    letters = sum(1 for char in text if char.isalpha())
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return letters > 10 and cjk / max(letters, 1) < 0.1


def _extract_json_array(content: str) -> List[Dict[str, Any]]:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
    start = content.find("[")
    end = content.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("响应中未找到 JSON 数组")
    return json.loads(content[start : end + 1])


class NewsTranslator:
    """把英文新闻标题/摘要批量翻译成中文。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None, client: Any = None):
        self.cfg = dict(config or OPENAI_CONFIG)
        self._client = client

    def is_configured(self) -> bool:
        return bool(self.cfg.get("api_key")) and bool(self.cfg.get("enabled"))

    def translate_news(self, news: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self.is_configured():
            return news
        items = [item for item in news if self._needs_translation(item)]
        if not items:
            logger.info("没有需要翻译的英文新闻")
            return news
        try:
            client = self._client or self._build_client()
            translated = self._translate_items(client, items)
        except Exception as e:
            logger.error(f"新闻翻译失败，保留原文: {e}")
            return news

        translated_by_id = {item.get("news_id"): item for item in translated if item.get("news_id")}
        changed = 0
        for original in items:
            result = translated_by_id.get(original.get("news_id"))
            if not result:
                continue
            title = result.get("title")
            summary = result.get("summary")
            if title:
                original["title_en"] = original.get("title", "")
                original["title"] = title
                changed += 1
            if summary:
                original["summary_en"] = original.get("summary", "")
                original["summary"] = summary
        logger.info(f"已完成新闻中文翻译: 更新 {changed} 条")
        return news

    def _build_client(self) -> Any:
        from openai import OpenAI

        kwargs = {"api_key": self.cfg["api_key"]}
        if self.cfg.get("base_url"):
            kwargs["base_url"] = self.cfg["base_url"]
        return OpenAI(**kwargs)

    def _needs_translation(self, item: Dict[str, Any]) -> bool:
        title = str(item.get("title") or "")
        summary = str(item.get("summary") or "")
        return _is_latin_text(title) or _is_latin_text(summary)

    def _translate_items(self, client: Any, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        translated = []
        for index in range(0, len(items), 10):
            chunk = items[index : index + 10]
            payload = [
                {
                    "news_id": item.get("news_id", ""),
                    "title": str(item.get("title", "")),
                    "summary": str(item.get("summary", ""))[:300],
                }
                for item in chunk
            ]
            prompt = (
                "你是财经新闻翻译。把以下英文财经新闻标题和摘要翻译成简洁、通顺的中文。"
                "公司名、人名和专有名词使用常见中文译名，股票代码保留原文。"
                '只输出 JSON 数组，每项包含 "news_id"、"title"、"summary"，不要输出其他内容。\n'
                + json.dumps(payload, ensure_ascii=False)
            )
            response = client.chat.completions.create(
                model=self.cfg.get("model", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": "You are a financial news translator. Always answer with valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            content = response.choices[0].message.content
            translated.extend(_extract_json_array(content))
        return translated
