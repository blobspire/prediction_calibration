from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd

from predmkt.reports.final_audit import build_final_audit, load_final_audit_config


def test_final_audit_writes_outputs_and_passes_phase16_edge_checks(
    tmp_path: Path,
) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path))

    summary = build_final_audit(config)

    assert summary.overall_status == "PASS"
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


def test_final_audit_fails_on_synthetic_no_edge_prices(tmp_path: Path) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path, synthetic_no_edge=True))

    summary = build_final_audit(config)

    assert summary.overall_status == "FAIL"
    checks = pd.read_parquet(Path(summary.audit_checks_path))
    edge = checks[checks["check_id"] == "edge_no_synthetic_no_prices"].iloc[0]
    assert edge["status"] == "FAIL"


def test_final_audit_fails_on_future_quote_edge_prices(tmp_path: Path) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path, future_quote_edge=True))

    summary = build_final_audit(config)

    assert summary.overall_status == "FAIL"
    checks = pd.read_parquet(Path(summary.audit_checks_path))
    edge = checks[checks["check_id"] == "edge_no_future_quotes"].iloc[0]
    assert edge["status"] == "FAIL"


def test_final_audit_fails_on_missing_phase12_taxonomy_columns(tmp_path: Path) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path, missing_phase12_taxonomy=True))

    summary = build_final_audit(config)

    assert summary.overall_status == "FAIL"
    checks = pd.read_parquet(Path(summary.audit_checks_path))
    taxonomy = checks[checks["check_id"] == "taxonomy_phase12_columns"].iloc[0]
    assert taxonomy["status"] == "FAIL"


def test_final_audit_fails_on_iid_inference_bootstrap(tmp_path: Path) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path, iid_inference=True))

    summary = build_final_audit(config)

    assert summary.overall_status == "FAIL"
    checks = pd.read_parquet(Path(summary.audit_checks_path))
    inference = checks[checks["check_id"] == "inference_bootstrap_unit"].iloc[0]
    assert inference["status"] == "FAIL"


def test_final_audit_fails_when_hierarchical_not_marked_experimental(tmp_path: Path) -> None:
    config = load_final_audit_config(
        _write_fixture(
            tmp_path,
            expected_models=("raw", "platt", "hierarchical_eb"),
            bad_hierarchical_label=True,
        )
    )

    summary = build_final_audit(config)

    assert summary.overall_status == "FAIL"
    checks = pd.read_parquet(Path(summary.audit_checks_path))
    hierarchical = checks[checks["check_id"] == "hierarchical_eb_experimental_label"].iloc[0]
    assert hierarchical["status"] == "FAIL"


def test_final_audit_fails_when_phase15_robustness_artifacts_missing(tmp_path: Path) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path, missing_phase15_robustness=True))

    summary = build_final_audit(config)

    assert summary.overall_status == "FAIL"
    checks = pd.read_parquet(Path(summary.audit_checks_path))
    robustness = checks[checks["check_id"] == "robustness_phase15_artifacts"].iloc[0]
    assert robustness["status"] == "FAIL"


def test_final_audit_fails_when_trade_weighted_not_labeled(tmp_path: Path) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path, bad_trade_weight_label=True))

    summary = build_final_audit(config)

    assert summary.overall_status == "FAIL"
    checks = pd.read_parquet(Path(summary.audit_checks_path))
    weighting = checks[checks["check_id"] == "trade_weighted_robustness_labeled"].iloc[0]
    assert weighting["status"] == "FAIL"


def test_final_audit_fails_when_event_family_purge_missing(tmp_path: Path) -> None:
    config = load_final_audit_config(_write_fixture(tmp_path, missing_event_family_purge=True))

    summary = build_final_audit(config)

    assert summary.overall_status == "FAIL"
    checks = pd.read_parquet(Path(summary.audit_checks_path))
    purge = checks[checks["check_id"] == "event_family_purged_sensitivity_present"].iloc[0]
    assert purge["status"] == "FAIL"


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
    iid_inference: bool = False,
    expected_models: tuple[str, ...] = ("raw", "platt"),
    bad_hierarchical_label: bool = False,
    missing_phase15_robustness: bool = False,
    bad_trade_weight_label: bool = False,
    missing_event_family_purge: bool = False,
    synthetic_no_edge: bool = False,
    future_quote_edge: bool = False,
) -> Path:
    raw_repo = tmp_path / "raw_repo"
    raw_repo.mkdir()
    subprocess.run(["git", "init"], cwd=raw_repo, check=True, capture_output=True)

    interim = tmp_path / "interim"
    processed = tmp_path / "processed"
    raw_baseline = tmp_path / "raw_baseline"
    walkforward = tmp_path / "walkforward"
    edge = tmp_path / "edge"
    inference = tmp_path / "inference"
    decomposition = tmp_path / "decomposition"
    robustness = tmp_path / "robustness"
    figures = tmp_path / "figures"
    tables = tmp_path / "tables"
    for path in (
        interim,
        processed,
        raw_baseline,
        walkforward,
        edge,
        inference,
        decomposition,
        robustness,
        figures,
        tables,
    ):
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
    _write_walkforward(
        walkforward,
        bad_prediction_key=bad_prediction_key,
        models=expected_models,
        bad_hierarchical_label=bad_hierarchical_label,
    )
    _write_edge(
        edge,
        bad_edge_side=bad_edge_side,
        synthetic_no_edge=synthetic_no_edge,
        future_quote_edge=future_quote_edge,
    )
    _write_inference(inference, iid_inference=iid_inference)
    _write_decomposition(decomposition, models=expected_models)
    _write_reporting(figures, tables)
    _write_robustness(
        robustness,
        missing_phase15=missing_phase15_robustness,
        bad_trade_weight_label=bad_trade_weight_label,
        missing_event_family_purge=missing_event_family_purge,
    )

    edge_side = '"YES"' if quote_edge_side else "YES"
    config_path = tmp_path / "final_audit.yaml"
    config_path.write_text(
        f"""
inputs:
  raw_repo_path: {raw_repo}
  interim_summary_path: {interim / "summary.json"}
  interim_contracts_path: {interim / "contracts.parquet"}
  interim_price_observations_path: {interim / "price_observations.parquet"}
  quote_observations_path: {interim / "quote_observations.parquet"}
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
  inference_dir: {inference}
  decomposition_dir: {decomposition}
  robustness_dir: {robustness}
  figure_manifest_path: {figures / "figure_manifest.json"}
  table_manifest_path: {tables / "table_manifest.json"}
outputs:
  audit_dir: {tmp_path / "audit"}
  semantics_doc_path: {tmp_path / "docs" / "final_data_semantics.md"}
audit:
  expected_horizons: [1d]
  expected_models: [{", ".join(expected_models)}]
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
    pd.DataFrame(
        {
            "contract_id": ["C0"],
            "quote_ts": [pd.Timestamp("2023-12-01", tz="UTC")],
            "yes_bid": [0.4],
            "yes_ask": [0.42],
            "no_bid": [0.58],
            "no_ask": [0.60],
            "quote_source": ["fixture"],
            "depth_available": [False],
        }
    ).to_parquet(interim / "quote_observations.parquet", index=False)
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
            "close_time": [
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
            "close_time": [
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


def _write_walkforward(
    walkforward: Path,
    *,
    bad_prediction_key: bool,
    models: tuple[str, ...],
    bad_hierarchical_label: bool,
) -> None:
    predictions = []
    for model in models:
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
                "close_time": pd.Timestamp("2024-01-10", tz="UTC"),
                "observed_outcome": 1,
                "raw_probability": 0.7,
                "predicted_probability": 0.75,
            }
        )
    pd.DataFrame(predictions).to_parquet(walkforward / "predictions.parquet", index=False)
    pd.DataFrame(
        {
            "fold_id": ["fold_2024_01"] * len(models),
            "model_name": list(models),
            "fit_row_count": [1] * len(models),
            "is_experimental": [
                False
                if model != "hierarchical_eb" or bad_hierarchical_label
                else True
                for model in models
            ],
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


def _write_edge(
    edge: Path,
    *,
    bad_edge_side: bool,
    synthetic_no_edge: bool,
    future_quote_edge: bool,
) -> None:
    pd.DataFrame(
        {
            "trade_side": [
                "MAYBE" if bad_edge_side else "YES",
                "NO" if synthetic_no_edge else "YES",
            ],
            "effective_cost": [0.55, 0.56],
            "net_edge": [0.2, 0.19],
            "entry_price_source": [
                "transaction_snapshot_proxy",
                "synthetic_no_complement" if synthetic_no_edge else "transaction_snapshot_proxy",
            ],
            "forecast_ts": [
                pd.Timestamp("2024-01-05", tz="UTC"),
                pd.Timestamp("2024-01-05", tz="UTC"),
            ],
            "quote_ts": [
                pd.Timestamp("2024-01-04", tz="UTC"),
                pd.Timestamp("2024-01-06" if future_quote_edge else "2024-01-04", tz="UTC"),
            ],
            "capacity_source": ["fixed_config_assumption_no_order_book_depth"] * 2,
        }
    ).to_parquet(edge / "edge_candidates.parquet", index=False)
    pd.DataFrame(
        {
            "execution_mode": ["transaction_proxy"],
            "quote_mode_used": [False],
            "input_prediction_rows": [2],
            "rows_with_attached_quote": [0],
            "candidate_rows": [2],
            "no_side_candidate_rows": [1 if synthetic_no_edge else 0],
            "synthetic_no_candidate_rows": [1 if synthetic_no_edge else 0],
            "future_quote_candidate_rows": [1 if future_quote_edge else 0],
            "quote_depth_available": [False],
            "capacity_source": ["fixed_config_assumption_no_order_book_depth"],
            "executable_profit_evidence": [False],
            "screen_language": ["simulated_expected_value_screen"],
            "limitations": ["simulated screen without order-book depth"],
        }
    ).to_parquet(edge / "executability_audit.parquet", index=False)
    pd.DataFrame(
        {
            "fee_schedule_id": ["kalshi_proxy_default"],
            "start_date": ["1900-01-01"],
            "end_date": [None],
            "formula": ["kalshi_proxy"],
            "fee_rate": [0.07],
            "source_status": ["proxy_assumption"],
            "source_note": ["fixture proxy"],
            "candidate_row_count": [2],
        }
    ).to_parquet(edge / "fee_schedule_audit.parquet", index=False)
    pd.DataFrame(
        {
            "trade_side": ["YES"],
            "model_name": ["raw"],
            "friction_tier": ["fee_only"],
            "candidate_row_count": [2],
            "selected_row_count": [1],
            "assumed_contracts": [1.0],
            "capacity_source": ["fixed_config_assumption_no_order_book_depth"],
            "selected_total_simulated_realized_net": [0.1],
            "selected_total_effective_cost": [0.5],
        }
    ).to_parquet(edge / "capacity_summary.parquet", index=False)
    pd.DataFrame(
        {
            "model_name": ["raw"],
            "friction_tier": ["fee_only"],
            "trade_side": ["YES"],
            "forecast_ts": [pd.Timestamp("2024-01-05", tz="UTC")],
            "row_id": [1],
            "simulated_realized_net_total": [0.1],
            "cumulative_simulated_pnl": [0.1],
            "pnl_label": ["simulated_assumption_dependent"],
        }
    ).to_parquet(edge / "simulated_pnl.parquet", index=False)
    (edge / "summary.json").write_text(
        json.dumps(
            {
                "candidate_row_count": 2,
                "trade_side": "yes_only",
                "effective_config": {
                    "screen": {"allow_synthetic_no": False},
                    "capacity": {"source": "fixed_config_assumption_no_order_book_depth"},
                },
                "limitations": [
                    "outputs are simulated expected-value screens and not executable profits"
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_inference(inference: Path, *, iid_inference: bool) -> None:
    bootstrap_unit = "row_id" if iid_inference else "event_family_id"
    (inference / "summary.json").write_text(
        json.dumps(
            {
                "bootstrap_unit": bootstrap_unit,
                "bootstrap_iterations": 20,
                "limitations": ["event-family clustered inference"],
            }
        ),
        encoding="utf-8",
    )
    score = pd.DataFrame(
        {
            "model_name": ["raw", "platt"],
            "metric_name": ["brier_score", "brier_score"],
            "grouping_name": ["overall", "overall"],
            "group_key": ["overall", "overall"],
            "estimate": [0.1, 0.09],
            "ci_lower": [0.08, 0.07],
            "ci_upper": [0.12, 0.11],
            "effective_cluster_count": [2.0, 2.0],
            "bootstrap_unit": [bootstrap_unit, bootstrap_unit],
            "aggregation_mode": ["equal_contract", "equal_contract"],
        }
    )
    paired = pd.DataFrame(
        {
            "baseline_model": ["raw"],
            "model_name": ["platt"],
            "metric_name": ["brier_score"],
            "grouping_name": ["overall"],
            "group_key": ["overall"],
            "estimate_delta": [-0.01],
            "ci_lower": [-0.02],
            "ci_upper": [-0.001],
            "p_value": [0.02],
            "q_value": [0.03],
            "effective_cluster_count": [2.0],
            "bootstrap_unit": [bootstrap_unit],
            "aggregation_mode": ["equal_contract"],
        }
    )
    calibration = pd.DataFrame(
        {
            "model_name": ["raw"],
            "parameter": ["calibration_slope"],
            "grouping_name": ["horizon"],
            "group_key": ["1d"],
            "estimate": [1.0],
            "ci_lower": [0.9],
            "ci_upper": [1.1],
            "p_value": [1.0],
            "effective_cluster_count": [2.0],
            "bootstrap_unit": [bootstrap_unit],
        }
    )
    diagnostics = pd.DataFrame(
        {
            "model_name": ["platt"],
            "metric_name": ["brier_score"],
            "grouping_name": ["overall"],
            "group_key": ["overall"],
            "cluster_count": [2],
            "mean_cluster_loss_diff": [-0.01],
        }
    )
    score.to_parquet(inference / "score_intervals.parquet", index=False)
    paired.to_parquet(inference / "paired_score_differences.parquet", index=False)
    calibration.to_parquet(inference / "calibration_intervals.parquet", index=False)
    paired.to_parquet(inference / "multiple_comparison_adjustments.parquet", index=False)
    diagnostics.to_parquet(inference / "paired_loss_diagnostics.parquet", index=False)


def _write_reporting(figures: Path, tables: Path) -> None:
    manifest = {
        "effective_config": {"reporting": {"artifact_run_label": "full"}},
        "source_artifacts": {
            "walkforward": "data/artifacts/walkforward",
            "edge": "data/artifacts/edge_sim",
            "inference": "data/artifacts/inference",
            "decomposition": "data/artifacts/decomposition",
        },
        "limitations": [
            "simulated edge screens",
            "taxonomy coverage remains limited",
            "clustered inference intervals included",
            "Murphy decomposition includes binning residuals",
        ],
    }
    (figures / "figure_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tables / "table_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    pd.DataFrame(
        {
            "model_name": ["raw", "platt"],
            "brier_score_ci_lower": [0.08, 0.07],
            "brier_delta_p_value": [None, 0.02],
            "brier_delta_q_value": [None, 0.03],
            "log_loss_ci_lower": [0.2, 0.19],
            "ece_delta_q_value": [None, 0.04],
            "effective_cluster_count": [2.0, 2.0],
        }
    ).to_csv(tables / "overall_score_comparison.csv", index=False)
    pd.DataFrame(
        {
            "model_name": ["raw"],
            "calibration_intercept_ci_lower": [-0.1],
            "calibration_intercept_p_value": [0.5],
            "calibration_slope_ci_lower": [0.9],
            "calibration_slope_p_value": [1.0],
            "effective_cluster_count": [2.0],
        }
    ).to_csv(tables / "calibration_intercept_slope.csv", index=False)
    pd.DataFrame(
        {
            "model_name": ["raw", "platt"],
            "row_count": [1, 1],
            "raw_brier": [0.12, 0.10],
            "reliability": [0.02, 0.01],
            "resolution": [0.03, 0.03],
            "uncertainty": [0.25, 0.25],
            "decomposed_brier": [0.24, 0.23],
            "binning_residual": [-0.12, -0.13],
        }
    ).to_csv(tables / "murphy_decomposition.csv", index=False)


def _write_decomposition(decomposition: Path, *, models: tuple[str, ...]) -> None:
    (decomposition / "summary.json").write_text(
        json.dumps(
            {
                "limitations": [
                    "Murphy decomposition uses fixed-width bins and reports binning residuals"
                ]
            }
        ),
        encoding="utf-8",
    )
    decomposition_rows = []
    bin_rows = []
    for index, model in enumerate(models):
        reliability = 0.01 + index * 0.001
        resolution = 0.03 + index * 0.001
        uncertainty = 0.25
        decomposed = reliability - resolution + uncertainty
        decomposition_rows.append(
            {
                "model_name": model,
                "grouping_name": "overall",
                "group_key": "overall",
                "row_count": 1,
                "reliability": reliability,
                "resolution": resolution,
                "uncertainty": uncertainty,
                "decomposed_brier": decomposed,
                "raw_brier": 0.12,
                "binning_residual": 0.12 - decomposed,
            }
        )
        bin_rows.append(
            {
                "model_name": model,
                "grouping_name": "overall",
                "bin_index": 0,
                "row_count": 1,
                "mean_probability": 0.7,
                "observed_frequency": 1.0,
                "is_empty": False,
                "is_sparse": False,
            }
        )
    pd.DataFrame(decomposition_rows).to_parquet(
        decomposition / "murphy_decomposition.parquet",
        index=False,
    )
    pd.DataFrame(bin_rows).to_parquet(decomposition / "murphy_bins.parquet", index=False)


def _write_robustness(
    robustness: Path,
    *,
    missing_phase15: bool = False,
    bad_trade_weight_label: bool = False,
    missing_event_family_purge: bool = False,
) -> None:
    artifact_paths = {}
    if not missing_phase15:
        staleness = pd.DataFrame(
            {
                "filter_name": ["all_rows"],
                "model_name": ["raw"],
                "horizon_name": ["1d"],
                "row_count": [1],
                "non_confirmatory": [True],
                "analysis_label": ["robustness_non_confirmatory"],
            }
        )
        weighting = pd.DataFrame(
            {
                "model_name": ["raw", "raw"],
                "horizon_name": ["1d", "1d"],
                "aggregation_mode": ["equal_contract", "trade_weighted"],
                "row_count": [1, 1],
                "non_confirmatory": [True, not bad_trade_weight_label],
                "analysis_label": [
                    "robustness_non_confirmatory",
                    "bad_label" if bad_trade_weight_label else "robustness_non_confirmatory",
                ],
            }
        )
        policies = ["report_only_all_test_rows"]
        if not missing_event_family_purge:
            policies.append("drop_overlapping_event_families")
        event_family = pd.DataFrame(
            {
                "policy_name": policies,
                "model_name": ["raw"] * len(policies),
                "horizon_name": ["1d"] * len(policies),
                "row_count": [1] * len(policies),
                "non_confirmatory": [True] * len(policies),
                "analysis_label": ["robustness_non_confirmatory"] * len(policies),
            }
        )
        full_runs = pd.DataFrame(
            {
                "variant_name": ["last_trade_only"],
                "status": ["completed"],
                "processed_dir": [str(robustness / "full_snapshot_variants" / "last_trade_only")],
                "artifact_dir": [str(robustness / "full_snapshot_variants" / "last_trade_only")],
                "non_confirmatory": [True],
                "analysis_label": ["robustness_non_confirmatory"],
            }
        )
        full_metrics = pd.DataFrame(
            {
                "variant_name": ["last_trade_only"],
                "model_name": ["raw"],
                "metric_name": ["brier_score"],
                "value": [0.1],
                "non_confirmatory": [True],
                "analysis_label": ["robustness_non_confirmatory"],
            }
        )
        frames = {
            "staleness_filter_sensitivity": staleness,
            "weighting_sensitivity": weighting,
            "event_family_exclusion_sensitivity": event_family,
            "full_snapshot_variant_runs": full_runs,
            "full_snapshot_variant_metrics": full_metrics,
        }
        for name, frame in frames.items():
            path = robustness / f"{name}.parquet"
            frame.to_parquet(path, index=False)
            artifact_paths[name] = str(path)
    (robustness / "summary.json").write_text(
        json.dumps(
            {
                "source_artifacts": {
                    "walkforward": "data/artifacts/walkforward",
                    "edge": "data/artifacts/edge_sim",
                },
                "artifact_paths": artifact_paths,
                "limitations": ["diagnostic outputs only and not confirmatory"],
            }
        ),
        encoding="utf-8",
    )
