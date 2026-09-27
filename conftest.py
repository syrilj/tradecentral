"""Repo-root conftest: applies the `needs_market_data_files` /
`needs_live_network` markers (registered in pytest.ini) to specific tests
that were measured to fail in a fresh checkout -- no data/, no runs/, no
provider credentials, no guaranteed network -- for reasons that are
environmental, not bugs.

This file exists (rather than `@pytest.mark...` decorators on the tests
themselves) because whoever wired up CI here was scoped to
`.github/workflows/ci.yml`, new root-level files, and `pytest.ini` /
`pyproject.toml` -- not `tests/`, which another worker owns concurrently.
A root-level conftest.py is collected by pytest regardless of that
boundary, so it is the one place this marking can be done without touching
files under `tests/`. If you own `tests/` and are reading this: moving
each entry below to a real `@pytest.mark.needs_market_data_files` /
`@pytest.mark.needs_live_network` decorator on the test itself is the
better long-term home for this -- it stays correct if the test moves or is
renamed, which a nodeid string here does not. Deleting the corresponding
line below when you do is expected and safe.

Every entry names the exact nodeid it applies to and why, so the exclusion
is greppable: `grep -nE "needs_market_data_files|needs_live_network"
conftest.py pytest.ini`.
"""
from __future__ import annotations

import pytest

# nodeid -> (marker name, reason). Reasons are shown by `pytest --markers`
# and duplicated here so this file is self-explanatory without cross-
# referencing the CI audit that produced it.
_MARKED_TESTS: dict[str, tuple[str, str]] = {
    "tests/e2e/test_tier1_features.py::test_f2_3_search_symbols_empty_query_majors_fallback": (
        "needs_market_data_files",
        "api_server's SYMBOL_INDEX is built from data/1d/*.parquet; with no "
        "parquet catalog present the 'liquid majors' fallback list is empty "
        "by construction, independent of the search logic under test.",
    ),
    "tests/e2e/test_tier1_features.py::test_f3_3_parquet_loading_handles_missing_files": (
        "needs_live_network",
        "asserts pead_adapter._load_symbol_df() returns an empty frame for a "
        "made-up ticker, but the adapter's live yfinance fallback has no "
        "mock/fixture seam here, so with real network access it actually "
        "fetches live data for the placeholder symbol and the frame is not "
        "empty. Passes or fails based on Yahoo Finance's live behavior, not "
        "the code path being tested.",
    ),
    "tests/research/test_directional_bakeoff.py::test_frozen_directional_universe_exactly_matches_local_research_cache": (
        "needs_market_data_files",
        "reads data/1d/*.parquet directly and asserts the configured "
        "directional universe is a subset of what's on disk; there is "
        "nothing on disk in a fresh checkout.",
    ),
    "tests/test_m3_adversarial_challenge.py::test_v90_signal_zero_numeric_drift_real_parquets": (
        "needs_market_data_files",
        "self-documenting: asserts 'Expected at least 20 real parquets, "
        "found {n}' against data/1d/*.parquet.",
    ),
    "tests/test_m3_adversarial_challenge.py::test_chain_free_adapter_model_parity_and_contracts": (
        "needs_market_data_files",
        "ChainFreeInternalModelsAdapter is pointed at data/1d and expects "
        "real OHLCV history for AAPL/NVDA/TSLA to produce any candidates.",
    ),
    "tests/test_trajectory_qlib_context.py::test_real_trajectory_payload_agrees_with_deep_on_staggered_ends": (
        "needs_live_network",
        "compares a live-fetched 'last_date' against a previously-frozen "
        "expected date; the two drift apart as real time passes because the "
        "fetch is live, not fixture-backed, so this fails deterministically "
        "on any day after the value was frozen.",
    ),
    "tests/test_rag_pipeline.py::test_model_doctor_diagnosis": (
        "needs_live_network",
        "QuantRAGPipeline initializes LocalSentenceEmbeddingEngine which downloads "
        "the all-MiniLM-L6-v2 model weights from HuggingFace over live network.",
    ),
    "tests/test_vpa_engine.py::test_vpa_health_shape": (
        "needs_market_data_files",
        "requires real OHLCV parquet files in data/1h and data/1d to verify data source counts",
    ),
    "tests/test_drift_backtest.py::test_load_symbol_daily_bars": (
        "needs_market_data_files",
        "reads real OHLCV daily parquet files from data/1d/*.parquet",
    ),
    "tests/test_drift_backtest.py::test_evaluate_systematic_execution": (
        "needs_market_data_files",
        "reads real OHLCV daily parquet files from data/1d/*.parquet",
    ),
    "tests/test_drift_backtest.py::test_evaluate_snapshot_signals": (
        "needs_market_data_files",
        "reads real OHLCV daily parquet files from data/1d/*.parquet",
    ),
    "tests/test_drift_backtest.py::test_run_drift_tab_backtests_smoke": (
        "needs_market_data_files",
        "reads real OHLCV daily parquet files from data/1d/*.parquet",
    ),
    "tests/research/test_regime_accuracy.py::test_spy_out_of_sample_institutional_metrics": (
        "needs_market_data_files",
        "reads data/1d/SPY.parquet to run out-of-sample backtest",
    ),
    "tests/test_decision_oos_capital.py::test_recorded_history_live_capital_stays_unauthorized": (
        "needs_market_data_files",
        "evaluates recorded capital against real data/1d daily parquet history",
    ),
    "tests/test_decision_tree_backtest.py::test_last_completed_week_is_a_strict_unseen_holdout": (
        "needs_market_data_files",
        "reads data/1d/*.parquet to evaluate last week holdout window",
    ),
    "tests/test_m3_adversarial_challenge.py::test_v90_signal_zero_numeric_drift_synthetic": (
        "needs_market_data_files",
        "requires gitignored model weights in models/v90/meta_xgb_long.json",
    ),
    "tests/test_m3_adversarial_challenge.py::test_standard_60_bars_and_252_bars_succeed_across_all_horizons": (
        "needs_market_data_files",
        "requires gitignored model weights in models/v90/meta_xgb_long.json",
    ),
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        entry = _MARKED_TESTS.get(item.nodeid)
        if entry is None:
            continue
        marker_name, reason = entry
        item.add_marker(getattr(pytest.mark, marker_name)(reason=reason))
