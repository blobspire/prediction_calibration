"""Fee, slippage, liquidity, and lockup-aware edge simulation."""

from predmkt.edge.fees import capital_lockup_cost, kalshi_proxy_taker_fee
from predmkt.edge.simulator import (
    EdgeSimulationConfig,
    EdgeSimulationError,
    EdgeSimulationSummary,
    FeeScheduleEntry,
    FrictionTier,
    load_edge_simulation_config,
    run_edge_simulation,
)

__all__ = [
    "EdgeSimulationConfig",
    "EdgeSimulationError",
    "EdgeSimulationSummary",
    "FeeScheduleEntry",
    "FrictionTier",
    "capital_lockup_cost",
    "kalshi_proxy_taker_fee",
    "load_edge_simulation_config",
    "run_edge_simulation",
]
