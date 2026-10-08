"""Pure batch budget/risk scenario, independent of strategic target gaps.

No quotes, order quantities, persistence, ledger reservation or entry signal.
Full round-trip costs are reserved conservatively in the same cash pool.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def preview_tactical(request, now=None):
    now = now or datetime.now(timezone.utc)
    def dec(value):
        return Decimal(str(value))

    def money(value):
        return float(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    cash, tolerance = dec(request.available_cash_usd), dec(request.loss_tolerance_pct) / 100
    reasons, rows = [], []
    age = (now - request.cash_as_of).total_seconds()
    if age < 0 or age > 86400:
        reasons.append('cash_timestamp_stale_or_future')
    if not request.cash_net_of_other_budgets:
        reasons.append('cash_must_exclude_other_budgets')
    total_capital, total_cost, total_risk = Decimal(0), Decimal(0), Decimal(0)
    missing_cost = False
    for index, lot in enumerate(request.lots):
        capital = dec(lot.investment_usd)
        costs = None if lot.round_trip_cost_usd is None else dec(lot.round_trip_cost_usd)
        planned = capital * dec(lot.planned_loss_pct) / 100
        limit = capital * tolerance
        row_reasons = []
        if costs is None:
            missing_cost = True
            row_reasons.append('all_in_costs_required')
        if planned + (costs or Decimal(0)) > limit:
            row_reasons.append('planned_loss_exceeds_lot_tolerance')
        rows.append({'lot_index': index, 'symbol': lot.symbol, 'investment_usd': money(capital),
                     'cost_reserve_usd': None if costs is None else money(costs),
                     'planned_loss_usd': None if costs is None else money(planned + costs),
                     'tolerance_usd': money(limit), 'reasons': row_reasons,
                     'thesis': lot.thesis, 'invalidation': lot.invalidation})
        total_capital += capital
        total_cost += costs or Decimal(0)
        total_risk += planned + (costs or Decimal(0))
    if total_capital + total_cost > cash:
        reasons.append('shared_cash_exceeded')
    if missing_cost:
        reasons.append('all_in_costs_required')
    if any('planned_loss_exceeds_lot_tolerance' in row['reasons'] for row in rows):
        reasons.append('lot_risk_exceeded')
    return {'state': 'needs_revision' if reasons else 'scenario_only', 'executable': False,
            'evaluated_at': now.isoformat(), 'cash_as_of': request.cash_as_of.isoformat(),
            'available_cash_usd': money(cash), 'total_investment_usd': money(total_capital),
            'cash_required_usd': None if missing_cost else money(total_capital + total_cost),
            'remaining_cash_usd': None if missing_cost else money(cash - total_capital - total_cost),
            'planned_loss_usd': None if missing_cost else money(total_risk),
            'tolerance_usd': money(total_capital * tolerance), 'reasons': reasons, 'lots': rows,
            'limitations': ['user_inputs_not_broker_verified', 'preview_not_reserved',
                            'no_live_entry_or_exit_validation', 'portfolio_concentration_not_evaluated',
                            'loss_tolerance_not_default_stop_or_guaranteed_cap',
                            'new_lots_not_original_core', 'average_cost_reduction_not_realized_profit']}
