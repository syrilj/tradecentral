"""End-to-end checks that all THREE gate paths render through reporting.py.

Mirrors the plan's own verification steps for P1-1:
  1. Run a migrated gate tool -> artifact JSON written.
  2. Render its GATE_*_RESULT.md from that artifact.
  3. Confirm every figure in the doc traces to an artifact key.
  4. Hand-edit a figure in the artifact, re-render, confirm the doc changes.
  5. Ask the renderer for a metric absent from the artifact -> must raise.

Rather than re-running full backtests here (slow, and qlib-path tests would
otherwise force `edge/tests/research` to require the qlib venv), each gate
path is exercised against a synthetic artifact shaped exactly like a REAL one
that this task's implementation already verified by hand:
  - gate path 2 (qlib_run_wide.XS3_GATE_SPEC / gate_verdict): shaped like
    edge/runs/qlib_xs3/pitwide.json, and the NO-GO / 5-of-6-fail verdict
    below matches edge/docs/GATE_XS3_CORRECTION.md's independently-verified
    figures (mean IC +0.0052, NW t +0.47, post-cost IR +0.373, turnover
    545%) exactly.
  - gate path 3 (build_pead_catalyst_model.PEAD_CATALYST_GATE_SPEC): shaped
    like edge/runs/pead_catalyst/results.json.
  - gate path 1 (runner.DIRECTIONAL_DAILY_GATE_SPEC): shaped like one
    horizon's slice of a real
    edge/runs/research/directional_daily_v1/*/report.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from edge.research.reporting import MetricNotFoundError, render_gate_doc

ROOT = Path(__file__).resolve().parents[3]


def _write(tmp_path: Path, payload: dict, name: str = "artifact.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Gate path 2: edge/tools/qlib_run_wide.py -- the XS family, "THE RETRACTED
# ONE". Needs qlib + ruamel.yaml to import. Guarded with a plain try/except
# (not a module-level `importorskip`) so this file's other, qlib-independent
# gate-path tests (1 and 3, below) still run under a plain
# `python3 -m pytest edge/tests/research -q` with no qlib venv -- only the
# tests that actually need qlib_run_wide skip in that environment.
# ---------------------------------------------------------------------------

sys.path.insert(0, str(ROOT / "edge" / "tools"))
try:
    import qlib_run_wide as qrw  # noqa: E402
    _QLIB_AVAILABLE = True
except ImportError:
    qrw = None  # type: ignore[assignment]
    _QLIB_AVAILABLE = False

_needs_qlib = pytest.mark.skipif(
    not _QLIB_AVAILABLE, reason="qlib_run_wide.py needs the qlib venv (ruamel.yaml, qlib)",
)


def _xs3_payload(**overrides) -> dict:
    """Shaped exactly like edge/runs/qlib_xs3/pitwide.json (verified by
    reading that real, on-disk artifact during implementation)."""
    base = {
        "generated_utc": "2026-07-30T20:53:49.158150+00:00",
        "market": "pitwide",
        "experiment": "qlib_xs3_pitwide",
        "recorder_id": "112b1d6af5b048a0b214fb83472ff83f",
        "spec": "edge/qlib_xs3/workflow_alpha158_lgb_wide.yaml",
        "benchmark": "SPY",
        "strategy": {"class": "IntervalTopkDropoutStrategy", "topk": 30, "n_drop": 3, "rebalance_days": 5},
        "metrics": {
            "rank_ic": {
                "n_days": 491, "mean_ic": 0.005194868217710388, "std_ic": 0.1487167086127049,
                "icir": 0.03493130170893649, "t_stat_naive": 0.7740259407724317,
                "t_stat_newey_west": 0.4652803749513097, "pct_days_positive": 0.4908350305498982,
            },
            "portfolio": {
                "risk": {
                    "('excess_return_with_cost', 'annualized_return')": 0.0695187733432307,
                    "('excess_return_with_cost', 'information_ratio')": 0.37281390965958705,
                },
            },
            "turnover": {"annualized_one_way": 5.449829623179592},
        },
    }
    base.update(overrides)
    return base


@_needs_qlib
def test_xs3_gate_verdict_matches_independently_verified_correction() -> None:
    """Reproduces edge/docs/GATE_XS3_CORRECTION.md's own numbers exactly:
    NO-GO, 5 of 6 criteria fail."""
    payload = _xs3_payload()
    result = qrw.gate_verdict(payload)
    assert result["verdict"] == "NO-GO"
    checks = result["gate_checks"]
    assert checks["mean_ic_gte_0020"] is False
    assert checks["rank_icir_gte_020"] is False
    assert checks["nw_tstat_gt_2"] is False
    assert checks["excess_return_with_cost_gt_0"] is True  # the one that passes
    assert checks["post_cost_ir_gt_05"] is False
    assert checks["annualized_one_way_turnover_lte_400pct"] is False
    assert sum(checks.values()) == 1  # exactly 1 of 6 passes, i.e. 5 of 6 fail


@_needs_qlib
def test_xs3_render_end_to_end(tmp_path: Path) -> None:
    payload = _xs3_payload()
    payload.update(qrw.gate_verdict(payload))
    artifact_path = _write(tmp_path, payload)

    doc = render_gate_doc(artifact_path=artifact_path, spec=qrw.XS3_GATE_SPEC)
    assert "NO-GO" in doc
    assert "+0.0052" in doc  # mean Rank IC, matches the correction doc
    assert "545.0%" in doc  # turnover, matches the correction doc
    assert str(artifact_path) in doc


@_needs_qlib
def test_xs3_render_raises_when_portfolio_analysis_missing(tmp_path: Path) -> None:
    """qlib_run_wide.gate_metrics() can produce `portfolio_error` instead of
    `portfolio` (its own try/except). Computing a verdict against that
    payload must raise, not silently treat the untested criteria as failed
    or passed on absent evidence."""
    payload = _xs3_payload()
    del payload["metrics"]["portfolio"]
    payload["metrics"]["portfolio_error"] = "RuntimeError: recorder missing object"
    with pytest.raises(MetricNotFoundError):
        qrw.gate_verdict(payload)


@_needs_qlib
def test_xs3_rerender_after_edit_changes_doc(tmp_path: Path) -> None:
    payload = _xs3_payload()
    payload.update(qrw.gate_verdict(payload))
    artifact_path = _write(tmp_path, payload)
    doc_before = render_gate_doc(artifact_path=artifact_path, spec=qrw.XS3_GATE_SPEC)

    payload2 = _xs3_payload(metrics={**payload["metrics"], "rank_ic": {**payload["metrics"]["rank_ic"], "mean_ic": 0.05}})
    payload2.update(qrw.gate_verdict(payload2))
    _write(tmp_path, payload2, name="artifact.json")
    doc_after = render_gate_doc(artifact_path=artifact_path, spec=qrw.XS3_GATE_SPEC)
    assert doc_before != doc_after
    assert "GO" in doc_after and "0.0500" in doc_after


# ---------------------------------------------------------------------------
# Gate path 3: build_pead_catalyst_model.py / build_pead_factor_hybrid.py
# ---------------------------------------------------------------------------

from edge.tools.build_pead_catalyst_model import PEAD_CATALYST_GATE_SPEC  # noqa: E402
from edge.tools.build_pead_factor_hybrid import PEAD_HYBRID_GATE_SPEC  # noqa: E402


def _pead_catalyst_payload(**overrides) -> dict:
    """Shaped like edge/runs/pead_catalyst/results.json (verified by running
    build_pead_catalyst_model.py during implementation; these are that run's
    real corrected figures, matching LOOKAHEAD_CORRECTION.md's
    '-10.38%/Sharpe -0.26')."""
    base = {
        "mean_rank_ic": -0.0027,
        "rank_icir": -0.12,
        "mean_rank_ic_conditional_abs_gt_1p5": 0.0397,
        "execution_lag_bars": 1,
        "annual_turnover": 116.437,
        "gross_annual_return_pct": 1.26,
        "net_annual_return_pct": -10.38,
        "compounded_annual_return_pct": -16.80,
        "annual_volatility_pct": 39.63,
        "sharpe_ratio": -0.26,
        "max_drawdown_pct": 88.67,
        "exposure": 0.753,
        "n_extreme_bars_masked": 24,
        "sensitivity_lag2_net_annual_pct": -13.31,
        "sensitivity_lag2_sharpe": -0.37,
        "short_pressure_active": False,
        "short_pressure_status_text": "INACTIVE: FINRA data absent, contributes nothing",
        "calibrated_prob_mean": 0.5039,
        "universe_size": 557,
        "gate_checks": {
            "mean_ic_gt_04": False, "icir_gt_05": False, "net_annual_gt_8": False,
            "sharpe_gt_06": False, "max_drawdown_lt_15": False,
        },
        "verdict": "NO-GO",
    }
    base.update(overrides)
    return base


def test_pead_catalyst_render_end_to_end_matches_corrected_figures(tmp_path: Path) -> None:
    artifact_path = _write(tmp_path, _pead_catalyst_payload())
    doc = render_gate_doc(artifact_path=artifact_path, spec=PEAD_CATALYST_GATE_SPEC)
    assert "NO-GO" in doc
    assert "-10.38%" in doc
    assert "-0.26" in doc
    assert "+502.98%" in doc  # the retracted figure, cited for context, not sourced from the artifact


def test_pead_catalyst_render_raises_on_missing_metric(tmp_path: Path) -> None:
    payload = _pead_catalyst_payload()
    del payload["sharpe_ratio"]
    artifact_path = _write(tmp_path, payload)
    with pytest.raises(MetricNotFoundError, match="sharpe_ratio"):
        render_gate_doc(artifact_path=artifact_path, spec=PEAD_CATALYST_GATE_SPEC)


def test_pead_hybrid_render_end_to_end(tmp_path: Path) -> None:
    payload = _pead_catalyst_payload(
        annual_turnover=146.55, net_annual_return_pct=1.53, sharpe_ratio=0.08,
        short_pressure_status_text="INACTIVE: FINRA data absent, multiplier neutralized to 1.0",
        verdict="NO-GO",
    )
    artifact_path = _write(tmp_path, payload)
    doc = render_gate_doc(artifact_path=artifact_path, spec=PEAD_HYBRID_GATE_SPEC)
    assert "1.53%" in doc
    assert "0.08" in doc


# ---------------------------------------------------------------------------
# Gate path 1: edge/research/runner.py -- daily-directional family
# ---------------------------------------------------------------------------

from edge.research.runner import DIRECTIONAL_DAILY_GATE_SPEC  # noqa: E402


def _directional_daily_payload(**overrides) -> dict:
    """Shaped like one real
    edge/runs/research/directional_daily_v1/*/report.json (verified by
    reading that real, on-disk artifact during implementation): all 3
    horizons fail on the paired CI vs. frozen momentum while passing
    standalone expectancy, matching STATUS.md's Step 10 description
    verbatim ('no challenger established a positive paired lower bound')."""
    def _horizon(trial: str, paired: float, expectancy: float, dsr: float, ece: float) -> dict:
        passed_paired = paired > 0
        return {
            "selected_trial": trial,
            "development_gate": {
                "status": "PASS_DEVELOPMENT_ONLY" if (passed_paired and expectancy > 0 and dsr > 0 and ece <= 0.05) else "FAIL_DEVELOPMENT_ONLY",
                "passed": passed_paired and expectancy > 0 and dsr > 0 and ece <= 0.05,
                "checks": {
                    "candidate_minus_momentum_ci95_lower_positive": passed_paired,
                    "candidate_net_expectancy_ci95_lower_positive": expectancy > 0,
                    "deflated_sharpe_lower_positive": dsr > 0,
                    "calibration_ece_within_limit": ece <= 0.05,
                },
                "metrics": {
                    "candidate_minus_momentum_ci95_lower": paired,
                    "candidate_net_expectancy_ci95_lower": expectancy,
                    "deflated_sharpe_lower": dsr,
                    "expected_calibration_error": ece,
                },
            },
        }

    base = {
        "status": "DEVELOPMENT_NO_GO_HOLDOUT_REMAINS_SEALED",
        "experiment_id": "e5caa497b9347854950aac660ee1f7b97bb27c4dbd2785e5d9ef9b7f5f0b936e",
        "symbols": 60,
        "development_bar_dates": 2499,
        "code_version": "d6aa8db4544fe22b67f272c754d6e51159fb43de6e96b9c4919c1798d4669cfd",
        "data_fingerprint": "15ccc6ab52103ef827c06cf7185c891c0e87630f4853b06767aefc536aa00e92",
        "terminal_holdout_id": "991ace4da67d1da23938409bca994717ed0e7353565c8a871347591a8015306d",
        "terminal_holdout_opened": False,
        "development_gate": {
            "status": "FAIL_DEVELOPMENT_ONLY",
            "passing_horizons": [],
            "failed_horizons": [5, 10, 20],
            "required_horizons": [5, 10, 20],
            "failed_checks": ["no_horizons_passed"],
        },
        "horizons": {
            "5": _horizon("xgboost_conservative_v1_5d", -0.00017710392824649826, 0.0006141892268678653, 0.2890074091400488, 0.011908288722768267),
            "10": _horizon("momentum_10d", 0.0, 0.002170162187554862, 0.6212875817692219, 0.014154769992454855),
            "20": _horizon("volatility_scaled_momentum_20d", -0.0002714046041260532, 0.006036368918231946, 0.8225932729596873, 0.045987526495256406),
        },
    }
    base.update(overrides)
    return base


def test_directional_daily_render_end_to_end_matches_status_md_finding(tmp_path: Path) -> None:
    """STATUS.md Step 10: 'no challenger established a positive paired lower
    bound versus frozen momentum' -- this must show up as FAIL on the paired
    check for all three frozen horizons."""
    artifact_path = _write(tmp_path, _directional_daily_payload())
    doc = render_gate_doc(artifact_path=artifact_path, spec=DIRECTIONAL_DAILY_GATE_SPEC)
    assert "FAIL_DEVELOPMENT_ONLY" in doc
    assert doc.count("❌ FAIL") == 3  # exactly the 3 paired-CI checks
    assert "xgboost_conservative_v1_5d" in doc
    assert "momentum_10d" in doc
    assert "volatility_scaled_momentum_20d" in doc


def test_directional_daily_render_raises_when_a_horizon_is_missing(tmp_path: Path) -> None:
    """Partial artifact: one of the three frozen horizons is absent
    entirely. Must raise cleanly (MetricNotFoundError), not KeyError."""
    payload = _directional_daily_payload()
    del payload["horizons"]["20"]
    artifact_path = _write(tmp_path, payload)
    with pytest.raises(MetricNotFoundError, match="20"):
        render_gate_doc(artifact_path=artifact_path, spec=DIRECTIONAL_DAILY_GATE_SPEC)


def test_directional_daily_render_raises_when_a_metric_is_missing(tmp_path: Path) -> None:
    payload = _directional_daily_payload()
    del payload["horizons"]["5"]["development_gate"]["metrics"]["deflated_sharpe_lower"]
    artifact_path = _write(tmp_path, payload)
    with pytest.raises(MetricNotFoundError, match="deflated_sharpe_lower"):
        render_gate_doc(artifact_path=artifact_path, spec=DIRECTIONAL_DAILY_GATE_SPEC)
