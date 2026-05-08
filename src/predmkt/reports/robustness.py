"""Robustness diagnostics from saved model and edge artifacts."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]

from predmkt.edge import (
    FrictionTier,
    load_edge_simulation_config,
    run_edge_simulation,
)
from predmkt.metrics.calibration import fit_calibration_intercept_slope
from predmkt.metrics.reliability import expected_calibration_error, reliability_bins
from predmkt.metrics.scoring import brier_score, log_loss


@dataclass(frozen=True)
class LiquidityFilter:
    """One liquidity-filter robustness rule."""

    name: str
    min_liquidity_proxy: float | None
    min_cumulative_volume: float | None


@dataclass(frozen=True)
class DomainExclusion:
    """One domain/category exclusion robustness rule."""

    name: str
    exclude_domains: tuple[str, ...]
    exclude_categories: tuple[str, ...]


@dataclass(frozen=True)
class FrictionScenario:
    """One edge-simulation friction robustness scenario."""

    name: str
    fee_rate: float
    capital_annual_rate: float
    min_net_edge: float
    tiers: tuple[FrictionTier, ...]


@dataclass(frozen=True)
class SnapshotVariant:
    """One small-sample snapshot-policy robustness variant."""

    name: str
    snapshot_methods: tuple[str, ...]


@dataclass(frozen=True)
class RobustnessConfig:
    """Configuration for non-confirmatory robustness diagnostics."""

    panel_path: Path
    walkforward_artifact_dir: Path
    edge_artifact_dir: Path
    backtest_config_path: Path
    sampling_config_path: Path
    contracts_path: Path
    price_observations_path: Path
    artifact_dir: Path
    table_dir: Path
    row_id_column: str
    model_column: str
    horizon_column: str
    contract_column: str
    event_family_column: str
    probability_column: str
    outcome_column: str
    snapshot_method_column: str
    liquidity_column: str
    cumulative_volume_column: str
    staleness_column: str
    domain_column: str
    category_column: str
    log_loss_epsilon: float
    reliability_bin_count: int
    reliability_min_bin_count: int
    calibration_min_rows: int
    calibration_max_iterations: int
    calibration_tolerance: float
    analysis_label: str
    limit_rows: int | None
    liquidity_filters: tuple[LiquidityFilter, ...]
    domain_exclusions: tuple[DomainExclusion, ...]
    friction_scenarios: tuple[FrictionScenario, ...]
    snapshot_variants_enabled: bool
    snapshot_variant_limit_contracts: int | None
    snapshot_variant_output_dir: Path
    snapshot_variants: tuple[SnapshotVariant, ...]
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class RobustnessSummary:
    """Summary metadata for robustness diagnostics."""

    artifact_dir: str
    table_dir: str
    source_artifacts: dict[str, str]
    artifact_paths: dict[str, str]
    snapshot_variant_count: int
    friction_scenario_count: int
    input_prediction_rows: int
    joined_prediction_rows: int
    effective_config: dict[str, Any]
    limitations: list[str]


class RobustnessError(ValueError):
    """Raised when robustness inputs are missing or invalid."""


def load_robustness_config(path: Path) -> RobustnessConfig:
    """Load robustness settings from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"robustness config must be a mapping: {path}")
    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    columns = _mapping(raw, "columns")
    metrics = _mapping(raw, "metrics")
    robustness = _mapping(raw, "robustness")
    snapshot_variants = _mapping(robustness, "snapshot_variants")

    return RobustnessConfig(
        panel_path=Path(_required(inputs, "panel_path")),
        walkforward_artifact_dir=Path(_required(inputs, "walkforward_artifact_dir")),
        edge_artifact_dir=Path(_required(inputs, "edge_artifact_dir")),
        backtest_config_path=Path(_required(inputs, "backtest_config_path")),
        sampling_config_path=Path(_required(inputs, "sampling_config_path")),
        contracts_path=Path(_required(inputs, "contracts_path")),
        price_observations_path=Path(_required(inputs, "price_observations_path")),
        artifact_dir=Path(_required(outputs, "artifact_dir")),
        table_dir=Path(_required(outputs, "table_dir")),
        row_id_column=str(_required(columns, "row_id_column")),
        model_column=str(_required(columns, "model_column")),
        horizon_column=str(_required(columns, "horizon_column")),
        contract_column=str(_required(columns, "contract_column")),
        event_family_column=str(_required(columns, "event_family_column")),
        probability_column=str(_required(columns, "probability_column")),
        outcome_column=str(_required(columns, "outcome_column")),
        snapshot_method_column=str(_required(columns, "snapshot_method_column")),
        liquidity_column=str(_required(columns, "liquidity_column")),
        cumulative_volume_column=str(_required(columns, "cumulative_volume_column")),
        staleness_column=str(_required(columns, "staleness_column")),
        domain_column=str(_required(columns, "domain_column")),
        category_column=str(_required(columns, "category_column")),
        log_loss_epsilon=float(_required(metrics, "log_loss_epsilon")),
        reliability_bin_count=int(_required(metrics, "reliability_bin_count")),
        reliability_min_bin_count=int(_required(metrics, "reliability_min_bin_count")),
        calibration_min_rows=int(_required(metrics, "calibration_min_rows")),
        calibration_max_iterations=int(_required(metrics, "calibration_max_iterations")),
        calibration_tolerance=float(_required(metrics, "calibration_tolerance")),
        analysis_label=str(_required(robustness, "analysis_label")),
        limit_rows=_optional_int(robustness.get("limit_rows")),
        liquidity_filters=tuple(
            LiquidityFilter(
                name=str(_required(item, "name")),
                min_liquidity_proxy=_optional_float(item.get("min_liquidity_proxy")),
                min_cumulative_volume=_optional_float(item.get("min_cumulative_volume")),
            )
            for item in _required_list(robustness, "liquidity_filters")
        ),
        domain_exclusions=tuple(
            DomainExclusion(
                name=str(_required(item, "name")),
                exclude_domains=tuple(str(value) for value in item.get("exclude_domains", [])),
                exclude_categories=tuple(
                    str(value) for value in item.get("exclude_categories", [])
                ),
            )
            for item in _required_list(robustness, "domain_exclusions")
        ),
        friction_scenarios=tuple(
            FrictionScenario(
                name=str(_required(item, "name")),
                fee_rate=float(_required(item, "fee_rate")),
                capital_annual_rate=float(_required(item, "capital_annual_rate")),
                min_net_edge=float(_required(item, "min_net_edge")),
                tiers=tuple(
                    FrictionTier(
                        name=str(_required(tier, "name")),
                        spread_cost=float(_required(tier, "spread_cost")),
                        slippage_cost=float(_required(tier, "slippage_cost")),
                    )
                    for tier in _required_list(item, "tiers")
                ),
            )
            for item in _required_list(robustness, "friction_scenarios")
        ),
        snapshot_variants_enabled=bool(_required(snapshot_variants, "enabled")),
        snapshot_variant_limit_contracts=_optional_int(snapshot_variants.get("limit_contracts")),
        snapshot_variant_output_dir=Path(_required(snapshot_variants, "output_dir")),
        snapshot_variants=tuple(
            SnapshotVariant(
                name=str(_required(item, "name")),
                snapshot_methods=tuple(str(value) for value in _required(item, "snapshot_methods")),
            )
            for item in _required_list(snapshot_variants, "variants")
        ),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def run_robustness(
    config: RobustnessConfig,
    *,
    run_snapshot_variants: bool = True,
) -> RobustnessSummary:
    """Write non-confirmatory robustness artifacts from saved results."""

    _validate_config(config)
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    config.table_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths = _artifact_paths(config.artifact_dir)

    predictions = _load_predictions(config)
    panel = _load_panel(config)
    joined = _join_predictions_panel(predictions, panel, config)

    snapshot_rows = snapshot_method_diagnostics(joined, config)
    liquidity_rows = liquidity_filter_diagnostics(joined, config)
    domain_rows = domain_exclusion_diagnostics(joined, config)
    friction_rows = friction_sensitivity(config)
    variant_rows = (
        snapshot_variant_runs(config) if run_snapshot_variants and config.snapshot_variants_enabled
        else pd.DataFrame(
            [
                {
                    "status": "not_run",
                    "reason": "snapshot variants disabled by CLI or config",
                    "analysis_label": config.analysis_label,
                    "non_confirmatory": True,
                }
            ]
        )
    )

    outputs = {
        "snapshot_method_slices": snapshot_rows,
        "liquidity_filter_sensitivity": liquidity_rows,
        "domain_exclusion_status": domain_rows,
        "friction_assumption_sensitivity": friction_rows,
        "snapshot_variant_runs": variant_rows,
    }
    for name, frame in outputs.items():
        frame.to_parquet(artifact_paths[name], index=False)
        _write_table_copies(frame, config.table_dir, name)

    summary = RobustnessSummary(
        artifact_dir=str(config.artifact_dir),
        table_dir=str(config.table_dir),
        source_artifacts=_source_artifacts(config),
        artifact_paths={key: str(path) for key, path in artifact_paths.items()},
        snapshot_variant_count=int(len(variant_rows)),
        friction_scenario_count=int(len(config.friction_scenarios)),
        input_prediction_rows=int(len(predictions)),
        joined_prediction_rows=int(len(joined)),
        effective_config=effective_robustness_config(config),
        limitations=_limitations(),
    )
    artifact_paths["summary"].write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return summary


def snapshot_method_diagnostics(
    joined: pd.DataFrame,
    config: RobustnessConfig,
) -> pd.DataFrame:
    """Return saved-artifact metric slices by snapshot method."""

    _require_columns(
        joined,
        [
            config.snapshot_method_column,
            config.model_column,
            config.horizon_column,
            config.probability_column,
            config.outcome_column,
        ],
        "snapshot-method diagnostics",
    )
    return _metric_rows(
        joined,
        config,
        ["snapshot_method", config.model_column, config.horizon_column],
        extra_columns={},
        rename={config.snapshot_method_column: "snapshot_method"},
    )


def liquidity_filter_diagnostics(
    joined: pd.DataFrame,
    config: RobustnessConfig,
) -> pd.DataFrame:
    """Return metric sensitivity rows after configured liquidity filters."""

    _require_columns(
        joined,
        [config.liquidity_column, config.cumulative_volume_column],
        "liquidity-filter diagnostics",
    )
    rows = []
    for rule in config.liquidity_filters:
        frame = joined.copy()
        if rule.min_liquidity_proxy is not None:
            frame = frame[
                pd.to_numeric(frame[config.liquidity_column], errors="coerce")
                >= rule.min_liquidity_proxy
            ]
        if rule.min_cumulative_volume is not None:
            frame = frame[
                pd.to_numeric(frame[config.cumulative_volume_column], errors="coerce")
                >= rule.min_cumulative_volume
            ]
        if frame.empty:
            rows.append(
                {
                    "filter_name": rule.name,
                    "model_name": None,
                    "horizon_name": None,
                    "row_count": 0,
                    "status": "empty_after_filter",
                    "analysis_label": config.analysis_label,
                    "non_confirmatory": True,
                }
            )
            continue
        rows.extend(
            _metric_rows(
                frame,
                config,
                [config.model_column, config.horizon_column],
                extra_columns={
                    "filter_name": rule.name,
                    "min_liquidity_proxy": rule.min_liquidity_proxy,
                    "min_cumulative_volume": rule.min_cumulative_volume,
                    "input_row_count": int(len(joined)),
                },
            ).to_dict(orient="records")
        )
    return pd.DataFrame(rows)


def domain_exclusion_diagnostics(
    joined: pd.DataFrame,
    config: RobustnessConfig,
) -> pd.DataFrame:
    """Return explicit domain/category exclusion status and metrics."""

    _require_columns(joined, [config.domain_column, config.category_column], "domain exclusions")
    domains = set(joined[config.domain_column].fillna("unknown").astype(str))
    categories = set(joined[config.category_column].fillna("unknown").astype(str))
    all_unknown = domains <= {"unknown"} and categories <= {"unknown"}
    rows: list[dict[str, Any]] = []
    for rule in config.domain_exclusions:
        if all_unknown:
            rows.append(
                {
                    "rule_name": rule.name,
                    "status": "not_applicable",
                    "reason": "domain_and_category_are_all_unknown",
                    "input_row_count": int(len(joined)),
                    "output_row_count": 0,
                    "excluded_row_count": 0,
                    "analysis_label": config.analysis_label,
                    "non_confirmatory": True,
                }
            )
            continue
        domain_mask = joined[config.domain_column].fillna("unknown").astype(str).isin(
            rule.exclude_domains
        )
        category_mask = joined[config.category_column].fillna("unknown").astype(str).isin(
            rule.exclude_categories
        )
        frame = joined[~(domain_mask | category_mask)].copy()
        rows.extend(
            _metric_rows(
                frame,
                config,
                [config.model_column, config.horizon_column],
                extra_columns={
                    "rule_name": rule.name,
                    "status": "computed",
                    "input_row_count": int(len(joined)),
                    "output_row_count": int(len(frame)),
                    "excluded_row_count": int(len(joined) - len(frame)),
                },
            ).to_dict(orient="records")
        )
    return pd.DataFrame(rows)


def friction_sensitivity(config: RobustnessConfig) -> pd.DataFrame:
    """Run configured edge-simulation friction scenarios and summarize outputs."""

    base = load_edge_simulation_config(config.backtest_config_path)
    rows: list[pd.DataFrame] = []
    for scenario in config.friction_scenarios:
        scenario_dir = config.artifact_dir / "friction_scenarios" / scenario.name
        scenario_config = replace(
            base,
            predictions_path=config.walkforward_artifact_dir / "predictions.parquet",
            panel_path=config.panel_path,
            artifact_dir=scenario_dir,
            fee_rate=scenario.fee_rate,
            capital_annual_rate=scenario.capital_annual_rate,
            min_net_edge=scenario.min_net_edge,
            tiers=scenario.tiers,
            limit_rows=config.limit_rows,
        )
        summary = run_edge_simulation(scenario_config)
        model_tier = pd.read_parquet(scenario_dir / "edge_summary_by_model_tier.parquet")
        model_tier.insert(0, "scenario_name", scenario.name)
        model_tier["fee_rate"] = scenario.fee_rate
        model_tier["capital_annual_rate"] = scenario.capital_annual_rate
        model_tier["min_net_edge"] = scenario.min_net_edge
        model_tier["scenario_artifact_dir"] = str(scenario_dir)
        model_tier["candidate_row_count_total"] = summary.candidate_row_count
        model_tier["analysis_label"] = config.analysis_label
        model_tier["non_confirmatory"] = True
        rows.append(model_tier)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def snapshot_variant_runs(config: RobustnessConfig) -> pd.DataFrame:
    """Run small-sample snapshot policy variants and return their summaries."""

    config.snapshot_variant_output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for variant in config.snapshot_variants:
        variant_dir = config.snapshot_variant_output_dir / variant.name
        output = variant_dir / "contract_horizon_panel.parquet"
        summary_path = (
            variant_dir / "contract_horizon_panel_summary.json"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable,
            "scripts/build_snapshot_panel.py",
            "--config",
            str(config.sampling_config_path),
            "--contracts",
            str(config.contracts_path),
            "--price-observations",
            str(config.price_observations_path),
            "--output",
            str(output),
            "--summary",
            str(summary_path),
            "--snapshot-methods",
            ",".join(variant.snapshot_methods),
        ]
        if config.snapshot_variant_limit_contracts is not None:
            cmd.extend(["--limit-contracts", str(config.snapshot_variant_limit_contracts)])
        completed = subprocess.run(cmd, check=False, text=True, capture_output=True)
        status = "completed" if completed.returncode == 0 else "failed"
        if completed.returncode != 0:
            rows.append(
                {
                    "variant_name": variant.name,
                    "status": status,
                    "returncode": completed.returncode,
                    "stderr": completed.stderr[-2000:],
                    "analysis_label": config.analysis_label,
                    "non_confirmatory": True,
                }
            )
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        rows.append(
            {
                "variant_name": variant.name,
                "status": status,
                "returncode": completed.returncode,
                "row_count": int(summary.get("row_count", 0)),
                "candidate_count": int(summary.get("candidate_count", 0)),
                "snapshot_method_counts_json": json.dumps(
                    summary.get("snapshot_method_counts", {}),
                    sort_keys=True,
                ),
                "output_path": str(output),
                "summary_path": str(summary_path),
                "analysis_label": config.analysis_label,
                "non_confirmatory": True,
            }
        )
    return pd.DataFrame(rows)


def effective_robustness_config(config: RobustnessConfig) -> dict[str, Any]:
    """Return a JSON-serializable effective robustness config."""

    return {
        "inputs": {
            "panel_path": str(config.panel_path),
            "walkforward_artifact_dir": str(config.walkforward_artifact_dir),
            "edge_artifact_dir": str(config.edge_artifact_dir),
            "backtest_config_path": str(config.backtest_config_path),
            "sampling_config_path": str(config.sampling_config_path),
        },
        "outputs": {
            "artifact_dir": str(config.artifact_dir),
            "table_dir": str(config.table_dir),
        },
        "robustness": {
            "analysis_label": config.analysis_label,
            "limit_rows": config.limit_rows,
            "liquidity_filters": [asdict(item) for item in config.liquidity_filters],
            "domain_exclusions": [asdict(item) for item in config.domain_exclusions],
            "friction_scenarios": [
                {
                    "name": item.name,
                    "fee_rate": item.fee_rate,
                    "capital_annual_rate": item.capital_annual_rate,
                    "min_net_edge": item.min_net_edge,
                    "tiers": [asdict(tier) for tier in item.tiers],
                }
                for item in config.friction_scenarios
            ],
            "snapshot_variants_enabled": config.snapshot_variants_enabled,
            "snapshot_variant_limit_contracts": config.snapshot_variant_limit_contracts,
        },
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }


def _metric_rows(
    frame: pd.DataFrame,
    config: RobustnessConfig,
    group_columns: list[str],
    *,
    extra_columns: dict[str, Any],
    rename: dict[str, str] | None = None,
) -> pd.DataFrame:
    if rename:
        frame = frame.rename(columns=rename)
        group_columns = [rename.get(column, column) for column in group_columns]
    rows: list[dict[str, Any]] = []
    for values, group in frame.groupby(group_columns, dropna=False, observed=True):
        if not isinstance(values, tuple):
            values = (values,)
        probabilities = pd.to_numeric(group[config.probability_column], errors="raise").tolist()
        outcomes = pd.to_numeric(group[config.outcome_column], errors="raise").tolist()
        bins = reliability_bins(
            probabilities,
            outcomes,
            bin_count=config.reliability_bin_count,
            min_bin_count=config.reliability_min_bin_count,
        )
        fit = fit_calibration_intercept_slope(
            probabilities,
            outcomes,
            epsilon=config.log_loss_epsilon,
            min_rows=config.calibration_min_rows,
            max_iterations=config.calibration_max_iterations,
            tolerance=config.calibration_tolerance,
        )
        row = {
            column: value
            for column, value in zip(group_columns, values, strict=True)
        }
        row.update(extra_columns)
        row.update(
            {
                "row_count": int(len(group)),
                "brier_score": brier_score(probabilities, outcomes),
                "log_loss": log_loss(
                    probabilities,
                    outcomes,
                    epsilon=config.log_loss_epsilon,
                ),
                "expected_calibration_error": expected_calibration_error(bins),
                "calibration_intercept": fit.intercept,
                "calibration_slope": fit.slope,
                "calibration_status": fit.status,
                "empty_bin_count": sum(item.is_empty for item in bins),
                "sparse_bin_count": sum(item.is_sparse for item in bins),
                "analysis_label": config.analysis_label,
                "non_confirmatory": True,
                "aggregation_mode": "equal_contract",
                "status": "computed",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _load_predictions(config: RobustnessConfig) -> pd.DataFrame:
    path = config.walkforward_artifact_dir / "predictions.parquet"
    if not path.exists():
        raise RobustnessError(f"missing walk-forward predictions: {path}")
    frame = pd.read_parquet(path)
    if config.limit_rows is not None:
        frame = frame.head(config.limit_rows).copy()
    _require_columns(
        frame,
        [
            config.row_id_column,
            config.model_column,
            config.horizon_column,
            config.contract_column,
            config.event_family_column,
            config.probability_column,
            config.outcome_column,
        ],
        "walk-forward predictions",
    )
    return frame.copy()


def _load_panel(config: RobustnessConfig) -> pd.DataFrame:
    if not config.panel_path.exists():
        raise RobustnessError(f"missing modeling panel: {config.panel_path}")
    frame = pd.read_parquet(config.panel_path).copy()
    if config.row_id_column not in frame.columns:
        frame.insert(0, config.row_id_column, range(len(frame)))
    return frame


def _join_predictions_panel(
    predictions: pd.DataFrame,
    panel: pd.DataFrame,
    config: RobustnessConfig,
) -> pd.DataFrame:
    panel_columns = [
        column
        for column in (
            config.row_id_column,
            config.contract_column,
            config.horizon_column,
            config.event_family_column,
            config.snapshot_method_column,
            config.liquidity_column,
            config.cumulative_volume_column,
            config.staleness_column,
            config.domain_column,
            config.category_column,
        )
        if column in panel.columns
    ]
    joined = predictions.merge(
        panel[panel_columns],
        on=config.row_id_column,
        how="left",
        suffixes=("", "_panel"),
        validate="many_to_one",
    )
    if joined[f"{config.contract_column}_panel"].isna().any():
        raise RobustnessError("walk-forward predictions reference row_ids missing from panel")
    for column in (config.contract_column, config.horizon_column, config.event_family_column):
        panel_column = f"{column}_panel"
        if panel_column in joined.columns:
            if not (joined[column].astype(str) == joined[panel_column].astype(str)).all():
                raise RobustnessError(f"prediction/panel key mismatch for {column}")
            joined = joined.drop(columns=[panel_column])
    return joined


def _validate_config(config: RobustnessConfig) -> None:
    if config.limit_rows is not None and config.limit_rows <= 0:
        raise RobustnessError("limit_rows must be positive when provided")
    if config.log_loss_epsilon <= 0.0:
        raise RobustnessError("log_loss_epsilon must be positive")
    if not config.liquidity_filters:
        raise RobustnessError("at least one liquidity filter is required")
    if not config.friction_scenarios:
        raise RobustnessError("at least one friction scenario is required")


def _require_columns(frame: pd.DataFrame, columns: list[str], context: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise RobustnessError(f"{context} missing required columns: {missing}")


def _artifact_paths(artifact_dir: Path) -> dict[str, Path]:
    return {
        "snapshot_method_slices": artifact_dir / "snapshot_method_slices.parquet",
        "liquidity_filter_sensitivity": artifact_dir / "liquidity_filter_sensitivity.parquet",
        "domain_exclusion_status": artifact_dir / "domain_exclusion_status.parquet",
        "friction_assumption_sensitivity": artifact_dir / "friction_assumption_sensitivity.parquet",
        "snapshot_variant_runs": artifact_dir / "snapshot_variant_runs.parquet",
        "summary": artifact_dir / "summary.json",
    }


def _source_artifacts(config: RobustnessConfig) -> dict[str, str]:
    return {
        "panel": str(config.panel_path),
        "walkforward_predictions": str(config.walkforward_artifact_dir / "predictions.parquet"),
        "edge_candidates": str(config.edge_artifact_dir / "edge_candidates.parquet"),
    }


def _write_table_copies(frame: pd.DataFrame, table_dir: Path, name: str) -> None:
    table_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(table_dir / f"{name}.csv", index=False)
    (table_dir / f"{name}.md").write_text(_markdown_table(frame), encoding="utf-8")


def _markdown_table(frame: pd.DataFrame) -> str:
    columns = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in frame.astype(object).where(pd.notna(frame), "").itertuples(index=False):
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines) + "\n"


def _limitations() -> list[str]:
    return [
        "Robustness outputs are diagnostics and sensitivity checks, not confirmatory "
        "replacement estimates.",
        "Snapshot-method slices are based on saved artifact rows; only the configured small "
        "snapshot variants are alternate reruns.",
        "Domain/category exclusions use Phase 12 rule-based taxonomy when available; "
        "low-confidence title, ambiguous, and unknown assignments remain non-confirmatory.",
        "Edge friction scenarios are simulated EV screens using transaction-price proxies; "
        "historical executable quote depth is unavailable.",
        "No NO-side complement trades are synthesized.",
    ]


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"robustness config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"robustness config missing required key: {key}")
    return raw[key]


def _required_list(raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = _required(raw, key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"robustness config key must be a list of mappings: {key}")
    return value


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        return float(value)
    raise ValueError(f"expected optional float-compatible value, got {type(value).__name__}")


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise ValueError(f"expected optional int-compatible value, got {type(value).__name__}")
