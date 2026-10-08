"""Read-only daily core-entry annotations for current allocation evaluations."""
import logging
from datetime import datetime, timedelta, timezone

from src.core import trading_calendar as calendar
from src.core.core_entry import CORE_SYMBOLS, assess_core_entry

logger = logging.getLogger(__name__)


class CoreEntryService:
    def __init__(self, repo, *, clock=None):
        self.repo = repo
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def annotate(self, result, snapshot):
        now = self.clock()
        dates = []
        try:
            latest = calendar.get_effective_trading_date('us', current_time=now)
            if calendar.is_latest_completed_close('us', latest, current_time=now):
                cal = calendar.xcals.get_calendar(calendar.MARKET_EXCHANGE['us'])
                dates = [s.date() for s in cal.sessions_in_range(latest - timedelta(days=150), latest)[-60:]]
        except Exception:
            logger.warning('Core entry calendar unavailable', exc_info=True)
        cache = {}
        for target in result['targets']:
            if target.get('source') != 'position' or target.get('market') != 'us':
                continue
            entries = []
            for symbol in target.get('symbols', []):
                if symbol not in CORE_SYMBOLS:
                    continue
                if symbol not in cache:
                    bars = self.repo.core_entry_daily_bars(symbol, dates[0], dates[-1]) if dates else []
                    positions = [p for a in snapshot.get('accounts', []) for p in a.get('positions', [])
                                 if p.get('symbol') == symbol and p.get('market') == 'us'
                                 and p.get('currency') == 'USD' and (p.get('quantity') or 0) > 0]
                    # Incomplete / absent ledger cost is not required for a first purchase.
                    cost = None
                    if positions and all(p.get('avg_cost') is not None for p in positions):
                        cost = sum(p['avg_cost'] * p['quantity'] for p in positions) / sum(p['quantity'] for p in positions)
                    cache[symbol] = assess_core_entry(symbol, bars, dates, cost=cost)
                entry = dict(cache[symbol])
                entry['allocation_action'] = target['action']
                # Price candidate != allocation approval. Cash caps remain owned
                # by the existing allocator, not recomputed for each candidate.
                entry['allocation_ready'] = target['action'] == 'add' and (target.get('funded_amount') or 0) > 0
                entry['evaluated_at'] = now.isoformat()
                entries.append(entry)
            target['core_entries'] = entries
