"""Fixed-window counterfactuals, NOT intraday/conditional-order backtests.

Prices must be complete, action-free USD daily bars supplied by the service.
Each horizon is an independent scenario with its own identical starting capital.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator

ENGINE_VERSION = "paper-window-v1"
HORIZONS = (1, 3, 5, 10)


class PaperAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quantity: int = Field(gt=0, le=100000, strict=True)
    baseline_shares: int = Field(ge=0, le=10000000, strict=True)
    protected_shares: int = Field(ge=0, le=10000000, strict=True)
    cash_usd: float = Field(ge=0, le=100000000, allow_inf_nan=False)
    buy_fee_usd: float = Field(ge=0, le=10000, allow_inf_nan=False)
    sell_fee_usd: float = Field(ge=0, le=10000, allow_inf_nan=False)
    slippage_bps: float = Field(ge=0, le=500, allow_inf_nan=False)
    fee_note: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_protection(self):
        if self.protected_shares > self.baseline_shares:
            raise ValueError("protected_shares exceeds baseline_shares")
        if not self.fee_note.strip():
            raise ValueError("fee_note is required")
        return self


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def observe_window(action: str, assumptions: dict, first: dict, last: dict, horizon: int) -> dict:
    """Use next-session open and Nth-session close, with adverse slippage.

    The service validates provenance, sessions and OHLC first. No high/low touch
    is interpreted as a fill; entry/exit levels from the signal are NOT executed.
    All fees are user-frozen *assumptions*, not verified brokerage charges.
    """
    q = _d(assumptions["quantity"])
    base = _d(assumptions["baseline_shares"])
    protected = _d(assumptions["protected_shares"])
    cash = _d(assumptions["cash_usd"])
    slip = _d(assumptions["slippage_bps"]) / 10000
    op, close = _d(first["open"]), _d(last["close"])
    fees = {side: _d(assumptions[f"{side}_fee_usd"]) for side in ("buy", "sell")}
    result = dict(horizon=horizon, status="no_fill", reason=None, entry_date=first["date"],
                  end_date=last["date"], relative_hold_pnl=0.0, closed_net_pnl=None,
                  economic_cost_improvement_per_share=None, opportunity_loss=0.0,
                  ending_shares=float(base), ending_cash=float(cash), fills=[],
                  baseline_kind="unchanged_shares" if base else "unchanged_cash")
    if action not in {"buy", "add", "reduce", "sell"}:
        return dict(result, reason="non_directional_action")
    side = "buy" if action in {"buy", "add"} else "sell"
    reverse = "sell" if side == "buy" else "buy"
    if side == "sell" and base - q < protected:
        return dict(result, reason="protected_shares")
    # Use a PREVIOUS completed session for capacity, not the entry day's future
    # total volume. Today's zero-volume bar still cannot substantiate a fill.
    if q > _d(first["volume"]) or q > _d(first["previous_volume"]) * Decimal("0.001"):
        return dict(result, reason="entry_liquidity_insufficient")
    entry = op * (1 + slip if side == "buy" else 1 - slip)
    exit_price = close * (1 + slip if reverse == "buy" else 1 - slip)
    first_cash = cash + (-q * entry if side == "buy" else q * entry) - fees[side]
    if first_cash < 0:
        return dict(result, reason="entry_cash_insufficient")
    shares = base + (q if side == "buy" else -q)
    result["fills"].append(dict(side=side, date=first["date"], price=_money(entry), quantity=float(q), fee=float(fees[side])))
    # T+1 research assumption: same-day sale proceeds cannot finance a buyback.
    settled = cash if side == "sell" and horizon == 1 else first_cash
    final_cash = first_cash + (-q * exit_price if reverse == "buy" else q * exit_price) - fees[reverse]
    reason = None
    if q > _d(last["volume"]) or q > _d(last["previous_volume"]) * Decimal("0.001"):
        reason = "exit_liquidity_insufficient"
    elif (reverse == "buy" and settled < q * exit_price + fees[reverse]) or final_cash < 0:
        reason = "exit_cash_insufficient"
    if reason:
        pnl = first_cash - cash + (shares - base) * close
        return dict(result, status="open", reason=reason, ending_shares=float(shares),
                    ending_cash=_money(first_cash), relative_hold_pnl=_money(pnl) if last["volume"] > 0 else None,
                    opportunity_loss=_money(max(-pnl, Decimal(0))) if last["volume"] > 0 else None)
    result["fills"].append(dict(side=reverse, date=last["date"], price=_money(exit_price), quantity=float(q), fee=float(fees[reverse])))
    pnl = final_cash - cash
    return dict(result, status="completed", ending_cash=_money(final_cash),
                relative_hold_pnl=_money(pnl), closed_net_pnl=_money(pnl),
                assumed_fees=float(fees["buy"] + fees["sell"]),
                assumed_slippage_cost=_money(q * (op + close) * slip),
                opportunity_loss=_money(max(-pnl, Decimal(0))),
                economic_cost_improvement_per_share=_money(pnl / base) if base else None)
