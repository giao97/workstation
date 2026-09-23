"""Daily HTML/Markdown/JSON report generation."""
from __future__ import annotations

import json
import math
from datetime import datetime
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, List

from config import REPORT_CONFIG
from src.data.storage import DataStorage
from src.risk.portfolio import PortfolioRisk


def _fmt(value: Any, digits: int = 2, default: str = "-") -> str:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return f"{number:.{digits}f}"


def _fmt_signed(value: Any, digits: int = 2, default: str = "-") -> str:
    formatted = _fmt(value, digits=digits, default=None)
    if formatted is None:
        return default
    number = float(formatted)
    return f"{number:+.{digits}f}"


def _score_display(value: Any) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if not math.isfinite(number):
        return "-"
    return str(max(0, min(100, int(round(number)))))


def _confidence_class(value: Any) -> str:
    return {
        "HIGH": "quality-high",
        "MEDIUM": "quality-medium",
        "LOW": "quality-low",
    }.get(str(value or "").upper(), "quality-low")


class ReportGenerator:
    """Generate the daily dashboard with chart data and risk context."""

    def __init__(self):
        self.output_dir = Path(REPORT_CONFIG["output_dir"])
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_daily_summary_report(
        self,
        stock_results: List[Dict[str, Any]],
        news_summary: Dict[str, Any],
        market_sentiment: Dict[str, Any],
    ) -> Path:
        stock_results = list(stock_results or [])
        news_summary = news_summary or {}
        market_sentiment = market_sentiment or {}
        date_str = datetime.now().strftime("%Y-%m-%d")
        portfolio_risk = PortfolioRisk.from_signal_results(stock_results)

        markdown = self._render_markdown(stock_results, news_summary, market_sentiment, portfolio_risk, date_str)
        html = self._render_html(stock_results, news_summary, market_sentiment, portfolio_risk, date_str)
        payload = {
            "date": date_str,
            "generated_at": datetime.now().isoformat(),
            "market_sentiment": market_sentiment,
            "news_summary": news_summary,
            "portfolio_risk": portfolio_risk,
            "stocks": stock_results,
        }

        storage = DataStorage(base_dir=self.output_dir)
        json_path = storage.save_snapshot_json(payload, f"daily_summary_{date_str}.json")
        storage.write_text_atomic(markdown, f"daily_summary_{date_str}.md")
        html_path = storage.write_text_atomic(html, f"daily_summary_{date_str}.html")

        archive_dir = f"archive/{date_str}"
        storage.write_text_atomic(markdown, f"daily_summary_{date_str}.md", subdir=archive_dir)
        storage.write_text_atomic(html, f"daily_summary_{date_str}.html", subdir=archive_dir)
        storage.write_text_atomic(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            f"daily_summary_{date_str}.json",
            subdir=archive_dir,
        )
        return html_path

    def _render_markdown(
        self,
        stock_results: List[Dict[str, Any]],
        news_summary: Dict[str, Any],
        market_sentiment: Dict[str, Any],
        portfolio_risk: Dict[str, Any],
        date: str,
    ) -> str:
        lines = [
            f"# 每日投资总结 - {date}",
            f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | A股 + 港股 + 美股",
            "",
            "## 市场情绪概览",
            "",
            f"- **综合判断**: {market_sentiment.get('overall', '中性')}",
            f"- **综合得分**: {_fmt_signed(market_sentiment.get('combined_score', 0))}",
            f"- **新闻情绪**: {_fmt_signed(market_sentiment.get('news_score', 0))} | **政策情绪**: {_fmt_signed(market_sentiment.get('policy_score', 0))}",
            "",
            "## 组合风险预览",
            "",
            f"- **候选总敞口**: {_fmt(portfolio_risk.get('total_notional', 0))}",
            f"- **剩余资金**: {_fmt(portfolio_risk.get('cash_remaining', 0))}",
            f"- **单标的最大权重**: {_fmt(portfolio_risk.get('max_weight_pct', 0))}%",
            f"- **集中度 HHI**: {_fmt(portfolio_risk.get('concentration_hhi', 0), 4)}",
        ]
        warnings = portfolio_risk.get("warnings") or []
        if warnings:
            lines.append("")
            for warning in warnings:
                lines.append(f"- ⚠️ {warning}")
        lines.extend(["", "## 今日要闻速览", ""])

        headlines = news_summary.get("global_headlines", [])
        if headlines:
            lines.append("### 市场重要消息")
            for index, headline in enumerate(headlines[:8], 1):
                impact = "🔥" if headline.get("impact_score", 0) >= 3 else "📌"
                lines.append(f"{index}. {impact} **{headline.get('title', '')}** ({headline.get('source', '')})")
                if headline.get("summary"):
                    lines.append(f"   > {str(headline['summary'])[:120]}")
            lines.append("")

        stock_summaries = news_summary.get("stock_summaries", {})
        if stock_summaries:
            lines.append("### 个股消息")
            for symbol, summary in stock_summaries.items():
                if summary.get("news_count", 0) <= 0:
                    continue
                total = summary.get("total_sentiment", 0)
                emoji = "📈" if total > 0 else "📉" if total < 0 else "📊"
                lines.append(f"- {emoji} **{symbol}**: {summary.get('summary', '')}")
            lines.append("")

        lines.extend(["## 个股深度分析", ""])
        for result in stock_results:
            code = result.get("code", "")
            name = result.get("name", "")
            market = result.get("market", "")
            technical = result.get("technical") or {}
            fundamental = result.get("fundamental") or {}
            signal = result.get("signal") or {}
            news = result.get("news_sentiment") or {}
            quality = result.get("data_quality") or {}
            suggestion = result.get("position_suggestion")

            lines.append(f"### {code} {name} ({market})")
            overall = str(signal.get("overall_signal") or "HOLD")
            signal_emoji = "🟢" if "BUY" in overall else "🔴" if "SELL" in overall else "🟡"
            lines.append(f"- **综合信号**: {signal_emoji} {overall} (置信度: {signal.get('overall_confidence', 'LOW')})")
            lines.append(f"- **当前价格**: {_fmt(technical.get('close'))}")
            lines.append(f"- **止损位**: {_fmt(signal.get('stop_loss'))} | **止盈位**: {_fmt(signal.get('take_profit'))}")

            if suggestion and suggestion.get("status") == "VALID":
                lines.append(
                    f"- **建议仓位**: {suggestion['shares']}股 / {suggestion['position_pct']}% "
                    f"(名义资金 {_fmt(suggestion.get('notional'))})"
                )

            if fundamental.get("available", True) is False or fundamental.get("total_score") is None:
                lines.append("- **基本面**: 数据不足，未纳入信号")
            else:
                lines.append(f"- **基本面评分**: {_score_display(fundamental.get('total_score'))}/100 ({fundamental.get('rating', '一般')})")
                for flag in (fundamental.get("flags") or [])[:3]:
                    lines.append(f"  - ✅ {flag}")
                for risk in (fundamental.get("risks") or [])[:3]:
                    lines.append(f"  - ⚠️ {risk}")

            lines.append(
                f"- **技术面**: RSI={_fmt(technical.get('rsi'), 1)} | MA20={_fmt(technical.get('ma20'))} | "
                f"MACD={'金叉' if technical.get('macd_golden_cross') else '死叉' if technical.get('macd_death_cross') else '中性'}"
            )
            latest_date = (quality.get("ohlcv") or {}).get("latest_date")
            lines.append(
                f"- **数据质量**: {quality.get('confidence', 'LOW')} | 最新日期 {latest_date or '-'} | "
                f"历史 {quality.get('ohlcv', {}).get('rows', 0)} 行"
            )
            issues = quality.get("issues") or []
            if issues:
                lines.append(f"  - {', '.join(issues)}")

            if news and news.get("news_count", 0) > 0:
                lines.append(
                    f"- **消息情绪**: {news.get('sentiment', '中性')} "
                    f"({_fmt_signed(news.get('sentiment_score', 0))}) | 相关消息{news.get('news_count')}条"
                )
                for item in (news.get("top_news") or [])[:3]:
                    lines.append(f"  - {item.get('title', '')}")
            else:
                lines.append("- **消息情绪**: 今日无相关消息")
            lines.append("")

        lines.extend(
            [
                "## 免责声明",
                "",
                "> 本报告仅供学习研究参考，不构成投资建议。市场有风险，投资需谨慎。",
                "",
            ]
        )
        return "\n".join(lines)

    def _render_html(
        self,
        stock_results: List[Dict[str, Any]],
        news_summary: Dict[str, Any],
        market_sentiment: Dict[str, Any],
        portfolio_risk: Dict[str, Any],
        date: str,
    ) -> str:
        stock_cards = ""
        chart_payloads = []
        for index, result in enumerate(stock_results):
            card, chart_payload = self._build_stock_card(index, result)
            stock_cards += card
            if chart_payload:
                chart_payloads.append(chart_payload)

        headlines = self._build_headlines(news_summary)
        sentiment_section = self._build_sentiment_section(market_sentiment)
        portfolio_section = self._build_portfolio_section(portfolio_risk)
        chart_script = self._build_chart_script(chart_payloads)
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日投资总结 - {date}</title>
<script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f8fafc;color:#0f172a;line-height:1.55;padding:20px}}
.container{{max-width:1360px;margin:0 auto}}
h1{{font-size:28px;color:#0f172a;margin-bottom:6px}}
.subtitle{{color:#64748b;font-size:14px;margin-bottom:20px}}
.section{{background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:18px;margin-bottom:16px}}
.section h2{{font-size:18px;color:#1d4ed8;margin-bottom:14px}}
.summary-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}}
.summary-item{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px}}
.summary-item b{{display:block;font-size:20px}}
.headline-item{{display:flex;gap:10px;align-items:flex-start;padding:10px;border-bottom:1px solid #e2e8f0}}
.headline-item:last-child{{border-bottom:0}}
.headline-source{{color:#64748b;font-size:12px;white-space:nowrap}}
.stock-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,390px),1fr));gap:14px}}
.stock-card{{border:1px solid #e2e8f0;border-radius:8px;padding:14px;background:#ffffff}}
.stock-header{{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;margin-bottom:10px}}
.stock-title{{font-size:18px;font-weight:700}}
.stock-name{{font-size:13px;color:#64748b}}
.market-tag{{font-size:11px;background:#eef2ff;color:#3730a3;padding:2px 6px;border-radius:4px;margin-left:6px}}
.badge{{padding:4px 10px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}}
.badge-buy{{background:#dcfce7;color:#15803d}}
.badge-sell{{background:#fee2e2;color:#b91c1c}}
.badge-hold{{background:#fef9c3;color:#a16207}}
.price-row{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:10px}}
.price-label{{font-size:11px;color:#64748b}}
.price-value{{font-size:15px;font-weight:700}}
.score-track{{height:6px;background:#e2e8f0;border-radius:999px;overflow:hidden;margin-bottom:10px}}
.score-fill{{height:100%;border-radius:999px}}
.tech-row{{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:10px}}
.tech-tag{{font-size:12px;background:#f8fafc;border:1px solid #e2e8f0;padding:4px 8px;border-radius:6px}}
.quality-high{{background:#dcfce7;color:#15803d}}
.quality-medium{{background:#fef9c3;color:#a16207}}
.quality-low{{background:#fee2e2;color:#b91c1c}}
.quality-badge{{font-size:11px;padding:2px 7px;border-radius:999px}}
.flags{{display:flex;flex-direction:column;gap:5px;margin-bottom:10px}}
.flag-good,.flag-bad{{font-size:12px;padding:6px 8px;border-radius:6px}}
.flag-good{{background:#f0fdf4;border-left:3px solid #22c55e}}
.flag-bad{{background:#fef2f2;border-left:3px solid #ef4444}}
.news-section{{background:#f8fafc;border-radius:6px;padding:9px;font-size:12px}}
.news-line{{padding:3px 0;border-bottom:1px solid #e2e8f0}}
.news-line:last-child{{border-bottom:0}}
.chart-wrap{{height:260px;margin-top:12px;border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;position:relative}}
.chart-fallback{{padding:12px;color:#64748b;font-size:12px}}
.position-suggestion{{font-size:12px;background:#eff6ff;border-radius:6px;padding:7px 9px;margin:8px 0;color:#1d4ed8}}
.warnings{{margin-top:8px;font-size:13px;color:#b91c1c}}
.footer{{text-align:center;color:#64748b;font-size:12px;margin-top:22px;padding-top:16px;border-top:1px solid #e2e8f0}}
@media (max-width:600px){{body{{padding:12px}}.stock-header{{flex-direction:column}}.summary-grid{{grid-template-columns:1fr}}.headline-item{{flex-wrap:wrap}}}}
</style>
</head>
<body>
<div class="container">
<h1>每日投资总结</h1>
<p class="subtitle">日期: {date} | 覆盖市场: A股 + 港股 + 美股</p>
<div class="section"><h2>市场情绪概览</h2>{sentiment_section}</div>
<div class="section"><h2>组合风险预览</h2>{portfolio_section}</div>
<div class="section"><h2>今日要闻速览</h2>{headlines}</div>
<div class="section"><h2>个股深度分析</h2><div class="stock-grid">{stock_cards or '<p>暂无可展示的个股结果</p>'}</div></div>
<div class="footer"><p>本报告仅供学习研究参考，不构成投资建议。市场有风险，投资需谨慎。</p><p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</div>
{chart_script}
</body>
</html>"""

    def _build_stock_card(self, index: int, result: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        code = result.get("code", "")
        name = result.get("name", "")
        market = result.get("market", "")
        technical = result.get("technical") or {}
        fundamental = result.get("fundamental") or {}
        signal = result.get("signal") or {}
        news = result.get("news_sentiment") or {}
        quality = result.get("data_quality") or {}
        suggestion = result.get("position_suggestion")
        chart_data = result.get("chart_data") or []

        overall = str(signal.get("overall_signal") or "HOLD")
        badge_class = "badge-buy" if "BUY" in overall else "badge-sell" if "SELL" in overall else "badge-hold"
        fund_score = _score_display(fundamental.get("total_score"))
        fund_color = "#ef4444"
        if fund_score != "-":
            numeric_score = float(fund_score)
            if numeric_score >= 70:
                fund_color = "#22c55e"
            elif numeric_score >= 45:
                fund_color = "#f59e0b"
        fund_rating = fundamental.get("rating", "数据不足")

        flags = ""
        if fundamental.get("available", True) is not False:
            for flag in (fundamental.get("flags") or [])[:3]:
                flags += f'<div class="flag-good">✅ {html_escape(str(flag))}</div>'
            for risk in (fundamental.get("risks") or [])[:3]:
                flags += f'<div class="flag-bad">⚠️ {html_escape(str(risk))}</div>'

        position_html = ""
        if suggestion and suggestion.get("status") == "VALID":
            position_html = (
                '<div class="position-suggestion">建议仓位: '
                f"{suggestion.get('shares')}股 / {suggestion.get('position_pct')}% | "
                f"止损 {_fmt(suggestion.get('stop_loss'))}</div>"
            )

        news_html = ""
        if news and news.get("news_count", 0) > 0:
            news_html = f'<div class="news-section"><b>消息情绪:</b> {html_escape(str(news.get("sentiment", "中性")))} ({_fmt_signed(news.get("sentiment_score", 0))})'
            for item in (news.get("top_news") or [])[:3]:
                color = "#16a34a" if item.get("sentiment_score", 0) > 0 else "#dc2626"
                news_html += f'<div class="news-line" style="color:{color}">• {html_escape(str(item.get("title", "")))}</div>'
            news_html += "</div>"
        else:
            news_html = '<div class="news-section"><b>今日无相关消息</b></div>'

        latest_date = (quality.get("ohlcv") or {}).get("latest_date") or "-"
        quality_html = (
            f'<span class="quality-badge {_confidence_class(quality.get("confidence"))}">'
            f"数据质量 {quality.get('confidence', 'LOW')} | {latest_date}</span>"
        )
        issues_html = "".join(f"<div>{html_escape(str(issue))}</div>" for issue in (quality.get("issues") or [])[:2])

        card = f"""
<div class="stock-card">
<div class="stock-header"><div><span class="stock-title">{html_escape(str(code))}</span> <span class="stock-name">{html_escape(str(name))}</span> <span class="market-tag">{html_escape(str(market))}</span></div><span class="badge {badge_class}">{html_escape(overall)}</span></div>
<div class="price-row">
<div><div class="price-label">当前价</div><div class="price-value">{_fmt(technical.get('close'))}</div></div>
<div><div class="price-label">基本面</div><div class="price-value">{fund_score}/100 {html_escape(str(fund_rating))}</div></div>
<div><div class="price-label">RSI</div><div class="price-value">{_fmt(technical.get('rsi'), 1)}</div></div>
</div>
<div class="score-track"><div class="score-fill" style="width:{fund_score if fund_score != '-' else 0}%;background:{fund_color}"></div></div>
<div class="tech-row">
<span class="tech-tag">MA20: {_fmt(technical.get('ma20'))}</span>
<span class="tech-tag">MACD: {'金叉' if technical.get('macd_golden_cross') else '死叉' if technical.get('macd_death_cross') else '中性'}</span>
<span class="tech-tag">止损: {_fmt(signal.get('stop_loss'))}</span>
<span class="tech-tag">止盈: {_fmt(signal.get('take_profit'))}</span>
</div>
<div>{quality_html}</div>
{position_html}
<div class="flags">{flags}</div>
<div class="news-section" style="font-size:11px;margin-bottom:8px">{issues_html}</div>
{news_html}
<div class="chart-wrap"><div id="chart-{index}" style="width:100%;height:100%"></div></div>
</div>"""
        chart_payload = {"id": f"chart-{index}", "data": chart_data}
        return card, chart_payload

    def _build_sentiment_section(self, market_sentiment: Dict[str, Any]) -> str:
        score = market_sentiment.get("combined_score", 0)
        color = "#16a34a" if score > 1 else "#dc2626" if score < -1 else "#d97706"
        return f"""
<div class="summary-grid">
<div class="summary-item"><b style="color:{color}">{_fmt_signed(score)}</b>综合得分</div>
<div class="summary-item"><b>{html_escape(str(market_sentiment.get('overall', '中性')))}</b>整体判断</div>
<div class="summary-item"><b>{_fmt_signed(market_sentiment.get('news_score', 0))}</b>新闻情绪</div>
<div class="summary-item"><b>{_fmt_signed(market_sentiment.get('policy_score', 0))}</b>政策情绪</div>
</div>
<p style="margin-top:10px;color:#475569">{html_escape(str(market_sentiment.get('summary', ''))) or '暂无情绪摘要'}</p>"""

    def _build_portfolio_section(self, portfolio_risk: Dict[str, Any]) -> str:
        warnings = "".join(
            f"<div>⚠️ {html_escape(str(warning))}</div>"
            for warning in (portfolio_risk.get("warnings") or [])
        )
        sector_weights = portfolio_risk.get("sector_weights") or {}
        sectors = "、".join(f"{name} {weight}%" for name, weight in list(sector_weights.items())[:5])
        return f"""
<div class="summary-grid">
<div class="summary-item"><b>{_fmt(portfolio_risk.get('total_notional', 0))}</b>候选总敞口</div>
<div class="summary-item"><b>{_fmt(portfolio_risk.get('cash_remaining', 0))}</b>剩余资金</div>
<div class="summary-item"><b>{_fmt(portfolio_risk.get('max_weight_pct', 0))}%</b>最大单标的权重</div>
<div class="summary-item"><b>{_fmt(portfolio_risk.get('concentration_hhi', 0), 4)}</b>集中度 HHI</div>
</div>
<p style="margin-top:10px;color:#475569">行业权重: {sectors or '暂无'}</p>
<div class="warnings">{warnings}</div>"""

    def _build_headlines(self, news_summary: Dict[str, Any]) -> str:
        headlines = news_summary.get("global_headlines", [])
        if not headlines:
            return "<p>暂无市场要闻</p>"
        items = []
        for headline in headlines[:8]:
            impact = "🔥" if headline.get("impact_score", 0) >= 3 else "📌"
            items.append(
                '<div class="headline-item">'
                f'<span>{impact}</span><span>{html_escape(str(headline.get("title", "")))}</span>'
                f'<span class="headline-source">{html_escape(str(headline.get("source", "")))}</span></div>'
            )
        return "".join(items)

    def _build_chart_script(self, chart_payloads: List[Dict[str, Any]]) -> str:
        payloads_json = json.dumps(chart_payloads, ensure_ascii=False, default=str)
        return f"""
<script>
(function(){{
  const payloads = {payloads_json};
  function lineData(data, key) {{
    return data
      .filter(row => row[key] !== undefined && row[key] !== null)
      .map(row => ({{time: row.date, value: row[key]}}));
  }}
  function renderChart(payload) {{
    const container = document.getElementById(payload.id);
    if (!container || !window.LightweightCharts || !payload.data || !payload.data.length) {{
      if (container && !window.LightweightCharts) container.innerHTML = '<div class="chart-fallback">图表资源未加载</div>';
      return;
    }}
    const chart = LightweightCharts.createChart(container, {{
      height: 260,
      layout: {{background: {{color: '#ffffff'}}, textColor: '#334155'}},
      grid: {{vertLines: {{color: '#f1f5f9'}}, horzLines: {{color: '#f1f5f9'}}}},
      rightPriceScale: {{borderColor: '#e2e8f0'}},
      timeScale: {{borderColor: '#e2e8f0'}}
    }});
    const candles = chart.addCandlestickSeries({{
      upColor: '#ef4444', downColor: '#22c55e', borderVisible: false,
      wickUpColor: '#ef4444', wickDownColor: '#22c55e'
    }});
    candles.setData(payload.data.map(row => ({{
      time: row.date, open: row.open, high: row.high, low: row.low, close: row.close
    }})));
    if (payload.data.some(row => row.ma20 !== undefined)) {{
      const ma = chart.addLineSeries({{color: '#2563eb', lineWidth: 2, title: 'MA20'}});
      ma.setData(lineData(payload.data, 'ma20'));
    }}
    if (payload.data.some(row => row.bb_upper !== undefined)) {{
      const upper = chart.addLineSeries({{color: '#f59e0b', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed}});
      const lower = chart.addLineSeries({{color: '#f59e0b', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed}});
      upper.setData(lineData(payload.data, 'bb_upper'));
      lower.setData(lineData(payload.data, 'bb_lower'));
    }}
    const volume = chart.addHistogramSeries({{color: '#94a3b8', priceFormat: {{type: 'volume'}}, priceScaleId: ''}});
    volume.setData(payload.data.map(row => ({{time: row.date, value: row.volume || 0}})));
    chart.priceScale('').applyOptions({{scaleMargins: {{top: 0.82, bottom: 0}}}});
    chart.timeScale().fitContent();
  }}
  window.addEventListener('DOMContentLoaded', () => payloads.forEach(renderChart));
}})();
</script>"""
