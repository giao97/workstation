# -*- coding: utf-8 -*-
"""Persistence helpers for versioned portfolio target-allocation plans."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, select

from src.storage import DatabaseManager, PortfolioAllocationPlan, PortfolioAllocationTarget


class PortfolioAllocationRepository:
    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def create_plan(
        self,
        *,
        name: str,
        owner_id: Optional[str],
        base_currency: str,
        target_total_value: float,
        targets: List[Dict[str, Any]],
        account_id: Optional[int] = None,
        ledger_complete: bool = False,
        cash_reserve_amount: float = 0.0,
        include_in_reports: bool = False,
    ) -> Tuple[PortfolioAllocationPlan, List[PortfolioAllocationTarget]]:
        with self.db.get_session() as session:
            plan = PortfolioAllocationPlan(
                name=name,
                owner_id=owner_id,
                base_currency=base_currency,
                target_total_value=target_total_value,
                account_id=account_id,
                ledger_complete=ledger_complete,
                cash_reserve_amount=cash_reserve_amount,
                include_in_reports=include_in_reports,
                version=1,
                is_active=True,
            )
            session.add(plan)
            session.flush()
            target_rows = self._replace_targets_in_session(session, int(plan.id), targets)
            session.commit()
            session.refresh(plan)
            for row in target_rows:
                session.refresh(row)
            session.expunge(plan)
            for row in target_rows:
                session.expunge(row)
            return plan, target_rows

    def update_plan(
        self,
        *,
        plan_id: int,
        name: str,
        owner_id: Optional[str],
        base_currency: str,
        target_total_value: float,
        targets: List[Dict[str, Any]],
        account_id: Optional[int] = None,
        ledger_complete: bool = False,
        cash_reserve_amount: float = 0.0,
        include_in_reports: bool = False,
    ) -> Optional[Tuple[PortfolioAllocationPlan, List[PortfolioAllocationTarget]]]:
        with self.db.get_session() as session:
            plan = session.get(PortfolioAllocationPlan, plan_id)
            if plan is None or not bool(plan.is_active):
                return None
            plan.name = name
            plan.owner_id = owner_id
            plan.base_currency = base_currency
            plan.target_total_value = target_total_value
            plan.account_id = account_id
            plan.ledger_complete = ledger_complete
            plan.cash_reserve_amount = cash_reserve_amount
            plan.include_in_reports = include_in_reports
            plan.version = int(plan.version or 1) + 1
            plan.updated_at = datetime.now()
            target_rows = self._replace_targets_in_session(session, plan_id, targets)
            session.commit()
            session.refresh(plan)
            for row in target_rows:
                session.refresh(row)
            session.expunge(plan)
            for row in target_rows:
                session.expunge(row)
            return plan, target_rows

    def get_plan(
        self,
        plan_id: int,
        *,
        include_inactive: bool = False,
    ) -> Optional[Tuple[PortfolioAllocationPlan, List[PortfolioAllocationTarget]]]:
        with self.db.get_session() as session:
            plan = session.get(PortfolioAllocationPlan, plan_id)
            if plan is None or (not include_inactive and not bool(plan.is_active)):
                return None
            targets = session.execute(
                select(PortfolioAllocationTarget)
                .where(PortfolioAllocationTarget.plan_id == plan_id)
                .order_by(PortfolioAllocationTarget.sort_order.asc(), PortfolioAllocationTarget.id.asc())
            ).scalars().all()
            session.expunge(plan)
            for row in targets:
                session.expunge(row)
            return plan, list(targets)

    def list_plans(self, *, include_inactive: bool = False) -> List[PortfolioAllocationPlan]:
        with self.db.get_session() as session:
            query = select(PortfolioAllocationPlan)
            if not include_inactive:
                query = query.where(PortfolioAllocationPlan.is_active.is_(True))
            rows = session.execute(
                query.order_by(PortfolioAllocationPlan.updated_at.desc(), PortfolioAllocationPlan.id.desc())
            ).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def deactivate_plan(self, plan_id: int) -> bool:
        with self.db.get_session() as session:
            plan = session.get(PortfolioAllocationPlan, plan_id)
            if plan is None:
                return False
            plan.is_active = False
            plan.updated_at = datetime.now()
            session.commit()
            return True

    @staticmethod
    def target_to_dict(row: PortfolioAllocationTarget) -> Dict[str, Any]:
        try:
            symbols = json.loads(row.symbols_json or "[]")
        except (TypeError, json.JSONDecodeError):
            symbols = []
        if not isinstance(symbols, list):
            symbols = []
        return {
            "id": int(row.id),
            "key": row.target_key,
            "name": row.name,
            "source": row.source,
            "policy": row.policy,
            "market": row.market,
            "symbols": [str(item) for item in symbols],
            "target_pct": float(row.target_pct),
            "min_pct": float(row.min_pct) if row.min_pct is not None else None,
            "max_pct": float(row.max_pct) if row.max_pct is not None else None,
            "batch_amount": float(row.batch_amount) if row.batch_amount is not None else None,
            "current_amount": float(row.current_amount) if row.current_amount is not None else None,
            "sort_order": int(row.sort_order or 0),
            "note": row.note,
        }

    @staticmethod
    def plan_to_dict(plan: PortfolioAllocationPlan) -> Dict[str, Any]:
        return {
            "id": int(plan.id),
            "owner_id": plan.owner_id,
            "name": plan.name,
            "base_currency": plan.base_currency,
            "target_total_value": float(plan.target_total_value),
            "account_id": plan.account_id,
            "ledger_complete": bool(plan.ledger_complete),
            "cash_reserve_amount": float(plan.cash_reserve_amount or 0),
            "include_in_reports": bool(plan.include_in_reports),
            "version": int(plan.version or 1),
            "is_active": bool(plan.is_active),
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
        }

    @staticmethod
    def _replace_targets_in_session(
        session: Any,
        plan_id: int,
        targets: List[Dict[str, Any]],
    ) -> List[PortfolioAllocationTarget]:
        session.execute(
            delete(PortfolioAllocationTarget).where(PortfolioAllocationTarget.plan_id == plan_id)
        )
        rows: List[PortfolioAllocationTarget] = []
        for target in targets:
            row = PortfolioAllocationTarget(
                plan_id=plan_id,
                target_key=target["key"],
                name=target["name"],
                source=target["source"],
                policy=target["policy"],
                market=target.get("market"),
                symbols_json=json.dumps(target.get("symbols") or [], ensure_ascii=False),
                target_pct=target["target_pct"],
                min_pct=target.get("min_pct"),
                max_pct=target.get("max_pct"),
                batch_amount=target.get("batch_amount"),
                current_amount=target.get("current_amount"),
                sort_order=target.get("sort_order", 0),
                note=target.get("note"),
            )
            session.add(row)
            rows.append(row)
        session.flush()
        for row in rows:
            session.refresh(row)
        return rows
