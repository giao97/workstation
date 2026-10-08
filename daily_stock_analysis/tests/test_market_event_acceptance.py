"""Acceptance runner contracts, with synthetic feeds clearly isolated from live checks."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest.mock import Mock, patch
from types import SimpleNamespace

import pytest

from scripts.check_market_events import main, model_route_summary, read_sources, run_check, stop_worker, summarize
from src.config import Config
from src.services.intelligence_service import FeedEntry, IntelligenceService
from src.storage import DatabaseManager


def create_source_db(path):
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE intelligence_sources (id INTEGER PRIMARY KEY, name TEXT, source_type TEXT, '
                           'url TEXT, scope_type TEXT, scope_value TEXT, market TEXT, enabled INTEGER, updated_at TEXT)')
        connection.executemany('INSERT INTO intelligence_sources VALUES (?,?,?,?,?,?,?,?,?)', [
            (1, 'Private source name', 'rss', 'https://example.com/feed?api_key=DO_NOT_PRINT', 'market', None, 'us', 1, '2026-09-30'),
            (2, 'Disabled', 'rss', 'https://example.com/off', 'market', None, 'us', 0, '2026-09-30'),
            (3, 'Other market', 'rss', 'https://example.com/cn', 'market', None, 'cn', 1, '2026-09-30')])
        connection.execute('CREATE TABLE portfolio_fake_private (balance TEXT)')
        connection.execute("INSERT INTO portfolio_fake_private VALUES ('PRIVATE_ACCOUNT_BALANCE')")


@pytest.fixture
def context(tmp_path, monkeypatch):
    database = tmp_path / 'production.db'
    create_source_db(database)
    monkeypatch.setenv('ENV_FILE', str(tmp_path / 'missing.env'))
    monkeypatch.setenv('DATABASE_PATH', str(database))
    Config.reset_instance(); DatabaseManager.reset_instance()
    output = tmp_path / 'output'; output.mkdir()
    yield database, output
    Config.reset_instance(); DatabaseManager.reset_instance()


def synthetic_feed(*args, **kwargs):
    now = datetime.now(timezone.utc).isoformat()
    return [FeedEntry(title='Synthetic Federal Reserve interest rate policy', summary='Synthetic test only, not real news.',
        url='https://example.com/article', source='Synthetic', published_at=datetime.now(),
        raw_payload={'published_at_raw': now})]


@pytest.mark.parametrize('backend,model,configured', [
    ('codex_cli', '', True), ('claude_code_cli', '', True), ('opencode_cli', '', True),
    ('litellm', '', False), ('litellm', 'synthetic/test', True), ('invalid-secret-value', 'synthetic/test', False),
])
def test_preflight_recognizes_selected_generation_route_without_model_call(backend, model, configured):
    summary = model_route_summary(SimpleNamespace(generation_backend=backend, litellm_model=model, llm_model_list=[]))
    assert summary['model_route_configured'] is configured
    assert summary['model_deployment_count'] == 0
    assert summary['generation_backend'] == ('invalid' if backend == 'invalid-secret-value' else backend)


def test_read_only_source_selection_does_not_migrate_or_copy_portfolio(context):
    database, _ = context
    before = database.read_bytes()
    sources, inventory = read_sources(database, 'us')
    assert len(sources) == 1 and inventory['enabled_count'] == 2
    assert sources[0]['url'].endswith('DO_NOT_PRINT')
    assert read_sources(database, 'hk')[1]['status'] == 'unconfigured'
    assert read_sources(database.parent / 'missing.db', 'us')[1]['status'] == 'database_missing'
    assert not (database.parent / 'missing.db').exists()
    assert database.read_bytes() == before


def test_preflight_performs_no_network_and_writes_no_scratch_db(context):
    database, output = context
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with patch.object(IntelligenceService, '_fetch_feed_entries', side_effect=AssertionError('No network')):
        result = run_check(output)
    assert result['result'] == 'preflight_only'
    assert not (output / 'acceptance.db').exists()
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    public = (output / 'acceptance.json').read_text()
    assert 'DO_NOT_PRINT' not in public and 'PRIVATE_ACCOUNT_BALANCE' not in public and 'Private source name' not in public


def test_live_uses_same_pipeline_and_retry_without_mutating_production(context):
    database, output = context
    before = database.read_bytes()
    with patch.object(IntelligenceService, '_fetch_feed_entries', side_effect=synthetic_feed) as fetch:
        result = run_check(output, live=True)
    assert result['result'] == 'incomplete'  # sources alone cannot certify model acceptance
    assert result['analysis_status'] == 'not_requested'
    assert result['checks']['model_contract'] is None
    assert all(result['checks'][key] for key in ['live_source_response', 'selected_events', 'frozen_roundtrip',
                                               'idempotent_retry', 'isolated_portfolio_empty'])
    assert fetch.call_count == 1
    assert database.read_bytes() == before
    assert 'DO_NOT_PRINT' not in (output / 'acceptance.json').read_text()
    assert 'PRIVATE_ACCOUNT_BALANCE' not in (output / 'brief.json').read_text()
    with sqlite3.connect(output / 'acceptance.db') as conn:
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='portfolio_fake_private'").fetchall()


def test_unavailable_model_not_reported_as_success(context):
    _, output = context
    analyzer = Mock(); analyzer.is_available.return_value = False
    with patch.object(IntelligenceService, '_fetch_feed_entries', side_effect=synthetic_feed), \
         patch('src.analyzer.GeminiAnalyzer', return_value=analyzer):
        result = run_check(output, live=True, model=True)
    assert result['analysis_status'] == 'model_unavailable'
    assert result['checks']['model_contract'] is False and result['result'] == 'incomplete'
    analyzer.generate_text.assert_not_called()


def test_isolated_acceptance_never_reads_configured_profile(context, monkeypatch):
    _, output = context
    monkeypatch.setenv('MARKET_EVENT_PROFILE_PATH', '/private/not-to-read.md')
    Config.reset_instance()
    with patch.object(IntelligenceService, '_fetch_feed_entries', side_effect=synthetic_feed), \
         patch('src.services.market_event_holdings.load_profile_holdings', side_effect=AssertionError('No profile access')):
        run_check(output, live=True)
    assert json.loads((output / 'brief.json').read_text())['holdings'] == []


def test_real_telemetry_writer_stays_in_scratch_and_retry_does_not_recall_model(context):
    from src.analyzer import GeminiAnalyzer
    database, output = context
    before = database.read_bytes()
    def synthetic_model(prompt, **kwargs):
        supplied = json.loads(prompt.split('\nUNTRUSTED_NEWS_DATA:\n')[1])
        result = [dict(event_key=item['event_key'], evidence_ids=item['evidence_ids'],
            transmission='Synthetic conditional transmission', beneficiaries='Unknown', risks='Unverified',
            countercase='Synthetic countercase', horizon='Verify first', confirmation='Check primary evidence',
            invalidation='Source retracts', holding_links=[]) for item in supplied]
        return json.dumps({'events': result}), 'synthetic/test', {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}
    with patch.object(IntelligenceService, '_fetch_feed_entries', side_effect=synthetic_feed), \
         patch.object(GeminiAnalyzer, 'is_available', return_value=True), \
         patch.object(GeminiAnalyzer, '_call_litellm', side_effect=synthetic_model) as model:
        result = run_check(output, live=True, model=True)
    assert result['result'] == 'technical_checks_passed'  # synthetic test, not a live-model claim
    assert model.call_count == 1 and database.read_bytes() == before
    with sqlite3.connect(output / 'acceptance.db') as connection:
        assert connection.execute('SELECT total_tokens FROM llm_usage').fetchall() == [(15,)]


def test_refresh_order_matches_deployment_source_order(context):
    database, output = context
    with sqlite3.connect(database) as connection:
        connection.execute('INSERT INTO intelligence_sources VALUES (?,?,?,?,?,?,?,?,?)',
            (4, 'Newest', 'rss', 'https://example.com/newest', 'market', None, 'us', 1, '2099-10-01'))
    with patch.object(IntelligenceService, '_fetch_feed_entries', side_effect=synthetic_feed) as fetch:
        run_check(output, live=True)
    assert [call.args[0]['url'] for call in fetch.call_args_list] == [
        'https://example.com/newest', 'https://example.com/feed?api_key=DO_NOT_PRINT']


def test_healthy_empty_feed_never_passes_acceptance(context):
    _, output = context
    with patch.object(IntelligenceService, '_fetch_feed_entries', return_value=[]):
        result = run_check(output, live=True, model=True)
    assert result['checks']['live_source_response'] is True
    assert result['checks']['selected_events'] is False and result['result'] == 'incomplete'


def test_existing_scratch_database_is_not_overwritten(context):
    _, output = context
    existing = output / 'acceptance.db'; existing.write_text('Keep this data')
    with pytest.raises(ValueError, match='new isolated'):
        run_check(output, live=True)
    assert existing.read_text() == 'Keep this data'


def test_template_must_match_market_and_unknown_id_fails(context):
    _, output = context
    with pytest.raises(ValueError, match='six existing'):
        run_check(output, live=True, templates=['nonexistent'])


def test_template_smoke_is_labelled_and_preserves_original_settings(context):
    database, output = context
    before = database.read_bytes()
    with patch.object(IntelligenceService, '_fetch_feed_entries', side_effect=synthetic_feed):
        result = run_check(output, live=True, templates=['global-marketwatch'])
    assert result['scope'] == 'template_smoke' and result['evidence_scope'] == 'explicit_templates'
    assert database.read_bytes() == before


def test_source_failure_does_not_appear_in_shareable_output(context):
    _, output = context
    with patch.object(IntelligenceService, '_fetch_feed_entries', side_effect=RuntimeError('Bearer TOP_SECRET')):
        result = run_check(output, live=True)
    assert result['result'] == 'incomplete' and not result['checks']['live_source_response']
    assert 'TOP_SECRET' not in (output / 'acceptance.json').read_text()


def test_summarize_does_not_confuse_structural_checks_with_reasoning_quality():
    evidence = dict(evidence_id='e1', time_precision='timestamp')
    brief = dict(events=[dict(evidence=[evidence], time_bucket='today')], markdown='Synthetic appendix',
        coverage=dict(sources=[dict(source='feed', status='ok')], analysis_status='available', collected_count=1))
    result = summarize(brief, model_requested=True, source_inventory={'status': 'available'},
                       frozen_roundtrip=True, retry_same_id=True, ledger_empty=True)
    assert result['result'] == 'technical_checks_passed'
    brief['events'][0]['evidence'].append(dict(evidence_id='unknown', time_precision='timezone_unknown'))
    assert summarize(brief, model_requested=True, source_inventory={'status': 'available'},
                     frozen_roundtrip=True, retry_same_id=True, ledger_empty=True)['result'] == 'incomplete'
    brief['events'][0]['evidence'].pop()
    brief['coverage']['analysis_status'] = 'partial_analysis'
    assert summarize(brief, model_requested=True, source_inventory={'status': 'available'},
                     frozen_roundtrip=True, retry_same_id=True, ledger_empty=True)['result'] == 'incomplete'


def test_timeout_is_bounded_and_not_passing(tmp_path, capsys):
    process = Mock(pid=98765, returncode=-9)
    process.wait.side_effect = subprocess.TimeoutExpired('worker', 10)
    with patch('scripts.check_market_events.subprocess.Popen', return_value=process), \
         patch('scripts.check_market_events.stop_worker') as stop:
        code = main(['--output-dir', str(tmp_path / 'timeout'), '--timeout-seconds', '10'])
    stop.assert_called_once_with(process)
    assert code == 2 and json.loads(capsys.readouterr().out)['result'] == 'timeout'


@pytest.mark.skipif(os.name == 'nt', reason='POSIX worker-tree termination; Windows uses taskkill')
def test_stop_worker_reaps_real_isolated_process():
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'], start_new_session=True)
    try:
        stop_worker(process)
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=5)


def test_offline_cli_runs_from_arbitrary_cwd(context):
    database, output = context
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'check_market_events.py'
    run = subprocess.run([sys.executable, str(script), '--output-dir', str(output.parent / 'cli')],
                         cwd=output, capture_output=True, text=True, timeout=45, env=os.environ.copy())
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)['result'] == 'preflight_only'
    assert database.is_file()
