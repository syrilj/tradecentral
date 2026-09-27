"""0DTE intraday tape — same-day option magnets read against the actual price bars.

Why this is a separate engine from `daily_plays.regime_attractor_engine`:

    That engine prices every strike with ``years = max(dte, 1.0) / 365``. For a
    swing horizon that is fine. For a contract that expires at today's close it
    is wrong in the one way that matters: a 0DTE option at 15:30 ET has ~30
    minutes of life, not a calendar day, and gamma goes as 1/sqrt(T). Pricing
    it at 1/365 understates ATM gamma by ~3x at the open and by an order of
    magnitude into the close, and -- worse -- makes it *constant* across the
    session, so the magnets never tighten. Watching them tighten is the whole
    point of trading 0DTE.

Everything here is computed from two real inputs and nothing else:

    bars   -- intraday OHLCV for the session (1m/5m), regular trading hours
    chain  -- the same-day expiry slice of the option chain

Time is measured in trading minutes to the 16:00 ET close and converted to
years over a 390-minute / 252-day year, so T shrinks as the session runs and
every gamma number below sharpens with it.

Positioning weight: for a same-day expiry, open interest is *yesterday's*
leftover and today's volume is what actually traded. Neither is dealer
inventory -- like the rest of this repo the sign convention here is the
industry charting one (calls positive, puts negative), not a claim about who
is long what. Both profiles are computed; `weight_basis` says which one drove
the levels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

__all__ = [
    "ZeroDteLevel",
    "LevelInteraction",
    "compute_zero_dte_tape",
    "gamma_regime",
    "session_minutes_remaining",
    "year_fraction_remaining",
    "rth_bars",
]

EXCHANGE_TZ = ZoneInfo("America/New_York")
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)
SESSION_MINUTES = 390.0
TRADING_DAYS = 252.0

# Gamma goes as 1/sqrt(T), so the last minutes of a 0DTE contract blow the
# scale up without adding information. Floor T at five minutes and say so in
# the payload rather than shipping a number that is only large because the
# clock ran out.
MIN_MINUTES_REMAINING = 5.0

_MULTIPLIER = 100.0


# ---------------------------------------------------------------------------
# Session clock


def _as_utc(ts: Any) -> datetime:
    """Coerce a bar timestamp to an aware UTC datetime (naive is read as UTC)."""
    if isinstance(ts, datetime):
        dt = ts
    else:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _session_close_utc(day: date) -> datetime:
    """16:00 America/New_York on `day`, in UTC -- DST-correct, not a fixed offset."""
    return datetime.combine(day, RTH_CLOSE, tzinfo=EXCHANGE_TZ).astimezone(timezone.utc)


def session_minutes_remaining(ts: Any, *, expiry: date | None = None) -> float:
    """Trading minutes from `ts` to the 16:00 ET close of the expiry session.

    Clamped to [0, SESSION_MINUTES]: before the open the whole session is
    ahead, after the close nothing is.
    """
    now = _as_utc(ts)
    day = expiry or now.astimezone(EXCHANGE_TZ).date()
    close = _session_close_utc(day)
    remaining = (close - now).total_seconds() / 60.0
    return max(0.0, min(SESSION_MINUTES, remaining))


def year_fraction_remaining(minutes: float, *, floor: bool = True) -> float:
    """Trading-minute clock as a year fraction: min / (390 * 252)."""
    m = max(minutes, MIN_MINUTES_REMAINING) if floor else max(minutes, 0.0)
    return m / (SESSION_MINUTES * TRADING_DAYS)


def rth_bars(bars: Sequence[Mapping[str, Any]], *, day: date | None = None) -> list[dict[str, Any]]:
    """Keep only regular-hours bars, optionally for one session, ordered by time.

    The feed carries 08:00-23:59 UTC. Extended-hours prints are thin enough
    that a wick there would fake a level touch, so they are dropped rather
    than blended in.
    """
    kept: list[dict[str, Any]] = []
    for b in bars:
        ts_raw = b.get("ts") or b.get("timestamp") or b.get("time") or b.get("t")
        if ts_raw is None:
            continue
        try:
            ts = _as_utc(ts_raw)
        except (ValueError, TypeError):
            continue
        local = ts.astimezone(EXCHANGE_TZ)
        if not (RTH_OPEN <= local.time() < RTH_CLOSE):
            continue
        if day is not None and local.date() != day:
            continue
        row = _normalize_bar(b, ts)
        if row is not None:
            kept.append(row)
    kept.sort(key=lambda r: r["ts"])
    return kept


def _normalize_bar(b: Mapping[str, Any], ts: datetime) -> dict[str, Any] | None:
    try:
        o = float(b.get("open", b.get("o")))
        h = float(b.get("high", b.get("h")))
        low = float(b.get("low", b.get("l")))
        c = float(b.get("close", b.get("c")))
        v = float(b.get("volume", b.get("v")) or 0.0)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(x) and x > 0 for x in (o, h, low, c)):
        return None
    if low > h:
        return None
    return {
        "ts": ts.isoformat(),
        "_ts": ts,
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "volume": max(0.0, v),
    }


# ---------------------------------------------------------------------------
# Chain -> gamma profile


def _row_field(row: Mapping[str, Any], *names: str) -> Any:
    for n in names:
        if n in row and row[n] is not None:
            return row[n]
    return None


def _option_right(row: Mapping[str, Any]) -> str | None:
    raw = _row_field(row, "right", "contract_type", "option_type", "type", "cp")
    s = str(raw or "").strip().lower()
    if s.startswith("c"):
        return "call"
    if s.startswith("p"):
        return "put"
    return None


def _bs_gamma(spot: float, strike: float, years: float, iv: float, rate: float) -> float | None:
    """Black-Scholes gamma phi(d1) / (S sigma sqrt(T))."""
    if spot <= 0 or strike <= 0 or years <= 0 or not 0.005 <= iv <= 5.0:
        return None
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * years) / (iv * root_t)
    return math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi) / (spot * iv * root_t)


def _dollar_gamma_1pct(weight: float, gamma: float, spot: float) -> float:
    """Dollar gamma for a 1% move: contracts * 100 * gamma * S^2 * 0.01."""
    if weight <= 0 or gamma <= 0 or spot <= 0:
        return 0.0
    return weight * _MULTIPLIER * gamma * (spot**2) * 0.01


def build_strike_profile(
    chain_rows: Sequence[Mapping[str, Any]],
    spot: float,
    years: float,
    *,
    rate: float = 0.045,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Per-strike call/put gamma notional under both weightings.

    Provider gamma is used when the feed carries it and re-derived from IV at
    the *live* time-to-expiry otherwise. Returns the profile plus a quality
    block recording which inputs were actually present.
    """
    by_strike: dict[float, dict[str, float]] = {}
    ivs_near_spot: list[float] = []
    provider_gamma_rows = 0
    derived_gamma_rows = 0
    iv_fallback_rows = 0
    total_oi = 0.0
    total_vol = 0.0

    # Pass one: a single usable volatility for this expiry.
    #
    # Some feeds quote a broken IV on one side of the book -- yfinance returns
    # 0.0 for most near-the-money SPX *calls* while its puts are fine. Dropping
    # those rows would hand back a profile built almost entirely from puts,
    # which is not a thin profile but a wrong one: the tilt and the flip would
    # both be artefacts of the gap. Borrowing the expiry's own at-the-money
    # volatility for those rows is a stated approximation instead of a silent
    # distortion, and `quality.iv_fallback_rows` reports how often it was used.
    fallback_iv = _expiry_atm_iv(chain_rows, spot)

    for row in chain_rows:
        right = _option_right(row)
        if right is None:
            continue
        try:
            strike = float(_row_field(row, "strike", "strike_price", "k"))
        except (TypeError, ValueError):
            continue
        if strike <= 0:
            continue

        try:
            iv = float(_row_field(row, "iv", "impliedVolatility", "implied_volatility") or 0.0)
        except (TypeError, ValueError):
            iv = 0.0
        iv = max(0.0, min(5.0, iv))

        try:
            oi = max(0.0, float(_row_field(row, "openInterest", "open_interest", "oi") or 0.0))
        except (TypeError, ValueError):
            oi = 0.0
        try:
            vol = max(
                0.0, float(_row_field(row, "volume_today", "volume", "vol", "day_volume") or 0.0)
            )
        except (TypeError, ValueError):
            vol = 0.0

        # Provider gamma is quoted at the provider's own asof. Re-deriving from
        # IV at our clock is what makes the level sharpen through the session,
        # so prefer the derived value whenever IV is usable and fall back to
        # the quoted one only when it is not.
        iv_used = iv
        if iv_used < 0.005 and fallback_iv is not None:
            iv_used = fallback_iv
            iv_fallback_rows += 1

        gamma = _bs_gamma(spot, strike, years, iv_used, rate) if iv_used >= 0.005 else None
        if gamma is not None:
            derived_gamma_rows += 1
        else:
            try:
                gamma = float(_row_field(row, "gamma") or 0.0) or None
            except (TypeError, ValueError):
                gamma = None
            if gamma is not None:
                provider_gamma_rows += 1
        if gamma is None or gamma <= 0:
            continue

        if abs(strike - spot) <= max(0.01 * spot, 1.0) and iv >= 0.005:
            ivs_near_spot.append(iv)

        slot = by_strike.setdefault(
            strike,
            {
                "call_oi": 0.0,
                "put_oi": 0.0,
                "call_vol": 0.0,
                "put_vol": 0.0,
                "call_gex_oi": 0.0,
                "put_gex_oi": 0.0,
                "call_gex_vol": 0.0,
                "put_gex_vol": 0.0,
            },
        )
        gex_oi = _dollar_gamma_1pct(oi, gamma, spot)
        gex_vol = _dollar_gamma_1pct(vol, gamma, spot)
        slot[f"{right}_oi"] += oi
        slot[f"{right}_vol"] += vol
        slot[f"{right}_gex_oi"] += gex_oi
        slot[f"{right}_gex_vol"] += gex_vol
        total_oi += oi
        total_vol += vol

    profile: list[dict[str, Any]] = []
    for k in sorted(by_strike):
        s = by_strike[k]
        profile.append(
            {
                "strike": k,
                "call_oi": s["call_oi"],
                "put_oi": s["put_oi"],
                "call_volume": s["call_vol"],
                "put_volume": s["put_vol"],
                "call_gex_oi_m": s["call_gex_oi"] / 1e6,
                "put_gex_oi_m": s["put_gex_oi"] / 1e6,
                "net_gex_oi_m": (s["call_gex_oi"] - s["put_gex_oi"]) / 1e6,
                "call_gex_vol_m": s["call_gex_vol"] / 1e6,
                "put_gex_vol_m": s["put_gex_vol"] / 1e6,
                "net_gex_vol_m": (s["call_gex_vol"] - s["put_gex_vol"]) / 1e6,
                "abs_gex_oi_m": (s["call_gex_oi"] + s["put_gex_oi"]) / 1e6,
                "abs_gex_vol_m": (s["call_gex_vol"] + s["put_gex_vol"]) / 1e6,
            }
        )

    atm_iv = sorted(ivs_near_spot)[len(ivs_near_spot) // 2] if ivs_near_spot else None
    quality = {
        "strikes": len(profile),
        "open_interest_available": total_oi > 0,
        "volume_available": total_vol > 0,
        "total_open_interest": total_oi,
        "total_volume": total_vol,
        "atm_iv": atm_iv,
        "gamma_derived_rows": derived_gamma_rows,
        "gamma_provider_rows": provider_gamma_rows,
        "iv_fallback_rows": iv_fallback_rows,
    }
    return profile, quality


def _expiry_atm_iv(chain_rows: Sequence[Mapping[str, Any]], spot: float) -> float | None:
    """Median usable implied vol nearest the money, across both rights.

    Widened in steps so a book that only quotes sensibly further out still
    yields a number, rather than falling back to a hardcoded volatility that
    would be a guess dressed as data.
    """
    if spot <= 0:
        return None
    scored: list[tuple[float, float]] = []
    for row in chain_rows:
        try:
            k = float(_row_field(row, "strike", "strike_price", "k"))
            v = float(_row_field(row, "iv", "impliedVolatility", "implied_volatility") or 0.0)
        except (TypeError, ValueError):
            continue
        if k > 0 and 0.005 <= v <= 5.0:
            scored.append((abs(k - spot) / spot, v))
    if not scored:
        return None
    for width in (0.01, 0.02, 0.05, 1.0):
        band = [v for d, v in scored if d <= width]
        if len(band) >= 3:
            return _median(band)
    return _median([v for _, v in scored])


def _gamma_flip(
    profile: Sequence[Mapping[str, Any]],
    key: str,
    abs_key: str,
    spot: float,
    *,
    max_distance: float | None = None,
) -> float | None:
    """Zero crossing of the per-strike net GEX curve, nearest spot, interpolated.

    Two guards that a longer-dated flip does not need. As T goes to zero on a
    same-day expiry, gamma collapses onto the at-the-money strikes and the
    wings go numerically flat, so a bare "nearest sign change" happily returns
    a strike 140 points away built out of rounding dust. So: only cross where
    both bracketing strikes carry real gamma mass, and only within a plausible
    distance of spot.
    """
    rows = list(profile)
    if len(rows) < 2:
        return None
    peak = max(abs(float(r[abs_key])) for r in rows) or 0.0
    if peak <= 0:
        return None
    floor = peak * 0.01  # a strike below 1% of the heaviest carries no signal
    limit = max_distance if (max_distance and max_distance > 0) else spot * 0.02

    crossings: list[float] = []
    for r1, r2 in zip(rows, rows[1:]):
        k1, g1, m1 = float(r1["strike"]), float(r1[key]), abs(float(r1[abs_key]))
        k2, g2, m2 = float(r2["strike"]), float(r2[key]), abs(float(r2[abs_key]))
        if m1 < floor or m2 < floor:
            continue
        if g1 == 0.0:
            x = k1
        elif (g1 < 0 < g2) or (g2 < 0 < g1):
            denom = abs(g1) + abs(g2)
            if denom <= 1e-12:
                continue
            x = k1 + (abs(g1) / denom) * (k2 - k1)
        else:
            continue
        if abs(x - spot) <= limit:
            crossings.append(x)

    if not crossings:
        return None
    return round(min(crossings, key=lambda x: abs(x - spot)), 2)


def _max_pain(profile: Sequence[Mapping[str, Any]], oi_key: tuple[str, str]) -> float | None:
    """Strike minimising total in-the-money payout to holders."""
    call_key, put_key = oi_key
    strikes = [float(r["strike"]) for r in profile]
    if len(strikes) < 3:
        return None
    best: tuple[float, float] | None = None
    for settle in strikes:
        pain = 0.0
        for r in profile:
            k = float(r["strike"])
            if settle > k:
                pain += (settle - k) * float(r[call_key]) * _MULTIPLIER
            if settle < k:
                pain += (k - settle) * float(r[put_key]) * _MULTIPLIER
        if best is None or pain < best[1]:
            best = (settle, pain)
    return best[0] if best else None


# ---------------------------------------------------------------------------
# Levels and their pull


@dataclass(frozen=True)
class LevelInteraction:
    """How the actual bars have behaved around one level, this session."""

    touches: int
    rejections: int
    closes_through: int
    bars_inside_band: int
    minutes_inside_band: float
    accept_ratio: float
    bars_since_touch: int | None
    approach_rate_per_min: float | None
    eta_minutes: float | None
    band: float
    verdict: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "touches": self.touches,
            "rejections": self.rejections,
            "closes_through": self.closes_through,
            "bars_inside_band": self.bars_inside_band,
            "minutes_inside_band": round(self.minutes_inside_band, 1),
            "accept_ratio": round(self.accept_ratio, 4),
            "bars_since_touch": self.bars_since_touch,
            "approach_rate_per_min": (
                round(self.approach_rate_per_min, 4)
                if self.approach_rate_per_min is not None
                else None
            ),
            "eta_minutes": round(self.eta_minutes, 1) if self.eta_minutes is not None else None,
            "band": round(self.band, 3),
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class ZeroDteLevel:
    kind: str
    label: str
    price: float
    spot: float
    pull: float
    components: dict[str, float]
    gex_at_strike_m: float | None
    interaction: LevelInteraction | None = None
    rank: int = 0
    note: str = ""
    confluence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        dist = self.price - self.spot
        return {
            "kind": self.kind,
            "label": self.label,
            "price": round(self.price, 2),
            "distance_pts": round(dist, 2),
            "distance_pct": round(dist / self.spot * 100.0, 3) if self.spot else None,
            "direction": "above" if dist > 0 else ("below" if dist < 0 else "at_spot"),
            "pull": round(self.pull, 1),
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "gex_at_strike_m": (
                round(self.gex_at_strike_m, 3) if self.gex_at_strike_m is not None else None
            ),
            "rank": self.rank,
            "note": self.note,
            "confluence": list(self.confluence),
            "lens_count": len(self.confluence) or 1,
            "interaction": self.interaction.to_dict() if self.interaction else None,
        }


# Relative authority of each level kind, before proximity and mass are applied.
_KIND_WEIGHT = {
    "gamma_flip": 1.00,
    "pin": 0.95,
    "call_wall": 0.90,
    "put_wall": 0.90,
    "max_pain": 0.75,
    "prior_close": 0.55,
    "session_open": 0.50,
    "vwap": 0.70,
}

_KIND_LABEL = {
    "gamma_flip": "Gamma flip",
    "pin": "Gamma pin",
    "call_wall": "Call wall",
    "put_wall": "Put wall",
    "max_pain": "Max pain",
    "prior_close": "Prior close",
    "session_open": "Session open",
    "vwap": "Session VWAP",
}


def expected_move(spot: float, atm_iv: float | None, years: float) -> float | None:
    """Remaining-session expected move: S * sigma * sqrt(T).

    This is the yardstick that makes 0DTE pull behave correctly. With 30
    minutes and 12% IV left on SPY at 770 it is about $1.60, so a magnet five
    dollars away is correctly scored as out of reach -- which a daily-scale
    expected move would not do.
    """
    if spot <= 0 or years <= 0 or not atm_iv or atm_iv <= 0:
        return None
    return spot * atm_iv * math.sqrt(years)


def gravitational_pull(
    level_price: float,
    spot: float,
    kind: str,
    *,
    em: float | None,
    mass_share: float,
) -> tuple[float, dict[str, float]]:
    """Pull score in [0, 100] from proximity (in expected moves) and gamma mass.

    Proximity uses a Gaussian in units of the *remaining* expected move, so the
    same level scores lower at 15:45 than it did at 10:00 unless price has come
    to meet it. Mass is the strike's share of session gamma notional.
    """
    if spot <= 0 or level_price <= 0:
        return 0.0, {"proximity": 0.0, "mass": 0.0}
    scale = em if (em and em > 0) else spot * 0.004
    d = abs(level_price - spot) / scale
    proximity = math.exp(-0.5 * d * d)
    mass = max(0.0, min(1.0, mass_share))
    weight = _KIND_WEIGHT.get(kind, 0.6)
    score = 100.0 * weight * (0.55 * proximity + 0.45 * mass)
    return (
        max(0.0, min(100.0, score)),
        {"proximity": proximity, "mass": mass, "kind_weight": weight, "distance_em": d},
    )


def _median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def measure_interaction(
    bars: Sequence[Mapping[str, Any]],
    level: float,
    *,
    bar_minutes: float,
    band: float | None = None,
    lookback: int = 30,
) -> LevelInteraction | None:
    """Count what the bars actually did at `level` -- touches, wicks, acceptance.

    The band is half a median bar range, so "at the level" means what it means
    on this symbol at this volatility rather than a hardcoded number of cents.
    """
    if not bars or level <= 0:
        return None
    ranges = [float(b["high"]) - float(b["low"]) for b in bars]
    tol = band if band is not None else max(_median(ranges) * 0.5, level * 1e-4)

    touches = rejections = closes_through = inside = 0
    last_touch_idx: int | None = None
    prev_close: float | None = None

    for i, b in enumerate(bars):
        hi, lo, c = float(b["high"]), float(b["low"]), float(b["close"])
        rng = max(hi - lo, 1e-9)
        if lo <= level <= hi:
            touches += 1
            last_touch_idx = i
            # A wick through that closes back by more than half the bar is the
            # level holding, not price passing through it.
            if abs(c - level) > 0.5 * rng:
                rejections += 1
        if abs(c - level) <= tol:
            inside += 1
        if prev_close is not None and (prev_close - level) * (c - level) < 0:
            closes_through += 1
        prev_close = c

    tail = list(bars[-lookback:])
    approach_rate: float | None = None
    eta: float | None = None
    if len(tail) >= 3:
        dists = [abs(float(b["close"]) - level) for b in tail]
        n = len(dists)
        mean_x = (n - 1) / 2.0
        mean_y = sum(dists) / n
        num = sum((i - mean_x) * (d - mean_y) for i, d in enumerate(dists))
        den = sum((i - mean_x) ** 2 for i in range(n))
        if den > 0:
            slope_per_bar = num / den
            approach_rate = slope_per_bar / max(bar_minutes, 1e-9)
            if slope_per_bar < 0:
                eta = dists[-1] / abs(approach_rate) if approach_rate else None

    n_bars = len(bars)
    accept_ratio = inside / n_bars if n_bars else 0.0
    if touches and rejections / touches >= 0.6 and (approach_rate or 0.0) > 0:
        verdict = "rejected"
    elif accept_ratio >= 0.25:
        verdict = "accepted"
    elif approach_rate is not None and approach_rate < 0:
        verdict = "converging"
    elif approach_rate is not None and approach_rate > 0:
        verdict = "diverging"
    else:
        verdict = "idle"

    return LevelInteraction(
        touches=touches,
        rejections=rejections,
        closes_through=closes_through,
        bars_inside_band=inside,
        minutes_inside_band=inside * bar_minutes,
        accept_ratio=accept_ratio,
        bars_since_touch=(n_bars - 1 - last_touch_idx) if last_touch_idx is not None else None,
        approach_rate_per_min=approach_rate,
        eta_minutes=eta,
        band=tol,
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# What the tape is trying to do


def session_vwap(bars: Sequence[Mapping[str, Any]]) -> float | None:
    """Volume-weighted average price over the session bars."""
    num = den = 0.0
    for b in bars:
        v = float(b.get("volume") or 0.0)
        if v <= 0:
            continue
        typical = (float(b["high"]) + float(b["low"]) + float(b["close"])) / 3.0
        num += typical * v
        den += v
    return num / den if den > 0 else None


def _velocity(bars: Sequence[Mapping[str, Any]], n: int, bar_minutes: float) -> float | None:
    """Signed price drift over the last `n` bars, in dollars per minute."""
    tail = list(bars[-n:])
    if len(tail) < 2:
        return None
    span = (len(tail) - 1) * max(bar_minutes, 1e-9)
    return (float(tail[-1]["close"]) - float(tail[0]["close"])) / span


def gamma_regime(spot: float, flip: float | None) -> tuple[str, str]:
    """Regime from where spot sits relative to the flip.

    Deliberately *not* the sign of aggregate net GEX. That aggregate is a
    charting convention (calls positive, puts negative) and its sign is
    unstable for a same-day expiry: as T shrinks, gamma concentrates on the
    at-the-money strike, so the whole sum can change sign through the session
    off an unchanged chain. Which side of the flip price is on is the stable
    statement, and it is the one traders actually use.
    """
    if flip is None or spot <= 0:
        return "unmeasured", "No gamma flip in this expiry's strike range; no regime read."
    if spot > flip:
        return (
            "above_flip",
            f"Spot is above the {flip:.2f} flip, in the call-gamma zone: hedging "
            "flows lean against moves, so fades and pins are the base case.",
        )
    if spot < flip:
        return (
            "below_flip",
            f"Spot is below the {flip:.2f} flip, in the put-gamma zone: hedging "
            "flows lean with moves, so breaks tend to extend rather than fade.",
        )
    return "at_flip", f"Spot is sitting on the {flip:.2f} flip - the regime pivot itself."


def classify_intent(
    bars: Sequence[Mapping[str, Any]],
    primary: ZeroDteLevel | None,
    *,
    gamma_state: str,
    gamma_note: str,
    bar_minutes: float,
    minutes_left: float,
    clock_is_live: bool = True,
) -> dict[str, Any]:
    """Read what price is trying to do against its dominant magnet.

    Deliberately conservative: every branch below is reachable only from
    counted bar behaviour plus the regime. When the evidence is thin the state
    is `unresolved`, not a guess.
    """

    if primary is None or primary.interaction is None or len(bars) < 5:
        return {
            "state": "unresolved",
            "headline": "Not enough session bars to read intent yet.",
            "gamma_state": gamma_state,
            "gamma_note": gamma_note,
            "target": None,
            "evidence": [],
        }

    ix = primary.interaction
    fast = _velocity(bars, 10, bar_minutes)
    slow = _velocity(bars, 30, bar_minutes)
    spot = float(bars[-1]["close"])
    gap = primary.price - spot
    evidence: list[str] = []

    if ix.touches:
        evidence.append(
            f"{ix.touches} bar{'s' if ix.touches != 1 else ''} touched {primary.label.lower()} "
            f"at {primary.price:.2f}, {ix.rejections} closed back away"
        )
    if ix.bars_inside_band:
        evidence.append(
            f"{ix.minutes_inside_band:.0f} min held inside +/-{ix.band:.2f} of it "
            f"({ix.accept_ratio * 100:.0f}% of the session)"
        )
    if ix.eta_minutes is not None:
        # The remaining-minutes clause only means something when these bars are
        # the expiry session's. Off-session it would be a countdown to a close
        # that already happened.
        tail = f" with {minutes_left:.0f} min left" if clock_is_live else ""
        evidence.append(
            f"closing on it at {abs(ix.approach_rate_per_min or 0):.3f}/min "
            f"-> {ix.eta_minutes:.0f} min away{tail}"
        )
    if fast is not None:
        evidence.append(f"last 10 bars drifting {fast:+.3f}/min")

    reachable = ix.eta_minutes is not None and (
        not clock_is_live or ix.eta_minutes <= minutes_left
    )

    if ix.verdict == "accepted" and abs(fast or 0.0) < (ix.band / max(bar_minutes, 1)) * 0.5:
        state = "pinning"
        headline = (
            f"Pinning {primary.label.lower()} {primary.price:.2f} - price keeps returning to it "
            f"and is not leaving on current drift."
        )
    elif ix.verdict == "converging" and reachable:
        state = "magnetized"
        headline = (
            f"Being pulled to {primary.label.lower()} {primary.price:.2f} "
            f"({gap:+.2f} away, ~{ix.eta_minutes:.0f} min at this pace)."
        )
    elif ix.verdict == "rejected":
        state = "rejected"
        headline = (
            f"{primary.label} {primary.price:.2f} is holding - "
            f"{ix.rejections} of {ix.touches} touches wicked and closed back."
        )
    elif ix.verdict == "diverging" and gamma_state == "below_flip":
        state = "escaping"
        headline = (
            f"Leaving {primary.label.lower()} {primary.price:.2f} from below the flip - "
            f"hedging flows extend this rather than fade it."
        )
    elif ix.verdict == "diverging":
        state = "drifting_off"
        headline = f"Drifting away from {primary.label.lower()} {primary.price:.2f}."
    else:
        state = "ranging"
        headline = f"No clean pull to {primary.label.lower()} {primary.price:.2f} yet."

    if slow is not None and fast is not None and abs(fast) > 2.0 * abs(slow) and abs(slow) > 0:
        evidence.append("short-horizon drift is running about twice the session pace")

    return {
        "state": state,
        "headline": headline,
        "gamma_state": gamma_state,
        "gamma_note": gamma_note,
        "target": {"price": round(primary.price, 2), "label": primary.label, "gap": round(gap, 2)},
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# Orchestrator


def compute_zero_dte_tape(
    symbol: str,
    bars: Sequence[Mapping[str, Any]],
    chain_rows: Sequence[Mapping[str, Any]],
    *,
    expiry: date | str | None = None,
    asof: Any = None,
    rate: float = 0.045,
    bar_minutes: float = 1.0,
    spot_override: float | None = None,
) -> dict[str, Any]:
    """Full 0DTE read: session bars, same-day magnets, their pull, and intent.

    `chain_rows` must already be the same-day expiry slice. `bars` may be a
    full multi-day feed; the session traded on `expiry` is selected from it.
    """
    sym = symbol.upper()
    warnings: list[str] = []

    exp_date: date | None
    if isinstance(expiry, str):
        exp_date = date.fromisoformat(expiry[:10])
    else:
        exp_date = expiry

    session = rth_bars(bars, day=exp_date)
    session_is_expiry_day = bool(session) or exp_date is None
    if not session and bars:
        # No bars on the expiry date itself (pre-open, holiday, or a chain
        # whose front expiry is a future session). Fall back to the most
        # recent complete session so the surface still shows real bars, and
        # say plainly that they are not the expiry session's.
        all_rth = rth_bars(bars)
        if all_rth:
            last_day = _as_utc(all_rth[-1]["_ts"]).astimezone(EXCHANGE_TZ).date()
            session = [
                b
                for b in all_rth
                if _as_utc(b["_ts"]).astimezone(EXCHANGE_TZ).date() == last_day
            ]
            session_is_expiry_day = exp_date is None or last_day == exp_date
            if exp_date and last_day != exp_date:
                warnings.append(
                    f"No bars for the {exp_date} expiry session; showing the "
                    f"{last_day} session instead. Levels are the {exp_date} chain's."
                )

    if not session:
        return {
            "symbol": sym,
            "measurable": False,
            "reason": "no regular-hours bars available",
            "warnings": warnings,
            "bars": [],
            "levels": [],
        }

    # Truncate at `asof`. Without this an intraday read scores its levels
    # against bars that had not printed yet -- the whole surface would be
    # lookahead, and every backtest of it would flatter itself.
    if asof is not None:
        cutoff = _as_utc(asof)
        truncated = [b for b in session if b["_ts"] <= cutoff]
        if truncated:
            session = truncated
        elif session:
            warnings.append(
                "Requested asof precedes the first session bar; showing the session "
                "from its open."
            )
            session = session[:1]

    last_bar = session[-1]
    spot = float(spot_override) if (spot_override and spot_override > 0) else float(
        last_bar["close"]
    )
    asof_ts = asof or last_bar["_ts"]
    minutes_left = session_minutes_remaining(asof_ts, expiry=exp_date)
    floored = minutes_left < MIN_MINUTES_REMAINING
    years = year_fraction_remaining(minutes_left)

    profile, quality = build_strike_profile(chain_rows, spot, years, rate=rate)
    if not profile:
        return {
            "symbol": sym,
            "measurable": False,
            "reason": "same-day expiry chain carried no usable strikes",
            "warnings": warnings,
            "bars": [_public_bar(b) for b in session],
            "levels": [],
        }

    use_volume = bool(quality["volume_available"]) and quality["total_volume"] > 0
    weight_basis = "volume" if use_volume else "open_interest"
    if not use_volume and not quality["open_interest_available"]:
        return {
            "symbol": sym,
            "measurable": False,
            "reason": "chain carried neither volume nor open interest",
            "warnings": warnings,
            "bars": [_public_bar(b) for b in session],
            "levels": [],
        }
    if not use_volume:
        warnings.append(
            "Same-day expiry carried no traded volume; levels are weighted by "
            "open interest, which for a 0DTE contract is the prior close's."
        )

    sfx = "vol" if use_volume else "oi"
    net_key, abs_key = f"net_gex_{sfx}_m", f"abs_gex_{sfx}_m"
    call_key, put_key = f"call_gex_{sfx}_m", f"put_gex_{sfx}_m"

    total_call = sum(float(r[call_key]) for r in profile)
    total_put = sum(float(r[put_key]) for r in profile)
    total_abs = (total_call + total_put) or 1e-9
    tilt = (total_call - total_put) / total_abs
    above_share = sum(float(r[abs_key]) for r in profile if r["strike"] > spot) / total_abs
    atm_iv = quality["atm_iv"]
    em = expected_move(spot, atm_iv, years)

    flip = _gamma_flip(
        profile, net_key, abs_key, spot, max_distance=max(3.0 * em, spot * 0.01) if em else None
    )
    calls_above = [r for r in profile if r["strike"] > spot and r[call_key] > 0]
    puts_below = [r for r in profile if r["strike"] < spot and r[put_key] > 0]
    call_wall = max(calls_above, key=lambda r: r[call_key])["strike"] if calls_above else None
    put_wall = max(puts_below, key=lambda r: r[put_key])["strike"] if puts_below else None
    pin = max(profile, key=lambda r: r[abs_key])["strike"]
    pain = _max_pain(
        profile,
        ("call_volume", "put_volume") if use_volume else ("call_oi", "put_oi"),
    )
    vwap = session_vwap(session)

    by_strike = {float(r["strike"]): r for r in profile}

    def mass_at(price: float) -> tuple[float, float | None]:
        row = min(profile, key=lambda r: abs(float(r["strike"]) - price))
        if abs(float(row["strike"]) - price) > max(0.01 * spot, 1.0):
            return 0.0, None
        return float(row[abs_key]) / total_abs, float(row[net_key])

    candidates: list[tuple[str, float | None]] = [
        ("gamma_flip", flip),
        ("pin", pin),
        ("call_wall", call_wall),
        ("put_wall", put_wall),
        ("max_pain", pain),
        ("vwap", vwap),
    ]

    levels: list[ZeroDteLevel] = []
    for kind, price in candidates:
        if price is None or price <= 0:
            continue
        if kind == "vwap":
            # VWAP is a bar statistic, not a strike. Snapping it to the nearest
            # strike would credit it with gamma it does not own.
            mass, gex_m = 0.0, None
        else:
            mass, gex_m = mass_at(float(price))
        pull, comps = gravitational_pull(float(price), spot, kind, em=em, mass_share=mass)
        levels.append(
            ZeroDteLevel(
                kind=kind,
                label=_KIND_LABEL.get(kind, kind),
                price=float(price),
                spot=spot,
                pull=pull,
                components=comps,
                gex_at_strike_m=gex_m,
                interaction=measure_interaction(
                    session, float(price), bar_minutes=bar_minutes
                ),
                note=_level_note(kind, weight_basis),
            )
        )

    levels = _merge_colocated(levels, spot)
    levels.sort(key=lambda lv: lv.pull, reverse=True)
    levels = [ZeroDteLevel(**{**lv.__dict__, "rank": i + 1}) for i, lv in enumerate(levels)]
    primary = levels[0] if levels else None

    gstate, gnote = gamma_regime(spot, flip)
    intent = classify_intent(
        session,
        primary,
        gamma_state=gstate,
        gamma_note=gnote,
        bar_minutes=bar_minutes,
        minutes_left=minutes_left,
        clock_is_live=session_is_expiry_day,
    )

    if floored:
        warnings.append(
            f"Under {MIN_MINUTES_REMAINING:.0f} minutes to the close; time to expiry is "
            "floored, so gamma is a lower bound on the real number."
        )
    if exp_date and minutes_left <= 0:
        warnings.append("The expiry session has already closed; this is a post-mortem read.")

    return {
        "symbol": sym,
        "measurable": True,
        "asof_utc": _as_utc(asof_ts).isoformat(),
        "expiry": exp_date.isoformat() if exp_date else None,
        "spot": round(spot, 2),
        "session": {
            "bar_minutes": bar_minutes,
            "bars_shown": len(session),
            "minutes_remaining": round(minutes_left, 1),
            "clock_is_live": session_is_expiry_day,
            "years_remaining": years,
            "open": round(float(session[0]["open"]), 2),
            "high": round(max(float(b["high"]) for b in session), 2),
            "low": round(min(float(b["low"]) for b in session), 2),
            "vwap": round(vwap, 2) if vwap else None,
            "volume": sum(float(b["volume"]) for b in session),
        },
        "gamma": {
            "weight_basis": weight_basis,
            "flip": flip,
            "state": gstate,
            "state_note": gnote,
            "tilt": round(tilt, 4),
            "tilt_note": (
                "Share of same-day gamma sitting in calls minus puts, from -1 to +1. "
                "Scale-free on purpose: the dollar aggregate is not quotable here "
                "because gamma is taken at the remaining life while the weights are "
                "the whole day's volume, so its magnitude means little even though "
                "its shape across strikes does."
            ),
            "above_spot_share": round(above_share, 4),
            "atm_iv": round(atm_iv, 4) if atm_iv else None,
            "expected_move": round(em, 2) if em else None,
            "expected_move_note": (
                "One standard deviation of the remaining session, S*sigma*sqrt(T)."
            ),
            "convention": (
                "Charting convention: calls positive, puts negative. Not a claim "
                "about dealer inventory."
            ),
        },
        "levels": [lv.to_dict() for lv in levels],
        "strike_profile": [
            {
                "strike": r["strike"],
                "call_gex_m": round(float(r[call_key]), 4),
                "put_gex_m": round(float(r[put_key]), 4),
                "net_gex_m": round(float(r[net_key]), 4),
                "call_contracts": r["call_volume"] if use_volume else r["call_oi"],
                "put_contracts": r["put_volume"] if use_volume else r["put_oi"],
            }
            for r in profile
            if abs(float(r["strike"]) - spot) <= max(0.03 * spot, 5.0)
        ],
        "intent": intent,
        "quality": quality,
        "warnings": warnings,
        "bars": [_public_bar(b) for b in session],
    }


def _merge_colocated(levels: list[ZeroDteLevel], spot: float) -> list[ZeroDteLevel]:
    """Collapse levels sitting on the same price into one, stronger, level.

    On a 0DTE chain the pin, the put wall and max pain routinely land on the
    same strike. Listing that strike three times reads as three separate
    magnets when it is really one -- and an unusually well-supported one. Merge
    them, keep the highest-authority label, and record the others as
    confluence with a modest boost per extra lens.
    """
    if not levels:
        return []
    tol = max(spot * 0.0005, 0.05)
    ordered = sorted(levels, key=lambda lv: lv.price)
    groups: list[list[ZeroDteLevel]] = [[ordered[0]]]
    for lv in ordered[1:]:
        if abs(lv.price - groups[-1][-1].price) <= tol:
            groups[-1].append(lv)
        else:
            groups.append([lv])

    merged: list[ZeroDteLevel] = []
    for g in groups:
        lead = max(g, key=lambda lv: _KIND_WEIGHT.get(lv.kind, 0.0))
        if len(g) == 1:
            merged.append(lead)
            continue
        kinds = tuple(sorted({lv.kind for lv in g}, key=lambda k: -_KIND_WEIGHT.get(k, 0.0)))
        boost = 1.0 + 0.10 * (len(kinds) - 1)
        others = ", ".join(_KIND_LABEL.get(k, k).lower() for k in kinds if k != lead.kind)
        merged.append(
            ZeroDteLevel(
                kind=lead.kind,
                label=lead.label,
                price=lead.price,
                spot=lead.spot,
                pull=min(100.0, lead.pull * boost),
                components={**lead.components, "confluence_boost": boost},
                gex_at_strike_m=lead.gex_at_strike_m,
                interaction=lead.interaction,
                note=f"{lead.note} Also {others} at this price.",
                confluence=kinds,
            )
        )
    return merged


def _public_bar(b: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ts": b["ts"],
        "open": round(float(b["open"]), 2),
        "high": round(float(b["high"]), 2),
        "low": round(float(b["low"]), 2),
        "close": round(float(b["close"]), 2),
        "volume": float(b["volume"]),
    }


def _level_note(kind: str, basis: str) -> str:
    src = "today's traded volume" if basis == "volume" else "prior-close open interest"
    return {
        "gamma_flip": f"Sign change in net gamma across strikes, from {src}.",
        "pin": f"Strike carrying the most gamma notional, from {src}.",
        "call_wall": f"Heaviest call gamma above spot, from {src}.",
        "put_wall": f"Heaviest put gamma below spot, from {src}.",
        "max_pain": f"Settlement minimising total payout, from {src}.",
        "vwap": "Session volume-weighted average price, from the bars themselves.",
    }.get(kind, "")
