"""Manuscript-ready tables and summaries."""

from predmkt.reports.manuscript import (
    ManuscriptTableSummary,
    ReportingConfig,
    ReportingError,
    load_reporting_config,
    make_manuscript_tables,
)
from predmkt.reports.raw_baseline_audit import (
    RawBaselineAuditConfig,
    RawBaselineAuditSummary,
    build_raw_baseline_audit,
    load_raw_baseline_audit_config,
)
from predmkt.reports.robustness import (
    RobustnessConfig,
    RobustnessSummary,
    load_robustness_config,
    run_robustness,
)

__all__ = [
    "ManuscriptTableSummary",
    "RawBaselineAuditConfig",
    "RawBaselineAuditSummary",
    "ReportingConfig",
    "ReportingError",
    "RobustnessConfig",
    "RobustnessSummary",
    "build_raw_baseline_audit",
    "load_raw_baseline_audit_config",
    "load_robustness_config",
    "load_reporting_config",
    "make_manuscript_tables",
    "run_robustness",
]
