"""Guard: portfolio-return accounting under edge/tools/ must route through
edge.research.portfolio.simulate_long_short.

Context (see edge/docs/LOOKAHEAD_CORRECTION.md): two PEAD simulators
hand-rolled `long_w.iloc[i:i+h] * close.pct_change(1)` and booked a weight
formed from bar i's own features against bar i's own realised return,
reporting +502.98%/Sharpe 5.38 where the honest answer was -10.38%/Sharpe
-0.26. `simulate_long_short` makes that pattern unrepresentable (it raises for
`execution_lag < 1`), but only for callers that actually use it. As of P1-5,
19 of 21 identified portfolio-return-computing tools hand-rolled their own
return alignment "in at least three different spellings" instead.

This test does not (and cannot, via static analysis) prove a file's alignment
is *correct*. It proves something narrower but load-bearing: that a module
computing a Sharpe-shaped annualized statistic from a return series is either
routed through the shared, audited primitive, or is a REVIEWED, COMMENTED,
NAMED exception in ALLOWLIST below. A new hand-rolled Sharpe landing in
edge/tools/ with no entry here fails this test -- that is the guard.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"

_ANNUALIZE_RE = re.compile(r"sqrt\(\s*252\s*\)|sqrt\(\s*TRADING_DAYS\s*\)")
_PRIMITIVE_MARKER = "simulate_long_short"

# Every entry is a deliberate, reviewed exemption with a stated reason -- not
# "not gotten to yet". Two different kinds of reason appear below, and they
# are NOT equivalent risk: read the comment, not just the presence of a key.
ALLOWLIST: dict[str, str] = {
    # --- Pure diagnostics: read/report already-computed results, emit no
    # verdict, compute no portfolio return of their own. Explicitly named as
    # such in the P1-5 task spec. ---------------------------------------
    "audit_wide_data.py": (
        "Pure data-quality diagnostic (gap/duplicate/split checks). Emits no "
        "verdict and computes no portfolio return."
    ),
    "render_dashboard.py": (
        "Renders already-computed run artifacts (JSON/parquet) to HTML/plots. "
        "Computes no portfolio return of its own."
    ),
    "api_server.py": (
        "Serves already-computed run artifacts over HTTP. Computes no "
        "portfolio return of its own."
    ),
    "fetch_vol_complex.py": (
        "sqrt(252) here annualizes a REALIZED-volatility feature "
        "(spy_realized_vol_20d = rolling std * sqrt(252)), not a portfolio "
        "return -- no weights, no close-to-close P&L, no verdict anywhere in "
        "this file."
    ),

    # --- Delegates portfolio simulation to qlib's own backtest engine
    # (TopkDropoutStrategy / executor / recorder), not hand-rolled pandas
    # pct_change/shift arithmetic. Verified: no pct_change/.shift() weight*
    # return multiplication anywhere in these files. -----------------------
    "qlib_run.py": (
        "gate_metrics() reads qlib's own TopkDropoutStrategy/executor report; "
        "does not independently multiply a weight by pct_change() itself."
    ),
    "qlib_run_wide.py": (
        "Same qlib-engine delegation as qlib_run.py (imports TopkDropoutStrategy "
        "from qlib.contrib.strategy). This is gate path #2 for P1-1 "
        "(gate_metrics at line 137); its reporting is retrofitted onto "
        "research/reporting.py separately -- that is a different concern "
        "(rendering a doc from an artifact) than this primitive (earning a "
        "weight against a price)."
    ),
    "qlib_deep_wide.py": (
        "Same qlib-engine delegation -- imports gate_metrics from qlib_run_wide.py "
        "rather than computing its own portfolio return."
    ),
    "qlib_null.py": (
        "Same qlib-engine delegation; a null/permutation harness wrapped "
        "around qlib's own backtester, not an independent accounting path."
    ),
    "qlib_sweep.py": (
        "Post-processes qlib's own backtest report (its own `report['return']`/"
        "`report['cost']` columns) for the GATE_XS2 grid sweep -- aggregates "
        "and annualizes an already-produced return series rather than "
        "multiplying a formed weight by a raw close-to-close return itself."
    ),

    # --- Owned by another agent this session; explicitly out of scope. ------
    "xs_v3_live_signals.py": (
        "Out of scope for this change (owned by another agent this session; "
        "do not touch). Its sqrt(252) call (--evaluate mode) computes "
        "realized statistics on already-logged live/paper-trade outcomes, "
        "not a backtest -- the lookahead this primitive guards against "
        "cannot occur on data describing what has already happened."
    ),

    # --- KNOWN GAPS. These DO emit a GO/NO-GO verdict from hand-rolled
    # pct_change/shift return alignment and are NOT routed through
    # simulate_long_short. They were in scope for P1-5's migration list,
    # audited, and deliberately left unmigrated -- either because the
    # primitive's weight-panel API cannot represent their accounting without
    # a materially larger rewrite than this pass budgeted for, or (one case)
    # because a live bug was found that is out of this task's assigned file
    # list. Do not read their presence here as "safe, same as the diagnostics
    # above" -- read it as "tracked, and someone still needs to close this".
    # See the P1-5 completion report for full per-file reasoning and the
    # before/after numbers already captured for each. -----------------------
    "backtest_vol_timing.py": (
        "KNOWN GAP, not a design exemption. Single-instrument (SPY/QQQ) "
        "Black-Scholes option strategy: one position at a time, cash-based "
        "sizing, path-dependent option-premium decay. simulate_long_short's "
        "API (a cross-sectional weight panel earning a linear close-to-close "
        "return) cannot represent option convexity without discarding it. "
        "No lookahead bug found in its current lag handling -- this is an "
        "architecture mismatch, not a correctness gap."
    ),
    "run_xs_alpha_v3.py": (
        "KNOWN GAP, not a design exemption. A deliberately-engineered "
        "overlapping-tranche portfolio (HOLD_DAYS overlapping tranches "
        "averaged by trailing active-tranche count, TWO explicitly "
        "dual-reported cost conventions net_capital/net_gross2, open-to-open "
        "marking) -- a materially different, already execution-lag-correct "
        "accounting model, not the bug pattern this primitive targets. A "
        "faithful migration is possible (build the tranche weight frame "
        "here, delegate earn/cost/risk accounting to simulate_long_short -- "
        "proven out in this same change for xs_baseline.py, whose gross "
        "returns matched the pre-migration figures almost exactly) but was "
        "judged too large to rewrite blind in this pass: zero existing test "
        "coverage of this file's internals, and a `--smoke` run of this very "
        "file during this task's audit overwrote the production "
        "edge/runs/xs_v3/predictions.parquet artifact (recovered via a full "
        "re-run), which raised the bar for caution rather than lowering it."
    ),
    "run_xs_alpha_v3_turnover_grid.py": (
        "KNOWN GAP -- duplicates run_xs_alpha_v3.py's tranche engine "
        "('Shared helpers, duplicated from run_xs_alpha_v3.py, unchanged' "
        "per its own docstring). Same reasoning as that file."
    ),
    "run_xs_alpha_v3_holdout_final.py": (
        "KNOWN GAP -- duplicates run_xs_alpha_v3_turnover_grid.py's tranche "
        "engine ('Identical logic' per its own docstring), and evaluates the "
        "sealed 2024-08-01+ terminal holdout (MEMORY: xs_v3 holdout is "
        "burned -- dev-period winner inverted out of sample). Left "
        "unmigrated deliberately rather than risk a rewrite bug touching a "
        "non-repeatable, already-spent evaluation."
    ),
    "run_walkforward_backtest.py": (
        "KNOWN GAP, not a design exemption. Event-cohort accounting: each "
        "trade's full multi-day net_return is computed once and attributed "
        "to its entry date (compute_portfolio_daily_series groups by entry "
        "date and averages), not a continuous daily weight-times-price "
        "mark-to-market -- a different shape than simulate_long_short's API "
        "expects without reconstructing a full daily weight panel from the "
        "event table first."
    ),
    "gcp_experiment_pead_v2.py": (
        "KNOWN GAP -- and unlike the entries above, this one IS a live bug, "
        "not just an architecture mismatch: `port_ret = (long_w * daily_ret)"
        ".sum(axis=1) - (short_w * daily_ret).sum(axis=1)` with `daily_ret = "
        "close_prices.pct_change(1)` and NO shift anywhere -- the exact "
        "lag-0, weight-earns-its-own-formation-bar's-return pattern that "
        "produced the retracted +502.98% (LOOKAHEAD_CORRECTION.md). Found "
        "during the P1-5 audit of edge/tools/ for 'any others that emit a "
        "gate verdict'. Out of this task's assigned file list -- a GCP "
        "Vertex remote-execution duplicate of build_pead_catalyst_model.py's "
        "PRE-FIX logic, not wired into any checked-in GATE_*_RESULT.md per "
        "STATUS.md -- so not fixed here, but flagged prominently rather than "
        "silently left for whoever runs it next."
    ),
}


def _tool_files() -> list[Path]:
    return sorted(p for p in TOOLS_DIR.glob("*.py") if p.name != "__init__.py")


def _violation(path_name: str, src: str) -> str | None:
    """Return a failure message if `src` needs to route through the shared
    primitive and does not, else None. Pure function so the guard logic
    itself can be unit-tested against synthetic input, not just trusted."""
    if not _ANNUALIZE_RE.search(src):
        return None  # doesn't annualize a return series at all
    if _PRIMITIVE_MARKER in src:
        return None  # routes through the primitive
    if path_name in ALLOWLIST and ALLOWLIST[path_name].strip():
        return None  # reviewed, commented exception
    return (
        f"{path_name} annualizes a return series via sqrt(252)/TRADING_DAYS "
        f"(a Sharpe-shaped statistic) but does not import simulate_long_short "
        f"and is not a commented entry in this test's ALLOWLIST. Either route "
        f"its portfolio-return computation through "
        f"edge.research.portfolio.simulate_long_short, or add a specific, "
        f"reasoned entry to ALLOWLIST."
    )


@pytest.mark.parametrize("path", _tool_files(), ids=lambda p: p.name)
def test_hand_rolled_sharpe_annualization_routes_through_primitive(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    msg = _violation(path.name, src)
    assert msg is None, msg


def test_allowlist_has_no_stale_entries() -> None:
    """The allowlist must name files that still exist, so it cannot silently
    drift from the codebase (e.g. a file gets deleted or renamed and the
    exemption keeps "covering" nothing, hiding that fact)."""
    existing = {p.name for p in _tool_files()}
    stale = sorted(set(ALLOWLIST) - existing)
    assert not stale, f"ALLOWLIST references files that no longer exist under edge/tools/: {stale}"


def test_migrated_tools_import_the_primitive() -> None:
    """Positive control for P1-5: the tools this change migrated must show up
    actually using the primitive, not merely be absent from ALLOWLIST."""
    migrated = [
        "build_factor_model.py",
        "build_finra_factor_model.py",
        "factor_probe.py",
        "xs_baseline.py",
        "build_pead_catalyst_model.py",
        "build_pead_factor_hybrid.py",
    ]
    missing = [
        name for name in migrated
        if _PRIMITIVE_MARKER not in (TOOLS_DIR / name).read_text(encoding="utf-8")
    ]
    assert not missing, f"expected these migrated tools to import simulate_long_short: {missing}"


def test_guard_actually_fails_on_a_hand_rolled_sharpe() -> None:
    """Proves the guard mechanism itself works, using a synthetic file it has
    never seen -- not just that the current repo happens to pass it. This is
    the literal case from LOOKAHEAD_CORRECTION.md: a weight multiplied
    straight against pct_change(1) with no shift, then annualized."""
    hand_rolled_src = """
import numpy as np
daily_ret = close_prices.pct_change(1).fillna(0.0)
port_ret = (long_w * daily_ret).sum(axis=1) - (short_w * daily_ret).sum(axis=1)
sharpe = float(port_ret.mean() / port_ret.std() * np.sqrt(252))
verdict = "GO" if sharpe > 0.6 else "NO-GO"
"""
    msg = _violation("not_a_real_file_never_allowlisted.py", hand_rolled_src)
    assert msg is not None, "guard failed to flag an unallowlisted hand-rolled Sharpe -- the test is not testing anything"
    assert "simulate_long_short" in msg


def test_guard_passes_when_primitive_is_imported() -> None:
    routed_src = """
from edge.research.portfolio import simulate_long_short
sim = simulate_long_short(long_weights=long_w, short_weights=short_w, close=close, execution_lag=1)
sharpe = sim.sharpe
"""
    assert _violation("not_a_real_file_never_allowlisted.py", routed_src) is None


def test_guard_passes_for_a_reasoned_allowlist_entry() -> None:
    hand_rolled_src = """
sharpe = float(x.mean() / x.std() * np.sqrt(252))
"""
    # Any real ALLOWLIST key exercises the same code path; reuse one rather
    # than fabricate a parallel list that could drift from the real one.
    real_key = next(iter(ALLOWLIST))
    assert _violation(real_key, hand_rolled_src) is None


def test_guard_does_not_flag_files_with_no_annualization() -> None:
    assert _violation("whatever.py", "x = 1 + 1\n") is None
