"""纯新闻日报生成器 - 只输出新闻摘要，不含行情/基本面/交易信号。"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, List

from config import REPORT_CONFIG
from src.data.storage import DataStorage


def _fmt_signed(value: Any, digits: int = 2, default: str = "-") -> str:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return f"{number:+.{digits}f}"


def _source_counts(news: List[Dict[str, Any]]) -> Dict[str, int]:
    return dict(Counter(str(item.get("source") or "未知") for item in news).most_common())


class NewsReportGenerator:
    """生成纯新闻日报: HTML / Markdown / JSON / 纯文本。"""

    def __init__(self):
        self.output_dir = Path(REPORT_CONFIG["output_dir"])
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        news: List[Dict[str, Any]],
        news_summary: Dict[str, Any],
        market_sentiment: Dict[str, Any],
    ) -> Path:
        news = list(news or [])
        news_summary = news_summary or {}
        market_sentiment = market_sentiment or {}
        date = news_summary.get("date") or datetime.now().strftime("%Y-%m-%d")

        top_news = sorted(
            news,
            key=lambda item: (item.get("impact_score", 0), str(item.get("publish_time", ""))),
            reverse=True,
        )[:30]

        payload = {
            "date": date,
            "generated_at": datetime.now().isoformat(),
            "total_news": len(news),
            "sources": _source_counts(news),
            "market_sentiment": market_sentiment,
            "global_headlines": news_summary.get("global_headlines", []),
            "stock_summaries": news_summary.get("stock_summaries", {}),
            "top_news": top_news,
        }

        markdown = self._render_markdown(payload, date)
        text = self._render_text(payload, date)
        html = self._render_html(payload, date)

        storage = DataStorage(base_dir=self.output_dir)
        storage.save_snapshot_json(payload, f"news_digest_{date}.json")
        storage.write_text_atomic(markdown, f"news_digest_{date}.md")
        storage.write_text_atomic(text, f"news_digest_{date}.txt")
        html_path = storage.write_text_atomic(html, f"news_digest_{date}.html")

        archive_dir = f"archive/{date}"
        storage.write_text_atomic(markdown, f"news_digest_{date}.md", subdir=archive_dir)
        storage.write_text_atomic(text, f"news_digest_{date}.txt", subdir=archive_dir)
        storage.write_text_atomic(html, f"news_digest_{date}.html", subdir=archive_dir)
        storage.write_text_atomic(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            f"news_digest_{date}.json",
            subdir=archive_dir,
        )
        return html_path

    def _render_markdown(self, payload: Dict[str, Any], date: str) -> str:
        sentiment = payload["market_sentiment"]
        lines = [
            f"# 每日新闻日报 - {date}",
            f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 共 {payload['total_news']} 条新闻",
            "",
            "## 市场情绪概览",
            "",
            f"- **综合判断**: {sentiment.get('overall', '中性观望')}",
            f"- **新闻情绪**: {_fmt_signed(sentiment.get('news_score', 0))}",
        ]
        if sentiment.get("summary"):
            lines.append(f"- **情绪摘要**: {sentiment['summary']}")

        lines.extend(["", "## 今日要闻", ""])
        headlines = payload["global_headlines"]
        if headlines:
            for index, item in enumerate(headlines[:10], 1):
                marker = "🔥" if item.get("impact_score", 0) >= 3 else "📌"
                lines.append(f"{index}. {marker} **{item.get('title', '')}** ({item.get('source', '')})")
                if item.get("summary"):
                    lines.append(f"   > {str(item['summary'])[:140]}")
        else:
            lines.append("今日暂无高重要性市场要闻。")

        lines.extend(["", "## 个股相关消息", ""])
        stock_summaries = payload["stock_summaries"]
        if stock_summaries:
            for symbol, stock in stock_summaries.items():
                if stock.get("news_count", 0) <= 0:
                    continue
                total = stock.get("total_sentiment", 0)
                marker = "📈" if total > 0 else "📉" if total < 0 else "📊"
                lines.append(f"- {marker} **{symbol}** ({stock.get('news_count', 0)}条): {stock.get('summary', '')}")
        else:
            lines.append("今日暂无个股相关消息。")

        lines.extend(["", "## 更多重要新闻", ""])
        for index, item in enumerate(payload["top_news"], 1):
            marker = "🔥" if item.get("impact_score", 0) >= 3 else "📌"
            lines.append(f"{index}. {marker} **{item.get('title', '')}** ({item.get('source', '')})")
            if item.get("summary"):
                lines.append(f"   > {str(item['summary'])[:120]}")

        lines.extend(
            [
                "",
                "## 免责声明",
                "",
                "> 本报告仅供学习研究参考，不构成投资建议。市场有风险，投资需谨慎。",
                "",
            ]
        )
        return "\n".join(lines)

    def _render_text(self, payload: Dict[str, Any], date: str) -> str:
        sentiment = payload["market_sentiment"]
        lines = [
            f"每日新闻日报 {date}",
            f"共 {payload['total_news']} 条新闻 | 生成时间 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "【市场情绪】",
            f"综合判断: {sentiment.get('overall', '中性观望')} | 新闻情绪: {_fmt_signed(sentiment.get('news_score', 0))}",
        ]
        if sentiment.get("summary"):
            lines.append(f"情绪摘要: {sentiment['summary']}")

        lines.extend(["", "【今日要闻】"])
        headlines = payload["global_headlines"]
        if headlines:
            for index, item in enumerate(headlines[:10], 1):
                lines.append(f"{index}. {item.get('title', '')} - {item.get('source', '')}")
        else:
            lines.append("今日暂无高重要性市场要闻。")

        lines.extend(["", "【个股消息】"])
        stock_summaries = payload["stock_summaries"]
        if stock_summaries:
            for symbol, stock in stock_summaries.items():
                if stock.get("news_count", 0) > 0:
                    lines.append(f"{symbol}: {stock.get('summary', '')}")
        else:
            lines.append("今日暂无个股相关消息。")

        lines.extend(["", "【更多重要新闻】"])
        for index, item in enumerate(payload["top_news"], 1):
            lines.append(f"{index}. {item.get('title', '')} - {item.get('source', '')}")

        lines.extend(
            [
                "",
                "免责声明: 本报告仅供学习研究参考，不构成投资建议。市场有风险，投资需谨慎。",
                "",
            ]
        )
        return "\n".join(lines)

    def _render_html(self, payload: Dict[str, Any], date: str) -> str:
        sentiment = payload["market_sentiment"]
        try:
            news_score = float(sentiment.get("news_score", 0))
        except (TypeError, ValueError):
            news_score = 0.0
        score_color = "#16a34a" if news_score > 1 else "#dc2626" if news_score < -1 else "#d97706"
        sources = "、".join(f"{name} {count}条" for name, count in (payload.get("sources") or {}).items()) or "暂无"
        sentiment_summary = ""
        if sentiment.get("summary"):
            sentiment_summary = f'<p class="muted" style="margin-top:10px">{html_escape(str(sentiment["summary"]))}</p>'
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日新闻日报 - {date}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f8fafc;color:#0f172a;line-height:1.55;padding:20px}}
.container{{max-width:960px;margin:0 auto}}
h1{{font-size:26px;color:#0f172a;margin-bottom:6px}}
.subtitle{{color:#64748b;font-size:14px;margin-bottom:20px}}
.section{{background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:18px;margin-bottom:16px}}
.section h2{{font-size:17px;color:#1d4ed8;margin-bottom:12px}}
.summary-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
.summary-item{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px}}
.summary-item b{{display:block;font-size:20px}}
.muted{{color:#64748b;font-size:12px}}
.news-item{{display:flex;gap:10px;align-items:flex-start;padding:10px;border-bottom:1px solid #e2e8f0}}
.news-item:last-child{{border-bottom:0}}
.impact{{font-size:15px}}
.news-title{{font-size:14px;font-weight:600;margin-bottom:2px}}
.news-meta{{color:#64748b;font-size:12px}}
.news-summary{{font-size:13px;color:#475569;margin-top:4px}}
.news-link{{color:#2563eb;text-decoration:none;margin-left:6px}}
.stock-card{{border:1px solid #e2e8f0;border-radius:8px;padding:12px;margin-bottom:10px;background:#ffffff}}
.stock-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}}
.stock-title{{font-size:16px;font-weight:700}}
.stock-count{{font-size:12px;background:#eef2ff;color:#3730a3;padding:2px 8px;border-radius:999px}}
.news-line{{padding:3px 0;border-bottom:1px solid #f1f5f9;font-size:13px}}
.news-line:last-child{{border-bottom:0}}
.footer{{text-align:center;color:#64748b;font-size:12px;margin-top:22px;padding-top:16px;border-top:1px solid #e2e8f0}}
@media (max-width:600px){{body{{padding:12px}}.summary-grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="container">
<h1>每日新闻日报</h1>
<p class="subtitle">日期: {date} | 共 {payload['total_news']} 条新闻 | 来源: {html_escape(sources)}</p>
<div class="section">
<h2>市场情绪概览</h2>
<div class="summary-grid">
<div class="summary-item"><b style="color:{score_color}">{_fmt_signed(news_score)}</b>新闻情绪</div>
<div class="summary-item"><b>{html_escape(str(sentiment.get('overall', '中性观望')))}</b>综合判断</div>
<div class="summary-item"><b>{payload['total_news']}</b>新闻总数</div>
</div>
{sentiment_summary}
</div>
<div class="section"><h2>今日要闻</h2>{self._headline_section(payload["global_headlines"])}</div>
<div class="section"><h2>个股相关消息</h2>{self._stock_section(payload["stock_summaries"])}</div>
<div class="section"><h2>更多重要新闻</h2>{self._top_news_section(payload["top_news"])}</div>
<div class="footer"><p>本报告仅供学习研究参考，不构成投资建议。市场有风险，投资需谨慎。</p><p>生成时间: {generated_at}</p></div>
</div>
</body>
</html>"""

    def _headline_section(self, headlines: List[Dict[str, Any]]) -> str:
        if not headlines:
            return "<p>今日暂无高重要性市场要闻。</p>"
        parts = []
        for item in headlines[:10]:
            marker = "🔥" if item.get("impact_score", 0) >= 3 else "📌"
            link = ""
            url = item.get("url")
            if url:
                link = f' <a class="news-link" href="{html_escape(str(url))}" target="_blank" rel="noopener">原文</a>'
            summary = ""
            if item.get("summary"):
                summary = f'<div class="news-summary">{html_escape(str(item["summary"])[:160])}</div>'
            parts.append(
                '<div class="news-item">'
                f'<span class="impact">{marker}</span>'
                "<div>"
                f'<div class="news-title">{html_escape(str(item.get("title", "")))}</div>'
                f'<div class="news-meta">{html_escape(str(item.get("source", "")))} | '
                f'{html_escape(str(item.get("category", "")))} | '
                f'{html_escape(str(item.get("publish_time", "")))}{link}</div>'
                f"{summary}"
                "</div>"
                "</div>"
            )
        return "".join(parts)

    def _stock_section(self, stock_summaries: Dict[str, Any]) -> str:
        if not stock_summaries:
            return "<p>今日暂无个股相关消息。</p>"
        parts = []
        for symbol, stock in stock_summaries.items():
            if stock.get("news_count", 0) <= 0:
                continue
            total = stock.get("total_sentiment", 0)
            color = "#16a34a" if total > 0 else "#dc2626" if total < 0 else "#d97706"
            news_lines = "".join(
                f'<div class="news-line">• {html_escape(str(item.get("title", "")))} '
                f'<span class="muted">{html_escape(str(item.get("source", "")))}</span></div>'
                for item in (stock.get("top_news") or [])[:5]
            )
            parts.append(
                '<div class="stock-card">'
                f'<div class="stock-header"><span class="stock-title">{html_escape(str(symbol))}</span>'
                f'<span class="stock-count">{stock.get("news_count", 0)}条</span></div>'
                f'<div class="news-summary" style="color:{color}">{html_escape(str(stock.get("summary", "")))}</div>'
                f"{news_lines}"
                "</div>"
            )
        return "".join(parts)

    def _top_news_section(self, top_news: List[Dict[str, Any]]) -> str:
        if not top_news:
            return "<p>暂无新闻数据。</p>"
        parts = []
        for item in top_news:
            marker = "🔥" if item.get("impact_score", 0) >= 3 else "📌"
            parts.append(
                '<div class="news-item">'
                f'<span class="impact">{marker}</span>'
                "<div>"
                f'<div class="news-title">{html_escape(str(item.get("title", "")))}</div>'
                f'<div class="news-meta">{html_escape(str(item.get("source", "")))} | '
                f'{html_escape(str(item.get("category", "")))}</div>'
                "</div>"
                "</div>"
            )
        return "".join(parts)
