from __future__ import annotations

from pathlib import Path

import pytest

from edge.research.hashing import ExperimentRegistry, experiment_hash, stable_hash, trial_hash
from edge.research.provenance import UpstreamSource, load_upstream_provenance


def test_provenance_is_pinned_and_runtime_safe() -> None:
    path = Path(__file__).resolve().parents[2] / "config" / "upstream_provenance.json"
    sources = load_upstream_provenance(path)
    assert {source.name for source in sources} == {
        "machine-learning-for-trading",
        "gs-quant",
        "financial-models-numerical-methods",
    }
    assert all(len(source.commit) == 40 and not source.code_imported for source in sources)
    with pytest.raises(ValueError, match="40-character"):
        UpstreamSource("bad", "https://example.com", "short", "MIT", "p", "u")


def test_hashes_are_mapping_order_independent_and_trial_specific() -> None:
    left = {"features": ["ret_5", "vol_20"], "horizon": 10, "threshold": 0.55}
    right = {"threshold": 0.55, "horizon": 10, "features": ["ret_5", "vol_20"]}
    assert stable_hash(left) == stable_hash(right)
    experiment = experiment_hash(left, data_fingerprint="daily-v1", code_version="abc123")
    assert experiment == experiment_hash(right, data_fingerprint="daily-v1", code_version="abc123")
    assert trial_hash(experiment, {"C": 1.0}) != trial_hash(experiment, {"C": 0.1})


def test_registry_is_append_only_idempotent_and_requires_parent() -> None:
    registry = ExperimentRegistry()
    experiment = registry.record_experiment({"horizon": 5}, data_fingerprint="data", code_version="code")
    assert registry.record_experiment({"horizon": 5}, data_fingerprint="data", code_version="code") is experiment
    trial = registry.record_trial(experiment.identifier, {"model": "logit", "C": 1.0})
    assert [entry.kind for entry in registry.entries] == ["experiment", "trial"]
    assert trial.sequence == 1
    with pytest.raises(ValueError, match="registered experiment"):
        registry.record_trial("missing", {"model": "logit"})
