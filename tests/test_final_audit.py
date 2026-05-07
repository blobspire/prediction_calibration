from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd

from predmkt.reports.final_audit import build_final_audit, load_final_audit_config


def test_final_audit_writes_outputs_and_marks_known_limitations_partial(
    tmp_path: Path,
) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path))

    summary = build_final_audit(config)

    assert summary.overall_status == "PARTIAL"
    assert summary.fail_count == 0
    assert Path(summary.audit_checks_path).exists()
    assert Path(summary.artifact_inventory_path).exists()
    assert Path(summary.phase_status_path).exists()
    assert Path(summary.semantics_doc_path).exists()
    report = Path(summary.semantics_doc_path).read_text(encoding="utf-8")
    assert "`resolution_ts`" in report
    assert "`close_time`" in report


def test_unquoted_yes_trade_side_config_is_normalized(tmp_path: Path) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path, quote_edge_side=False))

    assert config.expected_edge_trade_side == "YES"


def test_final_audit_fails_on_duplicate_snapshot_keys(tmp_path: Path) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path, duplicate_snapshot=True))

    summary = build_final_audit(config)

    assert summary.overall_status == "FAIL"
    checks = pd.read_parquet(Path(summary.audit_checks_path))
    duplicate = checks[checks["check_id"] == "snapshot_duplicate_keys"].iloc[0]
    assert duplicate["status"] == "FAIL"


def test_final_audit_fails_on_snapshot_lookahead(tmp_path: Path) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path, snapshot_lookahead=True))

    summary = build_final_audit(config)

    assert summary.overall_status == "FAIL"
    checks = pd.read_parquet(Path(summary.audit_checks_path))
    lookahead = checks[checks["check_id"] == "snapshot_no_lookahead_source_times"].iloc[0]
    assert lookahead["status"] == "FAIL"


def test_final_audit_fails_on_split_time_order(tmp_path: Path) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path, bad_split_order=True))

    summary = build_final_audit(config)

    assert summary.overall_status == "FAIL"
    checks = pd.read_parquet(Path(summary.audit_checks_path))
    split_order = checks[checks["check_id"] == "split_time_order"].iloc[0]
    assert split_order["status"] == "FAIL"


def test_final_audit_fails_on_prediction_panel_key_mismatch(tmp_path: Path) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path, bad_prediction_key=True))

    summary = build_final_audit(config)

    assert summary.overall_status == "FAIL"
    checks = pd.read_parquet(Path(summary.audit_checks_path))
    key_check = checks[checks["check_id"] == "prediction_panel_key_consistency"].iloc[0]
    assert key_check["status"] == "FAIL"


def test_final_audit_marks_unknown_taxonomy_partial(tmp_path: Path) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path, unknown_taxonomy=True))

    summary = build_final_audit(config)

    checks = pd.read_parquet(Path(summary.audit_checks_path))
    taxonomy = checks[checks["check_id"] == "domain_category_coverage"].iloc[0]
    assert summary.overall_status == "PARTIAL"
    assert taxonomy["status"] == "PARTIAL"


def test_final_audit_fails_on_unsupported_edge_side(tmp_path: Path) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path, bad_edge_side=True))

    summary = build_final_audit(config)

    assert summary.overall_status == "FAIL"
    checks = pd.read_parquet(Path(summary.audit_checks_path))
    edge = checks[checks["check_id"] == "edge_yes_only"].iloc[0]
    assert edge["status"] == "FAIL"


def test_final_audit_fails_on_missing_phase12_taxonomy_columns(tmp_path: Path) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path, missing_phase12_taxonomy=True))

    summary = build_final_audit(config)

    assert summary.overall_status == "FAIL"
    checks = pd.read_parquet(Path(summary.audit_checks_path))
    taxonomy = checks[checks["check_id"] == "taxonomy_phase12_columns"].iloc[0]
    assert taxonomy["status"] == "FAIL"


def _write_fixture(
    tmp_path: Path,
    *,
    duplicate_snapshot: bool = False,
    snapshot_lookahead: bool = False,
    bad_split_order: bool = False,
    bad_prediction_key: bool = False,
    unknown_taxonomy: bool = False,
    bad_edge_side: bool = False,
    quote_edge_side: bool = True,
    missing_phase12_taxonomy: bool = False,
) -> Path:
    raw_repo = tmp_path / "raw_repo"
    raw_repo.mkdir()
    subprocess.run(["git", "init"], cwd=raw_repo, check=True, capture_output=True)

    interim = tmp_path / "interim"
    processed = tmp_path / "processed"
    raw_baseline = tmp_path / "raw_baseline"
    walkforward = tmp_path / "walkforward"
    edge = tmp_path / "edge"
    robustness = tmp_path / "robustness"
    figures = tmp_path / "figures"
    tables = tmp_path / "tables"
    for path in (interim, processed, raw_baseline, walkforward, edge, robustness, figures, tables):
        path.mkdir()

    panel = _panel(unknown_taxonomy=unknown_taxonomy)
    if missing_phase12_taxonomy:
        panel = panel.drop(
            columns=[
                "is_sports",
                "taxonomy_rule_id",
                "taxonomy_ambiguous",
                "event_family_source",
                "event_family_confidence",
            ]
        )
    snapshot = _snapshot_panel(snapshot_lookahead=snapshot_lookahead)
    if duplicate_snapshot:
        snapshot = pd.concat([snapshot, snapshot.iloc[[0]]], ignore_index=True)

    _write_interim(interim)
    snapshot.to_parquet(processed / "contract_horizon_panel.parquet", index=False)
    (processed / "contract_horizon_panel_summary.json").write_text(
        json.dumps(
            {
                "row_count": len(snapshot),
                "duplicate_key_validation": {"passed": True},
                "no_lookahead_validation": {"passed": True},
            }
        ),
        encoding="utf-8",
    )
    panel.to_parquet(processed / "contract_horizon_panel_taxonomy.parquet", index=False)
    (processed / "contract_horizon_taxonomy_summary.json").write_text(
        json.dumps(
            {
                "input_row_count": len(panel),
                "output_row_count": len(panel),
                "dropped_row_count": 0,
                "unknown_rate": 1.0 if unknown_taxonomy else 0.0,
                "ambiguous_rate": 0.0,
                "event_family_source_counts": {
                    _fixture_event_family_source(unknown_taxonomy): len(panel)
                },
            }
        ),
        encoding="utf-8",
    )
    panel.to_parquet(processed / "modeling_panel.parquet", index=False)
    (processed / "modeling_panel_summary.json").write_text(
        json.dumps({"output_row_count": len(panel)}),
        encoding="utf-8",
    )
    _write_splits(processed, bad_split_order=bad_split_order)
    _write_raw_baseline(raw_baseline)
    _write_walkforward(walkforward, bad_prediction_key=bad_prediction_key)
    _write_edge(edge, bad_edge_side=bad_edge_side)
    _write_reporting(figures, tables)
    _write_robustness(robustness)

    edge_side = '"YES"' if quote_edge_side else "YES"
    config_path = tmp_path / "final_audit.yaml"
    config_path.write_text(
        f"""
inputs:
  raw_repo_path: {raw_repo}
  interim_summary_path: {interim / "summary.json"}
  interim_contracts_path: {interim / "contracts.parquet"}
  interim_price_observations_path: {interim / "price_observations.parquet"}
  contract_exclusion_summary_path: {interim / "contract_exclusion_summary.parquet"}
  price_observation_exclusion_summary_path: {interim / "price_exclusion_summary.parquet"}
  snapshot_panel_path: {processed / "contract_horizon_panel.parquet"}
  snapshot_summary_path: {processed / "contract_horizon_panel_summary.json"}
  taxonomy_panel_path: {processed / "contract_horizon_panel_taxonomy.parquet"}
  taxonomy_summary_path: {processed / "contract_horizon_taxonomy_summary.json"}
  modeling_panel_path: {processed / "modeling_panel.parquet"}
  modeling_summary_path: {processed / "modeling_panel_summary.json"}
  splits_path: {processed / "walkforward_splits.parquet"}
  split_integrity_path: {processed / "walkforward_split_integrity.parquet"}
  split_summary_path: {processed / "walkforward_split_summary.json"}
  raw_baseline_dir: {raw_baseline}
  walkforward_dir: {walkforward}
  edge_dir: {edge}
  robustness_dir: {robustness}
  figure_manifest_path: {figures / "figure_manifest.json"}
  table_manifest_path: {tables / "table_manifest.json"}
outputs:
  audit_dir: {tmp_path / "audit"}
  semantics_doc_path: {tmp_path / "docs" / "final_data_semantics.md"}
audit:
  expected_horizons: [1d]
  expected_models: [raw, platt]
  expected_edge_trade_side: {edge_side}
  expected_reporting_run_label: full
  known_partial_limitations:
    - edge_outputs_simulated_not_executable
""",
        encoding="utf-8",
    )
    return config_path


def _fixture_event_family_source(unknown_taxonomy: bool) -> str:
    return "event_id_fallback" if unknown_taxonomy else "event_family_regex_rule"


def _write_interim(interim: Path) -> None:
    pd.DataFrame(
        {
            "contract_id": ["C0", "C1"],
            "resolution_ts": [
                pd.Timestamp("2023-12-10", tz="UTC"),
                pd.Timestamp("2024-01-10", tz="UTC"),
            ],
            "close_time": [
                pd.Timestamp("2023-12-10", tz="UTC"),
                pd.Timestamp("2024-01-10", tz="UTC"),
            ],
        }
    ).to_parquet(interim / "contracts.parquet", index=False)
    pd.DataFrame(
        {"contract_id": ["C0"], "source_ts": [pd.Timestamp("2023-12-01", tz="UTC")]}
    ).to_parquet(interim / "price_observations.parquet", index=False)
    pd.DataFrame({"reason": ["status_not_finalized"], "count": [1]}).to_parquet(
        interim / "contract_exclusion_summary.parquet",
        index=False,
    )
    pd.DataFrame({"reason": ["contract_not_resolved_binary"], "count": [1]}).to_parquet(
        interim / "price_exclusion_summary.parquet",
        index=False,
    )
    (interim / "summary.json").write_text(
        json.dumps(
            {
                "contracts": {"excluded_rows": 1},
                "price_observations": {"excluded_rows": 1},
            }
        ),
        encoding="utf-8",
    )


def _snapshot_panel(*, snapshot_lookahead: bool) -> pd.DataFrame:
    price_ts = [
        pd.Timestamp("2023-12-01", tz="UTC"),
        pd.Timestamp("2024-01-06" if snapshot_lookahead else "2024-01-05", tz="UTC"),
    ]
    return pd.DataFrame(
        {
            "contract_id": ["C0", "C1"],
            "horizon_bucket": ["1d", "1d"],
            "forecast_ts": [
                pd.Timestamp("2023-12-01", tz="UTC"),
                pd.Timestamp("2024-01-05", tz="UTC"),
            ],
            "resolution_ts": [
                pd.Timestamp("2023-12-10", tz="UTC"),
                pd.Timestamp("2024-01-10", tz="UTC"),
            ],
            "price_timestamp": price_ts,
            "last_trade_ts": price_ts,
            "max_source_ts": price_ts,
        }
    )


def _panel(*, unknown_taxonomy: bool) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "contract_id": ["C0", "C1"],
            "event_family_id": ["E0", "E1"],
            "horizon_name": ["1d", "1d"],
            "forecast_ts": [
                pd.Timestamp("2023-12-01", tz="UTC"),
                pd.Timestamp("2024-01-05", tz="UTC"),
            ],
            "resolution_ts": [
                pd.Timestamp("2023-12-10", tz="UTC"),
                pd.Timestamp("2024-01-10", tz="UTC"),
            ],
            "price_timestamp": [
                pd.Timestamp("2023-12-01", tz="UTC"),
                pd.Timestamp("2024-01-05", tz="UTC"),
            ],
            "max_feature_source_ts": [
                pd.Timestamp("2023-12-01", tz="UTC"),
                pd.Timestamp("2024-01-05", tz="UTC"),
            ],
            "domain": ["unknown" if unknown_taxonomy else "macro"] * 2,
            "category": ["unknown" if unknown_taxonomy else "inflation"] * 2,
            "event_family_id_inferred": [unknown_taxonomy, unknown_taxonomy],
            "is_sports": [False, False],
            "taxonomy_rule_id": ["default_unknown" if unknown_taxonomy else "macro_rule"] * 2,
            "taxonomy_ambiguous": [False, False],
            "event_family_source": [
                "event_id_fallback" if unknown_taxonomy else "event_family_regex_rule"
            ]
            * 2,
            "event_family_confidence": ["low" if unknown_taxonomy else "medium"] * 2,
        }
    )


def _write_splits(processed: Path, *, bad_split_order: bool) -> None:
    pd.DataFrame(
        {
            "fold_id": ["fold_2024_01", "fold_2024_01"],
            "split": ["train", "test"],
            "row_id": [0, 1],
        }
    ).to_parquet(processed / "walkforward_splits.parquet", index=False)
    pd.DataFrame(
        {
            "fold_id": ["fold_2024_01"],
            "time_order_valid": [not bad_split_order],
            "row_exclusivity_valid": [True],
            "duplicate_row_count": [0],
        }
    ).to_parquet(processed / "walkforward_split_integrity.parquet", index=False)
    (processed / "walkforward_split_summary.json").write_text(
        json.dumps(
            {
                "time_order_valid": not bad_split_order,
                "leakage_event_family_count": 0,
            }
        ),
        encoding="utf-8",
    )


def _write_raw_baseline(raw_baseline: Path) -> None:
    (raw_baseline / "summary.json").write_text(
        json.dumps(
            {
                "primary_aggregation": "equal_contract",
                "effective_config": {
                    "aggregation": {"include_trade_weighted_robustness": False}
                },
            }
        ),
        encoding="utf-8",
    )


def _write_walkforward(walkforward: Path, *, bad_prediction_key: bool) -> None:
    predictions = []
    for model in ("raw", "platt"):
        predictions.append(
            {
                "fold_id": "fold_2024_01",
                "model_name": model,
                "row_id": 1,
                "contract_id": "WRONG" if bad_prediction_key and model == "raw" else "C1",
                "event_family_id": "E1",
                "horizon_name": "1d",
                "forecast_ts": pd.Timestamp("2024-01-05", tz="UTC"),
                "resolution_ts": pd.Timestamp("2024-01-10", tz="UTC"),
                "observed_outcome": 1,
                "raw_probability": 0.7,
                "predicted_probability": 0.75,
            }
        )
    pd.DataFrame(predictions).to_parquet(walkforward / "predictions.parquet", index=False)
    pd.DataFrame(
        {
            "fold_id": ["fold_2024_01", "fold_2024_01"],
            "model_name": ["raw", "platt"],
            "fit_row_count": [1, 1],
        }
    ).to_parquet(walkforward / "calibrator_fits.parquet", index=False)
    (walkforward / "summary.json").write_text(
        json.dumps(
            {
                "prediction_row_count": 2,
                "effective_config": {"evaluation": {"event_family_policy": "report_only"}},
                "event_family_overlap_count": 0,
            }
        ),
        encoding="utf-8",
    )


def _write_edge(edge: Path, *, bad_edge_side: bool) -> None:
    pd.DataFrame(
        {
            "trade_side": ["NO" if bad_edge_side else "YES", "YES"],
            "effective_cost": [0.55, 0.56],
            "net_edge": [0.2, 0.19],
        }
    ).to_parquet(edge / "edge_candidates.parquet", index=False)
    (edge / "summary.json").write_text(
        json.dumps(
            {
                "candidate_row_count": 2,
                "trade_side": "yes_only",
                "effective_config": {"screen": {"allow_synthetic_no": False}},
                "limitations": [
                    "outputs are simulated expected-value screens and not executable profits"
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_reporting(figures: Path, tables: Path) -> None:
    manifest = {
        "effective_config": {"reporting": {"artifact_run_label": "full"}},
        "source_artifacts": {
            "walkforward": "data/artifacts/walkforward",
            "edge": "data/artifacts/edge_sim",
        },
        "limitations": ["simulated edge screens", "unknown taxonomy remains limited"],
    }
    (figures / "figure_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tables / "table_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _write_robustness(robustness: Path) -> None:
    (robustness / "summary.json").write_text(
        json.dumps(
            {
                "source_artifacts": {
                    "walkforward": "data/artifacts/walkforward",
                    "edge": "data/artifacts/edge_sim",
                },
                "limitations": ["diagnostic outputs only and not confirmatory"],
            }
        ),
        encoding="utf-8",
    )
