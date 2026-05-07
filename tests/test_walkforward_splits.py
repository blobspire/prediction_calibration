import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from predmkt.validation.splits import (
    SplitValidationError,
    assign_walkforward_splits,
    build_walkforward_splits,
    detect_event_family_leakage,
    load_validation_config,
    make_walkforward_folds,
    normalize_split_panel,
    validate_split_integrity,
)


def test_load_validation_config(tmp_path: Path) -> None:
    config_path = tmp_path / "validation.yaml"
    config_path.write_text(_config_text(tmp_path), encoding="utf-8")

    config = load_validation_config(config_path)

    assert config.panel_path == tmp_path / "panel.parquet"
    assert config.mode == "expanding"
    assert config.first_test_month == "2024-01"
    assert config.validation_window_months == 1
    assert config.event_family_rule == "strict_overlap"
    assert config.config_sha256


def test_expanding_monthly_folds_are_time_ordered_and_growing(tmp_path: Path) -> None:
    config = _config(tmp_path)
    panel, _ = normalize_split_panel(_panel(), config)

    folds = make_walkforward_folds(panel, config)
    assignments = assign_walkforward_splits(panel, folds)
    integrity = validate_split_integrity(assignments, folds)

    assert [fold.fold_id for fold in folds] == ["fold_2024_01", "fold_2024_02"]
    assert integrity["time_order_valid"].all()
    assert integrity["row_exclusivity_valid"].all()
    assert integrity["train_row_count"].tolist()[0] < integrity["train_row_count"].tolist()[1]

    for fold_id in assignments["fold_id"].unique():
        fold_rows = assignments[assignments["fold_id"] == fold_id]
        train_max = fold_rows.loc[fold_rows["split"] == "train", "forecast_ts"].max()
        validation_min = fold_rows.loc[
            fold_rows["split"] == "validation", "forecast_ts"
        ].min()
        validation_max = fold_rows.loc[
            fold_rows["split"] == "validation", "forecast_ts"
        ].max()
        test_min = fold_rows.loc[fold_rows["split"] == "test", "forecast_ts"].min()

        assert train_max < validation_min
        assert validation_max < test_min


def test_split_assignment_is_deterministic_after_input_shuffle(tmp_path: Path) -> None:
    config = _config(tmp_path)
    shuffled = _panel().sample(frac=1.0, random_state=123).reset_index(drop=True)

    panel_a, _ = normalize_split_panel(_panel(), config)
    panel_b, _ = normalize_split_panel(shuffled, config)

    folds_a = make_walkforward_folds(panel_a, config)
    folds_b = make_walkforward_folds(panel_b, config)
    assignments_a = assign_walkforward_splits(panel_a, folds_a)
    assignments_b = assign_walkforward_splits(panel_b, folds_b)

    keys = ["fold_id", "split", "contract_id", "horizon", "forecast_ts"]
    assert assignments_a[keys].sort_values(keys).reset_index(drop=True).equals(
        assignments_b[keys].sort_values(keys).reset_index(drop=True)
    )


def test_event_family_leakage_detection_strict_overlap(tmp_path: Path) -> None:
    config = _config(tmp_path)
    panel, _ = normalize_split_panel(_panel(), config)
    fold = make_walkforward_folds(panel, config)[0]
    assignments = assign_walkforward_splits(panel, [fold])

    leakage = detect_event_family_leakage(assignments)

    assert "E_SHARED" in set(leakage["event_family_id"])
    assert leakage.loc[leakage["event_family_id"] == "E_SHARED", "splits"].iloc[0] == (
        "test,train,validation"
    )


def test_no_event_family_leakage_when_families_are_disjoint(tmp_path: Path) -> None:
    config = _config(tmp_path)
    source = _panel()
    source["event_family_id"] = [f"E{i}" for i in range(len(source))]
    panel, _ = normalize_split_panel(source, config)
    fold = make_walkforward_folds(panel, config)[0]
    assignments = assign_walkforward_splits(panel, [fold])

    assert detect_event_family_leakage(assignments).empty


def test_event_family_falls_back_to_event_id(tmp_path: Path) -> None:
    config = _config(tmp_path)
    source = _panel().drop(columns=["event_family_id"])

    normalized, source_name = normalize_split_panel(source, config)

    assert source_name == "event_id_fallback"
    assert normalized["event_family_id"].notna().all()


def test_missing_timestamp_column_fails(tmp_path: Path) -> None:
    config = _config(tmp_path)

    with pytest.raises(SplitValidationError, match="missing required columns"):
        normalize_split_panel(_panel().drop(columns=["forecast_ts"]), config)


def test_build_walkforward_splits_writes_artifacts(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.parquet"
    _panel().to_parquet(panel_path, index=False)
    config_path = tmp_path / "validation.yaml"
    config_path.write_text(_config_text(tmp_path), encoding="utf-8")
    config = load_validation_config(config_path)

    summary = build_walkforward_splits(config)

    assert summary.fold_count == 2
    assert summary.time_order_valid is True
    assert summary.row_exclusivity_valid is True
    assert summary.event_family_source == "event_family_id"
    assert summary.leakage_event_family_count > 0
    assert (tmp_path / "splits.parquet").exists()
    assert (tmp_path / "integrity.parquet").exists()
    assert (tmp_path / "summary.json").exists()

    splits = pq.read_table(tmp_path / "splits.parquet").to_pandas()
    assert {"fold_id", "split", "row_id", "contract_id", "horizon", "forecast_ts"} <= set(
        splits.columns
    )

    summary_json = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary_json["effective_config"]["split"]["first_test_month"] == "2024-01"


def _panel() -> pd.DataFrame:
    rows = []
    for month in pd.period_range("2023-09", "2024-03", freq="M"):
        for offset in range(2):
            rows.append(
                {
                    "contract_id": f"C_{month}_{offset}",
                    "event_id": f"EV_{month}_{offset}",
                    "event_family_id": "E_SHARED" if offset == 0 else f"E_{month}_{offset}",
                    "horizon_name": "1d" if offset == 0 else "7d",
                    "forecast_ts": pd.Timestamp(month.start_time, tz="UTC")
                    + pd.Timedelta(days=offset + 1),
                }
            )
    return pd.DataFrame(rows)


def _config(tmp_path: Path):
    config_path = tmp_path / "validation.yaml"
    config_path.write_text(_config_text(tmp_path), encoding="utf-8")
    config = load_validation_config(config_path)
    return replace(config, panel_path=tmp_path / "panel.parquet")


def _config_text(tmp_path: Path) -> str:
    return f"""
inputs:
  panel_path: {tmp_path / "panel.parquet"}
outputs:
  splits_path: {tmp_path / "splits.parquet"}
  integrity_path: {tmp_path / "integrity.parquet"}
  summary_path: {tmp_path / "summary.json"}
split:
  mode: expanding
  timestamp_column: forecast_ts
  train_start: auto
  first_test_month: "2024-01"
  validation_window: 1month
  test_window: 1month
  step: 1month
  exclude_incomplete_final_test_month: true
  limit_rows:
columns:
  contract_id_column: contract_id
  event_family_column: event_family_id
  event_family_fallback_column: event_id
  horizon_columns:
    - horizon_name
    - horizon_bucket
leakage:
  event_family_rule: strict_overlap
"""
