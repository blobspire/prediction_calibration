"""Config-driven conservative expected-value screens for walk-forward predictions."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]

from predmkt.edge.fees import SECONDS_PER_DAY


@dataclass(frozen=True)
class FrictionTier:
    """Named friction tier for edge simulation."""

    name: str
    spread_cost: float
    slippage_cost: float


@dataclass(frozen=True)
class EdgeSimulationConfig:
    """Configuration for conservative edge-screen generation."""

    predictions_path: Path
    panel_path: Path
    artifact_dir: Path
    row_id_column: str
    entry_price_column: str
    predicted_probability_column: str
    outcome_column: str
    forecast_column: str
    resolution_column: str
    model_column: str
    fold_column: str
    contract_column: str
    horizon_column: str
    event_family_column: str
    staleness_column: str
    liquidity_column: str
    cumulative_volume_column: str
    trade_side: str
    allow_synthetic_no: bool
    min_net_edge: float
    fee_formula: str
    fee_rate: float
    capital_lockup_enabled: bool
    capital_annual_rate: float
    capital_day_count: float
    max_staleness_seconds: float | None
    min_liquidity_proxy: float | None
    min_cumulative_volume: float | None
    tiers: tuple[FrictionTier, ...]
    limit_rows: int | None = None
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class EdgeSimulationSummary:
    """Summary metadata for a conservative edge-screen run."""

    predictions_path: str
    panel_path: str
    artifact_dir: str
    input_prediction_row_count: int
    joined_prediction_row_count: int
    candidate_row_count: int
    excluded_row_count: int
    tier_names: list[str]
    model_names: list[str]
    min_net_edge: float
    trade_side: str
    config_sha256: str | None
    git_commit: str | None
    git_dirty: bool | None
    artifact_paths: dict[str, str]
    effective_config: dict[str, Any]
    limitations: list[str]


class EdgeSimulationError(ValueError):
    """Raised when edge-simulation inputs or assumptions are invalid."""


def load_edge_simulation_config(path: Path) -> EdgeSimulationConfig:
    """Load edge-simulation settings from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"backtest config must be a mapping: {path}")

    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    columns = _mapping(raw, "columns")
    screen = _mapping(raw, "screen")
    fee = _mapping(raw, "fee")
    capital = _mapping(raw, "capital_lockup")
    filters = _mapping(raw, "filters")
    tiers_raw = raw.get("tiers")
    if not isinstance(tiers_raw, list) or not tiers_raw:
        raise ValueError("backtest config must define at least one friction tier")

    return EdgeSimulationConfig(
        predictions_path=Path(_required(inputs, "predictions_path")),
        panel_path=Path(_required(inputs, "panel_path")),
        artifact_dir=Path(_required(outputs, "artifact_dir")),
        row_id_column=str(_required(columns, "row_id_column")),
        entry_price_column=str(_required(columns, "entry_price_column")),
        predicted_probability_column=str(_required(columns, "predicted_probability_column")),
        outcome_column=str(_required(columns, "outcome_column")),
        forecast_column=str(_required(columns, "forecast_column")),
        resolution_column=str(_required(columns, "resolution_column")),
        model_column=str(_required(columns, "model_column")),
        fold_column=str(_required(columns, "fold_column")),
        contract_column=str(_required(columns, "contract_column")),
        horizon_column=str(_required(columns, "horizon_column")),
        event_family_column=str(_required(columns, "event_family_column")),
        staleness_column=str(_required(columns, "staleness_column")),
        liquidity_column=str(_required(columns, "liquidity_column")),
        cumulative_volume_column=str(_required(columns, "cumulative_volume_column")),
        trade_side=str(_required(screen, "trade_side")),
        allow_synthetic_no=bool(_required(screen, "allow_synthetic_no")),
        min_net_edge=float(_required(screen, "min_net_edge")),
        fee_formula=str(_required(fee, "formula")),
        fee_rate=float(_required(fee, "fee_rate")),
        capital_lockup_enabled=bool(_required(capital, "enabled")),
        capital_annual_rate=float(_required(capital, "annual_rate")),
        capital_day_count=float(_required(capital, "day_count")),
        max_staleness_seconds=_optional_float(filters.get("max_staleness_seconds")),
        min_liquidity_proxy=_optional_float(filters.get("min_liquidity_proxy")),
        min_cumulative_volume=_optional_float(filters.get("min_cumulative_volume")),
        tiers=tuple(
            FrictionTier(
                name=str(_required(tier, "name")),
                spread_cost=float(_required(tier, "spread_cost")),
                slippage_cost=float(_required(tier, "slippage_cost")),
            )
            for tier in tiers_raw
            if isinstance(tier, dict)
        ),
        limit_rows=_optional_int(screen.get("limit_rows")),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def run_edge_simulation(config: EdgeSimulationConfig) -> EdgeSimulationSummary:
    """Create conservative fee-aware YES-side edge screens."""

    _validate_config(config)
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths = _artifact_paths(config.artifact_dir)

    predictions = _load_predictions(config)
    panel = _load_panel(config)
    joined = _join_predictions_to_panel(predictions, panel, config)
    base_excluded, eligible = _base_exclusions(joined, config)
    candidates, tier_excluded = _candidate_rows(eligible, config)
    excluded = pd.concat([base_excluded, tier_excluded], ignore_index=True)

    tier_summary = _summary_by_tier(candidates, excluded, config)
    model_tier_summary = _summary_by_model_tier(candidates)

    candidates.to_parquet(artifact_paths["edge_candidates"], index=False)
    tier_summary.to_parquet(artifact_paths["edge_summary_by_tier"], index=False)
    model_tier_summary.to_parquet(artifact_paths["edge_summary_by_model_tier"], index=False)
    excluded.to_parquet(artifact_paths["excluded_rows"], index=False)

    git_commit, git_dirty = _git_state()
    summary = EdgeSimulationSummary(
        predictions_path=str(config.predictions_path),
        panel_path=str(config.panel_path),
        artifact_dir=str(config.artifact_dir),
        input_prediction_row_count=int(len(predictions)),
        joined_prediction_row_count=int(len(joined)),
        candidate_row_count=int(len(candidates)),
        excluded_row_count=int(len(excluded)),
        tier_names=[tier.name for tier in config.tiers],
        model_names=sorted(joined[config.model_column].dropna().astype(str).unique().tolist()),
        min_net_edge=config.min_net_edge,
        trade_side=config.trade_side,
        config_sha256=config.config_sha256,
        git_commit=git_commit,
        git_dirty=git_dirty,
        artifact_paths={key: str(value) for key, value in artifact_paths.items()},
        effective_config=_effective_config(config),
        limitations=[
            "Edge outputs are simulated expected-value screens, not executable trading "
            "profits or trade recommendations.",
            "The first edge layer is YES-side only; NO trades are not synthesized from "
            "1 minus the YES price.",
            "Entry prices are snapshot-based transaction proxies because historical "
            "executable bid/ask quotes and order-book depth are unavailable.",
            "The taker fee is a configurable Kalshi-style proxy, not a versioned audit "
            "of exact historical exchange billing.",
            "Spread and slippage tiers are conservative haircuts, not observed execution "
            "costs.",
            "Summaries are equal contract-horizon prediction rows and do not use trade "
            "weights.",
        ],
    )
    artifact_paths["summary"].write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return summary


def _load_predictions(config: EdgeSimulationConfig) -> pd.DataFrame:
    if not config.predictions_path.exists():
        raise EdgeSimulationError(f"predictions file does not exist: {config.predictions_path}")
    predictions = pd.read_parquet(config.predictions_path)
    if config.limit_rows is not None:
        predictions = predictions.head(config.limit_rows).copy()
    required = {
        config.row_id_column,
        config.entry_price_column,
        config.predicted_probability_column,
        config.outcome_column,
        config.forecast_column,
        config.resolution_column,
        config.model_column,
        config.contract_column,
        config.horizon_column,
        config.event_family_column,
    }
    missing = sorted(required - set(predictions.columns))
    if missing:
        raise EdgeSimulationError(f"prediction artifact missing columns: {missing}")
    return predictions.copy()


def _load_panel(config: EdgeSimulationConfig) -> pd.DataFrame:
    if not config.panel_path.exists():
        raise EdgeSimulationError(f"modeling panel does not exist: {config.panel_path}")
    panel = pd.read_parquet(config.panel_path)
    panel = panel.copy()
    if config.row_id_column not in panel.columns:
        panel.insert(0, config.row_id_column, range(len(panel)))
    return panel


def _join_predictions_to_panel(
    predictions: pd.DataFrame,
    panel: pd.DataFrame,
    config: EdgeSimulationConfig,
) -> pd.DataFrame:
    panel_column_names = {
        config.row_id_column,
        config.contract_column,
        config.horizon_column,
        config.event_family_column,
        config.forecast_column,
        config.resolution_column,
        config.staleness_column,
        config.liquidity_column,
        config.cumulative_volume_column,
        "snapshot_method",
        "price_timestamp",
        "close_time",
        "domain",
        "category",
    }
    panel_columns = [column for column in panel.columns if column in panel_column_names]
    joined = predictions.merge(
        panel[panel_columns],
        on=config.row_id_column,
        how="left",
        suffixes=("", "_panel"),
        validate="many_to_one",
    )
    if joined[f"{config.contract_column}_panel"].isna().any():
        raise EdgeSimulationError("prediction artifact references row_ids missing from panel")

    checks = {
        config.contract_column: joined[config.contract_column].astype(str)
        == joined[f"{config.contract_column}_panel"].astype(str),
        config.horizon_column: joined[config.horizon_column].astype(str)
        == joined[f"{config.horizon_column}_panel"].astype(str),
        config.event_family_column: joined[config.event_family_column].astype(str)
        == joined[f"{config.event_family_column}_panel"].astype(str),
    }
    for column in (config.forecast_column, config.resolution_column):
        left = pd.to_datetime(joined[column], utc=True, errors="raise")
        right = pd.to_datetime(joined[f"{column}_panel"], utc=True, errors="raise")
        checks[column] = left == right
        joined[column] = left
    failed = [name for name, mask in checks.items() if not bool(mask.all())]
    if failed:
        raise EdgeSimulationError(f"prediction/panel key mismatch for fields: {failed}")

    joined[config.resolution_column] = pd.to_datetime(
        joined[config.resolution_column],
        utc=True,
        errors="raise",
    )
    return joined


def _base_exclusions(
    joined: pd.DataFrame,
    config: EdgeSimulationConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = joined.copy()
    frame["entry_price"] = pd.to_numeric(frame[config.entry_price_column], errors="coerce")
    frame["predicted_probability"] = pd.to_numeric(
        frame[config.predicted_probability_column],
        errors="coerce",
    )
    frame["observed_outcome"] = pd.to_numeric(frame[config.outcome_column], errors="coerce")
    frame["holding_seconds"] = (
        frame[config.resolution_column] - frame[config.forecast_column]
    ).dt.total_seconds()

    reasons = pd.Series("", index=frame.index, dtype="object")
    reasons = _append_reason(
        reasons,
        frame["entry_price"].isna() | ~frame["entry_price"].between(0.0, 1.0),
        "invalid_entry_price",
    )
    reasons = _append_reason(
        reasons,
        frame["predicted_probability"].isna()
        | ~frame["predicted_probability"].between(0.0, 1.0),
        "invalid_predicted_probability",
    )
    reasons = _append_reason(
        reasons,
        ~frame["observed_outcome"].isin([0, 1]),
        "invalid_observed_outcome",
    )
    reasons = _append_reason(
        reasons,
        frame["holding_seconds"].isna() | (frame["holding_seconds"] < 0.0),
        "invalid_holding_period",
    )

    if config.max_staleness_seconds is not None:
        _require_column(frame, config.staleness_column, "max_staleness_seconds filter")
        staleness = pd.to_numeric(frame[config.staleness_column], errors="coerce")
        reasons = _append_reason(reasons, staleness.isna(), "missing_staleness")
        reasons = _append_reason(
            reasons,
            staleness > config.max_staleness_seconds,
            "stale_price",
        )
    if config.min_liquidity_proxy is not None:
        _require_column(frame, config.liquidity_column, "min_liquidity_proxy filter")
        liquidity = pd.to_numeric(frame[config.liquidity_column], errors="coerce")
        reasons = _append_reason(reasons, liquidity.isna(), "missing_liquidity_proxy")
        reasons = _append_reason(
            reasons,
            liquidity < config.min_liquidity_proxy,
            "low_liquidity_proxy",
        )
    if config.min_cumulative_volume is not None:
        _require_column(frame, config.cumulative_volume_column, "min_cumulative_volume filter")
        volume = pd.to_numeric(frame[config.cumulative_volume_column], errors="coerce")
        reasons = _append_reason(reasons, volume.isna(), "missing_cumulative_volume")
        reasons = _append_reason(
            reasons,
            volume < config.min_cumulative_volume,
            "low_cumulative_volume",
        )

    excluded_mask = reasons != ""
    excluded = _excluded_rows(frame[excluded_mask], reasons[excluded_mask])
    eligible = frame[~excluded_mask].copy()
    return excluded, eligible


def _candidate_rows(
    eligible: pd.DataFrame,
    config: EdgeSimulationConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if eligible.empty:
        return pd.DataFrame(), pd.DataFrame()

    candidate_frames: list[pd.DataFrame] = []
    excluded_frames: list[pd.DataFrame] = []
    for tier in config.tiers:
        frame = eligible.copy()
        frame["friction_tier"] = tier.name
        frame["trade_side"] = "YES"
        frame["fee_cost"] = config.fee_rate * frame["entry_price"] * (1.0 - frame["entry_price"])
        frame["spread_cost"] = tier.spread_cost
        frame["slippage_cost"] = tier.slippage_cost
        frame["cost_before_lockup"] = (
            frame["entry_price"] + frame["fee_cost"] + tier.spread_cost + tier.slippage_cost
        )
        holding_seconds = frame["holding_seconds"].clip(lower=0.0)
        if config.capital_lockup_enabled:
            frame["capital_lockup_cost"] = (
                frame["cost_before_lockup"]
                * config.capital_annual_rate
                * holding_seconds
                / (config.capital_day_count * SECONDS_PER_DAY)
            )
        else:
            frame["capital_lockup_cost"] = 0.0
        frame["effective_cost"] = frame["cost_before_lockup"] + frame["capital_lockup_cost"]
        invalid = frame["effective_cost"].isna() | (frame["effective_cost"] < 0.0)
        if invalid.any():
            invalid_reasons = pd.Series(
                "invalid_effective_cost",
                index=frame[invalid].index,
            )
            excluded_frames.append(
                _excluded_rows(frame[invalid], invalid_reasons)
            )
        frame = frame[~invalid].copy()
        frame["gross_edge"] = frame["predicted_probability"] - frame["entry_price"]
        frame["net_edge"] = frame["predicted_probability"] - frame["effective_cost"]
        frame["passes_threshold"] = frame["net_edge"] >= config.min_net_edge
        frame["notional_payout"] = 1.0
        frame["simulated_yes_payoff"] = frame["observed_outcome"].astype(float)
        frame["simulated_realized_net_per_contract"] = (
            frame["simulated_yes_payoff"] - frame["effective_cost"]
        )
        candidate_frames.append(_candidate_columns(frame, config))

    candidates = (
        pd.concat(candidate_frames, ignore_index=True) if candidate_frames else pd.DataFrame()
    )
    tier_excluded = (
        pd.concat(excluded_frames, ignore_index=True) if excluded_frames else pd.DataFrame()
    )
    return candidates, tier_excluded


def _candidate_columns(frame: pd.DataFrame, config: EdgeSimulationConfig) -> pd.DataFrame:
    optional_columns = [
        config.staleness_column,
        config.liquidity_column,
        config.cumulative_volume_column,
        "snapshot_method",
        "price_timestamp",
        "close_time",
        "domain",
        "category",
    ]
    base_columns = [
        config.fold_column,
        config.model_column,
        config.row_id_column,
        config.contract_column,
        config.event_family_column,
        config.horizon_column,
        config.forecast_column,
        config.resolution_column,
        config.outcome_column,
        "trade_side",
        "friction_tier",
        "entry_price",
        "predicted_probability",
        "fee_cost",
        "spread_cost",
        "slippage_cost",
        "capital_lockup_cost",
        "cost_before_lockup",
        "effective_cost",
        "gross_edge",
        "net_edge",
        "passes_threshold",
        "holding_seconds",
        "notional_payout",
        "simulated_yes_payoff",
        "simulated_realized_net_per_contract",
    ]
    columns = [*base_columns, *[column for column in optional_columns if column in frame.columns]]
    return frame[columns].copy()


def _excluded_rows(frame: pd.DataFrame, reasons: pd.Series) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    frame = frame.copy()
    if "friction_tier" not in frame.columns:
        frame["friction_tier"] = None
    columns = [
        column
        for column in (
            "fold_id",
            "model_name",
            "row_id",
            "contract_id",
            "event_family_id",
            "horizon_name",
            "forecast_ts",
            "close_time",
            "resolution_ts",
            "friction_tier",
        )
        if column in frame.columns
    ]
    excluded = frame[columns].copy()
    excluded["exclusion_reason"] = reasons.astype(str).to_numpy()
    return excluded


def _summary_by_tier(
    candidates: pd.DataFrame,
    excluded: pd.DataFrame,
    config: EdgeSimulationConfig,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    base_excluded_count = int(
        len(excluded[excluded.get("friction_tier", pd.Series(dtype=object)).isna()])
    ) if not excluded.empty else 0
    for tier in config.tiers:
        frame = (
            candidates[candidates["friction_tier"] == tier.name]
            if not candidates.empty
            else candidates
        )
        tier_excluded = (
            excluded[excluded.get("friction_tier", pd.Series(dtype=object)) == tier.name]
            if not excluded.empty
            else excluded
        )
        selected = frame[frame["passes_threshold"]] if not frame.empty else frame
        rows.append(
            _summary_row(
                tier.name,
                frame,
                selected,
                base_excluded_count + len(tier_excluded),
            )
        )
    return pd.DataFrame(rows)


def _summary_by_model_tier(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for (model_name, tier), frame in candidates.groupby(
        ["model_name", "friction_tier"],
        dropna=False,
        observed=True,
    ):
        selected = frame[frame["passes_threshold"]]
        row = _summary_row(str(tier), frame, selected, 0)
        row["model_name"] = str(model_name)
        rows.append(row)
    columns = ["model_name", *[column for column in rows[0] if column != "model_name"]]
    return pd.DataFrame(rows)[columns]


def _summary_row(
    tier_name: str,
    frame: pd.DataFrame,
    selected: pd.DataFrame,
    excluded_count: int,
) -> dict[str, Any]:
    return {
        "friction_tier": tier_name,
        "candidate_row_count": int(len(frame)),
        "selected_row_count": int(len(selected)),
        "excluded_row_count": int(excluded_count),
        "selected_share": _safe_mean(frame["passes_threshold"]) if not frame.empty else 0.0,
        "mean_entry_price": _safe_mean(frame["entry_price"]) if not frame.empty else None,
        "mean_predicted_probability": (
            _safe_mean(frame["predicted_probability"]) if not frame.empty else None
        ),
        "mean_fee_cost": _safe_mean(frame["fee_cost"]) if not frame.empty else None,
        "mean_spread_cost": _safe_mean(frame["spread_cost"]) if not frame.empty else None,
        "mean_slippage_cost": _safe_mean(frame["slippage_cost"]) if not frame.empty else None,
        "mean_capital_lockup_cost": (
            _safe_mean(frame["capital_lockup_cost"]) if not frame.empty else None
        ),
        "mean_gross_edge": _safe_mean(frame["gross_edge"]) if not frame.empty else None,
        "median_gross_edge": _safe_median(frame["gross_edge"]) if not frame.empty else None,
        "mean_net_edge": _safe_mean(frame["net_edge"]) if not frame.empty else None,
        "median_net_edge": _safe_median(frame["net_edge"]) if not frame.empty else None,
        "selected_mean_net_edge": (
            _safe_mean(selected["net_edge"]) if not selected.empty else None
        ),
        "selected_mean_simulated_realized_net_per_contract": (
            _safe_mean(selected["simulated_realized_net_per_contract"])
            if not selected.empty
            else None
        ),
    }


def _safe_mean(series: pd.Series) -> float:
    return float(series.astype(float).mean())


def _safe_median(series: pd.Series) -> float:
    return float(series.astype(float).median())


def _append_reason(reasons: pd.Series, mask: pd.Series, reason: str) -> pd.Series:
    updated = reasons.copy()
    mask = mask.fillna(True)
    updated.loc[mask & (updated == "")] = reason
    updated.loc[mask & (updated != reason) & (updated != "")] += f";{reason}"
    return updated


def _require_column(frame: pd.DataFrame, column: str, setting: str) -> None:
    if column not in frame.columns:
        raise EdgeSimulationError(f"{setting} requires missing column: {column}")


def _artifact_paths(artifact_dir: Path) -> dict[str, Path]:
    return {
        "edge_candidates": artifact_dir / "edge_candidates.parquet",
        "edge_summary_by_tier": artifact_dir / "edge_summary_by_tier.parquet",
        "edge_summary_by_model_tier": artifact_dir / "edge_summary_by_model_tier.parquet",
        "excluded_rows": artifact_dir / "excluded_rows.parquet",
        "summary": artifact_dir / "summary.json",
    }


def _effective_config(config: EdgeSimulationConfig) -> dict[str, Any]:
    return {
        "inputs": {
            "predictions_path": str(config.predictions_path),
            "panel_path": str(config.panel_path),
        },
        "outputs": {"artifact_dir": str(config.artifact_dir)},
        "screen": {
            "trade_side": config.trade_side,
            "allow_synthetic_no": config.allow_synthetic_no,
            "min_net_edge": config.min_net_edge,
            "limit_rows": config.limit_rows,
        },
        "fee": {"formula": config.fee_formula, "fee_rate": config.fee_rate},
        "capital_lockup": {
            "enabled": config.capital_lockup_enabled,
            "annual_rate": config.capital_annual_rate,
            "day_count": config.capital_day_count,
        },
        "filters": {
            "max_staleness_seconds": config.max_staleness_seconds,
            "min_liquidity_proxy": config.min_liquidity_proxy,
            "min_cumulative_volume": config.min_cumulative_volume,
        },
        "tiers": [asdict(tier) for tier in config.tiers],
        "columns": {
            "row_id_column": config.row_id_column,
            "entry_price_column": config.entry_price_column,
            "predicted_probability_column": config.predicted_probability_column,
            "outcome_column": config.outcome_column,
            "forecast_column": config.forecast_column,
            "resolution_column": config.resolution_column,
            "model_column": config.model_column,
            "fold_column": config.fold_column,
            "contract_column": config.contract_column,
            "horizon_column": config.horizon_column,
            "event_family_column": config.event_family_column,
            "staleness_column": config.staleness_column,
            "liquidity_column": config.liquidity_column,
            "cumulative_volume_column": config.cumulative_volume_column,
        },
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }


def _validate_config(config: EdgeSimulationConfig) -> None:
    if config.trade_side != "yes_only":
        raise EdgeSimulationError("Phase 8 supports trade_side = yes_only only")
    if config.allow_synthetic_no:
        raise EdgeSimulationError("synthetic NO complement trades are not supported")
    if config.fee_formula != "kalshi_proxy":
        raise EdgeSimulationError(f"unsupported fee formula: {config.fee_formula}")
    if config.fee_rate < 0.0:
        raise EdgeSimulationError("fee_rate cannot be negative")
    if config.min_net_edge < 0.0:
        raise EdgeSimulationError("min_net_edge cannot be negative")
    if config.capital_annual_rate < 0.0:
        raise EdgeSimulationError("capital annual_rate cannot be negative")
    if config.capital_day_count <= 0.0:
        raise EdgeSimulationError("capital day_count must be positive")
    if not config.tiers:
        raise EdgeSimulationError("at least one friction tier is required")
    seen: set[str] = set()
    for tier in config.tiers:
        if tier.name in seen:
            raise EdgeSimulationError(f"duplicate friction tier: {tier.name}")
        seen.add(tier.name)
        if tier.spread_cost < 0.0:
            raise EdgeSimulationError(f"spread_cost cannot be negative for tier {tier.name}")
        if tier.slippage_cost < 0.0:
            raise EdgeSimulationError(f"slippage_cost cannot be negative for tier {tier.name}")
    for name, value in (
        ("max_staleness_seconds", config.max_staleness_seconds),
        ("min_liquidity_proxy", config.min_liquidity_proxy),
        ("min_cumulative_volume", config.min_cumulative_volume),
    ):
        if value is not None and value < 0.0:
            raise EdgeSimulationError(f"{name} cannot be negative")
    if config.limit_rows is not None and config.limit_rows <= 0:
        raise EdgeSimulationError("limit_rows must be positive when provided")


def _git_state() -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return commit, bool(status.strip())
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"backtest config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"backtest config missing required key: {key}")
    return raw[key]


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float)):
        raise ValueError(f"expected numeric value or null, got {value!r}")
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, (str, int)):
        raise ValueError(f"expected integer value or null, got {value!r}")
    return int(value)
