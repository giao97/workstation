"""Backtest result reporting."""
from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Dict, List

from config import REPORT_DIR
from src.data.storage import DataStorage


def _aggregate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    metrics = [result["metrics"] for result in results if result.get("metrics")]
    if not metrics:
        return {"strategy_count": 0, "total_trades": 0, "total_net_profit": 0.0}

    total_trades = sum(item.get("trade_count", 0) for item in metrics)
    trade_weighted_win = sum(
        item.get("win_rate_pct", 0.0) * item.get("trade_count", 0)
        for item in metrics
    )
    average_win_rate = trade_weighted_win / total_trades if total_trades else 0.0
    return {
        "strategy_count": len(metrics),
        "total_trades": total_trades,
        "total_net_profit": round(sum(item.get("net_profit", 0.0) for item in metrics), 2),
        "average_total_return_pct": round(sum(item.get("total_return_pct", 0.0) for item in metrics) / len(metrics), 2),
        "average_annualized_return_pct": round(sum(item.get("annualized_return_pct", 0.0) for item in metrics) / len(metrics), 2),
        "average_sharpe_ratio": round(sum(item.get("sharpe_ratio", 0.0) for item in metrics) / len(metrics), 3),
        "worst_max_drawdown_pct": round(min(item.get("max_drawdown_pct", 0.0) for item in metrics), 2),
        "average_win_rate_pct": round(average_win_rate, 2),
        "average_profit_factor": round(
            sum(item.get("profit_factor") or 0.0 for item in metrics) / len(metrics),
            3,
        ),
    }


def generate_backtest_report(
    results: List[Dict[str, Any]],
    output_dir: Path = REPORT_DIR,
    date_str: str = None,
) -> Path:
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    storage = DataStorage(base_dir=output_dir)
    payload = {
        "date": date_str,
        "generated_at": datetime.now().isoformat(),
        "aggregate": _aggregate(results),
        "strategies": results,
    }
    json_path = storage.save_snapshot_json(payload, f"backtest_{date_str}.json", subdir="backtest")
    storage.write_text_atomic(_render_markdown(payload), f"backtest_{date_str}.md", subdir="backtest")
    storage.write_text_atomic(_render_html(payload), f"backtest_{date_str}.html", subdir="backtest")
    return json_path


def _render_markdown(payload: Dict[str, Any]) -> str:
    aggregate = payload["aggregate"]
    lines = [
        f"# 策略回测报告 - {payload['date']}",
        "",
        "## 汇总",
        "",
        f"- 策略数量: {aggregate.get('strategy_count', 0)}",
        f"- 总交易次数: {aggregate.get('total_trades', 0)}",
        f"- 总净收益: {aggregate.get('total_net_profit', 0)}",
        f"- 平均总收益率: {aggregate.get('average_total_return_pct', 0)}%",
        f"- 平均年化收益率: {aggregate.get('average_annualized_return_pct', 0)}%",
        f"- 平均夏普比率: {aggregate.get('average_sharpe_ratio', 0)}",
        f"- 最大回撤: {aggregate.get('worst_max_drawdown_pct', 0)}%",
        "",
        "| 标的 | 市场 | 区间 | 总收益 | 最大回撤 | 夏普 | 交易数 | 胜率 |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for result in payload["strategies"]:
        metrics = result.get("metrics") or {}
        lines.append(
            "| {symbol} | {market} | {start}~{end} | {total}% | {drawdown}% | {sharpe} | {trades} | {win}% |".format(
                symbol=escape(str(result.get("symbol", "-"))),
                market=escape(str(result.get("market", "-"))),
                start=result.get("period_start") or "-",
                end=result.get("period_end") or "-",
                total=metrics.get("total_return_pct", 0),
                drawdown=metrics.get("max_drawdown_pct", 0),
                sharpe=metrics.get("sharpe_ratio", 0),
                trades=metrics.get("trade_count", 0),
                win=metrics.get("win_rate_pct", 0),
            )
        )
    return "\n".join(lines) + "\n"


def _render_html(payload: Dict[str, Any]) -> str:
    aggregate = payload["aggregate"]
    rows = []
    for result in payload["strategies"]:
        metrics = result.get("metrics") or {}
        rows.append(
            "<tr>"
            f"<td>{escape(str(result.get('symbol', '-')))}</td>"
            f"<td>{escape(str(result.get('market', '-')))}</td>"
            f"<td>{escape(str(result.get('period_start') or '-'))} ~ {escape(str(result.get('period_end') or '-'))}</td>"
            f"<td>{metrics.get('total_return_pct', 0)}%</td>"
            f"<td>{metrics.get('max_drawdown_pct', 0)}%</td>"
            f"<td>{metrics.get('sharpe_ratio', 0)}</td>"
            f"<td>{metrics.get('trade_count', 0)}</td>"
            f"<td>{metrics.get('win_rate_pct', 0)}%</td>"
            "</tr>"
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>策略回测报告 - {escape(payload['date'])}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f8fafc;color:#0f172a;margin:0;padding:24px}}
.wrap{{max-width:1100px;margin:0 auto}}table{{width:100%;border-collapse:collapse;background:white}}
th,td{{padding:10px 12px;border-bottom:1px solid #e2e8f0;text-align:left}}th{{background:#eef2ff}}
.summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0}}
.metric{{background:white;padding:14px;border-radius:8px;border:1px solid #e2e8f0}}
.metric b{{display:block;font-size:24px;color:#2563eb}}
</style>
</head>
<body><div class="wrap">
<h1>策略回测报告</h1>
<p>{escape(payload['date'])} | 仅历史规则验证，不构成投资建议</p>
<div class="summary">
<div class="metric">策略<b>{aggregate.get('strategy_count', 0)}</b></div>
<div class="metric">总交易<b>{aggregate.get('total_trades', 0)}</b></div>
<div class="metric">平均收益<b>{aggregate.get('average_total_return_pct', 0)}%</b></div>
<div class="metric">最大回撤<b>{aggregate.get('worst_max_drawdown_pct', 0)}%</b></div>
<div class="metric">平均夏普<b>{aggregate.get('average_sharpe_ratio', 0)}</b></div>
</div>
<table><thead><tr><th>标的</th><th>市场</th><th>区间</th><th>总收益</th><th>最大回撤</th><th>夏普</th><th>交易数</th><th>胜率</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</div></body></html>"""
