# -*- coding: utf-8 -*-
"""Target-allocation plan CRUD and deterministic gap evaluation."""

from __future__ import annotations

import math
import re
from datetime import date
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from src.core.portfolio_allocation import (
    ALLOCATION_POLICIES,
    ALLOCATION_SOURCES,
    evaluate_allocation_plan,
    normalize_allocation_symbol,
)
from src.repositories.portfolio_allocation_repo import PortfolioAllocationRepository

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
    ) -> Dict[str, Any]:
        normalized = self._validate_plan(
            name=name,
            base_currency=base_currency,
            target_total_value=target_total_value,
            targets=targets,
            owner_id=owner_id,
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
    ) -> Optional[Dict[str, Any]]:
        normalized = self._validate_plan(
            name=name,
            base_currency=base_currency,
            target_total_value=target_total_value,
            targets=targets,
            owner_id=owner_id,
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
        as_of_date = as_of or date.today()
        snapshot = self.portfolio_service.get_portfolio_snapshot(
            account_id=account_id,
            as_of=as_of_date,
            cost_method=cost_method,
            include_realtime=include_realtime,
        )
        normalized_snapshot = self._normalize_snapshot(
            snapshot=snapshot,
            plan_currency=plan["base_currency"],
            as_of_date=as_of_date,
        )
        result = evaluate_allocation_plan(plan=plan, normalized_snapshot=normalized_snapshot)
        result["account_id"] = account_id
        result["cost_method"] = cost_method
        result["include_realtime"] = bool(include_realtime)
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
        for account in snapshot.get("accounts") or []:
            account_currency = str(account.get("base_currency") or plan_currency).upper()
            converted_cash, cash_stale, cash_mode = self.portfolio_service.convert_amount(
                amount=float(account.get("total_cash") or 0.0),
                from_currency=account_currency,
                to_currency=plan_currency,
                as_of_date=as_of_date,
            )
            cash_value += converted_cash
            if cash_stale:
                cash_reliable = False
                limitations.append(f"cash_fx_stale:{account_currency}:{cash_mode}")

            for position in account.get("positions") or []:
                valuation_currency = str(position.get("valuation_currency") or account_currency).upper()
                converted_value, fx_stale, fx_mode = self.portfolio_service.convert_amount(
                    amount=float(position.get("market_value_base") or 0.0),
                    from_currency=valuation_currency,
                    to_currency=plan_currency,
                    as_of_date=as_of_date,
                )
                if fx_stale:
                    limitations.append(
                        f"position_fx_stale:{position.get('symbol')}:{valuation_currency}:{fx_mode}"
                    )
                positions.append({
                    "account_id": account.get("account_id"),
                    "symbol": position.get("symbol"),
                    "market": position.get("market"),
                    "market_value_plan": converted_value,
                    "price_available": bool(position.get("price_available", True)),
                    "price_stale": bool(position.get("price_stale", False)),
                    "fx_stale": bool(fx_stale),
                })

        return {
            "as_of": snapshot.get("as_of") or as_of_date.isoformat(),
            "account_count": int(snapshot.get("account_count") or 0),
            "cash_value": cash_value,
            "cash_reliable": cash_reliable,
            "positions": positions,
            "limitations": sorted(set(limitations)),
        }

    @classmethod
    def _validate_plan(
        cls,
        *,
        name: str,
        base_currency: str,
        target_total_value: float,
        targets: Sequence[Dict[str, Any]],
        owner_id: Optional[str],
    ) -> Dict[str, Any]:
        name_norm = str(name or "").strip()
        if not name_norm or len(name_norm) > 96:
            raise ValueError("name must contain 1 to 96 characters")
        currency = str(base_currency or "").strip().upper()
        if len(currency) < 3 or len(currency) > 8:
            raise ValueError("base_currency must contain 3 to 8 characters")
        total_value = cls._positive_finite(target_total_value, "target_total_value")
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
