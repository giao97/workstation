"""微信推送模块 - 支持企业微信群机器人 Webhook 和 Server酱。"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests

from config import WECHAT_PUSH_CONFIG

logger = logging.getLogger("quant_trading")


class WeChatPusher:
    """把日报摘要推送到微信：企业微信机器人 或 Server酱。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.cfg = dict(config or WECHAT_PUSH_CONFIG)

    def is_configured(self) -> bool:
        return bool(self.cfg.get("webhook_url") or self.cfg.get("serverchan_sendkey"))

    def send_text(self, text: str, title: str = "每日新闻日报") -> bool:
        if not self.is_configured():
            logger.info("微信推送未配置，跳过")
            return False
        text = text.strip()
        if not text:
            logger.warning("推送内容为空，跳过")
            return False
        max_chars = int(self.cfg.get("max_text_chars", 6000))
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...(内容过长已截断)"

        results = []
        if self.cfg.get("webhook_url"):
            results.append(self._send_wecom(text))
        if self.cfg.get("serverchan_sendkey"):
            results.append(self._send_serverchan(title, text))
        return all(results)

    def _send_wecom(self, text: str) -> bool:
        url = self.cfg["webhook_url"]
        payload = {"msgtype": "text", "text": {"content": text}}
        try:
            response = requests.post(url, json=payload, timeout=20)
            data = response.json()
            if data.get("errcode") == 0:
                logger.info("企业微信推送成功")
                return True
            logger.error(f"企业微信推送失败: {data}")
            return False
        except Exception as e:
            logger.error(f"企业微信推送异常: {e}")
            return False

    def _send_serverchan(self, title: str, text: str) -> bool:
        key = self.cfg["serverchan_sendkey"]
        url = f"https://sctapi.ftqq.com/{key}.send"
        try:
            response = requests.post(url, data={"title": title, "desp": text}, timeout=20)
            data = response.json()
            if data.get("code") == 0:
                logger.info("Server酱推送成功")
                return True
            logger.error(f"Server酱推送失败: {data}")
            return False
        except Exception as e:
            logger.error(f"Server酱推送异常: {e}")
            return False
