"""Statistical-correctness tests for research/vpa_backtest.py.

These do NOT run the VPA engine (too slow, and not the point). They build
synthetic panels of pre-computed (direction, forward_return, as_of) rows with
known statistical properties and exercise the harness's statistics layer --
the cluster bootstrap, the time-based purge, rolling origins, cost
adjustment, and the verdict logic -- directly. `run_backtest` itself is
exercised end-to-end by monkeypatching `_collect_observations`, which is the
only place it touches the (real, slow) engine.
"""

import datetime as dt
import pickle
import random

import pytest

from research.vpa_backtest import (
    _aggregate_origin_verdict,
    _collect_observations,
    _observations,
    _observations_worker,
    _origin_dispersion,
    _origin_fractions,
    _summarise,
    _time_split,
    run_backtest,
)


def _dates(n):
    """`n` sequential weekday ISO date strings, starting 2020-01-01."""
    start = dt.date(2020, 1, 1)
    out = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def _row(symbol, as_of, direction, forward_return, prob=60):
    return {
        "symbol": symbol,
        "as_of": as_of,
        "direction": direction,
        "probability_pct": prob,
        "confidence": 0.6,
        "forward_return": forward_return,
        "evidence_count": 3,
    }


# ---------------------------------------------------------------------------
# D1. Clustered bootstrap.
# ---------------------------------------------------------------------------

def test_clustered_ci_is_wider_than_naive_se_under_cross_sectional_dependence():
    """Every symbol on a date moves together (shared daily shock); direction
    is genuinely random. The naive per-row SE treats this as ~1,500
    independent draws; the true independent information is ~30 days. The
    clustered CI must be markedly wider -- this is the whole point of D1."""
    rng = random.Random(7)
    dates = _dates(30)
    n_symbols = 50
    rows = []
    for d in dates:
        day_up = rng.random() < 0.5
        # All symbols get the SAME call on a given date: the entire day's
        # "signal" is one shared draw, not `n_symbols` independent ones, so
        # whether a call hits is fully determined per-date (up to tiny
        # noise). ~1,500 rows, but only ~30 independent Bernoulli draws.
        direction = "BULLISH" if rng.random() < 0.5 else "BEARISH"
        for s in range(n_symbols):
            fwd = (0.01 if day_up else -0.01) + rng.gauss(0, 0.0005)
            rows.append(_row(f"SYM{s}", d, direction, fwd))

    summary = _summarise(rows, "test", n_boot=2000, seed=42)
    naive_se = summary["hit_rate_stderr"]
    ci = summary["hit_rate_ci_clustered"]
    assert ci["lo"] is not None and ci["hi"] is not None

    naive_width = 2 * 1.96 * naive_se
    clustered_width = ci["hi"] - ci["lo"]
    # The real-data pilot found clustered CIs 3-5x wider than naive; this
    # synthetic panel has near-total within-date dependence, so demand at
    # least 2x to keep the test robust without being flaky.
    assert clustered_width > 2 * naive_width, (clustered_width, naive_width)


def test_bootstrap_recovers_known_interval_on_independent_data():
    """Sanity check: with one observation per date (no overlap, no
    cross-section), the clustered bootstrap must NOT be gratuitously wide --
    it should track the naive binomial interval reasonably closely, proving
    the machinery isn't just "always report a huge interval"."""
    rng = random.Random(11)
    dates = _dates(400)
    p_hit = 0.55
    rows = []
    for d in dates:
        direction = "BULLISH" if rng.random() < 0.5 else "BEARISH"
        hit = rng.random() < p_hit
        mag = abs(rng.gauss(0.01, 0.002))
        if direction == "BULLISH":
            fwd = mag if hit else -mag
        else:
            fwd = -mag if hit else mag
        rows.append(_row("ONLY", d, direction, fwd))

    summary = _summarise(rows, "test", n_boot=2000, seed=99)
    naive_se = summary["hit_rate_stderr"]
    ci = summary["hit_rate_ci_clustered"]
    naive_width = 2 * 1.96 * naive_se
    clustered_width = ci["hi"] - ci["lo"]
    ratio = clustered_width / naive_width
    assert 0.5 <= ratio <= 2.0, ratio
    assert abs(summary["hit_rate"] - p_hit) < 0.07


def test_clustered_point_estimate_matches_plain_hit_rate():
    """The bootstrap point estimate (mean over all dates counted once) must
    reproduce the existing, unchanged `hit_rate` formula exactly."""
    rng = random.Random(3)
    dates = _dates(60)
    rows = []
    for d in dates:
        for s in range(5):
            direction = "BULLISH" if rng.random() < 0.5 else "BEARISH"
            rows.append(_row(f"S{s}", d, direction, rng.gauss(0, 0.01)))
    summary = _summarise(rows, "test", n_boot=50, seed=1)
    # Different rounding precision (6dp for the CI point, 4dp for the plain
    # field) means exact equality isn't meaningful; they must agree to 4dp.
    assert round(summary["hit_rate_ci_clustered"]["point"], 4) == summary["hit_rate"]


# ---------------------------------------------------------------------------
# D2. Time-based purge.
# ---------------------------------------------------------------------------

def test_time_purge_removes_forward_window_overlap_and_respects_embargo():
    dates = _dates(200)
    horizon = 10
    rows = [_row("X", d, "BULLISH", 0.01) for d in dates]
    is_rows, oos_rows, purged, cut_date = _time_split(rows, dates, 0.6, horizon)

    cut_idx = dates.index(cut_date)
    date_idx = {d: i for i, d in enumerate(dates)}

    for o in is_rows:
        assert date_idx[o["as_of"]] + horizon <= cut_idx
    for o in oos_rows:
        assert date_idx[o["as_of"]] >= cut_idx + horizon

    assert purged > 0
    assert purged == len(rows) - len(is_rows) - len(oos_rows)


def test_time_purge_scales_with_calendar_days_not_row_count():
    """The bug (D2): dropping `horizon` pooled ROWS drops a fraction of a
    single trading day once many symbols share each date. The fix must drop
    observations across a band of distinct DATES around the cut -- a band
    whose size is a function of `horizon` alone, regardless of how many
    symbols (here 60) are stacked on each date. The band is ~2*horizon wide
    (an embargo of `horizon` dates is enforced on each side of the cut),
    exactly as the old (buggy) row-based purge intended but failed to
    achieve once multiple symbols shared a date."""
    dates = _dates(100)
    horizon = 10
    symbols_per_date = 60
    rows = []
    for d in dates:
        for s in range(symbols_per_date):
            rows.append(_row(f"S{s}", d, "BULLISH", 0.01))

    is_rows, oos_rows, purged, cut_date = _time_split(rows, dates, 0.6, horizon)
    purged_dates = (
        {o["as_of"] for o in rows} - {o["as_of"] for o in is_rows} - {o["as_of"] for o in oos_rows}
    )
    expected_band = 2 * horizon - 1  # cut_idx-horizon+1 .. cut_idx+horizon-1 inclusive
    assert len(purged_dates) == expected_band
    assert purged == expected_band * symbols_per_date
    # And critically: the band size does NOT scale with symbols_per_date --
    # it is fixed by `horizon` regardless of how many rows share a date.
    assert len(purged_dates) < symbols_per_date


# ---------------------------------------------------------------------------
# D3. Rolling origins.
# ---------------------------------------------------------------------------

def test_origin_fractions_include_the_primary_split_exactly():
    fracs = _origin_fractions(5, 0.6)
    assert len(fracs) == 5
    assert any(abs(f - 0.6) < 1e-9 for f in fracs)
    assert fracs == sorted(fracs)


def test_rolling_origins_produce_one_result_per_origin_and_a_dispersion_figure():
    fracs = _origin_fractions(5, 0.6)
    dates = _dates(300)
    rng = random.Random(3)
    rows = [
        _row("X", d, "BULLISH" if rng.random() < 0.5 else "BEARISH", rng.gauss(0, 0.01))
        for d in dates
    ]
    origin_results = []
    for i, frac in enumerate(fracs):
        _, oos_rows, _, cut_date = _time_split(rows, dates, frac, 10)
        oos_s = _summarise(oos_rows, "out-of-sample", n_boot=200, seed=100 + i)
        origin_results.append(
            {
                "split_fraction": frac,
                "split_date": cut_date,
                "out_of_sample": oos_s,
                "in_sample": {},
                "verdict": "no edge",
                "purged_observations": 0,
            }
        )

    assert len(origin_results) == 5
    disp = _origin_dispersion(origin_results)
    assert disp["n_origins"] == 5
    assert "stdev" in disp and "range" in disp and "mean" in disp


def test_aggregate_origin_verdict_flags_inconsistency_as_noise():
    fake = [
        {"verdict": "signal"},
        {"verdict": "no edge"},
        {"verdict": "no edge"},
        {"verdict": "no edge"},
    ]
    agg = _aggregate_origin_verdict(fake)
    assert agg["verdict"] == "inconsistent across origins"
    assert "noise" in agg["notes"][0].lower()


def test_aggregate_origin_verdict_requires_all_origins_to_agree_for_signal():
    fake = [{"verdict": "signal"}] * 4
    agg = _aggregate_origin_verdict(fake)
    assert agg["verdict"] == "signal"

    fake_noedge = [{"verdict": "no edge"}] * 4
    assert _aggregate_origin_verdict(fake_noedge)["verdict"] == "no measurable edge"


# ---------------------------------------------------------------------------
# D4. Costs.
# ---------------------------------------------------------------------------

def test_costs_reduce_net_mean_return_by_expected_amount():
    dates = _dates(50)
    rows = [_row("X", d, "BULLISH", 0.02) for d in dates]
    summary = _summarise(rows, "test", cost_bp=10.0, n_boot=100, seed=1)
    assert summary["mean_forward_return"] == pytest.approx(0.02, abs=1e-9)
    assert summary["mean_forward_return_net"] == pytest.approx(0.02 - 10.0 / 10000.0, abs=1e-9)

    bull = summary["by_direction"]["BULLISH"]
    assert bull["mean_forward_return_net"] == pytest.approx(
        bull["mean_forward_return"] - 10.0 / 10000.0, abs=1e-9
    )


# ---------------------------------------------------------------------------
# D5. Verdict keyed off the clustered interval, planted-signal / pure-noise
# end-to-end checks via run_backtest (with _collect_observations stubbed out
# so these stay fast and don't touch the real engine or disk).
# ---------------------------------------------------------------------------

def _make_fake_collect(rows):
    def fake_collect(symbols_, timeframe, horizon, stride, max_bars, jobs=1):
        return list(rows), []
    return fake_collect


def test_planted_true_signal_is_detected_as_signal(monkeypatch):
    """A synthetic panel where direction genuinely predicts the forward
    return (68% correct, +/-2% magnitude, small noise) must be reported as
    signal -- consistently across every rolling origin. A harness that can
    only ever say 'no edge' is useless; this proves it can say yes."""
    rng = random.Random(21)
    dates = _dates(500)
    symbols = [f"SYM{i}" for i in range(15)]
    rows = []
    for d in dates:
        for sym in symbols:
            direction = "BULLISH" if rng.random() < 0.5 else "BEARISH"
            correct = rng.random() < 0.68
            if direction == "BULLISH":
                sign = 1 if correct else -1
            else:
                sign = -1 if correct else 1
            fwd = sign * 0.02 + rng.gauss(0, 0.004)
            rows.append(_row(sym, d, direction, fwd, prob=65))

    monkeypatch.setattr("research.vpa_backtest._collect_observations", _make_fake_collect(rows))

    report = run_backtest(
        ["SYM0"], horizon=10, stride=1, split=0.6, n_boot=500, n_origins=4, seed=5
    )
    assert report["interpretation"]["verdict"] == "signal"
    for o in report["rolling_origins"]:
        assert o["verdict"] == "signal", o


def test_pure_noise_is_reported_as_no_edge_across_origins(monkeypatch):
    """Direction carries zero information. The harness must not manufacture
    a signal verdict, and must not flip-flop across origins."""
    rng = random.Random(55)
    dates = _dates(400)
    symbols = [f"SYM{i}" for i in range(10)]
    rows = []
    for d in dates:
        for sym in symbols:
            direction = "BULLISH" if rng.random() < 0.5 else "BEARISH"
            fwd = rng.gauss(0, 0.01)
            rows.append(_row(sym, d, direction, fwd))

    monkeypatch.setattr("research.vpa_backtest._collect_observations", _make_fake_collect(rows))

    report = run_backtest(
        ["SYM0"], horizon=10, stride=1, split=0.6, n_boot=500, n_origins=4, seed=9
    )
    assert report["interpretation"]["verdict"] in ("no measurable edge", "inconclusive")
    signal_origins = [o for o in report["rolling_origins"] if o["verdict"] == "signal"]
    assert signal_origins == []


# ---------------------------------------------------------------------------
# D6. Parallel worker must be a plain, picklable, top-level wrapper (no
# closures / bound state) -- this is what makes `--jobs` safe with
# ProcessPoolExecutor. Doesn't actually spin up a process pool here to keep
# the suite fast and avoid platform-specific spawn flakiness in CI.
# ---------------------------------------------------------------------------

def test_observations_worker_is_a_plain_picklable_module_level_function():
    pickle.dumps(_observations_worker)


def test_collect_observations_sequential_path_matches_symbol_order(monkeypatch):
    calls = []

    def fake_observations(symbol, timeframe, horizon, stride, max_bars):
        calls.append(symbol)
        if symbol == "SKIP":
            return []
        return [_row(symbol, "2020-01-02", "BULLISH", 0.01)]

    monkeypatch.setattr("research.vpa_backtest._observations", fake_observations)
    rows, skipped = _collect_observations(["AAA", "SKIP", "BBB"], "1D", 10, 5, 1200, jobs=1)
    assert calls == ["AAA", "SKIP", "BBB"]
    assert skipped == ["SKIP"]
    assert {r["symbol"] for r in rows} == {"AAA", "BBB"}


# ---------------------------------------------------------------------------
# Look-ahead regression: `_observations` must call the engine with
# symbol=None. The engine prefers its own on-disk bars whenever a symbol is
# supplied (the UI contract), so passing the symbol would silently analyse
# the *present* window for every historical as-of date and reduce the whole
# walk-forward to a per-symbol constant.
# ---------------------------------------------------------------------------

def test_observations_feeds_history_only_and_no_symbol(monkeypatch):
    bars = [
        {"d": f"2020-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}", "c": 100.0 + i}
        for i in range(460)
    ]
    seen = []

    def fake_analyze(symbol, timeframe, ohlcv_series=None, **_):
        seen.append((symbol, len(ohlcv_series or [])))
        return {
            "primary_scenario": {"direction": "BULLISH", "probability_pct": 57},
            "confidence_score": 0.6,
        }

    monkeypatch.setattr("research.vpa_backtest.load_bars", lambda *a, **k: (bars, {}))
    monkeypatch.setattr("research.vpa_engine.analyze_chart_vpa", fake_analyze)

    rows = _observations("TESTSYMBOL", "1D", horizon=10, stride=100, max_bars=300)

    assert rows, "expected at least one observation"
    assert seen, "engine was never called"
    assert all(sym is None for sym, _ in seen)
    # Every engine call saw a truncated history, never the full panel.
    assert all(n < len(bars) for _, n in seen)
    assert [n for _, n in seen] == sorted(n for _, n in seen)
    assert all(r["symbol"] == "TESTSYMBOL" for r in rows)
