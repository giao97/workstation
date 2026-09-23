# -*- coding: utf-8 -*-
from datetime import datetime, timezone

import pandas as pd

from data_provider.financial_period_adapter import (
    normalize_akshare_financials,
    normalize_futu_reports,
    normalize_statement_frames,
)
from src.services.fundamental_research_service import FundamentalResearchService
from src.storage import DatabaseManager


def test_a_share_wide_statement_maps_multiple_periods() -> None:
    frame = pd.DataFrame({
        "指标": ["营业收入", "归母净利润", "经营活动产生的现金流量净额", "总资产"],
        "2025-12-31": [1000, 120, 150, 3000],
        "2024-12-31": [900, 100, 110, 2800],
    })
    periods = normalize_akshare_financials(frame, provider="stock_financial_abstract")
    assert len(periods) == 2
    assert periods[0]["provider"] == "stock_financial_abstract"
    assert periods[0]["revenue"] == 1000
    assert periods[1]["net_profit_parent"] == 100


def test_hk_futu_statements_join_by_period() -> None:
    statements = {
        "income": {"report_list": [
            {"date_time_str": "2025-12-31", "period_text": "FY2025", "currency_code": "HKD",
             "publish_date": "2026-03-20", "item_list": [
                 {"display_name": "营业额", "data": 500}, {"display_name": "净利润", "data": 60},
             ]},
            {"date_time_str": "2024-12-31", "period_text": "FY2024", "currency_code": "HKD",
             "publish_date": "2025-03-20", "item_list": [
                 {"display_name": "营业额", "data": 450}, {"display_name": "净利润", "data": 50},
             ]},
        ]},
        "cash_flow": {"report_list": [
            {"date_time_str": "2025-12-31", "item_list": [
                {"display_name": "经营现金流", "data": 80},
            ]},
        ]},
    }
    periods = normalize_futu_reports(statements)
    assert len(periods) == 2
    assert periods[0]["published_at"].startswith("2026-03-20")
    assert periods[0]["operating_cash_flow"] == 80
    assert periods[0]["provider"] == "futu"


def test_us_yfinance_statement_frames_map_three_statements() -> None:
    columns = [pd.Timestamp("2026-03-31"), pd.Timestamp("2025-12-31")]
    income = pd.DataFrame({columns[0]: {"Total Revenue": 100, "Net Income": 20}, columns[1]: {"Total Revenue": 90, "Net Income": 18}})
    balance = pd.DataFrame({columns[0]: {"Total Assets": 300, "Total Debt": 80}, columns[1]: {"Total Assets": 280, "Total Debt": 75}})
    cash = pd.DataFrame({columns[0]: {"Operating Cash Flow": 30, "Capital Expenditure": -8}, columns[1]: {"Operating Cash Flow": 25, "Capital Expenditure": -7}})
    periods = normalize_statement_frames(income=income, balance_sheet=balance, cash_flow=cash, currency="USD")
    assert len(periods) == 2
    assert periods[0]["total_assets"] == 300
    assert periods[0]["capital_expenditure"] == -8
    assert periods[0]["provider"] == "yfinance"


def _contract(*, revenue: float, published_at: str, as_of: str) -> dict:
    return {
        "stock_code": "AAPL", "market": "us", "as_of": as_of,
        "periods": [{
            "period_end": "2025-12-31", "period_type": "annual", "currency": "USD",
            "provider": "sec", "published_at": published_at, "revenue": revenue,
            "net_profit_parent": 20, "evidence_ids": ["ephemeral-run-id"],
        }],
    }


def test_financial_persistence_tracks_revisions_and_point_in_time() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    try:
        first = _contract(revenue=100, published_at="2026-03-01T00:00:00Z", as_of="2026-03-02T00:00:00Z")
        assert db.save_financial_research_contract(first) == 1
        assert db.save_financial_research_contract(first) == 0
        revised = _contract(revenue=110, published_at="2026-05-01T00:00:00Z", as_of="2026-05-02T00:00:00Z")
        assert db.save_financial_research_contract(revised) == 1

        old_view = db.get_financial_periods_as_of("AAPL", datetime(2026, 4, 1, tzinfo=timezone.utc))
        new_view = db.get_financial_periods_as_of("AAPL", datetime(2026, 6, 1, tzinfo=timezone.utc))
        assert old_view[0]["revenue"] == 100
        assert old_view[0]["revision_no"] == 1
        assert new_view[0]["revenue"] == 110
        assert new_view[0]["revision_no"] == 2
        assert new_view[0]["supersedes_id"] is not None
    finally:
        DatabaseManager.reset_instance()


def test_standard_report_has_fixed_sections_and_missing_data_is_explicit() -> None:
    context = {
        "market": "us",
        "source_chain": [{"provider": "sec", "result": "ok"}],
        "earnings": {"data": {"financial_periods": [{
            "report_date": "2025-12-31", "period": "annual", "currency": "USD",
            "provider": "sec", "published_at": "2026-03-01T00:00:00Z",
            "revenue": 100, "net_profit_parent": 20,
        }]}},
    }
    enriched = FundamentalResearchService.enrich_context(
        "AAPL", context, as_of=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    report = enriched["research"]["standard_report"]
    assert report["report_type"] == "standard"
    assert len(report["sections"]) == 13
    by_id = {section["section_id"]: section for section in report["sections"]}
    assert by_id["financial_quality"]["status"] in {"available", "limited"}
    assert by_id["peer_comparison"]["status"] == "missing"
    assert by_id["peer_comparison"]["narrative"] is None
    assert any("不自动下单" in item for item in report["disclosures"])

