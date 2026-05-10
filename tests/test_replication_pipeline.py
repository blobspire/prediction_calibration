from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_small_sample_pipeline.py"
_SPEC = importlib.util.spec_from_file_location("run_small_sample_pipeline", _SCRIPT_PATH)
assert _SPEC is not None
replication = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["run_small_sample_pipeline"] = replication
_SPEC.loader.exec_module(replication)


def test_small_sample_pipeline_dry_run_manifest(tmp_path: Path) -> None:
    config_path = tmp_path / "replication_small.yaml"
    manifest_path = tmp_path / "artifacts" / "replication_manifest.json"
    config_path.write_text(
        f"""
inputs:
  contracts_path: data/interim/kalshi/contracts.parquet
  price_observations_path: data/interim/kalshi/price_observations.parquet
outputs:
  processed_dir: {tmp_path / "processed"}
  artifact_dir: {tmp_path / "artifacts"}
  paper_dir: {tmp_path / "paper"}
  manifest_path: {manifest_path}
configs:
  sampling: configs/sampling.yaml
  taxonomy: configs/taxonomy.yaml
  features: configs/features.yaml
  metrics: configs/metrics.yaml
  validation: configs/validation.yaml
  models: configs/models.yaml
  inference: configs/inference.yaml
  backtest: configs/backtest.yaml
  decomposition: configs/decomposition.yaml
  reporting: configs/reporting.yaml
limits:
  limit_contracts: 123
  limit_folds: 2
replication:
  run_label: small_sample
  non_confirmatory: true
  start_from: data/interim/kalshi
""",
        encoding="utf-8",
    )

    config = replication.load_replication_config(config_path)
    stages = replication.build_stages(config)
    assert [stage.name for stage in stages] == [
        "snapshot",
        "taxonomy",
        "features",
        "raw_baseline",
        "splits",
        "walkforward",
        "inference",
        "edge",
        "decomposition",
        "figures",
        "tables",
    ]
    assert "--limit-contracts" in stages[0].command
    assert "--examples" in stages[1].command
    assert str(tmp_path / "processed" / "contract_horizon_taxonomy_examples.parquet") in stages[
        1
    ].command
    assert "--limit-folds" in stages[5].command
    assert "--predictions" in stages[6].command
    assert "--artifact-dir" in stages[8].command
    assert "--decomposition-dir" in stages[9].command

    manifest = replication.run_pipeline(config, dry_run=True)
    assert manifest.dry_run is True
    assert manifest.stage_count == 11
    assert manifest_path.exists()
    written = json.loads(manifest_path.read_text())
    assert written["effective_config"]["replication"]["non_confirmatory"] is True
    assert "data/raw" not in " ".join(stages[0].command)
