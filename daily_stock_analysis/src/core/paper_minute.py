"""Prospective one-session close-confirmed paper rules, never broker orders."""
from datetime import timezone

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from src.core.paper_observation import _d, _money

MINUTE_ENGINE_VERSION = "paper-minute-v1"


class MinuteRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_price: float = Field(gt=0, le=1000000, allow_inf_nan=False)
    exit_price: float = Field(gt=0, le=1000000, allow_inf_nan=False)
    invalidation_price: float = Field(gt=0, le=1000000, allow_inf_nan=False)
    expires_at: AwareDatetime

    @field_validator("expires_at")
    @classmethod
    def minute_boundary(cls, value):
        if value.second or value.microsecond:
            raise ValueError("minute_expiry_must_be_minute_aligned")
        return value.astimezone(timezone.utc)


def replay_minutes(action: str, assumptions: dict, rules: dict, bars: list[dict]) -> dict:
    """Service supplies one contiguous window, with one pre-start warmup bar.

    Previous bar close confirms; only the next open can fill, subject to adverse
    slippage, a price bound and 1% of the previous minute's volume. Candle touches
    alone never fill a limit. The invalidation level ends the simulation without
    forced liquidation or chasing a buyback. At most one round trip is modelled.
    """
    q, base = _d(assumptions["quantity"]), _d(assumptions["baseline_shares"])
    protected, cash0 = _d(assumptions["protected_shares"]), _d(assumptions["cash_usd"])
    cash, shares = cash0, base
    slip = _d(assumptions["slippage_bps"]) / 10000
    entry, target, invalid = (_d(rules[k]) for k in ("entry_price", "exit_price", "invalidation_price"))
    side = "buy" if action in {"buy", "add"} else "sell"
    fees = {s: _d(assumptions[f"{s}_fee_usd"]) for s in ("buy", "sell")}
    fills, events = [], []
    result = dict(horizon=0, status="no_fill", reason="minute_no_trigger", fills=fills, events=events,
                  baseline_kind="unchanged_shares" if base else "unchanged_cash",
                  relative_hold_pnl=0.0, closed_net_pnl=None, economic_cost_improvement_per_share=None,
                  opportunity_loss=0.0, entry_date=bars[1]["timestamp"], end_date=rules["expires_at"])
    if side == "sell" and base - q < protected:
        return dict(result, reason="protected_shares", ending_shares=float(base), ending_cash=float(cash))
    pending = None
    for i, bar in enumerate(bars[1:], start=1):
        op, high, low, close = (_d(bar[k]) for k in ("open", "high", "low", "close"))
        if _d(bar["volume"]) == 0:
            if pending:
                result["reason"] = "minute_liquidity_insufficient"
                events.append(dict(timestamp=bar["timestamp"], kind="rejected", reason=result["reason"], side=pending))
            pending = None
            continue  # No trade evidence; do not confirm a stale candle.
        # An opening gap is observable BEFORE any opening fill; later high/low
        # invalidation is processed AFTER fills, so losing entries are not erased.
        if (side == "buy" and op <= invalid) or (side == "sell" and op >= invalid):
            result["reason"] = "minute_invalidated"
            events.append(dict(timestamp=bar["timestamp"], kind="invalidation_at_open"))
            break
        if pending:
            leg = pending
            pending = None
            price = op * (1 + slip if leg == "buy" else 1 - slip)
            bound = entry if not fills else target
            bound_ok = price <= bound if leg == "buy" else price >= bound
            enough_volume = q <= _d(bars[i - 1]["volume"]) * _d("0.01") and q <= _d(bar["volume"])
            new_cash = cash + (q * price if leg == "sell" else -q * price) - fees[leg]
            # Single-session cash-only assumption: sale proceeds NEVER settle in
            # this window. A buyback must be funded by the original settled cash.
            spendable = cash0 if side == "sell" and fills else cash
            enough_cash = new_cash >= 0 and (leg != "buy" or spendable >= q * price + fees[leg])
            reason = ("minute_price_bound" if not bound_ok else "minute_liquidity_insufficient" if not enough_volume
                      else "exit_cash_insufficient" if fills and not enough_cash
                      else "entry_cash_insufficient" if not enough_cash else None)
            if reason:
                result["reason"] = reason
                events.append(dict(timestamp=bar["timestamp"], kind="rejected", reason=reason, side=leg))
            else:
                cash = new_cash
                shares += q if leg == "buy" else -q
                fills.append(dict(side=leg, timestamp=bar["timestamp"], confirmation_bar=bars[i - 1]["timestamp"],
                                  price=_money(price), quantity=float(q), fee=float(fees[leg])))
                result["reason"] = "minute_exit_not_filled"
                if len(fills) == 2:
                    result.update(status="completed", reason=None)
                    break
        invalid_touch = low <= invalid if side == "buy" else high >= invalid
        if invalid_touch:
            target_touch = high >= target if side == "buy" else low <= target
            result["reason"] = "minute_ambiguous_range" if target_touch else "minute_invalidated"
            events.append(dict(timestamp=bar["timestamp"], kind=result["reason"]))
            break
        if not fills:
            confirmed = close <= entry if side == "buy" else close >= entry
            if confirmed:
                pending = side
        else:
            confirmed = close >= target if side == "buy" else close <= target
            if confirmed:
                pending = "sell" if side == "buy" else "buy"
    if len(fills) == 1:
        result["status"] = "open"
        if result["reason"] == "minute_no_trigger":
            result["reason"] = "minute_exit_not_filled"
    elif not fills and pending and result["reason"] == "minute_no_trigger":
        result["reason"] = "minute_no_next_bar"
    pnl = cash - cash0 + (shares - base) * _d(bars[-1]["close"])
    mark_usable = shares == base or bars[-1]["volume"] > 0
    result.update(ending_shares=float(shares), ending_cash=_money(cash),
                  relative_hold_pnl=_money(pnl) if mark_usable else None,
                  opportunity_loss=_money(max(-pnl, _d(0))) if mark_usable else None)
    if len(fills) == 2:
        result.update(closed_net_pnl=_money(pnl),
                      economic_cost_improvement_per_share=_money(pnl / base) if base else None,
                      assumed_fees=_money(fees["buy"] + fees["sell"]))
    return result
