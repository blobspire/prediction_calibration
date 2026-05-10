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
    exclude_sports: bool | None = None
    exclude_ambiguous: bool = False
    allowed_taxonomy_confidence: tuple[str, ...] = ()


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
class StalenessFilter:
    """One stale-price filter robustness rule."""

    name: str
    max_staleness_seconds: float | None


@dataclass(frozen=True)
class WeightingSensitivity:
    """Weighting robustness settings."""

    modes: tuple[str, ...]
    trade_weight_column: str


@dataclass(frozen=True)
class EventFamilyPurging:
    """Event-family purging robustness settings."""

    enabled: bool
    fit_splits: tuple[str, ...]


@dataclass(frozen=True)
class FullSnapshotVariant:
    """One full downstream snapshot-policy robustness variant."""

    name: str
    snapshot_methods: tuple[str, ...]
    vwap_window: str | None
    max_staleness: str | None
    limit_contracts: int | None


@dataclass(frozen=True)
class RobustnessConfig:
    """Configuration for non-confirmatory robustness diagnostics."""

    panel_path: Path
    walkforward_artifact_dir: Path
    edge_artifact_dir: Path
    splits_path: Path
    backtest_config_path: Path
    sampling_config_path: Path
    taxonomy_config_path: Path
    features_config_path: Path
    validation_config_path: Path
    models_config_path: Path
    inference_config_path: Path
    decomposition_config_path: Path
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
    trade_weight_column: str
    domain_column: str
    category_column: str
    is_sports_column: str
    taxonomy_confidence_column: str
    taxonomy_ambiguous_column: str
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
    staleness_filters: tuple[StalenessFilter, ...]
    weighting_sensitivity: WeightingSensitivity
    event_family_purging: EventFamilyPurging
    snapshot_variants_enabled: bool
    snapshot_variant_limit_contracts: int | None
    snapshot_variant_output_dir: Path
    snapshot_variants: tuple[SnapshotVariant, ...]
    full_snapshot_variants_enabled: bool
    full_snapshot_variant_output_dir: Path
    full_snapshot_variant_processed_dir: Path
    full_snapshot_variant_run_downstream: bool
    full_snapshot_variant_limit_contracts: int | None
    full_snapshot_variant_inference_bootstrap_iterations: int | None
    full_snapshot_variants: tuple[FullSnapshotVariant, ...]
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
    full_snapshot_variant_count: int
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
    full_snapshot_variants = _mapping_or_empty(robustness, "full_snapshot_variants")
    weighting = _mapping_or_empty(robustness, "weighting_sensitivity")
    event_family = _mapping_or_empty(robustness, "event_family_purging")

    return RobustnessConfig(
        panel_path=Path(_required(inputs, "panel_path")),
        walkforward_artifact_dir=Path(_required(inputs, "walkforward_artifact_dir")),
        edge_artifact_dir=Path(_required(inputs, "edge_artifact_dir")),
        splits_path=Path(inputs.get("splits_path", "data/processed/walkforward_splits.parquet")),
        backtest_config_path=Path(_required(inputs, "backtest_config_path")),
        sampling_config_path=Path(_required(inputs, "sampling_config_path")),
        taxonomy_config_path=Path(inputs.get("taxonomy_config_path", "configs/taxonomy.yaml")),
        features_config_path=Path(inputs.get("features_config_path", "configs/features.yaml")),
        validation_config_path=Path(
            inputs.get("validation_config_path", "configs/validation.yaml")
        ),
        models_config_path=Path(inputs.get("models_config_path", "configs/models.yaml")),
        inference_config_path=Path(inputs.get("inference_config_path", "configs/inference.yaml")),
        decomposition_config_path=Path(
            inputs.get("decomposition_config_path", "configs/decomposition.yaml")
        ),
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
        trade_weight_column=str(
            columns.get(
                "trade_weight_column",
                columns.get("cumulative_volume_column", "cumulative_volume_to_forecast"),
            )
        ),
        domain_column=str(_required(columns, "domain_column")),
        category_column=str(_required(columns, "category_column")),
        is_sports_column=str(columns.get("is_sports_column", "is_sports")),
        taxonomy_confidence_column=str(
            columns.get("taxonomy_confidence_column", "taxonomy_confidence")
        ),
        taxonomy_ambiguous_column=str(
            columns.get("taxonomy_ambiguous_column", "taxonomy_ambiguous")
        ),
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
                exclude_sports=_optional_bool(item.get("exclude_sports")),
                exclude_ambiguous=_optional_bool(item.get("exclude_ambiguous")) or False,
                allowed_taxonomy_confidence=tuple(
                    str(value) for value in item.get("allowed_taxonomy_confidence", [])
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
        staleness_filters=tuple(
            StalenessFilter(
                name=str(_required(item, "name")),
                max_staleness_seconds=_optional_float(item.get("max_staleness_seconds")),
            )
            for item in _list_or_empty(robustness, "staleness_filters")
        )
        or (StalenessFilter(name="all_rows", max_staleness_seconds=None),),
        weighting_sensitivity=WeightingSensitivity(
            modes=tuple(str(value) for value in weighting.get("modes", ["equal_contract"])),
            trade_weight_column=str(
                weighting.get("trade_weight_column", columns.get("trade_weight_column", ""))
            ),
        ),
        event_family_purging=EventFamilyPurging(
            enabled=bool(event_family.get("enabled", True)),
            fit_splits=tuple(str(value) for value in event_family.get("fit_splits", []))
            or ("train", "validation"),
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
        full_snapshot_variants_enabled=bool(full_snapshot_variants.get("enabled", False)),
        full_snapshot_variant_output_dir=Path(
            full_snapshot_variants.get(
                "output_dir",
                "data/artifacts/robustness/full_snapshot_variants",
            )
        ),
        full_snapshot_variant_processed_dir=Path(
            full_snapshot_variants.get(
                "processed_dir",
                "data/processed/robustness/full_snapshot_variants",
            )
        ),
        full_snapshot_variant_run_downstream=bool(
            full_snapshot_variants.get("run_downstream", True)
        ),
        full_snapshot_variant_limit_contracts=_optional_int(
            full_snapshot_variants.get("limit_contracts")
        ),
        full_snapshot_variant_inference_bootstrap_iterations=_optional_int(
            full_snapshot_variants.get("inference_bootstrap_iterations")
        ),
        full_snapshot_variants=tuple(
            FullSnapshotVariant(
                name=str(_required(item, "name")),
                snapshot_methods=tuple(str(value) for value in _required(item, "snapshot_methods")),
                vwap_window=_optional_str(item.get("vwap_window")),
                max_staleness=_optional_str(item.get("max_staleness")),
                limit_contracts=_optional_int(item.get("limit_contracts")),
            )
            for item in _list_or_empty(full_snapshot_variants, "variants")
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
    staleness_rows = staleness_filter_diagnostics(joined, config)
    weighting_rows = weighting_sensitivity_diagnostics(joined, config)
    event_family_rows = event_family_exclusion_sensitivity(joined, config)
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
    full_variant_rows, full_variant_metric_rows = (
        full_snapshot_variant_runs(config)
        if run_snapshot_variants and config.full_snapshot_variants_enabled
        else (
            pd.DataFrame(
                [
                    {
                        "status": "not_run",
                        "reason": "full snapshot variants disabled by CLI or config",
                        "analysis_label": config.analysis_label,
                        "non_confirmatory": True,
                    }
                ]
            ),
            pd.DataFrame(
                [
                    {
                        "status": "not_run",
                        "reason": "full snapshot variants disabled by CLI or config",
                        "analysis_label": config.analysis_label,
                        "non_confirmatory": True,
                    }
                ]
            ),
        )
    )

    outputs = {
        "snapshot_method_slices": snapshot_rows,
        "liquidity_filter_sensitivity": liquidity_rows,
        "staleness_filter_sensitivity": staleness_rows,
        "weighting_sensitivity": weighting_rows,
        "event_family_exclusion_sensitivity": event_family_rows,
        "domain_exclusion_status": domain_rows,
        "friction_assumption_sensitivity": friction_rows,
        "snapshot_variant_runs": variant_rows,
        "full_snapshot_variant_runs": full_variant_rows,
        "full_snapshot_variant_metrics": full_variant_metric_rows,
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
        full_snapshot_variant_count=int(len(full_variant_rows)),
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


def staleness_filter_diagnostics(
    joined: pd.DataFrame,
    config: RobustnessConfig,
) -> pd.DataFrame:
    """Return metric sensitivity rows after configured stale-price filters."""

    _require_columns(joined, [config.staleness_column], "staleness-filter diagnostics")
    rows: list[dict[str, Any]] = []
    staleness = pd.to_numeric(joined[config.staleness_column], errors="coerce")
    for rule in config.staleness_filters:
        frame = joined.copy()
        if rule.max_staleness_seconds is not None:
            frame = frame[staleness <= rule.max_staleness_seconds].copy()
        if frame.empty:
            rows.append(
                {
                    "filter_name": rule.name,
                    "max_staleness_seconds": rule.max_staleness_seconds,
                    "model_name": None,
                    "horizon_name": None,
                    "input_row_count": int(len(joined)),
                    "row_count": 0,
                    "excluded_row_count": int(len(joined)),
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
                    "max_staleness_seconds": rule.max_staleness_seconds,
                    "input_row_count": int(len(joined)),
                    "excluded_row_count": int(len(joined) - len(frame)),
                },
            ).to_dict(orient="records")
        )
    return pd.DataFrame(rows)


def weighting_sensitivity_diagnostics(
    joined: pd.DataFrame,
    config: RobustnessConfig,
) -> pd.DataFrame:
    """Return equal-contract, equal-family, and explicit trade-weighted metrics."""

    rows: list[dict[str, Any]] = []
    for mode in config.weighting_sensitivity.modes:
        if mode == "equal_contract":
            rows.extend(
                _metric_rows(
                    joined,
                    config,
                    [config.model_column, config.horizon_column],
                    extra_columns={
                        "weight_column": None,
                        "weighting_status": "primary_estimand_recomputed_as_robustness",
                    },
                ).to_dict(orient="records")
            )
            continue
        if mode == "equal_event_family":
            _require_columns(
                joined,
                [config.event_family_column],
                "equal-event-family weighting diagnostics",
            )
            rows.extend(
                _weighted_metric_rows(
                    joined,
                    config,
                    [config.model_column, config.horizon_column],
                    aggregation_mode="equal_event_family",
                    weight_column=None,
                    extra_columns={
                        "weight_column": config.event_family_column,
                        "weighting_status": "non_confirmatory_equal_event_family",
                    },
                ).to_dict(orient="records")
            )
            continue
        if mode == "trade_weighted":
            weight_column = (
                config.weighting_sensitivity.trade_weight_column
                or config.trade_weight_column
                or config.cumulative_volume_column
            )
            _require_columns(joined, [weight_column], "trade-weighted diagnostics")
            rows.extend(
                _weighted_metric_rows(
                    joined,
                    config,
                    [config.model_column, config.horizon_column],
                    aggregation_mode="trade_weighted",
                    weight_column=weight_column,
                    extra_columns={
                        "weight_column": weight_column,
                        "weighting_status": "non_confirmatory_trade_weighted_robustness",
                    },
                ).to_dict(orient="records")
            )
            continue
        raise RobustnessError(f"unknown weighting sensitivity mode: {mode}")
    return pd.DataFrame(rows)


def event_family_exclusion_sensitivity(
    joined: pd.DataFrame,
    config: RobustnessConfig,
) -> pd.DataFrame:
    """Return metrics with overlapping fit/test event families excluded."""

    if not config.event_family_purging.enabled:
        return pd.DataFrame(
            [
                {
                    "policy_name": "drop_overlapping_event_families",
                    "status": "not_applicable",
                    "reason": "event-family purging disabled by config",
                    "analysis_label": config.analysis_label,
                    "non_confirmatory": True,
                }
            ]
        )
    _require_columns(
        joined,
        ["fold_id", config.event_family_column],
        "event-family exclusion diagnostics",
    )
    if not config.splits_path.exists():
        raise RobustnessError(
            f"missing split assignments for event-family purging: {config.splits_path}"
        )
    splits = pd.read_parquet(config.splits_path)
    _require_columns(
        splits,
        ["fold_id", "split", "row_id"],
        "event-family purging split assignments",
    )
    if config.event_family_column not in splits.columns:
        panel = _load_panel(config)
        panel = panel[[config.row_id_column, config.event_family_column]]
        splits = splits.merge(panel, on=config.row_id_column, how="left", validate="many_to_one")
    _require_columns(
        splits,
        ["fold_id", "split", config.event_family_column],
        "event-family purging split assignments",
    )
    overlap_pairs = _overlapping_fold_families(splits, config)
    joined_with_overlap = joined.copy()
    if overlap_pairs.empty:
        joined_with_overlap["_event_family_overlap"] = False
    else:
        marker = overlap_pairs.assign(_event_family_overlap=True)
        joined_with_overlap = joined_with_overlap.merge(
            marker,
            on=["fold_id", config.event_family_column],
            how="left",
            validate="many_to_one",
        )
        joined_with_overlap["_event_family_overlap"] = joined_with_overlap[
            "_event_family_overlap"
        ].fillna(False).astype(bool)

    rows: list[dict[str, Any]] = []
    for policy_name, frame in (
        ("report_only_all_test_rows", joined_with_overlap),
        (
            "drop_overlapping_event_families",
            joined_with_overlap[~joined_with_overlap["_event_family_overlap"]].copy(),
        ),
    ):
        if frame.empty:
            rows.append(
                {
                    "policy_name": policy_name,
                    "model_name": None,
                    "horizon_name": None,
                    "input_row_count": int(len(joined_with_overlap)),
                    "row_count": 0,
                    "excluded_row_count": int(len(joined_with_overlap)),
                    "overlap_family_count": int(len(overlap_pairs)),
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
                    "policy_name": policy_name,
                    "input_row_count": int(len(joined_with_overlap)),
                    "excluded_row_count": int(len(joined_with_overlap) - len(frame)),
                    "overlap_family_count": int(len(overlap_pairs)),
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
        sports_mask = pd.Series(False, index=joined.index)
        if rule.exclude_sports is not None:
            if config.is_sports_column not in joined.columns:
                rows.append(
                    {
                        "rule_name": rule.name,
                        "status": "not_applicable",
                        "reason": f"missing_{config.is_sports_column}",
                        "input_row_count": int(len(joined)),
                        "output_row_count": 0,
                        "excluded_row_count": 0,
                        "analysis_label": config.analysis_label,
                        "non_confirmatory": True,
                    }
                )
                continue
            sports_mask = joined[config.is_sports_column].fillna(False).astype(bool)
            if not rule.exclude_sports:
                sports_mask = ~sports_mask
        ambiguous_mask = pd.Series(False, index=joined.index)
        if rule.exclude_ambiguous:
            if config.taxonomy_ambiguous_column not in joined.columns:
                rows.append(
                    {
                        "rule_name": rule.name,
                        "status": "not_applicable",
                        "reason": f"missing_{config.taxonomy_ambiguous_column}",
                        "input_row_count": int(len(joined)),
                        "output_row_count": 0,
                        "excluded_row_count": 0,
                        "analysis_label": config.analysis_label,
                        "non_confirmatory": True,
                    }
                )
                continue
            ambiguous_mask = joined[config.taxonomy_ambiguous_column].fillna(False).astype(bool)
        confidence_mask = pd.Series(False, index=joined.index)
        if rule.allowed_taxonomy_confidence:
            if config.taxonomy_confidence_column not in joined.columns:
                rows.append(
                    {
                        "rule_name": rule.name,
                        "status": "not_applicable",
                        "reason": f"missing_{config.taxonomy_confidence_column}",
                        "input_row_count": int(len(joined)),
                        "output_row_count": 0,
                        "excluded_row_count": 0,
                        "analysis_label": config.analysis_label,
                        "non_confirmatory": True,
                    }
                )
                continue
            confidence = joined[config.taxonomy_confidence_column].fillna("unknown").astype(str)
            confidence_mask = ~confidence.isin(rule.allowed_taxonomy_confidence)
        exclusion_mask = (
            domain_mask | category_mask | sports_mask | ambiguous_mask | confidence_mask
        )
        frame = joined[~exclusion_mask].copy()
        if frame.empty:
            rows.append(
                {
                    "rule_name": rule.name,
                    "status": "empty_after_filter",
                    "input_row_count": int(len(joined)),
                    "output_row_count": 0,
                    "excluded_row_count": int(exclusion_mask.sum()),
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
                    "rule_name": rule.name,
                    "status": "computed",
                    "input_row_count": int(len(joined)),
                    "output_row_count": int(len(frame)),
                    "excluded_row_count": int(exclusion_mask.sum()),
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


def full_snapshot_variant_runs(config: RobustnessConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run full downstream snapshot variants and return run and metric summaries."""

    config.full_snapshot_variant_output_dir.mkdir(parents=True, exist_ok=True)
    config.full_snapshot_variant_processed_dir.mkdir(parents=True, exist_ok=True)
    run_rows: list[dict[str, Any]] = []
    metric_rows: list[pd.DataFrame] = []
    for variant in config.full_snapshot_variants:
        processed_dir = config.full_snapshot_variant_processed_dir / variant.name
        artifact_dir = config.full_snapshot_variant_output_dir / variant.name
        processed_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        commands = full_snapshot_variant_commands(config, variant, processed_dir, artifact_dir)
        command_log = artifact_dir / "commands.json"
        command_log.write_text(json.dumps(commands, indent=2), encoding="utf-8")
        status = "completed"
        failed_stage = None
        returncode = 0
        stderr_tail = ""
        for stage in commands:
            completed = subprocess.run(
                stage["cmd"],
                check=False,
                text=True,
                capture_output=True,
            )
            if completed.returncode != 0:
                status = "failed"
                failed_stage = stage["name"]
                returncode = int(completed.returncode)
                stderr_tail = completed.stderr[-4000:]
                break
        summary_path = processed_dir / "contract_horizon_panel_summary.json"
        walkforward_summary_path = artifact_dir / "walkforward" / "summary.json"
        edge_summary_path = artifact_dir / "edge_sim" / "summary.json"
        row: dict[str, Any] = {
            "variant_name": variant.name,
            "status": status,
            "failed_stage": failed_stage,
            "returncode": returncode,
            "stderr": stderr_tail,
            "processed_dir": str(processed_dir),
            "artifact_dir": str(artifact_dir),
            "commands_path": str(command_log),
            "snapshot_methods": ",".join(variant.snapshot_methods),
            "vwap_window": variant.vwap_window,
            "max_staleness": variant.max_staleness,
            "limit_contracts": _variant_limit_contracts(config, variant),
            "analysis_label": config.analysis_label,
            "non_confirmatory": True,
        }
        if summary_path.exists():
            snapshot_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            row["snapshot_row_count"] = int(snapshot_summary.get("row_count", 0))
            row["snapshot_method_counts_json"] = json.dumps(
                snapshot_summary.get("snapshot_method_counts", {}),
                sort_keys=True,
            )
        if walkforward_summary_path.exists():
            walkforward_summary = json.loads(walkforward_summary_path.read_text(encoding="utf-8"))
            row["prediction_row_count"] = int(
                walkforward_summary.get("prediction_row_count", 0)
            )
        if edge_summary_path.exists():
            edge_summary = json.loads(edge_summary_path.read_text(encoding="utf-8"))
            row["edge_candidate_row_count"] = int(edge_summary.get("candidate_row_count", 0))
        run_rows.append(row)

        aggregate_path = artifact_dir / "walkforward" / "aggregate_metrics.parquet"
        if aggregate_path.exists():
            metrics = pd.read_parquet(aggregate_path)
            metrics.insert(0, "variant_name", variant.name)
            metrics["variant_status"] = status
            metrics["analysis_label"] = config.analysis_label
            metrics["non_confirmatory"] = True
            metric_rows.append(metrics)
    metrics_frame = (
        pd.concat(metric_rows, ignore_index=True)
        if metric_rows
        else pd.DataFrame(
            [
                {
                    "status": "not_available",
                    "reason": "no full snapshot variant aggregate metrics were written",
                    "analysis_label": config.analysis_label,
                    "non_confirmatory": True,
                }
            ]
        )
    )
    return pd.DataFrame(run_rows), metrics_frame


def full_snapshot_variant_commands(
    config: RobustnessConfig,
    variant: FullSnapshotVariant,
    processed_dir: Path,
    artifact_dir: Path,
) -> list[dict[str, Any]]:
    """Return the command chain for one full snapshot variant."""

    snapshot_panel = processed_dir / "contract_horizon_panel.parquet"
    snapshot_summary = processed_dir / "contract_horizon_panel_summary.json"
    taxonomy_panel = processed_dir / "contract_horizon_panel_taxonomy.parquet"
    taxonomy_audit = processed_dir / "contract_horizon_taxonomy_audit.parquet"
    taxonomy_examples = processed_dir / "contract_horizon_taxonomy_examples.parquet"
    taxonomy_summary = processed_dir / "contract_horizon_taxonomy_summary.json"
    feature_panel = processed_dir / "modeling_panel.parquet"
    feature_summary = processed_dir / "modeling_panel_summary.json"
    splits = processed_dir / "walkforward_splits.parquet"
    integrity = processed_dir / "walkforward_split_integrity.parquet"
    split_summary = processed_dir / "walkforward_split_summary.json"
    walkforward_dir = artifact_dir / "walkforward"
    inference_dir = artifact_dir / "inference"
    edge_dir = artifact_dir / "edge_sim"
    decomposition_dir = artifact_dir / "decomposition"

    snapshot_cmd = [
        sys.executable,
        "scripts/build_snapshot_panel.py",
        "--config",
        str(config.sampling_config_path),
        "--contracts",
        str(config.contracts_path),
        "--price-observations",
        str(config.price_observations_path),
        "--output",
        str(snapshot_panel),
        "--summary",
        str(snapshot_summary),
        "--snapshot-methods",
        ",".join(variant.snapshot_methods),
    ]
    if variant.vwap_window:
        snapshot_cmd.extend(["--vwap-window", variant.vwap_window])
    if variant.max_staleness:
        snapshot_cmd.extend(["--max-staleness", variant.max_staleness])
    limit_contracts = _variant_limit_contracts(config, variant)
    if limit_contracts is not None:
        snapshot_cmd.extend(["--limit-contracts", str(limit_contracts)])

    commands = [
        {"name": "snapshot", "cmd": snapshot_cmd},
        {
            "name": "taxonomy",
            "cmd": [
                sys.executable,
                "scripts/build_taxonomy_panel.py",
                "--config",
                str(config.taxonomy_config_path),
                "--panel",
                str(snapshot_panel),
                "--contracts",
                str(config.contracts_path),
                "--output",
                str(taxonomy_panel),
                "--audit",
                str(taxonomy_audit),
                "--summary",
                str(taxonomy_summary),
                "--examples",
                str(taxonomy_examples),
            ],
        },
        {
            "name": "features",
            "cmd": [
                sys.executable,
                "scripts/build_feature_panel.py",
                "--config",
                str(config.features_config_path),
                "--panel",
                str(taxonomy_panel),
                "--price-observations",
                str(config.price_observations_path),
                "--contracts",
                str(config.contracts_path),
                "--output",
                str(feature_panel),
                "--summary",
                str(feature_summary),
            ],
        },
        {
            "name": "splits",
            "cmd": [
                sys.executable,
                "scripts/build_walkforward_splits.py",
                "--config",
                str(config.validation_config_path),
                "--panel",
                str(feature_panel),
                "--splits",
                str(splits),
                "--integrity",
                str(integrity),
                "--summary",
                str(split_summary),
            ],
        },
    ]
    if not config.full_snapshot_variant_run_downstream:
        return commands
    commands.extend(
        [
            {
                "name": "walkforward",
                "cmd": [
                    sys.executable,
                    "scripts/fit_walkforward.py",
                    "--config",
                    str(config.models_config_path),
                    "--panel",
                    str(feature_panel),
                    "--splits",
                    str(splits),
                    "--artifact-dir",
                    str(walkforward_dir),
                ],
            },
            {
                "name": "inference",
                "cmd": _with_optional_int_arg(
                    [
                        sys.executable,
                        "scripts/run_inference.py",
                        "--config",
                        str(config.inference_config_path),
                        "--predictions",
                        str(walkforward_dir / "predictions.parquet"),
                        "--panel",
                        str(feature_panel),
                        "--artifact-dir",
                        str(inference_dir),
                    ],
                    "--bootstrap-iterations",
                    config.full_snapshot_variant_inference_bootstrap_iterations,
                ),
            },
            {
                "name": "edge",
                "cmd": [
                    sys.executable,
                    "scripts/run_edge_sim.py",
                    "--config",
                    str(config.backtest_config_path),
                    "--predictions",
                    str(walkforward_dir / "predictions.parquet"),
                    "--panel",
                    str(feature_panel),
                    "--artifact-dir",
                    str(edge_dir),
                ],
            },
            {
                "name": "decomposition",
                "cmd": [
                    sys.executable,
                    "scripts/evaluate_decomposition.py",
                    "--config",
                    str(config.decomposition_config_path),
                    "--predictions",
                    str(walkforward_dir / "predictions.parquet"),
                    "--artifact-dir",
                    str(decomposition_dir),
                ],
            },
        ]
    )
    return commands


def effective_robustness_config(config: RobustnessConfig) -> dict[str, Any]:
    """Return a JSON-serializable effective robustness config."""

    return {
        "inputs": {
            "panel_path": str(config.panel_path),
            "walkforward_artifact_dir": str(config.walkforward_artifact_dir),
            "edge_artifact_dir": str(config.edge_artifact_dir),
            "splits_path": str(config.splits_path),
            "backtest_config_path": str(config.backtest_config_path),
            "sampling_config_path": str(config.sampling_config_path),
            "taxonomy_config_path": str(config.taxonomy_config_path),
            "features_config_path": str(config.features_config_path),
            "validation_config_path": str(config.validation_config_path),
            "models_config_path": str(config.models_config_path),
            "inference_config_path": str(config.inference_config_path),
            "decomposition_config_path": str(config.decomposition_config_path),
        },
        "outputs": {
            "artifact_dir": str(config.artifact_dir),
            "table_dir": str(config.table_dir),
        },
        "robustness": {
            "analysis_label": config.analysis_label,
            "limit_rows": config.limit_rows,
            "liquidity_filters": [asdict(item) for item in config.liquidity_filters],
            "staleness_filters": [asdict(item) for item in config.staleness_filters],
            "weighting_sensitivity": asdict(config.weighting_sensitivity),
            "event_family_purging": asdict(config.event_family_purging),
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
            "full_snapshot_variants_enabled": config.full_snapshot_variants_enabled,
            "full_snapshot_variant_output_dir": str(config.full_snapshot_variant_output_dir),
            "full_snapshot_variant_processed_dir": str(
                config.full_snapshot_variant_processed_dir
            ),
            "full_snapshot_variant_run_downstream": (
                config.full_snapshot_variant_run_downstream
            ),
            "full_snapshot_variant_limit_contracts": (
                config.full_snapshot_variant_limit_contracts
            ),
            "full_snapshot_variant_inference_bootstrap_iterations": (
                config.full_snapshot_variant_inference_bootstrap_iterations
            ),
            "full_snapshot_variants": [asdict(item) for item in config.full_snapshot_variants],
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


def _weighted_metric_rows(
    frame: pd.DataFrame,
    config: RobustnessConfig,
    group_columns: list[str],
    *,
    aggregation_mode: str,
    weight_column: str | None,
    extra_columns: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for values, group in frame.groupby(group_columns, dropna=False, observed=True):
        if not isinstance(values, tuple):
            values = (values,)
        probabilities = pd.to_numeric(group[config.probability_column], errors="raise")
        outcomes = pd.to_numeric(group[config.outcome_column], errors="raise")
        if aggregation_mode == "equal_event_family":
            family_sizes = group.groupby(config.event_family_column, observed=True)[
                config.event_family_column
            ].transform("size")
            weights = 1.0 / pd.to_numeric(family_sizes, errors="raise")
        elif aggregation_mode == "trade_weighted":
            if weight_column is None:
                raise RobustnessError("trade_weighted aggregation requires a weight column")
            weights = pd.to_numeric(group[weight_column], errors="coerce").fillna(0.0)
            weights = weights.where(weights > 0.0, 0.0)
        else:
            raise RobustnessError(f"unsupported weighted aggregation mode: {aggregation_mode}")
        total_weight = float(weights.sum())
        row = {column: value for column, value in zip(group_columns, values, strict=True)}
        row.update(extra_columns)
        if total_weight <= 0.0:
            row.update(
                {
                    "row_count": int(len(group)),
                    "family_count": int(group[config.event_family_column].nunique()),
                    "total_weight": total_weight,
                    "brier_score": None,
                    "log_loss": None,
                    "expected_calibration_error": None,
                    "calibration_intercept": None,
                    "calibration_slope": None,
                    "calibration_status": "zero_total_weight",
                    "empty_bin_count": None,
                    "sparse_bin_count": None,
                    "analysis_label": config.analysis_label,
                    "non_confirmatory": True,
                    "aggregation_mode": aggregation_mode,
                    "status": "zero_total_weight",
                }
            )
            rows.append(row)
            continue
        brier_losses = (probabilities - outcomes) ** 2
        log_losses = [
            log_loss([probability], [outcome], epsilon=config.log_loss_epsilon)
            for probability, outcome in zip(probabilities, outcomes, strict=True)
        ]
        ece, empty_bins, sparse_bins = _weighted_ece(
            probabilities,
            outcomes,
            weights,
            bin_count=config.reliability_bin_count,
            min_bin_count=config.reliability_min_bin_count,
        )
        row.update(
            {
                "row_count": int(len(group)),
                "family_count": int(group[config.event_family_column].nunique()),
                "total_weight": total_weight,
                "brier_score": float((brier_losses * weights).sum() / total_weight),
                "log_loss": float(
                    sum(loss * weight for loss, weight in zip(log_losses, weights, strict=True))
                    / total_weight
                ),
                "expected_calibration_error": ece,
                "calibration_intercept": None,
                "calibration_slope": None,
                "calibration_status": "not_computed_for_weighted_aggregation",
                "empty_bin_count": empty_bins,
                "sparse_bin_count": sparse_bins,
                "analysis_label": config.analysis_label,
                "non_confirmatory": True,
                "aggregation_mode": aggregation_mode,
                "status": "computed",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _weighted_ece(
    probabilities: pd.Series,
    outcomes: pd.Series,
    weights: pd.Series,
    *,
    bin_count: int,
    min_bin_count: int,
) -> tuple[float, int, int]:
    total_weight = float(weights.sum())
    ece = 0.0
    empty_bins = 0
    sparse_bins = 0
    for bin_index in range(bin_count):
        lower = bin_index / bin_count
        upper = (bin_index + 1) / bin_count
        if bin_index == bin_count - 1:
            mask = (probabilities >= lower) & (probabilities <= upper)
        else:
            mask = (probabilities >= lower) & (probabilities < upper)
        count = int(mask.sum())
        if count == 0:
            empty_bins += 1
            sparse_bins += 1 if min_bin_count > 0 else 0
            continue
        if count < min_bin_count:
            sparse_bins += 1
        bin_weights = weights[mask]
        bin_weight = float(bin_weights.sum())
        if bin_weight <= 0.0:
            continue
        mean_probability = float((probabilities[mask] * bin_weights).sum() / bin_weight)
        observed_frequency = float((outcomes[mask] * bin_weights).sum() / bin_weight)
        ece += (bin_weight / total_weight) * abs(mean_probability - observed_frequency)
    return float(ece), empty_bins, sparse_bins


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
            config.is_sports_column,
            config.taxonomy_confidence_column,
            config.taxonomy_ambiguous_column,
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
    allowed_modes = {"equal_contract", "equal_event_family", "trade_weighted"}
    unknown_modes = sorted(set(config.weighting_sensitivity.modes) - allowed_modes)
    if unknown_modes:
        raise RobustnessError(f"unknown weighting sensitivity modes: {unknown_modes}")
    if config.full_snapshot_variants_enabled and not config.full_snapshot_variants:
        raise RobustnessError("full snapshot variants are enabled but no variants are configured")


def _require_columns(frame: pd.DataFrame, columns: list[str], context: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise RobustnessError(f"{context} missing required columns: {missing}")


def _artifact_paths(artifact_dir: Path) -> dict[str, Path]:
    return {
        "snapshot_method_slices": artifact_dir / "snapshot_method_slices.parquet",
        "liquidity_filter_sensitivity": artifact_dir / "liquidity_filter_sensitivity.parquet",
        "staleness_filter_sensitivity": artifact_dir / "staleness_filter_sensitivity.parquet",
        "weighting_sensitivity": artifact_dir / "weighting_sensitivity.parquet",
        "event_family_exclusion_sensitivity": (
            artifact_dir / "event_family_exclusion_sensitivity.parquet"
        ),
        "domain_exclusion_status": artifact_dir / "domain_exclusion_status.parquet",
        "friction_assumption_sensitivity": artifact_dir / "friction_assumption_sensitivity.parquet",
        "snapshot_variant_runs": artifact_dir / "snapshot_variant_runs.parquet",
        "full_snapshot_variant_runs": artifact_dir / "full_snapshot_variant_runs.parquet",
        "full_snapshot_variant_metrics": artifact_dir / "full_snapshot_variant_metrics.parquet",
        "summary": artifact_dir / "summary.json",
    }


def _source_artifacts(config: RobustnessConfig) -> dict[str, str]:
    return {
        "panel": str(config.panel_path),
        "walkforward_predictions": str(config.walkforward_artifact_dir / "predictions.parquet"),
        "walkforward_splits": str(config.splits_path),
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
        "Snapshot-method slices are based on saved artifact rows; Phase 15 full snapshot "
        "variants are written separately from confirmatory artifacts.",
        "Trade-weighted outputs are non-confirmatory robustness diagnostics only; the primary "
        "estimand remains equal-contract.",
        "Event-family-purged outputs are sensitivity diagnostics and do not replace the "
        "primary report-only walk-forward policy.",
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


def _mapping_or_empty(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"robustness config key must be a mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"robustness config missing required key: {key}")
    return raw[key]


def _list_or_empty(raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = raw.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"robustness config key must be a list of mappings: {key}")
    return value


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


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    raise ValueError(f"expected optional bool-compatible value, got {type(value).__name__}")


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _variant_limit_contracts(
    config: RobustnessConfig,
    variant: FullSnapshotVariant,
) -> int | None:
    return (
        variant.limit_contracts
        if variant.limit_contracts is not None
        else config.full_snapshot_variant_limit_contracts
    )


def _with_optional_int_arg(
    cmd: list[str],
    flag: str,
    value: int | None,
) -> list[str]:
    if value is not None:
        cmd.extend([flag, str(value)])
    return cmd


def _overlapping_fold_families(
    splits: pd.DataFrame,
    config: RobustnessConfig,
) -> pd.DataFrame:
    fit = splits[splits["split"].astype(str).isin(config.event_family_purging.fit_splits)]
    test = splits[splits["split"].astype(str) == "test"]
    fit_pairs = fit[["fold_id", config.event_family_column]].drop_duplicates()
    test_pairs = test[["fold_id", config.event_family_column]].drop_duplicates()
    return fit_pairs.merge(
        test_pairs,
        on=["fold_id", config.event_family_column],
        how="inner",
        validate="many_to_many",
    ).drop_duplicates()
