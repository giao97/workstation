"""Period trading contribution versus unchanged shares; not tax-lot profit.

No assumed fills, annualisation, fee schedules or future closing costs. All
money is kept in the instrument's original currency, using Decimal arithmetic.
"""
from decimal import Decimal
from typing import Any, Dict, List, Optional


def _decimal(value) -> Decimal:
    return Decimal(str(value))


def _output(value: Optional[Decimal]) -> Optional[float]:
    return float(value) if value is not None else None


def evaluate_trading_contribution(
    *, baseline_quantity: float, ending_quantity: float, trades: List[Dict[str, Any]],
    ledger_confirmed: bool, corporate_actions: List[Dict[str, Any]],
    valuation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compare identical initial holdings/cash, with versus without period trades.

    A restored share count makes the endpoint price cancel algebraically. An
    unclosed position needs a usable endpoint valuation; cash released by a sale
    alone is never profit. Corporate actions fail closed until entitlement and
    adjusted-share semantics are supported.
    """
    baseline, ending = _decimal(baseline_quantity), _decimal(ending_quantity)
    buys = sum((_decimal(t['quantity']) * _decimal(t['price']) for t in trades if t['side'] == 'buy'), Decimal(0))
    sells = sum((_decimal(t['quantity']) * _decimal(t['price']) for t in trades if t['side'] == 'sell'), Decimal(0))
    costs = sum((_decimal(t['fee']) + _decimal(t['tax']) for t in trades), Decimal(0))
    unknown_fees = [t['id'] for t in trades if t['fee_status'] != 'confirmed']
    gross = sells - buys
    net_cash = gross - costs if not unknown_fees else None
    limitations = []
    if not ledger_confirmed:
        limitations.append('performance_ledger_unconfirmed')
    if unknown_fees:
        limitations.append('performance_costs_unverified')
    if any(t['executed_at'] is None for t in trades):
        limitations.append('performance_execution_time_unknown')
    if corporate_actions:
        limitations.append('performance_corporate_action_unsupported')

    gap = ending - baseline if not corporate_actions else None
    status = ('unsupported' if corporate_actions else 'no_activity' if not trades else
              'restored' if gap == 0 else 'under_baseline' if gap < 0 else 'over_baseline')
    comparable = ledger_confirmed and not unknown_fees and not corporate_actions
    relative = closed_net = improvement = None
    mark_difference = None
    if comparable and gap == 0:
        relative = net_cash
        if trades:
            closed_net = net_cash
            improvement = closed_net / baseline if baseline > 0 else None
    elif gap is not None and gap != 0:
        if valuation and valuation.get('usable'):
            mark_difference = gap * _decimal(valuation['price'])
            if comparable:
                relative = net_cash + mark_difference
        else:
            limitations.append('performance_endpoint_unavailable')

    return {
        'status': status, 'baseline_quantity': float(baseline), 'ending_quantity': float(ending),
        'baseline_kind': 'unchanged_shares' if baseline > 0 else 'unchanged_cash',
        'share_gap': _output(gap),
        'unrecovered_quantity': _output(max(Decimal(0), -gap)) if gap is not None else None,
        'extra_quantity': _output(max(Decimal(0), gap)) if gap is not None else None,
        'buy_notional': float(buys), 'sell_notional': float(sells),
        'gross_cash_flow': float(gross), 'recorded_costs': float(costs),
        'costs_confirmed': not unknown_fees, 'net_cash_flow': _output(net_cash),
        'closed_net_pnl': _output(closed_net),
        'relative_hold_pnl': _output(relative), 'mark_difference': _output(mark_difference),
        'economic_cost_improvement_per_share': _output(improvement),
        'comparison_kind': ('unavailable' if relative is None else 'marked_estimate' if gap != 0 else 'cash_difference'),
        'unverified_fee_trade_ids': unknown_fees, 'trade_count': len(trades),
        'limitations': limitations,
    }


def aggregate_contributions(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Never add currencies, per-share improvements, or omit unknown rows silently."""
    totals = []
    for currency in sorted({item['currency'] for item in items}):
        rows = [item for item in items if item['currency'] == currency]
        known = [r for r in rows if r['relative_hold_pnl'] is not None]
        closed = [r for r in rows if r['closed_net_pnl'] is not None]
        total = sum((_decimal(r['relative_hold_pnl']) for r in known), Decimal(0)) if len(known) == len(rows) else None
        totals.append({
            'currency': currency, 'item_count': len(rows), 'comparable_count': len(known),
            'closed_verified_count': len(closed),
            'verified_closed_net_pnl': float(sum((_decimal(r['closed_net_pnl']) for r in closed), Decimal(0))) if closed else None,
            'relative_hold_pnl': _output(total),
            'contains_marked_estimate': any(r['comparison_kind'] == 'marked_estimate' for r in rows),
        })
    return totals
