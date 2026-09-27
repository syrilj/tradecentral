"""Pure, offline research primitives for the daily directional programme.

The package deliberately contains no model training, provider, broker, or order
code.  It makes the research protocol reproducible before a model is allowed to
consume these utilities.
"""
from .hashing import ExperimentRegistry, experiment_hash, stable_hash, trial_hash
from .labels import (
    FROZEN_HORIZONS,
    directional_labels,
    tradable_directional_labels,
    valid_label_origins,
)
from .provenance import UpstreamSource, load_upstream_provenance
from .regimes import classify_regimes, performance_by_regime, slice_by_regime
from .splits import (
    WalkForwardFold,
    expanding_walk_forward_splits,
    nested_walk_forward_splits,
    purged_embargoed_kfold_splits,
)
from .statistics import (
    BootstrapCI,
    DeflatedSharpeApproximation,
    bonferroni_deflated_sharpe_approximation,
    date_block_bootstrap_ci,
)

__all__ = [
    "BootstrapCI",
    "DeflatedSharpeApproximation",
    "ExperimentRegistry",
    "FROZEN_HORIZONS",
    "UpstreamSource",
    "WalkForwardFold",
    "bonferroni_deflated_sharpe_approximation",
    "classify_regimes",
    "date_block_bootstrap_ci",
    "directional_labels",
    "expanding_walk_forward_splits",
    "experiment_hash",
    "load_upstream_provenance",
    "nested_walk_forward_splits",
    "performance_by_regime",
    "purged_embargoed_kfold_splits",
    "slice_by_regime",
    "stable_hash",
    "trial_hash",
    "tradable_directional_labels",
    "valid_label_origins",
]
