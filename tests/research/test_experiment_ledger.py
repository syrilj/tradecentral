from __future__ import annotations

import json

import pytest

from edge.research.experiment_ledger import ExperimentLedger, SCHEMA_VERSION


UPSTREAM = [{
    "name": "reference", "url": "https://example.test/reference",
    "commit": "a" * 40, "license": "MIT", "code_imported": False,
}]
BOUNDARIES = {
    "train": {"start": "2015-01-01", "end": "2021-12-31"},
    "validation": {"start": "2022-01-01", "end": "2023-12-31"},
    "terminal_holdout": {"start": "2024-01-01", "end": "2025-12-31"},
}

# Real boundaries, transcribed from the two documents that motivate the
# source_panel conflict check (see the "xs_v3 vs GATE_XS4" tests below).
XS_V3_HOLDOUT_BOUNDARIES = {
    # edge/runs/xs_v3/holdout_final.json: "holdout_start": "2024-08-01",
    # "final_model_train_max_date": "2024-07-31". The holdout is open-ended
    # ("2024-08-01 onward" per edge/runs/xs_v3/DECISION_RECORD.md); the
    # ledger's boundary schema requires a concrete end date, so 9999-12-31 is
    # a documented "no end has been set yet" sentinel, not a real date.
    "train": {"start": "2015-01-01", "end": "2024-06-30"},
    "validation": {"start": "2024-07-01", "end": "2024-07-31"},
    "terminal_holdout": {"start": "2024-08-01", "end": "9999-12-31"},
}
GATE_XS4_CONFIRMATION_BOUNDARIES = {
    # edge/docs/GATE_XS4.md confirmation-phase table, transcribed verbatim.
    "train": {"start": "2016-08-01", "end": "2023-06-30"},
    "validation": {"start": "2023-07-17", "end": "2023-12-29"},
    "terminal_holdout": {"start": "2024-01-16", "end": "2026-07-29"},
}
# Two terminal_holdout windows that do NOT overlap each other, for the
# negative-control test.
EARLY_HOLDOUT_BOUNDARIES = {
    "train": {"start": "2000-01-01", "end": "2009-12-31"},
    "validation": {"start": "2010-01-01", "end": "2010-06-30"},
    "terminal_holdout": {"start": "2010-07-01", "end": "2011-06-30"},
}
LATE_HOLDOUT_BOUNDARIES = {
    "train": {"start": "2012-01-01", "end": "2013-12-31"},
    "validation": {"start": "2014-01-01", "end": "2014-06-30"},
    "terminal_holdout": {"start": "2014-07-01", "end": "2015-06-30"},
}
# edge/tools/qlib_ingest_wide.py:68 -- the root/origin panel both xs_v3
# (directly) and GATE_XS4 (via the qlib_us_1d_wide provider staged from it)
# ultimately read.
SOURCE_PANEL_1D_WIDE = "edge/data/1d_wide"


def _experiment(ledger: ExperimentLedger, *, config=None, fingerprint="daily-dataset-v1", boundaries=None):
    return ledger.preregister_experiment(
        features=["momentum_20", "volatility_20"], model="regularized_logistic",
        config={"C": 0.1, "horizon_days": 10} if config is None else config,
        upstream_provenance=UPSTREAM, dataset_fingerprint=fingerprint,
        boundaries=BOUNDARIES if boundaries is None else boundaries, code_version="edge-commit-123",
    )


def test_preregistration_is_deterministic_and_persists_complete_provenance(tmp_path) -> None:
    path = tmp_path / "experiments.jsonl"
    ledger = ExperimentLedger(path)
    first = _experiment(ledger)
    second = _experiment(ledger, config={"horizon_days": 10, "C": 0.1})
    assert first == second
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == SCHEMA_VERSION
    assert raw["payload"]["dataset_fingerprint"] == "daily-dataset-v1"
    assert raw["payload"]["upstream_provenance"][0]["commit"] == "a" * 40
    assert raw["payload"]["upstream_provenance"][0]["license"] == "MIT"
    assert raw["payload"]["boundaries"] == BOUNDARIES


def test_trial_results_are_append_only_idempotent_and_conflicts_do_not_overwrite(tmp_path) -> None:
    path = tmp_path / "experiments.jsonl"
    ledger = ExperimentLedger(path)
    experiment = _experiment(ledger)
    trial = ledger.preregister_trial(experiment.record_id, features=["momentum_20"], model="baseline", config={"kind": "momentum"})
    result = ledger.record_trial_result(trial.record_id, status="COMPLETED", metrics={"mean_return": 0.01})
    assert ledger.record_trial_result(trial.record_id, status="COMPLETED", metrics={"mean_return": 0.01}) == result
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="append-only conflict"):
        ledger.record_trial_result(trial.record_id, status="COMPLETED", metrics={"mean_return": 0.02})
    assert path.read_text(encoding="utf-8") == before
    assert [record.kind for record in ledger.records] == ["experiment_preregistered", "trial_preregistered", "trial_result"]


def test_terminal_holdout_is_fresh_and_may_be_evaluated_once(tmp_path) -> None:
    ledger = ExperimentLedger(tmp_path / "experiments.jsonl")
    experiment = _experiment(ledger)
    trial = ledger.preregister_trial(experiment.record_id, features=["momentum_20"], model="baseline", config={"kind": "momentum"})
    holdout = ledger.preregister_terminal_holdout(experiment.record_id, dataset_fingerprint="fresh-terminal-2024-2025")
    evaluation = ledger.record_terminal_holdout_evaluation(holdout.record_id, trial_id=trial.record_id, metrics={"net_expectancy": 0.002})
    assert ledger.record_terminal_holdout_evaluation(holdout.record_id, trial_id=trial.record_id, metrics={"net_expectancy": 0.002}) == evaluation
    with pytest.raises(ValueError, match="append-only conflict"):
        ledger.record_terminal_holdout_evaluation(holdout.record_id, trial_id=trial.record_id, metrics={"net_expectancy": 0.003})
    other = _experiment(ledger, config={"C": 1.0, "horizon_days": 20}, fingerprint="daily-dataset-v2")
    with pytest.raises(ValueError, match="already registered"):
        ledger.preregister_terminal_holdout(other.record_id, dataset_fingerprint="fresh-terminal-2024-2025")


def test_boundaries_and_trial_parentage_fail_closed(tmp_path) -> None:
    ledger = ExperimentLedger(tmp_path / "experiments.jsonl")
    invalid = dict(BOUNDARIES)
    invalid["validation"] = {"start": "2021-12-01", "end": "2023-01-01"}
    with pytest.raises(ValueError, match="must not overlap"):
        ledger.preregister_experiment(
            features=["feature"], model="model", config={}, upstream_provenance=UPSTREAM,
            dataset_fingerprint="data", boundaries=invalid, code_version="code",
        )
    one = _experiment(ledger)
    two = _experiment(ledger, config={"C": 2.0}, fingerprint="daily-v3")
    one_trial = ledger.preregister_trial(one.record_id, features=["feature"], model="model", config={})
    two_holdout = ledger.preregister_terminal_holdout(two.record_id, dataset_fingerprint="fresh-two")
    with pytest.raises(ValueError, match="must belong"):
        ledger.record_terminal_holdout_evaluation(two_holdout.record_id, trial_id=one_trial.record_id, metrics={})


def test_terminal_holdout_source_panel_is_optional_and_matches_pre_extension_payload_shape(tmp_path) -> None:
    """Calls that omit source_panel (e.g. edge/research/runner.py:556, the
    only real caller of this method today) must keep producing the exact
    payload shape this method produced before source_panel existed, so
    already-persisted ledgers (edge/runs/research/directional_daily_v1/
    experiments.jsonl and edge/runs/research/directional_daily_etf_v1/
    experiments.jsonl both exist on disk today) stay idempotent against it."""
    ledger = ExperimentLedger(tmp_path / "experiments.jsonl")
    experiment = _experiment(ledger)
    holdout = ledger.preregister_terminal_holdout(experiment.record_id, dataset_fingerprint="no-panel-v1")
    assert set(holdout.payload) == {"experiment_id", "boundaries", "dataset_fingerprint", "status"}
    assert "source_panel" not in holdout.payload
    # Idempotent replay of the identical call must return the same record, not append a new one.
    replay = ledger.preregister_terminal_holdout(experiment.record_id, dataset_fingerprint="no-panel-v1")
    assert replay == holdout


def test_terminal_holdout_source_panel_conflict_catches_overlap_fingerprint_alone_misses(tmp_path) -> None:
    """The scenario the source_panel check exists for. xs_v3's burned holdout
    (2024-08-01 onward) and GATE_XS4.md's "unspent" confirmation window
    (2024-01-16 -> 2026-07-29) overlap in calendar time and both ultimately
    read edge/data/1d_wide (edge/tools/qlib_ingest_wide.py:68 -- GATE_XS4
    reads it indirectly, via the qlib_us_1d_wide provider staged from it),
    but the two pipelines compute different dataset fingerprints for that
    overlap. Fingerprint identity alone (the pre-existing check) is blind to
    this; keying on (source_panel, calendar range) as well must catch it.
    """
    ledger = ExperimentLedger(tmp_path / "experiments.jsonl")
    xs_v3 = _experiment(ledger, fingerprint="xs_v3-experiment-fp-v1", boundaries=XS_V3_HOLDOUT_BOUNDARIES)
    xs_v3_holdout_fingerprint = "xs_v3-holdout-1d_wide-v1"
    ledger.preregister_terminal_holdout(
        xs_v3.record_id, dataset_fingerprint=xs_v3_holdout_fingerprint, source_panel=SOURCE_PANEL_1D_WIDE,
    )
    gate_xs4 = _experiment(
        ledger, config={"arm": "lgb158"}, fingerprint="qlib_xs4-experiment-fp-v1",
        boundaries=GATE_XS4_CONFIRMATION_BOUNDARIES,
    )
    gate_xs4_holdout_fingerprint = "qlib_xs4-confirm-qlib_us_1d_wide-v1"
    # Different fingerprints for calendar-overlapping data on the same panel
    # is exactly the documented bug -- proves the pre-existing check alone
    # would miss this conflict.
    assert gate_xs4_holdout_fingerprint != xs_v3_holdout_fingerprint
    with pytest.raises(ValueError, match="overlaps an already-registered holdout"):
        ledger.preregister_terminal_holdout(
            gate_xs4.record_id, dataset_fingerprint=gate_xs4_holdout_fingerprint, source_panel=SOURCE_PANEL_1D_WIDE,
        )


def test_terminal_holdout_source_panel_conflict_is_scoped_to_the_same_panel(tmp_path) -> None:
    """Same overlapping calendar range, but a genuinely different source
    panel, must NOT conflict -- the check is scoped by panel identity, not
    calendar range alone, so two independent data sources never collide."""
    ledger = ExperimentLedger(tmp_path / "experiments.jsonl")
    one = _experiment(ledger, fingerprint="panel-a-experiment-v1", boundaries=XS_V3_HOLDOUT_BOUNDARIES)
    ledger.preregister_terminal_holdout(
        one.record_id, dataset_fingerprint="panel-a-holdout-v1", source_panel="edge/data/1d_wide",
    )
    two = _experiment(ledger, config={"C": 5.0}, fingerprint="panel-b-experiment-v1", boundaries=GATE_XS4_CONFIRMATION_BOUNDARIES)
    holdout = ledger.preregister_terminal_holdout(
        two.record_id, dataset_fingerprint="panel-b-holdout-v1", source_panel="edge/data/1h",
    )
    assert holdout.payload["source_panel"] == "edge/data/1h"


def test_terminal_holdout_source_panel_conflict_permits_non_overlapping_ranges_on_same_panel(tmp_path) -> None:
    """Two genuinely disjoint holdout windows on the same panel are both
    legitimate registrations -- spending one does not spend the other."""
    ledger = ExperimentLedger(tmp_path / "experiments.jsonl")
    early = _experiment(ledger, fingerprint="early-experiment-v1", boundaries=EARLY_HOLDOUT_BOUNDARIES)
    ledger.preregister_terminal_holdout(
        early.record_id, dataset_fingerprint="early-holdout-v1", source_panel=SOURCE_PANEL_1D_WIDE,
    )
    late = _experiment(ledger, config={"C": 7.0}, fingerprint="late-experiment-v1", boundaries=LATE_HOLDOUT_BOUNDARIES)
    holdout = ledger.preregister_terminal_holdout(
        late.record_id, dataset_fingerprint="late-holdout-v1", source_panel=SOURCE_PANEL_1D_WIDE,
    )
    assert holdout.payload["boundaries"] == LATE_HOLDOUT_BOUNDARIES["terminal_holdout"]


def test_record_trial_result_persists_and_reloads_a_return_series(tmp_path) -> None:
    path = tmp_path / "experiments.jsonl"
    ledger = ExperimentLedger(path)
    experiment = _experiment(ledger)
    trial = ledger.preregister_trial(experiment.record_id, features=["momentum_20"], model="baseline", config={"kind": "momentum"})
    series = [0.01, -0.004, 0.0, 0.02]
    result = ledger.record_trial_result(
        trial.record_id, status="COMPLETED", metrics={"mean_return": 0.0065}, return_series=series,
    )
    assert result.payload["return_series"] == series
    assert result.payload["metrics"] == {"mean_return": 0.0065}
    # Round-trip through disk: a fresh ledger instance over the same file sees the identical series.
    reloaded_result = next(r for r in ExperimentLedger(path).records if r.kind == "trial_result")
    assert reloaded_result.payload["return_series"] == series


def test_record_trial_result_without_return_series_omits_the_key_and_still_loads(tmp_path) -> None:
    path = tmp_path / "experiments.jsonl"
    ledger = ExperimentLedger(path)
    experiment = _experiment(ledger)
    trial = ledger.preregister_trial(experiment.record_id, features=["momentum_20"], model="baseline", config={"kind": "momentum"})
    result = ledger.record_trial_result(trial.record_id, status="COMPLETED", metrics={"mean_return": 0.01})
    assert "return_series" not in result.payload
    # Backward compatibility: a ledger containing only pre-existing,
    # series-less trial_result records still loads cleanly end to end.
    reloaded_result = next(r for r in ExperimentLedger(path).records if r.kind == "trial_result")
    assert "return_series" not in reloaded_result.payload
    assert reloaded_result.payload["metrics"] == {"mean_return": 0.01}


def test_record_trial_result_rejects_empty_or_non_finite_return_series(tmp_path) -> None:
    ledger = ExperimentLedger(tmp_path / "experiments.jsonl")
    experiment = _experiment(ledger)
    trial = ledger.preregister_trial(experiment.record_id, features=["momentum_20"], model="baseline", config={"kind": "momentum"})
    with pytest.raises(ValueError, match="must not be empty"):
        ledger.record_trial_result(trial.record_id, status="COMPLETED", metrics={"mean_return": 0.0}, return_series=[])
    with pytest.raises(ValueError, match="finite"):
        ledger.record_trial_result(
            trial.record_id, status="COMPLETED", metrics={"mean_return": 0.0}, return_series=[0.01, float("inf")],
        )
