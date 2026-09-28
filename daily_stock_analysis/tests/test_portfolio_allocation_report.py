from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.core.market_review import run_market_review
from src.core.portfolio_allocation import evaluate_allocation_plan
from src.services.portfolio_allocation_report import ALLOCATION_MARKER, build_allocation_report


def _status():
    return evaluate_allocation_plan(plan={
        "id": 1, "name": "Personal allocation", "version": 2, "base_currency": "CNY",
        "ledger_complete": True, "target_total_value": 100_000, "cash_reserve_amount": 10_000,
        "targets": [{"key": "stock", "name": "ETF", "source": "position", "symbols": ["VOO"],
                     "target_pct": 100, "policy": "buy_only", "batch_amount": 15_000}],
    }, normalized_snapshot={"account_count": 1, "as_of": "2026-09-25", "cash_value": 20_000, "positions": []})


def test_only_opted_in_plans_are_evaluated():
    service = MagicMock()
    service.list_plans.return_value = [{"id": 1, "include_in_reports": False}]
    assert build_allocation_report(service=service) is None
    service.evaluate_plan.assert_not_called()
    service.list_plans.return_value.append({"id": 2, "include_in_reports": True})
    service.evaluate_plan.return_value = _status()
    report = build_allocation_report(service=service)
    service.evaluate_plan.assert_called_once_with(2, include_realtime=True)
    assert report["statuses"][0]["total_recommended_add"] == 10_000
    assert "10,000.00" in report["markdown"]


def test_evaluation_failure_is_visible_without_failing_market_report():
    service = MagicMock()
    service.list_plans.return_value = [{"id": 1, "include_in_reports": True}]
    service.evaluate_plan.side_effect = ValueError("account no longer exists")
    report = build_allocation_report(service=service)
    assert "本次不提供金额" in report["markdown"]
    assert report["statuses"] == []


def test_multiple_plans_warn_against_combining_budgets():
    service = MagicMock()
    service.list_plans.return_value = [{"id": number, "include_in_reports": True} for number in (1, 2)]
    service.evaluate_plan.return_value = _status()
    report = build_allocation_report(service=service)
    assert "不能叠加执行" in report["markdown"]
    assert len(report["statuses"]) == 2


def test_reports_distinguish_ledger_budget_from_unknown_confirmed_cash():
    from src.services.portfolio_allocation_report import render_allocation_status
    status = _status()
    zh = render_allocation_status(status)
    en = render_allocation_status(status, language='en')
    assert '账面预算余额 10,000.00' in zh
    assert '已核实现金上限 待核实' in zh
    assert '现金覆盖待核实不代表可执行' in zh
    assert 'Confirmed cash cap Unknown' in en
    assert 'Planned deposits are excluded' in en


def test_report_files_history_notifications_and_return_share_one_allocation():
    notifier = MagicMock()
    notifier.is_available.return_value = True
    notifier.send.return_value = True
    analyzer = MagicMock()
    analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
        report="Market body", market_light_snapshot={},
        structured_payload={"sections": [{"key": "overview", "title": "Overview", "markdown": "Market body"}]},
    )
    service = MagicMock()
    service.list_plans.return_value = [{"id": 1, "include_in_reports": True}]
    service.evaluate_plan.return_value = _status()
    summary = build_allocation_report(service=service)
    for region in ("cn", "cn,us"):
        with patch("src.core.market_review.MarketAnalyzer", return_value=analyzer), \
                patch("src.core.market_review.build_allocation_report", return_value=summary) as build, \
                patch("src.core.market_review._persist_market_review_history") as persist:
            result = run_market_review(notifier, config=SimpleNamespace(report_language="zh", market_review_region=region),
                                       return_structured=True)
        build.assert_called_once()
        assert result.report.count(ALLOCATION_MARKER) == 1
        assert notifier.save_report_to_file.call_args.args[0].count(ALLOCATION_MARKER) == 1
        assert notifier.send.call_args.args[0].count(ALLOCATION_MARKER) == 1
        assert persist.call_args.kwargs["market_review_payload"]["allocation_summary"]["statuses"][0]["plan_version"] == 2


def test_context_only_run_does_not_read_personal_allocation():
    analyzer = MagicMock()
    analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(report="Market body", market_light_snapshot={})
    with patch("src.core.market_review.MarketAnalyzer", return_value=analyzer), \
            patch("src.core.market_review.build_allocation_report") as build:
        result = run_market_review(MagicMock(), config=SimpleNamespace(report_language="zh", market_review_region="us"),
                                   send_notification=False, save_report_file=False, persist_history=False)
    build.assert_not_called()
    assert ALLOCATION_MARKER not in result
