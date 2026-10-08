# -*- coding: utf-8 -*-
"""Deterministic target-allocation evaluation.

The engine deliberately contains no market-timing logic.  It compares a
versioned allocation plan with a normalized portfolio snapshot and returns an
allocation gap plus a capped next-batch amount.  A caller must still combine
that output with current market evidence before presenting an execution idea.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Set


ALLOCATION_ACTIONS = frozenset({"add", "hold", "reduce", "review"})
ALLOCATION_SOURCES = frozenset({"position", "cash", "manual"})
ALLOCATION_POLICIES = frozenset({"buy_only", "rebalance", "hold_only", "exit_only"})


def _finite_number(value: Any, *, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def normalize_allocation_symbol(value: Any) -> str:
    """Return a conservative comparison key without guessing the market."""

    text = str(value or "").strip().upper().replace(" ", "")
    if not text:
        return ""
    if text.endswith(".US"):
        text = text[:-3]
    return text


def _position_value(position: Mapping[str, Any]) -> float:
    if not bool(position.get("price_available", True)):
        return 0.0
    return max(0.0, _finite_number(position.get("market_value_plan")))


def _target_current_amount(
    target: Mapping[str, Any],
    *,
    cash_value: float,
    positions: List[Mapping[str, Any]],
) -> Dict[str, Any]:
    source = str(target.get("source") or "position").strip().lower()
    matched_positions: List[Dict[str, Any]] = []
    matched_indexes: Set[int] = set()
    limitations: List[str] = []

    if source == "manual":
        raw_current = target.get("current_amount")
        if raw_current is None:
            return {
                "amount": None,
                "matched_positions": [],
                "matched_indexes": set(),
                "limitations": ["manual_current_amount_missing"],
            }
        return {
            "amount": max(0.0, _finite_number(raw_current)),
            "matched_positions": [],
            "matched_indexes": set(),
            "limitations": [],
        }

    if source == "cash":
        cash_limitations = [] if bool(target.get("cash_reliable", True)) else ["cash_fx_unreliable"]
        return {
            "amount": None if cash_limitations else max(0.0, cash_value),
            "matched_positions": [],
            "matched_indexes": set(),
            "limitations": cash_limitations,
        }

    symbols = {
        normalize_allocation_symbol(symbol)
        for symbol in (target.get("symbols") or [])
        if normalize_allocation_symbol(symbol)
    }
    target_market = str(target.get("market") or "").strip().lower()
    current_amount = 0.0
    for index, position in enumerate(positions):
        symbol = normalize_allocation_symbol(position.get("symbol"))
        market = str(position.get("market") or "").strip().lower()
        if symbol not in symbols or (target_market and market != target_market):
            continue
        matched_indexes.add(index)
        value = _position_value(position)
        if not bool(position.get("price_available", True)):
            limitations.append(f"position_price_missing:{symbol}")
        elif bool(position.get("price_stale", False)) and not position.get("price_reference_usable", False):
            limitations.append(f"position_price_stale:{symbol}")
        if bool(position.get("fx_stale", False)):
            limitations.append(f"position_fx_unreliable:{symbol}")
        current_amount += value
        matched_positions.append({
            "symbol": str(position.get("symbol") or symbol),
            "market": market,
            "current_amount": round(value, 2),
            "price_available": bool(position.get("price_available", True)),
            "price_stale": bool(position.get("price_stale", False)),
        })

    return {
        "amount": None if any(item.startswith(("position_price_missing:", "position_fx_unreliable:"))
                              for item in limitations) else current_amount,
        "matched_positions": matched_positions,
        "matched_indexes": matched_indexes,
        "limitations": sorted(set(limitations)),
    }


def _allocation_action(
    *,
    current_amount: Optional[float],
    target_amount: float,
    min_amount: Optional[float],
    max_amount: Optional[float],
    batch_amount: Optional[float],
    policy: str,
    data_complete: bool,
) -> Dict[str, Any]:
    if not data_complete or current_amount is None:
        return {"action": "review", "recommended_amount": 0.0, "reason": "current_amount_unavailable"}

    gap = target_amount - current_amount
    below_band = min_amount is not None and current_amount < min_amount
    above_band = max_amount is not None and current_amount > max_amount

    if policy in {"hold_only", "exit_only"} and gap > 0:
        return {"action": "hold", "recommended_amount": 0.0, "reason": f"policy_{policy}"}

    if gap > 0:
        if policy == "rebalance" and min_amount is not None and not below_band:
            return {"action": "hold", "recommended_amount": 0.0, "reason": "inside_rebalance_band"}
        cap = gap if batch_amount is None else min(gap, batch_amount)
        reason = "below_min_band" if below_band else "below_target"
        return {"action": "add", "recommended_amount": round(max(0.0, cap), 2), "reason": reason}

    if gap < 0 and policy in {"rebalance", "exit_only"}:
        excess = current_amount - target_amount
        if max_amount is not None and not above_band and policy != "exit_only":
            return {"action": "hold", "recommended_amount": 0.0, "reason": "inside_rebalance_band"}
        cap = excess if batch_amount is None else min(excess, batch_amount)
        return {"action": "reduce", "recommended_amount": round(max(0.0, cap), 2), "reason": "above_target"}

    return {
        "action": "hold",
        "recommended_amount": 0.0,
        "reason": "at_or_above_target" if gap <= 0 else "inside_rebalance_band",
    }


def evaluate_allocation_plan(
    *,
    plan: Mapping[str, Any],
    normalized_snapshot: Mapping[str, Any],
) -> Dict[str, Any]:
    """Evaluate a plan against values already converted to plan currency."""

    total_value = _finite_number(plan.get("target_total_value"))
    if total_value <= 0:
        raise ValueError("target_total_value must be positive")

    positions = [
        item for item in (normalized_snapshot.get("positions") or [])
        if isinstance(item, Mapping)
    ]
    cash_value = max(0.0, _finite_number(normalized_snapshot.get("cash_value")))
    account_count = int(_finite_number(normalized_snapshot.get("account_count")))
    target_results: List[Dict[str, Any]] = []
    matched_position_indexes: Set[int] = set()
    plan_limitations = list(normalized_snapshot.get("limitations") or [])
    ledger_complete = bool(plan.get("ledger_complete", False))
    if not ledger_complete:
        plan_limitations.append("ledger_not_confirmed")

    for target in plan.get("targets") or []:
        source = str(target.get("source") or "position").strip().lower()
        policy = str(target.get("policy") or "buy_only").strip().lower()
        target_pct = max(0.0, _finite_number(target.get("target_pct")))
        target_amount = total_value * target_pct / 100.0
        min_pct = target.get("min_pct")
        max_pct = target.get("max_pct")
        min_amount = None if min_pct is None else total_value * _finite_number(min_pct) / 100.0
        max_amount = None if max_pct is None else total_value * _finite_number(max_pct) / 100.0
        batch_amount_value = target.get("batch_amount")
        batch_amount = None if batch_amount_value is None else max(0.0, _finite_number(batch_amount_value))

        target_for_evaluation = dict(target)
        target_for_evaluation["cash_reliable"] = bool(normalized_snapshot.get("cash_reliable", True))
        current = _target_current_amount(
            target_for_evaluation,
            cash_value=cash_value,
            positions=positions,
        )
        matched_position_indexes.update(current["matched_indexes"])
        limitations = list(current["limitations"])
        current_amount = current["amount"]
        reference_notes = sorted({note for index in current["matched_indexes"]
                                  for note in positions[index].get("reference_notes", [])})
        if source == "cash":
            reference_notes = list(normalized_snapshot.get("cash_reference_notes") or [])

        data_complete = not limitations
        if source in {"position", "cash"} and account_count <= 0:
            data_complete = False
            limitations.append("portfolio_accounts_missing")
            current_amount = None
        if source in {"position", "cash"} and not ledger_complete:
            data_complete = False
            limitations.append("ledger_not_confirmed")
            current_amount = None

        action = _allocation_action(
            current_amount=current_amount,
            target_amount=target_amount,
            min_amount=min_amount,
            max_amount=max_amount,
            batch_amount=batch_amount,
            policy=policy,
            data_complete=data_complete,
        )
        current_pct = None if current_amount is None else current_amount / total_value * 100.0
        gap_amount = None if current_amount is None else target_amount - current_amount
        if current_amount is None:
            band_status = "unknown"
        elif min_amount is not None and current_amount < min_amount:
            band_status = "below_min"
        elif max_amount is not None and current_amount > max_amount:
            band_status = "above_max"
        else:
            band_status = "inside_band"

        target_results.append({
            "key": str(target.get("key") or ""),
            "name": str(target.get("name") or target.get("key") or ""),
            "source": source,
            "policy": policy,
            "market": str(target.get("market") or "").strip().lower() or None,
            "symbols": list(target.get("symbols") or []),
            "target_pct": round(target_pct, 4),
            "target_amount": round(target_amount, 2),
            "current_pct": round(current_pct, 4) if current_pct is not None else None,
            "current_amount": round(current_amount, 2) if current_amount is not None else None,
            "gap_amount": round(gap_amount, 2) if gap_amount is not None else None,
            "min_pct": _finite_number(min_pct) if min_pct is not None else None,
            "max_pct": _finite_number(max_pct) if max_pct is not None else None,
            "batch_amount": round(batch_amount, 2) if batch_amount is not None else None,
            "band_status": band_status,
            "action": action["action"],
            "recommended_amount": action["recommended_amount"],
            "allocation_cap": action["recommended_amount"],
            "reason": action["reason"],
            "data_complete": data_complete,
            "is_estimate": bool(reference_notes),
            "reference_notes": reference_notes,
            "limitations": sorted(set(limitations)),
            "matched_positions": current["matched_positions"],
        })

    # All additions share one budget. Sale proceeds and manual balances are not
    # spendable cash until they are actually recorded in the account ledger.
    cash_target = sum(item["target_amount"] for item in target_results if item["source"] == "cash")
    reserve = max(cash_target, _finite_number(plan.get("cash_reserve_amount")))
    cash_known = ledger_complete and account_count > 0 and bool(normalized_snapshot.get("cash_reliable", True))
    reserved_orders = max(0.0, _finite_number(normalized_snapshot.get('reserved_cash_value')))
    available_cash = math.floor(max(0.0, cash_value - reserve - reserved_orders) * 100 + 1e-8) / 100 if cash_known else None
    budget_pools = [dict(b) for b in normalized_snapshot.get('budget_pools', [])]
    remaining = available_cash or 0.0
    for item in target_results:
        if item["source"] == "cash" and item["action"] in {"add", "reduce"}:
            item.update(action="hold", recommended_amount=0.0, reason="cash_reserve_only")
        elif item["action"] == "add":
            item["reference_notes"] = sorted(set(item["reference_notes"] +
                                                  list(normalized_snapshot.get("cash_reference_notes") or [])))
            item["is_estimate"] = bool(item["reference_notes"])
            if not cash_known:
                item.update(action="review", recommended_amount=0.0, reason="cash_budget_unavailable")
                item["limitations"].append("cash_budget_unavailable")
            else:
                amount = min(item["allocation_cap"], remaining)
                matches = [b for b in budget_pools if b['market'] == item['market']
                           and set(b['symbols']) & set(item['symbols'])]
                if any(b['remaining'] is None for b in matches):
                    item.update(action='review', recommended_amount=0.0, reason='period_budget_unverified')
                    item['limitations'].append('period_budget_unverified')
                    plan_limitations.append('period_budget_unverified')
                    continue
                for budget in matches:
                    amount = min(amount, max(0.0, budget['remaining']))
                amount = math.floor(max(0.0, amount) * 100 + 1e-8) / 100
                if amount < item["allocation_cap"]:
                    item["reason"] = 'period_budget_limited' if matches else "cash_budget_limited"
                for budget in matches:
                    budget['remaining'] = max(0.0, budget['remaining'] - amount)
                item["recommended_amount"] = round(amount, 2)
                if amount == 0:
                    item["action"] = "hold"
                remaining = round(remaining - amount, 2)

    # A separate, additive field: ledger-based planning caps remain compatible.
    # Confirmed cash cannot be moved between markets or pre-funded by promises.
    pools = dict(normalized_snapshot.get("confirmed_pools") or {})
    funding_known = cash_known and bool(normalized_snapshot.get("funding_complete", False))
    confirmed_cash = max(0.0, sum(pools.values()) - reserve) if funding_known else None
    funded_remaining = confirmed_cash or 0.0
    for item in target_results:
        item["funded_amount"] = None
        if funding_known and item["market"] in pools:
            amount = min(item["recommended_amount"], funded_remaining, pools[item["market"]]) if item["action"] == "add" else 0.0
            # Do not round a sub-cent cash cap upwards.
            item["funded_amount"] = math.floor(max(0.0, amount) * 100 + 1e-8) / 100
            funded_remaining = max(0.0, funded_remaining - item["funded_amount"])
            pools[item["market"]] = max(0.0, pools[item["market"]] - item["funded_amount"])

    unassigned_positions = []
    for index, position in enumerate(positions):
        if index in matched_position_indexes:
            continue
        value = _position_value(position)
        price_available = bool(position.get("price_available", True))
        if not price_available:
            plan_limitations.append(
                f"unassigned_position_price_missing:{normalize_allocation_symbol(position.get('symbol'))}"
            )
        unassigned_positions.append({
            "symbol": str(position.get("symbol") or ""),
            "market": str(position.get("market") or "").strip().lower(),
            "current_amount": round(value, 2),
            "price_available": price_available,
        })

    if any(not item["data_complete"] for item in target_results):
        plan_limitations.append("allocation_current_amount_incomplete")
    if not cash_known:
        plan_limitations.append("cash_budget_unavailable")
    if unassigned_positions:
        plan_limitations.append("unassigned_positions_present")
    if any(item["is_estimate"] for item in target_results):
        plan_limitations.append("allocation_uses_reference_data")

    known_current = sum(
        float(item["current_amount"])
        for item in target_results
        if item["current_amount"] is not None
    )
    return {
        "plan_id": plan.get("id"),
        "plan_name": str(plan.get("name") or ""),
        "plan_version": int(_finite_number(plan.get("version"), default=1.0)),
        "base_currency": str(plan.get("base_currency") or "CNY").upper(),
        "target_total_value": round(total_value, 2),
        "ledger_complete": ledger_complete,
        "cash_reserve_amount": round(reserve, 2),
        "available_cash": available_cash,
        "confirmed_cash": round(confirmed_cash, 2) if confirmed_cash is not None else None,
        "funding_accounts": normalized_snapshot.get("funding_accounts", []),
        "total_recommended_add": round(sum(
            item["recommended_amount"] for item in target_results if item["action"] == "add"
        ), 2),
        "as_of": normalized_snapshot.get("as_of"),
        "data_quality": "partial" if plan_limitations else "ok",
        "limitations": sorted(set(str(item) for item in plan_limitations if item)),
        "known_current_amount": round(known_current, 2),
        "unassigned_current_amount": round(sum(item["current_amount"] for item in unassigned_positions), 2),
        "unassigned_positions": unassigned_positions,
        "targets": target_results,
        "disclosures": [
            "recommended_amount is an allocation cap, not a market-timing or automatic trading instruction",
            "targets with incomplete current amounts require review before any action",
            "additions share the recorded cash budget after reserves, in target order; sale proceeds are not pre-spent",
            "current_pct uses target_total_value as denominator, not the partial known portfolio total",
        ],
    }
