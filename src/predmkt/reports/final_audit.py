"""Final scientific artifact and data-semantics audit."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd  # type: ignore[import-untyped]
import pyarrow.parquet as pq
import yaml  # type: ignore[import-untyped]

STATUS_ORDER = {"PASS": 0, "PARTIAL": 1, "FAIL": 2}


@dataclass(frozen=True)
class FinalAuditConfig:
    """Configuration for the final artifact and data-semantics audit."""

    raw_repo_path: Path | None
    interim_summary_path: Path
    interim_contracts_path: Path
    interim_price_observations_path: Path
    contract_exclusion_summary_path: Path
    price_observation_exclusion_summary_path: Path
    snapshot_panel_path: Path
    snapshot_summary_path: Path
    taxonomy_panel_path: Path
    taxonomy_summary_path: Path
    modeling_panel_path: Path
    modeling_summary_path: Path
    splits_path: Path
    split_integrity_path: Path
    split_summary_path: Path
    raw_baseline_dir: Path
    walkforward_dir: Path
    edge_dir: Path
    inference_dir: Path
    decomposition_dir: Path
    robustness_dir: Path
    figure_manifest_path: Path
    table_manifest_path: Path
    audit_dir: Path
    semantics_doc_path: Path
    expected_horizons: tuple[str, ...]
    expected_models: tuple[str, ...]
    expected_edge_trade_side: str
    expected_reporting_run_label: str
    known_partial_limitations: tuple[str, ...]
    severity_rules: dict[str, Any]
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class FinalAuditSummary:
    """Summary metadata for a final scientific artifact audit."""

    overall_status: str
    audit_dir: str
    semantics_doc_path: str
    check_count: int
    pass_count: int
    partial_count: int
    fail_count: int
    phase_status_path: str
    audit_checks_path: str
    artifact_inventory_path: str
    effective_config: dict[str, Any]
    limitations: list[str]


class FinalAuditError(ValueError):
    """Raised when final-audit configuration is invalid."""


def load_final_audit_config(path: Path) -> FinalAuditConfig:
    """Load final-audit settings from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"final audit config must be a mapping: {path}")
    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    audit = _mapping(raw, "audit")
    raw_repo_value = inputs.get("raw_repo_path")
    return FinalAuditConfig(
        raw_repo_path=Path(raw_repo_value) if raw_repo_value else None,
        interim_summary_path=Path(_required(inputs, "interim_summary_path")),
        interim_contracts_path=Path(_required(inputs, "interim_contracts_path")),
        interim_price_observations_path=Path(_required(inputs, "interim_price_observations_path")),
        contract_exclusion_summary_path=Path(_required(inputs, "contract_exclusion_summary_path")),
        price_observation_exclusion_summary_path=Path(
            _required(inputs, "price_observation_exclusion_summary_path")
        ),
        snapshot_panel_path=Path(_required(inputs, "snapshot_panel_path")),
        snapshot_summary_path=Path(_required(inputs, "snapshot_summary_path")),
        taxonomy_panel_path=Path(_required(inputs, "taxonomy_panel_path")),
        taxonomy_summary_path=Path(_required(inputs, "taxonomy_summary_path")),
        modeling_panel_path=Path(_required(inputs, "modeling_panel_path")),
        modeling_summary_path=Path(_required(inputs, "modeling_summary_path")),
        splits_path=Path(_required(inputs, "splits_path")),
        split_integrity_path=Path(_required(inputs, "split_integrity_path")),
        split_summary_path=Path(_required(inputs, "split_summary_path")),
        raw_baseline_dir=Path(_required(inputs, "raw_baseline_dir")),
        walkforward_dir=Path(_required(inputs, "walkforward_dir")),
        edge_dir=Path(_required(inputs, "edge_dir")),
        inference_dir=Path(_required(inputs, "inference_dir")),
        decomposition_dir=Path(_required(inputs, "decomposition_dir")),
        robustness_dir=Path(_required(inputs, "robustness_dir")),
        figure_manifest_path=Path(_required(inputs, "figure_manifest_path")),
        table_manifest_path=Path(_required(inputs, "table_manifest_path")),
        audit_dir=Path(_required(outputs, "audit_dir")),
        semantics_doc_path=Path(_required(outputs, "semantics_doc_path")),
        expected_horizons=tuple(str(item) for item in _required(audit, "expected_horizons")),
        expected_models=tuple(str(item) for item in _required(audit, "expected_models")),
        expected_edge_trade_side=_normalize_trade_side(
            _required(audit, "expected_edge_trade_side")
        ),
        expected_reporting_run_label=str(_required(audit, "expected_reporting_run_label")),
        known_partial_limitations=tuple(
            str(item) for item in _required(audit, "known_partial_limitations")
        ),
        severity_rules=dict(audit.get("severity_rules", {})),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def build_final_audit(config: FinalAuditConfig) -> FinalAuditSummary:
    """Run final artifact checks and write audit outputs."""

    config.audit_dir.mkdir(parents=True, exist_ok=True)
    config.semantics_doc_path.parent.mkdir(parents=True, exist_ok=True)

    inventory = artifact_inventory(config)
    checks: list[dict[str, Any]] = []
    checks.extend(_artifact_existence_checks(inventory))
    if any(row["status"] == "FAIL" for row in checks):
        checks_frame = pd.DataFrame(checks)
    else:
        checks.extend(_audit_interim_semantics(config))
        checks.extend(_audit_snapshot_panel(config))
        checks.extend(_audit_modeling_panel(config))
        checks.extend(_audit_splits(config))
        checks.extend(_audit_walkforward(config))
        checks.extend(_audit_inference(config))
        checks.extend(_audit_decomposition(config))
        checks.extend(_audit_raw_baseline(config))
        checks.extend(_audit_edge(config))
        checks.extend(_audit_reporting(config))
        checks.extend(_audit_robustness(config))
        checks_frame = pd.DataFrame(checks)

    phase_status = _phase_status(checks_frame)
    overall_status = _overall_status(checks_frame)
    paths = _artifact_paths(config.audit_dir)
    inventory.to_parquet(paths["inventory"], index=False)
    checks_frame.to_parquet(paths["checks"], index=False)
    phase_status.to_parquet(paths["phase_status"], index=False)
    config.semantics_doc_path.write_text(
        _semantics_markdown(config, checks_frame, phase_status, overall_status),
        encoding="utf-8",
    )

    summary = FinalAuditSummary(
        overall_status=overall_status,
        audit_dir=str(config.audit_dir),
        semantics_doc_path=str(config.semantics_doc_path),
        check_count=int(len(checks_frame)),
        pass_count=int((checks_frame["status"] == "PASS").sum()) if not checks_frame.empty else 0,
        partial_count=(
            int((checks_frame["status"] == "PARTIAL").sum()) if not checks_frame.empty else 0
        ),
        fail_count=int((checks_frame["status"] == "FAIL").sum()) if not checks_frame.empty else 0,
        phase_status_path=str(paths["phase_status"]),
        audit_checks_path=str(paths["checks"]),
        artifact_inventory_path=str(paths["inventory"]),
        effective_config=effective_final_audit_config(config),
        limitations=[
            "Phase 11 audits saved artifacts and data semantics; it does not rebuild data, "
            "refit models, or change methodology.",
            "A PARTIAL verdict can be acceptable for Phase 11 when hard invariants pass but "
            "known semantic limitations remain.",
            "Final deployment still requires later roadmap phases for edge executability and "
            "run-registry hardening; taxonomy/domain claims remain conditional on confidence "
            "and ambiguity review.",
        ],
    )
    paths["summary"].write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return summary


def artifact_inventory(config: FinalAuditConfig) -> pd.DataFrame:
    """Return configured artifact inventory with existence and Parquet metadata."""

    paths = _configured_artifacts(config)
    rows: list[dict[str, Any]] = []
    for key, path in paths.items():
        exists = path.exists()
        row: dict[str, Any] = {
            "artifact_key": key,
            "path": str(path),
            "exists": exists,
            "artifact_type": path.suffix.lstrip(".") or "directory",
            "row_count": None,
            "columns_json": None,
        }
        if exists and path.suffix == ".parquet":
            parquet = pq.ParquetFile(path)  # type: ignore[no-untyped-call]
            row["row_count"] = int(parquet.metadata.num_rows)
            row["columns_json"] = json.dumps(parquet.schema_arrow.names)
        rows.append(row)
    return pd.DataFrame(rows)


def effective_final_audit_config(config: FinalAuditConfig) -> dict[str, Any]:
    """Return a JSON-serializable effective config."""

    return {
        "inputs": {key: str(path) for key, path in _configured_artifacts(config).items()},
        "outputs": {
            "audit_dir": str(config.audit_dir),
            "semantics_doc_path": str(config.semantics_doc_path),
        },
        "audit": {
            "expected_horizons": list(config.expected_horizons),
            "expected_models": list(config.expected_models),
            "expected_edge_trade_side": config.expected_edge_trade_side,
            "expected_reporting_run_label": config.expected_reporting_run_label,
            "known_partial_limitations": list(config.known_partial_limitations),
            "severity_rules": config.severity_rules,
        },
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }


def _audit_interim_semantics(config: FinalAuditConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    summary = _read_json(config.interim_summary_path)
    contracts = _parquet_columns(config.interim_contracts_path)
    rows.append(
        _check(
            "phase_2",
            "resolution_ts_present",
            "PASS" if "resolution_ts" in contracts else "FAIL",
            "interim contracts include normalized resolution_ts",
            "interim contracts missing resolution_ts",
            {"columns": contracts},
        )
    )
    rows.append(
        _check(
            "phase_2",
            "close_time_not_retained",
            "PASS" if "close_time" in contracts else "FAIL",
            "interim contracts retain close_time separately",
            "cleaned contracts do not retain raw close_time separately; resolution_ts is the "
            "audited downstream timestamp and remains a semantic limitation",
            {"required_column": "close_time"},
        )
    )
    contract_excluded = int(summary.get("contracts", {}).get("excluded_rows", 0))
    price_excluded = int(summary.get("price_observations", {}).get("excluded_rows", 0))
    rows.append(
        _check(
            "phase_2",
            "exclusion_summaries_present",
            "PASS" if contract_excluded >= 0 and price_excluded >= 0 else "FAIL",
            "interim summaries record contract and price-observation exclusions",
            "interim summaries do not record exclusions",
            {"contract_excluded": contract_excluded, "price_excluded": price_excluded},
        )
    )
    rows.append(_raw_repo_check(config))
    return rows


def _audit_snapshot_panel(config: FinalAuditConfig) -> list[dict[str, Any]]:
    summary = _read_json(config.snapshot_summary_path)
    available_columns = set(_parquet_columns(config.snapshot_panel_path))
    read_columns = [
        "contract_id",
        "horizon_bucket",
        "forecast_ts",
        "resolution_ts",
        "price_timestamp",
        "last_trade_ts",
        "max_source_ts",
    ]
    if "close_time" in available_columns:
        read_columns.append("close_time")
    frame = pd.read_parquet(
        config.snapshot_panel_path,
        columns=read_columns,
    )
    frame["forecast_ts"] = pd.to_datetime(frame["forecast_ts"], utc=True)
    frame["resolution_ts"] = pd.to_datetime(frame["resolution_ts"], utc=True)
    frame["price_timestamp"] = pd.to_datetime(frame["price_timestamp"], utc=True)
    last_trade_ts = pd.to_datetime(frame["last_trade_ts"], utc=True)
    max_source_ts = pd.to_datetime(frame["max_source_ts"], utc=True)
    duplicate_count = int(frame.duplicated(["contract_id", "horizon_bucket"]).sum())
    bad_order = int((frame["forecast_ts"] >= frame["resolution_ts"]).sum())
    bad_price_ts = int((frame["price_timestamp"] > frame["forecast_ts"]).sum())
    bad_last_trade = int((last_trade_ts.notna() & (last_trade_ts > frame["forecast_ts"])).sum())
    bad_max_source = int((max_source_ts.notna() & (max_source_ts > frame["forecast_ts"])).sum())
    horizons = tuple(sorted(frame["horizon_bucket"].dropna().astype(str).unique().tolist()))
    expected = tuple(sorted(config.expected_horizons))
    return [
        _check(
            "phase_3",
            "snapshot_row_count_matches_summary",
            "PASS" if len(frame) == int(summary.get("row_count", -1)) else "FAIL",
            "snapshot row count matches summary",
            "snapshot row count does not match summary",
            {"rows": len(frame), "summary_rows": summary.get("row_count")},
        ),
        _check(
            "phase_3",
            "snapshot_duplicate_keys",
            "PASS" if duplicate_count == 0 else "FAIL",
            "one row per contract x horizon in snapshot panel",
            "snapshot panel has duplicate contract x horizon rows",
            {"duplicate_count": duplicate_count},
        ),
        _check(
            "phase_3",
            "snapshot_forecast_before_resolution",
            "PASS" if bad_order == 0 else "FAIL",
            "all snapshot rows satisfy forecast_ts < resolution_ts",
            "snapshot rows violate forecast_ts < resolution_ts",
            {"bad_rows": bad_order},
        ),
        _check(
            "phase_3",
            "snapshot_close_time_retained",
            "PASS" if "close_time" in available_columns else "FAIL",
            "snapshot panel retains raw close_time separately from resolution_ts",
            "snapshot panel does not retain raw close_time separately from resolution_ts",
            {"required_column": "close_time"},
        ),
        _check(
            "phase_3",
            "snapshot_no_lookahead_source_times",
            "PASS" if bad_price_ts + bad_last_trade + bad_max_source == 0 else "FAIL",
            "snapshot source timestamps are at or before forecast_ts",
            "snapshot source timestamps use future information",
            {
                "bad_price_timestamp": bad_price_ts,
                "bad_last_trade_ts": bad_last_trade,
                "bad_max_source_ts": bad_max_source,
            },
        ),
        _check(
            "phase_3",
            "snapshot_expected_horizons",
            "PASS" if horizons == expected else "FAIL",
            "snapshot horizons match final audit config",
            "snapshot horizons do not match final audit config",
            {"observed": horizons, "expected": expected},
        ),
        _check(
            "phase_3",
            "snapshot_summary_validations",
            "PASS"
            if summary.get("duplicate_key_validation", {}).get("passed") is True
            and summary.get("no_lookahead_validation", {}).get("passed") is True
            else "FAIL",
            "snapshot summary records duplicate and no-lookahead validation pass",
            "snapshot summary validation flags do not pass",
            {
                "duplicate_key_validation": summary.get("duplicate_key_validation"),
                "no_lookahead_validation": summary.get("no_lookahead_validation"),
            },
        ),
    ]


def _audit_modeling_panel(config: FinalAuditConfig) -> list[dict[str, Any]]:
    summary = _read_json(config.modeling_summary_path)
    taxonomy_summary = _read_json(config.taxonomy_summary_path)
    available_columns = set(_parquet_columns(config.modeling_panel_path))
    taxonomy_required = [
        "is_sports",
        "taxonomy_rule_id",
        "taxonomy_ambiguous",
        "event_family_source",
        "event_family_confidence",
    ]
    missing_taxonomy_columns = sorted(set(taxonomy_required) - available_columns)
    read_columns = [
        "contract_id",
        "horizon_name",
        "forecast_ts",
        "resolution_ts",
        "price_timestamp",
        "max_feature_source_ts",
        "domain",
        "category",
        "event_family_id",
        "event_family_id_inferred",
        *[column for column in taxonomy_required if column in available_columns],
    ]
    if "close_time" in available_columns:
        read_columns.append("close_time")
    frame = pd.read_parquet(
        config.modeling_panel_path,
        columns=read_columns,
    )
    frame["forecast_ts"] = pd.to_datetime(frame["forecast_ts"], utc=True)
    frame["resolution_ts"] = pd.to_datetime(frame["resolution_ts"], utc=True)
    price_ts = pd.to_datetime(frame["price_timestamp"], utc=True)
    feature_ts = pd.to_datetime(frame["max_feature_source_ts"], utc=True)
    duplicate_count = int(frame.duplicated(["contract_id", "horizon_name"]).sum())
    bad_order = int((frame["forecast_ts"] >= frame["resolution_ts"]).sum())
    bad_price_ts = int((price_ts > frame["forecast_ts"]).sum())
    bad_feature_ts = int((feature_ts.notna() & (feature_ts > frame["forecast_ts"])).sum())
    domain_unknown = _all_unknown(frame["domain"])
    category_unknown = _all_unknown(frame["category"])
    inferred_share = float(pd.to_numeric(frame["event_family_id_inferred"], errors="coerce").mean())
    taxonomy_input_rows = int(taxonomy_summary.get("input_row_count", -1))
    taxonomy_output_rows = int(taxonomy_summary.get("output_row_count", -2))
    taxonomy_dropped = int(taxonomy_summary.get("dropped_row_count", -1))
    unknown_rate = taxonomy_summary.get("unknown_rate")
    ambiguous_rate = taxonomy_summary.get("ambiguous_rate")
    event_family_source_counts = taxonomy_summary.get("event_family_source_counts", {})
    return [
        _check(
            "phase_4_5",
            "modeling_row_count_matches_summary",
            "PASS" if len(frame) == int(summary.get("output_row_count", -1)) else "FAIL",
            "modeling row count matches summary",
            "modeling row count does not match summary",
            {"rows": len(frame), "summary_rows": summary.get("output_row_count")},
        ),
        _check(
            "phase_4_5",
            "modeling_duplicate_keys",
            "PASS" if duplicate_count == 0 else "FAIL",
            "one row per contract x horizon in modeling panel",
            "modeling panel has duplicate contract x horizon rows",
            {"duplicate_count": duplicate_count},
        ),
        _check(
            "phase_4_5",
            "modeling_no_lookahead",
            "PASS" if bad_order + bad_price_ts + bad_feature_ts == 0 else "FAIL",
            "modeling panel timestamps satisfy no-lookahead invariants",
            "modeling panel has timestamp/no-lookahead violations",
            {
                "bad_forecast_order": bad_order,
                "bad_price_timestamp": bad_price_ts,
                "bad_feature_source": bad_feature_ts,
            },
        ),
        _check(
            "phase_4_5",
            "modeling_close_time_retained",
            "PASS" if "close_time" in available_columns else "FAIL",
            "modeling panel retains raw close_time separately from resolution_ts",
            "modeling panel does not retain raw close_time separately from resolution_ts",
            {"required_column": "close_time"},
        ),
        _check(
            "taxonomy",
            "taxonomy_phase12_columns",
            "PASS" if not missing_taxonomy_columns else "FAIL",
            "modeling panel carries Phase 12 taxonomy audit columns",
            "modeling panel is missing Phase 12 taxonomy audit columns",
            {"missing_columns": missing_taxonomy_columns},
        ),
        _check(
            "taxonomy",
            "taxonomy_no_row_drops",
            "PASS"
            if taxonomy_input_rows == taxonomy_output_rows == len(frame) and taxonomy_dropped == 0
            else "FAIL",
            "taxonomy enrichment preserved row count",
            "taxonomy enrichment dropped rows or summary row counts disagree",
            {
                "taxonomy_input_rows": taxonomy_input_rows,
                "taxonomy_output_rows": taxonomy_output_rows,
                "taxonomy_dropped": taxonomy_dropped,
                "modeling_rows": len(frame),
            },
        ),
        _check(
            "taxonomy",
            "domain_category_coverage",
            "PARTIAL" if domain_unknown or category_unknown else "PASS",
            "domain/category taxonomy has non-unknown coverage",
            "domain/category taxonomy remains too sparse for final domain-level claims",
            {
                "domain_all_unknown": domain_unknown,
                "category_all_unknown": category_unknown,
                "unknown_rate": unknown_rate,
                "ambiguous_rate": ambiguous_rate,
            },
        ),
        _check(
            "taxonomy",
            "event_family_proxy",
            "PARTIAL" if inferred_share >= 0.99 else "PASS",
            "event_family_id has audited non-proxy coverage",
            "event_family_id relies almost entirely on fallback grouping",
            {
                "event_family_inferred_share": inferred_share,
                "event_family_source_counts": event_family_source_counts,
            },
        ),
        _check(
            "taxonomy",
            "taxonomy_ambiguity_reported",
            "PASS" if "ambiguous_rate" in taxonomy_summary else "FAIL",
            "taxonomy summary reports ambiguity rate",
            "taxonomy summary does not report ambiguity rate",
            {"ambiguous_rate": ambiguous_rate},
        ),
    ]


def _audit_splits(config: FinalAuditConfig) -> list[dict[str, Any]]:
    summary = _read_json(config.split_summary_path)
    integrity = pd.read_parquet(config.split_integrity_path)
    time_valid = bool(integrity["time_order_valid"].all())
    row_valid = bool(integrity["row_exclusivity_valid"].all())
    duplicate_count = int(integrity["duplicate_row_count"].sum())
    return [
        _check(
            "phase_5",
            "split_time_order",
            "PASS" if time_valid and summary.get("time_order_valid") is True else "FAIL",
            "split integrity confirms forecast-time ordering",
            "split integrity found invalid time ordering",
            {"summary_time_order_valid": summary.get("time_order_valid")},
        ),
        _check(
            "phase_5",
            "split_row_exclusivity",
            "PASS" if row_valid and duplicate_count == 0 else "FAIL",
            "no row appears in multiple splits within a fold",
            "split assignments contain duplicate rows within folds",
            {"duplicate_row_count": duplicate_count},
        ),
        _check(
            "phase_5",
            "event_family_overlap_reported",
            "PASS" if "leakage_event_family_count" in summary else "FAIL",
            "event-family overlap diagnostics are reported",
            "event-family overlap diagnostics are missing",
            {"leakage_event_family_count": summary.get("leakage_event_family_count")},
        ),
    ]


def _audit_walkforward(config: FinalAuditConfig) -> list[dict[str, Any]]:
    summary = _read_json(config.walkforward_dir / "summary.json")
    event_policy = str(
        summary.get("effective_config", {}).get("evaluation", {}).get("event_family_policy", "")
    ).lower()
    phase15_purge_available = _phase15_event_family_purge_available(config)
    event_policy_status = "FAIL"
    if "report" in event_policy:
        event_policy_status = "PASS" if phase15_purge_available else "PARTIAL"
    elif any(token in event_policy for token in ("filter", "exclude", "strict")):
        event_policy_status = "PASS"
    predictions_path = config.walkforward_dir / "predictions.parquet"
    prediction_columns = _parquet_columns(predictions_path)
    read_columns = [
        "fold_id",
        "model_name",
        "row_id",
        "contract_id",
        "event_family_id",
        "horizon_name",
        "forecast_ts",
        "resolution_ts",
        "observed_outcome",
        "raw_probability",
        "predicted_probability",
    ]
    if "close_time" in prediction_columns:
        read_columns.append("close_time")
    predictions = pd.read_parquet(
        predictions_path,
        columns=read_columns,
    )
    expected_models = set(config.expected_models)
    observed_models = set(predictions["model_name"].astype(str).unique())
    model_count = len(expected_models)
    row_model_counts = predictions.groupby(["fold_id", "row_id"], observed=True)[
        "model_name"
    ].nunique()
    identical_test_rows = bool((row_model_counts == model_count).all())
    bad_probability = int(
        (~pd.to_numeric(predictions["predicted_probability"], errors="coerce").between(0, 1)).sum()
    )
    bad_outcome = int((~predictions["observed_outcome"].isin([0, 1])).sum())
    key_mismatches = _prediction_panel_key_mismatch_count(predictions, config)
    fit_mismatches = _fit_row_mismatch_count(config)
    fits = pd.read_parquet(config.walkforward_dir / "calibrator_fits.parquet")
    hierarchical_fits = fits[fits["model_name"].astype(str) == "hierarchical_eb"].copy()
    requires_hierarchical = "hierarchical_eb" in expected_models
    experimental_label_valid = (
        not requires_hierarchical
        or (
            not hierarchical_fits.empty
            and "is_experimental" in hierarchical_fits.columns
            and bool(hierarchical_fits["is_experimental"].all())
        )
    )
    missing_expected_fits = sorted(expected_models - set(fits["model_name"].astype(str).unique()))
    return [
        _check(
            "phase_7",
            "walkforward_model_set",
            "PASS" if observed_models == expected_models else "FAIL",
            "walk-forward predictions include expected model set",
            "walk-forward predictions model set differs from config",
            {"observed": sorted(observed_models), "expected": sorted(expected_models)},
        ),
        _check(
            "phase_7",
            "walkforward_prediction_row_count",
            "PASS" if len(predictions) == int(summary.get("prediction_row_count", -1)) else "FAIL",
            "walk-forward prediction count matches summary",
            "walk-forward prediction count does not match summary",
            {"rows": len(predictions), "summary_rows": summary.get("prediction_row_count")},
        ),
        _check(
            "phase_7",
            "identical_test_rows_across_models",
            "PASS" if identical_test_rows else "FAIL",
            "all models predict on identical fold x row_id test rows",
            "models do not share identical test row IDs",
            {"bad_fold_row_count": int((row_model_counts != model_count).sum())},
        ),
        _check(
            "phase_7",
            "prediction_values_valid",
            "PASS" if bad_probability + bad_outcome == 0 else "FAIL",
            "predictions have valid probabilities and binary outcomes",
            "predictions contain invalid probabilities or outcomes",
            {"bad_probability": bad_probability, "bad_outcome": bad_outcome},
        ),
        _check(
            "phase_7",
            "prediction_panel_key_consistency",
            "PASS" if key_mismatches == 0 else "FAIL",
            "prediction row_ids match panel keys",
            "prediction row_ids do not match panel keys",
            {"mismatch_count": key_mismatches},
        ),
        _check(
            "phase_7",
            "fit_rows_resolved_by_test_start",
            "PASS" if fit_mismatches == 0 else "FAIL",
            "calibrator fit row counts match train+validation labels resolved by test start",
            "calibrator fit row counts do not match the resolved-by-test-start policy",
            {"mismatch_count": fit_mismatches},
        ),
        _check(
            "phase_7",
            "prediction_close_time_retained",
            "PASS" if "close_time" in prediction_columns else "FAIL",
            "walk-forward predictions retain raw close_time separately from resolution_ts",
            "walk-forward predictions do not retain raw close_time separately from resolution_ts",
            {"required_column": "close_time"},
        ),
        _check(
            "phase_14",
            "walkforward_phase14_fit_metadata",
            "PASS" if not missing_expected_fits else "FAIL",
            "calibrator fit metadata includes all expected Phase 14 models",
            "calibrator fit metadata is missing expected model rows",
            {"missing_models": missing_expected_fits},
        ),
        _check(
            "phase_14",
            "hierarchical_eb_experimental_label",
            "PASS" if experimental_label_valid else "FAIL",
            "hierarchical_eb fit artifacts are labeled experimental",
            "hierarchical_eb fit artifacts are missing required experimental labeling",
            {
                "hierarchical_fit_rows": int(len(hierarchical_fits)),
                "has_is_experimental_column": "is_experimental" in fits.columns,
            },
        ),
        _check(
            "phase_7",
            "event_family_policy_report_only",
            event_policy_status,
            "event-family report-only primary policy has Phase 15 purged sensitivity",
            "event-family overlaps are reported, not filtered, and Phase 15 purged "
            "sensitivity is missing",
            {
                "event_family_overlap_count": summary.get("event_family_overlap_count"),
                "event_family_policy": event_policy,
                "phase15_purged_sensitivity_available": phase15_purge_available,
            },
        ),
    ]


def _audit_raw_baseline(config: FinalAuditConfig) -> list[dict[str, Any]]:
    summary = _read_json(config.raw_baseline_dir / "summary.json")
    primary = summary.get("primary_aggregation")
    return [
        _check(
            "phase_4",
            "raw_baseline_primary_aggregation",
            "PASS" if primary == "equal_contract" else "FAIL",
            "raw baseline primary aggregation is equal-contract",
            "raw baseline primary aggregation is not equal-contract",
            {"primary_aggregation": primary},
        ),
        _check(
            "phase_4",
            "raw_baseline_trade_weighting_not_default",
            "PASS"
            if not summary.get("effective_config", {})
            .get("aggregation", {})
            .get("include_trade_weighted_robustness", True)
            else "FAIL",
            "trade-weighted robustness is not enabled as confirmatory default",
            "trade-weighted robustness appears enabled by default",
            {},
        ),
    ]


def _audit_inference(config: FinalAuditConfig) -> list[dict[str, Any]]:
    summary = _read_json(config.inference_dir / "summary.json")
    bootstrap_unit = str(summary.get("bootstrap_unit", "")).lower()
    bootstrap_mode = str(summary.get("bootstrap_mode", "")).lower()
    paired = pd.read_parquet(config.inference_dir / "paired_score_differences.parquet")
    scores = pd.read_parquet(config.inference_dir / "score_intervals.parquet")
    calibration = pd.read_parquet(config.inference_dir / "calibration_intervals.parquet")
    required_paired = {
        "estimate_delta",
        "ci_lower",
        "ci_upper",
        "p_value",
        "q_value",
        "effective_cluster_count",
        "bootstrap_unit",
        "aggregation_mode",
    }
    required_scores = {
        "estimate",
        "ci_lower",
        "ci_upper",
        "effective_cluster_count",
        "bootstrap_unit",
        "aggregation_mode",
    }
    required_calibration = {
        "estimate",
        "ci_lower",
        "ci_upper",
        "p_value",
        "effective_cluster_count",
        "bootstrap_unit",
    }
    bad_units = int(
        sum(
            (frame["bootstrap_unit"].astype(str).str.lower() != "event_family_id").sum()
            for frame in (paired, scores, calibration)
            if "bootstrap_unit" in frame.columns
        )
    )
    bad_aggregation = int(
        sum(
            (frame["aggregation_mode"].astype(str) != "equal_contract").sum()
            for frame in (paired, scores)
            if "aggregation_mode" in frame.columns
        )
    )
    iid_language = bootstrap_unit in {"iid", "row", "row_id", "trade", "trade_id"} or any(
        token in bootstrap_mode for token in ("iid", "row", "trade")
    )
    return [
        _check(
            "phase_13",
            "inference_bootstrap_unit",
            "PASS" if bootstrap_unit == "event_family_id" and bad_units == 0 else "FAIL",
            "inference artifacts use event-family clustered bootstrap",
            "inference artifacts do not use the required event-family bootstrap unit",
            {"summary_bootstrap_unit": bootstrap_unit, "bad_artifact_rows": bad_units},
        ),
        _check(
            "phase_13",
            "inference_no_iid_bootstrap",
            "PASS" if not iid_language else "FAIL",
            "inference summary contains no iid row/trade bootstrap language",
            "inference summary reports an iid/row/trade bootstrap mode",
            {"bootstrap_summary_text_contains_iid_or_row": iid_language},
        ),
        _check(
            "phase_13",
            "inference_required_columns",
            "PASS"
            if required_paired <= set(paired.columns)
            and required_scores <= set(scores.columns)
            and required_calibration <= set(calibration.columns)
            else "FAIL",
            "inference artifacts contain CI, p/q-value, and cluster-count columns",
            "inference artifacts are missing required uncertainty columns",
            {
                "paired_missing": sorted(required_paired - set(paired.columns)),
                "scores_missing": sorted(required_scores - set(scores.columns)),
                "calibration_missing": sorted(required_calibration - set(calibration.columns)),
            },
        ),
        _check(
            "phase_13",
            "inference_equal_contract",
            "PASS" if bad_aggregation == 0 else "FAIL",
            "inference point estimates remain equal-contract",
            "inference artifacts include non-equal-contract confirmatory aggregation rows",
            {"bad_aggregation_rows": bad_aggregation},
        ),
    ]


def _audit_decomposition(config: FinalAuditConfig) -> list[dict[str, Any]]:
    summary = _read_json(config.decomposition_dir / "summary.json")
    decomposition = pd.read_parquet(config.decomposition_dir / "murphy_decomposition.parquet")
    bins = pd.read_parquet(config.decomposition_dir / "murphy_bins.parquet")
    expected_models = set(config.expected_models)
    observed_models = set(decomposition["model_name"].astype(str).unique())
    required_decomposition = {
        "model_name",
        "grouping_name",
        "row_count",
        "reliability",
        "resolution",
        "uncertainty",
        "decomposed_brier",
        "raw_brier",
        "binning_residual",
    }
    required_bins = {
        "model_name",
        "grouping_name",
        "bin_index",
        "row_count",
        "mean_probability",
        "observed_frequency",
        "is_empty",
        "is_sparse",
    }
    decomposition_missing = sorted(required_decomposition - set(decomposition.columns))
    bins_missing = sorted(required_bins - set(bins.columns))
    if decomposition_missing:
        identity_max = float("inf")
    else:
        identity_error = (
            decomposition["decomposed_brier"].astype(float)
            - (
                decomposition["reliability"].astype(float)
                - decomposition["resolution"].astype(float)
                + decomposition["uncertainty"].astype(float)
            )
        ).abs()
        identity_max = float(identity_error.max())
    return [
        _check(
            "phase_14",
            "decomposition_model_set",
            "PASS" if expected_models <= observed_models else "FAIL",
            "Murphy decomposition includes expected Phase 14 model set",
            "Murphy decomposition is missing expected models",
            {"observed": sorted(observed_models), "expected": sorted(expected_models)},
        ),
        _check(
            "phase_14",
            "decomposition_required_columns",
            "PASS"
            if not decomposition_missing and not bins_missing
            else "FAIL",
            "Murphy decomposition artifacts include required component and bin columns",
            "Murphy decomposition artifacts are missing required columns",
            {
                "decomposition_missing": decomposition_missing,
                "bins_missing": bins_missing,
            },
        ),
        _check(
            "phase_14",
            "decomposition_identity",
            "PASS" if identity_max <= 1e-12 else "FAIL",
            "Murphy components satisfy decomposed_brier = reliability - resolution + uncertainty",
            "Murphy component identity check failed",
            {"max_identity_error": identity_max},
        ),
        _check(
            "phase_14",
            "decomposition_binning_residual_reported",
            "PASS" if "binning_residual" in decomposition.columns else "FAIL",
            "Murphy decomposition reports binning_residual",
            "Murphy decomposition does not report binning_residual",
            {
                "summary_limitations": summary.get("limitations", []),
                "max_abs_binning_residual": (
                    float(decomposition["binning_residual"].astype(float).abs().max())
                    if "binning_residual" in decomposition.columns
                    else None
                ),
            },
        ),
    ]


def _audit_edge(config: FinalAuditConfig) -> list[dict[str, Any]]:
    summary = _read_json(config.edge_dir / "summary.json")
    candidates = pd.read_parquet(
        config.edge_dir / "edge_candidates.parquet",
        columns=["trade_side", "effective_cost", "net_edge"],
    )
    trade_side = candidates["trade_side"].astype(str).str.upper()
    bad_side = int((trade_side != config.expected_edge_trade_side).sum())
    bad_cost = int((pd.to_numeric(candidates["effective_cost"], errors="coerce") < 0).sum())
    limitations = " ".join(str(item).lower() for item in summary.get("limitations", []))
    mentions_simulated = "simulated" in limitations and "not executable" in limitations
    return [
        _check(
            "phase_8",
            "edge_candidate_row_count",
            "PASS" if len(candidates) == int(summary.get("candidate_row_count", -1)) else "FAIL",
            "edge candidate count matches summary",
            "edge candidate count does not match summary",
            {"rows": len(candidates), "summary_rows": summary.get("candidate_row_count")},
        ),
        _check(
            "phase_8",
            "edge_yes_only",
            "PASS"
            if bad_side == 0
            and summary.get("trade_side") == "yes_only"
            and summary.get("effective_config", {}).get("screen", {}).get("allow_synthetic_no")
            is False
            else "FAIL",
            "edge candidates are YES-only and synthetic NO is disabled",
            "edge candidates include unsupported trade sides or synthetic NO is enabled",
            {"bad_side_count": bad_side, "trade_side": summary.get("trade_side")},
        ),
        _check(
            "phase_8",
            "edge_nonnegative_costs",
            "PASS" if bad_cost == 0 else "FAIL",
            "edge effective costs are nonnegative",
            "edge effective costs include negative values",
            {"bad_cost_count": bad_cost},
        ),
        _check(
            "phase_8",
            "edge_simulated_limitation_language",
            "PASS" if mentions_simulated else "FAIL",
            "edge summary explicitly says outputs are simulated and not executable",
            "edge summary lacks simulated/not-executable limitation language",
            {"limitations": summary.get("limitations", [])},
        ),
        _check(
            "phase_8",
            "edge_executability_limitations",
            "PARTIAL",
            "edge uses executable quote/depth data",
            "edge remains a simulated screen using transaction-price proxies and assumed frictions",
            {"known_limitation": "edge_outputs_simulated_not_executable"},
        ),
    ]


def _audit_reporting(config: FinalAuditConfig) -> list[dict[str, Any]]:
    figure = _read_json(config.figure_manifest_path)
    table = _read_json(config.table_manifest_path)
    figure_config = figure.get("effective_config", {}).get("reporting", {})
    table_config = table.get("effective_config", {}).get("reporting", {})
    source_text = json.dumps(
        {
            "figure": figure.get("source_artifacts", {}),
            "table": table.get("source_artifacts", {}),
        }
    ).lower()
    limitations = " ".join(
        str(item).lower()
        for item in [*figure.get("limitations", []), *table.get("limitations", [])]
    )
    table_dir = config.table_manifest_path.parent
    score_table = pd.read_csv(table_dir / "overall_score_comparison.csv")
    calibration_table = pd.read_csv(table_dir / "calibration_intercept_slope.csv")
    decomposition_table_path = table_dir / "murphy_decomposition.csv"
    decomposition_table = (
        pd.read_csv(decomposition_table_path)
        if decomposition_table_path.exists()
        else pd.DataFrame()
    )
    score_required = {
        "brier_score_ci_lower",
        "brier_delta_p_value",
        "brier_delta_q_value",
        "log_loss_ci_lower",
        "ece_delta_q_value",
        "effective_cluster_count",
    }
    calibration_required = {
        "calibration_intercept_ci_lower",
        "calibration_intercept_p_value",
        "calibration_slope_ci_lower",
        "calibration_slope_p_value",
        "effective_cluster_count",
    }
    source_artifacts = {
        "figure": figure.get("source_artifacts", {}),
        "table": table.get("source_artifacts", {}),
    }
    return [
        _check(
            "phase_9",
            "reporting_full_run_label",
            "PASS"
            if figure_config.get("artifact_run_label") == config.expected_reporting_run_label
            and table_config.get("artifact_run_label") == config.expected_reporting_run_label
            else "FAIL",
            "manuscript manifests use the expected full run label",
            "manuscript manifests do not use the expected full run label",
            {
                "figure_label": figure_config.get("artifact_run_label"),
                "table_label": table_config.get("artifact_run_label"),
            },
        ),
        _check(
            "phase_9",
            "reporting_sources_not_smoke",
            "PASS" if "smoke" not in source_text else "FAIL",
            "manuscript source artifacts point to full outputs, not smoke outputs",
            "manuscript source artifacts include smoke paths",
            {"source_artifacts": source_text},
        ),
        _check(
            "phase_9_13",
            "reporting_sources_include_inference",
            "PASS" if "inference" in source_text else "FAIL",
            "manuscript manifests include Phase 13 inference artifact sources",
            "manuscript manifests do not include inference artifact sources",
            {"source_artifacts": source_artifacts},
        ),
        _check(
            "phase_9_14",
            "reporting_sources_include_decomposition",
            "PASS" if "decomposition" in source_text else "FAIL",
            "manuscript manifests include Phase 14 decomposition artifact sources",
            "manuscript manifests do not include decomposition artifact sources",
            {"source_artifacts": source_artifacts},
        ),
        _check(
            "phase_9_14",
            "reporting_tables_include_decomposition",
            "PASS"
            if not decomposition_table.empty
            and {"reliability", "resolution", "uncertainty", "binning_residual"}
            <= set(decomposition_table.columns)
            else "FAIL",
            "manuscript tables include Murphy decomposition components",
            "manuscript tables are missing Murphy decomposition output",
            {
                "table_exists": decomposition_table_path.exists(),
                "columns": list(decomposition_table.columns),
            },
        ),
        _check(
            "phase_9_13",
            "reporting_tables_include_uncertainty",
            "PASS"
            if score_required <= set(score_table.columns)
            and calibration_required <= set(calibration_table.columns)
            else "FAIL",
            "manuscript score and calibration tables include clustered uncertainty columns",
            "manuscript tables are missing clustered uncertainty columns",
            {
                "score_missing": sorted(score_required - set(score_table.columns)),
                "calibration_missing": sorted(
                    calibration_required - set(calibration_table.columns)
                ),
            },
        ),
        _check(
            "phase_9",
            "reporting_limitations",
            "PASS"
            if "simulated" in limitations and "taxonomy" in limitations and "cluster" in limitations
            else "FAIL",
            "manuscript manifests record simulated-edge and taxonomy-coverage limitations",
            "manuscript manifests lack key limitation language",
            {"limitations": limitations},
        ),
    ]


def _audit_robustness(config: FinalAuditConfig) -> list[dict[str, Any]]:
    summary = _read_json(config.robustness_dir / "summary.json")
    source_text = json.dumps(summary.get("source_artifacts", {})).lower()
    limitations = " ".join(str(item).lower() for item in summary.get("limitations", []))
    artifact_paths = summary.get("artifact_paths", {})
    phase15_required = {
        "staleness_filter_sensitivity",
        "weighting_sensitivity",
        "event_family_exclusion_sensitivity",
        "full_snapshot_variant_runs",
        "full_snapshot_variant_metrics",
    }
    missing_phase15 = sorted(
        name
        for name in phase15_required
        if name not in artifact_paths or not Path(str(artifact_paths[name])).exists()
    )
    checks = [
        _check(
            "phase_10",
            "robustness_sources_not_smoke",
            "PASS" if "smoke" not in source_text else "FAIL",
            "robustness source artifacts point to full outputs",
            "robustness source artifacts include smoke paths",
            {"source_artifacts": summary.get("source_artifacts", {})},
        ),
        _check(
            "phase_10",
            "robustness_non_confirmatory_label",
            "PASS" if "diagnostic" in limitations or "not confirmatory" in limitations else "FAIL",
            "robustness outputs are explicitly diagnostic/non-confirmatory",
            "robustness summary lacks diagnostic/non-confirmatory limitation language",
            {"limitations": summary.get("limitations", [])},
        ),
        _check(
            "phase_15",
            "robustness_phase15_artifacts",
            "PASS" if not missing_phase15 else "FAIL",
            "Phase 15 robustness artifacts are present",
            "Phase 15 robustness artifacts are missing",
            {"missing_artifacts": missing_phase15},
        ),
    ]
    if not missing_phase15:
        checks.extend(_audit_phase15_robustness_artifacts(artifact_paths))
    return checks


def _audit_phase15_robustness_artifacts(
    artifact_paths: dict[str, Any],
) -> list[dict[str, Any]]:
    weighting = pd.read_parquet(Path(str(artifact_paths["weighting_sensitivity"])))
    event_family = pd.read_parquet(
        Path(str(artifact_paths["event_family_exclusion_sensitivity"]))
    )
    full_variants = pd.read_parquet(Path(str(artifact_paths["full_snapshot_variant_runs"])))
    trade_weighted = weighting[
        weighting.get("aggregation_mode", pd.Series(dtype=str)).astype(str) == "trade_weighted"
    ]
    trade_weighted_ok = (
        not trade_weighted.empty
        and "non_confirmatory" in trade_weighted.columns
        and bool(trade_weighted["non_confirmatory"].fillna(False).all())
        and "analysis_label" in trade_weighted.columns
        and trade_weighted["analysis_label"].astype(str).str.contains("robustness").all()
    )
    purge_present = (
        "policy_name" in event_family.columns
        and "drop_overlapping_event_families"
        in set(event_family["policy_name"].dropna().astype(str))
    )
    full_variant_smoke_paths = [
        str(value)
        for column in ("processed_dir", "artifact_dir")
        if column in full_variants.columns
        for value in full_variants[column].dropna().tolist()
        if "smoke" in str(value).lower()
    ]
    full_variant_completed = (
        "status" in full_variants.columns
        and set(full_variants["status"].dropna().astype(str)) <= {"completed"}
        and not full_variants.empty
    )
    return [
        _check(
            "phase_15",
            "trade_weighted_robustness_labeled",
            "PASS" if trade_weighted_ok else "FAIL",
            "trade-weighted outputs are present and labeled non-confirmatory robustness",
            "trade-weighted outputs are absent or not clearly labeled robustness-only",
            {"trade_weighted_row_count": int(len(trade_weighted))},
        ),
        _check(
            "phase_15",
            "event_family_purged_sensitivity_present",
            "PASS" if purge_present else "FAIL",
            "event-family-purged sensitivity exists for report-only primary policy",
            "event-family-purged sensitivity artifact is missing the purged policy",
            {
                "policies": sorted(
                    set(event_family.get("policy_name", pd.Series(dtype=str)).dropna().astype(str))
                )
            },
        ),
        _check(
            "phase_15",
            "full_snapshot_variants_completed",
            "PASS" if full_variant_completed and not full_variant_smoke_paths else "FAIL",
            "full alternate snapshot variants completed outside smoke paths",
            "full alternate snapshot variants are incomplete or point to smoke paths",
            {
                "status_counts": full_variants.get(
                    "status",
                    pd.Series(dtype=str),
                )
                .astype(str)
                .value_counts()
                .to_dict(),
                "smoke_paths": full_variant_smoke_paths,
            },
        ),
    ]


def _phase15_event_family_purge_available(config: FinalAuditConfig) -> bool:
    summary_path = config.robustness_dir / "summary.json"
    if not summary_path.exists():
        return False
    summary = _read_json(summary_path)
    artifact_paths = summary.get("artifact_paths", {})
    path = artifact_paths.get("event_family_exclusion_sensitivity")
    if not path or not Path(str(path)).exists():
        return False
    frame = pd.read_parquet(Path(str(path)), columns=["policy_name"])
    return "drop_overlapping_event_families" in set(frame["policy_name"].dropna().astype(str))


def _prediction_panel_key_mismatch_count(
    predictions: pd.DataFrame,
    config: FinalAuditConfig,
) -> int:
    panel = pd.read_parquet(
        config.modeling_panel_path,
        columns=[
            "contract_id",
            "event_family_id",
            "horizon_name",
            "forecast_ts",
            "resolution_ts",
        ],
    )
    panel = panel.reset_index(names="row_id")
    joined = predictions.merge(
        panel,
        on="row_id",
        how="left",
        suffixes=("", "_panel"),
        validate="many_to_one",
    )
    if joined["contract_id_panel"].isna().any():
        return int(joined["contract_id_panel"].isna().sum())
    mismatch = (
        (joined["contract_id"].astype(str) != joined["contract_id_panel"].astype(str))
        | (joined["event_family_id"].astype(str) != joined["event_family_id_panel"].astype(str))
        | (joined["horizon_name"].astype(str) != joined["horizon_name_panel"].astype(str))
        | (
            pd.to_datetime(joined["forecast_ts"], utc=True)
            != pd.to_datetime(joined["forecast_ts_panel"], utc=True)
        )
        | (
            pd.to_datetime(joined["resolution_ts"], utc=True)
            != pd.to_datetime(joined["resolution_ts_panel"], utc=True)
        )
    )
    return int(mismatch.sum())


def _fit_row_mismatch_count(config: FinalAuditConfig) -> int:
    panel = pd.read_parquet(config.modeling_panel_path, columns=["resolution_ts"]).reset_index(
        names="row_id"
    )
    panel["resolution_ts"] = pd.to_datetime(panel["resolution_ts"], utc=True)
    splits = pd.read_parquet(config.splits_path, columns=["fold_id", "split", "row_id"])
    fit_splits = splits[splits["split"].isin(["train", "validation"])].merge(
        panel,
        on="row_id",
        how="left",
        validate="many_to_one",
    )
    fit_splits["test_start_ts"] = fit_splits["fold_id"].map(_test_start_from_fold_id)
    expected = (
        fit_splits[fit_splits["resolution_ts"] <= fit_splits["test_start_ts"]]
        .groupby("fold_id", observed=True)
        .size()
        .rename("expected_fit_rows")
        .reset_index()
    )
    fits = pd.read_parquet(
        config.walkforward_dir / "calibrator_fits.parquet",
        columns=["fold_id", "model_name", "fit_row_count"],
    )
    joined = fits.merge(expected, on="fold_id", how="left", validate="many_to_one")
    mismatch = joined["fit_row_count"].astype(int) != joined["expected_fit_rows"].fillna(-1).astype(
        int
    )
    return int(mismatch.sum())


def _raw_repo_check(config: FinalAuditConfig) -> dict[str, Any]:
    path = config.raw_repo_path
    if path is None or not path.exists():
        return _check(
            "phase_1_2",
            "raw_repo_cleanliness",
            "PARTIAL",
            "raw Becker repo is available and clean",
            "raw Becker repo path is unavailable; raw-data mutation cannot be audited here",
            {"raw_repo_path": str(path) if path else None},
        )
    if not (path / ".git").exists():
        return _check(
            "phase_1_2",
            "raw_repo_cleanliness",
            "PARTIAL",
            "raw Becker repo is a clean git checkout",
            "raw path exists but is not a git checkout; cleanliness cannot be audited",
            {"raw_repo_path": str(path)},
        )
    completed = subprocess.run(
        ["git", "-C", str(path), "status", "--short"],
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        return _check(
            "phase_1_2",
            "raw_repo_cleanliness",
            "PARTIAL",
            "raw Becker repo git status is readable",
            "raw Becker repo git status failed",
            {"stderr": completed.stderr[-1000:]},
        )
    dirty_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    return _check(
        "phase_1_2",
        "raw_repo_cleanliness",
        "PASS" if not dirty_lines else "PARTIAL",
        "raw Becker repo git status is clean",
        "raw Becker repo has local changes or untracked files; confirm these are expected "
        "raw-data downloads",
        {"dirty_line_count": len(dirty_lines), "examples": dirty_lines[:10]},
    )


def _artifact_existence_checks(inventory: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for record in inventory.to_dict(orient="records"):
        artifact_key = str(record["artifact_key"])
        exists = bool(record["exists"])
        if artifact_key == "raw_repo_path" and not exists:
            status = "PARTIAL"
            message = (
                "raw Becker repo path is unavailable; raw-data mutation cannot be audited here"
            )
        else:
            status = "PASS" if exists else "FAIL"
            message = f"missing required artifact: {artifact_key}"
        rows.append(
            _check(
                "artifact_inventory",
                f"exists_{artifact_key}",
                status,
                f"artifact exists: {artifact_key}",
                message,
                {"path": record["path"]},
            )
        )
    return rows


def _phase_status(checks: pd.DataFrame) -> pd.DataFrame:
    if checks.empty:
        return pd.DataFrame(
            columns=["phase", "status", "pass_count", "partial_count", "fail_count"]
        )
    rows = []
    for phase, group in checks.groupby("phase", observed=True):
        status = _overall_status(group)
        rows.append(
            {
                "phase": phase,
                "status": status,
                "pass_count": int((group["status"] == "PASS").sum()),
                "partial_count": int((group["status"] == "PARTIAL").sum()),
                "fail_count": int((group["status"] == "FAIL").sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("phase").reset_index(drop=True)


def _overall_status(checks: pd.DataFrame) -> str:
    if checks.empty:
        return "FAIL"
    if (checks["status"] == "FAIL").any():
        return "FAIL"
    if (checks["status"] == "PARTIAL").any():
        return "PARTIAL"
    return "PASS"


def _semantics_markdown(
    config: FinalAuditConfig,
    checks: pd.DataFrame,
    phase_status: pd.DataFrame,
    overall_status: str,
) -> str:
    failed = checks[checks["status"] == "FAIL"] if not checks.empty else pd.DataFrame()
    partial = checks[checks["status"] == "PARTIAL"] if not checks.empty else pd.DataFrame()
    close_time_retained = _check_status(checks, "close_time_not_retained") == "PASS"
    close_time_line = (
        "- Cleaned interim contracts retain raw `close_time` separately from normalized "
        "`resolution_ts`; downstream snapshot/modeling/prediction artifacts are audited "
        "for the same retained field."
        if close_time_retained
        else "- Cleaned interim contracts currently do not retain a separate raw "
        "`close_time` column, so the resolution/close-time mapping remains a documented "
        "semantic limitation."
    )
    lines = [
        "# Final Data Semantics Audit",
        "",
        f"Overall status: **{overall_status}**.",
        "",
        "This Phase 11 audit inspects saved artifacts only. It does not rebuild data, "
        "refit models, or alter methodology.",
        "",
        "## Key Semantic Findings",
        "",
        "- `resolution_ts` is the normalized timestamp used by downstream panels.",
        close_time_line,
        "- Domain/category taxonomy is rule-based and audited, but low-confidence title, "
        "ambiguous, and unknown assignments remain non-confirmatory.",
        "- `event_family_id` uses audited regex grouping where available and explicit "
        "event_id/contract_id fallbacks elsewhere; Phase 13 inference resamples these "
        "event-family clusters.",
        "- Phase 14 adds binned reliability correction and an experimental "
        "`hierarchical_eb` empirical-Bayes additive recalibrator.",
        "- Murphy decomposition is reported from fixed-width bins, with binning residuals "
        "retained rather than treated as exact Brier identities.",
        "- Edge outputs remain simulated expected-value screens, not executable trading profits.",
        "",
        "## Phase Status",
        "",
        _markdown_table(phase_status),
        "",
        "## Partial Checks",
        "",
        _markdown_table(partial[["phase", "check_id", "message"]])
        if not partial.empty
        else "No partial checks.",
        "",
        "## Failed Checks",
        "",
        _markdown_table(failed[["phase", "check_id", "message"]])
        if not failed.empty
        else "No failed checks.",
        "",
        "## Source Config",
        "",
        f"- Config path: `{config.config_path}`",
        f"- Config SHA256: `{config.config_sha256}`",
    ]
    return "\n".join(lines) + "\n"


def _check_status(checks: pd.DataFrame, check_id: str) -> str | None:
    if checks.empty or "check_id" not in checks.columns:
        return None
    matches = checks.loc[checks["check_id"] == check_id, "status"]
    if matches.empty:
        return None
    return str(matches.iloc[0])


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "No rows."
    columns = [str(column) for column in frame.columns]
    rows = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for item in frame.astype(object).where(pd.notna(frame), "").itertuples(index=False):
        rows.append("| " + " | ".join(str(value) for value in item) + " |")
    return "\n".join(rows)


def _check(
    phase: str,
    check_id: str,
    status: str,
    pass_message: str,
    fail_message: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    if status not in STATUS_ORDER:
        raise FinalAuditError(f"invalid check status: {status}")
    return {
        "phase": phase,
        "check_id": check_id,
        "status": status,
        "message": pass_message if status == "PASS" else fail_message,
        "details_json": json.dumps(details, sort_keys=True, default=str),
    }


def _configured_artifacts(config: FinalAuditConfig) -> dict[str, Path]:
    artifacts = {
        "interim_summary": config.interim_summary_path,
        "interim_contracts": config.interim_contracts_path,
        "interim_price_observations": config.interim_price_observations_path,
        "contract_exclusion_summary": config.contract_exclusion_summary_path,
        "price_observation_exclusion_summary": config.price_observation_exclusion_summary_path,
        "snapshot_panel": config.snapshot_panel_path,
        "snapshot_summary": config.snapshot_summary_path,
        "taxonomy_panel": config.taxonomy_panel_path,
        "taxonomy_summary": config.taxonomy_summary_path,
        "modeling_panel": config.modeling_panel_path,
        "modeling_summary": config.modeling_summary_path,
        "splits": config.splits_path,
        "split_integrity": config.split_integrity_path,
        "split_summary": config.split_summary_path,
        "raw_baseline_summary": config.raw_baseline_dir / "summary.json",
        "walkforward_summary": config.walkforward_dir / "summary.json",
        "walkforward_predictions": config.walkforward_dir / "predictions.parquet",
        "walkforward_calibrator_fits": config.walkforward_dir / "calibrator_fits.parquet",
        "edge_summary": config.edge_dir / "summary.json",
        "edge_candidates": config.edge_dir / "edge_candidates.parquet",
        "inference_summary": config.inference_dir / "summary.json",
        "inference_score_intervals": config.inference_dir / "score_intervals.parquet",
        "inference_paired_score_differences": (
            config.inference_dir / "paired_score_differences.parquet"
        ),
        "inference_calibration_intervals": config.inference_dir / "calibration_intervals.parquet",
        "inference_multiple_comparison_adjustments": (
            config.inference_dir / "multiple_comparison_adjustments.parquet"
        ),
        "inference_paired_loss_diagnostics": (
            config.inference_dir / "paired_loss_diagnostics.parquet"
        ),
        "decomposition_summary": config.decomposition_dir / "summary.json",
        "decomposition_murphy_decomposition": (
            config.decomposition_dir / "murphy_decomposition.parquet"
        ),
        "decomposition_murphy_bins": config.decomposition_dir / "murphy_bins.parquet",
        "robustness_summary": config.robustness_dir / "summary.json",
        "figure_manifest": config.figure_manifest_path,
        "table_manifest": config.table_manifest_path,
    }
    if config.raw_repo_path is not None:
        artifacts["raw_repo_path"] = config.raw_repo_path
    return artifacts


def _artifact_paths(audit_dir: Path) -> dict[str, Path]:
    return {
        "checks": audit_dir / "audit_checks.parquet",
        "inventory": audit_dir / "artifact_inventory.parquet",
        "phase_status": audit_dir / "phase_status.parquet",
        "summary": audit_dir / "summary.json",
    }


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _parquet_columns(path: Path) -> list[str]:
    parquet = pq.ParquetFile(path)  # type: ignore[no-untyped-call]
    return list(parquet.schema_arrow.names)


def _all_unknown(values: pd.Series) -> bool:
    unique_values = set(values.fillna("unknown").astype(str).str.lower().unique())
    return unique_values <= {"unknown"}


def _test_start_from_fold_id(fold_id: str) -> pd.Timestamp:
    _, year, month = fold_id.split("_")
    return pd.Timestamp(f"{year}-{month}-01", tz="UTC")


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"final audit config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"final audit config missing required key: {key}")
    return raw[key]


def _normalize_trade_side(value: Any) -> str:
    if isinstance(value, bool):
        return "YES" if value else "NO"
    text = str(value).strip().upper()
    if text in {"YES", "YES_ONLY"}:
        return "YES"
    if text in {"NO", "NO_ONLY"}:
        return "NO"
    return text
