import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from predmkt.reports.final_readiness import (
    build_final_readiness,
    load_final_run_config,
)


def test_final_run_config_loads(tmp_path: Path) -> None:
    config_path = _write_fixture(tmp_path)

    config = load_final_run_config(config_path)

    assert config.run_label == "test_final"
    assert config.artifact_run_label == "full"
    assert config.registry_dir == tmp_path / "registry"
    assert config.readiness_doc_path == tmp_path / "final_readiness_audit.md"
    assert config.check_commands[0].name == "noop"
    assert config.config_sha256


def test_build_final_readiness_writes_registry_and_doc(tmp_path: Path) -> None:
    config = load_final_run_config(_write_fixture(tmp_path))

    summary = build_final_readiness(config, run_checks=True, invoked_command=("test",))

    assert summary.status == "READY_WITH_LIMITATIONS"
    assert Path(summary.run_registry_path).exists()
    assert Path(summary.artifact_manifest_path).exists()
    assert Path(summary.config_manifest_path).exists()
    assert Path(summary.data_snapshot_manifest_path).exists()
    assert Path(summary.check_results_path).exists()
    doc = Path(summary.readiness_doc_path).read_text(encoding="utf-8")
    assert "Final Readiness Audit" in doc
    assert "READY_WITH_LIMITATIONS" in doc
    checks = pd.read_parquet(summary.check_results_path)
    assert checks.loc[checks["name"] == "noop", "status"].iloc[0] == "PASS"


def test_build_final_run_registry_script_supports_skip_checks(tmp_path: Path) -> None:
    config_path = _write_fixture(tmp_path)
    repo = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_final_run_registry.py",
            "--config",
            str(config_path),
            "--skip-checks",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "READY_WITH_LIMITATIONS" not in result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "BLOCKED_CHECKS"
    assert (tmp_path / "registry" / "summary.json").exists()


def _write_fixture(tmp_path: Path) -> Path:
    final_audit = tmp_path / "final_audit"
    final_audit.mkdir()
    (final_audit / "summary.json").write_text(
        json.dumps({"overall_status": "PASS"}),
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "phase": ["phase_1"],
            "check_id": ["ok"],
            "status": ["PASS"],
            "message": ["ok"],
            "details_json": ["{}"],
        }
    ).to_parquet(final_audit / "audit_checks.parquet", index=False)
    pd.DataFrame(
        {
            "phase": ["phase_1"],
            "status": ["PASS"],
            "pass_count": [1],
            "partial_count": [0],
            "fail_count": [0],
        }
    ).to_parquet(final_audit / "phase_status.parquet", index=False)
    pd.DataFrame(
        {
            "artifact_key": ["summary"],
            "path": [str(final_audit / "summary.json")],
            "exists": [True],
            "artifact_type": ["json"],
            "row_count": [None],
            "columns_json": [None],
        }
    ).to_parquet(final_audit / "artifact_inventory.parquet", index=False)

    artifact = tmp_path / "artifact_summary.json"
    artifact.write_text(json.dumps({"row_count": 3}), encoding="utf-8")
    config_to_hash = tmp_path / "sampling.yaml"
    config_to_hash.write_text("x: 1\n", encoding="utf-8")
    config_path = tmp_path / "final_run.yaml"
    config_path.write_text(
        f"""
inputs:
  raw_repo_path:
  final_audit_summary_path: {final_audit / "summary.json"}
  final_audit_checks_path: {final_audit / "audit_checks.parquet"}
  final_audit_phase_status_path: {final_audit / "phase_status.parquet"}
  final_audit_inventory_path: {final_audit / "artifact_inventory.parquet"}
  artifact_paths:
    artifact_summary: {artifact}
  config_paths:
    - {config_to_hash}
outputs:
  registry_dir: {tmp_path / "registry"}
  readiness_doc_path: {tmp_path / "final_readiness_audit.md"}
final_run:
  run_label: test_final
  artifact_run_label: full
  raw_manifest_mode: metadata_only
  max_artifact_hash_bytes: 1000000
  full_run_command:
    - echo full
  small_sample_command: echo small
  claim_boundaries:
    - test claim boundary
checks:
  run_by_default: true
  commands:
    - name: noop
      command: [{sys.executable}, -c, "print('ok')"]
      required: true
      scope: test
""",
        encoding="utf-8",
    )
    return config_path
