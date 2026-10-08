"""Daily-close opportunity screen, separate from allocation and execution gates.

Versioned research heuristics, not a backtested strategy or fair-value model.
Costs are context only. This module never generates quantities or spends money.
"""
from math import isfinite


CORE_SYMBOLS = frozenset({'QQQM', 'VOO'})
METHOD = 'core-pullback-v1'


def assess_core_entry(symbol, bars, expected_dates, *, cost=None):
    result = dict(symbol=symbol, method=METHOD, state='data_required', as_of=None,
                  sources=[], metrics={}, reasons=[], checks=[], executable=False,
                  limitations=['daily_reference_only', 'unverified_adjustment_basis',
                               'heuristic_not_backtested', 'valuation_news_not_evaluated',
                               'budget_cash_fees_separate'])
    if symbol not in CORE_SYMBOLS:
        result['reasons'] = ['outside_core_scope']
        return result
    if not expected_dates or len(expected_dates) != 60:
        result['reasons'] = ['calendar_unavailable']
        return result
    if [b['date'] for b in bars] != list(expected_dates):
        result['reasons'] = ['need_latest_60_sessions']
        return result
    result['as_of'] = expected_dates[-1].isoformat()
    prices = [b.get('close') for b in bars]
    if any(isinstance(p, bool) or not isinstance(p, (float, int)) or not isfinite(p) or p <= 0 for p in prices):
        result['reasons'] = ['invalid_close']
        return result
    sources = {str(b.get('source') or '').strip() for b in bars}
    result['sources'] = sorted(s for s in sources if s)
    if '' in sources or len(sources) != 1:
        result['reasons'] = ['source_missing_or_mixed']
        return result
    close = prices[-1]
    ma20, ma60 = sum(prices[-20:]) / 20, sum(prices) / 60
    drawdown = (close / max(prices) - 1) * 100
    low_distance = (close / min(prices) - 1) * 100
    daily_change = (close / prices[-2] - 1) * 100
    metrics = dict(close=close, ma20=ma20, ma60=ma60, low60=min(prices), high60=max(prices),
                   drawdown_pct=drawdown, above_low_pct=low_distance, daily_change_pct=daily_change)
    if isinstance(cost, (float, int)) and not isinstance(cost, bool) and isfinite(cost) and cost > 0:
        metrics.update(ledger_cost=cost, versus_cost_pct=(close / cost - 1) * 100)
    if not all(isfinite(value) for value in metrics.values()):
        result['reasons'] = ['invalid_close']
        return result
    result['metrics'] = {key: round(value, 6) for key, value in metrics.items()}
    checks = []
    # A low in a flat 60-session range alone is deliberately not a trigger.
    if drawdown <= -3 and close <= ma20:
        checks.append('pullback_below_ma20')
    if low_distance <= 3 and drawdown <= -3 and close <= ma60:
        checks.append('near_60_session_low')
    if metrics.get('versus_cost_pct', 0) < 0:
        checks.append('below_cost_context_only')
    result['checks'] = checks
    # Abrupt historical discontinuities may also be splits / bad data; do not
    # silently treat an unadjusted series as a bargain.
    discontinuity = any(abs(b / a - 1) >= .15 for a, b in zip(prices, prices[1:]))
    if discontinuity or drawdown <= -20 or daily_change <= -5:
        result.update(state='risk_review', reasons=['large_move_or_deep_drawdown'])
    elif any(c != 'below_cost_context_only' for c in checks):
        if daily_change >= 0:
            result.update(state='candidate', reasons=['pullback_and_close_not_lower'])
        else:
            result.update(state='wait', reasons=['wait_for_stabilization'])
    else:
        result.update(state='wait', reasons=['no_pullback_setup'])
    return result
