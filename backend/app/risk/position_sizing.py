"""Position sizing: the largest position that respects BOTH limits.

  1. Risk limit       - loss if the stop loss is hit  <= balance x MAX_RISK_PERCENT
  2. Allocation limit - margin locked by the trade    <= balance x MAX_TRADE_ALLOCATION_PERCENT

For a position of N units (account currency USD):
  loss at stop  = N x |entry - stop| x (quote -> USD rate)
  position value= N x entry x (quote -> USD rate)        (value of the base currency / ounces)
  margin        = position value / leverage

Units are whole numbers (1 unit = 1 unit of base currency, or 1 troy ounce for
metals), rounded DOWN so neither limit is ever exceeded. If the result is
below the minimum size, the trade is not tradable and the reason is given -
the system must then answer WAIT rather than exceed a limit.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Literal

from app.core.instruments import get_instrument


@dataclass(frozen=True)
class PositionSize:
    instrument: str
    direction: Literal["BUY", "SELL"]
    units: int
    tradable: bool
    reason: str | None
    limited_by: Literal["risk", "allocation"]

    entry: float
    stop_loss: float
    stop_distance_pips: float

    balance: float
    risk_percent: float
    max_risk_amount: float      # allowed loss at the stop
    risk_amount: float          # actual loss at the stop for `units`
    allocation_percent: float
    max_allocation: float       # allowed margin
    margin_required: float      # actual margin for `units`
    leverage: float
    position_value: float       # notional value in account currency
    pip_value: float            # value of 1 pip for the whole position, account currency

    def to_dict(self) -> dict:
        return asdict(self)


def size_position(
    instrument: str,
    *,
    balance: float,
    entry: float,
    stop_loss: float,
    risk_percent: float,
    allocation_percent: float,
    leverage: float,
    account_currency: str = "USD",
    rates: Mapping[str, float] | None = None,
    min_units: int = 1,
) -> PositionSize:
    inst = get_instrument(instrument)
    if balance <= 0 or entry <= 0 or stop_loss <= 0:
        raise ValueError("balance, entry and stop_loss must be positive")
    if leverage < 1:
        raise ValueError("leverage must be >= 1")
    distance = abs(entry - stop_loss)
    if distance == 0:
        raise ValueError("stop_loss must differ from entry")

    to_account = inst.quote_to_account_rate(entry, account_currency, rates)
    loss_per_unit = distance * to_account
    margin_per_unit = entry * to_account / leverage

    max_risk = balance * risk_percent / 100.0
    max_alloc = balance * allocation_percent / 100.0
    units_by_risk = math.floor(max_risk / loss_per_unit + 1e-9)
    units_by_alloc = math.floor(max_alloc / margin_per_unit + 1e-9)
    units = min(units_by_risk, units_by_alloc)
    limited_by = "risk" if units_by_risk <= units_by_alloc else "allocation"

    tradable, reason = True, None
    if units < min_units:
        tradable = False
        if limited_by == "allocation":
            unit = "oz" if inst.asset_class == "metal" else "unit"
            reason = (f"{min_units} {unit} needs ${margin_per_unit * min_units:,.2f} margin "
                      f"but the allocation is ${max_alloc:,.2f}")
        else:
            reason = (f"stop is {inst.price_to_pips(distance):.1f} pips away: even {min_units} unit would risk "
                      f"${loss_per_unit * min_units:,.4f}, above the ${max_risk:,.2f} limit")
        units = 0

    return PositionSize(
        instrument=inst.name,
        direction="BUY" if stop_loss < entry else "SELL",
        units=units,
        tradable=tradable,
        reason=reason,
        limited_by=limited_by,
        entry=entry,
        stop_loss=stop_loss,
        stop_distance_pips=round(inst.price_to_pips(distance), 2),
        balance=balance,
        risk_percent=risk_percent,
        max_risk_amount=round(max_risk, 2),
        risk_amount=round(units * loss_per_unit, 4),
        allocation_percent=allocation_percent,
        max_allocation=round(max_alloc, 2),
        margin_required=round(units * margin_per_unit, 4),
        leverage=leverage,
        position_value=round(units * entry * to_account, 2),
        pip_value=round(units * inst.pip_value_per_unit(entry, account_currency, rates), 6),
    )
