"""Read-only, source-traceable trading review over the existing portfolio ledger."""
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from data_provider.realtime_types import parse_quote_timestamp
from src.core.portfolio_execution import MARKET_CURRENCIES, MARKET_TIMEZONES
from src.core.portfolio_performance import aggregate_contributions, evaluate_trading_contribution
from src.repositories.portfolio_repo import PortfolioRepository
from src.services.portfolio_service import PortfolioService

METHOD_VERSION = 'period-hold-v1'


class PortfolioPerformanceService:
    def __init__(self, repo: Optional[PortfolioRepository] = None):
        self.repo = repo or PortfolioRepository()
        self.portfolio = PortfolioService(self.repo)

    def _identity(self, row):
        return (self.portfolio._normalize_symbol_for_position(row.symbol), row.market, row.currency)

    def evaluate(self, account_id, *, start_date: date, end_date: date, symbols=None,
                 ledger_confirmed=False, include_realtime=False):
        if start_date <= date.min or end_date < start_date or (end_date - start_date).days > 366:
            raise ValueError('Choose an explicit review period of at most 367 days')
        requested = sorted({self.portfolio._normalize_symbol_for_position(s) for s in (symbols or [])})
        if len(requested) > 50 or any(not s or len(s) > 16 for s in requested):
            raise ValueError('Use at most 50 valid symbols')
        now = datetime.now(timezone.utc)
        observations = []
        # Explicit SQLite read transaction keeps baseline, rows and fingerprint
        # coherent. It ends before any optional quote request; no ledger writes.
        with self.repo.db.get_session() as session:
            if session.get_bind().dialect.name == 'sqlite':
                session.connection().exec_driver_sql('BEGIN')
            account = self.portfolio._require_active_account_in_session(session=session, account_id=account_id)
            account_zone = MARKET_TIMEZONES[account.market]
            if end_date > now.astimezone(ZoneInfo(account_zone)).date():
                raise ValueError('The review cannot end after the current exchange date')
            opening = self.repo.get_opening_balance(account_id, session)
            if opening and start_date <= date.fromisoformat(opening['as_of']):
                raise ValueError('Review must start after the confirmed end-of-day opening balance')
            trades = self.repo.list_trades_in_session(session=session, account_id=account_id, as_of=end_date)
            actions = self.repo.list_corporate_actions_in_session(session=session, account_id=account_id, as_of=end_date)
            keys = {self._identity(t) for t in trades if start_date <= t.trade_date}
            keys |= {self._identity(a) for a in actions if start_date <= a.effective_date}
            if requested:
                historical_keys = {self._identity(t) for t in trades}
                if opening:
                    historical_keys |= {(self.portfolio._normalize_symbol_for_position(p['symbol']), opening['market'], opening['currency'])
                                        for p in opening['positions']}
                keys |= {key for key in historical_keys if key[0] in requested}
                keys = {key for key in keys if key[0] in requested}
                if set(requested) - {key[0] for key in keys}:
                    raise ValueError('A requested symbol has no recorded holding or execution; no zero holding is inferred')
            if len(keys) > 50:
                raise ValueError('Limit this review to at most 50 instrument/currency groups')
            for key in sorted(keys):
                symbol, market, currency = key
                if end_date > now.astimezone(ZoneInfo(MARKET_TIMEZONES[market])).date():
                    raise ValueError('The review cannot end after any included instrument exchange date')
                before = self.portfolio._calculate_available_quantity(account_id=account_id, key=key,
                    as_of_date=start_date - timedelta(days=1), session=session)
                after = self.portfolio._calculate_available_quantity(account_id=account_id, key=key,
                    as_of_date=end_date, session=session)
                # Ledger quantities support eight decimals; discard binary-float
                # replay dust before deciding whether a position was restored.
                before, after = round(before, 8), round(after, 8)
                selected = [t for t in trades if self._identity(t) == key and t.trade_date >= start_date]
                selected_actions = [a for a in actions if self._identity(a) == key and a.effective_date >= start_date]
                for trade in selected:
                    for field in ('quantity', 'price', 'fee', 'tax'):
                        value = getattr(trade, field)
                        if value is None or not math.isfinite(value) or value < 0 or (field in {'quantity', 'price'} and value == 0):
                            raise ValueError(f'Trade #{trade.id} has an invalid {field}; reconcile the ledger before review')
                observations.append({
                    'symbol': symbol, 'market': market, 'currency': currency,
                    'baseline_quantity': before, 'ending_quantity': after,
                    'trades': [self.portfolio._trade_row_to_dict(t) for t in selected],
                    'corporate_actions': [{c.name: getattr(a, c.name) for c in a.__table__.columns} for a in selected_actions],
                })
            fingerprint = self.repo.ledger_fingerprint(account_id, session)

        items = []
        for observation in observations:
            mark = None
            if observation['baseline_quantity'] != observation['ending_quantity'] and not observation['corporate_actions']:
                mark = self._endpoint(observation, end_date, include_realtime)
            result = evaluate_trading_contribution(
                baseline_quantity=observation['baseline_quantity'], ending_quantity=observation['ending_quantity'],
                trades=observation['trades'], corporate_actions=observation['corporate_actions'],
                ledger_confirmed=ledger_confirmed, valuation=mark)
            items.append({**observation, **result, 'valuation': mark})
        payload = {
            'account_id': account_id, 'start_date': start_date.isoformat(), 'end_date': end_date.isoformat(),
            'timezone': account_zone, 'requested_symbols': requested, 'ledger_confirmed': bool(ledger_confirmed),
            'methodology_version': METHOD_VERSION, 'ledger_fingerprint': fingerprint,
            'generated_at': datetime.now(timezone.utc).isoformat(), 'items': items,
            'totals_by_currency': aggregate_contributions(items),
            'disclosures': ['all_period_trades_included', 'not_tax_lot_or_account_return',
                            'cash_interest_and_income_tax_excluded', 'actual_fills_already_include_slippage',
                            'no_order_or_cash_availability_inference'],
        }
        # Include observation data, reference prices and algorithm version. This
        # is an evidence fingerprint, not a claim of broker certification.
        payload['evidence_hash'] = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        return payload

    def _endpoint(self, observation, end_date, include_realtime):
        now = datetime.now(timezone.utc)
        market = observation['market']
        result = {'price': None, 'source': None, 'provider': None, 'timestamp': None,
                  'fetched_at': None, 'usable': False, 'reason': 'realtime_not_requested'}
        if not include_realtime:
            return result
        if market not in {'cn', 'hk', 'us'}:
            return {**result, 'reason': 'market_valuation_unsupported'}
        if observation['currency'] != MARKET_CURRENCIES[market]:
            return {**result, 'reason': 'valuation_currency_mismatch'}
        zone = ZoneInfo(MARKET_TIMEZONES[market])
        if end_date != now.astimezone(zone).date():
            # Historical daily closes do not carry an unadjusted-price contract.
            return {**result, 'reason': 'historical_unadjusted_endpoint_unavailable'}
        quote = self.portfolio._fetch_realtime_position_price(observation['symbol'])
        if quote is None:
            return {**result, 'reason': 'quote_unavailable'}
        stamp = parse_quote_timestamp(quote.timestamp)
        result.update(price=quote.price, source=quote.source, provider=quote.provider,
                      timestamp=quote.timestamp, fetched_at=quote.fetched_at)
        age = (datetime.now(timezone.utc) - stamp).total_seconds() if stamp is not None else None
        if (not quote.is_available or quote.is_stale or not quote.provider or age is None
                or not math.isfinite(quote.price) or quote.price <= 0
                or not 0 <= age <= 300 or stamp.astimezone(zone).date() != end_date):
            return {**result, 'reason': 'quote_stale_or_unverifiable'}
        current_trades = [t for t in observation['trades'] if t['trade_date'] == end_date.isoformat()]
        if any(not t['executed_at'] for t in current_trades):
            return {**result, 'reason': 'intraday_execution_time_unknown'}
        if any(parse_quote_timestamp(t['executed_at']) > stamp for t in current_trades):
            return {**result, 'reason': 'quote_precedes_execution'}
        return {**result, 'usable': True, 'reason': 'fresh_timestamped_quote'}
