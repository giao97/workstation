"""Deterministic, opt-in allocation section for daily reports."""

import html
import logging
from typing import Any, Dict, Optional

from src.services.portfolio_allocation_service import PortfolioAllocationService

logger = logging.getLogger(__name__)
ALLOCATION_MARKER = "<!-- dsa-allocation -->"


def render_allocation_status(status: Dict[str, Any], *, language: str = "zh") -> str:
    zh = language == "zh"
    currency = status["base_currency"]

    def cell(value: Any) -> str:
        return html.escape(str(value)).replace("|", "&#124;").replace("\n", " ").replace("\r", " ").replace("`", "&#96;")

    def money(value: Any) -> str:
        return ("待核实" if zh else "Unknown") if value is None else f"{float(value):,.2f}"

    conditions_text = {
        "ledger_not_confirmed": "请确认持仓与现金已完整录入",
        "portfolio_accounts_missing": "请先建立账户并录入资产",
        "manual_current_amount_missing": "请补充手工资产余额",
        "position_price_missing": "请补充行情",
        "position_price_stale": "请更新过期行情",
        "close_reference": "最近收盘参考价",
        "fx_reference": "日线汇率估算",
        "position_fx_unreliable": "请刷新持仓换算汇率",
        "cash_fx_unreliable": "请刷新现金换算汇率",
        "cash_budget_unavailable": "请核实可用现金",
        "cash_budget_limited": "已受剩余现金预算限制",
        "cash_reserve_only": "保留现金，不生成买卖动作",
        "below_target": "低于目标，需确认交易条件",
        "below_min_band": "低于配置下限，需确认交易条件",
        "above_target": "超过目标，需检查减仓条件",
        "inside_rebalance_band": "在再平衡区间内",
        "at_or_above_target": "已达到目标",
        "policy_hold_only": "仅跟踪",
        "policy_exit_only": "只减不增",
        "current_amount_unavailable": "请核实当前金额",
    }
    actions = {"add": "有配置空间", "reduce": "检查减仓", "hold": "等待 / 持有", "review": "先核实数据"}
    lines = [
        f"#### {cell(status['plan_name'])} · v{status['plan_version']}",
        "",
        (f"截至 {status['as_of']}，币种 {currency}，占比分母为计划资产 {money(status['target_total_value'])}。"
         if zh else f"As of {status['as_of']}; {currency}; weights use plan capital {money(status['target_total_value'])}."),
        (f"预留现金 {money(status['cash_reserve_amount'])}；账面预算余额 {money(status['available_cash'])}；"
         f"合计配置上限 {money(status['total_recommended_add'])}。" if zh else
         f"Cash reserve {money(status['cash_reserve_amount'])}; ledger budget remaining {money(status['available_cash'])}; "
         f"total additions capped at {money(status['total_recommended_add'])}."),
        (f"已核实现金上限 {money(status.get('confirmed_cash'))}；计划追加不计入现金，跨日或账本变化须重新确认。"
         if zh else f"Confirmed cash cap {money(status.get('confirmed_cash'))}. Planned deposits are excluded; reconfirm after a date or ledger change."),
        "",
        ("| 资产 | 目标 / 当前占比 | 当前金额 | 目标缺口 | 账面本批上限 | 现金覆盖上限 | 状态 / 条件 |" if zh else
         "| Asset | Target / current % | Current value | Gap | Ledger batch cap | Cash-backed cap | Status / conditions |"),
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for target in status["targets"]:
        action = actions[target["action"]] if zh else target["action"]
        codes = target["limitations"] or [target["reason"]]
        conditions = "; ".join(conditions_text.get(code.split(':')[0], code) if zh else code for code in codes)
        if target.get("is_estimate"):
            action += "（估算参考）" if zh else " (estimate)"
            notes = []
            for note in target.get("reference_notes", []):
                code, *details = note.split(":")
                notes.append(f"{conditions_text.get(code, code) if zh else code} {' / '.join(details)}")
            conditions += "; " + "; ".join(notes)
        current_pct = "—" if target["current_pct"] is None else f"{target['current_pct']:.2f}%"
        lines.append(
            f"| {cell(target['name'])} | {target['target_pct']:g}% / {current_pct} | {money(target['current_amount'])} | "
            f"{money(target['gap_amount'])} | {money(target['recommended_amount'])} | "
            f"{money(target.get('funded_amount'))} | {action} · {cell(conditions)} |"
        )
    if status["unassigned_positions"]:
        names = ", ".join(cell(item["symbol"]) for item in status["unassigned_positions"])
        lines.extend(["", ("未归类持仓：" if zh else "Unassigned positions: ") + names])
    lines.extend(["", ("等待条件：现金覆盖待核实不代表可执行；先补齐标记的数据，金额仅为配置上限，执行前仍需核验当日行情、估值、消息、交易费用及换汇可用性。"
                       if zh else "Unknown cash coverage is not executable. Resolve data flags and verify current quotes, valuation, news, fees and currency availability. Amounts are allocation caps.")])
    return "\n".join(lines)


def build_allocation_report(*, language: str = "zh", service=None) -> Optional[Dict[str, Any]]:
    """Only explicitly opted-in plans may reach existing report recipients."""
    service = service or PortfolioAllocationService()
    plans = [plan for plan in service.list_plans() if plan.get("include_in_reports")]
    if not plans:
        return None
    blocks = []
    statuses = []
    if len(plans) > 1:
        blocks.append("以下计划分别评估，可能共用账户现金；不同计划的配置金额不能叠加执行。" if language == "zh" else
                      "Plans are evaluated independently and may share account cash. Do not combine their allocation amounts.")
    for plan in plans:
        try:
            status = service.evaluate_plan(plan["id"], include_realtime=True)
            if status is None:
                raise ValueError("allocation plan is no longer active")
            statuses.append(status)
            blocks.append(render_allocation_status(status, language=language))
        except Exception:
            logger.warning("Allocation report unavailable for plan %s", plan["id"], exc_info=True)
            blocks.append(
                f"计划 #{plan['id']} 暂无法评估，请检查账户与数据；本次不提供金额。" if language == "zh" else
                f"Plan #{plan['id']} could not be evaluated. Check account data; no amount is suggested."
            )
    return {
        "title": "配置提醒" if language == "zh" else "Allocation review",
        "markdown": "\n\n".join(blocks),
        "statuses": statuses,
    }


def append_allocation_report(markdown: str, payload: Dict[str, Any]) -> str:
    section = payload.get("allocation_summary")
    if not section or ALLOCATION_MARKER in markdown:
        return markdown
    return f"{markdown.rstrip()}\n\n{ALLOCATION_MARKER}\n\n### {section['title']}\n\n{section['markdown']}"
