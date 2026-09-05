"""Heavy-absorption detector: streaming, O(1)-per-observation by default, pure math.

Absorption is the market-microstructure pattern where a large run of
aggressive volume trades through resting liquidity but price barely moves --
a passive counterparty is "absorbing" the flow and defending the level. The
classic read is directional:

* **Sell absorption** (heavy selling, price holds) -> a passive buyer is
  defending support -> expected reversal **up**.
* **Buy absorption** (heavy buying, price holds) -> a passive seller is
  defending resistance -> expected reversal **down**.

This module is deliberately split into two layers:

1. ``AbsorptionDetector`` -- an incremental state machine that folds one
   observation at a time and returns a readout in O(1). It is the "speed"
   deliverable: it can consume a live tick/bar/print feed without ever
   recomputing a rolling window from scratch.

2. ``build_absorption_scan`` -- a batch helper that replays the detector over
   in-memory OHLCV frames (hourly preferred, daily fallback) and returns a
   ranked cross-section. It mirrors ``tools/momentum_scan.py``: pure, no I/O,
   callers hand it data already in memory.

There is no order-book depth, L2, or time-and-sales data anywhere in this
repo, so every "flow" figure here is a *descriptive proxy*, not a causal
identification. ``signed_flow`` is the caller's signed-volume proxy (CLV x
volume for bars, aggressor-signed premium for options prints); ``volume`` is
total activity. The detector never invents a direction from call/put
identity alone -- an unsigned observation contributes volume but zero signed
flow, exactly like the rest of the flow stack.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

import pandas as pd


# ---------------------------------------------------------------------------
# Config -- every threshold/window is a named field so it can be grid-searched
# or preregistered without touching a function body (repo convention).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AbsorptionConfig:
    """Thresholds and windows for the absorption detector."""

    # Rolling window (in observations) over which flow is measured. For
    # hourly bars this is ~20 hours; for a live print tape it is the last N
    # prints.
    window: int = 20
    # Short window (in observations) over which the price stall is measured.
    # Absorption is heavy flow with price pinned *now*, so the stall is
    # judged over the last few bars, not the whole flow window (over 20
    # hourly bars the median move is ~2.4 ATRs, which would never stall).
    price_window: int = 3
    # Trailing baseline (in observations) used to normalize "heavy" volume.
    # The baseline excludes the flow window itself, otherwise a surge is
    # dampened by its own volume and can never clear the surge gate.
    baseline_window: int = 60
    # Trailing window for the close-to-close / true-range volatility unit.
    atr_window: int = 14
    # gross_flow / (baseline_mean * window) must reach this to be "heavy".
    vol_surge_min: float = 1.5
    # |price_move| over ``price_window`` must stay below this many ATRs to
    # be a "stall".
    price_stall_max: float = 0.5
    # |net_flow| / gross_flow must reach this to be directional.
    imbalance_min: float = 0.3
    # When > 0, the imbalance gate becomes distribution-relative in addition
    # to the absolute floor above: once at least min_baseline_observations
    # of this symbol's own trailing |imbalance| history exist (same window
    # as baseline_window), the effective threshold becomes
    #   clamp(percentile(history, imbalance_percentile), 0.5*imbalance_min, imbalance_min)
    # i.e. it can only RELAX the gate below imbalance_min (never tighten it
    # above), and it is floored at half of imbalance_min so a symbol with a
    # flat/near-zero imbalance history can never trivially clear the gate on
    # noise. 0 (default) disables this entirely: the gate is the plain
    # absolute imbalance_min, unchanged from every existing caller.
    #
    # Why this exists: ``imbalance`` here is CLV(bars) x volume normalized
    # into net/gross (research.flow_state.signed_volume_proxy), a bounded,
    # mean-reverting proxy -- not an aggressor-classified tape. Measured
    # across all 59 tracked symbols' full local history in edge/data/1h
    # (296,937 mature, non-warming hourly readouts, ~2023-08 to ~2026-07):
    # a fixed imbalance_min=0.3 sits at roughly the 95th-97th percentile of
    # that proxy's own distribution (p90=0.27, p95=0.32, p97=0.35) -- real
    # and reachable (6.5% of readouts individually, 0.50% jointly with
    # vol_surge_min=1.5 + stall + a mature baseline: 1,492/296,937, i.e.
    # roughly one genuine absorption print per symbol every ~6 weeks of
    # hourly bars), just strict enough that a single cross-sectional
    # snapshot across 59 symbols shows zero signals ~74% of the time by
    # chance alone -- not evidence the gate is broken. Percentile mode lets
    # a caller opt into a self-calibrating, per-symbol relative bar instead
    # of asserting one fixed absolute number is correct for every
    # signed-flow input forever; see CLV_PROXY_SCAN_CONFIG below for the
    # config build_absorption_scan actually uses.
    imbalance_percentile: float = 0.0
    # Minimum observations before any readout is produced.
    min_observations: int = 20
    # Minimum trailing baseline samples ("heavy volume" is judged relative to
    # this many prior observations) before ``signal`` may fire. Passing
    # ``min_observations`` alone lets the flow window fill while the
    # baseline is still nearly empty (as few as 1 sample), which would judge
    # "heavy" against noise. Half of ``baseline_window`` is a reasonable
    # default anchor; override for a stricter or looser warm-up.
    min_baseline_observations: int = 30

    def __post_init__(self) -> None:
        if self.window < 2:
            raise ValueError("window must be >= 2")
        if self.price_window < 1:
            raise ValueError("price_window must be >= 1")
        if self.baseline_window < 2:
            raise ValueError("baseline_window must be >= 2")
        if self.atr_window < 1:
            raise ValueError("atr_window must be >= 1")
        if self.vol_surge_min <= 0:
            raise ValueError("vol_surge_min must be positive")
        if self.price_stall_max <= 0:
            raise ValueError("price_stall_max must be positive")
        if not 0.0 <= self.imbalance_min <= 1.0:
            raise ValueError("imbalance_min must be in [0, 1]")
        if not 0.0 <= self.imbalance_percentile < 1.0:
            raise ValueError("imbalance_percentile must be in [0, 1)")
        if self.min_observations < 1:
            raise ValueError("min_observations must be positive")
        if not 1 <= self.min_baseline_observations <= self.baseline_window:
            raise ValueError("min_baseline_observations must be in [1, baseline_window]")


# ---------------------------------------------------------------------------
# Observation / readout records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AbsorptionObservation:
    """One unit of flow. ``signed_flow`` is the signed portion of ``volume``.

    ``signed_flow`` may be 0 (unsigned activity); it must never exceed
    ``volume`` in magnitude. ``high``/``low`` are optional and only improve
    the volatility unit (true range) when present.
    """

    ts: datetime
    price: float
    volume: float
    signed_flow: float = 0.0
    high: float | None = None
    low: float | None = None


@dataclass(frozen=True)
class AbsorptionReadout:
    """Detector state at one observation index.

    ``baseline_warming`` is True whenever the trailing baseline has fewer
    than ``cfg.min_baseline_observations`` samples. It is the fail-closed
    "not ready" signal: distinct from ``signal=False``, which means the
    baseline was mature and evaluated but found nothing. A caller must not
    treat ``signal=False`` while ``baseline_warming=True`` as "evaluated,
    no absorption" -- it means "not yet evaluable."

    ``imbalance_threshold`` is the actual |imbalance| bar that had to be
    cleared for ``flow_direction`` to be nonzero on this observation --
    ``cfg.imbalance_min`` unchanged, or a symbol-relative value when
    ``cfg.imbalance_percentile`` is enabled (see ``AbsorptionConfig``). It
    makes the gate's calibration visible per-row instead of only living in
    the config: an operator can see how close ``imbalance`` came to it.
    """

    index: int
    ts: datetime
    price: float
    gross_flow: float
    net_flow: float
    imbalance: float
    price_move: float
    vol_ratio: float
    atr: float
    atr_frac: float
    surge_strength: float
    stall_strength: float
    absorption_magnitude: float
    absorption_score: float
    flow_direction: int
    reversal_direction: int
    signal: bool
    signal_kind: str | None
    baseline_warming: bool
    imbalance_threshold: float


def readout_to_dict(readout: AbsorptionReadout) -> dict[str, Any]:
    """Serialize a readout for the API. Every key is always present."""
    return {
        "index": readout.index,
        "ts": readout.ts.isoformat(),
        "price": round(readout.price, 4),
        "gross_flow": round(readout.gross_flow, 2),
        "net_flow": round(readout.net_flow, 2),
        "imbalance": round(readout.imbalance, 6),
        "price_move": round(readout.price_move, 6),
        "vol_ratio": round(readout.vol_ratio, 4),
        "atr": round(readout.atr, 4),
        "atr_frac": round(readout.atr_frac, 6),
        "surge_strength": round(readout.surge_strength, 4),
        "stall_strength": round(readout.stall_strength, 4),
        "absorption_magnitude": round(readout.absorption_magnitude, 4),
        "absorption_score": round(readout.absorption_score, 4),
        "flow_direction": readout.flow_direction,
        "reversal_direction": readout.reversal_direction,
        "signal": readout.signal,
        "signal_kind": readout.signal_kind,
        "baseline_warming": readout.baseline_warming,
        "imbalance_threshold": round(readout.imbalance_threshold, 6),
    }


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile of an already-sorted, non-empty-or-empty seq.

    ``fraction`` in [0, 1); e.g. 0.85 -> the value at/above ~85% of the
    supplied history. Returns 0.0 for an empty input (no history to derive
    a threshold from -- callers must not treat that as "found a low bar").
    """
    n = len(sorted_values)
    if n == 0:
        return 0.0
    idx = min(n - 1, int(fraction * n))
    return sorted_values[idx]


# ---------------------------------------------------------------------------
# Incremental detector
# ---------------------------------------------------------------------------

class AbsorptionDetector:
    """Streaming absorption detector. O(1) per ``update`` by default.

    Maintains rolling sums over a fixed window plus a trailing baseline mean
    and a trailing true-range mean, so a live feed never triggers a full
    window recompute. ``update`` returns the readout for the observation just
    folded in (a warm-up readout with ``signal=False`` until enough history
    exists). If ``cfg.imbalance_percentile > 0`` is enabled, each update
    additionally sorts a small (<= ``baseline_window``) trailing history to
    resolve the relative imbalance threshold -- O(w log w) in that window,
    not O(1) -- but the window is small and fixed, so this stays cheap.
    """

    def __init__(self, cfg: AbsorptionConfig | None = None) -> None:
        self.cfg = cfg or AbsorptionConfig()
        self._window_vol: deque[float] = deque(maxlen=self.cfg.window)
        self._window_signed: deque[float] = deque(maxlen=self.cfg.window)
        self._price_window: deque[float] = deque(maxlen=self.cfg.price_window)
        self._baseline_vol: deque[float] = deque(maxlen=self.cfg.baseline_window)
        self._atr_ranges: deque[float] = deque(maxlen=self.cfg.atr_window)
        self._imbalance_history: deque[float] = deque(maxlen=self.cfg.baseline_window)
        self._vol_sum = 0.0
        self._signed_sum = 0.0
        self._baseline_sum = 0.0
        self._atr_sum = 0.0
        self._prev_price: float | None = None
        self._index = 0

    @staticmethod
    def _push(dq: deque[float], value: float, running: float) -> float:
        if len(dq) == dq.maxlen:
            running -= dq[0]
        dq.append(value)
        return running + value

    def update(self, obs: AbsorptionObservation) -> AbsorptionReadout:
        cfg = self.cfg
        price = float(obs.price)
        volume = float(obs.volume)
        signed = float(obs.signed_flow) if obs.signed_flow is not None else 0.0

        if self._prev_price is None:
            true_range = 0.0
        elif obs.high is not None and obs.low is not None:
            high = float(obs.high)
            low = float(obs.low)
            prev = self._prev_price
            true_range = max(high - low, abs(high - prev), abs(low - prev))
        else:
            true_range = abs(price - self._prev_price)

        # The baseline is the trailing volume *before* the flow window, so a
        # surge is not dampened by its own volume.
        if len(self._window_vol) == self._window_vol.maxlen:
            self._baseline_sum = self._push(
                self._baseline_vol, self._window_vol[0], self._baseline_sum
            )
        self._vol_sum = self._push(self._window_vol, volume, self._vol_sum)
        self._signed_sum = self._push(self._window_signed, signed, self._signed_sum)
        self._price_window.append(price)
        self._atr_sum = self._push(self._atr_ranges, true_range, self._atr_sum)

        self._prev_price = price
        self._index += 1
        return self._snapshot(obs)

    def _snapshot(self, obs: AbsorptionObservation) -> AbsorptionReadout:
        cfg = self.cfg
        index = self._index - 1  # 0-based, matching the observation sequence
        price = float(obs.price)

        # The baseline deque is pushed to inside update() regardless of warm
        # state, so this is accurate even if window < min_observations lets
        # the baseline start filling before the warm-up period ends.
        baseline_warming = len(self._baseline_vol) < cfg.min_baseline_observations

        warm = index < cfg.min_observations or len(self._window_vol) < cfg.window
        if warm:
            return AbsorptionReadout(
                index=index,
                ts=obs.ts,
                price=price,
                gross_flow=0.0,
                net_flow=0.0,
                imbalance=0.0,
                price_move=0.0,
                vol_ratio=0.0,
                atr=0.0,
                atr_frac=0.0,
                surge_strength=0.0,
                stall_strength=0.0,
                absorption_magnitude=0.0,
                absorption_score=0.0,
                flow_direction=0,
                reversal_direction=0,
                signal=False,
                signal_kind=None,
                baseline_warming=baseline_warming,
                imbalance_threshold=cfg.imbalance_min,
            )

        gross = self._vol_sum
        net = self._signed_sum
        imbalance = net / gross if gross > 0 else 0.0

        # Stall is judged over the short price window: heavy flow with price
        # pinned *now*, not over the whole flow window.
        first_price = self._price_window[0]
        price_move = (price - first_price) / first_price if first_price > 0 else 0.0

        baseline_mean = (
            self._baseline_sum / len(self._baseline_vol) if self._baseline_vol else 0.0
        )
        vol_ratio = gross / (baseline_mean * cfg.window) if baseline_mean > 0 else 0.0

        atr = self._atr_sum / len(self._atr_ranges) if self._atr_ranges else 0.0
        atr_frac = atr / price if price > 0 else 0.0

        surge = min(1.0, vol_ratio / cfg.vol_surge_min)
        stall_denom = cfg.price_stall_max * atr_frac
        stall = 1.0 - min(1.0, abs(price_move) / stall_denom) if stall_denom > 0 else 0.0

        # Distribution-relative imbalance gate (opt-in, see AbsorptionConfig
        # .imbalance_percentile). Computed from history strictly BEFORE this
        # observation, then this observation's |imbalance| is appended for
        # future steps -- never self-referential. Bounded to
        # [0.5*imbalance_min, imbalance_min]: it can only relax the absolute
        # gate, never tighten it, and a flat/near-zero trailing history can
        # never trivially clear the gate on noise.
        imbalance_threshold = cfg.imbalance_min
        if (
            cfg.imbalance_percentile > 0
            and len(self._imbalance_history) >= cfg.min_baseline_observations
        ):
            relative = _percentile(
                sorted(self._imbalance_history), cfg.imbalance_percentile
            )
            imbalance_threshold = max(0.5 * cfg.imbalance_min, min(cfg.imbalance_min, relative))
        self._imbalance_history.append(abs(imbalance))

        if imbalance >= imbalance_threshold:
            flow_direction = 1
        elif imbalance <= -imbalance_threshold:
            flow_direction = -1
        else:
            flow_direction = 0

        score = flow_direction * surge * stall
        magnitude = surge * stall
        signal = (
            not baseline_warming
            and flow_direction != 0
            and vol_ratio >= cfg.vol_surge_min
            and abs(price_move) < cfg.price_stall_max * atr_frac
        )
        signal_kind = None
        if signal:
            signal_kind = "buy_absorption" if flow_direction > 0 else "sell_absorption"

        return AbsorptionReadout(
            index=index,
            ts=obs.ts,
            price=price,
            gross_flow=gross,
            net_flow=net,
            imbalance=imbalance,
            price_move=price_move,
            vol_ratio=vol_ratio,
            atr=atr,
            atr_frac=atr_frac,
            surge_strength=surge,
            stall_strength=stall,
            absorption_magnitude=magnitude,
            absorption_score=score,
            flow_direction=flow_direction,
            reversal_direction=-flow_direction,
            signal=signal,
            signal_kind=signal_kind,
            baseline_warming=baseline_warming,
            imbalance_threshold=imbalance_threshold,
        )


def detect_absorption_series(
    observations: Sequence[AbsorptionObservation],
    cfg: AbsorptionConfig | None = None,
) -> list[AbsorptionReadout]:
    """Replay the detector over a sequence; one readout per observation."""
    detector = AbsorptionDetector(cfg)
    return [detector.update(obs) for obs in observations]


# ---------------------------------------------------------------------------
# Observation builders (bar / print -> detector input)
# ---------------------------------------------------------------------------

def observations_from_bars(bars: pd.DataFrame) -> list[AbsorptionObservation]:
    """OHLCV frame -> observations. ``signed_flow`` is the repo's CLV x volume
    proxy (``research.flow_state.signed_volume_proxy``), so direction is a
    descriptive proxy, never a measured aggressor side."""
    from edge.research.flow_state import signed_volume_proxy

    signed = signed_volume_proxy(bars)
    observations: list[AbsorptionObservation] = []
    for ts, row in bars.iterrows():
        observations.append(
            AbsorptionObservation(
                ts=ts.to_pydatetime(),
                price=float(row["close"]),
                volume=float(row["volume"]),
                signed_flow=float(signed.loc[ts]),
                high=float(row["high"]),
                low=float(row["low"]),
            )
        )
    return observations


def observations_from_flow_prints(
    prints: Sequence[Mapping[str, Any]],
) -> list[AbsorptionObservation]:
    """Normalized options-flow prints -> observations.

    ``volume`` is premium notional (the flow stack's activity unit) and
    ``signed_flow`` is aggressor-signed premium (0 when unsigned). Price is
    the print's underlying price, forward-filled when a print omits it.
    Prints with no price and no premium are skipped.

    ``AbsorptionDetector`` is strictly causal: it assumes observation 0 is
    the OLDEST print and rolls forward from there. Callers are not trusted
    to hand prints in that order -- e.g. the LSE flow tape is sorted
    newest-first -- so this function sorts prints ascending by timestamp
    itself before building observations (and before the price forward-fill
    runs, so fill direction is also correct). The sort is stable, so prints
    that share an exact timestamp keep the caller's original (provider)
    order. Prints with a missing or unparseable timestamp are dropped
    outright rather than sorted to either end, since there is no reliable
    place for them on the tape.
    """
    parsed: list[tuple[pd.Timestamp, Mapping[str, Any]]] = []
    for row in prints:
        ts_raw = row.get("timestamp") or row.get("ts")
        if ts_raw is None:
            continue
        try:
            ts = pd.Timestamp(ts_raw)
        except (TypeError, ValueError):
            continue
        if pd.isna(ts):
            continue
        parsed.append((ts, row))
    parsed.sort(key=lambda item: item[0])

    observations: list[AbsorptionObservation] = []
    last_price: float | None = None
    for ts, row in parsed:
        price = _finite(row.get("underlying_price") or row.get("spot"))
        if price is None:
            price = last_price
        else:
            last_price = price
        volume = _finite(row.get("premium") or row.get("volume") or row.get("contracts"))
        signed = _finite(row.get("signed_premium"))
        if price is None or volume is None or volume <= 0:
            continue
        observations.append(
            AbsorptionObservation(
                ts=ts.to_pydatetime(),
                price=price,
                volume=volume,
                signed_flow=signed if signed is not None else 0.0,
            )
        )
    return observations


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


# ---------------------------------------------------------------------------
# Cross-section scan (pure, in-memory in/out)
# ---------------------------------------------------------------------------

# build_absorption_scan always feeds observations_from_bars (the CLV proxy),
# never an aggressor-signed tape, so it can select a calibration derived
# specifically for that input rather than the plain aggressor-tape default
# (see AbsorptionConfig.imbalance_percentile for the full derivation and the
# measured percentiles). imbalance_min / vol_surge_min are left at the
# already-verified-reachable defaults (0.3 / 1.5); imbalance_percentile=0.85
# additionally lets each symbol's own trailing top-15% count as directional,
# capped by that same 0.3 ceiling and floored at 0.15 -- i.e. this can only
# ever make the gate easier to clear than the plain absolute default, never
# harder, and a flat/quiet symbol still cannot trip it on noise.
CLV_PROXY_SCAN_CONFIG = AbsorptionConfig(imbalance_percentile=0.85)


def build_absorption_scan(
    price_data: Mapping[str, pd.DataFrame],
    cfg: AbsorptionConfig | None = None,
) -> dict[str, Any]:
    """Ranked absorption cross-section from in-memory OHLCV frames.

    ``price_data`` maps symbol -> OHLCV DataFrame (open/high/low/close/volume,
    ascending DatetimeIndex, most-recent-last). Returns a board ranked by
    |absorption_score| descending -- the directional read the board exists
    for -- with ``absorption_magnitude`` descending as the tiebreaker.
    ``absorption_score`` is 0 whenever ``flow_direction == 0`` (unsigned
    flow), so an undirected row never outranks a genuine directional
    signal purely on volume. A symbol with too little history is skipped,
    never fabricated.

    When ``cfg`` is omitted, ``CLV_PROXY_SCAN_CONFIG`` is used (this
    function always builds observations via ``observations_from_bars``, the
    CLV proxy) rather than a bare ``AbsorptionConfig()``.

    Every row carries ``baseline_warming`` and ``imbalance_threshold`` so a
    caller can distinguish "not yet evaluable" from "evaluated, nothing
    found," and see exactly what bar this row's imbalance was judged
    against. The top-level ``gate_summary`` reports, across every evaluated
    row, how many clear each gate and the observed |imbalance| / vol_ratio
    distribution -- so a board with few or zero signals is explicable
    ("gate not met, here is how close"), never a silent blank screen (the
    repo's fail-closed / explicit-missing-state convention).
    """
    resolved_cfg = cfg if cfg is not None else CLV_PROXY_SCAN_CONFIG
    rows: list[dict[str, Any]] = []
    for symbol, bars in price_data.items():
        try:
            observations = observations_from_bars(bars)
            if len(observations) < resolved_cfg.min_observations:
                continue
            series = detect_absorption_series(observations, resolved_cfg)
        except Exception:
            # One malformed frame must not kill the whole scan (repo rule).
            continue
        if not series:
            continue
        last = series[-1]
        rows.append(
            {
                "symbol": str(symbol).upper(),
                "price": round(last.price, 4),
                "absorption_magnitude": round(last.absorption_magnitude, 4),
                "absorption_score": round(last.absorption_score, 4),
                "flow_direction": last.flow_direction,
                "reversal_direction": last.reversal_direction,
                "signal": last.signal,
                "signal_kind": last.signal_kind,
                "imbalance": round(last.imbalance, 6),
                "imbalance_threshold": round(last.imbalance_threshold, 6),
                "vol_ratio": round(last.vol_ratio, 4),
                "price_move": round(last.price_move, 6),
                "atr_frac": round(last.atr_frac, 6),
                "baseline_warming": last.baseline_warming,
                "asof": last.ts.isoformat(),
            }
        )
    rows.sort(
        key=lambda row: (
            -abs(float(row["absorption_score"])),
            -float(row["absorption_magnitude"]),
        )
    )

    imbalance_samples = sorted(abs(float(row["imbalance"])) for row in rows)
    vol_ratio_samples = sorted(float(row["vol_ratio"]) for row in rows)
    gate_summary = {
        "vol_surge_min": resolved_cfg.vol_surge_min,
        "imbalance_min": resolved_cfg.imbalance_min,
        "imbalance_percentile": resolved_cfg.imbalance_percentile,
        "rows_baseline_warming": sum(1 for row in rows if row["baseline_warming"]),
        "rows_clearing_direction_gate": sum(1 for row in rows if row["flow_direction"] != 0),
        "rows_clearing_surge_gate": sum(
            1 for row in rows if row["vol_ratio"] >= resolved_cfg.vol_surge_min
        ),
        "rows_signal": sum(1 for row in rows if row["signal"]),
        "imbalance_abs_p50": round(_percentile(imbalance_samples, 0.50), 6),
        "imbalance_abs_p90": round(_percentile(imbalance_samples, 0.90), 6),
        "imbalance_abs_max": round(imbalance_samples[-1], 6) if imbalance_samples else 0.0,
        "vol_ratio_p50": round(_percentile(vol_ratio_samples, 0.50), 4),
        "vol_ratio_p90": round(_percentile(vol_ratio_samples, 0.90), 4),
        "vol_ratio_max": round(vol_ratio_samples[-1], 4) if vol_ratio_samples else 0.0,
    }

    return {
        "universe_size": len(price_data),
        "evaluated": len(rows),
        "rows": rows,
        "gate_summary": gate_summary,
    }


# ---------------------------------------------------------------------------
# Order-flow absorption matrix -- fixed-range profile over the recent window
#
# This is the per-symbol companion to the scan: given the same OHLCV frame the
# detector consumes, it bins the trailing lookback window by price and answers
# the questions a Bookmap-style operator asks -- where did volume stack up
# (liquidity profile), which side was aggressive (delta column), where was
# aggression absorbed into a wick (absorption column), which price levels
# carry the strongest defended interest (strength zones), and what is the net
# flow-pressure read right now (pressure score).
#
# Everything here is built from the same descriptive proxies the detector
# uses (candle direction, CLV x volume, wick fractions) -- this repo has no
# trades/quotes/L2 data, so "buy"/"sell" are candle-direction buckets and
# "absorption" is wick-defended volume, never measured order-book depth.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderflowMatrixConfig:
    """Thresholds and weights for the order-flow absorption matrix."""

    # Trailing bars the profile, delta/absorption columns and zone scores
    # are built from.
    lookback: int = 220
    # Vertical price bins across the window's high-low range.
    bins: int = 30
    # Bars above this volume percentile are "strong" (shaded brighter).
    strong_volume_pct: float = 85.0
    # Value-area target coverage as a percent of total window volume.
    value_area_pct: float = 70.0
    # Cluster (print-size) tiers: a bar is a print when it beats this
    # percentile of recent volume / |delta| in a majority of windows.
    small_pct: float = 75.0
    medium_pct: float = 90.0
    big_pct: float = 97.0
    short_len: int = 20
    mid_len: int = 50
    long_len: int = 100
    # Zone scoring: minimum 0-10 strength to draw, cap on drawn zones, and
    # the touch count that earns the full touch component.
    zone_min_strength: float = 4.0
    zone_max: int = 6
    zone_touch_norm: float = 14.0
    # Zone score weights (normalized by their sum).
    w_vol: float = 0.28
    w_abs: float = 0.24
    w_touch: float = 0.22
    w_rej: float = 0.14
    w_rec: float = 0.12
    # Pressure score weights: net imbalance / CVD bias / absorption side /
    # latest print direction.
    pw_imbalance: float = 0.32
    pw_cvd: float = 0.30
    pw_absorption: float = 0.23
    pw_cluster: float = 0.15


def _wick_absorption_split(
    open_: float, high: float, low: float, close: float, volume: float
) -> tuple[float, float]:
    """Wick-fraction absorption proxy for one bar.

    A long upper wick means aggressive buyers pushed into the high and were
    absorbed by passive sellers; a long lower wick is the mirror. The bar's
    volume is attributed to the wick side in proportion to the wick's share
    of the range, but only when the wick is dominant (>50% of the range) so
    ordinary bars contribute nothing.

    Returns ``(absorbed_at_highs, absorbed_at_lows)``.
    """
    rng = high - low
    if rng <= 0 or volume <= 0:
        return 0.0, 0.0
    upper = high - max(open_, close)
    lower = min(open_, close) - low
    at_highs = volume * (upper / rng) if upper > 0.5 * rng else 0.0
    at_lows = volume * (lower / rng) if lower > 0.5 * rng else 0.0
    return at_highs, at_lows


def build_orderflow_matrix(
    bars: pd.DataFrame,
    readouts: Sequence[AbsorptionReadout] | None = None,
    cfg: OrderflowMatrixConfig | None = None,
) -> dict[str, Any]:
    """Fixed-range order-flow profile over the trailing window of ``bars``.

    ``bars`` is an OHLCV frame (open/high/low/close/volume, ascending,
    most-recent-last) -- the same frame the caller fed the detector. When
    ``readouts`` are supplied and positionally aligned 1:1 with ``bars``
    (true whenever they came from ``detect_absorption_series`` over
    ``observations_from_bars(bars)``), per-bar delta uses the detector's
    ``net_flow`` so the matrix and the series agree; otherwise delta falls
    back to the CLV x volume proxy computed here.

    The returned dict always carries the same keys; when the frame is empty
    or degenerate (no price range), bins/zones are empty and ``poc`` /
    ``vah`` / ``val`` are None rather than fabricated. Every number is
    rounded for the wire.
    """
    resolved = cfg if cfg is not None else OrderflowMatrixConfig()
    window = bars.tail(resolved.lookback)
    n = len(window)

    def _empty() -> dict[str, Any]:
        return {
            "available": False,
            "lookback": resolved.lookback,
            "bins_used": 0,
            "window_bars": n,
            "window_low": None,
            "window_high": None,
            "bins": [],
            "poc": None,
            "vah": None,
            "val": None,
            "zones": [],
            "pressure": None,
            "last_print": None,
        }

    if n < 5:
        return _empty()

    highs = window["high"].to_numpy(dtype=float)
    lows = window["low"].to_numpy(dtype=float)
    opens = window["open"].to_numpy(dtype=float)
    closes = window["close"].to_numpy(dtype=float)
    volumes = window["volume"].to_numpy(dtype=float)

    hi_win = float(highs.max())
    lo_win = float(lows.min())
    rng_win = hi_win - lo_win
    if rng_win <= 0:
        return _empty()

    n_bins = resolved.bins
    bin_sz = rng_win / n_bins

    # Per-bar delta: detector readouts when aligned, else the CLV proxy.
    net_by_bar: list[float] = []
    if readouts is not None and len(readouts) == len(bars):
        tail = readouts[-n:]
        net_by_bar = [float(r.net_flow) for r in tail]
    else:
        for o, h, l, c, v in zip(opens, highs, lows, closes, volumes):
            rng = h - l
            clv = ((c - l) - (h - c)) / rng if rng > 0 else 0.0
            net_by_bar.append(clv * v)

    vol_sorted = sorted(float(v) for v in volumes)
    strong_thr = _percentile(vol_sorted, resolved.strong_volume_pct / 100.0)

    total_bin = [0.0] * n_bins
    buy_bin = [0.0] * n_bins
    sell_bin = [0.0] * n_bins
    strong_buy_bin = [0.0] * n_bins
    strong_sell_bin = [0.0] * n_bins
    delta_bin = [0.0] * n_bins
    absorb_bin = [0.0] * n_bins
    touch_bin = [0.0] * n_bins
    rej_bin = [0.0] * n_bins
    # Offset (bars ago) of the most recent touch per bin; starts "never".
    rec_bin = [float(n)] * n_bins

    def _bin_of(price: float) -> int:
        return max(0, min(n_bins - 1, int((price - lo_win) / bin_sz)))

    for off, (o, h, l, c, v) in enumerate(zip(opens, highs, lows, closes, volumes)):
        if v <= 0:
            continue
        buy = c >= o
        strong = v >= strong_thr
        bi = _bin_of((h + l + c) / 3.0)
        total_bin[bi] += v
        if buy:
            buy_bin[bi] += v
            if strong:
                strong_buy_bin[bi] += v
        else:
            sell_bin[bi] += v
            if strong:
                strong_sell_bin[bi] += v
        delta_bin[bi] += net_by_bar[off]

        # Wick-defended volume lands in the extreme bin it was absorbed at.
        at_hi, at_lo = _wick_absorption_split(o, h, l, c, v)
        if at_hi > 0:
            absorb_bin[_bin_of(h)] += at_hi
        if at_lo > 0:
            absorb_bin[_bin_of(l)] += at_lo

        lo_i = _bin_of(l)
        hi_i = _bin_of(h)
        rng = h - l
        for b in range(lo_i, hi_i + 1):
            touch_bin[b] += 1.0
            if off < rec_bin[b]:
                rec_bin[b] = off
        if rng > 0:
            if (h - max(o, c)) > 0.5 * rng:
                rej_bin[hi_i] += 1.0
            if (min(o, c) - l) > 0.5 * rng:
                rej_bin[lo_i] += 1.0

    tot_vol = sum(total_bin)
    if tot_vol <= 0:
        return _empty()

    max_bin_vol = max(total_bin)
    max_abs = max(absorb_bin)
    max_rej = max(rej_bin)
    max_abs_delta = max(abs(d) for d in delta_bin)
    tot_buy = sum(buy_bin)
    tot_sell = sum(sell_bin)

    # POC + value area (expand from POC to target coverage).
    poc_idx = total_bin.index(max_bin_vol)
    poc_px = lo_win + bin_sz * poc_idx + bin_sz * 0.5
    va_flag = [False] * n_bins
    va_flag[poc_idx] = True
    target = tot_vol * resolved.value_area_pct / 100.0
    acc = total_bin[poc_idx]
    lo_ix = hi_ix = poc_idx
    while acc < target and (lo_ix > 0 or hi_ix < n_bins - 1):
        up_c = total_bin[hi_ix + 1] if hi_ix < n_bins - 1 else -1.0
        dn_c = total_bin[lo_ix - 1] if lo_ix > 0 else -1.0
        if up_c >= dn_c:
            hi_ix += 1
            acc += up_c
            va_flag[hi_ix] = True
        else:
            lo_ix -= 1
            acc += dn_c
            va_flag[lo_ix] = True
    vah_px = lo_win + bin_sz * (hi_ix + 1)
    val_px = lo_win + bin_sz * lo_ix

    # Zone scoring: local peaks of the volume/absorption blend, scored by the
    # weighted mix of volume share, absorption share, touches, rejections and
    # recency, on a 0-10 scale.
    w_sum = max(resolved.w_vol + resolved.w_abs + resolved.w_touch + resolved.w_rej + resolved.w_rec, 1e-9)
    sig = [0.0] * n_bins
    strength = [0.0] * n_bins
    for i in range(n_bins):
        vol_f = total_bin[i] / max_bin_vol if max_bin_vol > 0 else 0.0
        abs_f = absorb_bin[i] / max_abs if max_abs > 0 else 0.0
        touch_f = min(touch_bin[i] / max(resolved.zone_touch_norm, 1.0), 1.0)
        rej_f = rej_bin[i] / max_rej if max_rej > 0 else 0.0
        rec_f = 1.0 - min(rec_bin[i] / max(n - 1, 1), 1.0)
        strength[i] = (
            (vol_f * resolved.w_vol + abs_f * resolved.w_abs + touch_f * resolved.w_touch
             + rej_f * resolved.w_rej + rec_f * resolved.w_rec)
            / w_sum * 10.0
        )
        sig[i] = vol_f * 0.5 + abs_f * 0.5

    peaks: list[int] = []
    for i in range(1, n_bins - 1):
        if sig[i] > sig[i - 1] and sig[i] >= sig[i + 1] and sig[i] > 0 and strength[i] >= resolved.zone_min_strength:
            peaks.append(i)
    peaks.sort(key=lambda i: strength[i], reverse=True)
    peaks = peaks[: resolved.zone_max]

    last_close = float(closes[-1])
    zones: list[dict[str, Any]] = []
    for i in sorted(peaks):
        z_lo = lo_win + bin_sz * i
        z_hi = z_lo + bin_sz
        support = (z_lo + z_hi) / 2.0 < last_close
        sc = round(strength[i], 1)
        zones.append(
            {
                "low": round(z_lo, 4),
                "high": round(z_hi, 4),
                "mid": round((z_lo + z_hi) / 2.0, 4),
                "strength": sc,
                "tier": (
                    "ELITE" if sc >= 8
                    else "STRONG" if sc >= 6.5
                    else "MODERATE" if sc >= 5
                    else "WEAK" if sc >= 3.5
                    else "FORMING"
                ),
                "side": "support" if support else "resistance",
                "volume": round(total_bin[i], 2),
                "absorption": round(absorb_bin[i], 2),
                "touches": int(touch_bin[i]),
                "rejections": int(rej_bin[i]),
            }
        )
    zones.sort(key=lambda z: z["strength"], reverse=True)

    # Cluster (print) tiers: a bar is a print when its volume or |delta|
    # beats the tier percentile in a majority of the three windows. The last
    # print drives the pressure score's cluster term.
    def _print_tiers(series_abs: list[float], raw: list[float]) -> tuple[list[int], bool]:
        m = len(series_abs)
        tiers = [0] * m
        for i in range(m):
            def _hits(pct_num: float) -> int:
                count = 0
                for win in (resolved.short_len, resolved.mid_len, resolved.long_len):
                    lo = max(0, i - win + 1)
                    hist = sorted(series_abs[lo : i + 1])
                    if raw[i] >= _percentile(hist, pct_num / 100.0):
                        count += 1
                return count

            if _hits(resolved.big_pct) >= 2:
                tiers[i] = 3
            elif _hits(resolved.medium_pct) >= 2:
                tiers[i] = 2
            elif _hits(resolved.small_pct) >= 2:
                tiers[i] = 1
        return tiers, True

    vol_list = [float(v) for v in volumes]
    abs_delta_list = [abs(d) for d in net_by_bar]
    vol_tiers, _ = _print_tiers(vol_list, vol_list)
    delta_tiers, _ = _print_tiers(abs_delta_list, abs_delta_list)
    tiers = [max(a, b) for a, b in zip(vol_tiers, delta_tiers)]

    last_cluster_dir = 0.0
    for i in range(n - 1, -1, -1):
        if tiers[i] > 0:
            d = net_by_bar[i]
            c, o = closes[i], opens[i]
            last_cluster_dir = (
                1.0 if (d > 0 or (d == 0 and c >= o)) else -1.0
            )
            break
    last_tier = tiers[-1]
    last_delta = net_by_bar[-1]
    last_print = {
        "tier": "WHALE" if last_tier == 3 else "MEDIUM" if last_tier == 2 else "SMALL" if last_tier == 1 else None,
        "tier_rank": last_tier,
        "side": ("BUY" if last_delta > 0 else "SELL" if last_delta < 0 else "MIXED") if last_tier > 0 else None,
        "bar_delta": round(last_delta, 2),
        "bar_volume": round(vol_list[-1], 2),
        "vol_ratio": round(vol_list[-1] / (sum(vol_list) / n), 3) if n else 0.0,
    }

    # Pressure score: net buy/sell share + cumulative-delta bias + which side
    # of price absorption stacks on + direction of the latest print.
    imbalance = (tot_buy - tot_sell) / tot_vol
    sum_delta = sum(net_by_bar)
    sum_abs_delta = sum(abs_delta_list)
    cd_bias = sum_delta / max(sum_abs_delta, 1.0)
    abs_above = sum(absorb_bin[i] for i in range(n_bins) if lo_win + bin_sz * (i + 0.5) >= last_close)
    abs_below = tot_abs - abs_above if (tot_abs := sum(absorb_bin)) else 0.0
    abs_bias = (abs_below - abs_above) / max(abs_below + abs_above, 1.0)
    pressure_score = (
        imbalance * resolved.pw_imbalance
        + max(-1.0, min(1.0, cd_bias)) * resolved.pw_cvd
        + abs_bias * resolved.pw_absorption
        + last_cluster_dir * resolved.pw_cluster
    ) * 100.0

    bins_out = []
    for i in range(n_bins):
        z_lo = lo_win + bin_sz * i
        bins_out.append(
            {
                "index": i,
                "low": round(z_lo, 4),
                "high": round(z_lo + bin_sz, 4),
                "mid": round(z_lo + bin_sz * 0.5, 4),
                "total": round(total_bin[i], 2),
                "buy": round(buy_bin[i], 2),
                "sell": round(sell_bin[i], 2),
                "strong_buy": round(strong_buy_bin[i], 2),
                "strong_sell": round(strong_sell_bin[i], 2),
                "delta": round(delta_bin[i], 2),
                "delta_frac": round(abs(delta_bin[i]) / max_abs_delta, 4) if max_abs_delta > 0 else 0.0,
                "absorption": round(absorb_bin[i], 2),
                "touches": int(touch_bin[i]),
                "rejections": int(rej_bin[i]),
                "in_value_area": va_flag[i],
                "strength": round(strength[i], 2),
            }
        )

    return {
        "available": True,
        "lookback": resolved.lookback,
        "bins_used": n_bins,
        "window_bars": n,
        "window_low": round(lo_win, 4),
        "window_high": round(hi_win, 4),
        "asof": window.index[-1].isoformat(),
        "atr": round(_last_atr(readouts, n), 4),
        "bins": bins_out,
        "poc": round(poc_px, 4),
        "vah": round(vah_px, 4),
        "val": round(val_px, 4),
        "zones": zones,
        "last_print": last_print,
        "pressure": {
            "score": round(pressure_score, 1),
            "regime": "ACCUM" if pressure_score > 20 else "DISTRIB" if pressure_score < -20 else "BALANCED",
            "imbalance": round(imbalance, 4),
            "cvd_bias": round(cd_bias, 4),
            "absorption_bias": round(abs_bias, 4),
            "absorption_side": (
                "SUPPORT" if abs_bias > 0.1 else "RESISTANCE" if abs_bias < -0.1 else "BALANCED"
            ),
            "last_cluster_dir": int(last_cluster_dir),
            "buy_share": round(tot_buy / tot_vol, 4),
            "sell_share": round(tot_sell / tot_vol, 4),
        },
    }


def _last_atr(readouts: Sequence[AbsorptionReadout] | None, n: int) -> float:
    """Most recent ATR of the window for price-vs-level context."""
    if readouts:
        return float(readouts[-1].atr)
    return 0.0
