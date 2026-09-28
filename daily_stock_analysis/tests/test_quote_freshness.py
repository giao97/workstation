"""Provider metadata -> portfolio valuation -> allocation safety, without network calls."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_provider.akshare_fetcher import AkshareFetcher
from data_provider.base import DataFetcherManager
from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote, parse_quote_timestamp
from data_provider.yfinance_fetcher import YfinanceFetcher
from src.config import Config
from src.services.portfolio_allocation_service import PortfolioAllocationService
from src.services.portfolio_service import PortfolioService
from src.storage import DatabaseManager


@pytest.fixture
def portfolio(tmp_path, monkeypatch):
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "unused.env"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "quotes.db"))
    monkeypatch.setenv("REALTIME_SOURCE_PRIORITY", "tencent")
    monkeypatch.setenv("ENABLE_REALTIME_QUOTE", "true")
    monkeypatch.setenv("REALTIME_CACHE_TTL", "600")
    Config.reset_instance()
    DatabaseManager.reset_instance()
    service = PortfolioService()
    yield service
    DatabaseManager.reset_instance()
    Config.reset_instance()


def tencent_payload(stamp):
    fields = [""] * 50
    fields[1:7] = ["红利低波ETF", "512890", "1.185", "1.182", "1.18", "1000"]
    fields[30:35] = [stamp, "0.003", "0.25", "1.188", "1.18"]
    return 'v_sh512890="' + "~".join(fields) + '";'


@pytest.mark.parametrize("value", [None, "", "bad", "2026-09-24T15:00:00", float('nan'), float('inf'), True, 0])
def test_unknown_or_invalid_provider_times_are_not_invented(value):
    assert parse_quote_timestamp(value) is None


@pytest.mark.parametrize("source", ["tencent", "sina"])
def test_etf_respects_requested_provider(source, monkeypatch):
    fetcher = AkshareFetcher()
    target = MagicMock(return_value=UnifiedRealtimeQuote(code="512890", price=1.185))
    monkeypatch.setattr(fetcher, f"_get_stock_realtime_quote_{source}", target)
    eastmoney = MagicMock(side_effect=AssertionError("must not silently route ETF to Eastmoney"))
    monkeypatch.setattr(fetcher, "_get_etf_realtime_quote", eastmoney)
    quote = fetcher.get_realtime_quote("512890", source=source)
    assert quote.price == 1.185
    target.assert_called_once_with("512890")
    eastmoney.assert_not_called()


def test_etf_eastmoney_failure_really_falls_back_to_tencent(portfolio, monkeypatch):
    Config.get_instance().realtime_source_priority = "akshare_em,tencent"
    fetcher = AkshareFetcher()
    monkeypatch.setattr(fetcher, "_get_etf_realtime_quote", lambda _: None)
    monkeypatch.setattr(fetcher, "_enforce_rate_limit", lambda: None)
    monkeypatch.setattr("data_provider.akshare_fetcher.requests.get", lambda *args, **kwargs:
                        SimpleNamespace(status_code=200, text=tencent_payload("20260924161438")))
    quote = DataFetcherManager(fetchers=[fetcher]).get_realtime_quote("512890")
    assert quote.source == RealtimeSource.TENCENT
    assert quote.fallback_from == "akshare_em"
    assert quote.provider_timestamp == "2026-09-24T08:14:38+00:00"


@pytest.mark.parametrize("known_time", [True, False])
def test_old_tencent_quote_preserves_date_and_blocks_allocation(portfolio, monkeypatch, known_time):
    old_day = date.today() - timedelta(days=30)
    monkeypatch.setattr(AkshareFetcher, "_enforce_rate_limit", lambda _: None)
    monkeypatch.setattr("data_provider.akshare_fetcher.requests.get", lambda *args, **kwargs:
                        SimpleNamespace(status_code=200, text=tencent_payload(old_day.strftime('%Y%m%d') + '150000' if known_time else '')))
    account = portfolio.create_account(name="Test", broker=None, market="cn", base_currency="CNY")
    portfolio.record_trade(account_id=account['id'], symbol="512890", trade_date=date.today(), side="buy", quantity=100,
                           price=1, market="cn", currency="CNY")
    portfolio.record_cash_ledger(account_id=account['id'], event_date=date.today(), direction="in", amount=150000)
    snapshot = portfolio.get_portfolio_snapshot(account_id=account['id'])
    position = snapshot['accounts'][0]['positions'][0]
    assert position['price_date'] == (str(old_day) if known_time else None)
    assert position['price_timestamp'] == (str(old_day) + 'T07:00:00+00:00' if known_time else None)
    assert position['price_fetched_at'] is not None
    assert position['price_stale'] is True
    assert position['last_price'] == 1.185
    assert position['data_quality'] == "partial"
    from api.v1.schemas.portfolio import PortfolioPositionItem
    assert PortfolioPositionItem.model_validate(position).price_timestamp == position['price_timestamp']
    allocation = PortfolioAllocationService(portfolio_service=portfolio)
    plan = allocation.create_plan(name="Test", base_currency="CNY", target_total_value=1000000,
                                  account_id=account['id'], ledger_complete=True, targets=[
                                      {"key": "cash", "name": "Cash", "source": "cash", "target_pct": 10},
                                      {"key": "stock", "name": "ETF", "symbols": ["512890"], "target_pct": 90},
                                  ])
    status = allocation.evaluate_plan(plan['id'])
    target = next(item for item in status['targets'] if item['key'] == 'stock')
    assert target['action'] == 'review'
    assert target['recommended_amount'] == 0
    assert 'position_price_stale:512890' in target['limitations']


@pytest.mark.parametrize("offset,expected_stale", [(None, True), (-1800, True), (300, True), (-10, False)])
def test_portfolio_checks_quote_instant_not_retrieval_date(portfolio, monkeypatch, offset, expected_stale):
    now = datetime.now(timezone.utc)
    quote = UnifiedRealtimeQuote(code="VOO", price=700, source=RealtimeSource.YFINANCE,
                                 provider_timestamp=None if offset is None else (now + timedelta(seconds=offset)).isoformat(),
                                 fetched_at=now.isoformat(), is_stale=False)
    monkeypatch.setattr(DataFetcherManager, "get_realtime_quote", lambda *args, **kwargs: quote)
    result = portfolio._resolve_position_price(symbol="VOO", market="us", as_of_date=date.today())
    assert result.is_stale is expected_stale
    if offset is None:
        assert result.price_date is None
    assert result.price == 700


def test_quote_date_uses_exchange_timezone_not_server_date(portfolio, monkeypatch):
    quote = UnifiedRealtimeQuote(code="VOO", price=700, provider_timestamp="2026-09-26T00:30:00+00:00")
    monkeypatch.setattr(DataFetcherManager, "get_realtime_quote", lambda *args, **kwargs: quote)
    result = portfolio._resolve_position_price(symbol="VOO", market="us", as_of_date=date.today())
    assert result.price_date == date(2026, 9, 25)


@pytest.mark.parametrize("symbol", ["VOO", "SPX"])
def test_yahoo_price_and_time_come_from_same_observation(symbol, monkeypatch):
    info = {'regularMarketPrice': 707.51, 'regularMarketTime': 1790351582,
            'regularMarketPreviousClose': 700, 'currency': 'USD', 'shortName': symbol}
    ticker = SimpleNamespace(info=info, fast_info=SimpleNamespace(last_price=1.0, previous_close=699))
    monkeypatch.setattr('yfinance.Ticker', lambda _: ticker)
    quote = YfinanceFetcher().get_realtime_quote(symbol)
    assert quote.price == 707.51
    assert parse_quote_timestamp(quote.provider_timestamp).timestamp() == info['regularMarketTime']
    assert quote.source == RealtimeSource.YFINANCE
    assert quote.change_amount == 7.51
    assert quote.pre_close == 700


@pytest.mark.parametrize('symbol', ['VOO', 'SPX'])
def test_yahoo_does_not_mix_regular_price_with_unknown_previous_close(symbol, monkeypatch):
    ticker = SimpleNamespace(info={'regularMarketPrice': 707.51, 'regularMarketTime': 1790351582},
                             fast_info=SimpleNamespace(last_price=707, previous_close=699))
    monkeypatch.setattr('yfinance.Ticker', lambda _: ticker)
    quote = YfinanceFetcher().get_realtime_quote(symbol)
    assert quote.price == 707.51
    assert quote.pre_close is None and quote.change_pct is None


def test_yahoo_unknown_time_does_not_borrow_fetch_time(monkeypatch):
    ticker = SimpleNamespace(info={'regularMarketPrice': 707.51}, fast_info=SimpleNamespace(last_price=707.5))
    monkeypatch.setattr('yfinance.Ticker', lambda _: ticker)
    quote = YfinanceFetcher().get_realtime_quote('VOO')
    assert quote.provider_timestamp is None


def test_fx_preserves_observation_date_and_filters_future_bars(portfolio, monkeypatch):
    history = pd.DataFrame({'Close': [6.71, 6.72, 99.0]}, index=pd.to_datetime(['2026-09-24', '2026-09-25', '2026-09-27']))
    monkeypatch.setattr('src.services.portfolio_service.yf.Ticker', lambda _: SimpleNamespace(history=lambda **kwargs: history))
    assert portfolio._fetch_fx_rate_from_yfinance(from_currency='USD', to_currency='CNY', as_of_date=date(2026, 9, 26)) == (6.72, date(2026, 9, 25))
    account = portfolio.create_account(name='FX', broker=None, market='us', base_currency='CNY')
    portfolio.record_cash_ledger(account_id=account['id'], event_date=date(2026, 9, 24), direction='in', amount=1000, currency='USD')
    summary = portfolio.refresh_fx_rates(account_id=account['id'], as_of=date(2026, 9, 26))
    assert summary['stale_count'] == 1
    cached = portfolio.repo.get_latest_fx_rate(from_currency='USD', to_currency='CNY', as_of=date(2026, 9, 26))
    assert cached.rate_date == date(2026, 9, 25)
    assert portfolio.convert_amount(amount=100, from_currency='USD', to_currency='CNY', as_of_date=date(2026, 9, 26))[1] is True


@pytest.mark.parametrize("market,now,day,stamp,expected", [
    ("us", "2026-09-26T13:00:00Z", "2026-09-25", "2026-09-25T20:00:00Z", True),
    ("us", "2026-09-28T12:00:00Z", "2026-09-25", "2026-09-25T20:00:00Z", True),
    ("us", "2026-09-28T15:00:00Z", "2026-09-25", None, True),
    ("us", "2026-09-28T21:00:00Z", "2026-09-25", None, False),
    ("us", "2026-09-26T13:00:00Z", "2026-09-25", "2026-09-25T16:00:00Z", False),
    ("us", "2026-09-26T13:00:00Z", "2026-09-24", "2026-09-24T20:00:00Z", False),
    ("cn", "2026-09-26T13:00:00Z", "2026-09-24", "2026-09-24T08:14:38Z", True),
    ("us", "2026-11-27T20:00:00Z", "2026-11-27", "2026-11-27T18:00:00Z", True),
    ("us", "2026-11-27T17:00:00Z", "2026-11-27", "2026-11-27T18:00:00Z", False),
])
def test_close_reference_respects_sessions_holidays_and_early_close(market, now, day, stamp, expected):
    from src.core.trading_calendar import is_latest_completed_close
    assert is_latest_completed_close(market, date.fromisoformat(day),
                                     quote_time=parse_quote_timestamp(stamp),
                                     current_time=parse_quote_timestamp(now)) is expected


def test_calendar_unavailable_never_blesses_a_stale_quote(monkeypatch):
    from src.core import trading_calendar
    monkeypatch.setattr(trading_calendar, '_XCALS_AVAILABLE', False)
    assert not trading_calendar.is_latest_completed_close('us', date(2026, 9, 25))


@pytest.mark.parametrize("asof,rate_day,flag,expected", [
    ('2026-09-26', '2026-09-25', False, True),
    ('2026-09-28', '2026-09-25', False, True),
    ('2026-09-29', '2026-09-25', False, False),
    ('2026-09-26', '2026-09-24', False, False),
    ('2026-09-26', '2026-09-25', True, False),
])
def test_allocation_fx_reference_does_not_change_accounting_fx(portfolio, asof, rate_day, flag, expected):
    portfolio.repo.save_fx_rate(from_currency='USD', to_currency='CNY', rate_date=date.fromisoformat(rate_day),
                               rate=7.0, source='fixture', is_stale=flag)
    for source, target, amount, converted in [('USD', 'CNY', 100, 700), ('CNY', 'USD', 700, 100)]:
        value, usable, note = portfolio.convert_amount_for_allocation(
            amount=amount, from_currency=source, to_currency=target, as_of_date=date.fromisoformat(asof))
        assert usable is expected
        if usable:
            assert value == converted
            assert rate_day in note
        else:
            assert note is None
        assert portfolio.convert_amount(amount=amount, from_currency=source, to_currency=target,
                                        as_of_date=date.fromisoformat(asof))[1] is True


@pytest.mark.parametrize("fx_available", [True, False])
def test_real_snapshot_allocation_isolates_fx_and_renders_weekend_estimates(portfolio, monkeypatch, fx_available):
    from src.services.portfolio_service import _ResolvedPositionPrice
    from src.services.portfolio_allocation_report import render_allocation_status
    from api.v1.schemas.portfolio import PortfolioAllocationStatusResponse
    asof = date(2025, 1, 11)
    account = portfolio.create_account(name='Mixed', broker=None, market='us', base_currency='CNY')
    for currency, amount in [('CNY', 20000), ('USD', 700)]:
        portfolio.record_cash_ledger(account_id=account['id'], event_date=date(2025, 1, 10),
                                     direction='in', amount=amount, currency=currency)
    for symbol, market, currency, price in [('VOO', 'us', 'USD', 700), ('512890', 'cn', 'CNY', 1)]:
        portfolio.record_trade(account_id=account['id'], symbol=symbol, trade_date=date(2025, 1, 10),
                               side='buy', quantity=1, price=price, market=market, currency=currency)
    def resolved(**kwargs):
        return _ResolvedPositionPrice(price=700 if kwargs['symbol'] == 'VOO' else 1, source='history_close',
                                      price_date=date(2025, 1, 10), is_stale=True, is_available=True)
    monkeypatch.setattr(portfolio, '_resolve_position_price', resolved)
    if fx_available:
        portfolio.repo.save_fx_rate(from_currency='USD', to_currency='CNY', rate_date=date(2025, 1, 10),
                                   rate=7, source='fixture', is_stale=False)
    allocation = PortfolioAllocationService(portfolio_service=portfolio)
    plan = allocation.create_plan(name='Weekend', base_currency='CNY', target_total_value=100000,
                                  account_id=account['id'], ledger_complete=True, targets=[
                                      {'key': 'cash', 'name': 'Cash', 'source': 'cash', 'target_pct': 10},
                                      {'key': 'us', 'name': 'US', 'symbols': ['VOO'], 'target_pct': 45, 'batch_amount': 1000},
                                      {'key': 'cn', 'name': 'CN', 'symbols': ['512890'], 'target_pct': 45, 'batch_amount': 1000},
                                  ])
    status = allocation.evaluate_plan(plan['id'], as_of=asof, include_realtime=False)
    cash, us, cn = status['targets']
    assert status['available_cash'] == 9999
    assert cn['action'] == 'add' and cn['recommended_amount'] == 1000 and cn['is_estimate']
    assert us['action'] == ('add' if fx_available else 'review')
    assert us['recommended_amount'] == (1000 if fx_available else 0)
    assert 'close_reference:VOO:2025-01-10' in us['reference_notes']
    if fx_available:
        assert us['current_amount'] == 4900
        assert 'fx_reference:USD/CNY:2025-01-10' in us['reference_notes']
    validated = PortfolioAllocationStatusResponse.model_validate(status).model_dump()
    assert validated['targets'][2]['is_estimate'] is True
    report = render_allocation_status(validated)
    assert '估算参考' in report and '2025-01-10' in report
