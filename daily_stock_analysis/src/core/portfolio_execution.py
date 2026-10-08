"""Shared, deterministic execution/budget validation. No broker integration."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

MARKET_TIMEZONES = {'cn': 'Asia/Shanghai', 'hk': 'Asia/Hong_Kong', 'us': 'America/New_York',
                    'jp': 'Asia/Tokyo', 'kr': 'Asia/Seoul', 'tw': 'Asia/Taipei'}
MARKET_CURRENCIES = {'cn': 'CNY', 'hk': 'HKD', 'us': 'USD', 'jp': 'JPY', 'kr': 'KRW', 'tw': 'TWD'}
FEE_STATUSES = {'unknown', 'estimated', 'confirmed'}


def number(value, name, *, positive=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f'{name} must be a finite number') from None
    if isinstance(value, bool) or not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError(f'{name} must be finite and {"positive" if positive else "nonnegative"}')
    if result >= Decimal('1e15') or result.as_tuple().exponent < -8:
        raise ValueError(f'{name} exceeds supported precision (8 decimal places)')
    return result


def utc_timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timestamp requires an explicit timezone offset')
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def execution_metadata(*, executed_at, trade_date, market, fee_status):
    if fee_status not in FEE_STATUSES:
        raise ValueError('fee_status must be unknown, estimated or confirmed')
    stamp = utc_timestamp(executed_at) if executed_at is not None else None
    if stamp is not None:
        if stamp > datetime.now(timezone.utc).replace(tzinfo=None):
            raise ValueError('Execution time cannot be in the future')
        local = stamp.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(MARKET_TIMEZONES[market]))
        if local.date() != trade_date:
            raise ValueError('trade_date must match execution time in the exchange timezone')
    return stamp


def ordered_events(events, priority):
    """Order each position's day consistently in both validation and full replay.

    An unrelated holding with missing timestamps must not change another
    holding's FIFO or oversell result. Cash/corporate action priority is retained.
    """
    def position(row):
        return (row.symbol, row.market, row.currency)

    unknown_groups = {(day, position(row)) for kind, day, _, row in events
                      if kind == 'trade' and getattr(row, 'executed_at', None) is None}

    def key(event):
        kind, day, identifier, row = event
        group = position(row) if kind == 'trade' else ('', '', '')
        stamp = row.executed_at if kind == 'trade' and (day, group) not in unknown_groups else datetime.min
        return day, priority[kind], group, stamp, identifier

    return sorted(events, key=key)
