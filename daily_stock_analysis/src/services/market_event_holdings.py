"""Opt-in, read-only symbol projection from the documented investment profile.

This is news context, not a portfolio import. Never return quantities, costs,
cash, prose instructions, paths or historical/target holdings to the model.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from src.core.market_events import digest

MAX_PROFILE_BYTES = 128 * 1024
MAX_PROFILE_AGE_DAYS = 7


def load_recorded_holding_scope(db, now, profile_path='', account_id=None):
    """Shared symbol-only read scope; no valuation, writes, or broker/model calls."""
    from sqlalchemy import select
    from src.core.portfolio_execution import MARKET_TIMEZONES
    from src.repositories.portfolio_repo import PortfolioRepository
    from src.services.portfolio_service import PortfolioService
    from src.storage import PortfolioAccount
    repo = PortfolioRepository(db)
    portfolio = PortfolioService(repo)
    positions = {}
    with db.get_session() as session:
        if session.get_bind().dialect.name == 'sqlite':
            session.connection().exec_driver_sql('BEGIN')
        accounts = list(session.scalars(select(PortfolioAccount)))
        if account_id is not None and not any(a.id == account_id and a.is_active for a in accounts):
            raise ValueError('Active portfolio account not found')
        for account in (a for a in accounts if a.is_active and (account_id is None or a.id == account_id)):
            today = now.astimezone(ZoneInfo(MARKET_TIMEZONES[account.market])).date()
            opening = repo.get_opening_balance(account.id, session)
            trades = repo.list_trades_in_session(session=session, account_id=account.id, as_of=today)
            keys = {(portfolio._normalize_symbol_for_position(t.symbol), t.market, t.currency) for t in trades}
            if opening:
                keys |= {(p['symbol'], opening['market'], opening['currency']) for p in opening['positions']}
            for key in keys:
                qty = portfolio._calculate_available_quantity(account_id=account.id, key=key, as_of_date=today, session=session)
                if qty > 1e-8:
                    symbol, market, _ = key
                    positions[(symbol, market)] = {'symbol': symbol, 'market': market, 'basis': 'recorded_ledger'}
    if not accounts and profile_path and account_id is None:
        return load_profile_holdings(profile_path, now)
    return list(positions.values()), {'status': 'recorded_ledger' if positions else 'no_recorded_holdings'}


def _section(document, heading, required=True):
    lines = document.splitlines()
    matches = [i for i, line in enumerate(lines) if line.strip() == heading]
    if len(matches) != 1:
        if not matches and not required:
            return []
        raise ValueError('Missing or ambiguous current-holdings section')
    result = []
    for line in lines[matches[0] + 1:]:
        if re.match(r'^#{1,6}\s', line):
            break
        result.append(line.strip())
    return result


def _rows(lines, *, include_cost=False):
    headers = [i for i, line in enumerate(lines) if re.match(r'^\|\s*标的\s*\|', line)]
    if len(headers) != 1:
        raise ValueError('Missing or ambiguous holdings table')
    start = headers[0]
    if '份额' not in lines[start].split('|')[2] or start + 1 >= len(lines):
        raise ValueError('Unexpected quantity column')
    if include_cost and '成本' not in lines[start].split('|')[3]:
        raise ValueError('Unexpected cost column')
    if not re.fullmatch(r'[| :\-]+', lines[start + 1]):
        raise ValueError('Missing Markdown table separator')
    result = []
    for line in lines[start + 2:]:
        if not line.startswith('|'):
            break
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        if len(cells) < 3:
            raise ValueError('Incomplete holdings row')
        if cells[0] == '合计':
            continue
        result.append(cells[:3] if include_cost else cells[:2])
    if len(result) > 50:
        raise ValueError('Too many holdings')
    return result


def _held(quantity):
    match = re.match(r'^(?:约\s*)?(\d[\d,]*(?:\.\d+)?)\s*(?:股|份)(?:\s|（|$)', quantity)
    if match:
        return Decimal(match[1].replace(',', '')) > 0
    # A presence-only row in the CURRENT table may have an unknown quantity.
    if quantity in {'未显示，待确认', '未显示', '待确认', '未知'}:
        return True
    raise ValueError('Unrecognized quantity; do not infer a holding')


def load_profile_holdings(path, now):
    """Fail closed on stale/invalid files; no fallback to historical sections."""
    metadata = {'status': 'profile_invalid', 'profile_date': None}
    try:
        with Path(path).open('rb') as stream:
            content = stream.read(MAX_PROFILE_BYTES + 1)
        if len(content) > MAX_PROFILE_BYTES:
            return [], metadata
        document = content.decode('utf-8-sig')
        dates = re.findall(r'^更新日期[：:]\s*(\d{4}-\d{2}-\d{2})(?:\s|$)', document, re.M)
        if len(dates) != 1:
            return [], metadata
        updated = date.fromisoformat(dates[0])
        metadata['profile_date'] = updated.isoformat()
        age = (now.astimezone(ZoneInfo('Asia/Shanghai')).date() - updated).days
        if age < 0:
            return [], metadata
        if age > MAX_PROFILE_AGE_DAYS:
            return [], dict(metadata, status='profile_stale')
        positions = {}
        for symbol, quantity in _rows(_section(document, '## 当前主要持仓')):
            if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,15}', symbol):
                raise ValueError('Invalid US symbol')
            if ('us', symbol) in positions:
                raise ValueError('Duplicate symbol')
            positions[('us', symbol)] = _held(quantity)
        domestic = _section(document, '### 当前已知人民币资产', required=False)
        for label, quantity in _rows(domestic) if domestic else []:
            symbols = re.findall(r'(?<!\d)\d{6}(?!\d)', label)
            if len(symbols) != 1 or ('cn', symbols[0]) in positions:
                raise ValueError('Invalid or duplicate domestic symbol')
            positions[('cn', symbols[0])] = _held(quantity)
        holdings = [{'symbol': symbol, 'market': market, 'basis': 'investment_profile'}
                    for (market, symbol), held in sorted(positions.items()) if held]
        return holdings, dict(metadata, status='profile_reference',
                              revision=digest({'date': metadata['profile_date'], 'holdings': holdings}))
    except (OSError, UnicodeError):
        return [], dict(metadata, status='profile_unavailable')
    except (ValueError, IndexError):
        return [], metadata
