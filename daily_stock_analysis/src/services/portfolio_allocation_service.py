# -*- coding: utf-8 -*-
"""Target-allocation plan CRUD and deterministic gap evaluation."""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from src.core.portfolio_allocation import (
    ALLOCATION_POLICIES,
    ALLOCATION_SOURCES,
    evaluate_allocation_plan,
    normalize_allocation_symbol,
)
from src.repositories.portfolio_allocation_repo import PortfolioAllocationRepository
from data_provider.realtime_types import parse_quote_timestamp
from src.core.trading_calendar import get_market_now, is_latest_completed_close

if TYPE_CHECKING:
    from src.services.portfolio_service import PortfolioService


_TARGET_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SUPPORTED_MARKETS = frozenset({"cn", "hk", "us", "jp", "kr", "tw"})


class PortfolioAllocationService:
    def __init__(
        self,
        *,
        repo: Optional[PortfolioAllocationRepository] = None,
        portfolio_service: Optional["PortfolioService"] = None,
    ):
        self.repo = repo or PortfolioAllocationRepository()
        if portfolio_service is None:
            from src.services.portfolio_service import PortfolioService

            portfolio_service = PortfolioService()
        self.portfolio_service = portfolio_service

    def create_plan(
        self,
        *,
        name: str,
        base_currency: str,
        target_total_value: float,
        targets: Sequence[Dict[str, Any]],
        owner_id: Optional[str] = None,
        account_id: Optional[int] = None,
        ledger_complete: bool = False,
        cash_reserve_amount: float = 0.0,
        include_in_reports: bool = False,
    ) -> Dict[str, Any]:
        normalized = self._validate_plan(
            name=name,
            base_currency=base_currency,
            target_total_value=target_total_value,
            targets=targets,
            owner_id=owner_id,
            account_id=account_id,
            ledger_complete=ledger_complete,
            cash_reserve_amount=cash_reserve_amount,
            include_in_reports=include_in_reports,
        )
        plan, target_rows = self.repo.create_plan(**normalized)
        return self._serialize_plan(plan, target_rows)

    def update_plan(
        self,
        plan_id: int,
        *,
        name: str,
        base_currency: str,
        target_total_value: float,
        targets: Sequence[Dict[str, Any]],
        owner_id: Optional[str] = None,
        account_id: Optional[int] = None,
        ledger_complete: bool = False,
        cash_reserve_amount: float = 0.0,
        include_in_reports: bool = False,
    ) -> Optional[Dict[str, Any]]:
        normalized = self._validate_plan(
            name=name,
            base_currency=base_currency,
            target_total_value=target_total_value,
            targets=targets,
            owner_id=owner_id,
            account_id=account_id,
            ledger_complete=ledger_complete,
            cash_reserve_amount=cash_reserve_amount,
            include_in_reports=include_in_reports,
        )
        result = self.repo.update_plan(plan_id=plan_id, **normalized)
        if result is None:
            return None
        plan, target_rows = result
        return self._serialize_plan(plan, target_rows)

    def get_plan(self, plan_id: int, *, include_inactive: bool = False) -> Optional[Dict[str, Any]]:
        result = self.repo.get_plan(plan_id, include_inactive=include_inactive)
        if result is None:
            return None
        return self._serialize_plan(*result)

    def list_plans(self, *, include_inactive: bool = False) -> List[Dict[str, Any]]:
        return [self.repo.plan_to_dict(row) for row in self.repo.list_plans(include_inactive=include_inactive)]

    def deactivate_plan(self, plan_id: int) -> bool:
        return self.repo.deactivate_plan(plan_id)

    def evaluate_plan(
        self,
        plan_id: int,
        *,
        account_id: Optional[int] = None,
        as_of: Optional[date] = None,
        cost_method: str = "fifo",
        include_realtime: bool = True,
    ) -> Optional[Dict[str, Any]]:
        plan = self.get_plan(plan_id)
        if plan is None:
            return None
        plan_account = plan.get("account_id")
        if account_id is not None and account_id != plan_account:
            raise ValueError("account_id must match the plan scope; do not evaluate a full plan against one account")
        account_id = plan_account
        as_of_date = as_of or date.today()
        snapshot = self.portfolio_service.get_portfolio_snapshot(
            account_id=account_id,
            as_of=as_of_date,
            cost_method=cost_method,
            include_realtime=include_realtime,
        )
        from src.repositories.portfolio_repo import PortfolioRepository
        from src.services.portfolio_budget_service import PortfolioBudgetService
        budgets = PortfolioBudgetService(PortfolioRepository(self.repo.db))
        for account in snapshot.get('accounts') or []:
            account['budget_periods'] = budgets.list_status(account['account_id'], require_account=False)
            account['budget_history_unavailable'] = bool(account['budget_periods']) and as_of_date != date.today()
        normalized_snapshot = self._normalize_snapshot(
            snapshot=snapshot,
            plan_currency=plan["base_currency"],
            as_of_date=as_of_date,
        )
        result = evaluate_allocation_plan(plan=plan, normalized_snapshot=normalized_snapshot)
        result["account_id"] = account_id
        result["cost_method"] = cost_method
        result["include_realtime"] = bool(include_realtime)
        # Current research annotations only, independent of cash/gap computation.
        # Historical evaluations must not leak reviews created after their as_of.
        from src.services.allocation_review_service import AllocationReviewService
        from src.repositories.allocation_review_repo import AllocationReviewRepository
        if as_of is None or as_of == date.today():
            from src.services.core_entry_service import CoreEntryService
            CoreEntryService(self.repo).annotate(result, snapshot)
            reviews = AllocationReviewService(AllocationReviewRepository(self.repo.db)).latest(plan_id)
            for target in result["targets"]:
                target["research_reviews"] = [dict(item, state="plan_changed")
                    if item["expected_plan_version"] != result["plan_version"] else item
                    for item in reviews if item["target_key"] == target["key"]]
        return result

    def _normalize_snapshot(
        self,
        *,
        snapshot: Dict[str, Any],
        plan_currency: str,
        as_of_date: date,
    ) -> Dict[str, Any]:
        cash_value = 0.0
        cash_reliable = True
        positions: List[Dict[str, Any]] = []
        limitations = list(snapshot.get("limitations") or [])
        cash_reference_notes: List[str] = []
        confirmed_pools: Dict[str, float] = {}
        funding_accounts = []
        funding_complete = True
        reserved_cash_value = 0.0
        budget_pools = []

        def convert(amount, currency):
            converter = getattr(self.portfolio_service, "convert_amount_for_allocation", None)
            if converter is not None:
                return converter(amount=amount, from_currency=currency, to_currency=plan_currency,
                                 as_of_date=as_of_date)
            value, stale, _ = self.portfolio_service.convert_amount(
                amount=amount, from_currency=currency, to_currency=plan_currency, as_of_date=as_of_date)
            return value, not stale, None

        for account in snapshot.get("accounts") or []:
            account_fx_stale = bool(account.get("fx_stale", False))
            account_currency = str(account.get("base_currency") or plan_currency).upper()
            native_cash = account.get("cash_balances")
            funding = account.get("funding") or {}
            observed = funding.get("funding") or {}
            cash_cap = funding.get("confirmed_cash_cap")
            budget_periods = account.get('budget_periods') or []
            native_reserved = sum(b['native_reserved'] for b in budget_periods)
            converted_reserved, reliable_reserved, _ = convert(native_reserved, account_currency)
            reserved_cash_value += converted_reserved
            if not reliable_reserved or account.get('budget_history_unavailable'):
                cash_reliable = False
                limitations.append('budget_reservation_unverified')
            for budget in budget_periods:
                # No automatic monthly renewal. A previous/future configured
                # budget keeps covered symbols blocked until a current period exists.
                covered_now = {s for b in budget_periods if b['active_period'] for s in b['symbols']}
                symbols = budget['symbols'] if budget['active_period'] else [s for s in budget['symbols'] if s not in covered_now]
                if not symbols:
                    continue
                cap = budget['remaining_amount']
                if not budget['active_period']:
                    cap = 0.0
                converted_budget, reliable_budget, _ = convert(cap or 0, budget['currency'])
                budget_pools.append({'id': budget['id'], 'market': account.get('market'),
                    'symbols': symbols, 'remaining': converted_budget if cap is not None and reliable_budget else None})
            funding_accounts.append({"account_id": account.get("account_id"), "currency": account_currency,
                                     "cash_confirmed": bool(funding.get("cash_confirmed")),
                                     "confirmed_cash_cap": cash_cap,
                                     "planned_deposit": observed.get("planned_deposit"),
                                     "planned_deposit_date": observed.get("planned_deposit_date")})
            if cash_cap is None or not funding.get("cash_confirmed") or not isinstance(native_cash, dict):
                funding_complete = False
            else:
                cap = max(0.0, min(max(0.0, float(native_cash.get(account_currency, 0))),
                                  max(0.0, float(cash_cap))) - native_reserved)
                converted_cap, reliable_cap, _ = convert(cap, account_currency)
                market = account.get("market")
                native_currency = {"cn": "CNY", "us": "USD", "hk": "HKD", "jp": "JPY", "kr": "KRW", "tw": "TWD"}.get(market)
                if not reliable_cap or native_currency != account_currency:
                    funding_complete = False
                else:
                    confirmed_pools[market] = confirmed_pools.get(market, 0.0) + converted_cap
            # Revalue actual cash currencies, not an account total already polluted
            # by missing FX or the historical P&L conversion quality flag.
            balances = native_cash if isinstance(native_cash, dict) else {
                account_currency: float(account.get("total_cash") or 0.0)}
            for currency, amount in balances.items():
                converted_cash, reliable, note = convert(float(amount), currency)
                cash_value += converted_cash
                if not reliable or (native_cash is None and account_fx_stale):
                    cash_reliable = False
                    limitations.append(f"cash_fx_stale:{currency}")
                if note:
                    cash_reference_notes.append(note)

            for position in account.get("positions") or []:
                native_value = all(position.get(key) is not None for key in ("quantity", "last_price", "currency"))
                valuation_currency = str(position["currency"] if native_value else
                                         position.get("valuation_currency") or account_currency).upper()
                value = (float(position["quantity"]) * float(position["last_price"]) if native_value else
                         float(position.get("market_value_base") or 0.0))
                converted_value, reliable, note = convert(value, valuation_currency)
                fx_stale = not reliable or (not native_value and account_fx_stale)
                if fx_stale:
                    limitations.append(f"position_fx_stale:{position.get('symbol')}:{valuation_currency}")
                reference_notes = [note] if note else []
                close_reference = self._close_reference(position, as_of_date)
                if close_reference:
                    reference_notes.append(close_reference)
                positions.append({
                    "account_id": account.get("account_id"),
                    "symbol": position.get("symbol"),
                    "market": position.get("market"),
                    "market_value_plan": converted_value,
                    "price_available": bool(position.get("price_available", True)),
                    "price_stale": bool(position.get("price_stale", False)) or position.get("price_source") == "history_close",
                    "price_reference_usable": bool(close_reference),
                    "reference_notes": reference_notes,
                    "fx_stale": bool(fx_stale),
                })

        return {
            "as_of": snapshot.get("as_of") or as_of_date.isoformat(),
            "account_count": int(snapshot.get("account_count") or 0),
            "cash_value": cash_value,
            "reserved_cash_value": reserved_cash_value,
            "budget_pools": budget_pools,
            "cash_reliable": cash_reliable,
            "cash_reference_notes": sorted(set(cash_reference_notes)),
            "funding_complete": funding_complete,
            "confirmed_pools": confirmed_pools,
            "funding_accounts": funding_accounts,
            "positions": positions,
            "limitations": sorted(set(limitations)),
        }

    @staticmethod
    def _close_reference(position: Dict[str, Any], as_of_date: date) -> Optional[str]:
        if not position.get("price_available", True):
            return None
        market = str(position.get("market") or "")
        if market not in _SUPPORTED_MARKETS:
            return None
        now = datetime.now(timezone.utc)
        if as_of_date != date.today():
            # A historical as-of snapshot is evaluated at that market's day end,
            # never using a future instant beyond the actual evaluation time.
            now = min(now, get_market_now(market, datetime.combine(as_of_date, time.max)))
        is_bar = position.get("price_source") == "history_close"
        instant = parse_quote_timestamp(position.get("price_timestamp"))
        if not is_bar and instant is None:
            return None
        try:
            observed = (date.fromisoformat(position["price_date"]) if is_bar else
                        get_market_now(market, instant).date())
        except (TypeError, ValueError, KeyError):
            return None
        if is_latest_completed_close(market, observed, quote_time=None if is_bar else instant, current_time=now):
            return f"close_reference:{position.get('symbol')}:{observed.isoformat()}"
        return None

    @classmethod
    def _validate_plan(
        cls,
        *,
        name: str,
        base_currency: str,
        target_total_value: float,
        targets: Sequence[Dict[str, Any]],
        owner_id: Optional[str],
        account_id: Optional[int] = None,
        ledger_complete: bool = False,
        cash_reserve_amount: float = 0.0,
        include_in_reports: bool = False,
    ) -> Dict[str, Any]:
        name_norm = str(name or "").strip()
        if not name_norm or len(name_norm) > 96:
            raise ValueError("name must contain 1 to 96 characters")
        currency = str(base_currency or "").strip().upper()
        if len(currency) < 3 or len(currency) > 8:
            raise ValueError("base_currency must contain 3 to 8 characters")
        total_value = cls._positive_finite(target_total_value, "target_total_value")
        if account_id is not None and (type(account_id) is not int or account_id <= 0):
            raise ValueError("account_id must be a positive integer")
        if type(ledger_complete) is not bool or type(include_in_reports) is not bool:
            raise ValueError("ledger_complete and include_in_reports must be booleans")
        reserve = cls._nonnegative_finite(cash_reserve_amount, "cash_reserve_amount")
        if reserve > total_value:
            raise ValueError("cash_reserve_amount cannot exceed target_total_value")
        owner_norm = str(owner_id).strip() if owner_id not in (None, "") else None
        if owner_norm is not None and len(owner_norm) > 64:
            raise ValueError("owner_id must contain at most 64 characters")
        if not targets:
            raise ValueError("targets must not be empty")

        normalized_targets: List[Dict[str, Any]] = []
        seen_keys = set()
        seen_symbols: Dict[str, str] = {}
        cash_targets = 0
        target_pct_sum = 0.0
        for index, raw in enumerate(targets):
            target = dict(raw)
            key = str(target.get("key") or "").strip().lower()
            if not _TARGET_KEY_RE.fullmatch(key):
                raise ValueError(f"invalid target key: {key or '<empty>'}")
            if key in seen_keys:
                raise ValueError(f"duplicate target key: {key}")
            seen_keys.add(key)

            target_name = str(target.get("name") or "").strip()
            if not target_name or len(target_name) > 96:
                raise ValueError(f"target {key} name must contain 1 to 96 characters")
            source = str(target.get("source") or "position").strip().lower()
            policy = str(target.get("policy") or "buy_only").strip().lower()
            if source not in ALLOCATION_SOURCES:
                raise ValueError(f"target {key} source must be one of {sorted(ALLOCATION_SOURCES)}")
            if policy not in ALLOCATION_POLICIES:
                raise ValueError(f"target {key} policy must be one of {sorted(ALLOCATION_POLICIES)}")

            market = str(target.get("market") or "").strip().lower() or None
            if market is not None and market not in _SUPPORTED_MARKETS:
                raise ValueError(f"target {key} market is unsupported: {market}")
            symbols = []
            for raw_symbol in target.get("symbols") or []:
                symbol = normalize_allocation_symbol(raw_symbol)
                if symbol and symbol not in symbols:
                    symbols.append(symbol)
            if source == "position" and not symbols:
                raise ValueError(f"target {key} position source requires symbols")
            if source != "position" and symbols:
                raise ValueError(f"target {key} symbols are only valid for position source")
            if source == "cash":
                cash_targets += 1
                if cash_targets > 1:
                    raise ValueError("only one cash target is allowed per plan")

            for symbol in symbols:
                previous = seen_symbols.get(symbol)
                if previous is not None:
                    raise ValueError(f"symbol {symbol} is assigned to both {previous} and {key}")
                seen_symbols[symbol] = key

            target_pct = cls._bounded_pct(target.get("target_pct"), f"target {key} target_pct")
            min_pct = cls._optional_pct(target.get("min_pct"), f"target {key} min_pct")
            max_pct = cls._optional_pct(target.get("max_pct"), f"target {key} max_pct")
            if min_pct is not None and min_pct > target_pct:
                raise ValueError(f"target {key} min_pct cannot exceed target_pct")
            if max_pct is not None and max_pct < target_pct:
                raise ValueError(f"target {key} max_pct cannot be below target_pct")
            if min_pct is not None and max_pct is not None and min_pct > max_pct:
                raise ValueError(f"target {key} min_pct cannot exceed max_pct")

            batch_amount = target.get("batch_amount")
            if batch_amount is not None:
                batch_amount = cls._positive_finite(batch_amount, f"target {key} batch_amount")
            current_amount = target.get("current_amount")
            if current_amount is not None:
                current_amount = cls._nonnegative_finite(current_amount, f"target {key} current_amount")
            if source != "manual" and current_amount is not None:
                raise ValueError(f"target {key} current_amount is only valid for manual source")

            note = str(target.get("note") or "").strip() or None
            if note is not None and len(note) > 500:
                raise ValueError(f"target {key} note must contain at most 500 characters")
            sort_order = int(target.get("sort_order", index))
            normalized_targets.append({
                "key": key,
                "name": target_name,
                "source": source,
                "policy": policy,
                "market": market,
                "symbols": symbols,
                "target_pct": target_pct,
                "min_pct": min_pct,
                "max_pct": max_pct,
                "batch_amount": batch_amount,
                "current_amount": current_amount,
                "sort_order": sort_order,
                "note": note,
            })
            target_pct_sum += target_pct

        if not math.isclose(target_pct_sum, 100.0, rel_tol=0.0, abs_tol=0.01):
            raise ValueError(f"target_pct must sum to 100, got {target_pct_sum:.4f}")

        return {
            "name": name_norm,
            "owner_id": owner_norm,
            "base_currency": currency,
            "target_total_value": total_value,
            "account_id": account_id,
            "ledger_complete": ledger_complete,
            "cash_reserve_amount": reserve,
            "include_in_reports": include_in_reports,
            "targets": normalized_targets,
        }

    def _serialize_plan(self, plan: Any, target_rows: Sequence[Any]) -> Dict[str, Any]:
        payload = self.repo.plan_to_dict(plan)
        payload["targets"] = [self.repo.target_to_dict(row) for row in target_rows]
        return payload

    @staticmethod
    def _positive_finite(value: Any, field: str) -> float:
        parsed = PortfolioAllocationService._nonnegative_finite(value, field)
        if parsed <= 0:
            raise ValueError(f"{field} must be positive")
        return parsed

    @staticmethod
    def _nonnegative_finite(value: Any, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} must be a finite number")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be a finite number") from exc
        if not math.isfinite(parsed) or parsed < 0:
            raise ValueError(f"{field} must be a non-negative finite number")
        return parsed

    @classmethod
    def _bounded_pct(cls, value: Any, field: str) -> float:
        parsed = cls._nonnegative_finite(value, field)
        if parsed > 100:
            raise ValueError(f"{field} must be between 0 and 100")
        return parsed

    @classmethod
    def _optional_pct(cls, value: Any, field: str) -> Optional[float]:
        if value is None:
            return None
        return cls._bounded_pct(value, field)
