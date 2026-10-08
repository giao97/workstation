"""Composition arithmetic, source contracts, real persistence and read-only scope."""
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from api.v1.endpoints import portfolio as endpoint
from src.core.etf_exposure import compare_compositions, composition_coverage
from src.repositories.etf_composition_repo import EtfCompositionRepository
from src.schemas.etf_exposure import EtfCompositionCommit, EtfCompositionInput
from src.services.etf_exposure_service import EtfExposureService
from src.storage import EtfCompositionSnapshot, PortfolioAccount, PortfolioTrade, PortfolioPosition
from tests.test_market_events import setup, NOW  # noqa: F401


def row(symbol='NVDA', weight='10', kind='equity', market='us'):
    return dict(symbol=symbol, market=market, name='Synthetic listing', weight_pct=weight, kind=kind)


def document(symbol='AAA', rows=None, **patch):
    return dict(fund_symbol=symbol, fund_market='us', holdings_as_of='2026-09-28',
        source_name='Synthetic test, not real issuer data', source_url='https://example.com/holdings',
        source_published_at='2026-09-29T00:00:00Z', methodology='long_only_nav_weight_pct',
        constituents=rows or [row()], **patch)


def fixture_snapshot(symbol, rows, snapshot_id):
    return dict(document(symbol, rows), id=snapshot_id)


def test_exact_overlap_partial_cash_nested_and_direct_matches():
    a = fixture_snapshot('AAA', [row(weight='10'), row('TSLA', '5'), row('CASH', '3', 'cash'), row('NEST', '10', 'fund')], 1)
    b = fixture_snapshot('BBB', [row(weight='7'), row('TSLA', '8'), row('NVDA', '2', market='hk')], 2)
    scope = [{'market': 'us', 'symbol': s} for s in ('AAA', 'BBB', 'TSLA', 'UNKNOWN')]
    result = compare_compositions([a, b], scope, date(2026, 9, 29))
    pair = result['pairs'][0]
    assert pair['observed_overlap_pct'] == 12  # min(10,7) + min(5,8); not normalized to 100
    assert pair['shared_count'] == 2
    assert result['funds'][0]['coverage']['undisclosed_pct'] == 72
    assert result['funds'][0]['coverage']['nested_fund_pct'] == 10
    assert {m['symbol'] for m in result['held_constituent_matches']} == {'TSLA'}
    assert result['portfolio_exposure_pct'] is None
    assert len(result['unclassified_holdings']) == 2
    assert a['constituents'] == document('AAA', a['constituents'])['constituents']


@pytest.mark.parametrize('day,status', [('2026-09-27', 'date_mismatch'), ('2026-09-01', 'stale_or_future'), ('2026-10-01', 'stale_or_future')])
def test_different_or_stale_dates_block_numeric_overlap(day, status):
    a = fixture_snapshot('AAA', [row()], 1); b = fixture_snapshot('BBB', [row()], 2)
    b['holdings_as_of'] = day
    result = compare_compositions([a, b], [{'market': 'us', 'symbol': s} for s in ('AAA', 'BBB')], date(2026, 9, 29))
    assert result['pairs'][0]['status'] == status
    assert result['pairs'][0]['observed_overlap_pct'] is None
    assert result['pairs'][0]['shared_count'] is None


def test_library_membership_not_holdings_and_zero_not_unknown():
    a = fixture_snapshot('AAA', [row()], 1); b = fixture_snapshot('BBB', [row('OTHER')], 2)
    assert compare_compositions([a, b], [], date(2026, 9, 29))['funds'] == []
    result = compare_compositions([a, b], [{'market': 'us', 'symbol': s} for s in ('AAA', 'BBB')], date(2026, 9, 29))
    assert result['pairs'][0]['observed_overlap_pct'] == 0
    assert 'partial_disclosure_is_not_full_diversification' in result['limitations']


@pytest.mark.parametrize('rows', [[row(weight='NaN')], [row(weight='Infinity')], [row(weight='-1')],
    [row(weight='0')], [row(weight='101')], [row(weight='60'), row('TSLA', '41')], [row(), row()], [row('AAA')]])
def test_invalid_weights_duplicates_and_self_holding_rejected(rows):
    with pytest.raises(ValidationError):
        EtfCompositionInput(**document(rows=rows))


@pytest.mark.parametrize('url', ['http://localhost/a', 'file:///tmp/a', 'https://x.example/a?token=SECRET', 'https://u:p@example.com/a'])
def test_unsafe_source_links_rejected(url):
    data = document(); data['source_url'] = url
    with pytest.raises(ValidationError):
        EtfCompositionInput(**data)


def test_timezone_methodology_and_explicit_review_required():
    for field, value in [('source_published_at', '2026-09-29T10:00:00'), ('methodology', 'notional_exposure')]:
        data = document(); data[field] = value
        with pytest.raises(ValidationError): EtfCompositionInput(**data)
    for reviewed in (False, 1, 'true'):
        with pytest.raises(ValidationError):
            EtfCompositionCommit(snapshot=document(), source_reviewed=reviewed)


@pytest.fixture()
def exposure(setup):
    original, clock, *_ = setup
    repo = EtfCompositionRepository(original.repo.db)
    return EtfExposureService(repo, clock, original.intelligence.config)


def save(service, data):
    return service.save(EtfCompositionCommit(snapshot=data, source_reviewed=True))


def count(service, model):
    with service.repo.db.get_session() as session:
        return session.scalar(select(func.count()).select_from(model))


def test_preview_no_write_save_idempotent_and_revision_immutable(exposure):
    assert exposure.preview(EtfCompositionInput(**document()))['coverage']['undisclosed_pct'] == 90
    assert count(exposure, EtfCompositionSnapshot) == 0
    first = save(exposure, document())
    assert save(exposure, document())['id'] == first['id']
    correction = document(rows=[row(weight='12')]); newer = save(exposure, correction)
    assert newer['id'] != first['id']
    assert exposure.repo.get(first['id']) == first
    assert exposure.repo.latest()[0]['id'] == newer['id']
    older = document(); older['holdings_as_of'] = '2026-09-27'
    save(exposure, older)
    assert exposure.repo.latest()[0]['id'] == newer['id']
    assert count(exposure, PortfolioAccount) == count(exposure, PortfolioTrade) == count(exposure, PortfolioPosition) == 0


def test_input_order_does_not_create_duplicate_snapshots(exposure):
    data = document(rows=[row(), row('TSLA')])
    first = save(exposure, data)
    data['constituents'].reverse()
    data['constituents'][0]['weight_pct'] = '10.00'
    assert save(exposure, data)['id'] == first['id']


def test_unknown_publication_not_replaced_by_retention_time(exposure):
    data = document(); data['source_published_at'] = None
    result = save(exposure, data)
    assert result['source_published_at'] is None
    assert result['recorded_at']


@pytest.mark.parametrize('field,value', [('holdings_as_of', '2026-09-30'), ('source_published_at', '2026-09-29T23:00:00Z'),
    ('source_published_at', '2026-09-27T10:00:00Z')])
def test_future_and_publication_before_holdings_rejected(exposure, field, value):
    data = document(); data[field] = value
    with pytest.raises(ValueError): save(exposure, data)


def test_expired_data_is_retained_but_not_used_as_current(exposure):
    first = save(exposure, document())
    exposure.clock.return_value = NOW + timedelta(days=20)
    assert composition_coverage(first, exposure.clock().date())['status'] == 'stale'
    assert exposure.repo.get(first['id']) == first


def test_profile_unknown_quantity_stays_scope_without_fabricated_weights(exposure, tmp_path):
    from tests.test_market_event_holdings import PROFILE
    path = tmp_path / 'profile.md'; path.write_text(PROFILE)
    exposure.config.market_event_profile_path = str(path)
    save(exposure, document('VOO', [row('TSLA', '4')]))
    report = exposure.report()
    assert report['holding_context']['status'] == 'profile_reference'
    assert {h['symbol'] for h in report['holdings']} == {'VOO', 'TSLA', '518880', '021514'}
    assert report['held_constituent_matches'][0]['fund_weight_pct'] == 4
    assert report['portfolio_exposure_pct'] is None
    assert 'PRIVATE' not in str(report)
    assert count(exposure, PortfolioAccount) == count(exposure, PortfolioPosition) == 0


def test_real_ledger_scope_excludes_closed_future_and_other_accounts(exposure, tmp_path):
    from tests.test_market_event_holdings import PROFILE
    path = tmp_path / 'profile.md'; path.write_text(PROFILE)
    exposure.config.market_event_profile_path = str(path)
    with exposure.repo.db.get_session() as session:
        a = PortfolioAccount(name='Fixture A', market='us', base_currency='USD', is_active=True)
        b = PortfolioAccount(name='Fixture B', market='us', base_currency='USD', is_active=True)
        session.add_all([a, b]); session.flush(); account_id = a.id
        for account, symbol, side, day in [(a, 'AAA', 'buy', 28), (a, 'HAL', 'buy', 28), (a, 'HAL', 'sell', 28),
                                         (a, 'FUTURE', 'buy', 30), (b, 'BBB', 'buy', 28)]:
            session.add(PortfolioTrade(account_id=account.id, symbol=symbol, market='us', currency='USD', side=side,
                quantity=1, price=100, fee=1, tax=0, trade_date=date(2026, 9, day)))
        session.commit()
    report = exposure.report(account_id)
    assert [h['symbol'] for h in report['holdings']] == ['AAA']
    assert report['holding_context']['status'] == 'recorded_ledger'
    assert {h['symbol'] for h in exposure.report()['holdings']} == {'AAA', 'BBB'}
    assert count(exposure, PortfolioTrade) == 5 and count(exposure, PortfolioPosition) == 0
    with pytest.raises(ValueError): exposure.report(999999)


def test_api_preview_save_read_and_validation(exposure, monkeypatch):
    monkeypatch.setattr(endpoint, 'EtfExposureService', lambda: exposure)
    app = FastAPI(); app.include_router(endpoint.router, prefix='/portfolio')
    client = TestClient(app)
    data = document()
    assert client.post('/portfolio/etf-compositions/preview', json=data).status_code == 200
    assert count(exposure, EtfCompositionSnapshot) == 0
    assert client.post('/portfolio/etf-compositions', json={'snapshot': data, 'source_reviewed': False}).status_code == 422
    saved = client.post('/portfolio/etf-compositions', json={'snapshot': data, 'source_reviewed': True})
    assert saved.status_code == 200
    assert client.get('/portfolio/etf-compositions/' + str(saved.json()['id'])).json() == saved.json()
    assert client.get('/portfolio/etf-compositions/999999').status_code == 404
    assert client.get('/portfolio/etf-exposure').json()['portfolio_exposure_pct'] is None
    assert client.get('/portfolio/etf-exposure?account_id=-1').status_code == 422
    assert count(exposure, PortfolioTrade) == count(exposure, PortfolioAccount) == 0
