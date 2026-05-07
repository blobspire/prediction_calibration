"""Matplotlib plots for raw baseline forecast metrics."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import yaml

DEFAULT_HORIZON_ORDER = ("30d", "14d", "7d", "3d", "1d", "6h", "1h", "close")
DEFAULT_FIGURE_FORMATS = ("png", "svg")
METRIC_COLORS = {
    "brier_score": "#2364aa",
    "log_loss": "#d95f02",
    "expected_calibration_error": "#2a9d8f",
    "intercept": "#6a4c93",
    "slope": "#c1121f",
}


@dataclass(frozen=True)
class RawBaselinePlotConfig:
    """Configuration for raw baseline metric plotting."""

    artifact_dir: Path
    figure_dir: Path
    horizon_order: tuple[str, ...] = DEFAULT_HORIZON_ORDER
    aggregation_mode: str = "equal_contract"
    figure_formats: tuple[str, ...] = DEFAULT_FIGURE_FORMATS
    dpi: int = 180
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class RawBaselinePlotSummary:
    """Summary of generated raw baseline figures."""

    artifact_dir: str
    figure_dir: str
    figure_paths: dict[str, list[str]]
    aggregation_mode: str
    horizon_order: list[str]
    source_artifacts: dict[str, str]
    effective_config: dict[str, Any]
    limitations: list[str]


class PlotGenerationError(ValueError):
    """Raised when figure generation inputs are missing or invalid."""


def load_raw_baseline_plot_config(path: Path) -> RawBaselinePlotConfig:
    """Load raw baseline plotting configuration from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"figure config must be a mapping: {path}")
    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    raw_baseline = _mapping(raw, "raw_baseline")
    formats = raw_baseline.get("figure_formats")
    if formats is None:
        legacy_format = raw_baseline.get("figure_format")
        formats = [legacy_format] if legacy_format else list(DEFAULT_FIGURE_FORMATS)
    return RawBaselinePlotConfig(
        artifact_dir=Path(_required(inputs, "raw_baseline_artifact_dir")),
        figure_dir=Path(_required(outputs, "raw_baseline_figure_dir")),
        horizon_order=tuple(raw_baseline.get("horizon_order", DEFAULT_HORIZON_ORDER)),
        aggregation_mode=str(raw_baseline.get("aggregation_mode", "equal_contract")),
        figure_formats=tuple(str(item) for item in formats),
        dpi=int(raw_baseline.get("dpi", 180)),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def build_raw_baseline_plots(config: RawBaselinePlotConfig) -> RawBaselinePlotSummary:
    """Build raw baseline metric visualizations from saved artifacts."""

    _validate_formats(config.figure_formats)
    config.figure_dir.mkdir(parents=True, exist_ok=True)
    _set_plot_style()

    artifacts = _artifact_paths(config.artifact_dir)
    for path in artifacts.values():
        if not path.exists():
            raise PlotGenerationError(f"missing raw baseline artifact: {path}")

    metrics = pd.read_parquet(artifacts["metrics_by_group"])
    reliability = pd.read_parquet(artifacts["reliability_bins"])
    calibration = pd.read_parquet(artifacts["calibration_fits"])

    figure_paths = {
        "metric_overview": _save_figure(
            _metric_overview_figure(metrics, config),
            config,
            "raw_baseline_metric_overview",
        ),
        "horizon_metrics": _save_figure(
            _horizon_metrics_figure(metrics, config),
            config,
            "raw_baseline_horizon_metrics",
        ),
        "calibration_by_horizon": _save_figure(
            _calibration_by_horizon_figure(calibration, config),
            config,
            "raw_baseline_calibration_by_horizon",
        ),
        "reliability_overall": _save_figure(
            _reliability_overall_figure(reliability, metrics, config),
            config,
            "raw_baseline_reliability_overall",
        ),
        "reliability_by_horizon": _save_figure(
            _reliability_by_horizon_figure(reliability, config),
            config,
            "raw_baseline_reliability_by_horizon",
        ),
    }

    summary = RawBaselinePlotSummary(
        artifact_dir=str(config.artifact_dir),
        figure_dir=str(config.figure_dir),
        figure_paths={key: [str(path) for path in paths] for key, paths in figure_paths.items()},
        aggregation_mode=config.aggregation_mode,
        horizon_order=list(config.horizon_order),
        source_artifacts={key: str(value) for key, value in artifacts.items()},
        effective_config=_effective_config(config),
        limitations=[
            "Figures visualize raw baseline artifacts only; they are not recalibrated "
            "or walk-forward model results.",
            "Domain/category visualizations remain exploratory because taxonomy coverage "
            "mixes high-confidence ticker rules with lower-confidence title and unknown "
            "assignments.",
            "Figures use transaction-price baseline probabilities and public liquidity "
            "proxies, not executable historical quotes.",
        ],
    )
    summary_path = config.figure_dir / "raw_baseline_plot_summary.json"
    summary_path.write_text(json.dumps(asdict(summary), indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _metric_overview_figure(
    metrics: pd.DataFrame,
    config: RawBaselinePlotConfig,
) -> plt.Figure:
    row = _single_metric_row(metrics, "overall", config.aggregation_mode)
    labels = ["Brier", "Log loss", "ECE"]
    columns = ["brier_score", "log_loss", "expected_calibration_error"]
    values = [float(row[column]) for column in columns]

    fig, ax = plt.subplots(figsize=(7.2, 4.5), constrained_layout=True)
    bars = ax.bar(labels, values, color=[METRIC_COLORS[column] for column in columns], alpha=0.88)
    ax.set_title("Raw Baseline Metric Overview")
    ax.set_ylabel("Score, lower is better")
    ax.set_xlabel("Metric")
    ax.set_ylim(0, max(values) * 1.22)
    ax.grid(axis="y", color="#d1d5db", linewidth=0.8, alpha=0.8)
    ax.bar_label(bars, labels=[f"{value:.3f}" for value in values], padding=3, fontsize=9)
    ax.text(
        0.0,
        -0.22,
        f"Aggregation: {config.aggregation_mode}; rows: {int(row['row_count']):,}",
        transform=ax.transAxes,
        fontsize=9,
        color="#4b5563",
    )
    return fig


def _horizon_metrics_figure(metrics: pd.DataFrame, config: RawBaselinePlotConfig) -> plt.Figure:
    horizon = _ordered_horizon_rows(metrics, "horizon", config)
    fig, axes = plt.subplots(3, 1, figsize=(9.0, 8.4), sharex=True, constrained_layout=True)
    specs = [
        ("brier_score", "Brier score", "Brier"),
        ("log_loss", "Log loss", "Log loss"),
        ("expected_calibration_error", "Expected calibration error", "ECE"),
    ]
    x = range(len(horizon))
    for ax, (column, title, ylabel) in zip(axes, specs, strict=True):
        values = horizon[column].astype(float)
        ax.bar(x, values, color=METRIC_COLORS[column], alpha=0.86)
        ax.set_title(title, loc="left", fontsize=11)
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", color="#d1d5db", linewidth=0.8, alpha=0.8)
        ax.set_ylim(0, max(values) * 1.18)
    axes[-1].set_xticks(list(x), horizon["horizon_name"].astype(str).tolist())
    axes[-1].set_xlabel("Forecast horizon")
    fig.suptitle("Raw Baseline Scores by Horizon", fontsize=14, fontweight="bold")
    return fig


def _calibration_by_horizon_figure(
    calibration: pd.DataFrame,
    config: RawBaselinePlotConfig,
) -> plt.Figure:
    horizon = _ordered_horizon_rows(calibration, "horizon", config)
    fig, axes = plt.subplots(2, 1, figsize=(9.0, 6.8), sharex=True, constrained_layout=True)
    x = range(len(horizon))

    axes[0].bar(x, horizon["intercept"].astype(float), color=METRIC_COLORS["intercept"], alpha=0.86)
    axes[0].axhline(0.0, color="#111827", linewidth=1.0)
    axes[0].set_title("Calibration intercept", loc="left", fontsize=11)
    axes[0].set_ylabel("Intercept")
    axes[0].grid(axis="y", color="#d1d5db", linewidth=0.8, alpha=0.8)

    axes[1].bar(x, horizon["slope"].astype(float), color=METRIC_COLORS["slope"], alpha=0.86)
    axes[1].axhline(1.0, color="#111827", linewidth=1.0, linestyle="--", label="Ideal slope = 1")
    axes[1].set_title("Calibration slope", loc="left", fontsize=11)
    axes[1].set_ylabel("Slope")
    axes[1].set_xticks(list(x), horizon["horizon_name"].astype(str).tolist())
    axes[1].set_xlabel("Forecast horizon")
    axes[1].grid(axis="y", color="#d1d5db", linewidth=0.8, alpha=0.8)
    axes[1].legend(loc="best", frameon=False)

    fig.suptitle("Raw Baseline Calibration by Horizon", fontsize=14, fontweight="bold")
    return fig


def _reliability_overall_figure(
    reliability: pd.DataFrame,
    metrics: pd.DataFrame,
    config: RawBaselinePlotConfig,
) -> plt.Figure:
    rows = _reliability_rows(reliability, "overall", config)
    overall = _single_metric_row(metrics, "overall", config.aggregation_mode)
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.8), constrained_layout=True)
    _draw_reliability_curve(
        axes[0],
        rows,
        title="Observed frequency vs. predicted probability",
        show_ylabel=True,
    )
    centers = (rows["bin_lower"] + rows["bin_upper"]) / 2
    axes[1].bar(centers, rows["row_count"], width=0.08, color="#6b7280", alpha=0.82)
    axes[1].set_title("Reliability-bin support", loc="left", fontsize=11)
    axes[1].set_xlabel("Probability bin midpoint")
    axes[1].set_ylabel("Rows")
    axes[1].grid(axis="y", color="#d1d5db", linewidth=0.8, alpha=0.8)
    fig.suptitle(
        "Raw Baseline Reliability: Overall\n"
        f"ECE={float(overall['expected_calibration_error']):.3f}; "
        f"rows={int(overall['row_count']):,}",
        fontsize=14,
        fontweight="bold",
    )
    return fig


def _reliability_by_horizon_figure(
    reliability: pd.DataFrame,
    config: RawBaselinePlotConfig,
) -> plt.Figure:
    column_count = min(4, max(len(config.horizon_order), 1))
    row_count = math.ceil(len(config.horizon_order) / column_count)
    fig, axes = plt.subplots(
        row_count,
        column_count,
        figsize=(3.3 * column_count, 3.6 * row_count),
        sharex=True,
        sharey=True,
    )
    axes_flat = list(axes.ravel()) if hasattr(axes, "ravel") else [axes]
    for ax, horizon_name in zip(axes_flat, config.horizon_order, strict=False):
        rows = _reliability_rows(
            reliability,
            "horizon",
            config,
            horizon_name=horizon_name,
        )
        _draw_reliability_curve(ax, rows, title=horizon_name, show_ylabel=False)
    for ax in axes_flat[len(config.horizon_order) :]:
        ax.axis("off")
    for ax in axes_flat[::column_count]:
        ax.set_ylabel("Observed frequency")
    for ax in axes_flat[-column_count:]:
        ax.set_xlabel("Mean predicted probability")
    fig.suptitle("Raw Baseline Reliability by Horizon", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return fig


def _draw_reliability_curve(
    ax: plt.Axes,
    rows: pd.DataFrame,
    *,
    title: str,
    show_ylabel: bool,
) -> None:
    plotted = rows.dropna(subset=["mean_predicted_probability", "observed_frequency"]).copy()
    ax.plot([0, 1], [0, 1], color="#6b7280", linestyle="--", linewidth=1.0, label="Ideal")
    if not plotted.empty:
        sizes = 25 + 160 * plotted["row_count"] / max(float(plotted["row_count"].max()), 1.0)
        colors = plotted["is_sparse"].map({True: "#d95f02", False: "#2364aa"}).tolist()
        ax.scatter(
            plotted["mean_predicted_probability"],
            plotted["observed_frequency"],
            s=sizes,
            c=colors,
            alpha=0.78,
            edgecolors="#111827",
            linewidths=0.35,
        )
        ax.plot(
            plotted["mean_predicted_probability"],
            plotted["observed_frequency"],
            color="#2364aa",
            linewidth=1.3,
            alpha=0.72,
        )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title(title, loc="left", fontsize=11)
    ax.set_xlabel("Mean predicted probability")
    if show_ylabel:
        ax.set_ylabel("Observed frequency")
    ax.grid(color="#d1d5db", linewidth=0.8, alpha=0.8)


def _single_metric_row(
    metrics: pd.DataFrame,
    grouping_name: str,
    aggregation_mode: str,
) -> pd.Series:
    rows = metrics[
        (metrics["grouping_name"] == grouping_name)
        & (metrics["aggregation_mode"] == aggregation_mode)
    ]
    if len(rows) != 1:
        raise PlotGenerationError(
            f"expected one row for grouping={grouping_name}, aggregation={aggregation_mode}; "
            f"found {len(rows)}"
        )
    return rows.iloc[0]


def _ordered_horizon_rows(
    frame: pd.DataFrame,
    grouping_name: str,
    config: RawBaselinePlotConfig,
) -> pd.DataFrame:
    rows = frame[
        (frame["grouping_name"] == grouping_name)
        & (frame["aggregation_mode"] == config.aggregation_mode)
    ].copy()
    rows["horizon_name"] = pd.Categorical(
        rows["horizon_name"],
        categories=list(config.horizon_order),
        ordered=True,
    )
    rows = rows.sort_values("horizon_name")
    if rows.empty:
        raise PlotGenerationError(f"no horizon rows found for grouping={grouping_name}")
    return rows


def _reliability_rows(
    reliability: pd.DataFrame,
    grouping_name: str,
    config: RawBaselinePlotConfig,
    *,
    horizon_name: str | None = None,
) -> pd.DataFrame:
    mask = (
        (reliability["grouping_name"] == grouping_name)
        & (reliability["aggregation_mode"] == config.aggregation_mode)
    )
    if horizon_name is not None:
        mask &= reliability["horizon_name"] == horizon_name
    rows = reliability[mask].copy().sort_values("bin_index")
    if rows.empty:
        raise PlotGenerationError(
            f"no reliability rows found for grouping={grouping_name}, horizon={horizon_name}"
        )
    return rows


def _save_figure(
    fig: plt.Figure,
    config: RawBaselinePlotConfig,
    stem: str,
) -> list[Path]:
    paths: list[Path] = []
    for figure_format in config.figure_formats:
        path = config.figure_dir / f"{stem}.{figure_format}"
        fig.savefig(path, dpi=config.dpi, bbox_inches="tight", facecolor="white")
        paths.append(path)
    plt.close(fig)
    return paths


def _set_plot_style() -> None:
    plt.rcParams.update(
        {
            "axes.facecolor": "white",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "figure.facecolor": "white",
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "savefig.facecolor": "white",
        }
    )


def _validate_formats(formats: tuple[str, ...]) -> None:
    if not formats:
        raise PlotGenerationError("at least one figure format is required")
    allowed = {"png", "svg", "pdf"}
    unsupported = sorted(set(formats) - allowed)
    if unsupported:
        raise PlotGenerationError(f"unsupported figure formats: {unsupported}")


def _artifact_paths(artifact_dir: Path) -> dict[str, Path]:
    return {
        "metrics_by_group": artifact_dir / "metrics_by_group.parquet",
        "reliability_bins": artifact_dir / "reliability_bins.parquet",
        "calibration_fits": artifact_dir / "calibration_fits.parquet",
    }


def _effective_config(config: RawBaselinePlotConfig) -> dict[str, Any]:
    return {
        "inputs": {"raw_baseline_artifact_dir": str(config.artifact_dir)},
        "outputs": {"raw_baseline_figure_dir": str(config.figure_dir)},
        "raw_baseline": {
            "horizon_order": list(config.horizon_order),
            "aggregation_mode": config.aggregation_mode,
            "figure_formats": list(config.figure_formats),
            "dpi": config.dpi,
        },
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"figure config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"figure config missing required key: {key}")
    return raw[key]
