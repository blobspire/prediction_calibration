"""Manuscript-ready figures from saved result artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd  # type: ignore[import-untyped]
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from predmkt.metrics.reliability import reliability_bins
from predmkt.reports.manuscript import (
    ReportingConfig,
    ReportingError,
    _common_limitations,
    _ordered_horizons,
    _ordered_models,
    _validate_reporting_config,
    effective_reporting_config,
    reporting_source_paths,
)

COLORS = {
    "raw": "#6b7280",
    "platt": "#2364aa",
    "beta": "#2a9d8f",
    "isotonic": "#d95f02",
    "ink": "#111827",
    "light": "#e5e7eb",
    "red": "#c1121f",
    "purple": "#6a4c93",
}


@dataclass(frozen=True)
class ManuscriptFigureSummary:
    """Summary of generated manuscript figures."""

    figure_dir: str
    figure_paths: dict[str, list[str]]
    source_artifacts: dict[str, str]
    effective_config: dict[str, Any]
    limitations: list[str]


def make_manuscript_figures(config: ReportingConfig) -> ManuscriptFigureSummary:
    """Write manuscript figures from saved walk-forward and edge artifacts."""

    _validate_reporting_config(config, require_figures=True, require_tables=False)
    config.figure_dir.mkdir(parents=True, exist_ok=True)
    _set_plot_style()

    sources = reporting_source_paths(config)
    predictions = pd.read_parquet(sources["walkforward_predictions"])
    aggregate = pd.read_parquet(sources["walkforward_aggregate_metrics"])
    raw_reliability = pd.read_parquet(sources["raw_baseline_reliability_bins"])
    edge_summary = pd.read_parquet(sources["edge_summary_by_model_tier"])
    simulated_pnl = pd.read_parquet(sources["edge_simulated_pnl"])

    figure_paths = {
        "reliability_overall": _save_figure(
            _reliability_overall_figure(predictions, raw_reliability, config),
            config,
            "manuscript_reliability_overall",
        ),
        "reliability_by_horizon_model": _save_figure(
            _reliability_by_horizon_model_figure(predictions, config),
            config,
            "manuscript_reliability_by_horizon_model",
        ),
        "calibration_slope_heatmap": _save_figure(
            _calibration_slope_heatmap(aggregate, config),
            config,
            "manuscript_calibration_slope_heatmap",
        ),
        "score_comparison": _save_figure(
            _score_comparison_figure(aggregate, config),
            config,
            "manuscript_score_comparison",
        ),
        "edge_friction_sensitivity": _save_figure(
            _edge_friction_sensitivity_figure(edge_summary, config),
            config,
            "manuscript_edge_friction_sensitivity",
        ),
        "edge_simulated_pnl": _save_figure(
            _edge_simulated_pnl_figure(simulated_pnl, config),
            config,
            "manuscript_edge_simulated_pnl",
        ),
    }

    summary = ManuscriptFigureSummary(
        figure_dir=str(config.figure_dir),
        figure_paths={key: [str(path) for path in paths] for key, paths in figure_paths.items()},
        source_artifacts={key: str(path) for key, path in sources.items()},
        effective_config=effective_reporting_config(config),
        limitations=_common_limitations(config),
    )
    (config.figure_dir / "figure_manifest.json").write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def _reliability_overall_figure(
    predictions: pd.DataFrame,
    raw_reliability: pd.DataFrame,
    config: ReportingConfig,
) -> Figure:
    models = _available_models(predictions, config)
    fig, axes = plt.subplots(
        1,
        len(models),
        figsize=(3.8 * len(models), 3.9),
        sharex=True,
        sharey=True,
    )
    axes_list = list(axes.ravel()) if hasattr(axes, "ravel") else [axes]
    raw_rows = _raw_overall_reliability(raw_reliability, config)
    for ax, model_name in zip(axes_list, models, strict=True):
        rows = _prediction_reliability_rows(
            predictions[predictions["model_name"] == model_name],
            config,
        )
        if model_name == "raw" and not raw_rows.empty:
            _draw_reliability(ax, raw_rows, "Raw baseline bins", "#9ca3af", alpha=0.45)
        _draw_reliability(ax, rows, model_name, COLORS.get(model_name, "#2364aa"))
        ax.set_title(model_name, loc="left")
    axes_list[0].set_ylabel("Observed frequency")
    for ax in axes_list:
        ax.set_xlabel("Mean predicted probability")
    fig.suptitle("Out-of-Sample Reliability by Model", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    return fig


def _reliability_by_horizon_model_figure(
    predictions: pd.DataFrame,
    config: ReportingConfig,
) -> Figure:
    available_models = _available_models(predictions, config)
    model = "raw" if "raw" in set(predictions["model_name"]) else available_models[0]
    horizons = [item for item in config.horizon_order if item in set(predictions["horizon_name"])]
    if not horizons:
        raise ReportingError("no configured horizons found in walk-forward predictions")
    column_count = min(3, len(horizons))
    row_count = (len(horizons) + column_count - 1) // column_count
    fig, axes = plt.subplots(
        row_count,
        column_count,
        figsize=(3.6 * column_count, 3.4 * row_count),
        sharex=True,
        sharey=True,
    )
    axes_list = list(axes.ravel()) if hasattr(axes, "ravel") else [axes]
    for ax, horizon_name in zip(axes_list, horizons, strict=False):
        frame = predictions[
            (predictions["model_name"] == model)
            & (predictions["horizon_name"].astype(str) == horizon_name)
        ]
        rows = _prediction_reliability_rows(frame, config)
        _draw_reliability(ax, rows, horizon_name, COLORS.get(model, "#2364aa"))
    for ax in axes_list[len(horizons) :]:
        ax.axis("off")
    for ax in axes_list[::column_count]:
        ax.set_ylabel("Observed frequency")
    for ax in axes_list[-column_count:]:
        ax.set_xlabel("Mean predicted probability")
    fig.suptitle(f"Out-of-Sample Reliability by Horizon ({model})", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return fig


def _calibration_slope_heatmap(aggregate: pd.DataFrame, config: ReportingConfig) -> Figure:
    rows = _horizon_metric_rows(aggregate, config)
    pivot = rows.pivot_table(
        index="model_name",
        columns="horizon_name",
        values="calibration_slope",
        aggfunc="first",
        observed=True,
    )
    pivot = (
        pivot.reindex(index=list(config.model_order), columns=list(config.horizon_order))
        .dropna(how="all", axis=0)
        .dropna(how="all", axis=1)
    )
    if pivot.empty:
        raise ReportingError("no calibration slope values available for heatmap")
    fig, ax = plt.subplots(figsize=(1.05 * len(pivot.columns) + 2.2, 0.65 * len(pivot) + 2.0))
    values = pivot.astype(float)
    image = ax.imshow(values, cmap="RdBu_r", vmin=0.5, vmax=1.5, aspect="auto")
    ax.set_xticks(range(len(values.columns)), values.columns)
    ax.set_yticks(range(len(values.index)), values.index)
    ax.set_title("Calibration Slope by Model and Horizon")
    for row_index, model_name in enumerate(values.index):
        for column_index, horizon_name in enumerate(values.columns):
            value = values.loc[model_name, horizon_name]
            if pd.notna(value):
                ax.text(
                    column_index,
                    row_index,
                    f"{value:.2f}",
                    ha="center",
                    va="center",
                    fontsize=8,
                )
    fig.colorbar(image, ax=ax, label="Slope (ideal = 1)")
    fig.tight_layout()
    return fig


def _score_comparison_figure(aggregate: pd.DataFrame, config: ReportingConfig) -> Figure:
    rows = aggregate[
        (aggregate["metric_scope"] == config.metric_scope)
        & (aggregate["grouping_name"] == "overall")
    ].copy()
    rows = _ordered_models(rows, config)
    metrics = [
        ("brier_score", "Brier score"),
        ("log_loss", "Log loss"),
        ("expected_calibration_error", "ECE"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 3.9), constrained_layout=True)
    for ax, (column, label) in zip(axes, metrics, strict=True):
        ax.bar(
            rows["model_name"],
            rows[column].astype(float),
            color=[COLORS.get(model, "#2364aa") for model in rows["model_name"]],
            alpha=0.88,
        )
        ax.set_title(label, loc="left")
        ax.set_ylabel("Lower is better")
        ax.grid(axis="y", color=COLORS["light"], linewidth=0.8)
        ax.tick_params(axis="x", rotation=35)
    fig.suptitle("Out-of-Sample Score Comparison", fontsize=14, fontweight="bold")
    return fig


def _edge_friction_sensitivity_figure(
    edge_summary: pd.DataFrame,
    config: ReportingConfig,
) -> Figure:
    rows = _ordered_models(edge_summary.copy(), config)
    tiers = ["fee_only", "fee_spread", "fee_spread_slippage"]
    models = [model for model in config.model_order if model in set(rows["model_name"])]
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.3), constrained_layout=True)
    for model_name in models:
        frame = rows[rows["model_name"] == model_name].set_index("friction_tier").reindex(tiers)
        axes[0].plot(
            tiers,
            frame["mean_net_edge"].astype(float),
            marker="o",
            label=model_name,
            color=COLORS.get(model_name),
        )
        axes[1].plot(
            tiers,
            frame["selected_share"].astype(float),
            marker="o",
            label=model_name,
            color=COLORS.get(model_name),
        )
    axes[0].axhline(0.0, color=COLORS["ink"], linewidth=0.9)
    axes[0].set_title("Mean net edge")
    axes[0].set_ylabel("Probability points")
    axes[1].set_title("Share passing threshold")
    axes[1].set_ylabel("Share")
    for ax in axes:
        ax.grid(axis="y", color=COLORS["light"], linewidth=0.8)
        ax.tick_params(axis="x", rotation=25)
        ax.legend(frameon=False)
    fig.suptitle("Edge Sensitivity to Conservative Friction Tiers", fontsize=14, fontweight="bold")
    return fig


def _edge_simulated_pnl_figure(
    simulated_pnl: pd.DataFrame,
    config: ReportingConfig,
) -> Figure:
    fig, ax = plt.subplots(figsize=(8.8, 4.4), constrained_layout=True)
    if simulated_pnl.empty:
        ax.text(
            0.5,
            0.5,
            "No threshold-passing simulated edge rows",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        return fig
    rows = simulated_pnl.copy()
    rows["forecast_ts"] = pd.to_datetime(rows["forecast_ts"], utc=True, errors="coerce")
    models = [model for model in config.model_order if model in set(rows["model_name"])]
    preferred_tier = "fee_spread_slippage"
    if preferred_tier not in set(rows["friction_tier"]):
        preferred_tier = str(rows["friction_tier"].iloc[0])
    for model_name in models:
        frame = rows[
            (rows["model_name"] == model_name)
            & (rows["friction_tier"] == preferred_tier)
        ].sort_values(["forecast_ts", "row_id"])
        if frame.empty:
            continue
        ax.plot(
            frame["forecast_ts"],
            frame["cumulative_simulated_pnl"].astype(float),
            label=model_name,
            color=COLORS.get(model_name),
            linewidth=1.4,
        )
    ax.axhline(0.0, color=COLORS["ink"], linewidth=0.9)
    ax.set_title(f"Simulated Cumulative PnL ({preferred_tier})")
    ax.set_ylabel("Simulated net per configured contract size")
    ax.set_xlabel("Forecast timestamp")
    ax.grid(axis="y", color=COLORS["light"], linewidth=0.8)
    ax.legend(frameon=False)
    fig.suptitle(
        "Assumption-Dependent Edge Screen PnL",
        fontsize=14,
        fontweight="bold",
    )
    return fig


def _prediction_reliability_rows(
    frame: pd.DataFrame,
    config: ReportingConfig,
) -> pd.DataFrame:
    if frame.empty:
        raise ReportingError("cannot draw reliability figure from empty prediction frame")
    bins = reliability_bins(
        frame["predicted_probability"].astype(float).tolist(),
        frame["observed_outcome"].astype(float).tolist(),
        bin_count=config.reliability_bin_count,
        min_bin_count=config.reliability_min_bin_count,
    )
    total = len(frame)
    return pd.DataFrame(
        {
            "bin_index": item.bin_index,
            "bin_lower": item.bin_lower,
            "bin_upper": item.bin_upper,
            "row_count": item.row_count,
            "mean_predicted_probability": item.mean_predicted_probability,
            "observed_frequency": item.observed_frequency,
            "is_sparse": item.is_sparse,
            "total_row_count": total,
        }
        for item in bins
    )


def _raw_overall_reliability(
    raw_reliability: pd.DataFrame,
    config: ReportingConfig,
) -> pd.DataFrame:
    rows = raw_reliability[
        (raw_reliability["aggregation_mode"] == config.aggregation_mode)
        & (raw_reliability["grouping_name"] == "overall")
    ].copy()
    return rows.sort_values("bin_index")


def _horizon_metric_rows(aggregate: pd.DataFrame, config: ReportingConfig) -> pd.DataFrame:
    rows = aggregate[
        (aggregate["metric_scope"] == config.metric_scope)
        & (aggregate["grouping_name"] == "horizon")
    ].copy()
    if rows.empty:
        raise ReportingError("no horizon aggregate metrics available")
    if "horizon_name" not in rows.columns:
        rows["horizon_name"] = rows["group_key"]
    return _ordered_models(_ordered_horizons(rows, config), config)


def _draw_reliability(
    ax: Axes,
    rows: pd.DataFrame,
    label: str,
    color: str,
    *,
    alpha: float = 0.84,
) -> None:
    plotted = rows.dropna(subset=["mean_predicted_probability", "observed_frequency"]).copy()
    ax.plot([0, 1], [0, 1], color="#6b7280", linestyle="--", linewidth=0.9)
    if not plotted.empty:
        sizes = 24 + 120 * plotted["row_count"] / max(float(plotted["row_count"].max()), 1.0)
        ax.scatter(
            plotted["mean_predicted_probability"],
            plotted["observed_frequency"],
            s=sizes,
            color=color,
            alpha=alpha,
            edgecolors=COLORS["ink"],
            linewidths=0.35,
            label=label,
        )
        ax.plot(
            plotted["mean_predicted_probability"],
            plotted["observed_frequency"],
            color=color,
            linewidth=1.1,
            alpha=alpha,
        )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.grid(color=COLORS["light"], linewidth=0.8)


def _available_models(frame: pd.DataFrame, config: ReportingConfig) -> list[str]:
    present = set(frame["model_name"].astype(str))
    models = [model for model in config.model_order if model in present]
    if not models:
        raise ReportingError("no configured models found in saved predictions")
    return models


def _save_figure(fig: Figure, config: ReportingConfig, stem: str) -> list[Path]:
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
