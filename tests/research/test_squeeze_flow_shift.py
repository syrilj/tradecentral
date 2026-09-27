"""Shipped squeeze readout must react to a mid-sample flow reversal."""
from __future__ import annotations

from edge.daily_plays.gex_core import compute_theory_squeeze
from edge.research.flow_shift import current_flow_after_shift, squeeze_with_shifted_flow


def _fuel_chain():
    return [
        {"right": "call", "strike": 101, "gamma": 0.08, "open_interest": 50_000, "multiplier": 100, "dte": 2},
        {"right": "put", "strike": 99, "gamma": 0.02, "open_interest": 5_000, "multiplier": 100, "dte": 2},
    ]


def _locked_pre_shift(signed_flow, *, momentum=0.04):
    """What the old full-window imbalance would have fed the squeeze."""
    total = sum(signed_flow)
    gross = sum(abs(x) for x in signed_flow)
    locked = (total / gross) if gross else 0.0
    return compute_theory_squeeze(
        chain_rows=_fuel_chain(),
        spot=100.0,
        adv_notional=50_000_000.0,
        call_imbalance=locked,
        momentum=momentum,
    )


def test_mid_window_reversal_changes_squeeze_vs_locked_pre_shift_readout():
    momentum = 0.04
    no_shift = [1.0] * 12
    reversed_flow = [1.0] * 8 + [-1.0] * 8

    stable = squeeze_with_shifted_flow(
        chain_rows=_fuel_chain(),
        spot=100.0,
        adv_notional=50_000_000.0,
        momentum=momentum,
        signed_flow=no_shift,
        last_age=0.0,
        max_fresh_age=2.0,
    )
    flipped = squeeze_with_shifted_flow(
        chain_rows=_fuel_chain(),
        spot=100.0,
        adv_notional=50_000_000.0,
        momentum=momentum,
        signed_flow=reversed_flow,
        last_age=0.0,
        max_fresh_age=2.0,
    )
    locked = _locked_pre_shift(reversed_flow, momentum=momentum)

    assert stable["squeeze_score"] != flipped["squeeze_score"]
    assert flipped["squeeze_score"] < stable["squeeze_score"]
    # Locked full-window net on 8 up / 8 down is ~0; the shipped path must
    # not keep that pre-shift (or cancelled) score after the reversal.
    assert flipped["squeeze_score"] != locked["squeeze_score"]
    assert flipped["call_imbalance"] < 0
    assert flipped["flow_shift"]["last_shift_index"] == 8


def test_thin_or_pre_shift_squeeze_cannot_report_high_confidence():
    thin = squeeze_with_shifted_flow(
        chain_rows=_fuel_chain(),
        spot=100.0,
        adv_notional=50_000_000.0,
        momentum=0.04,
        signed_flow=[1.0, 1.0],
    )
    assert thin["flow_shift"]["confidence_band"] != "high"
    assert thin["flow_shift"]["thin"] is True

    just_shifted = squeeze_with_shifted_flow(
        chain_rows=_fuel_chain(),
        spot=100.0,
        adv_notional=50_000_000.0,
        momentum=0.04,
        signed_flow=[1.0] * 8 + [-1.0],
    )
    assert just_shifted["flow_shift"]["shifted"] is True
    assert just_shifted["flow_shift"]["confidence_band"] != "high"

    stale = squeeze_with_shifted_flow(
        chain_rows=_fuel_chain(),
        spot=100.0,
        adv_notional=50_000_000.0,
        momentum=0.04,
        signed_flow=[1.0] * 12,
        last_age=10.0,
        max_fresh_age=2.0,
    )
    assert stale["flow_shift"]["stale"] is True
    assert stale["flow_shift"]["confidence_band"] != "high"
    assert stale["call_imbalance"] == 0.0


def test_squeeze_with_shifted_flow_is_compute_theory_squeeze_on_post_shift():
    values = [1.0] * 8 + [-1.0] * 8
    readout = current_flow_after_shift(values)
    composed = squeeze_with_shifted_flow(
        chain_rows=_fuel_chain(),
        spot=100.0,
        adv_notional=50_000_000.0,
        momentum=0.04,
        signed_flow=values,
    )
    direct = compute_theory_squeeze(
        chain_rows=_fuel_chain(),
        spot=100.0,
        adv_notional=50_000_000.0,
        call_imbalance=readout.effective_imbalance,
        momentum=0.04,
    )
    assert composed["squeeze_score"] == direct["squeeze_score"]
    assert composed["squeeze_label"] == direct["squeeze_label"]
    assert composed["call_imbalance"] == readout.effective_imbalance
