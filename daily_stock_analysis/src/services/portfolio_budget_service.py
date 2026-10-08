"""Manual execution reconciliation and finite-period investment budgets.

All writes use the existing portfolio transaction lock. No operation sends an
order, synthesizes a fill, or treats sale proceeds as a new investment budget.
"""
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.core.portfolio_execution import MARKET_CURRENCIES, MARKET_TIMEZONES, execution_metadata, number, utc_timestamp
from src.repositories.portfolio_repo import PortfolioRepository
from src.services.portfolio_service import PortfolioConflictError, PortfolioService
from src.storage import (PortfolioAuditEvent, PortfolioBudgetPeriod, PortfolioBudgetTradeAdjustment,
                         PortfolioPurchaseIntent, PortfolioTrade)

OPEN_ORDER_STATES = {'submitted', 'pending_cancel'}
TRANSITIONS = {'planned': {'submitted', 'cancelled', 'expired'},
               'submitted': {'pending_cancel', 'cancelled', 'expired'},
               'pending_cancel': {'submitted', 'cancelled', 'expired'},
               'cancelled': set(), 'expired': set()}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _audit(session, account_id, entity, entity_id, action, payload):
    session.add(PortfolioAuditEvent(account_id=account_id, entity=entity, entity_id=entity_id,
                action=action, payload_json=json.dumps(payload, ensure_ascii=False, default=str)))


def _payload(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


class PortfolioBudgetService:
    def __init__(self, repo=None):
        self.repo = repo or PortfolioRepository()
        self.portfolio = PortfolioService(self.repo)

    @staticmethod
    def _required(session, model, identifier):
        row = session.get(model, identifier)
        if row is None:
            raise ValueError(f'{model.__tablename__} record not found')
        return row

    def create_budget(self, account_id, data):
        start, end = date.fromisoformat(data['start_date']), date.fromisoformat(data['end_date'])
        if end < start or (end - start).days > 366:
            raise ValueError('Choose an explicit period of at most 367 days')
        symbols = sorted({self.portfolio._normalize_symbol_for_storage(s) for s in data['symbols']})
        if not symbols or any(not s or len(s) > 16 for s in symbols):
            raise ValueError('At least one valid symbol is required')
        amount = number(data['amount'], 'amount', positive=True)
        with self.repo.portfolio_write_session() as session:
            account = self.portfolio._require_active_account_in_session(session=session, account_id=account_id)
            expected_zone = MARKET_TIMEZONES[account.market]
            if data['timezone'] != expected_zone:
                raise ValueError(f'Budget dates use the exchange timezone: {expected_zone}')
            fields = dict(account_id=account_id, name=data['name'].strip(),
                          currency=self.portfolio._normalize_currency(data['currency']), timezone=expected_zone,
                          start_date=start, end_date=end, amount=amount, symbols_json=json.dumps(symbols),
                          ledger_complete=bool(data.get('ledger_complete', False)), request_key=data['request_key'])
            existing = session.scalar(select(PortfolioBudgetPeriod).where(
                PortfolioBudgetPeriod.request_key == data['request_key']))
            if existing:
                if any(getattr(existing, k) != v for k, v in fields.items()):
                    raise PortfolioConflictError('Request key reused with different budget content')
                return {'id': existing.id}
            others = session.scalars(select(PortfolioBudgetPeriod).where(
                PortfolioBudgetPeriod.account_id == account_id,
                PortfolioBudgetPeriod.start_date <= end, PortfolioBudgetPeriod.end_date >= start)).all()
            if any(set(symbols) & set(json.loads(b.symbols_json)) for b in others):
                raise PortfolioConflictError('Overlapping periods cannot budget the same account/symbol twice')
            row = PortfolioBudgetPeriod(**fields)
            session.add(row)
            session.flush()
            _audit(session, account_id, 'budget', row.id, 'create', fields)
            return {'id': row.id}


    def confirm_ledger(self, budget_id, confirmed):
        with self.repo.portfolio_write_session() as session:
            row = self._required(session, PortfolioBudgetPeriod, budget_id)
            row.ledger_complete = confirmed
            _audit(session, row.account_id, 'budget', row.id, 'ledger_confirmation', {'confirmed': confirmed})
        return {'id': budget_id}

    def reconcile_trade(self, trade_id, data):
        """Revise fee/time evidence only; position facts are not silently rewritten."""
        with self.repo.portfolio_write_session() as session:
            row = self._required(session, PortfolioTrade, trade_id)
            if row.revision != data['expected_revision']:
                raise PortfolioConflictError('Trade changed; reload before confirming')
            before = self.portfolio._trade_row_to_dict(row)
            stamp = execution_metadata(executed_at=data.get('executed_at'), trade_date=row.trade_date,
                                       market=row.market, fee_status=data['fee_status'])
            row.fee, row.tax = float(number(data['fee'], 'fee')), float(number(data['tax'], 'tax'))
            row.fee_status, row.executed_at = data['fee_status'], stamp
            row.revision += 1
            session.flush()
            self.portfolio._calculate_available_quantity(account_id=row.account_id,
                key=(self.portfolio._normalize_symbol_for_position(row.symbol), row.market, row.currency),
                as_of_date=date.max, session=session)
            self.repo._invalidate_account_cache_in_session(session=session, account_id=row.account_id,
                                                           from_date=row.trade_date)
            after = self.portfolio._trade_row_to_dict(row)
            _audit(session, row.account_id, 'trade', row.id, 'reconcile',
                   {'before': before, 'after': after, 'reason': data['reason']})
            return after

    def audit(self, account_id):
        self.portfolio._require_active_account(account_id)
        with self.repo.db.get_session() as session:
            rows = session.scalars(select(PortfolioAuditEvent).where(
                PortfolioAuditEvent.account_id == account_id).order_by(PortfolioAuditEvent.id.desc()).limit(200)).all()
            return [{'id': r.id, 'entity': r.entity, 'entity_id': r.entity_id, 'action': r.action,
                     'created_at': r.created_at.isoformat() + 'Z', 'payload': json.loads(r.payload_json)} for r in rows]

    @staticmethod
    def _matches(budget, trade):
        return (trade.account_id == budget.account_id and trade.side == 'buy'
                and budget.start_date <= trade.trade_date <= budget.end_date
                and trade.symbol in json.loads(budget.symbols_json))

    def adjust_trade(self, budget_id, trade_id, data):
        with self.repo.portfolio_write_session() as session:
            budget = self._required(session, PortfolioBudgetPeriod, budget_id)
            trade = self._required(session, PortfolioTrade, trade_id)
            if not self._matches(budget, trade):
                raise ValueError('Only matching buy executions in this period can be adjusted')
            if data['excluded'] and trade.intent_id is not None:
                raise ValueError('A fill linked to a budget intent cannot be excluded')
            rate = number(data['fx_rate'], 'fx_rate', positive=True) if data.get('fx_rate') is not None else None
            if trade.currency == budget.currency and rate not in (None, Decimal(1)):
                raise ValueError('Same-currency conversion must be 1')
            row = session.scalar(select(PortfolioBudgetTradeAdjustment).where(
                PortfolioBudgetTradeAdjustment.budget_id == budget_id,
                PortfolioBudgetTradeAdjustment.trade_id == trade_id))
            before = _payload(row) if row else None
            if row is None:
                row = PortfolioBudgetTradeAdjustment(budget_id=budget_id, trade_id=trade_id)
                session.add(row)
            row.fx_rate, row.excluded, row.reason = rate, data['excluded'], data['reason']
            session.flush()
            _audit(session, budget.account_id, 'budget_trade', trade_id, 'adjust',
                   {'before': before, 'after': _payload(row)})
        return {'id': trade_id}

    def _status(self, session, budget):
        trades = session.scalars(select(PortfolioTrade).where(
            PortfolioTrade.account_id == budget.account_id, PortfolioTrade.side == 'buy',
            PortfolioTrade.trade_date >= budget.start_date, PortfolioTrade.trade_date <= budget.end_date)).all()
        adjustments = {r.trade_id: r for r in session.scalars(select(PortfolioBudgetTradeAdjustment).where(
            PortfolioBudgetTradeAdjustment.budget_id == budget.id)).all()}
        spent = Decimal(0)
        unresolved, details = [], []
        for trade in trades:
            if not self._matches(budget, trade):
                continue
            adjustment = adjustments.get(trade.id)
            excluded = bool(adjustment and adjustment.excluded)
            rate = Decimal(1) if trade.currency == budget.currency else (adjustment.fx_rate if adjustment else None)
            verified = trade.fee_status == 'confirmed' and rate is not None
            debit = ((Decimal(str(trade.quantity)) * Decimal(str(trade.price)) + Decimal(str(trade.fee))
                      + Decimal(str(trade.tax))) * rate) if verified and not excluded else None
            if not excluded:
                if debit is None:
                    unresolved.append(trade.id)
                else:
                    spent += debit
            details.append({'trade_id': trade.id, 'symbol': trade.symbol, 'excluded': excluded,
                            'fee_status': trade.fee_status, 'fx_rate': float(rate) if rate is not None else None,
                            'amount': float(debit) if debit is not None else None})
        intents = session.scalars(select(PortfolioPurchaseIntent).where(
            PortfolioPurchaseIntent.budget_id == budget.id)).all()
        reserved, native_reserved = Decimal(0), Decimal(0)
        intent_details = []
        for row in intents:
            fills = session.scalars(select(PortfolioTrade).where(PortfolioTrade.intent_id == row.id)).all()
            filled = sum((Decimal(str(t.quantity)) for t in fills), Decimal(0))
            leaves = max(Decimal(0), row.quantity - filled)
            # A broker order does not disappear merely because our plan TTL elapsed.
            native = (leaves * row.limit_price + row.fee_reserve) if leaves and row.status in OPEN_ORDER_STATES else Decimal(0)
            reserved += native * row.fx_rate
            native_reserved += native
            state = ('filled' if not leaves else 'expired_pending_confirmation'
                     if row.status in OPEN_ORDER_STATES and row.expires_at <= _now() else
                     'partially_filled' if fills and row.status == 'submitted' else row.status)
            intent_details.append({'id': row.id, 'symbol': row.symbol, 'status': state,
                'reported_status': row.status, 'revision': row.revision, 'quantity': float(row.quantity),
                'filled_quantity': float(filled), 'remaining_quantity': float(leaves),
                'reserved_amount': float(native * row.fx_rate), 'expires_at': row.expires_at.isoformat() + 'Z'})
        known = budget.ledger_complete and not unresolved
        today = datetime.now(ZoneInfo(budget.timezone)).date()
        remaining = max(Decimal(0), budget.amount - spent - reserved) if known else None
        return {'id': budget.id, 'account_id': budget.account_id, 'name': budget.name, 'currency': budget.currency,
                'timezone': budget.timezone, 'start_date': budget.start_date.isoformat(),
                'end_date': budget.end_date.isoformat(), 'symbols': json.loads(budget.symbols_json),
                'amount': float(budget.amount), 'ledger_complete': budget.ledger_complete,
                'active_period': budget.start_date <= today <= budget.end_date,
                'confirmed_spent': float(spent), 'reserved_amount': float(reserved),
                'native_reserved': float(native_reserved), 'remaining_amount': float(remaining) if remaining is not None else None,
                'over_budget_amount': float(max(Decimal(0), spent + reserved - budget.amount)),
                'unresolved_trade_ids': unresolved, 'trades': details, 'intents': intent_details,
                'limitations': ([] if known else ['budget_ledger_or_costs_unverified'])}

    def list_status(self, account_id, *, require_account=True):
        if require_account:
            self.portfolio._require_active_account(account_id)
        with self.repo.db.get_session() as session:
            budgets = session.scalars(select(PortfolioBudgetPeriod).where(
                PortfolioBudgetPeriod.account_id == account_id).order_by(PortfolioBudgetPeriod.start_date.desc())).all()
            return [self._status(session, row) for row in budgets]

    def create_intent(self, budget_id, data):
        expires = utc_timestamp(data['expires_at'])
        with self.repo.portfolio_write_session() as session:
            budget = self._required(session, PortfolioBudgetPeriod, budget_id)
            symbol = self.portfolio._normalize_symbol_for_storage(data['symbol'])
            if symbol not in json.loads(budget.symbols_json):
                raise ValueError('Intent symbol must belong to the budget')
            account = self.portfolio._require_active_account_in_session(session=session, account_id=budget.account_id)
            if account.base_currency != MARKET_CURRENCIES[account.market]:
                raise ValueError('Order planning requires an account denominated in the market trading currency')
            fields = {key: number(data[key], key, positive=key != 'fee_reserve')
                      for key in ('quantity', 'limit_price', 'fee_reserve', 'fx_rate')}
            if account.base_currency == budget.currency and fields['fx_rate'] != 1:
                raise ValueError('Same-currency conversion must be 1')
            values = dict(budget_id=budget_id, symbol=symbol, expires_at=expires,
                          request_key=data['request_key'], **fields)
            existing = session.scalar(select(PortfolioPurchaseIntent).where(
                PortfolioPurchaseIntent.request_key == data['request_key']))
            if existing:
                if any(getattr(existing, k) != v for k, v in values.items()):
                    raise PortfolioConflictError('Request key reused with different intent content')
                return {'id': existing.id}
            local_expiry = expires.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(budget.timezone)).date()
            if expires <= _now() or not budget.start_date <= local_expiry <= budget.end_date:
                raise ValueError('Intent must expire in the future within this budget period')
            row = PortfolioPurchaseIntent(**values, status='planned')
            session.add(row)
            session.flush()
            _audit(session, budget.account_id, 'intent', row.id, 'create', values)
            return {'id': row.id}

    def set_intent_state(self, intent_id, data):
        with self.repo.portfolio_write_session() as session:
            row = self._required(session, PortfolioPurchaseIntent, intent_id)
            budget = self._required(session, PortfolioBudgetPeriod, row.budget_id)
            if row.revision != data['expected_revision']:
                raise PortfolioConflictError('Intent changed; reload before confirming')
            state = data['status']
            if state not in TRANSITIONS[row.status]:
                raise ValueError('Invalid intent state transition')
            before = _payload(row)
            # This is a factual user report, not order authorization. Even an
            # over-budget order must be recorded, then shown as a budget breach.
            row.status, row.revision = state, row.revision + 1
            _audit(session, budget.account_id, 'intent', row.id, 'status',
                   {'before': before, 'after': _payload(row), 'reason': data['reason']})
        return {'id': intent_id}

    def validate_fill(self, session, trade):
        intent = self._required(session, PortfolioPurchaseIntent, trade.intent_id)
        budget = self._required(session, PortfolioBudgetPeriod, intent.budget_id)
        account = self.portfolio._require_active_account_in_session(session=session, account_id=budget.account_id)
        if not self._matches(budget, trade) or trade.symbol != intent.symbol or trade.currency != account.base_currency or trade.market != account.market:
            raise ValueError('Execution does not match the intended account, symbol, currency or period')
        adjustment = session.scalar(select(PortfolioBudgetTradeAdjustment).where(
            PortfolioBudgetTradeAdjustment.budget_id == budget.id,
            PortfolioBudgetTradeAdjustment.trade_id == trade.id))
        if adjustment and adjustment.excluded:
            raise ValueError('Remove the explicit budget exclusion before linking this execution')
        fills = session.scalars(select(PortfolioTrade).where(PortfolioTrade.intent_id == intent.id)).all()
        if sum(Decimal(str(t.quantity)) for t in fills) > intent.quantity:
            raise PortfolioConflictError('Confirmed fills exceed the intent quantity')
        intent.revision += 1
        if intent.status == 'planned':
            intent.status = 'submitted'
        _audit(session, trade.account_id, 'intent', intent.id, 'fill_link', {'trade_id': trade.id})

    def link_existing_fill(self, intent_id, trade_id):
        with self.repo.portfolio_write_session() as session:
            trade = self._required(session, PortfolioTrade, trade_id)
            if trade.intent_id == intent_id:
                return {'id': trade_id}
            if trade.intent_id is not None:
                raise PortfolioConflictError('Trade is already linked to another intent')
            trade.intent_id = intent_id
            trade.revision += 1
            session.flush()
            self.validate_fill(session, trade)
            self.repo._invalidate_account_cache_in_session(session=session, account_id=trade.account_id,
                                                           from_date=trade.trade_date)
        return {'id': trade_id}
