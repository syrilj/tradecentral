"""Causal, session-aware feature engine for intraday bars.

Pure functions, no I/O, no network -- callers that read parquet live in
``tools/`` or in ``research/*_panel.py``, matching the separation
``research/flow_state.py`` and ``research/microstructure.py`` already use.

Why this module exists
----------------------
The 2026-09-01 audit (``docs/audits/2026-09-01-vwap-orderflow-evaluation.md``)
established two things about the bars this repo actually holds:

* Session-VWAP distance, crosses and time-on-side carry **no** measurable
  directional information at 1h resolution -- 512k observations, 119 symbols,
  session-clustered intervals all straddling zero.
* Time-of-day-normalised relative volume **does** forecast the *size* of the
  remaining session move, monotonically: ~44bp of absolute move at normal slot
  volume rising to ~96bp above 3x slot volume, with no directional content.

So these features are built to describe state and to forecast magnitude. None
of them is presented as a directional signal, and this module deliberately
exposes no "buy/sell" opinion.

The leakage contract
--------------------
Every column at row ``t`` is a function of bars ``<= t`` only, and every
*baseline* a bar is judged against excludes the bar itself. Both halves matter:
including the current bar in its own 20-period average is what makes a genuine
volume climax look merely "above average", and is a mild form of self-reference
even when it is not outright lookahead.

``assert_causal`` is the executable form of that contract and is used by the
tests: it perturbs the tail of a frame and asserts nothing at or before the
perturbation moved.

Time-of-day normalisation
-------------------------
US equity volume and range are strongly U-shaped across the session, so a
trailing all-bar baseline systematically flags the open as "high volume" and
midday as "low volume" no matter what the market is doing. Baselines here are
therefore taken over the **same slot** (bar-of-session) across prior sessions,
with a trailing all-bar fallback while slot history is still short.

Slot identity is the bar's *ordinal position within its session*, not its clock
hour: a half-length final bar, a late open or a short holiday session all keep
their ordinal, whereas an hour-of-day key silently mixes them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

__all__ = [
    "SessionFeatureConfig",
    "session_id",
    "slot_index",
    "session_vwap",
    "slot_baseline",
    "build_features",
    "assert_causal",
    "FEATURE_COLUMNS",
]

OHLCV = ("open", "high", "low", "close", "volume")

#: Descriptive state features. Deliberately excludes every forward-looking
#: column so a caller can select the model matrix without hand-listing names.
FEATURE_COLUMNS = (
    "vwap_z",
    "vwap_dist_bp",
    "above_vwap",
    "bars_on_side",
    "cross_up",
    "cross_dn",
    "vwap_slope_bp",
    "rvol_slot",
    "log_rvol_slot",
    "cum_rvol_session",
    "range_ratio",
    "realized_vol",
    "trend_20s",
    "clv",
    "signed_flow_proxy",
    "cum_signed_flow_proxy",
)


@dataclass(frozen=True)
class SessionFeatureConfig:
    """Windows and guards. One place to retune, per repo convention."""

    #: Prior sessions in a slot baseline.
    baseline_sessions: int = 20
    #: Minimum same-slot samples before the slot baseline is trusted.
    min_slot_samples: int = 10
    #: Trailing bars for the all-bar fallback baseline.
    fallback_bars: int = 20
    #: Minimum observations for the fallback baseline.
    min_fallback_samples: int = 5
    #: Sessions of realised volatility / trend context.
    context_sessions: int = 20
    #: Bars over which the VWAP slope is measured.
    slope_bars: int = 3
    #: Sessions with a bar count outside the modal count are dropped as
    #: irregular (half days, feed gaps) rather than silently reshaping slots.
    drop_irregular_sessions: bool = True

    def __post_init__(self) -> None:
        if self.baseline_sessions < 2:
            raise ValueError("baseline_sessions must be >= 2")
        if self.min_slot_samples < 1:
            raise ValueError("min_slot_samples must be >= 1")
        if self.fallback_bars < 2:
            raise ValueError("fallback_bars must be >= 2")
        if self.slope_bars < 1:
            raise ValueError("slope_bars must be >= 1")
        if self.context_sessions < 1:
            raise ValueError("context_sessions must be >= 1")


def _validate(bars: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(bars, pd.DataFrame):
        raise TypeError("bars must be a DataFrame")
    missing = [c for c in OHLCV if c not in bars.columns]
    if missing:
        raise ValueError(f"bars is missing required columns: {missing}")
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise TypeError("bars must have a DatetimeIndex")
    if not bars.index.is_monotonic_increasing:
        raise ValueError("bars index must be ascending; rolling() walks positional order")
    if bars.index.has_duplicates:
        raise ValueError("bars index must be unique")
    return bars


def session_id(index: pd.DatetimeIndex) -> pd.Series:
    """Calendar-date session key.

    US cash sessions do not straddle midnight, so the normalised date is the
    session. A futures-style overnight session would need a different key and
    this function is the single place that would change.
    """
    return pd.Series(index.normalize(), index=index, name="session")


def slot_index(index: pd.DatetimeIndex) -> pd.Series:
    """Ordinal position of each bar within its session (0-based).

    Ordinal rather than clock hour: a shortened session or a late first print
    keeps its ordinal, where an hour key would silently pool a half-length
    close with a full midday bar.
    """
    sess = session_id(index)
    return sess.groupby(sess).cumcount().rename("slot")


def session_vwap(bars: pd.DataFrame) -> pd.DataFrame:
    """Per-session VWAP with running weighted sd, reset at each session.

    Uses typical price (H+L+C)/3 -- the standard within-bar proxy for where
    volume actually traded -- and West's incremental weighted variance rather
    than ``E[x^2] - E[x]^2``, which loses precision to cancellation once the
    cumulative sums dwarf the variance (a real risk on high-priced names).

    Zero, negative and non-finite volume bars contribute nothing: they carry
    the previous VWAP forward instead of dragging it. Bars before any positive
    volume in their session are NaN, never a fabricated value.

    Returns columns ``vwap``, ``vwap_sd``.
    """
    _validate(bars)
    tp = ((bars["high"] + bars["low"] + bars["close"]) / 3.0).to_numpy(dtype=float)
    vol = pd.to_numeric(bars["volume"], errors="coerce").to_numpy(dtype=float)
    sess = session_id(bars.index).to_numpy()

    n = len(bars)
    vwap = np.full(n, np.nan)
    sd = np.full(n, np.nan)

    w_sum = 0.0
    mean = 0.0
    m2 = 0.0
    prev_sess = None
    for i in range(n):
        if prev_sess is None or sess[i] != prev_sess:
            w_sum, mean, m2 = 0.0, 0.0, 0.0
            prev_sess = sess[i]
        w = vol[i]
        x = tp[i]
        if np.isfinite(w) and w > 0.0 and np.isfinite(x):
            w_sum += w
            delta = x - mean
            mean += (w / w_sum) * delta
            m2 += w * delta * (x - mean)
        if w_sum > 0.0:
            vwap[i] = mean
            sd[i] = math_sqrt(max(0.0, m2 / w_sum))
    return pd.DataFrame({"vwap": vwap, "vwap_sd": sd}, index=bars.index)


def math_sqrt(x: float) -> float:
    """``sqrt`` that returns NaN rather than raising on a negative input."""
    return float(np.sqrt(x)) if x >= 0 else float("nan")


def slot_baseline(
    values: pd.Series,
    slots: pd.Series,
    cfg: SessionFeatureConfig | None = None,
) -> pd.DataFrame:
    """Trailing same-slot median of ``values``, exclusive of the current bar.

    Falls back to a trailing all-bar median while a slot has fewer than
    ``cfg.min_slot_samples`` prior observations, so early history degrades
    gracefully instead of emitting nothing.

    Returns columns ``baseline`` and ``baseline_kind`` (``slot_median`` /
    ``trailing_median`` / empty when neither is available), so a downstream
    reader can always see which baseline a ratio was judged against rather
    than having to infer it.
    """
    cfg = cfg or SessionFeatureConfig()
    v = pd.to_numeric(values, errors="coerce").astype(float)

    # shift(1) BEFORE rolling: the bar never enters the baseline it is judged
    # against. Grouped by slot, shift(1) steps back one *session* within the
    # slot, which is the intended comparison.
    per_slot = v.groupby(slots)
    slot_med = per_slot.transform(
        lambda s: s.shift(1).rolling(cfg.baseline_sessions, min_periods=cfg.min_slot_samples).median()
    )
    fallback = v.shift(1).rolling(cfg.fallback_bars, min_periods=cfg.min_fallback_samples).median()

    baseline = slot_med.where(slot_med.notna(), fallback)
    kind = pd.Series("", index=v.index, dtype="object")
    kind[fallback.notna()] = "trailing_median"
    kind[slot_med.notna()] = "slot_median"
    return pd.DataFrame({"baseline": baseline, "baseline_kind": kind})


def _drop_irregular_sessions(bars: pd.DataFrame) -> pd.DataFrame:
    sess = session_id(bars.index)
    counts = sess.value_counts()
    if counts.empty:
        return bars
    modal = int(counts.mode().iloc[0])
    keep = counts[counts == modal].index
    return bars[sess.isin(keep)]


def build_features(
    bars: pd.DataFrame,
    cfg: SessionFeatureConfig | None = None,
    *,
    symbol: str | None = None,
) -> pd.DataFrame:
    """Full causal feature frame for one symbol's intraday bars.

    Every column at row ``t`` uses bars ``<= t``; every baseline excludes bar
    ``t`` itself. Forward-looking target columns are NOT produced here -- see
    ``forward_targets`` -- so that a caller cannot accidentally hand a target
    to a model as a feature.
    """
    cfg = cfg or SessionFeatureConfig()
    _validate(bars)
    if cfg.drop_irregular_sessions:
        bars = _drop_irregular_sessions(bars)
    if bars.empty:
        return pd.DataFrame(index=bars.index)

    close = pd.to_numeric(bars["close"], errors="coerce").astype(float)
    vol = pd.to_numeric(bars["volume"], errors="coerce").astype(float)
    sess = session_id(bars.index)
    slots = slot_index(bars.index)
    bars_per_session = int(slots.max()) + 1

    out = pd.DataFrame(index=bars.index)
    if symbol is not None:
        out["symbol"] = symbol
    out["session"] = sess
    out["slot"] = slots

    # --- VWAP state -------------------------------------------------------
    vw = session_vwap(bars)
    out["vwap"] = vw["vwap"]
    out["vwap_sd"] = vw["vwap_sd"]
    # A zero sd (first bar of a session, or a session that has traded at a
    # single price) makes z undefined, not infinite.
    out["vwap_z"] = (close - vw["vwap"]) / vw["vwap_sd"].replace(0.0, np.nan)
    out["vwap_dist_bp"] = (close / vw["vwap"] - 1.0) * 1e4
    above = (close > vw["vwap"])
    out["above_vwap"] = above.astype("float").where(vw["vwap"].notna())

    # A missing prior side means "no cross": the first bar of the history has
    # nothing to have crossed from. Cast before filling so the boolean stays
    # a boolean rather than round-tripping through object dtype.
    prev_above = above.shift(1).astype("boolean").fillna(above.astype("boolean")).astype(bool)
    same_session = sess.eq(sess.shift(1))
    out["cross_up"] = (above & ~prev_above & same_session).astype(int)
    out["cross_dn"] = (~above & prev_above & same_session).astype(int)
    # Bars since the last side change, restarting each session.
    side_change = above.ne(prev_above) | ~same_session
    out["bars_on_side"] = above.groupby(side_change.cumsum()).cumcount() + 1
    out["vwap_slope_bp"] = (vw["vwap"] / vw["vwap"].shift(cfg.slope_bars) - 1.0) * 1e4
    out.loc[~sess.eq(sess.shift(cfg.slope_bars)), "vwap_slope_bp"] = np.nan

    # --- Volume state (the part with demonstrated forecasting value) ------
    vol_base = slot_baseline(vol, slots, cfg)
    out["rvol_slot"] = vol / vol_base["baseline"].replace(0.0, np.nan)
    out["log_rvol_slot"] = np.log(out["rvol_slot"].where(out["rvol_slot"] > 0))
    out["rvol_baseline_kind"] = vol_base["baseline_kind"]

    cum_vol = vol.groupby(sess).cumsum()
    cum_base = slot_baseline(cum_vol, slots, cfg)
    out["cum_rvol_session"] = cum_vol / cum_base["baseline"].replace(0.0, np.nan)

    # --- Range / volatility state ----------------------------------------
    sess_high = bars["high"].groupby(sess).cummax()
    sess_low = bars["low"].groupby(sess).cummin()
    sess_range = (sess_high - sess_low) / close
    range_base = slot_baseline(sess_range, slots, cfg)
    out["range_ratio"] = sess_range / range_base["baseline"].replace(0.0, np.nan)

    ret = close.pct_change()
    ctx = cfg.context_sessions * bars_per_session
    out["realized_vol"] = ret.rolling(ctx, min_periods=max(10, ctx // 2)).std().shift(1)
    out["trend_20s"] = (close / close.shift(ctx) - 1.0).shift(1)

    # --- Bar-geometry flow PROXY -----------------------------------------
    # ((2C-H-L)/(H-L)) * V. This is a transform of the bar's own return, NOT
    # measured order flow: there are no trades, quotes or aggressor side in
    # this repo. Named `_proxy` so it cannot be mistaken for a delta, and any
    # "divergence" against price is partly price diverging from a function of
    # price. Kept because it is a legitimate cheap state descriptor.
    rng = (bars["high"] - bars["low"]).astype(float)
    clv = pd.Series(0.0, index=bars.index)
    ok = rng > 0
    clv.loc[ok] = ((2.0 * close - bars["high"] - bars["low"]) / rng).loc[ok]
    out["clv"] = clv
    out["signed_flow_proxy"] = clv * vol
    out["cum_signed_flow_proxy"] = out["signed_flow_proxy"].groupby(sess).cumsum()

    return out


def forward_targets(
    bars: pd.DataFrame,
    cfg: SessionFeatureConfig | None = None,
) -> pd.DataFrame:
    """Forward-looking targets. Kept OUT of ``build_features`` on purpose.

    ``ret_next_bp`` is the next bar's close-to-close return within the same
    session; ``ret_eod_bp`` is from this close to the session's last close, and
    is NaN on the final bar (there is no remaining session to measure).
    ``abs_eod_bp`` is the magnitude target the audit found forecastable.
    """
    cfg = cfg or SessionFeatureConfig()
    _validate(bars)
    if cfg.drop_irregular_sessions:
        bars = _drop_irregular_sessions(bars)
    if bars.empty:
        return pd.DataFrame(index=bars.index)

    close = pd.to_numeric(bars["close"], errors="coerce").astype(float)
    sess = session_id(bars.index)
    out = pd.DataFrame(index=bars.index)

    nxt = close.shift(-1)
    out["ret_next_bp"] = ((nxt / close - 1.0) * 1e4).where(sess.eq(sess.shift(-1)))
    last = close.groupby(sess).transform("last")
    is_last = ~sess.eq(sess.shift(-1))
    out["ret_eod_bp"] = ((last / close - 1.0) * 1e4).mask(is_last)
    out["abs_eod_bp"] = out["ret_eod_bp"].abs()
    return out


def assert_causal(
    bars: pd.DataFrame,
    cfg: SessionFeatureConfig | None = None,
    *,
    cut: float = 0.7,
    columns: Sequence[str] | None = None,
) -> None:
    """Executable leakage guard: perturb the tail, assert the head is unmoved.

    Recomputes ``build_features`` on a frame whose bars after ``cut`` have been
    replaced with wildly different values. Any feature at or before the cut
    that changes is reading the future. Raises ``AssertionError`` naming the
    offending columns.
    """
    cfg = cfg or SessionFeatureConfig()
    _validate(bars)
    k = int(len(bars) * cut)
    if k < 2 or k >= len(bars):
        raise ValueError("cut must leave bars on both sides")

    # Anchor the cut to a TIMESTAMP, not a row position. `build_features` may
    # drop irregular sessions, so positional slicing of its output can reach
    # past the tamper point and flag a legitimate difference as a leak -- which
    # is exactly what this guard did on real data with half-day sessions.
    cut_ts = bars.index[k]

    base = build_features(bars, cfg)
    tampered = bars.copy()
    tail = tampered.index >= cut_ts
    tampered.loc[tail, ["open", "high", "low", "close"]] *= 3.7
    tampered.loc[tail, "volume"] *= 11.0
    after = build_features(tampered, cfg)

    common = base.index[base.index < cut_ts].intersection(after.index[after.index < cut_ts])
    if len(common) < 2:
        raise ValueError("cut left too few comparable rows before it")
    cols = list(columns) if columns is not None else [
        c for c in base.columns if c not in ("symbol", "session", "rvol_baseline_kind")
    ]
    offenders = []
    for c in cols:
        a = pd.to_numeric(base.loc[common, c], errors="coerce")
        b = pd.to_numeric(after.loc[common, c], errors="coerce")
        if not np.allclose(a.to_numpy(), b.to_numpy(), rtol=1e-9, atol=1e-9, equal_nan=True):
            offenders.append(c)
    assert not offenders, f"lookahead detected in columns: {offenders}"
