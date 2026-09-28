from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch
from datetime import date
from pathlib import Path

from src.config import Config
from src.repositories.portfolio_allocation_repo import PortfolioAllocationRepository
from src.services.portfolio_allocation_service import PortfolioAllocationService
from src.storage import DatabaseManager


class _FakePortfolioService:
    def get_portfolio_snapshot(self, **_kwargs):
        return {
            "as_of": "2026-09-25",
            "account_count": 1,
            "limitations": [],
            "accounts": [
                {
                    "account_id": 1,
                    "base_currency": "CNY",
                    "total_cash": 150_000,
                    "positions": [
                        {
                            "symbol": "VOO",
                            "market": "us",
                            "market_value_base": 4_750,
                            "valuation_currency": "CNY",
                            "price_available": True,
                            "price_stale": False,
                        }
                    ],
                }
            ],
        }

    @staticmethod
    def convert_amount(*, amount, from_currency, to_currency, as_of_date):
        del from_currency, to_currency, as_of_date
        return float(amount), False, "same_currency"


class PortfolioAllocationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        env_path = root / ".env"
        db_path = root / "allocation.db"
        env_path.write_text(
            "\n".join([
                "STOCK_LIST=VOO",
                "GEMINI_API_KEY=test",
                "ADMIN_AUTH_ENABLED=false",
                f"DATABASE_PATH={db_path}",
            ]) + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(env_path)
        os.environ["DATABASE_PATH"] = str(db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        db = DatabaseManager.get_instance()
        self.service = PortfolioAllocationService(
            repo=PortfolioAllocationRepository(db),
            portfolio_service=_FakePortfolioService(),
        )

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    @staticmethod
    def _targets():
        return [
            {
                "key": "liquidity",
                "name": "流动资金",
                "source": "cash",
                "policy": "rebalance",
                "target_pct": 10,
                "min_pct": 8,
                "max_pct": 12,
                "batch_amount": 20_000,
            },
            {
                "key": "sp500",
                "name": "标普500",
                "source": "position",
                "policy": "buy_only",
                "market": "us",
                "symbols": ["VOO", "IVV"],
                "target_pct": 8,
                "batch_amount": 13_000,
            },
            {
                "key": "other",
                "name": "其他已知资产",
                "source": "manual",
                "policy": "hold_only",
                "target_pct": 82,
                "current_amount": 820_000,
            },
        ]

    def test_crud_version_and_evaluation(self) -> None:
        plan = self.service.create_plan(
            name="100w target",
            base_currency="CNY",
            target_total_value=1_000_000,
            targets=self._targets(),
            ledger_complete=True,
            include_in_reports=True,
        )
        self.assertEqual(plan["version"], 1)
        self.assertEqual(len(plan["targets"]), 3)
        self.assertTrue(self.service.get_plan(plan["id"])["include_in_reports"])

        status = self.service.evaluate_plan(plan["id"], as_of=date(2026, 9, 25))
        self.assertIsNotNone(status)
        by_key = {item["key"]: item for item in status["targets"]}
        self.assertEqual(by_key["sp500"]["gap_amount"], 75_250)
        self.assertEqual(by_key["sp500"]["recommended_amount"], 13_000)

        targets = self._targets()
        targets[1]["batch_amount"] = 10_000
        updated = self.service.update_plan(
            plan["id"],
            name="100w target",
            base_currency="CNY",
            target_total_value=1_000_000,
            targets=targets,
        )
        self.assertEqual(updated["version"], 2)
        self.assertTrue(self.service.deactivate_plan(plan["id"]))
        self.assertIsNone(self.service.get_plan(plan["id"]))

    def test_account_conversion_failure_survives_identity_conversion(self) -> None:
        snapshot = self.service.portfolio_service.get_portfolio_snapshot()
        snapshot["accounts"][0]["fx_stale"] = True
        plan = self.service.create_plan(name="test", base_currency="CNY", target_total_value=1_000_000,
                                        targets=self._targets(), ledger_complete=True)
        with patch.object(self.service.portfolio_service, "get_portfolio_snapshot", return_value=snapshot):
            status = self.service.evaluate_plan(plan["id"])
        self.assertEqual(status["targets"][1]["action"], "review")
        self.assertIsNone(status["available_cash"])

    def test_dated_fx_cache_is_stale_even_when_provider_flag_is_fresh(self) -> None:
        from src.services.portfolio_service import PortfolioService
        portfolio = PortfolioService()
        portfolio.repo.save_fx_rate(from_currency="USD", to_currency="CNY", rate_date=date(2026, 9, 24),
                                    rate=7.0, source="test", is_stale=False)
        for source, target in (("USD", "CNY"), ("CNY", "USD")):
            _, stale, _ = portfolio.convert_amount(amount=100, from_currency=source, to_currency=target,
                                                   as_of_date=date(2026, 9, 25))
            self.assertTrue(stale)
        _, stale, _ = portfolio.convert_amount(amount=100, from_currency="USD", to_currency="CNY",
                                               as_of_date=date(2026, 9, 24))
        self.assertFalse(stale)

    def test_evaluation_cannot_override_plan_scope(self) -> None:
        plan = self.service.create_plan(name="test", base_currency="CNY", target_total_value=1_000_000,
                                        targets=self._targets())
        with self.assertRaisesRegex(ValueError, "scope"):
            self.service.evaluate_plan(plan["id"], account_id=7)
        scoped = self.service.create_plan(name="test", base_currency="CNY", target_total_value=1_000_000,
                                          targets=self._targets(), account_id=7)
        with patch.object(self.service.portfolio_service, "get_portfolio_snapshot",
                          wraps=self.service.portfolio_service.get_portfolio_snapshot) as get_snapshot:
            self.service.evaluate_plan(scoped["id"])
        self.assertEqual(get_snapshot.call_args.kwargs["account_id"], 7)

    def test_old_schema_is_upgraded_without_confirming_unknown_balances(self) -> None:
        from sqlalchemy import inspect
        db = self.service.repo.db
        old_plan = self.service.create_plan(name="existing", base_currency="CNY", target_total_value=1_000_000,
                                            targets=self._targets(), ledger_complete=True, include_in_reports=True)
        with db._engine.begin() as connection:
            for column in ("account_id", "ledger_complete", "cash_reserve_amount", "include_in_reports"):
                connection.exec_driver_sql(f"ALTER TABLE portfolio_allocation_plans DROP COLUMN {column}")
        db._ensure_portfolio_allocation_schema_record()
        db._ensure_portfolio_allocation_schema_record()
        columns = {column["name"] for column in inspect(db._engine).get_columns("portfolio_allocation_plans")}
        self.assertTrue({"account_id", "ledger_complete", "cash_reserve_amount", "include_in_reports"} <= columns)
        migrated = self.service.get_plan(old_plan["id"])
        self.assertFalse(migrated["ledger_complete"])
        self.assertFalse(migrated["include_in_reports"])
        self.assertEqual(len(migrated["targets"]), 3)
        plan = self.service.create_plan(name="migrated", base_currency="CNY", target_total_value=1_000_000,
                                        targets=self._targets())
        self.assertFalse(plan["ledger_complete"])
        self.assertFalse(plan["include_in_reports"])

    def test_rejects_invalid_total_and_duplicate_symbol(self) -> None:
        with self.assertRaisesRegex(ValueError, "sum to 100"):
            self.service.create_plan(
                name="bad",
                base_currency="CNY",
                target_total_value=1_000_000,
                targets=[{
                    "key": "cash",
                    "name": "cash",
                    "source": "cash",
                    "target_pct": 10,
                }],
            )

        targets = self._targets()
        targets[2] = {
            "key": "duplicate",
            "name": "duplicate",
            "source": "position",
            "policy": "buy_only",
            "market": "us",
            "symbols": ["VOO"],
            "target_pct": 82,
        }
        with self.assertRaisesRegex(ValueError, "assigned to both"):
            self.service.create_plan(
                name="bad duplicate",
                base_currency="CNY",
                target_total_value=1_000_000,
                targets=targets,
            )


if __name__ == "__main__":
    unittest.main()
