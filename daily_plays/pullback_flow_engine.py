"""Quantitative Pullback & Institutional Options Flow Engine for TradeCentral Daily Plays.

Scans the equity universe for two-sided chart-plus-options-structure setups:

- ``pullback_bounce`` (long call): healthy pullback in an established uptrend
  with an RSI reset, trend support, and dominant call flow.
- ``breakdown_roll`` (long put): extended or failed-bounce structure rolling
  over beneath the mean with dominant put flow and a call-wall ceiling.

Both sleeves consume the same institutional options evidence (Put/Call ratios,
Call/Put Walls, Max Pain, ATM IV) and produce sized, policy-gated tickets for
the Plays tab.  This engine is a transparent technical-screen heuristic, never
a calibrated model: confidence provenance stays ``unavailable`` so no decision
can masquerade as model-endorsed.

Quote honesty: legs carry the *snapshot capture* timestamp from the cached
chain (``captured_utc``), never the run clock.  Greeks are Black-Scholes
values derived from the provider's cached IV when plausible, and absent
otherwise.  A leg cut from a chain snapshot that is not today's is gated out
of ENTER (``chain_snapshot_not_current``) instead of being presented as live.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date, datetime, timezone
import glob
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .clock import RunContext
from .config import DailyPlaysConfig
from .options_calculator import black_scholes

# Single source of truth for engine provenance stamped into run manifests,
# /api/plays payloads, and the dashboard engine badge.
PULLBACK_FLOW_ENGINE_NAME = "pullback_flow_engine"
PULLBACK_FLOW_ENGINE_VERSION = "3.3.0"


def load_price_data(symbol: str, root_dir: str | Path = ".") -> pd.DataFrame | None:
    root = Path(root_dir)
    candidates = [
        root / "data" / "1d" / f"{symbol}.parquet",
        root / "data" / "1d_wide" / f"{symbol}.parquet",
        root / "data" / "1d_smallcap" / f"{symbol}.parquet",
        root / "edge" / "data" / "1d" / f"{symbol}.parquet",
        root / "edge" / "data" / "1d_wide" / f"{symbol}.parquet",
    ]
    for c in candidates:
        if c.is_file():
            try:
                df = pd.read_parquet(c)
                df.columns = [col.lower() for col in df.columns]
                if "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.sort_values("date").reset_index(drop=True)
                return df
            except Exception:
                continue
    return None


def load_latest_option_chain(
    symbol: str, root_dir: str | Path = "."
) -> tuple[pd.DataFrame | None, str | None]:
    root = Path(root_dir)
    patterns = [
        str(root / "data" / "option_chains" / "date=*"),
        str(root / "edge" / "data" / "option_chains" / "date=*"),
    ]
    date_dirs: list[str] = []
    for pat in patterns:
        date_dirs.extend(glob.glob(pat))
    date_dirs = sorted(date_dirs, reverse=True)

    for d in date_dirs:
        path = os.path.join(d, f"{symbol}.parquet")
        if os.path.exists(path):
            try:
                df = pd.read_parquet(path)
                return df, os.path.basename(d)
            except Exception:
                continue
    return None, None


def _chain_capture_time(df_chain: pd.DataFrame) -> datetime | None:
    """Snapshot capture time from the cached chain; never the run clock.

    The capture stamp is what makes these legs honest: they are reference
    quotes from a stored snapshot, and their age must be measurable against
    the moment the snapshot was taken, not against whenever this scan ran.
    """
    if df_chain is None or df_chain.empty:
        return None
    column = "captured_utc" if "captured_utc" in df_chain.columns else None
    if column is None:
        for candidate in df_chain.columns:
            if str(candidate).lower() in {"captured_utc", "capture_utc", "asof_utc"}:
                column = candidate
                break
    if column is None:
        return None
    values = pd.to_datetime(df_chain[column], errors="coerce", utc=True).dropna()
    if values.empty:
        return None
    # One snapshot per file; the median tolerates a stray malformed stamp.
    # floor('s') avoids a noisy nanosecond-truncation UserWarning on pyarrow
    # timestamps while keeping the stamp second-precise.
    values = values.dt.floor("s")
    stamp = values.median()
    parsed = stamp.to_pydatetime() if hasattr(stamp, "to_pydatetime") else None
    if parsed is None or parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def calculate_technical_profile(df: pd.DataFrame | None) -> dict[str, Any] | None:
    if df is None or len(df) < 20:
        return None

    close = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2]) if len(df) > 1 else close
    close_5d = float(df["close"].iloc[-5]) if len(df) >= 5 else float(df["close"].iloc[0])
    close_20d = float(df["close"].iloc[-20]) if len(df) >= 20 else float(df["close"].iloc[0])

    high_20 = float(df["high"].tail(20).max() if "high" in df else df["close"].tail(20).max())
    low_20 = float(df["low"].tail(20).min() if "low" in df else df["close"].tail(20).min())
    high_50 = float(df["high"].tail(50).max() if "high" in df else df["close"].tail(50).max())
    low_50 = float(df["low"].tail(50).min() if "low" in df else df["close"].tail(50).min())

    ema_9 = float(df["close"].ewm(span=9, adjust=False).mean().iloc[-1])
    ema_21 = float(df["close"].ewm(span=21, adjust=False).mean().iloc[-1])
    sma_50 = float(df["close"].rolling(50).mean().iloc[-1]) if len(df) >= 50 else ema_21
    sma_200 = float(df["close"].rolling(200).mean().iloc[-1]) if len(df) >= 200 else None

    # RSI 14
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    rsi = float((100 - (100 / (1 + rs))).iloc[-1])

    # ATR 14
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift()).abs()
    tr3 = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])

    pct_1d = ((close - prev_close) / prev_close) * 100
    pct_5d = ((close - close_5d) / close_5d) * 100
    pullback_20d = ((close - high_20) / high_20) * 100

    # Pivot points & Support / Resistance
    high_recent = float(df["high"].tail(10).max() if "high" in df else high_20)
    low_recent = float(df["low"].tail(10).min() if "low" in df else low_20)
    pivot = (high_recent + low_recent + close) / 3.0
    r1 = (2 * pivot) - low_recent
    s1 = (2 * pivot) - high_recent
    r2 = pivot + (high_recent - low_recent)
    s2 = pivot - (high_recent - low_recent)
    r3 = high_recent + 2 * (pivot - low_recent)
    s3 = low_recent - 2 * (high_recent - pivot)

    return {
        "close": close,
        "prev_close": prev_close,
        "pct_1d": pct_1d,
        "pct_5d": pct_5d,
        "high_20d": high_20,
        "low_20d": low_20,
        "pullback_20d": pullback_20d,
        "ema_9": ema_9,
        "ema_21": ema_21,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "rsi": rsi,
        "atr": atr,
        "pivot": pivot,
        "r1": r1,
        "r2": r2,
        "r3": r3,
        "s1": s1,
        "s2": s2,
        "s3": s3,
        "recent_high": high_recent,
        "recent_low": low_recent,
    }


def _bs_greeks_for_leg(
    *,
    spot_price: float,
    strike: float,
    dte: float,
    right: str,
    iv: float | None,
) -> dict[str, float | None]:
    """Black-Scholes delta/gamma/theta/charm from the provider's cached IV.

    Missing or implausible IV yields ``None`` fields rather than a plausible-
    looking default: an unmeasured Greek stays unmeasured.
    """
    greeks: dict[str, float | None] = {"delta": None, "gamma": None, "theta": None, "charm": None}
    if iv is None or not 0.05 <= iv <= 3.0:
        return greeks
    years = max(0.0, float(dte)) / 365.0
    if years < 1.0 / 365.0 or spot_price <= 0 or strike <= 0:
        return greeks
    try:
        priced = black_scholes(
            spot=spot_price, strike=strike, years=years, rate=0.045, vol=float(iv), right=right
        )
    except Exception:
        return greeks
    is_call = right == "call"
    greeks["delta"] = round(float(priced["delta"]), 4)
    greeks["gamma"] = round(float(priced["gamma"]), 6)
    greeks["theta"] = round(float(priced["theta"]), 4)
    # Charm (∂Δ/∂t per day) mirrors the Drift view's convention; reuse the same
    # closed form so the two surfaces can never disagree about one contract.
    root_t = math.sqrt(years)
    rate = 0.045
    d1 = (math.log(spot_price / strike) + (rate + 0.5 * iv * iv) * years) / (iv * root_t)
    d2 = d1 - iv * root_t
    density = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    charm_year = -density * (d1 / (2.0 * years) + (-d2 / (iv * years) + 2.0 * rate / iv) * 0.5)
    if not is_call:
        pass  # with q = 0 charm is identical for calls and puts
    greeks["charm"] = round(charm_year / 365.0, 6)
    return greeks


def _build_leg(
    row: Mapping[str, Any],
    *,
    right: str,
    target_exp: str,
    exp_col: str,
    spot_price: float,
    chain_capture: datetime | None,
    provider_label: str,
    fallback_iv: float,
) -> dict[str, Any] | None:
    """Build a policy-ready leg from one chain row without inventing quote data."""
    bid_raw = pd.to_numeric(pd.Series([row.get("bid")]), errors="coerce").iloc[0]
    ask_raw = pd.to_numeric(pd.Series([row.get("ask")]), errors="coerce").iloc[0]
    last_raw = pd.to_numeric(
        pd.Series([row.get("lastprice") if "lastprice" in row else row.get("lastPrice", 0.0)]),
        errors="coerce",
    ).iloc[0]
    bid = float(bid_raw) if pd.notna(bid_raw) else 0.0
    ask = float(ask_raw) if pd.notna(ask_raw) else 0.0
    last = float(last_raw) if pd.notna(last_raw) else 0.0
    mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else (last if last > 0 else 0.0)
    spread_pct = ((ask - bid) / mid) if (mid > 0 and ask >= bid >= 0) else None
    occ_sym = str(
        row.get("contractsymbol") or row.get("contractSymbol") or row.get("occ_symbol") or ""
    )
    try:
        dte_val = int(float(row.get("dte")))
    except (TypeError, ValueError):
        return None
    strike = float(row.get("strike"))
    volume_val = int(
        pd.to_numeric(pd.Series([row.get("volume")]), errors="coerce").fillna(0).iloc[0]
    )
    oi_val = int(
        pd.to_numeric(
            pd.Series(
                [row.get("openinterest") if "openinterest" in row else row.get("openInterest", 0)]
            ),
            errors="coerce",
        )
        .fillna(0)
        .iloc[0]
    )
    iv_val = pd.to_numeric(
        pd.Series(
            [
                row.get("impliedvolatility")
                if "impliedvolatility" in row
                else row.get("impliedVolatility")
            ]
        ),
        errors="coerce",
    )
    iv_float = float(iv_val.iloc[0]) if pd.notna(iv_val.iloc[0]) else None
    greeks = _bs_greeks_for_leg(
        spot_price=spot_price,
        strike=strike,
        dte=dte_val,
        right=right,
        iv=iv_float,
    )
    underlying = str(row.get("symbol") or "").upper()
    return {
        "side": "buy",
        "right": right,
        "occ_symbol": occ_sym,
        "underlying": underlying,
        "expiry": target_exp,
        "dte": dte_val,
        "strike": strike,
        "multiplier": 100,
        # A missing NBBO half must stay missing; the liquidity gate rejects it
        # downstream instead of the engine substituting a synthetic price.
        "bid": bid if bid > 0 else None,
        "ask": ask if ask > 0 else None,
        "mid": round(mid, 2) if mid > 0 else None,
        "spread_pct": round(spread_pct, 4) if spread_pct is not None else None,
        "volume": volume_val,
        "open_interest": oi_val,
        "quote_asof_utc": (
            chain_capture.isoformat().replace("+00:00", "Z") if chain_capture else None
        ),
        "provider": provider_label,
        "iv": round(iv_float, 4)
        if iv_float is not None
        else round(fallback_iv, 4)
        if fallback_iv > 0
        else None,
        "delta": greeks["delta"],
        "gamma": greeks["gamma"],
        "theta": greeks["theta"],
        "charm": greeks["charm"],
    }


def analyze_options_gex_fast(
    df_chain: pd.DataFrame | None,
    spot_price: float,
    *,
    dte_min: int = 30,
    dte_max: int = 60,
    asof_date: date | None = None,
    min_open_interest: int = 0,
    min_volume: int = 0,
) -> dict[str, Any] | None:
    if df_chain is None or df_chain.empty:
        return None

    chain = df_chain.copy()
    chain.columns = [c.lower() for c in chain.columns]

    if "right" in chain.columns:
        chain["right_norm"] = (
            chain["right"]
            .astype(str)
            .str.lower()
            .map({"c": "call", "p": "put", "call": "call", "put": "put"})
            .fillna("call")
        )
    elif "type" in chain.columns:
        chain["right_norm"] = (
            chain["type"]
            .astype(str)
            .str.lower()
            .map({"c": "call", "p": "put", "call": "call", "put": "put"})
            .fillna("call")
        )
    else:
        chain["right_norm"] = "call"

    vol_col = "volume" if "volume" in chain.columns else None
    oi_col = (
        "openinterest"
        if "openinterest" in chain.columns
        else ("open_interest" if "open_interest" in chain.columns else None)
    )
    iv_col = (
        "impliedvolatility"
        if "impliedvolatility" in chain.columns
        else ("iv" if "iv" in chain.columns else None)
    )

    chain["vol"] = pd.to_numeric(chain[vol_col], errors="coerce").fillna(0) if vol_col else 0.0
    chain["oi"] = pd.to_numeric(chain[oi_col], errors="coerce").fillna(0) if oi_col else 0.0
    chain["iv"] = pd.to_numeric(chain[iv_col], errors="coerce").fillna(0) if iv_col else 0.0
    chain["strike"] = pd.to_numeric(chain["strike"], errors="coerce").fillna(0.0)

    total_call_vol = float(chain[chain["right_norm"] == "call"]["vol"].sum())
    total_put_vol = float(chain[chain["right_norm"] == "put"]["vol"].sum())
    total_call_oi = float(chain[chain["right_norm"] == "call"]["oi"].sum())
    total_put_oi = float(chain[chain["right_norm"] == "put"]["oi"].sum())

    pcr_vol = (total_put_vol / total_call_vol) if total_call_vol > 0 else 1.0
    pcr_oi = (total_put_oi / total_call_oi) if total_call_oi > 0 else 1.0

    calls = (
        chain[chain["right_norm"] == "call"]
        .groupby("strike")
        .agg({"vol": "sum", "oi": "sum"})
        .reset_index()
    )
    puts = (
        chain[chain["right_norm"] == "put"]
        .groupby("strike")
        .agg({"vol": "sum", "oi": "sum"})
        .reset_index()
    )

    call_wall = (
        float(calls.loc[calls["oi"].idxmax()]["strike"])
        if not calls.empty and calls["oi"].max() > 0
        else None
    )
    put_wall = (
        float(puts.loc[puts["oi"].idxmax()]["strike"])
        if not puts.empty and puts["oi"].max() > 0
        else None
    )
    top_call_vol_strike = (
        float(calls.loc[calls["vol"].idxmax()]["strike"])
        if not calls.empty and calls["vol"].max() > 0
        else None
    )
    top_put_vol_strike = (
        float(puts.loc[puts["vol"].idxmax()]["strike"])
        if not puts.empty and puts["vol"].max() > 0
        else None
    )

    # Vectorized fast max pain
    call_vals = chain[chain["right_norm"] == "call"][["strike", "oi"]].values
    put_vals = chain[chain["right_norm"] == "put"][["strike", "oi"]].values
    all_strikes = np.unique(chain["strike"].values)
    all_strikes = all_strikes[all_strikes > 0]

    if len(all_strikes) > 0 and (len(call_vals) > 0 or len(put_vals) > 0):
        losses = []
        for k in all_strikes:
            c_l = (
                np.sum(np.maximum(0.0, k - call_vals[:, 0]) * call_vals[:, 1])
                if len(call_vals) > 0
                else 0.0
            )
            p_l = (
                np.sum(np.maximum(0.0, put_vals[:, 0] - k) * put_vals[:, 1])
                if len(put_vals) > 0
                else 0.0
            )
            losses.append(c_l + p_l)
        max_pain = float(all_strikes[np.argmin(losses)])
    else:
        max_pain = spot_price

    # Expiry selection within the policy DTE window (default 30-60 DTE for
    # swing trades).  Aligning the picker to the same window the leg-validation
    # gate enforces prevents every short-dated expiry from being selected only
    # to fail validation with "dte_outside_policy_window".  DTE is measured
    # against the caller's run clock (or the snapshot's own date), never
    # datetime.now(), so a replayed snapshot stays deterministic.
    #
    # Among in-window expiries, prefer the one whose near-spot contracts show
    # real liquidity: a wide market on the nearest date should route the scan
    # to a deeper expiry inside the same window, not fail the whole symbol.
    exp_col = (
        "expiry"
        if "expiry" in chain.columns
        else ("expiration" if "expiration" in chain.columns else None)
    )
    today = asof_date or date.today()
    target_exp = None
    target_iv = None

    def _expiry_liquidity(sub_frame: Any) -> float:
        """Best (lowest) near-spot spread across an expiry; inf when unquoted."""
        bids = pd.to_numeric(sub_frame.get("bid"), errors="coerce")
        asks = pd.to_numeric(sub_frame.get("ask"), errors="coerce")
        mids = (bids + asks) / 2.0
        spreads = (asks - bids) / mids.where(mids > 0)
        near = sub_frame.iloc[(sub_frame["strike"] - spot_price).abs().argsort()[:8]]
        near_spreads = spreads.loc[near.index].dropna()
        return float(near_spreads.min()) if not near_spreads.empty else float("inf")

    if exp_col:
        window_rows: list[tuple[float, str]] = []
        for e in sorted(chain[exp_col].dropna().unique()):
            try:
                ed = datetime.strptime(str(e)[:10], "%Y-%m-%d").date()
                dte = (ed - today).days
            except Exception:
                continue
            if not dte_min <= dte <= dte_max:
                continue
            sub = chain[chain[exp_col] == e]
            if sub.empty:
                continue
            window_rows.append((_expiry_liquidity(sub), str(e)[:10]))
        if window_rows:
            _, target_exp = min(window_rows)
        elif len(exps_in_window := [str(e)[:10] for e in sorted(chain[exp_col].dropna().unique())]):
            # Fall back to the nearest in-window expiry if none fall inside the
            # policy window, so the engine still reports a chain snapshot
            # rather than silently dropping the symbol.  The leg-validation
            # gate will then honestly record the dte_outside_policy_window
            # failure.
            all_exps = exps_in_window or []
            target_exp = str(all_exps[0])[:10] if all_exps else None
        if target_exp:
            sub = chain[chain[exp_col].astype(str).str.startswith(target_exp)]
            atm_contracts = sub.iloc[(sub["strike"] - spot_price).abs().argsort()[:4]]
            median_iv = pd.to_numeric(atm_contracts["iv"], errors="coerce").median()
            target_iv = float(median_iv) if pd.notna(median_iv) else None

    iv_est = target_iv if (target_iv and target_iv > 0.05 and target_iv < 5.0) else 0.45
    implied_1w_move = spot_price * iv_est * math.sqrt(7.0 / 365.0)
    implied_30d_move = spot_price * iv_est * math.sqrt(30.0 / 365.0)

    # Candidate legs: prefer the most liquid contract near the target
    # moneyness instead of blindly taking the nearest strike.  A liquidity-
    # aware rank (policy floors first, then spread, then distance to the
    # ~1% OTM call / ~2% OTM put targets) mirrors how the main pipeline's
    # select_directional_contract evaluates every contract rather than one.
    def _leg_liquidity_key(rows: Any, otm_target: float) -> Any:
        frame = rows.copy()
        bid_num = pd.to_numeric(frame.get("bid"), errors="coerce").fillna(0.0)
        ask_num = pd.to_numeric(frame.get("ask"), errors="coerce").fillna(0.0)
        mid_num = (bid_num + ask_num) / 2.0
        with np.errstate(divide="ignore", invalid="ignore"):
            spread_num = np.where(mid_num > 0, (ask_num - bid_num) / mid_num, np.inf)
        oi_num = pd.to_numeric(frame.get("oi"), errors="coerce").fillna(0.0)
        vol_num = pd.to_numeric(frame.get("vol"), errors="coerce").fillna(0.0)
        distance = (frame["strike"] - otm_target).abs()
        return pd.DataFrame(
            {
                "spread": spread_num,
                "distance": distance,
                "oi": oi_num.values,
                "vol": vol_num.values,
                "has_quote": ((bid_num > 0) & (ask_num >= bid_num)).values,
            }
        )

    best_call_leg = None
    best_put_leg = None
    chain_capture = _chain_capture_time(df_chain)
    provider_label = "TradeCentral GEX Engine"
    if target_exp and exp_col:
        sub_calls = chain[(chain[exp_col] == target_exp) & (chain["right_norm"] == "call")].copy()
        if not sub_calls.empty:
            ranked = _leg_liquidity_key(sub_calls, spot_price * 1.01)
            # Contracts that already satisfy the policy floors win outright;
            # among them, tightest spread then moneyness.  Only when nothing
            # passes the floors does the picker fall back to spread/distance
            # alone, so the downstream gate reports the true failure.
            liquid = ranked[(ranked["oi"] >= min_open_interest) & (ranked["vol"] >= min_volume)]
            pool = liquid if not liquid.empty else ranked
            order = pool.sort_values(["spread", "distance"], kind="stable").index
            best_row = sub_calls.loc[order[0]]
            best_call_leg = _build_leg(
                best_row,
                right="call",
                target_exp=target_exp,
                exp_col=exp_col,
                spot_price=spot_price,
                chain_capture=chain_capture,
                provider_label=provider_label,
                fallback_iv=iv_est,
            )
        sub_puts = chain[(chain[exp_col] == target_exp) & (chain["right_norm"] == "put")].copy()
        if not sub_puts.empty:
            ranked = _leg_liquidity_key(sub_puts, spot_price * 0.98)
            liquid = ranked[(ranked["oi"] >= min_open_interest) & (ranked["vol"] >= min_volume)]
            pool = liquid if not liquid.empty else ranked
            order = pool.sort_values(["spread", "distance"], kind="stable").index
            best_row = sub_puts.loc[order[0]]
            best_put_leg = _build_leg(
                best_row,
                right="put",
                target_exp=target_exp,
                exp_col=exp_col,
                spot_price=spot_price,
                chain_capture=chain_capture,
                provider_label=provider_label,
                fallback_iv=iv_est,
            )

    return {
        "call_vol": total_call_vol,
        "put_vol": total_put_vol,
        "call_oi": total_call_oi,
        "put_oi": total_put_oi,
        "pcr_vol": pcr_vol,
        "pcr_oi": pcr_oi,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "top_call_vol_strike": top_call_vol_strike,
        "top_put_vol_strike": top_put_vol_strike,
        "max_pain": max_pain,
        "target_exp": target_exp,
        "atm_iv": iv_est,
        "implied_1w_move": implied_1w_move,
        "implied_30d_move": implied_30d_move,
        "best_call_leg": best_call_leg,
        "best_put_leg": best_put_leg,
    }


def run_pullback_flow_engine(
    *,
    account: float = 10000.0,
    context: RunContext | None = None,
    config: DailyPlaysConfig | None = None,
    root_dir: str | Path = ".",
) -> dict[str, Any]:
    """Execute the full universe scan, ranking, and decision-support generator."""
    root = Path(root_dir)
    now_utc = datetime.now(timezone.utc)
    asof_iso = now_utc.isoformat().replace("+00:00", "Z")
    account_val = max(100.0, float(account))

    # Derive the same policy limits the main pipeline enforces via
    # OptionsPolicy, so legs are validated against preregistered config
    # rather than hardcoded thresholds.  When config is absent, fall back to
    # the OptionsPolicy defaults from options_validation.py.
    if config is not None:
        min_oi = config.min_open_interest
        min_vol = config.min_volume
        max_spread_pct = config.max_spread_pct
        swing_dte_min = config.swing_dte_min
        swing_dte_max = config.swing_dte_max
        max_position_risk_pct = config.max_position_risk_pct
    else:
        min_oi = 500
        min_vol = 50
        max_spread_pct = 0.10
        swing_dte_min = 30
        swing_dte_max = 60
        max_position_risk_pct = 0.005

    # Find all 1d equity parquet files
    all_files = sorted(
        glob.glob(str(root / "data" / "1d" / "*.parquet"))
        + glob.glob(str(root / "data" / "1d_wide" / "*.parquet"))
        + glob.glob(str(root / "edge" / "data" / "1d" / "*.parquet"))
        + glob.glob(str(root / "edge" / "data" / "1d_wide" / "*.parquet"))
    )

    seen: set[str] = set()
    ordered_symbols: list[str] = []
    # Non-equity / index symbols to exclude from stock plays
    exclude_syms = {"SPY", "QQQ", "IWM", "VIX", "UVXY", "TLT", "USO", "GLD", "SLV", "DIA"}
    for fp in all_files:
        sym = Path(fp).stem.upper()
        if sym in seen or sym in exclude_syms:
            continue
        seen.add(sym)
        ordered_symbols.append(sym)
    scanned_count = len(ordered_symbols)

    def _scan_symbol(sym: str) -> dict[str, Any] | None:
        """Technical profile + options structure for one symbol (thread-safe)."""
        df_p = load_price_data(sym, root_dir=root)
        tech = calculate_technical_profile(df_p)
        if not tech or tech["close"] < 8.0:
            return None
        df_c, c_date = load_latest_option_chain(sym, root_dir=root)
        if df_c is None or len(df_c) < 5:
            return None
        opt = analyze_options_gex_fast(
            df_c,
            tech["close"],
            dte_min=swing_dte_min,
            dte_max=swing_dte_max,
            asof_date=now_utc.date(),
            min_open_interest=min_oi,
            min_volume=min_vol,
        )
        if not opt:
            return None
        return {"symbol": sym, "tech": tech, "opt": opt, "chain_date": c_date}

    # The scan is parquet-I/O and vectorized-math bound (both release the GIL),
    # so a small thread pool overlaps disk latency across symbols.  Pure-Python
    # scoring stays in the main thread afterwards and keeps its determinism.
    max_workers = min(12, max(1, len(ordered_symbols)))
    scanned_rows: list[dict[str, Any]] = []
    if ordered_symbols:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            scanned_rows = [
                row for row in executor.map(_scan_symbol, ordered_symbols) if row is not None
            ]

    scored_candidates: list[dict[str, Any]] = []
    directional_count = 0
    bounce_count = 0
    breakdown_count = 0

    for row in scanned_rows:
        sym = row["symbol"]
        tech = row["tech"]
        opt = row["opt"]
        close = tech["close"]
        pullback = tech["pullback_20d"]
        rsi = tech["rsi"]
        ema_21 = tech["ema_21"]
        sma_50 = tech["sma_50"]
        pct_5d = tech["pct_5d"]
        pcr_vol = opt["pcr_vol"]
        call_vol = opt["call_vol"]
        put_vol = opt["put_vol"]

        # ---- Sleeve A: pullback bounce (long call) -----------------------
        bounce_score = 0.0
        bounce_reasons: list[str] = []

        if -18.0 <= pullback <= -4.0:
            bounce_score += 30.0
            bounce_reasons.append(f"Healthy {pullback:.1f}% pullback in established uptrend")
        elif -28.0 <= pullback < -18.0:
            bounce_score += 20.0
            bounce_reasons.append(f"Deep {pullback:.1f}% pullback testing major support")
        elif -4.0 < pullback <= 0.0:
            bounce_score += 10.0
            bounce_reasons.append(f"Consolidation near highs ({pullback:.1f}%)")
        else:
            bounce_score += 5.0

        if 30.0 <= rsi <= 48.0:
            bounce_score += 25.0
            bounce_reasons.append(f"Oversold/neutral RSI reset ({rsi:.1f}) with strong bounce room")
        elif 48.0 < rsi <= 56.0:
            bounce_score += 15.0
            bounce_reasons.append(f"Constructive RSI baseline ({rsi:.1f})")

        if close >= sma_50:
            bounce_score += 15.0
            bounce_reasons.append("Holding above 50-day SMA trend baseline")
        if close >= ema_21:
            bounce_score += 10.0
            bounce_reasons.append("Reclaiming 21-day EMA mean reversion level")

        if pcr_vol <= 0.30:
            bounce_score += 30.0
            bounce_reasons.append(f"Aggressive institutional call sweep flow (PCR: {pcr_vol:.2f})")
        elif pcr_vol <= 0.65:
            bounce_score += 20.0
            bounce_reasons.append(f"Bullish call flow dominance (PCR: {pcr_vol:.2f})")

        if call_vol >= 5000:
            bounce_score += 15.0
            bounce_reasons.append(f"Massive call volume liquidity ({int(call_vol):,} contracts)")
        elif call_vol >= 1000:
            bounce_score += 10.0
            bounce_reasons.append(f"Solid options liquidity ({int(call_vol):,} calls)")

        if opt["put_wall"] and close >= opt["put_wall"] * 0.98:
            bounce_score += 10.0
            bounce_reasons.append(f"Supported by institutional Put Wall at ${opt['put_wall']:.2f}")

        # ---- Sleeve B: breakdown roll (long put) -------------------------
        breakdown_score = 0.0
        breakdown_reasons: list[str] = []

        if pullback >= 6.0:
            breakdown_score += 25.0
            breakdown_reasons.append(f"Extended {abs(pullback):.1f}% run above the 20-day high")
        elif 3.0 <= pullback < 6.0:
            breakdown_score += 15.0
            breakdown_reasons.append(f"Stretched {abs(pullback):.1f}% extension into resistance")

        if rsi >= 72.0:
            breakdown_score += 25.0
            breakdown_reasons.append(f"Overbought RSI exhaustion ({rsi:.1f})")
        elif 64.0 <= rsi < 72.0:
            breakdown_score += 15.0
            breakdown_reasons.append(f"Hot RSI baseline ({rsi:.1f}) losing momentum room")

        if close < sma_50:
            breakdown_score += 20.0
            breakdown_reasons.append("Trading below the 50-day SMA trend baseline")
        if close < ema_21:
            breakdown_score += 15.0
            breakdown_reasons.append("Rejected beneath the 21-day EMA mean-reversion level")
        if pct_5d <= -3.0:
            breakdown_score += 10.0
            breakdown_reasons.append(f"Failed bounce: {pct_5d:.1f}% over five sessions")

        if pcr_vol >= 1.50:
            breakdown_score += 25.0
            breakdown_reasons.append(f"Heavy institutional put dominance (PCR: {pcr_vol:.2f})")
        elif pcr_vol >= 1.00:
            breakdown_score += 15.0
            breakdown_reasons.append(f"Bearish put flow tilt (PCR: {pcr_vol:.2f})")

        if put_vol >= 5000:
            breakdown_score += 10.0
            breakdown_reasons.append(f"Deep put liquidity ({int(put_vol):,} contracts)")
        elif put_vol >= 1000:
            breakdown_score += 5.0
            breakdown_reasons.append(f"Workable put liquidity ({int(put_vol):,} puts)")

        if opt["call_wall"] and close <= opt["call_wall"] * 1.02:
            breakdown_score += 10.0
            breakdown_reasons.append(
                f"Capped by institutional Call Wall at ${opt['call_wall']:.2f}"
            )
        if opt["max_pain"] and opt["max_pain"] > opt["call_wall"] and close < opt["max_pain"]:
            breakdown_score += 5.0

        # ---- Shared structure: targets, stops, risk/reward ---------------
        target_1 = tech["r1"] if tech["r1"] > close else round(close + tech["atr"] * 2.0, 2)
        target_2 = tech["r2"] if tech["r2"] > target_1 else round(close + tech["atr"] * 3.5, 2)
        stop_loss = tech["s1"] if tech["s1"] < close else round(close - tech["atr"] * 1.5, 2)

        upside = (target_1 - close) / close
        downside = (close - stop_loss) / close
        rr_long = upside / (downside + 1e-4)
        rr_short = downside / (upside + 1e-4)

        if rr_long >= 1.5:
            bounce_score += 15.0
            bounce_reasons.append(f"Favorable Risk/Reward ratio ({rr_long:.1f}x)")
        if rr_short >= 1.5:
            breakdown_score += 15.0
            breakdown_reasons.append(f"Favorable Risk/Reward ratio ({rr_short:.1f}x)")

        # Each sleeve needs its own directional thesis before it counts.
        bounce_valid = bounce_score >= 40.0
        breakdown_valid = breakdown_score >= 40.0
        if bounce_valid or breakdown_valid:
            directional_count += 1
        if bounce_valid:
            bounce_count += 1
        if breakdown_valid:
            breakdown_count += 1

        # Keep whichever sleeve has the stronger case (ties break to the
        # bounce sleeve); the loser survives in evidence for auditability.
        if bounce_score >= breakdown_score:
            setup_kind = "pullback_bounce"
            strategy = "long_call"
            side = "long"
            score = bounce_score
            reasons = bounce_reasons
            risk_reward = rr_long
            counter_score = breakdown_score
            counter_reasons = breakdown_reasons
            invalidation = [f"Daily close below Support / Stop Loss at ${stop_loss:.2f}"]
            if opt["put_wall"]:
                invalidation.append(f"Break below Put Wall floor at ${opt['put_wall']:.2f}")
        else:
            setup_kind = "breakdown_roll"
            strategy = "long_put"
            side = "long"
            score = breakdown_score
            reasons = breakdown_reasons
            risk_reward = rr_short
            counter_score = bounce_score
            counter_reasons = bounce_reasons
            invalidation = [f"Daily close above Resistance / Stop Loss at ${target_1:.2f}"]
            if opt["call_wall"]:
                invalidation.append(f"Reclaim of the ${opt['call_wall']:.2f} Call Wall ceiling")

        scored_candidates.append(
            {
                "symbol": sym,
                "score": score,
                "setup_kind": setup_kind,
                "strategy": strategy,
                "counter_score": counter_score,
                "counter_reasons": counter_reasons[:3],
                "close": close,
                "pullback": pullback,
                "rsi": rsi,
                "tech": tech,
                "opt": opt,
                "target_1": target_1,
                "target_2": target_2,
                "stop_loss": stop_loss,
                "risk_reward": risk_reward,
                "reasons": reasons,
                "invalidation": invalidation,
                "chain_date": row["chain_date"],
            }
        )

    # Sort descending by composite score; ties break by symbol for determinism.
    scored_candidates.sort(key=lambda x: (-x["score"], x["symbol"]))

    # Build Decisions (ENTER, WATCH, ABSTAIN)
    plays_decisions = []
    watchlist_decisions = []
    rejections_decisions = []

    # Target top 10 as ENTER tickets
    top_plays = scored_candidates[:10]
    watch_plays = scored_candidates[10:20]
    reject_plays = scored_candidates[20:45]

    today_iso = now_utc.date().isoformat()

    def build_decision_dict(candidate: dict[str, Any], state: str, rank: int) -> dict[str, Any]:
        sym = candidate["symbol"]
        tech = candidate["tech"]
        opt = candidate["opt"]
        close = candidate["close"]
        strategy = str(candidate.get("strategy") or "long_call")
        leg = opt.get("best_call_leg" if strategy == "long_call" else "best_put_leg")

        # Validation: enforce the same liquidity/DTE/spread policy the main
        # pipeline enforces via OptionsPolicy, so this engine never emits a
        # play that would fail validate_structure downstream.
        leg_failures: list[str] = []
        if leg is None:
            leg_failures.append("options_chain_unavailable")
        else:
            if not leg.get("bid") or not leg.get("ask"):
                leg_failures.append("missing_nbbo_quote")
            if int(leg.get("open_interest") or 0) < min_oi:
                leg_failures.append("open_interest_below_policy_floor")
            if int(leg.get("volume") or 0) < min_vol:
                leg_failures.append("volume_below_policy_floor")
            spread_val = leg.get("spread_pct")
            if spread_val is None:
                leg_failures.append("spread_unmeasured")
            elif float(spread_val) > max_spread_pct:
                leg_failures.append("spread_exceeds_policy_ceiling")
            dte_val = int(leg.get("dte") or 0)
            if dte_val < swing_dte_min or dte_val > swing_dte_max:
                leg_failures.append("dte_outside_policy_window")
            quote_stamp = leg.get("quote_asof_utc")
            if not quote_stamp:
                leg_failures.append("chain_capture_time_missing")

        # A chain snapshot that is not from today cannot back an ENTER ticket:
        # its quotes may be days old and no run-clock stamp can make them
        # fresh.  WATCH keeps the structure visible with the age labelled.
        # The loader's folder label carries a "date=" prefix; strip it so the
        # freshness comparison is against the bare ISO day.
        chain_date = str(candidate.get("chain_date") or "").removeprefix("date=")
        stale_chain = bool(chain_date and chain_date != today_iso)
        if state == "ENTER" and stale_chain:
            leg_failures.append("chain_snapshot_not_current")

        # Risk sizing: use the config-validated per-position risk limit, not a
        # hardcoded 2% that is 4x the preregistered 0.5% cap.  A single contract
        # that costs more than the budget must not be forced via max(1, ...);
        # doing so would silently breach the risk cap.  Mirror
        # validate_structure's risk_budget_exceeded gate instead.
        max_loss_dollars = round(account_val * max_position_risk_pct, 2)
        mid_value = float(leg.get("mid") or 0.0) if leg else 0.0
        contract_cost = (mid_value * 100.0) if mid_value > 0 else 0.0
        if contract_cost <= 0:
            contracts = 0
            if leg is not None and "missing_nbbo_quote" not in leg_failures:
                leg_failures.append("risk_budget_exceeded")
        elif contract_cost > max_loss_dollars:
            contracts = 0
            if leg is not None:
                leg_failures.append("risk_budget_exceeded")
        else:
            contracts = min(100, int(max_loss_dollars // contract_cost))
        total_max_loss = round(contracts * contract_cost, 2) if contracts > 0 else 0.0

        # This engine is a technical-screen heuristic, not a calibrated
        # model.  Confidence provenance must be honest: confidence_kind is
        # "unavailable", model/calibrated probability are null, and
        # promotion_authorized is False so the downstream authorization gate
        # never sees a fabricated model endorsement.
        calibrated_prob = None
        model_artifact_sha256 = None
        promotion_authorized = False
        confidence_kind = "unavailable"
        calibration_version = None
        probability_target = None
        horizon_days = None
        entry_threshold = None
        threshold_version = None

        # Only carry the real leg forward when it passes policy checks.
        # If the leg fails or is absent, emit empty legs and record the
        # failure rather than fabricating a synthetic contract with fake
        # Greeks, volume, OI, and a "fresh" quote timestamp.
        if leg is None or leg_failures:
            legs_list: list[dict[str, Any]] = []
        else:
            legs_list = [leg]

        play_id = f"play_{sym}_{now_utc.strftime('%Y%m%d%H%M')}_{rank}"

        # An ENTER slot only stays ENTER when its ticket passed every gate.
        # Any failure downgrades the ticket to WATCH (re-bucketed below) so a
        # stale chain or an unaffordable contract can never render as
        # actionable.
        downgraded_at_build = state == "ENTER" and bool(leg_failures)
        effective_state = "WATCH" if downgraded_at_build else state

        thesis_points = list(candidate["reasons"][:4])
        if strategy == "long_call":
            thesis_points.append(
                f"Target 1: ${candidate['target_1']:.2f} · Target 2: ${candidate['target_2']:.2f}"
                + (f" · Call Wall: ${opt['call_wall']:.2f}" if opt.get("call_wall") else "")
            )
        else:
            thesis_points.append(
                f"Downside objective: ${candidate['stop_loss']:.2f} · Max pain: "
                + (f"${opt['max_pain']:.2f}" if opt.get("max_pain") else "unmeasured")
                + (f" · Put support wall: ${opt['put_wall']:.2f}" if opt.get("put_wall") else "")
            )

        return {
            "play_id": play_id,
            "symbol": sym,
            "side": "long",
            "strategy": strategy,
            "state": effective_state,
            "rank": rank,
            "thesis": thesis_points,
            "invalidation": candidate["invalidation"][:2],
            "entry": {
                "limit_reference": legs_list[0]["mid"] if legs_list else 0.0,
                "underlying_reference": round(close, 2),
                "quote_asof_utc": asof_iso,
                "max_quote_age_seconds": 120,
            },
            "legs": legs_list,
            "risk": {
                "account": account_val,
                "max_loss_dollars": total_max_loss,
                "max_loss_pct": round(total_max_loss / account_val, 4),
                "contracts": contracts,
                "reward_risk_reference": round(candidate["risk_reward"], 2),
            },
            "confidence": {
                "state": effective_state,
                "confidence_kind": confidence_kind,
                "evidence_grade": "F",
                "model_probability": calibrated_prob,
                "calibrated_probability": calibrated_prob,
                "calibration_version": calibration_version,
                "probability_target": probability_target,
                "horizon_days": horizon_days,
                "entry_threshold": entry_threshold,
                "threshold_version": threshold_version,
                "model_artifact_sha256": model_artifact_sha256,
                "promotion_authorized": promotion_authorized,
                "reasons": candidate["reasons"],
                "failed_checks": leg_failures
                if leg_failures
                else (
                    []
                    if effective_state == "ENTER"
                    else (
                        ["near_resistance"]
                        if effective_state == "WATCH"
                        else ["liquidity_or_spread_filter"]
                    )
                ),
            },
            "evidence": {
                "setup_kind": candidate.get("setup_kind"),
                "pullback_20d_pct": candidate["pullback"],
                "rsi_14": candidate["rsi"],
                "pct_5d": tech.get("pct_5d"),
                "ema_21": tech.get("ema_21"),
                "sma_50": tech.get("sma_50"),
                "atr_14": tech.get("atr"),
                "pcr_volume": opt.get("pcr_vol"),
                "pcr_open_interest": opt.get("pcr_oi"),
                "call_volume": opt.get("call_vol"),
                "put_volume": opt.get("put_vol"),
                "call_wall": opt.get("call_wall"),
                "put_wall": opt.get("put_wall"),
                "top_call_vol_strike": opt.get("top_call_vol_strike"),
                "top_put_vol_strike": opt.get("top_put_vol_strike"),
                "max_pain": opt.get("max_pain"),
                "target_expiry": opt.get("target_exp"),
                "atm_iv": opt.get("atm_iv"),
                "implied_1w_move": round(opt.get("implied_1w_move", 0.0), 2),
                "support_stop": candidate["stop_loss"],
                "target_1": candidate["target_1"],
                "target_2": candidate["target_2"],
                "counter_setup_score": candidate.get("counter_score"),
                "counter_reasons": candidate.get("counter_reasons"),
            },
            "freshness": {
                "asof_utc": asof_iso,
                "run_clock": asof_iso,
                "chain_date": candidate.get("chain_date"),
                "chain_snapshot_stale": stale_chain,
                "chain_captured_utc": (legs_list[0].get("quote_asof_utc") if legs_list else None),
            },
            "provenance": {
                "engine": "TradeCentral Pullback & Options Flow Scanner v3",
                "version": PULLBACK_FLOW_ENGINE_VERSION,
                "confidence_basis": "technical_screen_not_calibrated_model",
                "greeks_source": "black_scholes_from_cached_iv" if legs_list else None,
                "quotes_are_chain_capture": True,
                "enter_downgraded_to_watch": downgraded_at_build,
            },
        }

    for idx, c in enumerate(top_plays, 1):
        plays_decisions.append(build_decision_dict(c, "ENTER", idx))

    for idx, c in enumerate(watch_plays, 11):
        watchlist_decisions.append(build_decision_dict(c, "WATCH", idx))
    for idx, c in enumerate(reject_plays, 21):
        rejections_decisions.append(build_decision_dict(c, "ABSTAIN", idx))

    # Execution honesty: an ENTER slot whose ticket failed any execution gate
    # (stale chain, liquidity floor, unmeasured spread, zero affordable
    # contracts) is not actionable.  Re-bucket it to WATCH so the plays list
    # only ever contains tickets that passed every gate.  ABSTAIN records keep
    # their bucket; their failures are informational.
    def _downgrade(decision: dict[str, Any]) -> dict[str, Any]:
        if decision["state"] != "ENTER":
            return decision
        if decision["confidence"]["failed_checks"]:
            decision["state"] = "WATCH"
            decision["confidence"]["state"] = "WATCH"
            decision["provenance"] = {
                **decision["provenance"],
                "enter_downgraded_to_watch": True,
            }
        return decision

    plays_decisions = [_downgrade(d) for d in plays_decisions]
    watchlist_decisions = [_downgrade(d) for d in watchlist_decisions]
    demoted_to_watch = [d for d in plays_decisions if d["state"] == "WATCH"]
    actionable_plays = [d for d in plays_decisions if d["state"] == "ENTER"]
    watchlist_decisions = [*demoted_to_watch, *watchlist_decisions]
    # Operator semantics mirror the main pipeline: `plays` is actionable
    # ENTER tickets only; demoted and ranked-out records stay visible as WATCH.
    plays_decisions = actionable_plays
    status = "COMPLETE" if plays_decisions else "NO_PLAY"

    # Market map: this engine does not compute sector relative strength or
    # institutional flow rotation.  Report an explicit missing state rather
    # than fabricating "definitive" sector flow readings.
    market_map = {
        "source": "not_computed",
        "asof": asof_iso,
        "available": False,
        "reason": "pullback_flow_engine does not compute sector relative strength; use the main pipeline for market map data.",
        "money_in": [],
        "money_out": [],
        "rotation": None,
    }

    chain_snapshots_count = len(scanned_rows)
    execution_health_warnings = (
        [f"fallback_enter_tickets_demoted_to_watch:{len(demoted_to_watch)}"]
        if demoted_to_watch
        else []
    )
    scan_scope = {
        "sector_books_scored": 0,
        "targeted_count": len(scored_candidates),
        "model_covered_count": len(scored_candidates),
        "model_domain_supported": len(seen),
        "successfully_scanned_candidates": scanned_count,
        "directional_setups": directional_count,
        "bounce_setups": bounce_count,
        "breakdown_setups": breakdown_count,
        "chain_requests": chain_snapshots_count,
        "chain_snapshots": chain_snapshots_count,
        "flow_activity_requested": scanned_count,
        "flow_activity_observed": chain_snapshots_count,
    }

    run_id = f"{now_utc.strftime('%Y%m%dT%H%M%SZ')}-pbflow"

    manifest = {
        "run_id": run_id,
        "requested_for": now_utc.strftime("%Y-%m-%d"),
        "asof_utc": asof_iso,
        "market_session": context.market_session.value if context else "regular",
        "mode": "live",
        "account": account_val,
        "config_hash": "pullback_options_flow_engine_v3",
        "warnings": [],
        "schema_version": "daily-plays-run-v1",
        "status": status,
        "engine": PULLBACK_FLOW_ENGINE_NAME,
        "engine_version": PULLBACK_FLOW_ENGINE_VERSION,
    }

    payload = {
        "available": True,
        "run_id": run_id,
        "requested_for": now_utc.strftime("%Y-%m-%d"),
        "asof_utc": asof_iso,
        "market_session": context.market_session.value if context else "regular",
        "mode": "live",
        "account": account_val,
        "config_hash": manifest["config_hash"],
        "warnings": [],
        "status": status,
        "engine": PULLBACK_FLOW_ENGINE_NAME,
        "engine_version": PULLBACK_FLOW_ENGINE_VERSION,
        "market_map": market_map,
        "scan_scope": scan_scope,
        "flow_activity": {
            "coverage": {
                "requested": scanned_count,
                "with_activity": chain_snapshots_count,
            }
        },
        "plays": plays_decisions,
        "watchlist": watchlist_decisions,
        "rejections": rejections_decisions,
        "research_board": [],
        "decision_blockers": [],
        "advisory_evidence_warnings": [],
        "execution_health_warnings": execution_health_warnings,
    }

    return payload


def persist_pullback_plays_run(payload: Mapping[str, Any], output_root: str | Path) -> Path:
    """Persist run artifacts to output root in canonical daily-plays format."""
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    run_id = str(payload.get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    def write_json(name: str, data: Any) -> None:
        p = run_dir / name
        p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    manifest = {
        "run_id": run_id,
        "requested_for": payload.get("requested_for"),
        "asof_utc": payload.get("asof_utc"),
        "market_session": payload.get("market_session", "regular"),
        "mode": payload.get("mode", "live"),
        "account": payload.get("account", 10000.0),
        "config_hash": payload.get("config_hash", "pullback_v3"),
        "warnings": payload.get("warnings", []),
        "schema_version": "daily-plays-run-v1",
        "status": payload.get("status", "COMPLETE"),
        # Engine provenance so /api/plays and the dashboard badge can show
        # which engine produced the run without loading plays.json.
        "engine": payload.get("engine", PULLBACK_FLOW_ENGINE_NAME),
        "engine_version": payload.get("engine_version", PULLBACK_FLOW_ENGINE_VERSION),
    }

    write_json("manifest.json", manifest)
    write_json("plays.json", payload.get("plays", []))
    write_json(
        "decisions.json",
        [
            *(payload.get("plays") or []),
            *(payload.get("watchlist") or []),
            *(payload.get("rejections") or []),
        ],
    )
    write_json(
        "discovery.json",
        {
            "market_map": payload.get("market_map", {}),
            "sector_books_scored": (payload.get("scan_scope") or {}).get("sector_books_scored", 11),
            "targeted_count": (payload.get("scan_scope") or {}).get("targeted_count", 0),
            "model_covered_count": (payload.get("scan_scope") or {}).get("model_covered_count", 0),
            "model_covered_symbols": [p.get("symbol") for p in (payload.get("plays") or [])],
        },
    )
    write_json("flow_activity.json", payload.get("flow_activity", {}))
    write_json("research_board.json", payload.get("research_board", []))
    write_json("candidates.json", payload.get("plays", []))
    write_json("option_snapshots.json", {})

    # Also update desk_board_latest.json for desk views — atomically so a
    # crash mid-write never leaves a truncated JSON file for /api/plays.
    desk_latest = root / "desk_board_latest.json"
    try:
        import tempfile

        tmp_fd, tmp_path = tempfile.mkstemp(prefix=".desk_board_", suffix=".json", dir=str(root))
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, indent=2, default=str))
            os.replace(tmp_path, desk_latest)
        except Exception:
            os.unlink(tmp_path)
            raise
    except Exception:
        pass  # noqa: BLE001 — desk_latest is a convenience cache, not authoritative

    return run_dir
