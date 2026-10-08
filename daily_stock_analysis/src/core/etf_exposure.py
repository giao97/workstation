"""One-level exact-listing exposure, never issuer/factor or portfolio-weight inference."""
from decimal import Decimal
from itertools import combinations

METHOD_VERSION = 'etf-listed-equity-overlap-v1'


def composition_coverage(snapshot, today, max_age_days=7):
    from datetime import date
    age = (today - date.fromisoformat(snapshot['holdings_as_of'])).days
    totals = {kind: Decimal(0) for kind in ('equity', 'fund', 'cash', 'other')}
    for row in snapshot['constituents']:
        totals[row['kind']] += Decimal(str(row['weight_pct']))
    return {'status': 'eligible' if 0 <= age <= max_age_days else 'stale' if age > max_age_days else 'future',
            'age_days': age, 'disclosed_pct': float(sum(totals.values())),
            'equity_pct': float(totals['equity']), 'nested_fund_pct': float(totals['fund']),
            'cash_pct': float(totals['cash']), 'other_pct': float(totals['other']),
            'undisclosed_pct': float(100 - sum(totals.values()))}


def compare_compositions(snapshots, holdings, today, max_age_days=7):
    """Inputs are validated snapshots; each fund contributes its own NAV-weight vector."""
    held = {(h['market'], h['symbol']) for h in holdings}
    funds = [s for s in snapshots if (s['fund_market'], s['fund_symbol']) in held]
    coverage = {s['id']: composition_coverage(s, today, max_age_days) for s in funds}
    equities = {s['id']: {(c['market'], c['symbol']): Decimal(str(c['weight_pct']))
                         for c in s['constituents'] if c['kind'] == 'equity'} for s in funds}
    pairs, direct = [], []
    for left, right in combinations(funds, 2):
        item = {'left': left['fund_symbol'], 'right': right['fund_symbol'],
                'left_snapshot_id': left['id'], 'right_snapshot_id': right['id'],
                'observed_overlap_pct': None, 'shared_count': None, 'shared': []}
        if any(coverage[s['id']]['status'] != 'eligible' for s in (left, right)):
            item['status'] = 'stale_or_future'
        elif left['holdings_as_of'] != right['holdings_as_of']:
            item['status'] = 'date_mismatch'
        else:
            a, b = equities[left['id']], equities[right['id']]
            common = a.keys() & b.keys()
            rows = [{'market': k[0], 'symbol': k[1], 'left_weight_pct': float(a[k]),
                     'right_weight_pct': float(b[k]), 'overlap_pct': float(min(a[k], b[k]))} for k in common]
            item.update(status='observed_only', observed_overlap_pct=float(sum((min(a[k], b[k]) for k in common), Decimal(0))),
                        shared_count=len(rows), shared=sorted(rows, key=lambda r: (-r['overlap_pct'], r['market'], r['symbol'])))
        pairs.append(item)
    for fund in funds:
        if coverage[fund['id']]['status'] != 'eligible':
            continue
        for key, weight in sorted(equities[fund['id']].items()):
            if key in held:
                direct.append({'fund': fund['fund_symbol'], 'snapshot_id': fund['id'],
                               'symbol': key[1], 'market': key[0], 'fund_weight_pct': float(weight)})
    return {'methodology_version': METHOD_VERSION, 'funds': [dict(s, coverage=coverage[s['id']]) for s in funds],
            'pairs': pairs, 'held_constituent_matches': direct,
            'unclassified_holdings': [h for h in holdings if (h['market'], h['symbol']) not in
                                      {(s['fund_market'], s['fund_symbol']) for s in funds}],
            'portfolio_exposure_pct': None,
            'limitations': ['not_portfolio_weights', 'manual_source_attestation_not_certification',
                            'exact_market_symbol_only', 'no_issuer_adr_share_class_merge',
                            'no_nested_fund_derivative_or_factor_lookthrough',
                            'partial_disclosure_is_not_full_diversification', 'not_intraday_data',
                            'no_broker_sync_or_trade_recommendations']}
