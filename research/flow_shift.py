"""Causal flow-shift detection and honest post-shift confidence.

Pure functions, no I/O. A value computed as of step ``t`` uses observations
``<= t`` only. Incremental ``update_flow_shift`` is the source of truth;
batch helpers just replay it, so prefix-consistency is structural.

Why this exists
---------------
The live squeeze term previously used the *full-window* signed imbalance.
A mid-sample reversal then left the pre-shift cumulative sign locked in,
so the desk kept a high-confidence old direction after the tape had flipped.
This module:

1. Detects a direction change or persistence break at the first confirming
   observation (real-time on each arriving print/bar).
2. Rebuilds the signed imbalance from the *post-shift* window only.
3. Refuses a high-confidence band on thin, stale, or just-shifted samples.

The squeeze score itself stays ``compute_theory_squeeze``; callers pass
``CurrentFlowReadout.effective_imbalance`` as ``call_imbalance``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
from typing import Mapping, Sequence

HIGH_MIN_N = 8
HIGH_MIN_POST = 4


def _finite(value: float) -> bool:
    return value is not None and math.isfinite(float(value))


def observation_sign(value: float, *, noise_abs: float = 0.0) -> int:
    """Sign of a signed-flow observation; |x| <= noise is treated as 0."""
    if not _finite(value):
        return 0
    x = float(value)
    floor = max(0.0, float(noise_abs))
    if abs(x) <= floor:
        return 0
    return 1 if x > 0.0 else -1


@dataclass(frozen=True)
class FlowShiftConfig:
    """Detector + confidence knobs. Fit any of these on train folds only."""

    min_regime: int = 3
    confirm: int = 1
    noise_abs: float = 0.0
    persist_window: int = 5
    persist_min: int = 2
    high_min_n: int = HIGH_MIN_N
    high_min_post: int = HIGH_MIN_POST

    def __post_init__(self) -> None:
        if self.min_regime < 1 or self.confirm < 1:
            raise ValueError("min_regime and confirm must be positive")
        if self.noise_abs < 0:
            raise ValueError("noise_abs must be non-negative")
        if self.persist_window < 1 or self.persist_min < 1:
            raise ValueError("persist_window and persist_min must be positive")
        if self.persist_min > self.persist_window:
            raise ValueError("persist_min cannot exceed persist_window")
        if self.high_min_n < 1 or self.high_min_post < 1:
            raise ValueError("confidence floors must be positive")

    @property
    def recent_cap(self) -> int:
        return max(self.persist_window, self.confirm, self.min_regime)


@dataclass(frozen=True)
class FlowShiftState:
    """Compact incremental state. Enough to match a batch replay to t."""

    n: int = 0
    regime_sign: int = 0
    regime_len: int = 0
    opposite_run: int = 0
    last_shift_index: int | None = None
    last_shift_kind: str | None = None
    shifted: bool = False
    post_sum: float = 0.0
    post_abs: float = 0.0
    post_n: int = 0
    recent: tuple[float, ...] = ()

    @property
    def post_imbalance(self) -> float:
        if self.post_abs <= 0.0:
            return 0.0
        return float(self.post_sum / self.post_abs)


@dataclass(frozen=True)
class FlowShiftSnapshot:
    """Detector readout at a single causal index."""

    index: int
    value: float
    sign: int
    shifted: bool
    shift_kind: str | None
    last_shift_index: int | None
    regime_sign: int
    regime_len: int
    post_sum: float
    post_abs: float
    post_n: int
    post_imbalance: float


@dataclass(frozen=True)
class CurrentFlowReadout:
    """Post-shift flow + honest confidence for the squeeze directional term."""

    signed_imbalance: float
    effective_imbalance: float
    n: int
    n_post_shift: int
    last_shift_index: int | None
    last_shift_kind: str | None
    shifted: bool
    regime_sign: int
    confidence: float
    confidence_band: str
    confidence_reasons: tuple[str, ...]
    stale: bool
    thin: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["confidence_reasons"] = list(self.confidence_reasons)
        return payload


def empty_flow_shift_state() -> FlowShiftState:
    return FlowShiftState()


def _snapshot(state: FlowShiftState, value: float, sign: int) -> FlowShiftSnapshot:
    return FlowShiftSnapshot(
        index=state.n - 1,
        value=float(value),
        sign=int(sign),
        shifted=bool(state.shifted),
        shift_kind=state.last_shift_kind,
        last_shift_index=state.last_shift_index,
        regime_sign=int(state.regime_sign),
        regime_len=int(state.regime_len),
        post_sum=float(state.post_sum),
        post_abs=float(state.post_abs),
        post_n=int(state.post_n),
        post_imbalance=float(state.post_imbalance),
    )


def _accumulate_post(state: FlowShiftState, value: float) -> FlowShiftState:
    if not _finite(value):
        return state
    x = float(value)
    return replace(
        state,
        post_sum=state.post_sum + x,
        post_abs=state.post_abs + abs(x),
        post_n=state.post_n + 1,
    )


def _reset_post(values: Sequence[float]) -> tuple[float, float, int]:
    total = 0.0
    abs_total = 0.0
    n = 0
    for raw in values:
        if not _finite(raw):
            continue
        x = float(raw)
        total += x
        abs_total += abs(x)
        n += 1
    return total, abs_total, n


def _persistence_broken(state: FlowShiftState, cfg: FlowShiftConfig) -> bool:
    if state.regime_sign == 0 or state.regime_len < cfg.persist_window:
        return False
    if len(state.recent) < cfg.persist_window:
        return False
    window = state.recent[-cfg.persist_window:]
    same = sum(
        1
        for item in window
        if observation_sign(item, noise_abs=cfg.noise_abs) == state.regime_sign
    )
    return same < cfg.persist_min


def update_flow_shift(
    state: FlowShiftState | None,
    value: float,
    *,
    cfg: FlowShiftConfig | None = None,
) -> FlowShiftState:
    """Fold one new signed-flow observation into the detector state.

    Uses only the prior state plus ``value``. A prefix that has not yet
    seen the change cannot report it, because the change is not in ``value``.
    """
    cfg = cfg or FlowShiftConfig()
    prior = state or empty_flow_shift_state()
    x = float(value) if _finite(value) else 0.0
    sign = observation_sign(x, noise_abs=cfg.noise_abs)
    recent = (prior.recent + (x,))[-cfg.recent_cap:]
    nxt = replace(
        prior,
        n=prior.n + 1,
        shifted=False,
        recent=recent,
    )

    if nxt.regime_sign == 0:
        if sign == 0:
            return _accumulate_post(nxt, x)
        establishing = 0
        run = 0
        for item in reversed(recent):
            item_sign = observation_sign(item, noise_abs=cfg.noise_abs)
            if item_sign == 0:
                continue
            if establishing == 0:
                establishing = item_sign
                run = 1
                continue
            if item_sign == establishing:
                run += 1
                continue
            break
        if establishing != 0 and run >= cfg.min_regime:
            nxt = replace(nxt, regime_sign=establishing, regime_len=run, opposite_run=0)
        else:
            nxt = replace(nxt, regime_sign=0, regime_len=run, opposite_run=0)
        return _accumulate_post(nxt, x)

    if sign == nxt.regime_sign:
        nxt = replace(
            nxt,
            regime_len=nxt.regime_len + 1,
            opposite_run=0,
        )
        return _accumulate_post(nxt, x)

    if sign == -nxt.regime_sign:
        opposite_run = nxt.opposite_run + 1
        if opposite_run >= cfg.confirm:
            opposite_values = [item for item in recent if observation_sign(item, noise_abs=cfg.noise_abs) == sign]
            opposite_values = opposite_values[-opposite_run:]
            post_sum, post_abs, post_n = _reset_post(opposite_values)
            return replace(
                nxt,
                regime_sign=sign,
                regime_len=opposite_run,
                opposite_run=0,
                last_shift_index=nxt.n - 1,
                last_shift_kind="direction",
                shifted=True,
                post_sum=post_sum,
                post_abs=post_abs,
                post_n=post_n,
            )
        return replace(nxt, opposite_run=opposite_run)

    # Zero / noise: keep the regime, still count toward post-shift stats,
    # then maybe declare a persistence break once the trailing window no
    # longer supports the locked sign.
    nxt = _accumulate_post(replace(nxt, opposite_run=0), x)
    if _persistence_broken(nxt, cfg):
        # The tape has gone quiet: drop pre-break mass so the old sign
        # cannot stay locked at ±1. Current (breaking) observations only.
        post_sum, post_abs, post_n = _reset_post([x])
        return replace(
            nxt,
            regime_sign=0,
            regime_len=0,
            opposite_run=0,
            last_shift_index=nxt.n - 1,
            last_shift_kind="persistence",
            shifted=True,
            post_sum=post_sum,
            post_abs=post_abs,
            post_n=post_n,
        )
    return nxt


def detect_flow_shift_series(
    values: Sequence[float],
    *,
    cfg: FlowShiftConfig | None = None,
) -> list[FlowShiftSnapshot]:
    """Causal snapshots for ``values[0], …, values[t]`` at every t."""
    cfg = cfg or FlowShiftConfig()
    state = empty_flow_shift_state()
    out: list[FlowShiftSnapshot] = []
    for raw in values:
        x = float(raw) if _finite(float(raw) if raw is not None else float("nan")) else float("nan")
        state = update_flow_shift(state, x, cfg=cfg)
        sign = observation_sign(x, noise_abs=cfg.noise_abs) if _finite(x) else 0
        out.append(_snapshot(state, x if _finite(x) else 0.0, sign))
    return out


def detect_flow_shift_at(
    values: Sequence[float],
    *,
    end: int | None = None,
    cfg: FlowShiftConfig | None = None,
) -> FlowShiftSnapshot | None:
    """Snapshot using only ``values[:end]`` (``end`` is exclusive)."""
    prefix = list(values) if end is None else list(values[:end])
    series = detect_flow_shift_series(prefix, cfg=cfg)
    return series[-1] if series else None


def score_flow_confidence(
    *,
    n: int,
    n_post_shift: int,
    shifted_now: bool,
    last_shift_index: int | None,
    last_age: float | None = None,
    max_fresh_age: float | None = None,
    cfg: FlowShiftConfig | None = None,
) -> tuple[float, str, tuple[str, ...], bool, bool]:
    """Honest confidence. Thin / stale / pre-shift samples cannot be high.

    Returns ``(confidence, band, reasons, stale, thin)``.
    Size ramp matches the live tape convention (full confidence at ``high_min_n``).
    """
    cfg = cfg or FlowShiftConfig()
    post_n = max(0, int(n_post_shift))
    size_c = min(1.0, post_n / float(cfg.high_min_n))
    stale = (
        last_age is not None
        and max_fresh_age is not None
        and _finite(last_age)
        and _finite(max_fresh_age)
        and float(last_age) > float(max_fresh_age)
    )
    warming = last_shift_index is not None and (shifted_now or post_n < cfg.high_min_post)
    recency_c = 0.0 if stale else 1.0
    if shifted_now:
        warmup_c = 0.0
    elif last_shift_index is not None and post_n < cfg.high_min_post:
        warmup_c = post_n / float(cfg.high_min_post)
    else:
        warmup_c = 1.0
    confidence = max(0.0, min(1.0, size_c * recency_c * warmup_c))

    reasons: list[str] = []
    thin = post_n < cfg.high_min_n
    if thin:
        reasons.append("thin_sample")
    if stale:
        reasons.append("stale")
    if warming:
        reasons.append("pre_shift_or_warmup")

    if reasons:
        # Hard rule: any of the three defects blocks the high band.
        if stale or (thin and (warming or post_n < 2)):
            band = "low"
        else:
            band = "medium"
    elif confidence >= 0.8:
        band = "high"
    else:
        band = "medium"
    return confidence, band, tuple(reasons), bool(stale), bool(thin)


def current_flow_after_shift(
    values: Sequence[float],
    *,
    cfg: FlowShiftConfig | None = None,
    last_age: float | None = None,
    max_fresh_age: float | None = None,
) -> CurrentFlowReadout:
    """Post-shift signed imbalance and confidence for the latest observation."""
    cfg = cfg or FlowShiftConfig()
    series = detect_flow_shift_series(values, cfg=cfg)
    if not series:
        confidence, band, reasons, stale, thin = score_flow_confidence(
            n=0,
            n_post_shift=0,
            shifted_now=False,
            last_shift_index=None,
            last_age=last_age,
            max_fresh_age=max_fresh_age,
            cfg=cfg,
        )
        return CurrentFlowReadout(
            signed_imbalance=0.0,
            effective_imbalance=0.0,
            n=0,
            n_post_shift=0,
            last_shift_index=None,
            last_shift_kind=None,
            shifted=False,
            regime_sign=0,
            confidence=confidence,
            confidence_band=band,
            confidence_reasons=reasons,
            stale=stale,
            thin=thin,
        )
    last = series[-1]
    confidence, band, reasons, stale, thin = score_flow_confidence(
        n=len(series),
        n_post_shift=last.post_n,
        shifted_now=last.shifted,
        last_shift_index=last.last_shift_index,
        last_age=last_age,
        max_fresh_age=max_fresh_age,
        cfg=cfg,
    )
    signed = float(last.post_imbalance)
    return CurrentFlowReadout(
        signed_imbalance=signed,
        effective_imbalance=float(signed * confidence),
        n=len(series),
        n_post_shift=int(last.post_n),
        last_shift_index=last.last_shift_index,
        last_shift_kind=last.shift_kind,
        shifted=bool(last.shifted),
        regime_sign=int(last.regime_sign),
        confidence=float(confidence),
        confidence_band=band,
        confidence_reasons=reasons,
        stale=stale,
        thin=thin,
    )


def signed_observations_from_bars(bars: object) -> list[float]:
    """Causal signed-volume proxy observations from an OHLCV frame.

    Delegates to ``research.flow_state.signed_volume_proxy`` so the bar path
    shares the same CLV × volume definition as the flow-state engine.
    """
    from .flow_state import signed_volume_proxy

    series = signed_volume_proxy(bars)
    return [float(x) for x in series.to_numpy(dtype=float) if _finite(float(x))]


def squeeze_with_shifted_flow(
    *,
    chain_rows: Sequence[Mapping[str, object]],
    spot: float,
    adv_notional: float,
    momentum: float,
    signed_flow: Sequence[float],
    last_age: float | None = None,
    max_fresh_age: float | None = None,
    cfg: FlowShiftConfig | None = None,
    **theory_kwargs: object,
) -> dict[str, object]:
    """Shipped theory squeeze scored on *current* post-shift flow.

    Does not invent a second score: direction is ``compute_theory_squeeze``
    with ``call_imbalance=effective_imbalance``.
    """
    from edge.daily_plays.gex_core import compute_theory_squeeze

    readout = current_flow_after_shift(
        signed_flow,
        cfg=cfg,
        last_age=last_age,
        max_fresh_age=max_fresh_age,
    )
    theory = compute_theory_squeeze(
        chain_rows=chain_rows,
        spot=spot,
        adv_notional=adv_notional,
        call_imbalance=readout.effective_imbalance,
        momentum=momentum,
        **theory_kwargs,
    )
    payload = dict(theory)
    payload["flow_shift"] = readout.to_dict()
    return payload
