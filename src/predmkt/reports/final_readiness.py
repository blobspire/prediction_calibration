"""Phase 17 final run registry and readiness audit."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pyarrow.parquet as pq
import yaml  # type: ignore[import-untyped]


@dataclass(frozen=True)
class CheckCommand:
    """One configured readiness check command."""

    name: str
    command: tuple[str, ...]
    required: bool
    scope: str
    note: str


@dataclass(frozen=True)
class FinalRunConfig:
    """Configuration for the final run registry and readiness audit."""

    raw_repo_path: Path | None
    final_audit_summary_path: Path
    final_audit_checks_path: Path
    final_audit_phase_status_path: Path
    final_audit_inventory_path: Path
    artifact_paths: dict[str, Path]
    config_paths: tuple[Path, ...]
    registry_dir: Path
    readiness_doc_path: Path
    run_label: str
    artifact_run_label: str
    raw_manifest_mode: str
    max_artifact_hash_bytes: int
    full_run_command: tuple[str, ...]
    small_sample_command: str
    claim_boundaries: tuple[str, ...]
    checks_run_by_default: bool
    check_commands: tuple[CheckCommand, ...]
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class FinalReadinessSummary:
    """Summary metadata for Phase 17 readiness outputs."""

    status: str
    run_label: str
    artifact_run_label: str
    registry_dir: str
    readiness_doc_path: str
    started_at_utc: str
    ended_at_utc: str
    git_commit: str | None
    git_dirty: bool | None
    final_audit_status: str
    required_check_status: str
    artifact_manifest_path: str
    config_manifest_path: str
    data_snapshot_manifest_path: str
    check_results_path: str
    run_registry_path: str
    effective_config: dict[str, Any]
    limitations: list[str]


class FinalReadinessError(ValueError):
    """Raised when Phase 17 readiness configuration or artifacts are invalid."""


def load_final_run_config(path: Path) -> FinalRunConfig:
    """Load Phase 17 registry settings from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise FinalReadinessError(f"final run config must be a mapping: {path}")
    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    final_run = _mapping(raw, "final_run")
    checks = _mapping(raw, "checks")
    artifact_paths_raw = _mapping(inputs, "artifact_paths")
    config_paths_raw = inputs.get("config_paths", [])
    if not isinstance(config_paths_raw, list) or not config_paths_raw:
        raise FinalReadinessError("inputs.config_paths must be a non-empty list")
    raw_repo_value = inputs.get("raw_repo_path")
    check_commands = tuple(_check_command(item) for item in checks.get("commands", []))
    return FinalRunConfig(
        raw_repo_path=Path(str(raw_repo_value)) if raw_repo_value not in (None, "") else None,
        final_audit_summary_path=Path(_required(inputs, "final_audit_summary_path")),
        final_audit_checks_path=Path(_required(inputs, "final_audit_checks_path")),
        final_audit_phase_status_path=Path(_required(inputs, "final_audit_phase_status_path")),
        final_audit_inventory_path=Path(_required(inputs, "final_audit_inventory_path")),
        artifact_paths={str(key): Path(str(value)) for key, value in artifact_paths_raw.items()},
        config_paths=tuple(Path(str(item)) for item in config_paths_raw),
        registry_dir=Path(_required(outputs, "registry_dir")),
        readiness_doc_path=Path(_required(outputs, "readiness_doc_path")),
        run_label=str(_required(final_run, "run_label")),
        artifact_run_label=str(_required(final_run, "artifact_run_label")),
        raw_manifest_mode=str(_required(final_run, "raw_manifest_mode")),
        max_artifact_hash_bytes=int(_required(final_run, "max_artifact_hash_bytes")),
        full_run_command=tuple(str(item) for item in _required(final_run, "full_run_command")),
        small_sample_command=str(_required(final_run, "small_sample_command")),
        claim_boundaries=tuple(
            str(item) for item in final_run.get("claim_boundaries", [])
        ),
        checks_run_by_default=bool(checks.get("run_by_default", True)),
        check_commands=check_commands,
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def build_final_readiness(
    config: FinalRunConfig,
    *,
    run_checks: bool | None = None,
    invoked_command: tuple[str, ...] = (),
) -> FinalReadinessSummary:
    """Write Phase 17 run registry, manifests, and final readiness document."""

    started_at = _utc_now()
    config.registry_dir.mkdir(parents=True, exist_ok=True)
    config.readiness_doc_path.parent.mkdir(parents=True, exist_ok=True)
    paths = _output_paths(config.registry_dir)

    should_run_checks = config.checks_run_by_default if run_checks is None else run_checks
    check_results = _run_checks(config.check_commands) if should_run_checks else _skipped_checks(
        config.check_commands
    )
    _write_config_snapshot(config)
    config_manifest = _config_manifest(config)
    artifact_manifest = _artifact_manifest(config)
    data_snapshot = _data_snapshot_manifest(config)
    final_audit_summary = _read_json(config.final_audit_summary_path)
    final_audit_status = str(final_audit_summary.get("overall_status", "UNKNOWN"))
    required_check_status = _required_check_status(check_results)
    status = _readiness_status(final_audit_status, required_check_status)
    git_commit, git_dirty = _git_state()
    ended_at = _utc_now()

    config_manifest.to_parquet(paths["config_manifest"], index=False)
    artifact_manifest.to_parquet(paths["artifact_manifest"], index=False)
    data_snapshot.to_parquet(paths["data_snapshot_manifest"], index=False)
    check_results.to_parquet(paths["check_results"], index=False)

    registry = {
        "run_label": config.run_label,
        "artifact_run_label": config.artifact_run_label,
        "status": status,
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "invoked_command": list(invoked_command),
        "full_run_command": list(config.full_run_command),
        "small_sample_command": config.small_sample_command,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "config_sha256": config.config_sha256,
        "final_audit_status": final_audit_status,
        "required_check_status": required_check_status,
        "artifact_paths": {key: str(path) for key, path in config.artifact_paths.items()},
        "claim_boundaries": list(config.claim_boundaries),
    }
    paths["run_registry"].write_text(
        json.dumps(registry, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )

    summary = FinalReadinessSummary(
        status=status,
        run_label=config.run_label,
        artifact_run_label=config.artifact_run_label,
        registry_dir=str(config.registry_dir),
        readiness_doc_path=str(config.readiness_doc_path),
        started_at_utc=started_at,
        ended_at_utc=ended_at,
        git_commit=git_commit,
        git_dirty=git_dirty,
        final_audit_status=final_audit_status,
        required_check_status=required_check_status,
        artifact_manifest_path=str(paths["artifact_manifest"]),
        config_manifest_path=str(paths["config_manifest"]),
        data_snapshot_manifest_path=str(paths["data_snapshot_manifest"]),
        check_results_path=str(paths["check_results"]),
        run_registry_path=str(paths["run_registry"]),
        effective_config=effective_final_run_config(config),
        limitations=_limitations(config),
    )
    paths["summary"].write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    config.readiness_doc_path.write_text(
        _readiness_markdown(
            config,
            summary,
            check_results,
            artifact_manifest,
            data_snapshot,
        ),
        encoding="utf-8",
    )
    return summary


def effective_final_run_config(config: FinalRunConfig) -> dict[str, Any]:
    """Return JSON-serializable final-run config values."""

    return {
        "inputs": {
            "raw_repo_path": str(config.raw_repo_path) if config.raw_repo_path else None,
            "final_audit_summary_path": str(config.final_audit_summary_path),
            "final_audit_checks_path": str(config.final_audit_checks_path),
            "final_audit_phase_status_path": str(config.final_audit_phase_status_path),
            "final_audit_inventory_path": str(config.final_audit_inventory_path),
            "artifact_paths": {
                key: str(path) for key, path in config.artifact_paths.items()
            },
            "config_paths": [str(path) for path in config.config_paths],
        },
        "outputs": {
            "registry_dir": str(config.registry_dir),
            "readiness_doc_path": str(config.readiness_doc_path),
        },
        "final_run": {
            "run_label": config.run_label,
            "artifact_run_label": config.artifact_run_label,
            "raw_manifest_mode": config.raw_manifest_mode,
            "max_artifact_hash_bytes": config.max_artifact_hash_bytes,
            "full_run_command": list(config.full_run_command),
            "small_sample_command": config.small_sample_command,
            "claim_boundaries": list(config.claim_boundaries),
        },
        "checks": {
            "run_by_default": config.checks_run_by_default,
            "commands": [
                {
                    "name": item.name,
                    "command": list(item.command),
                    "required": item.required,
                    "scope": item.scope,
                    "note": item.note,
                }
                for item in config.check_commands
            ],
        },
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }


def _run_checks(commands: tuple[CheckCommand, ...]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in commands:
        started_at = _utc_now()
        result = subprocess.run(  # noqa: S603
            list(item.command),
            check=False,
            capture_output=True,
            text=True,
        )
        ended_at = _utc_now()
        rows.append(
            {
                "name": item.name,
                "command_json": json.dumps(list(item.command)),
                "required": item.required,
                "scope": item.scope,
                "note": item.note,
                "status": "PASS" if result.returncode == 0 else "FAIL",
                "returncode": int(result.returncode),
                "started_at_utc": started_at,
                "ended_at_utc": ended_at,
                "stdout_tail": result.stdout[-4000:],
                "stderr_tail": result.stderr[-4000:],
            }
        )
    return pd.DataFrame(rows)


def _skipped_checks(commands: tuple[CheckCommand, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "name": item.name,
            "command_json": json.dumps(list(item.command)),
            "required": item.required,
            "scope": item.scope,
            "note": item.note,
            "status": "SKIPPED",
            "returncode": None,
            "started_at_utc": None,
            "ended_at_utc": None,
            "stdout_tail": "",
            "stderr_tail": "",
        }
        for item in commands
    )


def _config_manifest(config: FinalRunConfig) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in config.config_paths:
        rows.append(_file_manifest_row("config", path, hash_large=True))
    return pd.DataFrame(rows)


def _write_config_snapshot(config: FinalRunConfig) -> None:
    snapshot_dir = config.registry_dir / "configs_snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for path in config.config_paths:
        if path.exists() and path.is_file():
            shutil.copy2(path, snapshot_dir / path.name)


def _artifact_manifest(config: FinalRunConfig) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    audit_paths = {
        "final_audit_summary": config.final_audit_summary_path,
        "final_audit_checks": config.final_audit_checks_path,
        "final_audit_phase_status": config.final_audit_phase_status_path,
        "final_audit_inventory": config.final_audit_inventory_path,
    }
    for key, path in {**config.artifact_paths, **audit_paths}.items():
        row = _file_manifest_row(
            key,
            path,
            hash_large=path.stat().st_size <= config.max_artifact_hash_bytes
            if path.exists() and path.is_file()
            else False,
        )
        if path.exists() and path.suffix == ".parquet":
            parquet = pq.ParquetFile(path)  # type: ignore[no-untyped-call]
            row["row_count"] = int(parquet.metadata.num_rows)
            row["columns_json"] = json.dumps(parquet.schema_arrow.names)
        rows.append(row)
    return pd.DataFrame(rows)


def _data_snapshot_manifest(config: FinalRunConfig) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if config.raw_repo_path:
        rows.append(
            {
                "snapshot_key": "raw_repo",
                "path": str(config.raw_repo_path),
                "exists": config.raw_repo_path.exists(),
                "manifest_mode": config.raw_manifest_mode,
                "git_commit": _git_commit(config.raw_repo_path),
                "git_dirty": _git_dirty(config.raw_repo_path),
                "file_count": _file_count(config.raw_repo_path),
                "size_bytes": _directory_size(config.raw_repo_path),
                "row_count": None,
                "notes": "metadata-only raw snapshot; raw files are not rewritten or fully hashed",
            }
        )
        kalshi = config.raw_repo_path / "data" / "kalshi"
        for name in ("markets", "trades"):
            path = kalshi / name
            rows.append(
                {
                    "snapshot_key": f"raw_kalshi_{name}",
                    "path": str(path),
                    "exists": path.exists(),
                    "manifest_mode": config.raw_manifest_mode,
                    "git_commit": None,
                    "git_dirty": None,
                    "file_count": _file_count(path),
                    "size_bytes": _directory_size(path),
                    "row_count": None,
                    "notes": "metadata-only directory snapshot",
                }
            )
    for key, path in config.artifact_paths.items():
        if not path.exists():
            continue
        row_count: int | None = None
        if path.suffix == ".parquet":
            parquet = pq.ParquetFile(path)  # type: ignore[no-untyped-call]
            row_count = int(parquet.metadata.num_rows)
        elif path.suffix == ".json":
            summary = _read_json(path)
            row_count = _first_int(
                summary,
                (
                    "row_count",
                    "output_row_count",
                    "input_row_count",
                    "prediction_row_count",
                    "candidate_row_count",
                ),
            )
        rows.append(
            {
                "snapshot_key": key,
                "path": str(path),
                "exists": True,
                "manifest_mode": "summary_or_parquet_metadata",
                "git_commit": None,
                "git_dirty": None,
                "file_count": 1,
                "size_bytes": path.stat().st_size,
                "row_count": row_count,
                "notes": "generated artifact included in final run registry",
            }
        )
    return pd.DataFrame(rows)


def _file_manifest_row(key: str, path: Path, *, hash_large: bool) -> dict[str, Any]:
    exists = path.exists()
    size = path.stat().st_size if exists and path.is_file() else None
    digest = _sha256(path) if exists and path.is_file() and hash_large else None
    hash_status = (
        "sha256" if digest else ("not_found" if not exists else "skipped_large_or_directory")
    )
    return {
        "artifact_key": key,
        "path": str(path),
        "exists": exists,
        "size_bytes": size,
        "sha256": digest,
        "hash_status": hash_status,
        "row_count": None,
        "columns_json": None,
    }


def _readiness_status(final_audit_status: str, required_check_status: str) -> str:
    if final_audit_status != "PASS":
        return "BLOCKED_FINAL_AUDIT"
    if required_check_status != "PASS":
        return "BLOCKED_CHECKS"
    return "READY_WITH_LIMITATIONS"


def _required_check_status(check_results: pd.DataFrame) -> str:
    if check_results.empty:
        return "SKIPPED"
    required = check_results[check_results["required"] == True]  # noqa: E712
    if required.empty:
        return "PASS"
    return "PASS" if (required["status"] == "PASS").all() else "FAIL"


def _readiness_markdown(
    config: FinalRunConfig,
    summary: FinalReadinessSummary,
    check_results: pd.DataFrame,
    artifact_manifest: pd.DataFrame,
    data_snapshot: pd.DataFrame,
) -> str:
    checks = check_results[["name", "status", "scope", "note"]].copy()
    artifact_rows = artifact_manifest[
        ["artifact_key", "exists", "size_bytes", "hash_status", "row_count"]
    ].head(40)
    data_rows = data_snapshot[
        ["snapshot_key", "exists", "manifest_mode", "file_count", "size_bytes", "row_count"]
    ].head(30)
    lines = [
        "# Final Readiness Audit",
        "",
        f"Status: **{summary.status}**.",
        "",
        "This Phase 17 readiness audit records the final run registry, config hashes, "
        "selected artifact hashes, data snapshot metadata, and verification command "
        "results. It does not change model methodology or reinterpret simulated edge "
        "outputs as executable trading profit.",
        "",
        "## Run Registry",
        "",
        f"- Run label: `{summary.run_label}`",
        f"- Artifact run label: `{summary.artifact_run_label}`",
        f"- Started UTC: `{summary.started_at_utc}`",
        f"- Ended UTC: `{summary.ended_at_utc}`",
        f"- Git commit: `{summary.git_commit}`",
        f"- Git dirty: `{summary.git_dirty}`",
        f"- Final artifact audit status: `{summary.final_audit_status}`",
        f"- Required check status: `{summary.required_check_status}`",
        f"- Frozen config snapshot: `{config.registry_dir / 'configs_snapshot'}`",
        "",
        "## CI Command Set",
        "",
        _markdown_table(checks),
        "",
        "The scoped mypy command is the Phase 17 CI type-check gate. Full "
        "`uv run mypy src` is intentionally not the gate yet because older "
        "PyArrow/Pandas-heavy modules still require typing cleanup.",
        "",
        "## Full Reproduction Commands",
        "",
        "Full run command sequence:",
        "",
        "```bash",
        *config.full_run_command,
        "```",
        "",
        "Small-sample replication command:",
        "",
        "```bash",
        config.small_sample_command,
        "```",
        "",
        "## Artifact Manifest Preview",
        "",
        _markdown_table(artifact_rows),
        "",
        "## Data Snapshot Preview",
        "",
        _markdown_table(data_rows),
        "",
        "## Claim Boundaries",
        "",
        *[f"- {item}" for item in config.claim_boundaries],
        "",
        "## Remaining Limitations",
        "",
        *[f"- {item}" for item in summary.limitations],
        "",
    ]
    return "\n".join(lines)


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows._"
    text = frame.copy()
    text = text.fillna("")
    columns = list(text.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in text.to_dict(orient="records"):
        lines.append("| " + " | ".join(str(row[column]) for column in columns) + " |")
    return "\n".join(lines)


def _limitations(config: FinalRunConfig) -> list[str]:
    return [
        "Phase 17 readiness records and validates existing full artifacts; it does not "
        "rerun the full scientific pipeline unless the documented command sequence is "
        "executed separately.",
        "Raw data hashing is metadata-only by default to avoid repeatedly hashing the "
        "entire local Becker data clone; configs and selected generated artifacts are "
        "hashed directly.",
        "Domain/category claims remain conditional on taxonomy confidence, ambiguity, "
        "and manual review.",
        "Event-family purging remains a robustness sensitivity; primary walk-forward "
        "outputs report overlaps and clustered inference resamples event-family IDs.",
        "Edge and PnL outputs remain simulated expected-value screens because public "
        "quote snapshots lack order-book depth.",
        f"Full-run artifacts are expected to use artifact_run_label={config.artifact_run_label}.",
    ]


def _output_paths(registry_dir: Path) -> dict[str, Path]:
    return {
        "artifact_manifest": registry_dir / "artifact_manifest.parquet",
        "config_manifest": registry_dir / "config_manifest.parquet",
        "data_snapshot_manifest": registry_dir / "data_snapshot_manifest.parquet",
        "check_results": registry_dir / "check_results.parquet",
        "run_registry": registry_dir / "run_registry.json",
        "summary": registry_dir / "summary.json",
    }


def _check_command(raw: object) -> CheckCommand:
    if not isinstance(raw, dict):
        raise FinalReadinessError("each check command must be a mapping")
    command = raw.get("command")
    if not isinstance(command, list) or not command:
        raise FinalReadinessError("check command must be a non-empty list")
    return CheckCommand(
        name=str(_required(raw, "name")),
        command=tuple(str(item) for item in command),
        required=bool(raw.get("required", True)),
        scope=str(raw.get("scope", "")),
        note=str(raw.get("note", "")),
    )


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise FinalReadinessError(f"config section must be a mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise FinalReadinessError(f"missing required config key: {key}")
    return raw[key]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise FinalReadinessError(f"JSON artifact must be an object: {path}")
    return raw


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_int(raw: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, int):
            return value
    return None


def _file_count(path: Path) -> int | None:
    if not path.exists():
        return None
    if path.is_file():
        return 1
    return sum(1 for item in path.rglob("*") if item.is_file())


def _directory_size(path: Path) -> int | None:
    if not path.exists():
        return None
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _git_state() -> tuple[str | None, bool | None]:
    return _git_commit(Path(".")), _git_dirty(Path("."))


def _git_commit(path: Path) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _git_dirty(path: Path) -> bool | None:
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(path), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return bool(result.stdout.strip())


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
