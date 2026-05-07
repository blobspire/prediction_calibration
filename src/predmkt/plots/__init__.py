"""Publication figure generation."""

from predmkt.plots.manuscript import (
    ManuscriptFigureSummary,
    make_manuscript_figures,
)
from predmkt.plots.presentation import (
    PresentationFigureConfig,
    PresentationFigureSummary,
    build_presentation_figures,
    load_presentation_figure_config,
)
from predmkt.plots.raw_baseline import (
    RawBaselinePlotConfig,
    RawBaselinePlotSummary,
    build_raw_baseline_plots,
    load_raw_baseline_plot_config,
)

__all__ = [
    "ManuscriptFigureSummary",
    "PresentationFigureConfig",
    "PresentationFigureSummary",
    "RawBaselinePlotConfig",
    "RawBaselinePlotSummary",
    "build_presentation_figures",
    "build_raw_baseline_plots",
    "load_presentation_figure_config",
    "load_raw_baseline_plot_config",
    "make_manuscript_figures",
]
