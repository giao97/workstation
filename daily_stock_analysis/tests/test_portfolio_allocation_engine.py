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
            "ledger_complete": True,
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
                "cash_value": 150_000,
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
        self.assertEqual(by_key["liquidity"]["action"], "hold")
        self.assertEqual(result["available_cash"], 50_000)
        self.assertEqual(result["total_recommended_add"], 50_000)
        self.assertEqual(by_key["fixed_income"]["recommended_amount"], 37_000)
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

    def test_unconfirmed_ledger_is_unknown_even_with_an_account(self) -> None:
        plan = self._plan()
        plan["ledger_complete"] = False
        result = evaluate_allocation_plan(plan=plan, normalized_snapshot={
            "account_count": 1, "cash_value": 200_000, "positions": [],
        })
        sp500 = result["targets"][1]
        self.assertIsNone(sp500["current_amount"])
        self.assertIsNone(sp500["gap_amount"])
        self.assertEqual(sp500["action"], "review")
        self.assertIsNone(result["available_cash"])
        self.assertEqual(result["total_recommended_add"], 0)

    def test_confirmed_zero_is_distinct_from_unknown(self) -> None:
        result = evaluate_allocation_plan(plan=self._plan(), normalized_snapshot={
            "account_count": 1, "cash_value": 200_000, "positions": [],
        })
        self.assertEqual(result["targets"][1]["current_amount"], 0)
        self.assertEqual(result["targets"][1]["action"], "add")

    def test_missing_accounts_are_unknown_even_if_ledger_was_confirmed(self) -> None:
        result = evaluate_allocation_plan(plan=self._plan(), normalized_snapshot={
            "account_count": 0, "cash_value": 0, "positions": [],
        })
        for target in result["targets"]:
            if target["source"] in {"position", "cash"}:
                self.assertIsNone(target["current_amount"])
                self.assertEqual(target["action"], "review")

    def test_stale_quote_requires_review(self) -> None:
        result = evaluate_allocation_plan(plan=self._plan(), normalized_snapshot={
            "account_count": 1, "cash_value": 200_000,
            "positions": [{"symbol": "VOO", "market": "us", "market_value_plan": 5_000,
                           "price_available": True, "price_stale": True}],
        })
        self.assertEqual(result["targets"][1]["action"], "review")
        self.assertEqual(result["targets"][1]["recommended_amount"], 0)

    def test_cash_reserve_and_unsettled_reductions_do_not_fund_additions(self) -> None:
        plan = self._plan()
        plan["cash_reserve_amount"] = 120_000
        plan["targets"][2]["current_amount"] = 900_000
        result = evaluate_allocation_plan(plan=plan, normalized_snapshot={
            "account_count": 1, "cash_value": 125_000, "positions": [],
        })
        self.assertEqual(result["targets"][2]["action"], "reduce")
        self.assertEqual(result["available_cash"], 5_000)
        self.assertEqual(result["targets"][1]["recommended_amount"], 5_000)
        self.assertEqual(result["total_recommended_add"], 5_000)

    def test_unreliable_cash_blocks_additions_but_preserves_gap(self) -> None:
        result = evaluate_allocation_plan(plan=self._plan(), normalized_snapshot={
            "account_count": 1, "cash_value": 200_000, "cash_reliable": False, "positions": [],
        })
        self.assertEqual(result["targets"][1]["gap_amount"], 80_000)
        self.assertEqual(result["targets"][1]["action"], "review")
        self.assertEqual(result["total_recommended_add"], 0)

    def test_rebalance_inside_lower_band_holds(self) -> None:
        result = evaluate_allocation_plan(plan=self._plan(), normalized_snapshot={
            "account_count": 1, "cash_value": 90_000, "positions": [],
        })
        self.assertEqual(result["targets"][0]["action"], "hold")
        self.assertEqual(result["targets"][0]["reason"], "inside_rebalance_band")

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
