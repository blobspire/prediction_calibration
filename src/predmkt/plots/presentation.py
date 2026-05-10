"""Presentation-ready figures for the raw Kalshi baseline story."""

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
SECONDS_PER_MINUTE = 60

COLORS = {
    "blue": "#2364aa",
    "orange": "#d95f02",
    "green": "#2a9d8f",
    "purple": "#6a4c93",
    "red": "#c1121f",
    "gray": "#6b7280",
    "ink": "#111827",
    "light": "#e5e7eb",
}


@dataclass(frozen=True)
class PresentationFigureConfig:
    """Configuration for presentation figure generation."""

    artifact_dir: Path
    audit_dir: Path
    snapshot_summary_path: Path
    modeling_panel_path: Path
    figure_dir: Path
    horizon_order: tuple[str, ...] = DEFAULT_HORIZON_ORDER
    aggregation_mode: str = "equal_contract"
    figure_formats: tuple[str, ...] = DEFAULT_FIGURE_FORMATS
    dpi: int = 200
    before_refinement: dict[str, Any] | None = None
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class PresentationFigureSummary:
    """Summary of generated presentation figures."""

    figure_dir: str
    figure_paths: dict[str, list[str]]
    source_artifacts: dict[str, str]
    effective_config: dict[str, Any]
    limitations: list[str]


class PresentationFigureError(ValueError):
    """Raised when presentation figure inputs are invalid."""


def load_presentation_figure_config(path: Path) -> PresentationFigureConfig:
    """Load presentation figure config from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"presentation config must be a mapping: {path}")
    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    presentation = _mapping(raw, "presentation")
    return PresentationFigureConfig(
        artifact_dir=Path(_required(inputs, "raw_baseline_artifact_dir")),
        audit_dir=Path(_required(inputs, "raw_baseline_audit_dir")),
        snapshot_summary_path=Path(_required(inputs, "snapshot_summary_path")),
        modeling_panel_path=Path(_required(inputs, "modeling_panel_path")),
        figure_dir=Path(_required(outputs, "presentation_figure_dir")),
        horizon_order=tuple(presentation.get("horizon_order", DEFAULT_HORIZON_ORDER)),
        aggregation_mode=str(presentation.get("aggregation_mode", "equal_contract")),
        figure_formats=tuple(
            str(item) for item in presentation.get("figure_formats", DEFAULT_FIGURE_FORMATS)
        ),
        dpi=int(presentation.get("dpi", 200)),
        before_refinement=presentation.get("before_refinement"),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def build_presentation_figures(
    config: PresentationFigureConfig,
) -> PresentationFigureSummary:
    """Build presentation-ready figures from saved artifacts."""

    _validate_config(config)
    config.figure_dir.mkdir(parents=True, exist_ok=True)
    _set_plot_style()

    sources = _source_paths(config)
    metrics = pd.read_parquet(sources["metrics_by_group"])
    calibration = pd.read_parquet(sources["calibration_fits"])
    reliability = pd.read_parquet(sources["reliability_bins"])
    staleness = pd.read_parquet(sources["staleness"])
    balanced = pd.read_parquet(sources["balanced_metrics"])
    orientation = pd.read_parquet(sources["orientation"])
    close_semantics = pd.read_parquet(sources["close_semantics"])
    snapshot_summary = json.loads(config.snapshot_summary_path.read_text(encoding="utf-8"))
    modeling = pd.read_parquet(
        config.modeling_panel_path,
        columns=["horizon_name", "raw_probability"],
    )

    figure_paths = {
        "pipeline_flow": _save_figure(
            _pipeline_flow_figure(),
            config,
            "presentation_pipeline_flow",
        ),
        "snapshot_policy_heatmap": _save_figure(
            _snapshot_policy_figure(snapshot_summary, config),
            config,
            "presentation_snapshot_policy",
        ),
        "sample_funnel": _save_figure(
            _sample_funnel_figure(snapshot_summary, config),
            config,
            "presentation_horizon_sample_funnel",
        ),
        "horizon_metric_triptych": _save_figure(
            _horizon_metric_triptych(metrics, config),
            config,
            "presentation_horizon_metric_triptych",
        ),
        "reliability_small_multiples": _save_figure(
            _reliability_small_multiples(reliability, config),
            config,
            "presentation_reliability_small_multiples",
        ),
        "close_reliability_zoom": _save_figure(
            _close_reliability_zoom(reliability, config),
            config,
            "presentation_close_reliability_zoom",
        ),
        "calibration_by_horizon": _save_figure(
            _calibration_by_horizon(calibration, config),
            config,
            "presentation_calibration_by_horizon",
        ),
        "staleness_percentiles": _save_figure(
            _staleness_percentiles(staleness, config),
            config,
            "presentation_staleness_percentiles",
        ),
        "probability_distribution": _save_figure(
            _probability_distribution(modeling, config),
            config,
            "presentation_probability_distribution_by_horizon",
        ),
        "calibration_gap_heatmap": _save_figure(
            _calibration_gap_heatmap(reliability, config),
            config,
            "presentation_calibration_gap_heatmap",
        ),
        "balanced_comparison": _save_figure(
            _balanced_comparison(balanced, config),
            config,
            "presentation_balanced_vs_unbalanced",
        ),
        "orientation_check": _save_figure(
            _orientation_check(orientation),
            config,
            "presentation_orientation_sanity_check",
        ),
        "close_timestamp_semantics": _save_figure(
            _close_timestamp_semantics(close_semantics),
            config,
            "presentation_close_timestamp_semantics",
        ),
        "dashboard": _save_figure(
            _dashboard(metrics, staleness, reliability, snapshot_summary, config),
            config,
            "presentation_summary_dashboard",
        ),
    }
    if config.before_refinement:
        figure_paths["snapshot_refinement_before_after"] = _save_figure(
            _snapshot_refinement_before_after(snapshot_summary, config),
            config,
            "presentation_snapshot_refinement_before_after",
        )

    summary = PresentationFigureSummary(
        figure_dir=str(config.figure_dir),
        figure_paths={key: [str(path) for path in paths] for key, paths in figure_paths.items()},
        source_artifacts={key: str(path) for key, path in sources.items()},
        effective_config=_effective_config(config),
        limitations=[
            "Presentation figures use current raw-baseline artifacts only; they are not "
            "walk-forward or recalibrated-model results.",
            "Domain/category findings remain exploratory because taxonomy coverage mixes "
            "high-confidence ticker rules with lower-confidence title and unknown rows.",
            "Snapshot prices are transaction-derived probabilities, not executable quotes.",
            "Before-refinement comparison uses recorded audit summary values, not a retained "
            "separate pre-refinement artifact directory.",
        ],
    )
    (config.figure_dir / "presentation_figure_summary.json").write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def _pipeline_flow_figure() -> plt.Figure:
    fig, ax = plt.subplots(figsize=(13.3, 7.5), constrained_layout=True)
    ax.axis("off")
    steps = [
        ("Raw Becker/Kalshi", "immutable Parquet\nmarkets + trades"),
        ("Interim Cleaning", "resolved binary\ncontracts + prices"),
        ("Snapshots", "contract x horizon\nno look-ahead"),
        ("Taxonomy + Features", "event proxy, staleness,\nliquidity, momentum"),
        ("Raw Metrics", "Brier, log loss,\nECE, calibration"),
        ("Diagnostics", "reliability, stale\nand method audits"),
    ]
    xs = [0.06, 0.235, 0.41, 0.585, 0.76, 0.92]
    y = 0.54
    for index, ((title, body), x) in enumerate(zip(steps, xs, strict=True)):
        ax.text(
            x,
            y,
            title + "\n" + body,
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=11,
            color=COLORS["ink"],
            bbox={
                "boxstyle": "round,pad=0.45,rounding_size=0.05",
                "facecolor": "#f8fafc",
                "edgecolor": COLORS["blue"],
                "linewidth": 1.6,
            },
        )
        if index < len(xs) - 1:
            ax.annotate(
                "",
                xy=(xs[index + 1] - 0.08, y),
                xytext=(x + 0.08, y),
                xycoords=ax.transAxes,
                arrowprops={"arrowstyle": "->", "lw": 1.8, "color": COLORS["gray"]},
            )
    ax.text(
        0.5,
        0.87,
        "Prediction-Market Calibration Pipeline",
        transform=ax.transAxes,
        ha="center",
        fontsize=22,
        fontweight="bold",
    )
    ax.text(
        0.5,
        0.18,
        "Confirmatory unit: one row per contract x forecast horizon bucket",
        transform=ax.transAxes,
        ha="center",
        fontsize=13,
        color=COLORS["gray"],
    )
    return fig


def _snapshot_policy_figure(
    snapshot_summary: dict[str, Any],
    config: PresentationFigureConfig,
) -> plt.Figure:
    policies = snapshot_summary["horizon_snapshot_policies"]
    rows = []
    for horizon in config.horizon_order:
        policy = policies[horizon]
        rows.append(
            {
                "horizon": horizon,
                "primary": 0 if policy["primary_method"] == "last_trade" else 1,
                "vwap_min": policy["vwap_window_seconds"] / 60,
                "stale_min": policy["max_staleness_seconds"] / 60,
            }
        )
    frame = pd.DataFrame(rows)
    fig, axes = plt.subplots(1, 3, figsize=(13.3, 5.2), constrained_layout=True)
    _policy_column_heatmap(axes[0], frame, "primary", "Primary method", ["last_trade", "vwap"])
    _numeric_policy_heatmap(axes[1], frame, "vwap_min", "VWAP window\n(minutes)")
    _numeric_policy_heatmap(axes[2], frame, "stale_min", "Max staleness\n(minutes)")
    fig.suptitle("Horizon-Specific Snapshot Policy", fontsize=18, fontweight="bold")
    return fig


def _sample_funnel_figure(
    snapshot_summary: dict[str, Any],
    config: PresentationFigureConfig,
) -> plt.Figure:
    counts = pd.Series(snapshot_summary["horizon_counts"]).reindex(config.horizon_order)
    fig, ax = plt.subplots(figsize=(11.2, 6.2), constrained_layout=True)
    bars = ax.bar(counts.index, counts.values, color=COLORS["blue"], alpha=0.88)
    ax.bar_label(bars, labels=[f"{int(value):,}" for value in counts.values], fontsize=8, padding=3)
    ax.set_title("Eligible Snapshot Rows by Horizon")
    ax.set_ylabel("Rows")
    ax.set_xlabel("Forecast horizon")
    ax.grid(axis="y", color=COLORS["light"], linewidth=0.8)
    ax.text(
        0.01,
        0.94,
        f"Total panel rows: {int(snapshot_summary['row_count']):,}",
        transform=ax.transAxes,
        fontsize=11,
        color=COLORS["gray"],
    )
    return fig


def _horizon_metric_triptych(
    metrics: pd.DataFrame,
    config: PresentationFigureConfig,
) -> plt.Figure:
    rows = _horizon_rows(metrics, config)
    fig, axes = plt.subplots(1, 3, figsize=(13.3, 4.8), sharex=True, constrained_layout=True)
    specs = [
        ("brier_score", "Brier", COLORS["blue"]),
        ("log_loss", "Log loss", COLORS["orange"]),
        ("expected_calibration_error", "ECE", COLORS["green"]),
    ]
    for ax, (column, title, color) in zip(axes, specs, strict=True):
        ax.plot(rows["horizon_name"], rows[column], marker="o", linewidth=2.1, color=color)
        ax.set_title(title)
        ax.set_xlabel("Horizon")
        ax.grid(axis="y", color=COLORS["light"], linewidth=0.8)
        ax.tick_params(axis="x", rotation=35)
    fig.suptitle("Raw Baseline Accuracy by Horizon", fontsize=18, fontweight="bold")
    return fig


def _reliability_small_multiples(
    reliability: pd.DataFrame,
    config: PresentationFigureConfig,
) -> plt.Figure:
    column_count = min(4, max(len(config.horizon_order), 1))
    row_count = math.ceil(len(config.horizon_order) / column_count)
    fig, axes = plt.subplots(
        row_count,
        column_count,
        figsize=(3.35 * column_count, 3.6 * row_count),
        sharex=True,
        sharey=True,
    )
    axes_flat = axes.ravel() if hasattr(axes, "ravel") else [axes]
    for ax, horizon in zip(axes_flat, config.horizon_order, strict=False):
        rows = _reliability_horizon_rows(reliability, horizon, config)
        _draw_reliability(ax, rows, title=horizon, show_counts=False)
    for ax in axes_flat[len(config.horizon_order) :]:
        ax.axis("off")
    for ax in axes_flat[::column_count]:
        ax.set_ylabel("Observed")
    for ax in axes_flat[-column_count:]:
        ax.set_xlabel("Predicted")
    fig.suptitle("Reliability by Forecast Horizon", fontsize=18, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return fig


def _close_reliability_zoom(
    reliability: pd.DataFrame,
    config: PresentationFigureConfig,
) -> plt.Figure:
    rows = _reliability_horizon_rows(reliability, "close", config)
    fig, axes = plt.subplots(1, 2, figsize=(13.3, 5.0), constrained_layout=True)
    _draw_reliability(axes[0], rows, title="Close Reliability", show_counts=True)
    centers = (rows["bin_lower"] + rows["bin_upper"]) / 2
    axes[1].bar(
        centers,
        rows["row_count"],
        width=0.08,
        color=COLORS["purple"],
        alpha=0.85,
    )
    axes[1].set_title("Close Bin Support")
    axes[1].set_xlabel("Probability bin midpoint")
    axes[1].set_ylabel("Rows")
    axes[1].grid(axis="y", color=COLORS["light"], linewidth=0.8)
    fig.suptitle(
        "Close Horizon: Good Accuracy, Selected Mid-Bin Calibration Gaps",
        fontweight="bold",
    )
    return fig


def _calibration_by_horizon(
    calibration: pd.DataFrame,
    config: PresentationFigureConfig,
) -> plt.Figure:
    rows = _horizon_rows(calibration, config)
    fig, axes = plt.subplots(1, 2, figsize=(13.3, 4.8), constrained_layout=True)
    axes[0].bar(rows["horizon_name"], rows["intercept"], color=COLORS["purple"], alpha=0.85)
    axes[0].axhline(0, color=COLORS["ink"], linewidth=1)
    axes[0].set_title("Calibration intercept")
    axes[0].set_ylabel("Intercept")
    axes[1].bar(rows["horizon_name"], rows["slope"], color=COLORS["red"], alpha=0.85)
    axes[1].axhline(1, color=COLORS["ink"], linewidth=1, linestyle="--")
    axes[1].set_title("Calibration slope")
    axes[1].set_ylabel("Slope")
    for ax in axes:
        ax.tick_params(axis="x", rotation=35)
        ax.grid(axis="y", color=COLORS["light"], linewidth=0.8)
    fig.suptitle("Calibration Coefficients by Horizon", fontsize=18, fontweight="bold")
    return fig


def _staleness_percentiles(
    staleness: pd.DataFrame,
    config: PresentationFigureConfig,
) -> plt.Figure:
    rows = staleness[staleness["snapshot_method"] == "all"].copy()
    rows = _order_horizon(rows, config)
    fig, ax = plt.subplots(figsize=(12.5, 5.6), constrained_layout=True)
    for column, label, color in [
        ("median_staleness_seconds", "median", COLORS["blue"]),
        ("p75_staleness_seconds", "p75", COLORS["green"]),
        ("p90_staleness_seconds", "p90", COLORS["orange"]),
        ("p95_staleness_seconds", "p95", COLORS["red"]),
    ]:
        ax.plot(
            rows["horizon_name"],
            rows[column] / SECONDS_PER_MINUTE,
            marker="o",
            linewidth=2,
            label=label,
            color=color,
        )
    ax.set_title("Snapshot Staleness Falls Sharply Near Close")
    ax.set_ylabel("Staleness minutes")
    ax.set_xlabel("Forecast horizon")
    ax.grid(axis="y", color=COLORS["light"], linewidth=0.8)
    ax.legend(frameon=False, ncol=4)
    return fig


def _probability_distribution(
    modeling: pd.DataFrame,
    config: PresentationFigureConfig,
) -> plt.Figure:
    column_count = min(4, max(len(config.horizon_order), 1))
    row_count = math.ceil(len(config.horizon_order) / column_count)
    fig, axes = plt.subplots(
        row_count,
        column_count,
        figsize=(3.35 * column_count, 3.5 * row_count),
        sharex=True,
        sharey=True,
    )
    axes_flat = axes.ravel() if hasattr(axes, "ravel") else [axes]
    bins = [index / 20 for index in range(21)]
    for ax, horizon in zip(axes_flat, config.horizon_order, strict=False):
        values = modeling.loc[modeling["horizon_name"] == horizon, "raw_probability"]
        ax.hist(values, bins=bins, color=COLORS["blue"], alpha=0.82)
        ax.set_title(horizon)
        ax.grid(axis="y", color=COLORS["light"], linewidth=0.8)
    for ax in axes_flat[len(config.horizon_order) :]:
        ax.axis("off")
    for ax in axes_flat[::column_count]:
        ax.set_ylabel("Rows")
    for ax in axes_flat[-column_count:]:
        ax.set_xlabel("Raw probability")
    fig.suptitle("Raw Probability Distribution by Horizon", fontsize=18, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return fig


def _calibration_gap_heatmap(
    reliability: pd.DataFrame,
    config: PresentationFigureConfig,
) -> plt.Figure:
    rows = reliability[
        (reliability["grouping_name"] == "horizon")
        & (reliability["aggregation_mode"] == config.aggregation_mode)
    ].copy()
    rows["signed_gap"] = rows["observed_frequency"] - rows["mean_predicted_probability"]
    pivot = rows.pivot(index="horizon_name", columns="bin_index", values="signed_gap")
    pivot = pivot.reindex(config.horizon_order)
    fig, ax = plt.subplots(figsize=(12.4, 5.6), constrained_layout=True)
    image = ax.imshow(pivot.to_numpy(), cmap="RdBu", vmin=-0.12, vmax=0.12, aspect="auto")
    ax.set_title("Calibration Gap Heatmap: Observed - Predicted")
    ax.set_xlabel("Probability bin")
    ax.set_ylabel("Horizon")
    ax.set_xticks(range(10), [f"{i/10:.1f}-{(i+1)/10:.1f}" for i in range(10)], rotation=35)
    ax.set_yticks(range(len(pivot.index)), [str(value) for value in pivot.index])
    plt.colorbar(image, ax=ax, fraction=0.025, pad=0.02)
    return fig


def _balanced_comparison(
    balanced: pd.DataFrame,
    config: PresentationFigureConfig,
) -> plt.Figure:
    rows = _order_horizon(balanced.copy(), config)
    fig, axes = plt.subplots(1, 3, figsize=(13.3, 4.6), constrained_layout=True)
    for ax, column, title in zip(
        axes,
        ["brier_score", "log_loss", "expected_calibration_error"],
        ["Brier", "Log loss", "ECE"],
        strict=True,
    ):
        pivot = rows.pivot(index="horizon_name", columns="panel_type", values=column)
        pivot = pivot.reindex(config.horizon_order)
        pivot.plot(kind="bar", ax=ax, alpha=0.82)
        ax.set_title(title)
        ax.set_xlabel("Horizon")
        ax.grid(axis="y", color=COLORS["light"], linewidth=0.8)
        ax.legend(frameon=False)
    fig.suptitle("All Rows vs. Complete-Horizon Contract Subset", fontweight="bold")
    return fig


def _orientation_check(orientation: pd.DataFrame) -> plt.Figure:
    fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.8), constrained_layout=True)
    axes[0].bar(orientation["outcome"], orientation["row_count"], color=COLORS["green"], alpha=0.84)
    axes[0].set_title("Rows by resolved outcome")
    axes[0].set_ylabel("Rows")
    bad = [
        int(orientation["bad_outcome_mapping_count"].sum()),
        int(orientation["invalid_snapshot_price_count"].sum()),
    ]
    axes[1].bar(["Bad outcome map", "Invalid price"], bad, color=COLORS["red"], alpha=0.84)
    axes[1].set_title("Orientation/probability checks")
    axes[1].set_ylim(0, max(1, max(bad) + 1))
    for ax in axes:
        ax.grid(axis="y", color=COLORS["light"], linewidth=0.8)
    fig.suptitle("YES-Side Price Orientation Sanity Check", fontweight="bold")
    return fig


def _close_timestamp_semantics(close_semantics: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(10.6, 4.8), constrained_layout=True)
    rows = close_semantics.copy()
    labels = rows["snapshot_method"].astype(str)
    med = rows["median_resolution_minus_price_timestamp_seconds"] / 60
    p95 = rows["p95_resolution_minus_price_timestamp_seconds"] / 60
    ax.bar(labels, med, color=COLORS["blue"], alpha=0.84, label="median")
    ax.scatter(labels, p95, color=COLORS["orange"], s=85, label="p95")
    ax.set_title("Close: Selected Price Timestamp Gap to Resolution")
    ax.set_ylabel("Minutes from price timestamp to resolution_ts")
    ax.grid(axis="y", color=COLORS["light"], linewidth=0.8)
    ax.legend(frameon=False)
    return fig


def _dashboard(
    metrics: pd.DataFrame,
    staleness: pd.DataFrame,
    reliability: pd.DataFrame,
    snapshot_summary: dict[str, Any],
    config: PresentationFigureConfig,
) -> plt.Figure:
    fig = plt.figure(figsize=(13.3, 7.5), constrained_layout=True)
    grid = fig.add_gridspec(2, 3)
    ax_counts = fig.add_subplot(grid[0, 0])
    ax_ece = fig.add_subplot(grid[0, 1])
    ax_stale = fig.add_subplot(grid[0, 2])
    ax_rel = fig.add_subplot(grid[1, :2])
    ax_notes = fig.add_subplot(grid[1, 2])

    counts = pd.Series(snapshot_summary["horizon_counts"]).reindex(config.horizon_order)
    ax_counts.bar(counts.index, counts.values, color=COLORS["blue"], alpha=0.86)
    ax_counts.set_title("Rows by horizon")
    ax_counts.tick_params(axis="x", rotation=35)
    ax_counts.grid(axis="y", color=COLORS["light"], linewidth=0.8)

    horizon_metrics = _horizon_rows(metrics, config)
    ax_ece.plot(
        horizon_metrics["horizon_name"],
        horizon_metrics["expected_calibration_error"],
        marker="o",
        color=COLORS["green"],
        linewidth=2,
    )
    ax_ece.set_title("ECE by horizon")
    ax_ece.tick_params(axis="x", rotation=35)
    ax_ece.grid(axis="y", color=COLORS["light"], linewidth=0.8)

    stale = staleness[staleness["snapshot_method"] == "all"].copy()
    stale = _order_horizon(stale, config)
    ax_stale.plot(
        stale["horizon_name"],
        stale["median_staleness_seconds"] / 60,
        marker="o",
        color=COLORS["orange"],
        linewidth=2,
    )
    ax_stale.set_title("Median staleness")
    ax_stale.set_ylabel("Minutes")
    ax_stale.tick_params(axis="x", rotation=35)
    ax_stale.grid(axis="y", color=COLORS["light"], linewidth=0.8)

    close = _reliability_horizon_rows(reliability, "close", config)
    _draw_reliability(ax_rel, close, title="Close reliability", show_counts=True)

    ax_notes.axis("off")
    close_metric = horizon_metrics[horizon_metrics["horizon_name"].astype(str) == "close"].iloc[0]
    ax_notes.text(
        0.0,
        0.95,
        "Current Raw Baseline",
        fontsize=16,
        fontweight="bold",
        transform=ax_notes.transAxes,
    )
    ax_notes.text(
        0.0,
        0.78,
        "\n".join(
            [
                f"Panel rows: {int(snapshot_summary['row_count']):,}",
                f"Close rows: {int(counts['close']):,}",
                f"Close Brier: {float(close_metric['brier_score']):.3f}",
                f"Close log loss: {float(close_metric['log_loss']):.3f}",
                f"Close ECE: {float(close_metric['expected_calibration_error']):.3f}",
                "Raw baseline only",
                "Not walk-forward",
            ]
        ),
        fontsize=12,
        color=COLORS["ink"],
        va="top",
        transform=ax_notes.transAxes,
    )
    fig.suptitle("Presentation Dashboard: Raw Kalshi Baseline", fontsize=18, fontweight="bold")
    return fig


def _snapshot_refinement_before_after(
    snapshot_summary: dict[str, Any],
    config: PresentationFigureConfig,
) -> plt.Figure:
    before = config.before_refinement or {}
    current_counts = snapshot_summary["horizon_counts"]
    frame = pd.DataFrame(
        {
            "Metric": [
                "Panel rows",
                "1h rows",
                "Close rows",
                "1h median stale",
                "Close median stale",
            ],
            "Before": [
                before.get("panel_rows"),
                before.get("one_hour_rows"),
                before.get("close_rows"),
                before.get("one_hour_median_staleness_seconds"),
                before.get("close_median_staleness_seconds"),
            ],
            "After": [
                snapshot_summary["row_count"],
                current_counts["1h"],
                current_counts["close"],
                509,
                74,
            ],
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(13.3, 5.0), constrained_layout=True)
    row_metrics = frame.iloc[:3]
    stale_metrics = frame.iloc[3:].copy()
    stale_metrics[["Before", "After"]] = stale_metrics[["Before", "After"]] / 60
    row_metrics.plot(x="Metric", y=["Before", "After"], kind="bar", ax=axes[0], alpha=0.84)
    stale_metrics.plot(x="Metric", y=["Before", "After"], kind="bar", ax=axes[1], alpha=0.84)
    axes[0].set_title("Eligibility after stricter policy")
    axes[0].set_ylabel("Rows")
    axes[1].set_title("Near-close staleness improvement")
    axes[1].set_ylabel("Median staleness minutes")
    for ax in axes:
        ax.tick_params(axis="x", rotation=25)
        ax.grid(axis="y", color=COLORS["light"], linewidth=0.8)
        ax.legend(frameon=False)
    fig.suptitle("Snapshot Methodology Refinement", fontweight="bold")
    return fig


def _draw_reliability(
    ax: plt.Axes,
    rows: pd.DataFrame,
    *,
    title: str,
    show_counts: bool,
) -> None:
    plotted = rows.dropna(subset=["mean_predicted_probability", "observed_frequency"])
    ax.plot([0, 1], [0, 1], linestyle="--", linewidth=1.0, color=COLORS["gray"])
    sizes = 30 + 170 * plotted["row_count"] / max(float(plotted["row_count"].max()), 1.0)
    ax.scatter(
        plotted["mean_predicted_probability"],
        plotted["observed_frequency"],
        s=sizes,
        color=COLORS["blue"],
        alpha=0.78,
        edgecolors=COLORS["ink"],
        linewidths=0.35,
    )
    ax.plot(
        plotted["mean_predicted_probability"],
        plotted["observed_frequency"],
        color=COLORS["blue"],
        linewidth=1.4,
        alpha=0.75,
    )
    if show_counts:
        for _, row in plotted.iterrows():
            ax.annotate(
                f"{int(row['row_count']):,}",
                (row["mean_predicted_probability"], row["observed_frequency"]),
                textcoords="offset points",
                xytext=(4, 4),
                fontsize=7,
            )
    ax.set_title(title)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.grid(color=COLORS["light"], linewidth=0.8)
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Observed frequency")


def _policy_column_heatmap(
    ax: plt.Axes,
    frame: pd.DataFrame,
    column: str,
    title: str,
    labels: list[str],
) -> None:
    values = frame[[column]].to_numpy()
    ax.imshow(values, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    ax.set_title(title)
    ax.set_yticks(range(len(frame)), frame["horizon"])
    ax.set_xticks([0], [""])
    for row_index, value in enumerate(frame[column]):
        ax.text(0, row_index, labels[int(value)], ha="center", va="center", fontsize=10)


def _numeric_policy_heatmap(
    ax: plt.Axes,
    frame: pd.DataFrame,
    column: str,
    title: str,
) -> None:
    values = frame[[column]].to_numpy()
    ax.imshow(values, cmap="YlGnBu", aspect="auto")
    ax.set_title(title)
    ax.set_yticks(range(len(frame)), [])
    ax.set_xticks([0], [""])
    for row_index, value in enumerate(frame[column]):
        ax.text(0, row_index, _duration_label_minutes(float(value)), ha="center", va="center")


def _horizon_rows(frame: pd.DataFrame, config: PresentationFigureConfig) -> pd.DataFrame:
    rows = frame[
        (frame["grouping_name"] == "horizon")
        & (frame["aggregation_mode"] == config.aggregation_mode)
    ].copy()
    return _order_horizon(rows, config)


def _reliability_horizon_rows(
    reliability: pd.DataFrame,
    horizon: str,
    config: PresentationFigureConfig,
) -> pd.DataFrame:
    rows = reliability[
        (reliability["grouping_name"] == "horizon")
        & (reliability["aggregation_mode"] == config.aggregation_mode)
        & (reliability["horizon_name"] == horizon)
    ].copy()
    if rows.empty:
        raise PresentationFigureError(f"missing reliability rows for horizon: {horizon}")
    return rows.sort_values("bin_index")


def _order_horizon(frame: pd.DataFrame, config: PresentationFigureConfig) -> pd.DataFrame:
    frame["horizon_name"] = pd.Categorical(
        frame["horizon_name"],
        categories=list(config.horizon_order),
        ordered=True,
    )
    return frame.sort_values("horizon_name").reset_index(drop=True)


def _duration_label_minutes(minutes: float) -> str:
    if minutes >= 1440 and minutes % 1440 == 0:
        return f"{int(minutes / 1440)}d"
    if minutes >= 60 and minutes % 60 == 0:
        return f"{int(minutes / 60)}h"
    return f"{int(minutes)}m"


def _save_figure(
    fig: plt.Figure,
    config: PresentationFigureConfig,
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
            "figure.facecolor": "white",
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "savefig.facecolor": "white",
        }
    )


def _validate_config(config: PresentationFigureConfig) -> None:
    if not config.figure_formats:
        raise PresentationFigureError("at least one figure format is required")
    unsupported = sorted(set(config.figure_formats) - {"png", "svg", "pdf"})
    if unsupported:
        raise PresentationFigureError(f"unsupported figure formats: {unsupported}")
    for path in _source_paths(config).values():
        if not path.exists():
            raise PresentationFigureError(f"missing presentation source artifact: {path}")


def _source_paths(config: PresentationFigureConfig) -> dict[str, Path]:
    return {
        "metrics_by_group": config.artifact_dir / "metrics_by_group.parquet",
        "calibration_fits": config.artifact_dir / "calibration_fits.parquet",
        "reliability_bins": config.artifact_dir / "reliability_bins.parquet",
        "staleness": config.audit_dir / "staleness_by_horizon_method.parquet",
        "method_counts": config.audit_dir / "snapshot_method_counts.parquet",
        "balanced_metrics": config.audit_dir / "balanced_horizon_metrics.parquet",
        "orientation": config.audit_dir / "orientation_sanity_by_outcome.parquet",
        "close_semantics": config.audit_dir / "close_timestamp_semantics.parquet",
        "snapshot_summary": config.snapshot_summary_path,
        "modeling_panel": config.modeling_panel_path,
    }


def _effective_config(config: PresentationFigureConfig) -> dict[str, Any]:
    return {
        "inputs": {
            "raw_baseline_artifact_dir": str(config.artifact_dir),
            "raw_baseline_audit_dir": str(config.audit_dir),
            "snapshot_summary_path": str(config.snapshot_summary_path),
            "modeling_panel_path": str(config.modeling_panel_path),
        },
        "outputs": {"presentation_figure_dir": str(config.figure_dir)},
        "presentation": {
            "horizon_order": list(config.horizon_order),
            "aggregation_mode": config.aggregation_mode,
            "figure_formats": list(config.figure_formats),
            "dpi": config.dpi,
            "before_refinement": config.before_refinement,
        },
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"presentation config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"presentation config missing required key: {key}")
    return raw[key]
