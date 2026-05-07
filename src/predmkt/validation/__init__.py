"""Walk-forward splits and leakage checks."""

from predmkt.validation.splits import (
    SplitValidationError,
    ValidationConfig,
    WalkForwardFold,
    WalkForwardSummary,
    assign_walkforward_splits,
    build_walkforward_splits,
    detect_event_family_leakage,
    load_validation_config,
    make_walkforward_folds,
    normalize_split_panel,
    validate_split_integrity,
)

__all__ = [
    "SplitValidationError",
    "ValidationConfig",
    "WalkForwardFold",
    "WalkForwardSummary",
    "assign_walkforward_splits",
    "build_walkforward_splits",
    "detect_event_family_leakage",
    "load_validation_config",
    "make_walkforward_folds",
    "normalize_split_panel",
    "validate_split_integrity",
]
