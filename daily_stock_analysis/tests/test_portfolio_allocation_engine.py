from __future__ import annotations

import unittest

from src.core.portfolio_allocation import evaluate_allocation_plan


class PortfolioAllocationEngineTest(unittest.TestCase):
    def _plan(self):
        return {
            "id": 7,
            "name": "100w target",
            "version": 1,
            "base_currency": "CNY",
            "target_total_value": 1_000_000,
            "targets": [
                {
                    "key": "liquidity",
                    "name": "流动资金",
                    "source": "cash",
                    "policy": "rebalance",
                    "symbols": [],
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
                    "min_pct": 6,
                    "max_pct": 10,
                    "batch_amount": 13_000,
                },
                {
                    "key": "fixed_income",
                    "name": "稳健固收",
                    "source": "manual",
                    "policy": "rebalance",
                    "symbols": [],
                    "target_pct": 82,
                    "batch_amount": 50_000,
                    "current_amount": 780_000,
                },
            ],
        }

    def test_evaluates_gap_and_caps_next_batch(self) -> None:
        result = evaluate_allocation_plan(
            plan=self._plan(),
            normalized_snapshot={
                "as_of": "2026-09-25",
                "account_count": 1,
                "cash_value": 90_000,
                "positions": [
                    {
                        "symbol": "VOO",
                        "market": "us",
                        "market_value_plan": 4_750,
                        "price_available": True,
                        "price_stale": False,
                    }
                ],
                "limitations": [],
            },
        )

        by_key = {item["key"]: item for item in result["targets"]}
        self.assertEqual(by_key["sp500"]["current_amount"], 4_750)
        self.assertEqual(by_key["sp500"]["gap_amount"], 75_250)
        self.assertEqual(by_key["sp500"]["action"], "add")
        self.assertEqual(by_key["sp500"]["recommended_amount"], 13_000)
        self.assertEqual(by_key["liquidity"]["action"], "add")
        self.assertEqual(result["data_quality"], "ok")

    def test_missing_manual_amount_requires_review(self) -> None:
        plan = self._plan()
        plan["targets"][2]["current_amount"] = None
        result = evaluate_allocation_plan(
            plan=plan,
            normalized_snapshot={
                "as_of": "2026-09-25",
                "account_count": 1,
                "cash_value": 100_000,
                "positions": [],
                "limitations": [],
            },
        )

        fixed_income = result["targets"][2]
        self.assertEqual(fixed_income["action"], "review")
        self.assertIsNone(fixed_income["current_amount"])
        self.assertIn("manual_current_amount_missing", fixed_income["limitations"])
        self.assertEqual(result["data_quality"], "partial")

    def test_exit_policy_reduces_overweight_position(self) -> None:
        plan = self._plan()
        plan["targets"][2] = {
            "key": "legacy_fund",
            "name": "待退出基金",
            "source": "position",
            "policy": "exit_only",
            "market": "cn",
            "symbols": ["021514"],
            "target_pct": 82,
            "batch_amount": 10_000,
        }
        result = evaluate_allocation_plan(
            plan=plan,
            normalized_snapshot={
                "as_of": "2026-09-25",
                "account_count": 1,
                "cash_value": 100_000,
                "positions": [
                    {
                        "symbol": "021514",
                        "market": "cn",
                        "market_value_plan": 850_000,
                        "price_available": True,
                    }
                ],
                "limitations": [],
            },
        )

        legacy = result["targets"][2]
        self.assertEqual(legacy["action"], "reduce")
        self.assertEqual(legacy["recommended_amount"], 10_000)

    def test_unassigned_positions_are_disclosed(self) -> None:
        result = evaluate_allocation_plan(
            plan=self._plan(),
            normalized_snapshot={
                "as_of": "2026-09-25",
                "account_count": 1,
                "cash_value": 90_000,
                "positions": [
                    {
                        "symbol": "QQQM",
                        "market": "us",
                        "market_value_plan": 25_000,
                        "price_available": True,
                    }
                ],
                "limitations": [],
            },
        )

        self.assertEqual(result["unassigned_current_amount"], 25_000)
        self.assertIn("unassigned_positions_present", result["limitations"])

    def test_unassigned_position_without_price_is_not_hidden(self) -> None:
        result = evaluate_allocation_plan(
            plan=self._plan(),
            normalized_snapshot={
                "as_of": "2026-09-25",
                "account_count": 1,
                "cash_value": 90_000,
                "positions": [
                    {
                        "symbol": "021514",
                        "market": "cn",
                        "market_value_plan": 0,
                        "price_available": False,
                    }
                ],
                "limitations": [],
            },
        )

        self.assertEqual(result["unassigned_positions"][0]["symbol"], "021514")
        self.assertFalse(result["unassigned_positions"][0]["price_available"])
        self.assertIn("unassigned_position_price_missing:021514", result["limitations"])

    def test_unreliable_fx_blocks_position_action(self) -> None:
        result = evaluate_allocation_plan(
            plan=self._plan(),
            normalized_snapshot={
                "as_of": "2026-09-25",
                "account_count": 1,
                "cash_value": 100_000,
                "cash_reliable": True,
                "positions": [
                    {
                        "symbol": "VOO",
                        "market": "us",
                        "market_value_plan": 707.63,
                        "price_available": True,
                        "fx_stale": True,
                    }
                ],
                "limitations": ["position_fx_stale:VOO:USD:fallback_1_to_1"],
            },
        )

        sp500 = next(item for item in result["targets"] if item["key"] == "sp500")
        self.assertEqual(sp500["action"], "review")
        self.assertEqual(sp500["recommended_amount"], 0)
        self.assertIn("position_fx_unreliable:VOO", sp500["limitations"])


if __name__ == "__main__":
    unittest.main()
