#!/usr/bin/env python3
"""Isolated news/model acceptance. Defaults to offline, read-only preflight.

Run on the deployment host using its Python environment and ENV_FILE. No API
server, scheduler, notification dispatcher or broker is started. Only public
news is passed to the configured model; portfolio tables are never copied.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def read_sources(database: Path, market: str):
    """Only read source settings. Never initialize/migrate the production DB."""
    if not database.is_file():
        return [], {'status': 'database_missing', 'enabled_count': 0, 'selected_count': 0}
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA query_only=ON')
            total = connection.execute('SELECT COUNT(*) FROM intelligence_sources WHERE enabled = 1').fetchone()[0]
            rows = connection.execute('SELECT source_type, url, scope_type, scope_value, market FROM intelligence_sources '
                'WHERE enabled = 1 ORDER BY updated_at DESC, id DESC LIMIT 100').fetchall()
        relevant = [dict(row) for row in rows if market == 'global' or row['market'] in {market, 'global'}]
        return relevant[:6], {'status': 'bounded' if total > 100 or len(relevant) > 6 else 'available' if relevant else 'unconfigured',
                             'enabled_count': total, 'selected_count': min(6, len(relevant))}
    except sqlite3.Error:
        return [], {'status': 'database_unreadable_or_schema_missing', 'enabled_count': None, 'selected_count': 0}


def write_json(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def model_route_summary(config):
    """Report the selected route, not authentication or model health. No calls."""
    from src.llm.backend_registry import LOCAL_CLI_GENERATION_BACKEND_IDS, resolve_generation_backend_id
    from src.llm.generation_backend import GenerationError

    try:
        backend = resolve_generation_backend_id(config)
    except GenerationError:
        # Do not publish arbitrary invalid configuration values.
        backend = 'invalid'
    return {
        'generation_backend': backend,
        'model_route_configured': backend in LOCAL_CLI_GENERATION_BACKEND_IDS
            or (backend == 'litellm' and bool(config.litellm_model)),
        'model_deployment_count': len(config.llm_model_list),
    }


def summarize(brief, *, model_requested, source_inventory, frozen_roundtrip, retry_same_id, ledger_empty):
    """Connectivity, evidence and model completion are separate gates."""
    events = brief['events']
    evidence = {ev['evidence_id']: ev for event in events for ev in event['evidence']}
    coverage = brief['coverage']
    live = [source for source in coverage['sources'] if source['status'] == 'ok']
    failures = [source for source in coverage['sources'] if source['status'] in {'failed', 'unconfigured', 'bounded'}]
    checks = {
        'live_source_response': bool(live),
        'selected_events': bool(events),
        'all_selected_evidence_dated': bool(evidence) and all(ev['time_precision'] == 'timestamp' for ev in evidence.values()),
        'requested_sources_completed': not failures and source_inventory['status'] not in {
            'bounded', 'database_unreadable_or_schema_missing'},
        'model_contract': coverage['analysis_status'] == 'available' if model_requested else None,
        'frozen_roundtrip': frozen_roundtrip,
        'idempotent_retry': retry_same_id,
        'rendered_appendix': bool(brief.get('markdown', '').strip()),
        'isolated_portfolio_empty': ledger_empty,
    }
    return {
        'result': 'technical_checks_passed' if model_requested and all(value is True for value in checks.values()) else 'incomplete',
        'checks': checks, 'analysis_status': coverage['analysis_status'],
        'source_statuses': coverage['sources'], 'collected_count': coverage['collected_count'],
        'selected_count': len(events), 'selected_evidence_time_precision_counts': dict(Counter(ev['time_precision'] for ev in evidence.values())),
        'selected_event_time_bucket_counts': dict(Counter(event['time_bucket'] for event in events)),
        'excluded': coverage.get('excluded', {}),
    }


def run_check(output: Path, *, market='us', live=False, model=False, search=False, templates=()):
    """CLI worker only: never invoke in a running API process (DB singleton)."""
    from src.config import Config

    started = time.monotonic()
    config = Config.get_instance()
    original_database = Path(config.database_path).resolve()
    sources, inventory = read_sources(original_database, market)
    summary = {
        'check_version': 'market-event-acceptance-v1',
        'started_at': datetime.now(timezone.utc).isoformat(),
        'market': market, 'scope': 'template_smoke' if templates else 'deployment_configuration_isolated',
        'result': 'preflight_only', 'live_requested': live, 'model_requested': model, 'search_requested': search,
        'preflight': {**model_route_summary(config), 'sources': inventory},
        'not_tested': ['model_reasoning_quality', 'portfolio_reconciliation', 'production_http_auth_and_ui',
                       'scheduler_and_notifications', 'quotes_nav_and_execution'],
        'safety': {'production_database_access': 'read_only_source_settings', 'production_sources_modified': False,
                   'portfolio_copied': False, 'notifications_sent': False, 'orders_created': False},
    }
    write_json(output / 'acceptance.json', summary)
    if not live:
        return summary

    # Set the isolated destination BEFORE constructing any repository/analyzer.
    # generate_text also writes usage telemetry via the same DB singleton.
    scratch = output / 'acceptance.db'
    if scratch.exists() or scratch.resolve() == original_database:
        raise ValueError('A new isolated database path is required')
    config.database_path = str(scratch)
    os.environ['DATABASE_PATH'] = str(scratch)
    from src.storage import DatabaseManager
    from src.repositories.intelligence_repo import IntelligenceRepository
    from src.repositories.market_event_repo import MarketEventRepository
    from src.schemas.market_events import BriefRequest
    from src.services.intelligence_service import IntelligenceService
    from src.services.market_event_service import MarketEventService
    from sqlalchemy import inspect, text

    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        intel = IntelligenceService(IntelligenceRepository(db), config)
        if templates:
            available = {item['template_id']: item for item in intel.list_source_templates()['items']}
            if len(templates) > 6 or any(name not in available for name in templates):
                raise ValueError('Select at most six existing source template IDs')
            sources = [available[name] for name in dict.fromkeys(templates)]
            if any(market != 'global' and item['market'] not in {market, 'global'} for item in sources):
                raise ValueError('Template must match the chosen market or global')
            inventory = {'status': 'explicit_templates', 'enabled_count': len(sources), 'selected_count': len(sources)}
        # Preserve source behavior but anonymize local names. URLs/settings never
        # enter the shareable summary; the private scratch DB is not for sharing.
        # Repository listing is newest-first. Reverse insertion preserves the
        # deployment refresh order, which matters for bounded input selection.
        for index, source in reversed(list(enumerate(sources))):
            fields = {key: source.get(key) for key in ('source_type', 'url', 'scope_type', 'scope_value', 'market')}
            intel.repo.create_source(dict(fields, name=f'acceptance-source-{index + 1}', enabled=True))
        service = MarketEventService(repo=MarketEventRepository(db), intelligence=intel, holdings_loader=lambda _: [])
        request = BriefRequest(request_key='acceptance_' + uuid.uuid4().hex, market=market, language='zh',
                               refresh_sources=True, search_news=search, analyze=model)
        brief = service.generate(request)
        frozen = service.repo.get(brief['id']) == brief
        retry = service.generate(request)
        with db.get_session() as session:
            tables = [name for name in inspect(db._engine).get_table_names() if name.startswith('portfolio_')]
            empty = all(session.scalar(text(f'SELECT COUNT(*) FROM "{name}"')) == 0 for name in tables)
        summary.update(summarize(brief, model_requested=model, source_inventory=inventory,
            frozen_roundtrip=frozen, retry_same_id=retry['id'] == brief['id'] and retry['events'] == brief['events'], ledger_empty=empty))
        summary['finished_at'] = datetime.now(timezone.utc).isoformat()
        summary['elapsed_seconds'] = round(time.monotonic() - started, 2)
        summary['evidence_scope'] = inventory['status']
        write_json(output / 'brief.json', brief)
        (output / 'brief.md').write_text(brief['markdown'], encoding='utf-8')
        write_json(output / 'acceptance.json', summary)
        return summary
    finally:
        DatabaseManager.reset_instance()


def stop_worker(process):
    """Kill only our isolated worker tree; a timeout is never a passing check."""
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--market', choices=['cn', 'hk', 'us', 'global'], default='us')
    parser.add_argument('--live', action='store_true', help='Fetch news from copied enabled sources in an isolated database')
    parser.add_argument('--model', action='store_true', help='With --live, call the existing model; may incur provider fees')
    parser.add_argument('--search', action='store_true', help='With --live, also use configured search channels; may incur fees')
    parser.add_argument('--template', action='append', default=[], help='Explicit template smoke instead of configured-source acceptance')
    parser.add_argument('--output-dir', type=Path, help='New private output directory (default: a fresh OS temporary directory)')
    parser.add_argument('--timeout-seconds', type=int, default=180)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if (args.model or args.search or args.template) and not args.live:
        parser.error('--model, --search and --template require --live')
    if not 10 <= args.timeout_seconds <= 600:
        parser.error('--timeout-seconds must be between 10 and 600')
    if args.worker:
        logging.disable(logging.CRITICAL)
        try:
            run_check(args.output_dir, market=args.market, live=args.live, model=args.model, search=args.search, templates=args.template)
            return 0
        except Exception as exc:
            # Never persist provider exceptions, credentials, URLs or raw logs.
            write_json(args.output_dir / 'acceptance.json', {'result': 'failed', 'failure_type': type(exc).__name__})
            return 1
    if args.output_dir:
        args.output_dir = args.output_dir.resolve()
        args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    else:
        args.output_dir = Path(tempfile.mkdtemp(prefix='dsa-market-acceptance-'))
    command = [sys.executable, str(Path(__file__).resolve()), '--worker', '--output-dir', str(args.output_dir), '--market', args.market]
    command.extend(flag for flag, enabled in [('--live', args.live), ('--model', args.model), ('--search', args.search)] if enabled)
    for template in args.template:
        command.extend(['--template', template])
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=os.name != 'nt')
    try:
        process.wait(timeout=args.timeout_seconds)
    except subprocess.TimeoutExpired:
        stop_worker(process)
        write_json(args.output_dir / 'acceptance.json', {'result': 'timeout', 'timeout_seconds': args.timeout_seconds})
    path = args.output_dir / 'acceptance.json'
    summary = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'result': 'worker_failed'}
    if process.returncode and summary.get('result') not in {'failed', 'timeout'}:
        summary['result'] = 'worker_failed'
        write_json(path, summary)
    print(json.dumps({'output_dir': str(args.output_dir), **summary}, ensure_ascii=False, indent=2))
    # Preflight is successful execution but explicitly NOT acceptance.
    return 0 if summary['result'] in {'preflight_only', 'technical_checks_passed'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
