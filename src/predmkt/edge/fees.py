"""Fee and capital-lockup assumptions for conservative edge screens."""

from __future__ import annotations

SECONDS_PER_DAY = 86_400.0


def kalshi_proxy_taker_fee(entry_price: float, fee_rate: float) -> float:
    """Return a configurable Kalshi-style taker fee proxy per $1 payout contract."""

    if not 0.0 <= entry_price <= 1.0:
        raise ValueError(f"entry_price must be in [0, 1], got {entry_price}")
    if fee_rate < 0.0:
        raise ValueError(f"fee_rate cannot be negative, got {fee_rate}")
    return fee_rate * entry_price * (1.0 - entry_price)


def capital_lockup_cost(
    cost_basis: float,
    holding_seconds: float,
    annual_rate: float,
    *,
    day_count: float = 365.25,
) -> float:
    """Return a simple annualized capital charge over the holding interval."""

    if cost_basis < 0.0:
        raise ValueError(f"cost_basis cannot be negative, got {cost_basis}")
    if holding_seconds < 0.0:
        raise ValueError(f"holding_seconds cannot be negative, got {holding_seconds}")
    if annual_rate < 0.0:
        raise ValueError(f"annual_rate cannot be negative, got {annual_rate}")
    if day_count <= 0.0:
        raise ValueError(f"day_count must be positive, got {day_count}")
    return cost_basis * annual_rate * holding_seconds / (day_count * SECONDS_PER_DAY)
