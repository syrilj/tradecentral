"""Walk-forward validation of the VPA engine against historical bars.

Answers one question: **do the engine's directional reads carry information,
and does that hold up outside the window we looked at while building it?**

Design notes that matter for trusting the output:

* **No lookahead.** At each as-of index `t` the engine is handed `bars[:t]` and
  nothing else. The forward return is measured from `t` onward and is never
  visible to the scorer.
* **Chronological split, never random.** Shuffling rows of a time series leaks
  the future into the training window. The split is a date cut: everything
  before it is in-sample, everything after is out-of-sample.
* **Time-based purge, not a row count.** Observations are pooled across many
  symbols on the same date, so dropping `horizon` *rows* around the cut drops
  a fraction of a single trading day, not an embargo. The purge now works in
  TIME: an observation is in-sample only if its entire forward window (its
  `as_of` date plus `horizon` bars, measured against the pooled distinct-date
  calendar) resolves at or before the cut date; out-of-sample begins only
  after an embargo of `horizon` trading dates past the cut. Rows that fall in
  between are dropped and counted.
* **Observations are not independent.** Two things break the textbook
  binomial standard error: consecutive reads for one symbol share most of
  their forward window (`stride` < `horizon` overlap), and every symbol
  observed on the same date shares that day's market move (cross-section).
  The headline confidence interval on every statistic reported here is a
  **cluster bootstrap that resamples whole dates**, not rows -- draw the set
  of distinct `as_of` dates with replacement, recompute the statistic over
  every row belonging to the drawn dates, repeat, and take the 2.5/97.5
  percentiles. The naive per-row binomial SE is still reported alongside it,
  clearly labelled, so the size of the correction is visible.
* **Rolling origins, not one split.** A single 60/40 cut is one draw from
  history. The harness also evaluates several expanding-window cut points
  ("origins") and requires the verdict to be consistent across them. A result
  that appears at one origin and vanishes at the others is reported as noise,
  not signal.
* **Costs are not blind anymore.** Every gross mean-return figure is paired
  with a net-of-cost figure using `--cost-bp` (round-trip, bp).
* **Primary metric is the return, not the hit rate.** Forward returns are
  left-skewed, so raw hit rates sit below 50% for every bucket regardless of
  skill and invite misreading. The primary reported number is a
  direction-signed mean forward return net of the same drift benchmark used
  for the hit rate (`directional_excess_return`), with its clustered CI. Hit
  rate is kept as a secondary, easier-to-read statistic alongside its
  base-rate benchmark.
* **What this can and cannot show.** The thresholds in `vpa_thresholds.py` were
  set from qualitative rules, not fitted to this data, so there is
  little to overfit in the classic sense. What an IS/OOS gap would reveal here
  is *fragility* -- a rule that only worked in one regime. Treat a large gap as
  a warning about robustness, not proof of curve-fitting.
* **Directional evidence, not a strategy.** Hit rate and mean return are
  measured on raw forward returns with no slippage or position sizing. This is
  a signal-quality check, not a P&L claim, even after the cost subtraction.

CLI:
    python3 -m research.vpa_backtest --symbols NVDA,AAPL --timeframe 1D
    python3 -m research.vpa_backtest --universe 40 --horizon 10 --json out.json
    python3 -m research.vpa_backtest --universe 60 --cost-bp 10 --n-origins 5 --jobs 4
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from research.vpa_bars import HOURLY_DIR, DAILY_DIRS, load_bars, sanitize_symbol

# Bars the engine needs before its 20-bar volume baseline and pivot detection
# have anything to work with. Reads before this are not evaluated.
MIN_WARMUP_BARS = 120

# Probability buckets for the calibration table.
PROB_BUCKETS: Sequence[Tuple[int, int]] = ((50, 56), (56, 62), (62, 68), (68, 74), (74, 81))

# Defaults for the statistics that were previously hardcoded / absent.
DEFAULT_N_BOOT = 1000
DEFAULT_SEED = 1234
DEFAULT_COST_BP = 10.0
DEFAULT_N_ORIGINS = 4
# Band of history-fraction cut points spanned by the rolling origins. 0.5
# leaves a usable OOS tail even at the earliest origin; 0.85 leaves at least
# some OOS margin (net of embargo) at the latest.
ORIGIN_FRACTION_RANGE = (0.5, 0.85)


def _forward_return(bars: List[Dict[str, Any]], t: int, horizon: int) -> Optional[float]:
    """Close-to-close return from the as-of bar to `horizon` bars later."""
    if t <= 0 or t + horizon >= len(bars):
        return None
    entry = bars[t - 1].get("c") or bars[t - 1].get("close")
    exit_ = bars[t - 1 + horizon].get("c") or bars[t - 1 + horizon].get("close")
    if not entry or not exit_ or entry <= 0:
        return None
    return (float(exit_) - float(entry)) / float(entry)


def _observations(
    symbol: str,
    timeframe: str,
    horizon: int,
    stride: int,
    max_bars: int,
) -> List[Dict[str, Any]]:
    """Run the engine forward through history, one read per `stride` bars."""
    from research.vpa_engine import analyze_chart_vpa

    bars, meta = load_bars(symbol, timeframe, max_bars)
    if not bars or len(bars) < MIN_WARMUP_BARS + horizon + 10:
        return []

    out: List[Dict[str, Any]] = []
    for t in range(MIN_WARMUP_BARS, len(bars) - horizon, stride):
        fwd = _forward_return(bars, t, horizon)
        if fwd is None:
            continue
        # The engine sees history only. Anything at or after `t` is future.
        # symbol=None is load-bearing: with a symbol the engine prefers its own
        # on-disk bars (the UI contract) and would silently read the *present*
        # for every historical as-of date.
        res = analyze_chart_vpa(
            symbol=None, timeframe=timeframe, ohlcv_series=bars[:t]
        )
        ps = res.get("primary_scenario") or {}
        direction = ps.get("direction")
        prob = ps.get("probability_pct")
        if not direction or prob is None:
            continue
        out.append(
            {
                "symbol": symbol,
                "as_of": bars[t - 1].get("d") or bars[t - 1].get("date"),
                "direction": direction,
                "probability_pct": prob,
                "confidence": res.get("confidence_score"),
                "forward_return": fwd,
                "evidence_count": (res.get("probability_basis") or {}).get("evidence_count", 0),
            }
        )
    return out


def _observations_worker(args: Tuple[str, str, int, int, int]) -> Tuple[str, List[Dict[str, Any]]]:
    """Top-level (picklable) wrapper for `--jobs` process-pool execution.

    Each symbol's walk-forward is fully independent of every other symbol's
    (separate bars, separate engine calls, no shared mutable state), so this
    is safe to parallelize -- it changes nothing about what gets computed,
    only how the per-symbol loop is scheduled.
    """
    symbol, timeframe, horizon, stride, max_bars = args
    return symbol, _observations(symbol, timeframe, horizon, stride, max_bars)


def _collect_observations(
    symbols: Sequence[str],
    timeframe: str,
    horizon: int,
    stride: int,
    max_bars: int,
    jobs: int = 1,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    tasks: List[str] = []
    for raw in symbols:
        sym = sanitize_symbol(raw)
        if sym:
            tasks.append(sym)

    rows: List[Dict[str, Any]] = []
    skipped: List[str] = []

    if jobs and jobs > 1 and len(tasks) > 1:
        results: Dict[str, List[Dict[str, Any]]] = {}
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            futures = {
                ex.submit(_observations_worker, (sym, timeframe, horizon, stride, max_bars)): sym
                for sym in tasks
            }
            for fut in as_completed(futures):
                sym, obs = fut.result()
                results[sym] = obs
        # Preserve deterministic symbol order regardless of completion order.
        for sym in tasks:
            obs = results.get(sym) or []
            if obs:
                rows.extend(obs)
            else:
                skipped.append(sym)
    else:
        for sym in tasks:
            obs = _observations(sym, timeframe, horizon, stride, max_bars)
            if obs:
                rows.extend(obs)
            else:
                skipped.append(sym)

    return rows, skipped


def _hit(obs: Dict[str, Any]) -> Optional[bool]:
    """Did the call point the right way? SIDEWAYS is not scored."""
    d, r = obs["direction"], obs["forward_return"]
    if d == "BULLISH":
        return r > 0
    if d == "BEARISH":
        return r < 0
    return None


# ---------------------------------------------------------------------------
# D1. Clustered bootstrap.
#
# Every headline statistic here (hit rate, mean forward return, the edge vs
# benchmark) is a ratio of sums over observations. Resampling whole `as_of`
# dates with replacement and recomputing the ratio is the standard fix for
# panel data where rows are neither independent draws (stride < horizon
# overlap) nor a single cross-section (many symbols share a date's move).
#
# To make this fast at thousands of rows x thousands of replicates, each
# statistic is expressed purely as a function of PER-DATE SUMS (counts and
# sums of forward returns). One bootstrap draw is then "pick dates with
# replacement, add up their precomputed per-date sums" -- vectorized with
# numpy so the cost scales with (n_boot x n_dates), not (n_boot x n_rows).
# ---------------------------------------------------------------------------

_AGG_COLS: Tuple[str, ...] = (
    "n_all", "pos_all", "sum_fwd_all",
    "n_bull", "hits_bull", "sum_fwd_bull",
    "n_bear", "hits_bear", "sum_fwd_bear",
)
_COL = {name: i for i, name in enumerate(_AGG_COLS)}


def _build_date_aggregates(rows: List[Dict[str, Any]]) -> Tuple[List[str], np.ndarray]:
    """Per distinct `as_of` date: counts and forward-return sums needed to
    reconstruct every statistic below without re-touching individual rows."""
    dates = sorted({str(o["as_of"]) for o in rows})
    idx = {d: i for i, d in enumerate(dates)}
    agg = np.zeros((len(dates), len(_AGG_COLS)), dtype=np.float64)
    for o in rows:
        i = idx[str(o["as_of"])]
        fwd = o["forward_return"]
        agg[i, _COL["n_all"]] += 1.0
        if fwd > 0:
            agg[i, _COL["pos_all"]] += 1.0
        agg[i, _COL["sum_fwd_all"]] += fwd
        h = _hit(o)
        if h is None:
            continue
        if o["direction"] == "BULLISH":
            agg[i, _COL["n_bull"]] += 1.0
            if h:
                agg[i, _COL["hits_bull"]] += 1.0
            agg[i, _COL["sum_fwd_bull"]] += fwd
        elif o["direction"] == "BEARISH":
            agg[i, _COL["n_bear"]] += 1.0
            if h:
                agg[i, _COL["hits_bear"]] += 1.0
            agg[i, _COL["sum_fwd_bear"]] += fwd
    return dates, agg


def _cluster_bootstrap(
    rows: List[Dict[str, Any]], n_boot: int = DEFAULT_N_BOOT, seed: int = DEFAULT_SEED
) -> Tuple[List[str], np.ndarray, np.ndarray]:
    """Return (distinct dates, point-estimate totals, bootstrap totals matrix).

    `boot_totals` has shape (n_boot, len(_AGG_COLS)): row j is the per-column
    sum over one draw of `n_dates` dates sampled with replacement from the
    observed distinct dates -- the cluster-bootstrap resample.
    """
    dates, agg = _build_date_aggregates(rows)
    n_dates = len(dates)
    point_totals = agg.sum(axis=0) if n_dates else np.zeros(len(_AGG_COLS))
    if n_dates == 0 or n_boot <= 0:
        return dates, point_totals, np.zeros((0, len(_AGG_COLS)))
    rng = np.random.default_rng(seed)
    sample_idx = rng.integers(0, n_dates, size=(n_boot, n_dates))
    boot_totals = agg[sample_idx].sum(axis=1)
    return dates, point_totals, boot_totals


def _safe_div(numer: np.ndarray, denom: np.ndarray) -> np.ndarray:
    return np.where(denom > 0, numer / np.where(denom > 0, denom, 1.0), np.nan)


def _stat_up_share(totals: np.ndarray) -> np.ndarray:
    return _safe_div(totals[..., _COL["pos_all"]], totals[..., _COL["n_all"]])


def _stat_mean_fwd_all(totals: np.ndarray) -> np.ndarray:
    return _safe_div(totals[..., _COL["sum_fwd_all"]], totals[..., _COL["n_all"]])


def _stat_hit_rate(totals: np.ndarray) -> np.ndarray:
    n_dir = totals[..., _COL["n_bull"]] + totals[..., _COL["n_bear"]]
    hits = totals[..., _COL["hits_bull"]] + totals[..., _COL["hits_bear"]]
    return _safe_div(hits, n_dir)


def _stat_mean_fwd_directional(totals: np.ndarray) -> np.ndarray:
    n_dir = totals[..., _COL["n_bull"]] + totals[..., _COL["n_bear"]]
    sum_dir = totals[..., _COL["sum_fwd_bull"]] + totals[..., _COL["sum_fwd_bear"]]
    return _safe_div(sum_dir, n_dir)


def _stat_expected_hit_rate_no_skill(totals: np.ndarray) -> np.ndarray:
    up = _stat_up_share(totals)
    n_bull = totals[..., _COL["n_bull"]]
    n_bear = totals[..., _COL["n_bear"]]
    n_dir = n_bull + n_bear
    numer = n_bull * up + n_bear * (1.0 - up)
    return _safe_div(numer, n_dir)


def _stat_edge(totals: np.ndarray) -> np.ndarray:
    return _stat_hit_rate(totals) - _stat_expected_hit_rate_no_skill(totals)


def _stat_directional_excess_return(totals: np.ndarray) -> np.ndarray:
    """Primary statistic (D5): direction-signed forward return in excess of
    the same unconditional-drift benchmark used for the hit-rate edge.

    Per observation this is `(fwd - mean_fwd_all)` for a BULLISH call and
    `(mean_fwd_all - fwd)` for a BEARISH call, so a positive value always
    means "the call was right, by more than drift alone would explain" --
    continuous instead of binary, so it does not inherit the hit rate's
    left-skew misreading problem.
    """
    mean_all = _stat_mean_fwd_all(totals)
    n_bull = totals[..., _COL["n_bull"]]
    n_bear = totals[..., _COL["n_bear"]]
    sum_bull = totals[..., _COL["sum_fwd_bull"]]
    sum_bear = totals[..., _COL["sum_fwd_bear"]]
    n_dir = n_bull + n_bear
    signed = (sum_bull - n_bull * mean_all) + (n_bear * mean_all - sum_bear)
    return _safe_div(signed, n_dir)


def _stat_bull_hit_rate(totals: np.ndarray) -> np.ndarray:
    return _safe_div(totals[..., _COL["hits_bull"]], totals[..., _COL["n_bull"]])


def _stat_bull_mean_fwd(totals: np.ndarray) -> np.ndarray:
    return _safe_div(totals[..., _COL["sum_fwd_bull"]], totals[..., _COL["n_bull"]])


def _stat_bull_edge(totals: np.ndarray) -> np.ndarray:
    return _stat_bull_hit_rate(totals) - _stat_up_share(totals)


def _stat_bear_hit_rate(totals: np.ndarray) -> np.ndarray:
    return _safe_div(totals[..., _COL["hits_bear"]], totals[..., _COL["n_bear"]])


def _stat_bear_mean_fwd(totals: np.ndarray) -> np.ndarray:
    return _safe_div(totals[..., _COL["sum_fwd_bear"]], totals[..., _COL["n_bear"]])


def _stat_bear_edge(totals: np.ndarray) -> np.ndarray:
    return _stat_bear_hit_rate(totals) - (1.0 - _stat_up_share(totals))


def _ci_from_stat(stat_fn, point_totals: np.ndarray, boot_totals: np.ndarray) -> Dict[str, Any]:
    """Point estimate plus a 95% percentile bootstrap interval for `stat_fn`."""
    point_val = float(stat_fn(point_totals))
    point = None if math.isnan(point_val) else round(point_val, 6)
    if boot_totals.shape[0] == 0:
        return {"point": point, "lo": None, "hi": None, "n_boot_valid": 0}
    vals = np.asarray(stat_fn(boot_totals), dtype=np.float64)
    vals = vals[~np.isnan(vals)]
    if vals.size == 0:
        return {"point": point, "lo": None, "hi": None, "n_boot_valid": 0}
    lo = float(np.percentile(vals, 2.5))
    hi = float(np.percentile(vals, 97.5))
    return {"point": point, "lo": round(lo, 6), "hi": round(hi, 6), "n_boot_valid": int(vals.size)}


def _summarise(
    rows: List[Dict[str, Any]],
    label: str,
    *,
    cost_bp: float = 0.0,
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = DEFAULT_SEED,
) -> Dict[str, Any]:
    directional = [o for o in rows if _hit(o) is not None]
    hits = [o for o in directional if _hit(o)]
    n = len(directional)

    # Base rate: how often ANY forward window in this period was positive.
    # Equities drift up, so a bullish call scores above 50% for free. Without
    # this comparison "BULLISH hits 54.7%" reads as skill when it is just the
    # market going up. Edge is measured against the base rate, not against 50%.
    up_share = (
        sum(1 for o in rows if o["forward_return"] > 0) / len(rows) if rows else None
    )

    by_direction: Dict[str, Any] = {}
    for d in ("BULLISH", "BEARISH"):
        sub = [o for o in directional if o["direction"] == d]
        if sub:
            hit_rate = sum(1 for o in sub if _hit(o)) / len(sub)
            # A bullish call's fair benchmark is the base rate; a bearish
            # call's is its complement.
            benchmark = up_share if d == "BULLISH" else (1 - up_share) if up_share is not None else None
            mean_fwd = statistics.fmean(o["forward_return"] for o in sub)
            by_direction[d] = {
                "n": len(sub),
                "hit_rate": round(hit_rate, 4),
                "benchmark": round(benchmark, 4) if benchmark is not None else None,
                "edge_vs_benchmark": round(hit_rate - benchmark, 4) if benchmark is not None else None,
                "mean_forward_return": round(mean_fwd, 5),
                # D4: net of round-trip cost.
                "mean_forward_return_net": round(mean_fwd - cost_bp / 10000.0, 5),
            }

    # Calibration: a higher stated probability should mean a higher hit rate.
    # If it does not, the number is decorative.
    calibration = []
    for lo, hi in PROB_BUCKETS:
        sub = [o for o in directional if lo <= o["probability_pct"] < hi]
        if len(sub) >= 20:
            calibration.append(
                {
                    "bucket": f"{lo}-{hi - 1}%",
                    "n": len(sub),
                    "hit_rate": round(sum(1 for o in sub if _hit(o)) / len(sub), 4),
                }
            )

    # D1: clustered bootstrap, applied to every headline statistic.
    dates_list, point_totals, boot_totals = _cluster_bootstrap(rows, n_boot=n_boot, seed=seed)
    hit_rate_ci = _ci_from_stat(_stat_hit_rate, point_totals, boot_totals)
    mean_fwd_ci = _ci_from_stat(_stat_mean_fwd_directional, point_totals, boot_totals)
    edge_ci = _ci_from_stat(_stat_edge, point_totals, boot_totals)
    excess_ci = _ci_from_stat(_stat_directional_excess_return, point_totals, boot_totals)

    if "BULLISH" in by_direction:
        by_direction["BULLISH"]["hit_rate_ci_clustered"] = _ci_from_stat(_stat_bull_hit_rate, point_totals, boot_totals)
        by_direction["BULLISH"]["mean_forward_return_ci_clustered"] = _ci_from_stat(_stat_bull_mean_fwd, point_totals, boot_totals)
        by_direction["BULLISH"]["edge_vs_benchmark_ci_clustered"] = _ci_from_stat(_stat_bull_edge, point_totals, boot_totals)
    if "BEARISH" in by_direction:
        by_direction["BEARISH"]["hit_rate_ci_clustered"] = _ci_from_stat(_stat_bear_hit_rate, point_totals, boot_totals)
        by_direction["BEARISH"]["mean_forward_return_ci_clustered"] = _ci_from_stat(_stat_bear_mean_fwd, point_totals, boot_totals)
        by_direction["BEARISH"]["edge_vs_benchmark_ci_clustered"] = _ci_from_stat(_stat_bear_edge, point_totals, boot_totals)

    mean_fwd_directional = statistics.fmean(o["forward_return"] for o in directional) if n else None

    return {
        "label": label,
        "observations": len(rows),
        "directional": n,
        "sideways": len(rows) - n,
        # Effective cluster count. This -- not `directional` -- is closer to
        # the true sample size the confidence interval rests on.
        "n_dates": len(dates_list),
        "hit_rate": round(len(hits) / n, 4) if n else None,
        "base_rate_up": round(up_share, 4) if up_share is not None else None,
        # What a skill-free caller would have scored, given the same mix of
        # bullish/bearish calls and this period's drift. This -- not 50% -- is
        # the number the engine has to beat.
        "expected_hit_rate_no_skill": (
            round(
                sum(
                    up_share if o["direction"] == "BULLISH" else (1.0 - up_share)
                    for o in directional
                )
                / n,
                4,
            )
            if n and up_share is not None
            else None
        ),
        # D1: the OLD binomial standard error. Kept, clearly labelled, for
        # comparison only -- it assumes every row is an independent draw.
        # It is not: consecutive reads for one symbol overlap most of their
        # forward window, and every symbol observed on the same date shares
        # that day's market move. Do not use this for the verdict; use
        # hit_rate_ci_clustered.
        "hit_rate_stderr": round(math.sqrt(0.25 / n), 4) if n else None,
        "hit_rate_stderr_caveat": (
            "naive binomial SE assuming independent rows -- understated for this "
            "data (overlap + same-day cross-section). See hit_rate_ci_clustered."
        ),
        "hit_rate_ci_clustered": hit_rate_ci,
        "mean_forward_return": round(mean_fwd_directional, 5) if n else None,
        "mean_forward_return_net": (
            round(mean_fwd_directional - cost_bp / 10000.0, 5) if n else None
        ),
        "mean_forward_return_ci_clustered": mean_fwd_ci,
        "edge_vs_benchmark_ci_clustered": edge_ci,
        # D5: primary reported statistic -- direction-signed excess return.
        "directional_excess_return": excess_ci["point"],
        "directional_excess_return_ci_clustered": excess_ci,
        "cost_bp_round_trip": cost_bp,
        "by_direction": by_direction,
        "calibration": calibration,
        "bootstrap": {
            "method": "cluster bootstrap: resample distinct as_of dates with replacement",
            "n_boot": n_boot,
            "seed": seed,
            "n_clusters": len(dates_list),
        },
    }


def _universe(limit: int, timeframe: str) -> List[str]:
    roots = [HOURLY_DIR] if timeframe in ("1h", "2h", "4h") else list(DAILY_DIRS)
    seen: List[str] = []
    for root in roots:
        if not Path(root).is_dir():
            continue
        for p in sorted(Path(root).glob("*.parquet")):
            sym = p.stem.upper()
            if sym not in seen:
                seen.append(sym)
            if len(seen) >= limit:
                return seen
    return seen


# ---------------------------------------------------------------------------
# D2. Time-based purge.
# ---------------------------------------------------------------------------

def _time_split(
    rows: List[Dict[str, Any]],
    all_dates: List[str],
    split_fraction: float,
    horizon: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int, Optional[str]]:
    """Chronological cut measured in TIME (distinct trading dates), with a
    proper embargo either side.

    An observation belongs to in-sample only if its entire forward window --
    `as_of` plus `horizon` bars, walked forward on the pooled distinct-date
    calendar -- resolves at or before the cut date. Out-of-sample begins only
    after an embargo of `horizon` trading dates past the cut. Everything in
    between is purged. This replaces dropping `horizon` pooled ROWS around the
    cut, which (with many symbols sharing each date) purged a fraction of a
    single trading day instead of an embargo.
    """
    n_dates = len(all_dates)
    if n_dates == 0:
        return [], [], 0, None
    cut_idx = min(n_dates - 1, max(0, int(n_dates * split_fraction)))
    cut_date = all_dates[cut_idx]
    date_idx = {d: i for i, d in enumerate(all_dates)}

    in_sample: List[Dict[str, Any]] = []
    out_sample: List[Dict[str, Any]] = []
    purged = 0
    for o in rows:
        i = date_idx.get(str(o["as_of"]))
        if i is None:
            purged += 1
            continue
        if i + horizon <= cut_idx:
            in_sample.append(o)
        elif i >= cut_idx + horizon:
            out_sample.append(o)
        else:
            purged += 1
    return in_sample, out_sample, purged, cut_date


# ---------------------------------------------------------------------------
# D3. Rolling origins.
# ---------------------------------------------------------------------------

def _origin_fractions(n_origins: int, primary_split: float) -> List[float]:
    """Expanding-window split fractions for rolling-origin evaluation.

    Spans `ORIGIN_FRACTION_RANGE`; `primary_split` is always included exactly
    (snapped onto the nearest generated point) so the single-origin view
    reported at the top level of `run_backtest` matches one of the origins.
    """
    n_origins = max(1, int(n_origins))
    if n_origins == 1:
        return [primary_split]
    lo, hi = ORIGIN_FRACTION_RANGE
    lo = min(lo, primary_split)
    hi = max(hi, primary_split)
    fracs = [lo + i * (hi - lo) / (n_origins - 1) for i in range(n_origins)]
    closest = min(range(n_origins), key=lambda i: abs(fracs[i] - primary_split))
    fracs[closest] = primary_split
    return sorted(fracs)


def _origin_verdict(oos_summary: Dict[str, Any]) -> str:
    """Per-origin verdict from the clustered CI on the primary statistic."""
    excess_ci = oos_summary.get("directional_excess_return_ci_clustered") or {}
    lo, hi, pt = excess_ci.get("lo"), excess_ci.get("hi"), excess_ci.get("point")
    if lo is not None and lo > 0:
        return "signal"
    if hi is not None and hi < 0:
        return "inverted"
    if pt is not None:
        return "no edge"
    return "inconclusive"


def _aggregate_origin_verdict(origin_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """D3: the verdict must be consistent across rolling origins, not rest on
    one. A result that appears at one origin and vanishes at the others is
    noise, and this function is what says so."""
    verdicts = [o["verdict"] for o in origin_results]
    n = len(verdicts)
    if n == 0:
        return {"verdict": "inconclusive", "notes": ["No origins evaluated."], "origin_verdicts": []}

    signal_n = verdicts.count("signal")
    inverted_n = verdicts.count("inverted")
    no_edge_n = verdicts.count("no edge")

    if signal_n == n:
        verdict = "signal"
        note = f"All {n} rolling origins independently show a significant edge in the same direction."
    elif inverted_n == n:
        verdict = "inverted"
        note = f"All {n} rolling origins independently show a significant edge OPPOSITE the engine's call direction."
    elif no_edge_n == n:
        verdict = "no measurable edge"
        note = f"None of the {n} rolling origins show an edge whose clustered CI excludes zero."
    else:
        verdict = "inconsistent across origins"
        note = (
            f"{signal_n}/{n} origins show signal, {inverted_n}/{n} show inversion, {no_edge_n}/{n} show no edge. "
            "A result that only shows up at some origins is noise, not a robust edge -- treat as no edge."
        )
    return {"verdict": verdict, "notes": [note], "origin_verdicts": verdicts}


def _origin_dispersion(origin_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    points = [
        (o["out_of_sample"].get("directional_excess_return_ci_clustered") or {}).get("point")
        for o in origin_results
    ]
    points = [p for p in points if p is not None]
    if len(points) < 2:
        return {"n_origins": len(origin_results), "note": "Fewer than 2 origins produced a usable estimate."}
    return {
        "n_origins": len(origin_results),
        "oos_directional_excess_return_by_origin": [round(p, 6) for p in points],
        "mean": round(statistics.fmean(points), 6),
        "stdev": round(statistics.pstdev(points), 6),
        "min": round(min(points), 6),
        "max": round(max(points), 6),
        "range": round(max(points) - min(points), 6),
    }


def run_backtest(
    symbols: Sequence[str],
    timeframe: str = "1D",
    horizon: int = 10,
    stride: int = 5,
    max_bars: int = 1200,
    split: float = 0.6,
    cost_bp: float = DEFAULT_COST_BP,
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = DEFAULT_SEED,
    n_origins: int = DEFAULT_N_ORIGINS,
    jobs: int = 1,
) -> Dict[str, Any]:
    """Walk history, then evaluate several rolling chronological IS/OOS cuts.

    `split` selects the single "primary" origin reported at the top level
    (`in_sample` / `out_of_sample` / `is_oos_hit_rate_gap`) for backward
    compatibility with existing consumers; the full rolling-origin picture is
    in `rolling_origins` / `rolling_origin_dispersion`, and the top-level
    `interpretation` verdict is driven by cross-origin consistency (D3), not
    by the primary origin alone.
    """
    rows, skipped = _collect_observations(symbols, timeframe, horizon, stride, max_bars, jobs=jobs)
    rows.sort(key=lambda o: str(o["as_of"]))
    if not rows:
        return {
            "error": "no observations produced",
            "symbols_requested": list(symbols),
            "symbols_skipped": skipped,
        }

    all_dates = sorted({str(o["as_of"]) for o in rows})

    origin_fracs = _origin_fractions(n_origins, split)
    origin_results: List[Dict[str, Any]] = []
    for i, frac in enumerate(origin_fracs):
        is_rows, oos_rows, purged, cut_date = _time_split(rows, all_dates, frac, horizon)
        is_s = _summarise(is_rows, "in-sample", cost_bp=cost_bp, n_boot=n_boot, seed=seed + i)
        oos_s = _summarise(oos_rows, "out-of-sample", cost_bp=cost_bp, n_boot=n_boot, seed=seed + 10_000 + i)
        origin_results.append(
            {
                "split_fraction": round(frac, 4),
                "split_date": cut_date,
                "purged_observations": purged,
                "in_sample": is_s,
                "out_of_sample": oos_s,
                "verdict": _origin_verdict(oos_s),
            }
        )

    origin_agg = _aggregate_origin_verdict(origin_results)
    origin_dispersion = _origin_dispersion(origin_results)

    # Primary origin = the one matching `split` (exact match: `_origin_fractions`
    # always snaps a generated point onto `split`).
    primary = min(origin_results, key=lambda o: abs(o["split_fraction"] - split))
    is_sum, oos_sum = primary["in_sample"], primary["out_of_sample"]

    gap = None
    if is_sum["hit_rate"] is not None and oos_sum["hit_rate"] is not None:
        gap = round(is_sum["hit_rate"] - oos_sum["hit_rate"], 4)

    return {
        "config": {
            "timeframe": timeframe,
            "horizon_bars": horizon,
            "stride_bars": stride,
            "max_bars_per_symbol": max_bars,
            "split_fraction": split,
            "split_date": primary["split_date"],
            "purged_observations": primary["purged_observations"],
            "purge_method": (
                f"time-based: an observation is in-sample only if its full forward window "
                f"(horizon={horizon} bars) resolves at or before the cut date; out-of-sample "
                f"begins only {horizon} trading dates after the cut date. Rows in between are dropped."
            ),
            "warmup_bars": MIN_WARMUP_BARS,
            "cost_bp_round_trip": cost_bp,
            "bootstrap_n": n_boot,
            "bootstrap_seed": seed,
            "n_origins": len(origin_fracs),
            "rolling_origin_fractions": [round(f, 4) for f in origin_fracs],
            "jobs": jobs,
        },
        "symbols_evaluated": sorted({o["symbol"] for o in rows}),
        "symbols_skipped": skipped,
        "in_sample": is_sum,
        "out_of_sample": oos_sum,
        "is_oos_hit_rate_gap": gap,
        "interpretation": _interpret(is_sum, oos_sum, gap, origin_agg),
        "rolling_origins": origin_results,
        "rolling_origin_dispersion": origin_dispersion,
    }


def _interpret(is_sum: Dict[str, Any], oos_sum: Dict[str, Any], gap: Optional[float], origin_agg: Dict[str, Any]) -> Dict[str, Any]:
    notes: List[str] = []

    oos_n = oos_sum["directional"]
    if oos_n < 100:
        notes.append(
            f"Only {oos_n} out-of-sample directional reads at the primary split; too few to conclude "
            "anything on their own. Widen the universe or shorten the stride."
        )

    # D1 + D5: primary statistic is the clustered CI on the direction-signed
    # excess return, not the naive-SE hit rate.
    excess_ci = oos_sum.get("directional_excess_return_ci_clustered") or {}
    pt, lo, hi = excess_ci.get("point"), excess_ci.get("lo"), excess_ci.get("hi")
    if pt is not None and lo is not None and hi is not None:
        notes.append(
            f"Primary split ({oos_sum['label']}): mean directional excess return {pt:+.4%} "
            f"[{lo:+.4%}, {hi:+.4%}] (95% cluster bootstrap over {oos_sum.get('n_dates')} distinct dates, "
            f"{oos_sum['bootstrap']['n_boot']} replicates, seed {oos_sum['bootstrap']['seed']})."
        )

    naive_se = oos_sum.get("hit_rate_stderr")
    clustered_hr = oos_sum.get("hit_rate_ci_clustered") or {}
    if naive_se is not None and clustered_hr.get("lo") is not None and clustered_hr.get("hi") is not None:
        width_naive = 2 * 1.96 * naive_se
        width_clustered = clustered_hr["hi"] - clustered_hr["lo"]
        if width_naive > 0:
            notes.append(
                f"Naive independent-row hit-rate SE implies a ~{width_naive:.1%}-wide 95% interval; the "
                f"clustered (whole-date) bootstrap gives a {width_clustered:.1%}-wide interval "
                f"({width_clustered / width_naive:.1f}x wider) once overlap and same-day cross-section "
                "are accounted for. Use the clustered figure."
            )

    # D3: cross-origin consistency drives the actual verdict.
    notes.extend(origin_agg.get("notes", []))
    verdict = origin_agg.get("verdict", "inconclusive")

    base = oos_sum.get("base_rate_up")
    if base is not None:
        notes.append(f"Base rate at the primary split: {base:.1%} of out-of-sample forward windows were positive.")

    if gap is not None and abs(gap) > 0.10:
        notes.append(
            f"In-sample beats out-of-sample hit rate by {gap:+.1%} at the primary split. The thresholds were "
            "set from qualitative rules rather than fitted here, so this points to regime "
            "fragility rather than curve-fitting -- but it is still a warning."
        )

    cal = oos_sum.get("calibration") or []
    if len(cal) >= 2:
        rates = [c["hit_rate"] for c in cal]
        if rates == sorted(rates):
            notes.append("Out-of-sample calibration is monotonic: higher stated probability did mean a higher hit rate.")
        else:
            notes.append(
                "Out-of-sample calibration is NOT monotonic -- a higher stated probability "
                "did not reliably mean a higher hit rate. Treat the percentage as a ranking "
                "of evidence weight only."
            )

    gross = oos_sum.get("mean_forward_return")
    net = oos_sum.get("mean_forward_return_net")
    if gross is not None and net is not None:
        notes.append(
            f"Gross mean forward return {gross:+.3%}; net of {oos_sum.get('cost_bp_round_trip')} bp "
            f"round-trip cost: {net:+.3%}."
        )

    notes.append(
        "Raw close-to-close returns (and their net-of-cost figures) measure signal quality, not "
        "tradeable P&L -- no slippage, borrow, or position sizing modelled."
    )
    return {"verdict": verdict, "notes": notes}


def main() -> None:
    ap = argparse.ArgumentParser(description="Walk-forward IS/OOS validation of the VPA engine.")
    ap.add_argument("--symbols", help="Comma-separated tickers.")
    ap.add_argument("--universe", type=int, default=0, help="Instead take the first N symbols on disk.")
    ap.add_argument("--timeframe", default="1D")
    ap.add_argument("--horizon", type=int, default=10, help="Forward bars used to score a read.")
    ap.add_argument("--stride", type=int, default=5, help="Bars between successive reads.")
    ap.add_argument("--max-bars", type=int, default=1200)
    ap.add_argument("--split", type=float, default=0.6, help="Fraction of history held as in-sample at the primary origin.")
    ap.add_argument("--cost-bp", type=float, default=DEFAULT_COST_BP, help="Round-trip transaction cost in bp, subtracted from gross mean returns.")
    ap.add_argument("--n-boot", type=int, default=DEFAULT_N_BOOT, help="Cluster-bootstrap replicates (resampling distinct as_of dates).")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Bootstrap RNG seed, for reproducibility.")
    ap.add_argument("--n-origins", type=int, default=DEFAULT_N_ORIGINS, help="Number of rolling (expanding-window) split origins.")
    ap.add_argument("--jobs", type=int, default=1, help="Parallel worker processes across symbols (each symbol is independent).")
    ap.add_argument("--json", help="Write the full report to this path.")
    args = ap.parse_args()

    if args.symbols:
        syms = [s.strip() for s in args.symbols.split(",") if s.strip()]
    elif args.universe:
        syms = _universe(args.universe, args.timeframe)
    else:
        ap.error("pass --symbols or --universe")

    report = run_backtest(
        syms,
        timeframe=args.timeframe,
        horizon=args.horizon,
        stride=args.stride,
        max_bars=args.max_bars,
        split=args.split,
        cost_bp=args.cost_bp,
        n_boot=args.n_boot,
        seed=args.seed,
        n_origins=args.n_origins,
        jobs=args.jobs,
    )

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))

    if "error" in report:
        print(json.dumps(report, indent=2))
        return

    cfg, is_s, oos = report["config"], report["in_sample"], report["out_of_sample"]
    print(
        f"VPA walk-forward  |  {cfg['timeframe']}  horizon={cfg['horizon_bars']}  "
        f"symbols={len(report['symbols_evaluated'])}  split={cfg['split_date']}  "
        f"cost={cfg['cost_bp_round_trip']}bp  n_boot={cfg['bootstrap_n']}  seed={cfg['bootstrap_seed']}"
    )
    print(f"{'':16}{'n':>7}{'dates':>7}{'hit':>9}{'se(naive)':>11}{'hit CI(cluster)':>20}{'mean fwd':>11}{'net fwd':>10}")
    for s in (is_s, oos):
        hr = f"{s['hit_rate']:.1%}" if s["hit_rate"] is not None else "—"
        se = f"±{s['hit_rate_stderr']:.1%}" if s["hit_rate_stderr"] is not None else "—"
        ci = s.get("hit_rate_ci_clustered") or {}
        ci_str = f"[{ci['lo']:.1%}, {ci['hi']:.1%}]" if ci.get("lo") is not None else "—"
        mf = f"{s['mean_forward_return']:+.2%}" if s["mean_forward_return"] is not None else "—"
        nf = f"{s['mean_forward_return_net']:+.2%}" if s.get("mean_forward_return_net") is not None else "—"
        print(f"{s['label']:16}{s['directional']:>7}{s['n_dates']:>7}{hr:>9}{se:>11}{ci_str:>20}{mf:>11}{nf:>10}")
    if report["is_oos_hit_rate_gap"] is not None:
        print(f"IS-OOS gap (primary origin): {report['is_oos_hit_rate_gap']:+.1%}")

    print("\nRolling origins:")
    for o in report["rolling_origins"]:
        oos_o = o["out_of_sample"]
        excess = oos_o.get("directional_excess_return_ci_clustered") or {}
        pt, lo, hi = excess.get("point"), excess.get("lo"), excess.get("hi")
        pt_s = f"{pt:+.3%}" if pt is not None else "—"
        ci_s = f"[{lo:+.3%}, {hi:+.3%}]" if lo is not None else "—"
        print(
            f"  split={o['split_fraction']:.2f} ({o['split_date']})  n_oos={oos_o['directional']:>5}  "
            f"excess_return={pt_s:>9} {ci_s:>22}  verdict={o['verdict']}"
        )
    disp = report.get("rolling_origin_dispersion") or {}
    if disp.get("stdev") is not None:
        print(f"Dispersion across origins: mean={disp['mean']:+.3%}  stdev={disp['stdev']:.3%}  range={disp['range']:.3%}")

    print(f"\nVerdict: {report['interpretation']['verdict']}")
    for n in report["interpretation"]["notes"]:
        print(f"  - {n}")


if __name__ == "__main__":
    main()
