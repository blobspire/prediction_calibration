"""Run or dry-run the deterministic small-sample paper replication path."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


@dataclass(frozen=True)
class PipelineStage:
    """One executable small-sample pipeline stage."""

    name: str
    command: list[str]


@dataclass(frozen=True)
class ReplicationConfig:
    """Small-sample replication command configuration."""

    contracts_path: Path
    price_observations_path: Path
    processed_dir: Path
    artifact_dir: Path
    paper_dir: Path
    manifest_path: Path
    sampling_config: Path
    taxonomy_config: Path
    features_config: Path
    metrics_config: Path
    validation_config: Path
    models_config: Path
    backtest_config: Path
    reporting_config: Path
    limit_contracts: int
    limit_folds: int
    run_label: str
    non_confirmatory: bool
    start_from: str
    config_path: Path
    config_sha256: str


@dataclass(frozen=True)
class ReplicationManifest:
    """Manifest for a small-sample pipeline run or dry run."""

    dry_run: bool
    stage_count: int
    stages: list[dict[str, Any]]
    outputs: dict[str, str]
    effective_config: dict[str, Any]
    limitations: list[str]


def load_replication_config(path: Path) -> ReplicationConfig:
    """Load small-sample replication settings from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"replication config must be a mapping: {path}")
    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    configs = _mapping(raw, "configs")
    limits = _mapping(raw, "limits")
    replication = _mapping(raw, "replication")
    return ReplicationConfig(
        contracts_path=Path(_required(inputs, "contracts_path")),
        price_observations_path=Path(_required(inputs, "price_observations_path")),
        processed_dir=Path(_required(outputs, "processed_dir")),
        artifact_dir=Path(_required(outputs, "artifact_dir")),
        paper_dir=Path(_required(outputs, "paper_dir")),
        manifest_path=Path(_required(outputs, "manifest_path")),
        sampling_config=Path(_required(configs, "sampling")),
        taxonomy_config=Path(_required(configs, "taxonomy")),
        features_config=Path(_required(configs, "features")),
        metrics_config=Path(_required(configs, "metrics")),
        validation_config=Path(_required(configs, "validation")),
        models_config=Path(_required(configs, "models")),
        backtest_config=Path(_required(configs, "backtest")),
        reporting_config=Path(_required(configs, "reporting")),
        limit_contracts=int(_required(limits, "limit_contracts")),
        limit_folds=int(_required(limits, "limit_folds")),
        run_label=str(_required(replication, "run_label")),
        non_confirmatory=bool(_required(replication, "non_confirmatory")),
        start_from=str(_required(replication, "start_from")),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def build_stages(config: ReplicationConfig) -> list[PipelineStage]:
    """Return ordered small-sample pipeline commands."""

    processed = config.processed_dir
    artifacts = config.artifact_dir
    paper = config.paper_dir
    snapshot = processed / "contract_horizon_panel.parquet"
    snapshot_summary = processed / "contract_horizon_panel_summary.json"
    taxonomy = processed / "contract_horizon_panel_taxonomy.parquet"
    taxonomy_audit = processed / "contract_horizon_taxonomy_audit.parquet"
    taxonomy_examples = processed / "contract_horizon_taxonomy_examples.parquet"
    taxonomy_summary = processed / "contract_horizon_taxonomy_summary.json"
    features = processed / "modeling_panel.parquet"
    features_summary = processed / "modeling_panel_summary.json"
    splits = processed / "walkforward_splits.parquet"
    split_integrity = processed / "walkforward_split_integrity.parquet"
    split_summary = processed / "walkforward_split_summary.json"
    raw_baseline = artifacts / "raw_baseline"
    walkforward = artifacts / "walkforward"
    edge = artifacts / "edge_sim"
    figures = paper / "figures"
    tables = paper / "tables"

    py = sys.executable
    return [
        PipelineStage(
            "snapshot",
            [
                py,
                "scripts/build_snapshot_panel.py",
                "--config",
                str(config.sampling_config),
                "--contracts",
                str(config.contracts_path),
                "--price-observations",
                str(config.price_observations_path),
                "--output",
                str(snapshot),
                "--summary",
                str(snapshot_summary),
                "--limit-contracts",
                str(config.limit_contracts),
            ],
        ),
        PipelineStage(
            "taxonomy",
            [
                py,
                "scripts/build_taxonomy_panel.py",
                "--config",
                str(config.taxonomy_config),
                "--panel",
                str(snapshot),
                "--contracts",
                str(config.contracts_path),
                "--output",
                str(taxonomy),
                "--audit",
                str(taxonomy_audit),
                "--summary",
                str(taxonomy_summary),
                "--examples",
                str(taxonomy_examples),
            ],
        ),
        PipelineStage(
            "features",
            [
                py,
                "scripts/build_feature_panel.py",
                "--config",
                str(config.features_config),
                "--panel",
                str(taxonomy),
                "--price-observations",
                str(config.price_observations_path),
                "--contracts",
                str(config.contracts_path),
                "--output",
                str(features),
                "--summary",
                str(features_summary),
            ],
        ),
        PipelineStage(
            "raw_baseline",
            [
                py,
                "scripts/evaluate_raw.py",
                "--config",
                str(config.metrics_config),
                "--panel",
                str(features),
                "--artifact-dir",
                str(raw_baseline),
            ],
        ),
        PipelineStage(
            "splits",
            [
                py,
                "scripts/build_walkforward_splits.py",
                "--config",
                str(config.validation_config),
                "--panel",
                str(features),
                "--splits",
                str(splits),
                "--integrity",
                str(split_integrity),
                "--summary",
                str(split_summary),
            ],
        ),
        PipelineStage(
            "walkforward",
            [
                py,
                "scripts/fit_walkforward.py",
                "--config",
                str(config.models_config),
                "--panel",
                str(features),
                "--splits",
                str(splits),
                "--artifact-dir",
                str(walkforward),
                "--limit-folds",
                str(config.limit_folds),
            ],
        ),
        PipelineStage(
            "edge",
            [
                py,
                "scripts/run_edge_sim.py",
                "--config",
                str(config.backtest_config),
                "--predictions",
                str(walkforward / "predictions.parquet"),
                "--panel",
                str(features),
                "--artifact-dir",
                str(edge),
            ],
        ),
        PipelineStage(
            "figures",
            [
                py,
                "scripts/make_figures.py",
                "--config",
                str(config.reporting_config),
                "--raw-baseline-dir",
                str(raw_baseline),
                "--walkforward-dir",
                str(walkforward),
                "--edge-dir",
                str(edge),
                "--artifact-run-label",
                config.run_label,
                "--figure-dir",
                str(figures),
            ],
        ),
        PipelineStage(
            "tables",
            [
                py,
                "scripts/make_tables.py",
                "--config",
                str(config.reporting_config),
                "--raw-baseline-dir",
                str(raw_baseline),
                "--walkforward-dir",
                str(walkforward),
                "--edge-dir",
                str(edge),
                "--artifact-run-label",
                config.run_label,
                "--table-dir",
                str(tables),
            ],
        ),
    ]


def run_pipeline(config: ReplicationConfig, *, dry_run: bool) -> ReplicationManifest:
    """Run or dry-run the configured small-sample replication stages."""

    if config.limit_contracts <= 0 or config.limit_folds <= 0:
        raise ValueError("limit_contracts and limit_folds must be positive")
    stages = build_stages(config)
    stage_rows: list[dict[str, Any]] = []
    for stage in stages:
        row = {"name": stage.name, "command": stage.command, "status": "dry_run"}
        if not dry_run:
            completed = subprocess.run(stage.command, check=False)
            row["returncode"] = completed.returncode
            row["status"] = "completed" if completed.returncode == 0 else "failed"
            if completed.returncode != 0:
                stage_rows.append(row)
                manifest = _manifest(config, dry_run=dry_run, stages=stage_rows)
                _write_manifest(config, manifest)
                raise RuntimeError(f"small-sample pipeline failed at stage {stage.name}")
        stage_rows.append(row)
    manifest = _manifest(config, dry_run=dry_run, stages=stage_rows)
    _write_manifest(config, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/replication_small.yaml"),
        help="YAML small-sample replication config.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Write manifest only.")
    args = parser.parse_args()

    config = load_replication_config(args.config)
    manifest = run_pipeline(config, dry_run=args.dry_run)
    print(json.dumps(asdict(manifest), indent=2, sort_keys=True, default=str))
    return 0


def _manifest(
    config: ReplicationConfig,
    *,
    dry_run: bool,
    stages: list[dict[str, Any]],
) -> ReplicationManifest:
    return ReplicationManifest(
        dry_run=dry_run,
        stage_count=len(stages),
        stages=stages,
        outputs={
            "processed_dir": str(config.processed_dir),
            "artifact_dir": str(config.artifact_dir),
            "paper_dir": str(config.paper_dir),
            "manifest_path": str(config.manifest_path),
        },
        effective_config={
            "limits": {
                "limit_contracts": config.limit_contracts,
                "limit_folds": config.limit_folds,
            },
            "replication": {
                "run_label": config.run_label,
                "non_confirmatory": config.non_confirmatory,
                "start_from": config.start_from,
            },
            "config_path": str(config.config_path),
            "config_sha256": config.config_sha256,
        },
        limitations=[
            "This command produces a deterministic small-sample replication path, not "
            "confirmatory full-sample results.",
            "The pipeline starts from cleaned interim Kalshi tables and does not mutate "
            "data/raw/.",
            "Edge outputs remain simulated EV screens using proxy frictions and transaction "
            "snapshot prices.",
        ],
    )


def _write_manifest(config: ReplicationConfig, manifest: ReplicationManifest) -> None:
    config.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    config.manifest_path.write_text(
        json.dumps(asdict(manifest), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"replication config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"replication config missing required key: {key}")
    return raw[key]


if __name__ == "__main__":
    raise SystemExit(main())
