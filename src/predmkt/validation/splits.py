"""Walk-forward split construction and integrity checks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


@dataclass(frozen=True)
class ValidationConfig:
    """Configuration for forecast-time walk-forward splits."""

    panel_path: Path
    splits_path: Path
    integrity_path: Path
    summary_path: Path
    mode: str
    timestamp_column: str
    train_start: str
    first_test_month: str
    validation_window_months: int
    test_window_months: int
    step_months: int
    exclude_incomplete_final_test_month: bool
    contract_id_column: str
    event_family_column: str
    event_family_fallback_column: str
    horizon_columns: tuple[str, ...]
    event_family_rule: str
    limit_rows: int | None = None
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class WalkForwardFold:
    """Timestamp boundaries for one walk-forward fold."""

    fold_id: str
    train_start_ts: pd.Timestamp
    train_end_ts: pd.Timestamp
    validation_start_ts: pd.Timestamp
    validation_end_ts: pd.Timestamp
    test_start_ts: pd.Timestamp
    test_end_ts: pd.Timestamp


@dataclass(frozen=True)
class WalkForwardSummary:
    """Summary written after split construction."""

    input_panel_path: str
    input_row_count: int
    split_assignment_row_count: int
    fold_count: int
    event_family_source: str
    leakage_event_family_count: int
    time_order_valid: bool
    row_exclusivity_valid: bool
    artifact_paths: dict[str, str]
    effective_config: dict[str, Any]
    limitations: list[str]


class SplitValidationError(ValueError):
    """Raised when walk-forward split inputs or outputs violate invariants."""


def load_validation_config(path: Path) -> ValidationConfig:
    """Load walk-forward validation configuration from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"validation config must be a mapping: {path}")

    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    split = _mapping(raw, "split")
    columns = _mapping(raw, "columns")
    leakage = _mapping(raw, "leakage")

    mode = str(_required(split, "mode"))
    if mode != "expanding":
        raise ValueError("validation.split.mode currently supports only 'expanding'")

    event_family_rule = str(_required(leakage, "event_family_rule"))
    if event_family_rule != "strict_overlap":
        raise ValueError("validation.leakage.event_family_rule must be 'strict_overlap'")

    validation_window_months = _parse_month_window(_required(split, "validation_window"))
    test_window_months = _parse_month_window(_required(split, "test_window"))
    step_months = _parse_month_window(_required(split, "step"))
    if validation_window_months <= 0 or test_window_months <= 0 or step_months <= 0:
        raise ValueError("validation split windows must be positive")

    return ValidationConfig(
        panel_path=Path(_required(inputs, "panel_path")),
        splits_path=Path(_required(outputs, "splits_path")),
        integrity_path=Path(_required(outputs, "integrity_path")),
        summary_path=Path(_required(outputs, "summary_path")),
        mode=mode,
        timestamp_column=str(_required(split, "timestamp_column")),
        train_start=str(_required(split, "train_start")),
        first_test_month=str(_required(split, "first_test_month")),
        validation_window_months=validation_window_months,
        test_window_months=test_window_months,
        step_months=step_months,
        exclude_incomplete_final_test_month=bool(
            _required(split, "exclude_incomplete_final_test_month")
        ),
        contract_id_column=str(_required(columns, "contract_id_column")),
        event_family_column=str(_required(columns, "event_family_column")),
        event_family_fallback_column=str(_required(columns, "event_family_fallback_column")),
        horizon_columns=tuple(str(column) for column in _required(columns, "horizon_columns")),
        event_family_rule=event_family_rule,
        limit_rows=_optional_int(split.get("limit_rows")),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def build_walkforward_splits(config: ValidationConfig) -> WalkForwardSummary:
    """Build split artifacts from a configured contract-horizon panel."""

    panel = pd.read_parquet(config.panel_path)
    if config.limit_rows is not None:
        if config.limit_rows <= 0:
            raise SplitValidationError("limit_rows must be positive when provided")
        panel = panel.head(config.limit_rows).copy()

    input_row_count = len(panel)
    if input_row_count == 0:
        raise SplitValidationError("walk-forward input panel is empty")

    normalized, event_family_source = normalize_split_panel(panel, config)
    folds = make_walkforward_folds(normalized, config)
    if not folds:
        raise SplitValidationError("no eligible walk-forward folds were generated")

    assignments = assign_walkforward_splits(normalized, folds)
    integrity = validate_split_integrity(assignments, folds)
    leakage_count = int(integrity["leakage_event_family_count"].sum())
    time_order_valid = bool(integrity["time_order_valid"].all())
    row_exclusivity_valid = bool(integrity["row_exclusivity_valid"].all())
    if not time_order_valid or not row_exclusivity_valid:
        raise SplitValidationError("walk-forward split integrity validation failed")

    config.splits_path.parent.mkdir(parents=True, exist_ok=True)
    config.integrity_path.parent.mkdir(parents=True, exist_ok=True)
    config.summary_path.parent.mkdir(parents=True, exist_ok=True)
    assignments.to_parquet(config.splits_path, index=False)
    integrity.to_parquet(config.integrity_path, index=False)

    summary = WalkForwardSummary(
        input_panel_path=str(config.panel_path),
        input_row_count=input_row_count,
        split_assignment_row_count=len(assignments),
        fold_count=len(folds),
        event_family_source=event_family_source,
        leakage_event_family_count=leakage_count,
        time_order_valid=time_order_valid,
        row_exclusivity_valid=row_exclusivity_valid,
        artifact_paths={
            "splits": str(config.splits_path),
            "integrity": str(config.integrity_path),
            "summary": str(config.summary_path),
        },
        effective_config=_effective_config(config),
        limitations=[
            "Splits are generated by forecast_ts only; recalibrators and model evaluation are "
            "not implemented here.",
            "Event-family leakage checks use the configured event_family_id when available and "
            "fall back to event_id for raw snapshot panels.",
            "Event-family checks use Phase 12 audited family IDs when present, with explicit "
            "event_id or contract_id fallbacks where regex grouping is unavailable.",
        ],
    )
    config.summary_path.write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def normalize_split_panel(
    panel: pd.DataFrame,
    config: ValidationConfig,
) -> tuple[pd.DataFrame, str]:
    """Return the canonical columns needed for split construction."""

    required = [config.timestamp_column, config.contract_id_column]
    missing = [column for column in required if column not in panel.columns]
    if missing:
        raise SplitValidationError(f"walk-forward input missing required columns: {missing}")

    horizon_column = _select_horizon_column(panel, config.horizon_columns)
    event_family_source = config.event_family_column
    if config.event_family_column in panel.columns:
        event_family = panel[config.event_family_column]
        if config.event_family_fallback_column in panel.columns:
            event_family = event_family.fillna(panel[config.event_family_fallback_column])
    elif config.event_family_fallback_column in panel.columns:
        event_family_source = f"{config.event_family_fallback_column}_fallback"
        event_family = panel[config.event_family_fallback_column]
    else:
        raise SplitValidationError(
            "walk-forward input missing event-family columns: "
            f"{config.event_family_column!r} and fallback "
            f"{config.event_family_fallback_column!r}"
        )

    normalized = pd.DataFrame(
        {
            "row_id": range(len(panel)),
            "contract_id": panel[config.contract_id_column].astype("string"),
            "horizon": panel[horizon_column].astype("string"),
            "forecast_ts": pd.to_datetime(panel[config.timestamp_column], utc=True, errors="raise"),
            "event_family_id": event_family.astype("string"),
        }
    )
    for optional_ts_column in ("close_time", "resolution_ts"):
        if optional_ts_column in panel.columns:
            normalized[optional_ts_column] = pd.to_datetime(
                panel[optional_ts_column],
                utc=True,
                errors="raise",
            )
    if normalized["forecast_ts"].isna().any():
        raise SplitValidationError("forecast_ts contains null values")
    if normalized["contract_id"].isna().any():
        raise SplitValidationError("contract_id contains null values")
    if normalized["horizon"].isna().any():
        raise SplitValidationError("horizon column contains null values")
    if normalized["event_family_id"].isna().any():
        raise SplitValidationError("event_family_id contains null values after fallback")

    normalized = normalized.sort_values(
        ["forecast_ts", "contract_id", "horizon", "row_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    return normalized, event_family_source


def make_walkforward_folds(
    panel: pd.DataFrame,
    config: ValidationConfig,
) -> list[WalkForwardFold]:
    """Generate deterministic expanding monthly folds."""

    min_ts = panel["forecast_ts"].min()
    max_ts = panel["forecast_ts"].max()
    test_start = pd.Timestamp(f"{config.first_test_month}-01", tz="UTC")
    train_start = (
        min_ts
        if config.train_start == "auto"
        else pd.Timestamp(config.train_start, tz="UTC")
    )
    folds: list[WalkForwardFold] = []

    while test_start <= max_ts:
        validation_end = test_start
        validation_start = validation_end - pd.DateOffset(
            months=config.validation_window_months
        )
        test_end = test_start + pd.DateOffset(months=config.test_window_months)
        if config.exclude_incomplete_final_test_month and max_ts < test_end:
            break

        train_end = validation_start
        fold = WalkForwardFold(
            fold_id=f"fold_{test_start.strftime('%Y_%m')}",
            train_start_ts=train_start,
            train_end_ts=train_end,
            validation_start_ts=validation_start,
            validation_end_ts=validation_end,
            test_start_ts=test_start,
            test_end_ts=test_end,
        )
        if _fold_has_rows(panel, fold):
            folds.append(fold)
        test_start = test_start + pd.DateOffset(months=config.step_months)

    return folds


def assign_walkforward_splits(
    panel: pd.DataFrame,
    folds: list[WalkForwardFold],
) -> pd.DataFrame:
    """Assign panel rows to train/validation/test for each fold."""

    pieces: list[pd.DataFrame] = []
    for fold in folds:
        split_masks = {
            "train": (panel["forecast_ts"] >= fold.train_start_ts)
            & (panel["forecast_ts"] < fold.train_end_ts),
            "validation": (panel["forecast_ts"] >= fold.validation_start_ts)
            & (panel["forecast_ts"] < fold.validation_end_ts),
            "test": (panel["forecast_ts"] >= fold.test_start_ts)
            & (panel["forecast_ts"] < fold.test_end_ts),
        }
        for split_name, mask in split_masks.items():
            split_rows = panel.loc[mask].copy()
            split_rows.insert(0, "split", split_name)
            split_rows.insert(0, "fold_id", fold.fold_id)
            pieces.append(split_rows)

    if not pieces:
        raise SplitValidationError("no split assignments were generated")
    return pd.concat(pieces, ignore_index=True)


def validate_split_integrity(
    assignments: pd.DataFrame,
    folds: list[WalkForwardFold],
) -> pd.DataFrame:
    """Validate time ordering, row exclusivity, and event-family leakage."""

    rows: list[dict[str, Any]] = []
    for fold in folds:
        fold_rows = assignments[assignments["fold_id"] == fold.fold_id]
        split_counts = fold_rows.groupby("split", observed=True).size().to_dict()
        row_split_counts = fold_rows.groupby("row_id", observed=True)["split"].nunique()
        duplicate_row_count = int((row_split_counts > 1).sum())

        leakage = detect_event_family_leakage(fold_rows)
        time_order_valid = _time_order_valid(fold_rows)
        rows.append(
            {
                "fold_id": fold.fold_id,
                "train_start_ts": fold.train_start_ts,
                "train_end_ts": fold.train_end_ts,
                "validation_start_ts": fold.validation_start_ts,
                "validation_end_ts": fold.validation_end_ts,
                "test_start_ts": fold.test_start_ts,
                "test_end_ts": fold.test_end_ts,
                "train_row_count": int(split_counts.get("train", 0)),
                "validation_row_count": int(split_counts.get("validation", 0)),
                "test_row_count": int(split_counts.get("test", 0)),
                "time_order_valid": time_order_valid,
                "row_exclusivity_valid": duplicate_row_count == 0,
                "duplicate_row_count": duplicate_row_count,
                "leakage_event_family_count": int(len(leakage)),
                "leakage_event_family_examples": ",".join(
                    leakage["event_family_id"].head(10).astype(str).tolist()
                ),
            }
        )
    return pd.DataFrame(rows)


def detect_event_family_leakage(fold_assignments: pd.DataFrame) -> pd.DataFrame:
    """Return families appearing in more than one split within a fold."""

    if fold_assignments.empty:
        return pd.DataFrame(columns=["event_family_id", "splits", "row_count"])
    grouped = (
        fold_assignments.groupby("event_family_id", observed=True)
        .agg(
            splits=("split", lambda values: ",".join(sorted(set(values)))),
            split_count=("split", "nunique"),
            row_count=("row_id", "count"),
        )
        .reset_index()
    )
    return grouped[grouped["split_count"] > 1][
        ["event_family_id", "splits", "row_count"]
    ].reset_index(drop=True)


def _fold_has_rows(panel: pd.DataFrame, fold: WalkForwardFold) -> bool:
    train_count = (
        (panel["forecast_ts"] >= fold.train_start_ts)
        & (panel["forecast_ts"] < fold.train_end_ts)
    ).sum()
    validation_count = (
        (panel["forecast_ts"] >= fold.validation_start_ts)
        & (panel["forecast_ts"] < fold.validation_end_ts)
    ).sum()
    test_count = (
        (panel["forecast_ts"] >= fold.test_start_ts)
        & (panel["forecast_ts"] < fold.test_end_ts)
    ).sum()
    return bool(train_count > 0 and validation_count > 0 and test_count > 0)


def _time_order_valid(fold_rows: pd.DataFrame) -> bool:
    split_times = {
        split: fold_rows.loc[fold_rows["split"] == split, "forecast_ts"]
        for split in ("train", "validation", "test")
    }
    if any(times.empty for times in split_times.values()):
        return False
    return bool(
        split_times["train"].max()
        < split_times["validation"].min()
        <= split_times["validation"].max()
        < split_times["test"].min()
    )


def _select_horizon_column(panel: pd.DataFrame, candidates: tuple[str, ...]) -> str:
    for column in candidates:
        if column in panel.columns:
            return column
    raise SplitValidationError(
        f"walk-forward input missing horizon column; tried {list(candidates)}"
    )


def _parse_month_window(value: object) -> int:
    text = str(value).strip().lower().replace(" ", "")
    for suffix in ("months", "month"):
        if text.endswith(suffix):
            return int(text[: -len(suffix)])
    raise ValueError(f"expected month window like '1month', got {value!r}")


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"validation config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"validation config missing required key: {key}")
    return raw[key]


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _effective_config(config: ValidationConfig) -> dict[str, Any]:
    return {
        "inputs": {"panel_path": str(config.panel_path)},
        "outputs": {
            "splits_path": str(config.splits_path),
            "integrity_path": str(config.integrity_path),
            "summary_path": str(config.summary_path),
        },
        "split": {
            "mode": config.mode,
            "timestamp_column": config.timestamp_column,
            "train_start": config.train_start,
            "first_test_month": config.first_test_month,
            "validation_window": f"{config.validation_window_months}month",
            "test_window": f"{config.test_window_months}month",
            "step": f"{config.step_months}month",
            "exclude_incomplete_final_test_month": config.exclude_incomplete_final_test_month,
            "limit_rows": config.limit_rows,
        },
        "columns": {
            "contract_id_column": config.contract_id_column,
            "event_family_column": config.event_family_column,
            "event_family_fallback_column": config.event_family_fallback_column,
            "horizon_columns": list(config.horizon_columns),
        },
        "leakage": {"event_family_rule": config.event_family_rule},
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }
