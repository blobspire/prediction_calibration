"""Manuscript-ready tables and summaries."""

from predmkt.reports.final_audit import (
    FinalAuditConfig,
    FinalAuditError,
    FinalAuditSummary,
    build_final_audit,
    load_final_audit_config,
)
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
    "FinalAuditConfig",
    "FinalAuditError",
    "FinalAuditSummary",
    "ManuscriptTableSummary",
    "RawBaselineAuditConfig",
    "RawBaselineAuditSummary",
    "ReportingConfig",
    "ReportingError",
    "RobustnessConfig",
    "RobustnessSummary",
    "build_final_audit",
    "build_raw_baseline_audit",
    "load_final_audit_config",
    "load_raw_baseline_audit_config",
    "load_robustness_config",
    "load_reporting_config",
    "make_manuscript_tables",
    "run_robustness",
]
