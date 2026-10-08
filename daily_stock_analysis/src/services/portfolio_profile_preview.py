"""Explicit text-upload preview only. No file access, model, database or cash inference."""
from datetime import datetime, date, timezone
from decimal import Decimal
import hashlib
import re
from zoneinfo import ZoneInfo

from src.services.market_event_holdings import MAX_PROFILE_BYTES, MAX_PROFILE_AGE_DAYS, _section, _rows, _held


def preview_profile(document: str, now=None):
    if len(document.encode('utf-8')) > MAX_PROFILE_BYTES:
        raise ValueError('Profile exceeds 128 KiB')
    document = document.lstrip('\ufeff')
    dates = re.findall(r'^更新日期[：:]\s*(\d{4}-\d{2}-\d{2})(?:\s|$)', document, re.M)
    if len(dates) != 1:
        raise ValueError('One profile update date is required')
    updated = date.fromisoformat(dates[0])
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('Asia/Shanghai')).date()
    if updated > today:
        raise ValueError('Profile date is in the future')
    lines = _section(document, '## 当前主要持仓')
    header = next((line for line in lines if re.match(r'^\|\s*标的\s*\|', line)), '')
    if '美元' not in header:
        raise ValueError('US preview requires an explicitly USD-denominated cost column')
    positions, seen = [], set()
    for symbol, quantity_text, cost_text in _rows(lines, include_cost=True):
        if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,15}', symbol) or symbol in seen:
            raise ValueError('Invalid or duplicate symbol')
        seen.add(symbol)
        if not _held(quantity_text):
            continue
        # Only exact quantities are candidates. Approximate quantities remain unknown.
        match = re.fullmatch(r'(\d+(?:,\d{3})*(?:\.\d+)?)\s*股', quantity_text)
        quantity = float(Decimal(match[1].replace(',', ''))) if match else None
        if quantity is not None and not 0 < quantity <= 1e12:
            raise ValueError('Quantity out of range')
        positions.append({'symbol': symbol, 'quantity': quantity,
                          'quantity_text': quantity_text[:200], 'cost_text': cost_text[:300],
                          'cost_status': 'requires_confirmation'})
    if not positions:
        raise ValueError('No current US holdings found')
    return {'profile_date': updated.isoformat(), 'market': 'us', 'currency': 'USD',
            'status': 'stale' if (today - updated).days > MAX_PROFILE_AGE_DAYS else 'reference',
            'source_hash': hashlib.sha256(document.encode('utf-8')).hexdigest(),
            'positions': positions, 'cash_balance': None, 'opening_date': None,
            'can_commit': False}
