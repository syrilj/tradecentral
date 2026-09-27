"""Validate bullish/bearish gamma-squeeze theory scores against subsequent returns.

Design goals (quant research hygiene):
- Report the shipped **theory score** hit rates (short-gamma fuel × signed-flow
  and/or momentum conviction).
- Report **momentum-only** baseline (so we don't claim gamma edge that is just mom).
- Report **SR-signed-by-momentum** (fuel × sign(mom)) to isolate short-gamma fuel.
- Cross-sectional rank IC of scores vs forward returns when N is large enough.
- Explicit caveats: single OI snapshot, dealer inventory assumed short-premium, etc.

Local data: ``edge/data/option_chains/date=*/*.parquet`` + ``edge/data/1d{,_wide}/*.parquet``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from edge.daily_plays.gex_core import (
    bs_gamma,
    compute_theory_squeeze,
)
from edge.research.flow_shift import current_flow_after_shift, signed_observations_from_bars


EDGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHAIN_ROOT = EDGE_ROOT / "data" / "option_chains"
DEFAULT_PRICE_DIRS = (EDGE_ROOT / "data" / "1d", EDGE_ROOT / "data" / "1d_wide")
DEFAULT_OUT = EDGE_ROOT / "runs" / "squeeze_validation"


@dataclass(frozen=True)
class SqueezeValidationConfig:
    chain_root: str = str(DEFAULT_CHAIN_ROOT)
    price_dirs: tuple[str, ...] = tuple(str(p) for p in DEFAULT_PRICE_DIRS)
    out_dir: str = str(DEFAULT_OUT)
    momentum_lookback: int = 5
    adv_window: int = 20
    forward_horizons: tuple[int, ...] = (1, 3, 5)
    score_threshold: float = 15.0
    risk_free_rate: float = 0.045
    max_dte: int = 45
    min_open_interest: int = 50
    score_scale: float = 40.0
    # If True, try yfinance for prices after local last date (forward test).
    fetch_missing_forward: bool = True


def _norm_right(value: Any) -> str | None:
    t = str(value or "").strip().lower()
    if t in {"c", "call"}:
        return "call"
    if t in {"p", "put"}:
        return "put"
    return None


def _load_one_price_file(path: Path) -> pd.DataFrame | None:
    """Load and normalize a single per-symbol OHLCV parquet.

    Returns ``None`` on any read/parse failure or if the result is unusable
    (no ``close`` column, or empty) rather than raising, so a caller can try
    the next candidate directory.
    """
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None
    if not isinstance(df.index, pd.DatetimeIndex):
        for col in ("Date", "date", "timestamp"):
            if col in df.columns:
                df = df.set_index(col)
                break
    try:
        df.index = pd.to_datetime(df.index).tz_localize(None)
    except (TypeError, ValueError):
        return None
    df = df.sort_index()
    # normalize columns
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for want in ("open", "high", "low", "close", "volume"):
        if want in cols:
            rename[cols[want]] = want
    df = df.rename(columns=rename)
    if "close" not in df.columns or df.empty:
        return None
    return df


def _load_price(symbol: str, price_dirs: Iterable[Path]) -> pd.DataFrame | None:
    """Load a symbol's OHLCV history, preferring the freshest candidate.

    ``price_dirs`` commonly lists more than one directory for the same
    symbol -- e.g. a stale ``data/1d`` snapshot alongside a current
    ``data/1d_wide`` one. Returning on the first directory that merely
    *contains* the file (the old behavior) silently pinned every forward
    return to whichever snapshot happened to be listed first, even when a
    later directory had weeks of newer bars -- this is why ``fwd_5d`` came
    back all-null against a chain panel that spanned dates past the stale
    directory's last close. Read every directory that has the symbol and
    keep whichever has the latest last-bar date.
    """
    best: pd.DataFrame | None = None
    best_max: pd.Timestamp | None = None
    for root in price_dirs:
        path = Path(root) / f"{symbol.upper()}.parquet"
        if not path.exists():
            continue
        df = _load_one_price_file(path)
        if df is None or df.empty:
            continue
        candidate_max = df.index.max()
        if best is None or candidate_max > best_max:
            best, best_max = df, candidate_max
    return best


def _try_yfinance_extend(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame | None:
    try:
        import yfinance as yf  # type: ignore
    except ImportError:
        return None
    try:
        hist = yf.Ticker(symbol).history(
            start=start.strftime("%Y-%m-%d"),
            end=(end + pd.Timedelta(days=2)).strftime("%Y-%m-%d"),
            auto_adjust=True,
        )
    except Exception:
        return None
    if hist is None or hist.empty:
        return None
    hist = hist.rename(columns={c: c.lower() for c in hist.columns})
    hist.index = pd.to_datetime(hist.index).tz_localize(None)
    return hist


def _chain_to_theory_rows(
    df: pd.DataFrame,
    *,
    spot: float,
    rate: float,
    max_dte: int,
    min_oi: int,
) -> tuple[list[dict[str, Any]], float, float]:
    """Return theory rows, call volume, put volume."""
    rows: list[dict[str, Any]] = []
    call_vol = 0.0
    put_vol = 0.0
    call_oi = 0.0
    put_oi = 0.0
    for rec in df.to_dict(orient="records"):
        right = _norm_right(rec.get("right") or rec.get("option_type"))
        strike = float(rec.get("strike") or 0)
        oi = float(rec.get("openInterest") or rec.get("open_interest") or 0)
        if not right or strike <= 0 or oi < min_oi:
            continue
        dte = rec.get("dte")
        if dte is None and rec.get("expiry") is not None:
            try:
                exp = pd.Timestamp(rec["expiry"]).tz_localize(None)
                asof = pd.Timestamp(rec.get("asof_date") or df["asof_date"].iloc[0]).tz_localize(None)
                dte = (exp.normalize() - asof.normalize()).days
            except Exception:
                dte = 30
        dte_f = float(dte if dte is not None else 30)
        if dte_f < 0 or dte_f > max_dte:
            continue
        iv = float(rec.get("impliedVolatility") or rec.get("iv") or 0)
        gamma = rec.get("gamma")
        if gamma is None or (isinstance(gamma, float) and (math.isnan(gamma) or gamma <= 0)):
            years = max(dte_f, 0.5) / 365.0
            gamma = bs_gamma(spot=spot, strike=strike, years=years, iv=iv, rate=rate)
        if gamma is None or gamma <= 0:
            continue
        vol = float(rec.get("volume") or 0)
        if right == "call":
            call_vol += vol
            call_oi += oi
        else:
            put_vol += vol
            put_oi += oi
        rows.append({
            "right": right,
            "strike": strike,
            "gamma": float(gamma),
            "open_interest": oi,
            "multiplier": float(rec.get("multiplier") or 100),
            "dte": dte_f,
        })
    # Prefer session volume imbalance; fall back to OI imbalance when volume is empty.
    tot_vol = call_vol + put_vol
    if tot_vol > 0:
        return rows, call_vol, put_vol
    return rows, call_oi, put_oi


def _forward_returns(prices: pd.DataFrame, asof: pd.Timestamp, horizons: tuple[int, ...]) -> dict[str, float | None]:
    """Close-to-close forward returns from the last session ≤ asof."""
    idx = prices.index
    eligible = idx[idx <= asof]
    if len(eligible) == 0:
        return {f"fwd_{h}d": None for h in horizons}
    t0 = eligible[-1]
    c0 = float(prices.loc[t0, "close"])
    if c0 <= 0:
        return {f"fwd_{h}d": None for h in horizons}
    # sessions after t0
    after = idx[idx > t0]
    out: dict[str, float | None] = {}
    for h in horizons:
        if len(after) < h:
            out[f"fwd_{h}d"] = None
        else:
            c1 = float(prices.loc[after[h - 1], "close"])
            out[f"fwd_{h}d"] = c1 / c0 - 1.0
    out["signal_session"] = t0.strftime("%Y-%m-%d")
    return out


def _hit(score: float, fwd: float | None, threshold: float) -> bool | None:
    try:
        score_f = float(score)
        fwd_f = float(fwd) if fwd is not None else float("nan")
    except (TypeError, ValueError):
        return None
    # DataFrame row iteration turns missing optional returns into NaN. Treat
    # them as censored observations, never as automatic misses.
    if not math.isfinite(score_f) or not math.isfinite(fwd_f) or abs(score_f) < threshold:
        return None
    if score_f >= threshold:
        return fwd_f > 0
    if score_f <= -threshold:
        return fwd_f < 0
    return None


def evaluate_universe(cfg: SqueezeValidationConfig) -> dict[str, Any]:
    chain_root = Path(cfg.chain_root)
    price_dirs = [Path(p) for p in cfg.price_dirs]
    date_dirs = sorted([p for p in chain_root.iterdir() if p.is_dir() and p.name.startswith("date=")])
    if not date_dirs:
        raise FileNotFoundError(f"no option chain dates under {chain_root}")

    records: list[dict[str, Any]] = []
    for ddir in date_dirs:
        asof_str = ddir.name.split("=", 1)[1]
        asof = pd.Timestamp(asof_str)
        for path in sorted(ddir.glob("*.parquet")):
            symbol = path.stem.upper()
            try:
                cdf = pd.read_parquet(path)
            except Exception as exc:
                records.append({"symbol": symbol, "asof": asof_str, "error": f"chain_read:{exc}"})
                continue
            if cdf.empty:
                continue
            spot = float(cdf["spot"].dropna().iloc[0]) if "spot" in cdf.columns and cdf["spot"].notna().any() else 0.0
            prices = _load_price(symbol, price_dirs)
            if prices is None or prices.empty:
                records.append({"symbol": symbol, "asof": asof_str, "error": "no_price_history"})
                continue

            # Extend with yfinance if we need forward returns past local data
            last_px = prices.index.max()
            if cfg.fetch_missing_forward and last_px < asof + pd.Timedelta(days=max(cfg.forward_horizons) + 5):
                extra = _try_yfinance_extend(
                    symbol,
                    start=last_px - pd.Timedelta(days=5),
                    end=asof + pd.Timedelta(days=max(cfg.forward_horizons) + 10),
                )
                if extra is not None and not extra.empty:
                    prices = pd.concat([prices, extra])
                    prices = prices[~prices.index.duplicated(keep="last")].sort_index()

            # Momentum / ADV as of last session ≤ asof
            hist = prices.loc[prices.index <= asof]
            if len(hist) < cfg.momentum_lookback + 1:
                # fall back to full history end
                hist = prices
            if len(hist) < 2:
                records.append({"symbol": symbol, "asof": asof_str, "error": "insufficient_price"})
                continue
            if spot <= 0:
                spot = float(hist["close"].iloc[-1])

            close = hist["close"].astype(float)
            mom_n = min(cfg.momentum_lookback, len(close) - 1)
            momentum = float(close.iloc[-1] / close.iloc[-(mom_n + 1)] - 1.0)
            vol = hist["volume"].astype(float) if "volume" in hist.columns else pd.Series(0.0, index=hist.index)
            dollar = (close * vol).replace([np.inf, -np.inf], np.nan).dropna()
            adv = float(dollar.tail(cfg.adv_window).mean()) if len(dollar) else 0.0

            theory_rows, call_vol, put_vol = _chain_to_theory_rows(
                cdf,
                spot=spot,
                rate=cfg.risk_free_rate,
                max_dte=cfg.max_dte,
                min_oi=cfg.min_open_interest,
            )
            tot_vol = call_vol + put_vol
            contract_right_imb = (call_vol - put_vol) / tot_vol if tot_vol > 0 else 0.0
            # Historical chains have no aggressor. Score the shipped directional
            # term on a causal bar signed-volume proxy and keep only post-shift mass.
            signed_flow_imb = 0.0
            flow_shift_payload = None
            bar_hist = hist
            hourly_path = EDGE_ROOT / "data" / "1h" / f"{symbol}.parquet"
            if hourly_path.exists():
                try:
                    hdf = pd.read_parquet(hourly_path)
                    if not isinstance(hdf.index, pd.DatetimeIndex):
                        for col in ("Date", "date", "timestamp"):
                            if col in hdf.columns:
                                hdf = hdf.set_index(col)
                                break
                    hdf.index = pd.to_datetime(hdf.index).tz_localize(None)
                    end = asof.normalize() + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
                    hdf = hdf.loc[hdf.index <= end]
                    cols = {c.lower(): c for c in hdf.columns}
                    hdf = hdf.rename(columns={cols[w]: w for w in ("open", "high", "low", "close", "volume") if w in cols})
                    if len(hdf) >= 8 and all(c in hdf.columns for c in ("open", "high", "low", "close", "volume")):
                        bar_hist = hdf
                except Exception:
                    bar_hist = hist
            try:
                if all(col in bar_hist.columns for col in ("open", "high", "low", "close", "volume")):
                    obs = signed_observations_from_bars(bar_hist)
                    if obs:
                        last_bar = pd.Timestamp(bar_hist.index.max())
                        age_days = float((asof.normalize() - last_bar.normalize()).days)
                        flow = current_flow_after_shift(obs, last_age=age_days, max_fresh_age=2.0)
                        signed_flow_imb = float(flow.effective_imbalance)
                        flow_shift_payload = flow.to_dict()
            except (KeyError, ValueError):
                signed_flow_imb = 0.0
                flow_shift_payload = None

            if not theory_rows:
                records.append({"symbol": symbol, "asof": asof_str, "error": "no_theory_rows"})
                continue

            theory = compute_theory_squeeze(
                chain_rows=theory_rows,
                spot=spot,
                adv_notional=adv,
                call_imbalance=signed_flow_imb,
                momentum=momentum,
                score_scale=cfg.score_scale,
            )

            # Baselines
            mom_score = 100.0 * math.tanh(cfg.score_scale * abs(momentum)) * (1.0 if momentum >= 0 else -1.0)
            sr = float(theory["squeeze_risk"] or 0.0)
            fuel_signed = 100.0 * math.tanh(cfg.score_scale * sr * abs(momentum)) * (
                1.0 if momentum >= 0 else -1.0
            )

            fwd = _forward_returns(prices, asof=asof, horizons=cfg.forward_horizons)
            score = float(theory["squeeze_score"])

            rec: dict[str, Any] = {
                "symbol": symbol,
                "asof": asof_str,
                "spot": spot,
                "n_contracts": len(theory_rows),
                "call_volume": call_vol,
                "put_volume": put_vol,
                "call_imbalance": signed_flow_imb,
                "directional_flow_imbalance": signed_flow_imb,
                "flow_shift": flow_shift_payload,
                "confidence_band": (flow_shift_payload or {}).get("confidence_band"),
                "contract_right_imbalance": contract_right_imb,
                "momentum": momentum,
                "adv": adv,
                "theory_score": score,
                "theory_label": theory["squeeze_label"],
                "squeeze_risk": sr,
                "bullish_ui": theory.get("bullish_ui"),
                "bearish_ui": theory.get("bearish_ui"),
                "short_premium_gex_m": (theory.get("short_premium_gex_m") or {}).get("total_gex_m"),
                "atm_share": (theory.get("short_premium_gex_m") or {}).get("atm_share"),
                "weighted_dte": (theory.get("short_premium_gex_m") or {}).get("weighted_dte"),
                "mom_score": mom_score,
                "fuel_signed_score": fuel_signed,
                **{k: v for k, v in fwd.items() if k != "signal_session"},
                "signal_session": fwd.get("signal_session"),
            }
            for h in cfg.forward_horizons:
                key = f"fwd_{h}d"
                rec[f"hit_theory_{h}d"] = _hit(score, rec.get(key), cfg.score_threshold)
                rec[f"hit_mom_{h}d"] = _hit(mom_score, rec.get(key), cfg.score_threshold)
                rec[f"hit_fuel_{h}d"] = _hit(fuel_signed, rec.get(key), cfg.score_threshold)
            records.append(rec)

    panel = pd.DataFrame.from_records(records)
    summary = _summarize(panel, cfg)
    train_oos, summary_updates = _score_train_oos(panel, cfg)
    summary.update(summary_updates)
    return {
        "config": asdict(cfg),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_records": int(len(panel)),
        "n_errors": int(panel["error"].notna().sum()) if "error" in panel.columns else 0,
        "summary": summary,
        "train_oos": train_oos,
        "panel": panel,
    }


def _score_train_oos(
    panel: pd.DataFrame, cfg: SqueezeValidationConfig
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Fit the walk-forward train/OOS block from a scored theory-score panel.

    Returns ``(train_oos, summary_updates)``: ``train_oos`` is the full
    ``evaluate_train_oos`` result (or the synthesized error block below),
    and ``summary_updates`` holds just the ``"train"``/``"oos"`` keys meant
    to be merged into the caller's summary dict. Split out of
    ``evaluate_universe`` so the failure-surfacing behavior here (the
    ``except`` clause) is unit-testable without a full option-chain
    fixture tree.
    """
    train_oos: dict[str, Any] | None = None
    summary_updates: dict[str, Any] = {}
    try:
        from edge.research.squeeze_flow_eval import (
            SqueezeFlowEvalConfig,
            evaluate_train_oos,
        )

        scored = panel[panel["error"].isna()].copy() if "error" in panel.columns else panel.copy()
        if not scored.empty and "theory_score" in scored.columns and "fwd_1d" in scored.columns:
            eval_panel = scored.rename(columns={"theory_score": "eval_score"})
            if "asof" in eval_panel.columns:
                eval_panel["asof"] = pd.to_datetime(eval_panel["asof"])
            if "confidence_band" not in eval_panel.columns:
                eval_panel["confidence_band"] = "medium"
            if "label_end" not in eval_panel.columns:
                eval_panel["label_end"] = eval_panel["asof"] + pd.tseries.offsets.BDay(max(cfg.forward_horizons))
            train_oos = evaluate_train_oos(
                eval_panel,
                cfg=SqueezeFlowEvalConfig(
                    # `label_horizon` is metadata only here (`label_end` is
                    # already set above); evaluate_train_oos pins its own
                    # walk-forward geometry to the horizon it actually scores
                    # (SCORE_LABEL_HORIZON in squeeze_flow_eval.py) regardless
                    # of this value.
                    label_horizon=max(cfg.forward_horizons),
                    initial_train_dates=max(2, eval_panel["asof"].nunique() // 3),
                    validation_dates=max(2, eval_panel["asof"].nunique() // 3),
                    embargo_dates=1,
                    include_partial_final=True,
                    min_partial_validation_dates=1,
                    min_threshold_n=1,
                ),
            )
            summary_updates["train"] = train_oos.get("train")
            summary_updates["oos"] = train_oos.get("oos")
    except Exception as exc:
        # A real failure here must never vanish as a clean-looking empty
        # pass -- that is precisely the governance bug this module exists to
        # avoid. Surface the exception into the saved summary so a promotion
        # gate sees an explicit error status instead of zeros that read like
        # "evaluated, no edge".
        error_info = {"type": type(exc).__name__, "message": str(exc)}
        train_oos = {"status": "error", "oos_error": error_info, "train": None, "oos": None}
        summary_updates["train"] = {"status": "error", "oos_error": error_info}
        summary_updates["oos"] = {"status": "error", "oos_error": error_info}
    return train_oos, summary_updates


def _hit_rate(series: pd.Series) -> dict[str, Any]:
    valid = series.dropna()
    if valid.empty:
        return {"n": 0, "hit_rate": None, "hits": 0}
    hits = int(valid.astype(bool).sum())
    n = int(len(valid))
    return {"n": n, "hits": hits, "hit_rate": hits / n}


def _rank_ic(scores: pd.Series, rets: pd.Series) -> float | None:
    mask = scores.notna() & rets.notna()
    if mask.sum() < 8:
        return None
    return float(scores[mask].corr(rets[mask], method="spearman"))


def _top_bottom_hit(scores: pd.Series, rets: pd.Series, frac: float = 0.25) -> dict[str, Any]:
    """Hit rate of top/bottom score fraction vs return sign (direction-aware)."""
    mask = scores.notna() & rets.notna()
    s, r = scores[mask], rets[mask]
    n = len(s)
    if n < 8:
        return {"n": n, "top_hit": None, "bottom_hit": None, "long_short_mean": None}
    k = max(1, int(math.floor(n * frac)))
    order = s.sort_values()
    bottom = order.index[:k]
    top = order.index[-k:]
    top_rets = r.loc[top]
    bot_rets = r.loc[bottom]
    top_hit = float((top_rets > 0).mean()) if len(top_rets) else None
    bot_hit = float((bot_rets < 0).mean()) if len(bot_rets) else None
    ls = float(top_rets.mean() - bot_rets.mean()) if len(top_rets) and len(bot_rets) else None
    return {
        "n": n,
        "k": k,
        "top_hit_rate_up": top_hit,
        "bottom_hit_rate_down": bot_hit,
        "long_short_mean_return": ls,
        "top_mean_return": float(top_rets.mean()) if len(top_rets) else None,
        "bottom_mean_return": float(bot_rets.mean()) if len(bot_rets) else None,
    }


def _amplification_test(sr: pd.Series, rets: pd.Series) -> dict[str, Any]:
    """Does higher short-gamma fuel correlate with larger |forward moves|?"""
    mask = sr.notna() & rets.notna()
    if mask.sum() < 8:
        return {"n": int(mask.sum()), "rank_ic_sr_vs_abs_ret": None}
    return {
        "n": int(mask.sum()),
        "rank_ic_sr_vs_abs_ret": float(sr[mask].corr(rets[mask].abs(), method="spearman")),
        "mean_abs_ret_high_sr": float(rets[mask][sr[mask] >= sr[mask].median()].abs().mean()),
        "mean_abs_ret_low_sr": float(rets[mask][sr[mask] < sr[mask].median()].abs().mean()),
    }


def _summarize(panel: pd.DataFrame, cfg: SqueezeValidationConfig) -> dict[str, Any]:
    if panel.empty:
        return {"error": "empty_panel"}
    if "error" in panel.columns:
        ok = panel[panel["error"].isna()].copy()
    else:
        ok = panel.copy()

    out: dict[str, Any] = {
        "n_scored": int(len(ok)),
        "label_counts": ok["theory_label"].value_counts().to_dict() if "theory_label" in ok.columns and len(ok) else {},
        "score_quantiles": ok["theory_score"].quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.95]).to_dict() if len(ok) else {},
        "mean_squeeze_risk": float(ok["squeeze_risk"].mean()) if len(ok) and "squeeze_risk" in ok else None,
        "max_abs_theory_score": float(ok["theory_score"].abs().max()) if len(ok) else None,
        "horizons": {},
        "threshold_sweep": {},
    }
    # Multi-threshold hit rates (absolute scores are often small on mega-caps)
    for thr in (5.0, 10.0, 15.0, 20.0, float(cfg.score_threshold)):
        thr_key = f"thr_{thr:g}"
        out["threshold_sweep"][thr_key] = {}
        for h in cfg.forward_horizons:
            hits = ok.apply(
                lambda row: _hit(float(row.get("theory_score") or 0), row.get(f"fwd_{h}d"), thr),
                axis=1,
            ) if len(ok) else pd.Series(dtype=object)
            out["threshold_sweep"][thr_key][f"{h}d"] = _hit_rate(hits)

    for h in cfg.forward_horizons:
        horizon: dict[str, Any] = {
            "theory_hit": _hit_rate(ok.get(f"hit_theory_{h}d", pd.Series(dtype=object))),
            "momentum_baseline_hit": _hit_rate(ok.get(f"hit_mom_{h}d", pd.Series(dtype=object))),
            "fuel_x_mom_hit": _hit_rate(ok.get(f"hit_fuel_{h}d", pd.Series(dtype=object))),
            "rank_ic_theory": _rank_ic(ok["theory_score"], ok[f"fwd_{h}d"]) if f"fwd_{h}d" in ok.columns else None,
            "rank_ic_mom": _rank_ic(ok["mom_score"], ok[f"fwd_{h}d"]) if f"fwd_{h}d" in ok.columns else None,
            "mean_fwd_when_bullish": None,
            "mean_fwd_when_bearish": None,
        }
        if f"fwd_{h}d" in ok.columns:
            bull = ok[ok["theory_score"] >= cfg.score_threshold][f"fwd_{h}d"].dropna()
            bear = ok[ok["theory_score"] <= -cfg.score_threshold][f"fwd_{h}d"].dropna()
            horizon["mean_fwd_when_bullish"] = float(bull.mean()) if len(bull) else None
            horizon["mean_fwd_when_bearish"] = float(bear.mean()) if len(bear) else None
            horizon["n_bullish_signals"] = int((ok["theory_score"] >= cfg.score_threshold).sum())
            horizon["n_bearish_signals"] = int((ok["theory_score"] <= -cfg.score_threshold).sum())
            horizon["top_bottom_quartile"] = _top_bottom_hit(ok["theory_score"], ok[f"fwd_{h}d"], frac=0.25)
            horizon["mom_top_bottom_quartile"] = _top_bottom_hit(ok["mom_score"], ok[f"fwd_{h}d"], frac=0.25)
            horizon["amplification"] = _amplification_test(ok["squeeze_risk"], ok[f"fwd_{h}d"])
        out["horizons"][f"{h}d"] = horizon

    if len(ok):
        out["fire_rate"] = {
            "bullish_squeeze": float((ok["theory_label"] == "bullish_squeeze").mean()),
            "bearish_squeeze": float((ok["theory_label"] == "bearish_squeeze").mean()),
            "neutral": float((ok["theory_label"] == "neutral").mean()),
            "abs_score_ge_threshold": float((ok["theory_score"].abs() >= cfg.score_threshold).mean()),
            "abs_score_ge_5": float((ok["theory_score"].abs() >= 5).sum()) / len(ok),
            "abs_score_ge_10": float((ok["theory_score"].abs() >= 10).sum()) / len(ok),
        }
    out["caveats"] = [
        "OI snapshot is sparse historically (often single date); OI is assumed sticky for forward tests.",
        "Dealer inventory uses short-premium assumption q=−OI; true MM book is not observed.",
        "Theory score gates on momentum — always compare to momentum-only baseline hit rate / IC.",
        "Historical chains have no aggressor; signed flow is a causal 1h/1d signed-volume proxy with post-shift detection, never reconstructed tape.",
        "On mega-cap liquid names |GEX|/ADV is tiny by construction — absolute squeeze labels rarely fire; use rank IC + amplification.",
        "Small N cross-section: treat hit rates as descriptive, not a GO gate alone.",
    ]
    return out


def run_and_save(cfg: SqueezeValidationConfig | None = None) -> dict[str, Any]:
    cfg = cfg or SqueezeValidationConfig()
    result = evaluate_universe(cfg)
    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    panel: pd.DataFrame = result.pop("panel")
    panel_path = out_dir / "panel.parquet"
    summary_path = out_dir / "summary.json"
    panel.to_parquet(panel_path, index=False)
    payload = {**result, "panel_path": str(panel_path)}
    summary_path.write_text(json.dumps(payload, indent=2, default=str))
    # compact leaderboard
    if not panel.empty and "theory_score" in panel.columns:
        ok = panel[panel["error"].isna()] if "error" in panel.columns else panel
        top = ok.reindex(ok["theory_score"].abs().sort_values(ascending=False).index).head(25)
        top.to_csv(out_dir / "top_signals.csv", index=False)
    return payload


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Gamma squeeze theory validation")
    p.add_argument("--out-dir", type=str, default=str(DEFAULT_OUT))
    p.add_argument("--no-fetch", action="store_true", help="Do not call yfinance for missing forwards")
    p.add_argument("--threshold", type=float, default=15.0)
    args = p.parse_args()
    cfg = SqueezeValidationConfig(
        out_dir=args.out_dir,
        fetch_missing_forward=not args.no_fetch,
        score_threshold=args.threshold,
    )
    payload = run_and_save(cfg)
    print(json.dumps({k: payload[k] for k in ("n_records", "n_errors", "summary", "panel_path")}, indent=2, default=str))


if __name__ == "__main__":
    main()
