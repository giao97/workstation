"""Opening inventory, statement reconciliation and confirmed funding boundaries.

All amounts here are in one account's base currency. Reported market values are
reconciliation evidence, never a replacement for timestamped market quotes.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from typing import Any, Dict

from sqlalchemy import select

from src.repositories.portfolio_repo import PortfolioRepository
from src.services.portfolio_service import PortfolioConflictError, PortfolioService
from src.storage import (PortfolioCashLedger, PortfolioCorporateAction, PortfolioFundingSnapshot,
                         PortfolioOpeningBalance, PortfolioTrade)


def _number(value: Any, name: str, *, positive: bool = False):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return value


class PortfolioAccountStateService:
    def __init__(self, repo=None):
        self.repo = repo or PortfolioRepository()
        self.portfolio = PortfolioService(self.repo)

    def _account(self, account_id, session=None):
        account = (self.repo.get_account(account_id) if session is None else
                   self.repo.get_account_in_session(session=session, account_id=account_id))
        if account is None:
            raise ValueError("Active account not found")
        return account

    def preview_opening(self, account_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        account = self._account(account_id)
        on_date = date.fromisoformat(str(payload["as_of"]))
        if on_date >= date.today():
            raise ValueError("Opening balance is an end-of-day snapshot; choose a completed past date")
        positions = []
        seen = set()
        for item in payload.get("positions") or []:
            symbol = self.portfolio._normalize_symbol(item["symbol"])
            if not symbol or symbol in seen:
                raise ValueError("Opening symbols must be nonempty and unique")
            seen.add(symbol)
            quantity = _number(item.get("quantity"), "quantity", positive=True)
            cost = _number(item.get("avg_cost"), "avg_cost")
            if quantity is None or cost is None:
                raise ValueError("Opening quantity and cost are required")
            positions.append({"symbol": symbol, "quantity": quantity, "avg_cost": cost,
                              "reported_market_value": _number(item.get("reported_market_value"), "market value")})
        if not positions:
            raise ValueError("At least one opening position is required")
        normalized = {"as_of": on_date.isoformat(), "currency": account.base_currency,
                      "market": account.market, "positions": sorted(positions, key=lambda x: x["symbol"]),
                      "cash_balance": _number(payload.get("cash_balance"), "cash_balance"),
                      "reported_market_value": _number(payload.get("reported_market_value"), "reported_market_value"),
                      "reported_equity": _number(payload.get("reported_equity"), "reported_equity")}
        digest = hashlib.sha256(json.dumps({"account_id": account_id, **normalized}, sort_keys=True).encode()).hexdigest()
        detail_known = all(x["reported_market_value"] is not None for x in positions)
        detail_total = sum(x["reported_market_value"] for x in positions) if detail_known else None
        mv, equity, cash = (normalized[k] for k in ("reported_market_value", "reported_equity", "cash_balance"))
        limitations = ["historical_realized_pnl_unavailable", "opening_fifo_lots_aggregated"]
        if cash is None:
            limitations.append("opening_cash_balance_required_before_commit")
        if self.repo.get_opening_balance(account_id):
            limitations.append("opening_balance_already_exists")
        with self.repo.db.get_session() as session:
            has_events = self._has_events(account_id, session)
        if has_events:
            limitations.append("existing_ledger_requires_manual_reconciliation")
        return {"account_id": account_id, "opening": normalized, "preview_token": digest,
                "can_commit": cash is not None and not has_events and "opening_balance_already_exists" not in limitations,
                "detail_market_value": detail_total,
                "market_value_difference": round(mv - detail_total, 6) if mv is not None and detail_total is not None else None,
                "equity_less_market_value": round(equity - mv, 6) if equity is not None and mv is not None else None,
                "equity_difference": round(equity - mv - cash, 6) if all(x is not None for x in (equity, mv, cash)) else None,
                "limitations": limitations}

    @staticmethod
    def _has_events(account_id, session):
        return any(session.execute(select(model.id).where(model.account_id == account_id).limit(1)).first()
                   for model in (PortfolioTrade, PortfolioCashLedger, PortfolioCorporateAction))

    def commit_opening(self, account_id, payload, preview_token):
        preview = self.preview_opening(account_id, payload)
        if preview_token != preview["preview_token"]:
            raise PortfolioConflictError("Opening preview changed; preview and confirm again")
        if preview["opening"]["cash_balance"] is None:
            raise ValueError("Confirm book cash explicitly; net equity minus market value is not confirmed cash")
        with self.repo.portfolio_write_session() as session:
            account = self._account(account_id, session)
            if (account.base_currency, account.market) != (preview["opening"]["currency"], preview["opening"]["market"]):
                raise PortfolioConflictError("Account changed; preview again")
            existing = session.get(PortfolioOpeningBalance, account_id)
            if existing:
                if existing.fingerprint == preview_token:
                    return {"account_id": account_id, "created": False}
                raise PortfolioConflictError("Opening balance already exists; it cannot be silently overwritten")
            if self._has_events(account_id, session):
                raise PortfolioConflictError("Account already has events; opening balance would duplicate history")
            session.add(PortfolioOpeningBalance(account_id=account_id,
                        as_of=date.fromisoformat(preview["opening"]["as_of"]),
                        payload_json=json.dumps(preview["opening"], sort_keys=True), fingerprint=preview_token))
            self.repo._invalidate_account_cache_in_session(
                session=session, account_id=account_id, from_date=date.fromisoformat(preview["opening"]["as_of"]))
        return {"account_id": account_id, "created": True}

    def record_funding(self, account_id, payload):
        account = self._account(account_id)
        on_date = date.fromisoformat(str(payload["as_of"]))
        if on_date > date.today():
            raise ValueError("Funding observation cannot be in the future")
        settled = _number(payload.get("settled_cash"), "settled_cash")
        available = _number(payload.get("available_cash"), "available_cash")
        planned = _number(payload.get("planned_deposit"), "planned_deposit")
        planned_date = payload.get("planned_deposit_date")
        if planned_date is not None:
            planned_date = date.fromisoformat(str(planned_date)).isoformat()
            if planned is None:
                raise ValueError("planned_deposit is required when a date is supplied")
        data = {"as_of": on_date.isoformat(), "currency": account.base_currency,
                "settled_cash": settled, "available_cash": available,
                "planned_deposit": planned, "planned_deposit_date": planned_date}
        with self.repo.portfolio_write_session() as session:
            current = self._account(account_id, session)
            if current.base_currency != account.base_currency:
                raise PortfolioConflictError("Account currency changed; retry")
            row = PortfolioFundingSnapshot(account_id=account_id, as_of=on_date,
                      payload_json=json.dumps(data), ledger_fingerprint=self.repo.ledger_fingerprint(account_id, session))
            session.add(row)
            session.flush()
            return {"id": row.id}

    def get_state(self, account_id, as_of=None):
        account = self._account(account_id)
        on_date = as_of or date.today()
        funding = self.repo.get_funding_snapshot(account_id, on_date)
        opening = self.repo.get_opening_balance(account_id)
        if opening and date.fromisoformat(opening["as_of"]) > on_date:
            opening = None
        cash_confirmed = bool(funding and funding["as_of"] == on_date.isoformat()
                              and funding["ledger_unchanged"]
                              and funding["currency"] == account.base_currency
                              and funding["settled_cash"] is not None and funding["available_cash"] is not None)
        return {"account_id": account_id, "currency": account.base_currency, "opening": opening,
                "funding": funding, "cash_confirmed": cash_confirmed,
                "confirmed_cash_cap": min(funding["settled_cash"], funding["available_cash"]) if cash_confirmed else None,
                "disclosures": ["planned deposits never change cash or P&L",
                                "cash confirmation expires on a new date or ledger change",
                                "confirmed cash remains subject to recorded balances, reserves and market conditions"]}
