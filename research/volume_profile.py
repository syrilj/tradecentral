"""Volume-price analysis (PREDATION_TAB_SPEC.md section 2.7).

An independent, non-parametric read on "where U is" that doesn't depend on
the Carlin/Lobo/Viswanathan impact-decomposition estimate in
predatory_liquidity.py: build a volume profile over the pre-event window,
find the point of control (POC) and value area, and use the low-volume node
below current price as a second guess at where the bottom prints. Pure
computation, no I/O -- callers hand this an in-memory OHLCV DataFrame.

Session volume is spread across every price bin its [low, high] range
touches, weighted by a triangular kernel peaked at that session's close (more
of the day's business is assumed to have happened near where it settled than
at the wick extremes). The spread is computed via the triangular
distribution's closed-form CDF evaluated at each bin edge, so per-bin shares
fall out of a single vectorised `diff` -- no numerical integration, no
double-counting, and volume is conserved exactly (each session's weights sum
to 1, degenerate cases included).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("low", "high", "close", "volume")


def _triangular_cdf(x: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    """CDF of a triangular distribution on [a, b] (a < b) with mode c, a <= c <= b.

    Degenerates cleanly to a one-sided ramp when c == a or c == b (a session
    whose close sits right at its low or high) -- see the branch guards
    below, which avoid the 0/0 that formula would otherwise hit.
    """
    x = np.clip(np.asarray(x, dtype=float), a, b)
    left_span = c - a
    right_span = b - c
    left_val = np.zeros_like(x)
    if left_span > 0:
        left_val = (x - a) ** 2 / ((b - a) * left_span)
    right_val = np.ones_like(x)
    if right_span > 0:
        right_val = 1.0 - (b - x) ** 2 / ((b - a) * right_span)
    return np.where(x <= c, left_val, right_val)


def _session_bin_shares(low: float, high: float, close: float, edges: np.ndarray) -> np.ndarray:
    """Fraction of one session's volume landing in each profile bin.

    `edges` spans the whole profile's price range (length = bins + 1), which
    always contains [low, high], so the triangular CDF is 0 at edges[0] and 1
    at edges[-1] and the per-bin `diff` sums to exactly 1.
    """
    n = len(edges) - 1
    if high <= low:
        # Zero-range bar (or degenerate/bad OHLC): all volume goes to the
        # single bin containing that price. Right-inclusive on the last bin
        # to match how build_profile itself treats the top edge.
        idx = int(np.searchsorted(edges, low, side="right")) - 1
        idx = min(max(idx, 0), n - 1)
        shares = np.zeros(n)
        shares[idx] = 1.0
        return shares
    close = min(max(close, low), high)  # guard against inconsistent OHLC input
    cdf_at_edges = _triangular_cdf(edges, low, high, close)
    shares = np.diff(cdf_at_edges)
    shares = np.clip(shares, 0.0, None)
    total = shares.sum()
    if total > 0:
        shares = shares / total  # numerical-safety renormalisation
    return shares


def build_profile(ohlcv_df: pd.DataFrame, bins: int = 50) -> dict:
    """Volume profile over the given OHLCV window.

    `ohlcv_df` needs `low`/`high`/`close`/`volume` columns; row order doesn't
    matter (this is a cross-sectional histogram over the window, not a
    time series). Returns
    ``{"bins": [{price_lo, price_hi, volume, is_poc, in_value_area}, ...],
    "poc": float, "vah": float, "val": float}``.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in ohlcv_df.columns]
    if missing:
        raise ValueError(f"build_profile: missing required column(s) {missing}")
    if ohlcv_df.empty:
        raise ValueError("build_profile: ohlcv_df has no rows")

    lo_all = float(ohlcv_df["low"].min())
    hi_all = float(ohlcv_df["high"].max())

    if hi_all <= lo_all:
        # Every bar in the window collapsed to (or never left) a single
        # price -- there's no range to bin. One bin holding all the volume
        # is the honest answer, not a 50-bin grid of width-zero slivers.
        price = lo_all
        total_vol = float(ohlcv_df["volume"].fillna(0.0).clip(lower=0).sum())
        bin_records = [{
            "price_lo": price, "price_hi": price, "volume": total_vol,
            "is_poc": True, "in_value_area": True,
        }]
        return {"bins": bin_records, "poc": price, "vah": price, "val": price}

    edges = np.linspace(lo_all, hi_all, bins + 1)
    bin_volumes = np.zeros(bins)

    for row in ohlcv_df.itertuples():
        low, high, close, vol = float(row.low), float(row.high), float(row.close), float(row.volume)
        if not (np.isfinite(low) and np.isfinite(high) and np.isfinite(close) and np.isfinite(vol)):
            continue
        if vol <= 0:
            continue
        bin_volumes += _session_bin_shares(low, high, close, edges) * vol

    bin_records = [
        {
            "price_lo": float(edges[i]),
            "price_hi": float(edges[i + 1]),
            "volume": float(bin_volumes[i]),
            "is_poc": False,
            "in_value_area": False,
        }
        for i in range(bins)
    ]

    poc_idx = int(np.argmax(bin_volumes))  # first occurrence wins on ties, like value_area's own POC search
    bin_records[poc_idx]["is_poc"] = True
    poc_price = (bin_records[poc_idx]["price_lo"] + bin_records[poc_idx]["price_hi"]) / 2.0

    val, vah = value_area(bin_records, coverage=0.70)
    for b in bin_records:
        # val/vah are literally the price_lo/price_hi of bins in this same
        # list (see value_area), so this is an exact, not epsilon, compare.
        b["in_value_area"] = b["price_lo"] >= val and b["price_hi"] <= vah

    return {"bins": bin_records, "poc": poc_price, "vah": vah, "val": val}


def value_area(bins: list[dict], coverage: float = 0.70) -> tuple[float, float]:
    """Smallest contiguous band of bins around the POC holding >= `coverage`
    of total volume -- the standard "expand from POC" heuristic, not a
    percentile approximation.

    Starting from the POC bin, repeatedly pull in whichever open neighbour
    (one step below the current band, one step above) carries more volume,
    until the band's cumulative share clears `coverage`. Ties alternate which
    side is preferred, starting with the upper neighbour, so a symmetric
    profile expands into a band centred on the POC instead of drifting to
    one side. Returns `(val, vah)`: the low edge of the lowest bin in the
    band and the high edge of the highest.
    """
    n = len(bins)
    if n == 0:
        raise ValueError("value_area: bins is empty")

    volumes = [float(b["volume"]) for b in bins]
    total = sum(volumes)
    poc_idx = max(range(n), key=lambda i: volumes[i])  # first occurrence wins on ties

    threshold = coverage * total
    lo_idx = hi_idx = poc_idx
    cum = volumes[poc_idx]
    prefer_above = True
    while cum < threshold and (lo_idx > 0 or hi_idx < n - 1):
        below = volumes[lo_idx - 1] if lo_idx > 0 else float("-inf")
        above = volumes[hi_idx + 1] if hi_idx < n - 1 else float("-inf")
        take_above = above > below or (above == below and prefer_above)
        if take_above:
            hi_idx += 1
            cum += above
        else:
            lo_idx -= 1
            cum += below
        prefer_above = not prefer_above

    return float(bins[lo_idx]["price_lo"]), float(bins[hi_idx]["price_hi"])


def lvn_below(bins: list[dict], price: float) -> float | None:
    """Midpoint of the lowest-volume bin entirely at/below `price` -- the air
    pocket price would travel through fast on the way down. None if no bin
    qualifies (price is at or below the bottom of the profile). Ties broken
    toward the lower-price bin (first in `bins`, which is price-ascending)."""
    below = [b for b in bins if float(b["price_hi"]) <= price]
    if not below:
        return None
    lvn = min(below, key=lambda b: float(b["volume"]))
    return (float(lvn["price_lo"]) + float(lvn["price_hi"])) / 2.0


def agreement(settle: float, val: float, vah: float, price_now: float) -> str:
    """Cross-check between the impact-model settle target and the volume
    profile's value area -- two independent reads on "where U is" agreeing is
    the confidence signal (spec section 2.7)."""
    if val <= settle <= vah:
        return "confirms"
    if settle < val and price_now > vah:
        return "conflicts"
    if settle > vah and price_now < val:
        return "conflicts"
    return "neutral"
