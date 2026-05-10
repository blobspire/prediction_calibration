"""Murphy-style Brier decomposition from saved forecast artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]

from predmkt.metrics.scoring import brier_score


@dataclass(frozen=True)
class DecompositionConfig:
    """Config for Murphy-style decomposition artifacts."""

    predictions_path: Path
    artifact_dir: Path
    probability_column: str
    outcome_column: str
    model_column: str
    bin_count: int
    min_bin_count: int
    min_rows: int
    groupings: tuple[dict[str, Any], ...]
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class DecompositionSummary:
    """Summary metadata for a decomposition run."""

    predictions_path: str
    artifact_dir: str
    input_row_count: int
    model_names: list[str]
    group_count: int
    bin_row_count: int
    config_sha256: str | None
    artifact_paths: dict[str, str]
    effective_config: dict[str, Any]
    limitations: list[str]


def load_decomposition_config(path: Path) -> DecompositionConfig:
    """Load decomposition settings from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"decomposition config must be a mapping: {path}")
    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    columns = _mapping(raw, "columns")
    decomposition = _mapping(raw, "decomposition")
    return DecompositionConfig(
        predictions_path=Path(_required(inputs, "predictions_path")),
        artifact_dir=Path(_required(outputs, "artifact_dir")),
        probability_column=str(_required(columns, "probability_column")),
        outcome_column=str(_required(columns, "outcome_column")),
        model_column=str(_required(columns, "model_column")),
        bin_count=int(_required(decomposition, "bin_count")),
        min_bin_count=int(_required(decomposition, "min_bin_count")),
        min_rows=int(_required(decomposition, "min_rows")),
        groupings=tuple(
            {
                "name": str(_required(grouping, "name")),
                "columns": tuple(str(column) for column in grouping.get("columns", [])),
            }
            for grouping in _required(decomposition, "groupings")
        ),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def evaluate_decomposition(config: DecompositionConfig) -> DecompositionSummary:
    """Write Murphy-style decomposition artifacts from saved predictions."""

    _validate_config(config)
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths = {
        "murphy_decomposition": config.artifact_dir / "murphy_decomposition.parquet",
        "murphy_bins": config.artifact_dir / "murphy_bins.parquet",
        "summary": config.artifact_dir / "summary.json",
    }
    predictions = pd.read_parquet(config.predictions_path)
    required = {
        config.probability_column,
        config.outcome_column,
        config.model_column,
    }
    for grouping in config.groupings:
        required.update(grouping["columns"])
    missing = sorted(required - set(predictions.columns))
    if missing:
        raise ValueError(f"prediction artifact missing decomposition columns: {missing}")
    predictions = predictions.copy()
    predictions[config.probability_column] = predictions[config.probability_column].astype(float)
    predictions[config.outcome_column] = predictions[config.outcome_column].astype(float)

    decomposition_rows: list[dict[str, Any]] = []
    bin_rows: list[dict[str, Any]] = []
    for grouping in config.groupings:
        grouping_name = str(grouping["name"])
        grouping_columns = list(grouping["columns"])
        group_columns = [config.model_column, *grouping_columns]
        for key, frame in predictions.groupby(group_columns, dropna=False, observed=True):
            key_values = _key_values(key, group_columns)
            components, bins = murphy_decomposition(
                frame[config.probability_column].astype(float).tolist(),
                frame[config.outcome_column].astype(float).tolist(),
                bin_count=config.bin_count,
                min_bin_count=config.min_bin_count,
                min_rows=config.min_rows,
            )
            group_key = _group_key(frame, grouping_columns)
            base_row = {
                config.model_column: key_values[config.model_column],
                "grouping_name": grouping_name,
                "group_key": group_key,
            }
            for column in grouping_columns:
                base_row[column] = key_values[column]
            decomposition_rows.append({**base_row, **components})
            for bin_row in bins:
                bin_rows.append({**base_row, **bin_row})

    decomposition_df = pd.DataFrame(decomposition_rows)
    bins_df = pd.DataFrame(bin_rows)
    decomposition_df.to_parquet(artifact_paths["murphy_decomposition"], index=False)
    bins_df.to_parquet(artifact_paths["murphy_bins"], index=False)

    summary = DecompositionSummary(
        predictions_path=str(config.predictions_path),
        artifact_dir=str(config.artifact_dir),
        input_row_count=int(len(predictions)),
        model_names=sorted(predictions[config.model_column].astype(str).unique().tolist()),
        group_count=int(len(decomposition_df)),
        bin_row_count=int(len(bins_df)),
        config_sha256=config.config_sha256,
        artifact_paths={key: str(value) for key, value in artifact_paths.items()},
        effective_config=_effective_config(config),
        limitations=[
            "Murphy components use fixed-width probability bins from saved predictions; "
            "the Brier identity is approximate when bins contain varied probabilities.",
            "binning_residual is reported as raw_brier - decomposed_brier and should "
            "not be suppressed.",
            "No models are refit and no feature or snapshot methodology is changed.",
        ],
    )
    artifact_paths["summary"].write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def murphy_decomposition(
    probabilities: list[float],
    outcomes: list[float],
    *,
    bin_count: int,
    min_bin_count: int,
    min_rows: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return Murphy reliability, resolution, and uncertainty components."""

    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have the same length")
    if not probabilities:
        raise ValueError("decomposition requires at least one row")
    if bin_count <= 0:
        raise ValueError("bin_count must be positive")
    if min_bin_count < 0:
        raise ValueError("min_bin_count cannot be negative")
    row_count = len(probabilities)
    base_rate = sum(outcomes) / row_count
    totals = [0.0] * bin_count
    probability_totals = [0.0] * bin_count
    counts = [0] * bin_count
    for probability, outcome in zip(probabilities, outcomes, strict=True):
        if not 0.0 <= float(probability) <= 1.0:
            raise ValueError(f"probability must be in [0, 1]: {probability}")
        if float(outcome) not in (0.0, 1.0):
            raise ValueError(f"outcome must be binary 0/1: {outcome}")
        index = min(int(float(probability) * bin_count), bin_count - 1)
        totals[index] += float(outcome)
        probability_totals[index] += float(probability)
        counts[index] += 1

    reliability = 0.0
    resolution = 0.0
    bins: list[dict[str, Any]] = []
    for index in range(bin_count):
        count = counts[index]
        lower = index / bin_count
        upper = (index + 1) / bin_count
        if count == 0:
            bins.append(
                {
                    "bin_index": index,
                    "bin_lower": lower,
                    "bin_upper": upper,
                    "row_count": 0,
                    "bin_weight": 0.0,
                    "mean_probability": None,
                    "observed_frequency": None,
                    "reliability_component": 0.0,
                    "resolution_component": 0.0,
                    "is_empty": True,
                    "is_sparse": False,
                }
            )
            continue
        observed_frequency = totals[index] / count
        mean_probability = probability_totals[index] / count
        weight = count / row_count
        reliability_component = weight * (mean_probability - observed_frequency) ** 2
        resolution_component = weight * (observed_frequency - base_rate) ** 2
        reliability += reliability_component
        resolution += resolution_component
        bins.append(
            {
                "bin_index": index,
                "bin_lower": lower,
                "bin_upper": upper,
                "row_count": count,
                "bin_weight": weight,
                "mean_probability": mean_probability,
                "observed_frequency": observed_frequency,
                "reliability_component": reliability_component,
                "resolution_component": resolution_component,
                "is_empty": False,
                "is_sparse": count < min_bin_count,
            }
        )

    uncertainty = base_rate * (1.0 - base_rate)
    decomposed_brier = reliability - resolution + uncertainty
    raw_brier = brier_score(probabilities, outcomes)
    components = {
        "row_count": row_count,
        "outcome_rate": base_rate,
        "bin_count": bin_count,
        "nonempty_bin_count": sum(1 for count in counts if count > 0),
        "empty_bin_count": sum(1 for count in counts if count == 0),
        "sparse_bin_count": sum(1 for count in counts if 0 < count < min_bin_count),
        "reliability": reliability,
        "resolution": resolution,
        "uncertainty": uncertainty,
        "decomposed_brier": decomposed_brier,
        "raw_brier": raw_brier,
        "binning_residual": raw_brier - decomposed_brier,
        "status": "too_few_rows" if row_count < min_rows else "ok",
    }
    return components, bins


def _validate_config(config: DecompositionConfig) -> None:
    if config.bin_count <= 0:
        raise ValueError("decomposition bin_count must be positive")
    if config.min_bin_count < 0:
        raise ValueError("decomposition min_bin_count cannot be negative")
    if config.min_rows < 0:
        raise ValueError("decomposition min_rows cannot be negative")
    if not config.groupings:
        raise ValueError("decomposition groupings cannot be empty")


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"decomposition config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"decomposition config missing required key: {key}")
    return raw[key]


def _effective_config(config: DecompositionConfig) -> dict[str, Any]:
    return {
        "inputs": {"predictions_path": str(config.predictions_path)},
        "outputs": {"artifact_dir": str(config.artifact_dir)},
        "columns": {
            "probability_column": config.probability_column,
            "outcome_column": config.outcome_column,
            "model_column": config.model_column,
        },
        "decomposition": {
            "bin_count": config.bin_count,
            "min_bin_count": config.min_bin_count,
            "min_rows": config.min_rows,
            "groupings": [
                {"name": item["name"], "columns": list(item["columns"])}
                for item in config.groupings
            ],
        },
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }


def _key_values(key: Any, columns: list[str]) -> dict[str, Any]:
    if len(columns) == 1 and not isinstance(key, tuple):
        key = (key,)
    return dict(zip(columns, key, strict=True))


def _group_key(frame: pd.DataFrame, group_columns: list[str]) -> str:
    if not group_columns:
        return "overall"
    first = frame.iloc[0]
    return "|".join(str(first[column]) for column in group_columns)
