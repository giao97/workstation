# -*- coding: utf-8 -*-
"""Tests for evidence timing and normalized fundamental research."""

from datetime import date, datetime, timedelta, timezone
import unittest

from pydantic import ValidationError

from src.schemas.financial_research import FinancialPeriod, FundamentalResearchContract
from src.schemas.research_evidence import EvidenceRecord, EvidenceSnapshot
from src.services.financial_quality_service import compute_financial_quality
from src.services.fundamental_research_service import FundamentalResearchService


class FundamentalResearchContractTest(unittest.TestCase):
    def test_evidence_snapshot_rejects_future_publication(self) -> None:
        as_of = datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc)
        record = EvidenceRecord(
            evidence_id="ev-future",
            stock_code="600519",
            market="cn",
            provider="cninfo",
            published_at=as_of + timedelta(minutes=1),
            retrieved_at=as_of,
        )
        with self.assertRaisesRegex(ValidationError, "not available at as_of"):
            EvidenceSnapshot(
                stock_code="600519",
                market="cn",
                as_of=as_of,
                records=[record],
            )

    def test_fundamental_contract_rejects_period_published_after_cutoff(self) -> None:
        as_of = datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc)
        evidence = EvidenceSnapshot(
            stock_code="600519",
            market="cn",
            as_of=as_of,
        )
        period = FinancialPeriod(
            period_end=date(2026, 6, 30),
            period_type="interim",
            published_at=as_of + timedelta(days=1),
            revenue=100.0,
        )
        with self.assertRaisesRegex(ValidationError, "were not published at as_of"):
            FundamentalResearchContract(
                stock_code="600519",
                market="cn",
                as_of=as_of,
                evidence=evidence,
                periods=[period],
                quality=compute_financial_quality([period]),
            )

    def test_compute_financial_quality_uses_reproducible_formulas(self) -> None:
        latest = FinancialPeriod(
            period_end=date(2025, 12, 31),
            period_type="annual",
            revenue=120.0,
            gross_profit=48.0,
            operating_income=30.0,
            net_profit_parent=24.0,
            operating_cash_flow=18.0,
            capital_expenditure=-6.0,
            total_assets=200.0,
            total_equity=100.0,
            total_debt=80.0,
            cash_and_equivalents=20.0,
            basic_eps=2.4,
            roe_pct=24.0,
        )
        previous = FinancialPeriod(
            period_end=date(2024, 12, 31),
            period_type="annual",
            revenue=100.0,
            net_profit_parent=20.0,
        )
        quality = compute_financial_quality([previous, latest])
        self.assertEqual(quality.gross_margin_pct, 40.0)
        self.assertEqual(quality.operating_margin_pct, 25.0)
        self.assertEqual(quality.net_margin_pct, 20.0)
        self.assertEqual(quality.cash_conversion_pct, 75.0)
        self.assertEqual(quality.debt_to_assets_pct, 40.0)
        self.assertEqual(quality.free_cash_flow, 12.0)
        self.assertEqual(quality.revenue_growth_pct, 20.0)
        self.assertEqual(quality.net_profit_growth_pct, 20.0)
        self.assertEqual(quality.completeness_pct, 100.0)
        self.assertEqual(quality.flags, [])

    def test_compute_financial_quality_flags_profit_cash_flow_divergence(self) -> None:
        period = FinancialPeriod(
            period_end=date(2025, 12, 31),
            period_type="annual",
            revenue=100.0,
            net_profit_parent=10.0,
            operating_cash_flow=-2.0,
        )
        quality = compute_financial_quality([period])
        self.assertIn("positive_profit_negative_operating_cash_flow", quality.flags)
        self.assertIsNone(quality.revenue_growth_pct)

    def test_enrich_context_preserves_legacy_blocks_and_adds_research_contract(self) -> None:
        as_of = datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc)
        legacy = {
            "market": "cn",
            "status": "partial",
            "valuation": {"status": "ok", "data": {"pe_ratio": 18.0}},
            "earnings": {
                "status": "ok",
                "data": {
                    "financial_report": {
                        "report_date": "2025-12-31",
                        "currency": "CNY",
                        "revenue": 120.0,
                        "gross_profit": 48.0,
                        "net_profit_parent": 24.0,
                        "operating_cash_flow": 18.0,
                        "roe": 24.0,
                    }
                },
            },
            "source_chain": [
                {"provider": "akshare.stock_financial_abstract", "result": "ok", "duration_ms": 12}
            ],
            "coverage": {"valuation": "ok", "earnings": "ok"},
        }
        enriched = FundamentalResearchService.enrich_context("600519", legacy, as_of=as_of)
        self.assertIs(enriched["valuation"], legacy["valuation"])
        self.assertEqual(enriched["coverage"], legacy["coverage"])
        self.assertEqual(enriched["as_of"], as_of.isoformat())
        research = enriched["research"]
        self.assertEqual(research["status"], "partial")
        self.assertEqual(research["data"]["stock_code"], "600519")
        self.assertEqual(research["data"]["periods"][0]["period_end"], "2025-12-31")
        self.assertEqual(research["data"]["quality"]["gross_margin_pct"], 40.0)
        self.assertIn("financial_report_publication_time_missing", research["data"]["warnings"])

    def test_enrich_context_does_not_invent_missing_financial_periods(self) -> None:
        enriched = FundamentalResearchService.enrich_context(
            "AAPL",
            {"market": "us", "status": "partial", "source_chain": []},
            as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
        )
        research = enriched["research"]
        self.assertEqual(research["status"], "not_supported")
        self.assertEqual(research["data"]["periods"], [])
        self.assertEqual(research["data"]["quality"]["completeness_pct"], 0.0)
        self.assertIn("normalized_financial_periods_missing", research["data"]["warnings"])

    def test_enrich_context_normalizes_multiple_periods_and_growth(self) -> None:
        context = {
            "market": "us",
            "status": "ok",
            "earnings": {
                "status": "ok",
                "data": {
                    "financial_periods": [
                        {
                            "report_date": "2025-12-31",
                            "period_type": "annual",
                            "published_at": "2026-02-01T00:00:00+00:00",
                            "currency": "USD",
                            "revenue": 120.0,
                            "net_profit_parent": 24.0,
                        },
                        {
                            "report_date": "2024-12-31",
                            "period_type": "annual",
                            "published_at": "2025-02-01T00:00:00+00:00",
                            "currency": "USD",
                            "revenue": 100.0,
                            "net_profit_parent": 20.0,
                        },
                    ]
                },
            },
            "source_chain": [{"provider": "sec.companyfacts", "result": "ok"}],
        }
        enriched = FundamentalResearchService.enrich_context(
            "AAPL",
            context,
            as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
        )
        research = enriched["research"]["data"]
        self.assertEqual(len(research["periods"]), 2)
        self.assertEqual(research["quality"]["revenue_growth_pct"], 20.0)
        self.assertEqual(research["quality"]["net_profit_growth_pct"], 20.0)
        self.assertNotIn("financial_report_publication_time_missing", research["warnings"])


if __name__ == "__main__":
    unittest.main()
