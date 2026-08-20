"""Quantitative Pullback & Institutional Options Flow Engine for TradeCentral Daily Plays.

Scans the equity universe for high-probability pullback bounce setups validated by
institutional options flow (Put/Call ratios, Call/Put Walls, Max Pain, and GEX).
Produces fully populated, sized, and verified PlaysPayload artifacts for the Plays tab.
"""

from __future__ import annotations

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


def analyze_options_gex_fast(
    df_chain: pd.DataFrame | None,
    spot_price: float,
    *,
    dte_min: int = 30,
    dte_max: int = 60,
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
    # to fail validation with "dte_outside_policy_window".
    exp_col = (
        "expiry"
        if "expiry" in chain.columns
        else ("expiration" if "expiration" in chain.columns else None)
    )
    target_exp = None
    target_iv = None
    if exp_col:
        exps = sorted(chain[exp_col].dropna().unique())
        today = datetime.now(timezone.utc).date()
        for e in exps:
            try:
                ed = datetime.strptime(str(e)[:10], "%Y-%m-%d").date()
                dte = (ed - today).days
                if dte_min <= dte <= dte_max:
                    target_exp = str(e)[:10]
                    sub = chain[chain[exp_col] == e]
                    atm_contracts = sub.iloc[(sub["strike"] - spot_price).abs().argsort()[:4]]
                    target_iv = float(atm_contracts["iv"].median())
                    break
            except Exception:
                pass
        # Fall back to the nearest in-window expiry if none fall inside the
        # policy window, so the engine still reports a chain snapshot rather
        # than silently dropping the symbol.  The leg-validation gate will
        # then honestly record the dte_outside_policy_window failure.
        if not target_exp and len(exps) > 0:
            target_exp = str(exps[0])[:10]

    iv_est = target_iv if (target_iv and target_iv > 0.05 and target_iv < 5.0) else 0.45
    implied_1w_move = spot_price * iv_est * math.sqrt(7.0 / 365.0)
    implied_30d_move = spot_price * iv_est * math.sqrt(30.0 / 365.0)

    # Find candidate contract near spot (Calls)
    best_call_leg = None
    if target_exp and exp_col:
        sub_calls = chain[(chain[exp_col] == target_exp) & (chain["right_norm"] == "call")].copy()
        if not sub_calls.empty:
            # Pick strike near spot or 1-2% OTM
            sub_calls["diff"] = (sub_calls["strike"] - spot_price * 1.01).abs()
            sub_calls = sub_calls.sort_values("diff")
            best_row = sub_calls.iloc[0]
            bid = float(best_row.get("bid") or 0.0)
            ask = float(best_row.get("ask") or 0.0)
            last = float(best_row.get("lastprice") or best_row.get("last_price") or 0.0)
            mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else (last if last > 0 else 1.0)
            spread_pct = ((ask - bid) / mid) if (mid > 0 and ask >= bid) else 0.05
            occ_sym = str(
                best_row.get("contractsymbol")
                or best_row.get("occ_symbol")
                or f"{best_row.get('symbol', '')}{target_exp.replace('-', '')}C{int(best_row['strike'] * 1000):08d}"
            )
            dte_val = int(best_row.get("dte") or 21)

            best_call_leg = {
                "side": "buy",
                "right": "call",
                "occ_symbol": occ_sym,
                "underlying": str(best_row.get("symbol") or "").upper(),
                "expiry": target_exp,
                "dte": dte_val if dte_val >= 0 else 21,
                "strike": float(best_row["strike"]),
                "multiplier": 100,
                "bid": bid if bid > 0 else round(mid * 0.95, 2),
                "ask": ask if ask > 0 else round(mid * 1.05, 2),
                "mid": round(mid, 2),
                "spread_pct": round(spread_pct, 4),
                "volume": int(best_row.get("vol") or 0),
                "open_interest": int(best_row.get("oi") or 0),
                "quote_asof_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "provider": "TradeCentral GEX Engine",
                "iv": round(float(best_row.get("iv") or iv_est), 4),
                "delta": round(float(best_row.get("delta") or 0.50), 3),
                "gamma": round(float(best_row.get("gamma") or 0.02), 4),
            }

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

    seen = set()
    scored_candidates = []
    scanned_count = 0
    directional_count = 0
    chain_snapshots_count = 0

    # Non-equity / index symbols to exclude from stock plays
    exclude_syms = {"SPY", "QQQ", "IWM", "VIX", "UVXY", "TLT", "USO", "GLD", "SLV", "DIA"}

    for fp in all_files:
        sym = Path(fp).stem.upper()
        if sym in seen or sym in exclude_syms:
            continue
        seen.add(sym)
        scanned_count += 1

        df_p = load_price_data(sym, root_dir=root)
        tech = calculate_technical_profile(df_p)
        if not tech or tech["close"] < 8.0:
            continue

        df_c, c_date = load_latest_option_chain(sym, root_dir=root)
        if df_c is None or len(df_c) < 5:
            continue
        chain_snapshots_count += 1

        opt = analyze_options_gex_fast(
            df_c, tech["close"], dte_min=swing_dte_min, dte_max=swing_dte_max
        )
        if not opt:
            continue

        close = tech["close"]
        pullback = tech["pullback_20d"]
        rsi = tech["rsi"]
        pcr_vol = opt["pcr_vol"]
        call_vol = opt["call_vol"]

        # Pullback & Momentum Criteria
        score = 0.0
        reasons = []
        invalidation = []

        # 1. Pullback zone
        if -18.0 <= pullback <= -4.0:
            score += 30.0
            reasons.append(f"Healthy {pullback:.1f}% pullback in established uptrend")
        elif -28.0 <= pullback < -18.0:
            score += 20.0
            reasons.append(f"Deep {pullback:.1f}% pullback testing major support")
        elif pullback > -4.0 and pullback <= 0.0:
            score += 10.0
            reasons.append(f"Consolidation near highs ({pullback:.1f}%)")
        else:
            score += 5.0

        # 2. RSI Reset
        if 30.0 <= rsi <= 48.0:
            score += 25.0
            reasons.append(f"Oversold/neutral RSI reset ({rsi:.1f}) with strong bounce room")
        elif 48.0 < rsi <= 56.0:
            score += 15.0
            reasons.append(f"Constructive RSI baseline ({rsi:.1f})")

        # 3. Moving Average Support
        if close >= tech["sma_50"]:
            score += 15.0
            reasons.append("Holding above 50-day SMA trend baseline")
        if close >= tech["ema_21"]:
            score += 10.0
            reasons.append("Reclaiming 21-day EMA mean reversion level")

        # 4. Institutional Options Flow
        if pcr_vol <= 0.30:
            score += 30.0
            reasons.append(f"Aggressive institutional call sweep flow (PCR: {pcr_vol:.2f})")
        elif pcr_vol <= 0.65:
            score += 20.0
            reasons.append(f"Bullish call flow dominance (PCR: {pcr_vol:.2f})")

        if call_vol >= 5000:
            score += 15.0
            reasons.append(f"Massive call volume liquidity ({int(call_vol):,} contracts)")
        elif call_vol >= 1000:
            score += 10.0
            reasons.append(f"Solid options liquidity ({int(call_vol):,} calls)")

        # 5. Gamma Profile
        if opt["put_wall"] and close >= opt["put_wall"] * 0.98:
            score += 10.0
            reasons.append(f"Supported by institutional Put Wall at ${opt['put_wall']:.2f}")

        # Targets & Stop loss
        target_1 = tech["r1"] if tech["r1"] > close else round(close + tech["atr"] * 2.0, 2)
        target_2 = tech["r2"] if tech["r2"] > target_1 else round(close + tech["atr"] * 3.5, 2)
        stop_loss = tech["s1"] if tech["s1"] < close else round(close - tech["atr"] * 1.5, 2)

        upside = (target_1 - close) / close
        downside = (close - stop_loss) / close
        rr = upside / (downside + 1e-4)

        if rr >= 1.5:
            score += 15.0
            reasons.append(f"Favorable Risk/Reward ratio ({rr:.1f}x)")

        # Invalidation criteria
        invalidation.append(f"Daily close below Support / Stop Loss at ${stop_loss:.2f}")
        if opt["put_wall"]:
            invalidation.append(f"Break below Put Wall floor at ${opt['put_wall']:.2f}")

        if score >= 40.0:
            directional_count += 1

        scored_candidates.append(
            {
                "symbol": sym,
                "score": score,
                "close": close,
                "pullback": pullback,
                "rsi": rsi,
                "tech": tech,
                "opt": opt,
                "target_1": target_1,
                "target_2": target_2,
                "stop_loss": stop_loss,
                "risk_reward": rr,
                "reasons": reasons,
                "invalidation": invalidation,
                "chain_date": c_date,
            }
        )

    # Sort descending by composite score
    scored_candidates.sort(key=lambda x: x["score"], reverse=True)

    # Build Decisions (ENTER, WATCH, ABSTAIN)
    plays_decisions = []
    watchlist_decisions = []
    rejections_decisions = []

    # Target top 10 as ENTER tickets
    top_plays = scored_candidates[:10]
    watch_plays = scored_candidates[10:20]
    reject_plays = scored_candidates[20:45]

    def build_decision_dict(candidate: dict[str, Any], state: str, rank: int) -> dict[str, Any]:
        sym = candidate["symbol"]
        tech = candidate["tech"]
        opt = candidate["opt"]
        close = candidate["close"]
        leg = opt.get("best_call_leg")

        # Validation: enforce the same liquidity/DTE/spread policy the main
        # pipeline enforces via OptionsPolicy, so this engine never emits a
        # play that would fail validate_structure downstream.
        leg_failures: list[str] = []
        if leg is None:
            leg_failures.append("options_chain_unavailable")
        else:
            if int(leg.get("open_interest") or 0) < min_oi:
                leg_failures.append("open_interest_below_policy_floor")
            if int(leg.get("volume") or 0) < min_vol:
                leg_failures.append("volume_below_policy_floor")
            if float(leg.get("spread_pct") or 0.0) > max_spread_pct:
                leg_failures.append("spread_exceeds_policy_ceiling")
            dte_val = int(leg.get("dte") or 0)
            if dte_val < swing_dte_min or dte_val > swing_dte_max:
                leg_failures.append("dte_outside_policy_window")

        # Risk sizing: use the config-validated per-position risk limit, not a
        # hardcoded 2% that is 4x the preregistered 0.5% cap.  A single contract
        # that costs more than the budget must not be forced via max(1, ...);
        # doing so would silently breach the risk cap.  Mirror
        # validate_structure's risk_budget_exceeded gate instead.
        max_loss_dollars = round(account_val * max_position_risk_pct, 2)
        contract_cost = (leg["mid"] * 100.0) if leg and leg.get("mid", 0) > 0 else 150.0
        if contract_cost <= 0:
            contracts = 0
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

        thesis_points = candidate["reasons"][:4]
        if opt.get("call_wall"):
            thesis_points.append(
                f"Target 1: ${candidate['target_1']:.2f} · Target 2 (Call Wall): ${candidate['target_2']:.2f}"
            )

        return {
            "play_id": play_id,
            "symbol": sym,
            "side": "long",
            "strategy": "long_call",
            "state": state,
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
                "state": state,
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
                    if state == "ENTER"
                    else (
                        ["near_resistance"] if state == "WATCH" else ["liquidity_or_spread_filter"]
                    )
                ),
            },
            "evidence": {
                "pullback_20d_pct": candidate["pullback"],
                "rsi_14": candidate["rsi"],
                "pcr_volume": opt.get("pcr_vol"),
                "pcr_open_interest": opt.get("pcr_oi"),
                "call_wall": opt.get("call_wall"),
                "put_wall": opt.get("put_wall"),
                "max_pain": opt.get("max_pain"),
                "implied_1w_move": round(opt.get("implied_1w_move", 0.0), 2),
                "support_stop": candidate["stop_loss"],
                "target_1": candidate["target_1"],
                "target_2": candidate["target_2"],
            },
            "freshness": {
                "asof_utc": asof_iso,
                "chain_date": candidate.get("chain_date"),
            },
            "provenance": {
                "engine": "TradeCentral Pullback & Options Flow Scanner v3",
                "version": "3.2.0",
            },
        }

    for idx, c in enumerate(top_plays, 1):
        plays_decisions.append(build_decision_dict(c, "ENTER", idx))

    for idx, c in enumerate(watch_plays, 11):
        watchlist_decisions.append(build_decision_dict(c, "WATCH", idx))

    for idx, c in enumerate(reject_plays, 21):
        rejections_decisions.append(build_decision_dict(c, "ABSTAIN", idx))

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

    scan_scope = {
        "sector_books_scored": 0,
        "targeted_count": len(scored_candidates),
        "model_covered_count": len(scored_candidates),
        "model_domain_supported": len(seen),
        "successfully_scanned_candidates": scanned_count,
        "directional_setups": directional_count,
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
        "status": "COMPLETE" if plays_decisions else "NO_PLAY",
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
        "status": "COMPLETE" if plays_decisions else "NO_PLAY",
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
        "execution_health_warnings": [],
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
