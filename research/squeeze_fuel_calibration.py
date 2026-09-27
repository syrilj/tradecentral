"""Backtest squeeze FUEL calibration candidates against realized forward |moves|.

Scope: the unsigned fuel leg only — squeeze_risk SR → fuel_ui = tanh(fuel_scale · SR).
Direction legs (signed flow × momentum) are explicitly out of scope.

Shipped theory (daily_plays/gex_core.py):

    SR      = |GEX⁻_1pct| / ADV · exp(-urgency_c · weighted_dte) · atm_share
    fuel_ui = tanh(fuel_scale · SR)          urgency_c = 0.05, fuel_scale = 40

Observed failure (NVDA, 2026-09-15): |GEX⁻|-weighted dte 64.5 d ⇒ urgency
exp(-0.05·64.5) = 0.0398 crushes liq 0.124 × atm 0.23 to SR ≈ 0.0011 ⇒
fuel ≈ 4–5% ⇒ panel reads "NO FUEL" on a mega-cap with billions of short dealer
gamma per 1% move. A long-dated tail drains the urgency of the *near* book that
actually rehedges intraday.

Candidates (SR variants; fuel = tanh(fuel_scale · SR) is a monotone display
transform, so rank metrics are computed on SR and fuel_scale is chosen after):

    base          shipped: liq · exp(-0.05 · dte_full) · atm
    c01_full / c02_full          milder urgency on full-book dte
    c05_near5 / c02_near5 / c01_near5   urgency on |GEX|-weighted dte of strikes
                                  within ±5% of spot (fallback: full-book dte)
    c05_front40 / c02_front40   urgency on dte of the front 40% of |GEX| by expiry
    c05_clip10    urgency on min(dte_full, 10)
    no_urgency    liq · atm (ablation)
    liq_only      liq (ablation)

Datasets: data/option_chains/date=*/SYMBOL.parquet snapshots. Two row
universes per snapshot:
  prod    production enrichment (BS gamma from IV when missing, NO dte/OI
          filters — matches options_intelligence._enrich_chain_for_theory)
  harness the prior validation filter (dte ≤ 45, OI ≥ 50) for comparability
          with runs/squeeze_validation
Prices: data/1d{,_wide}, latest-directory-wins loader. ADV = 20 sessions ≤ asof.
Forward close-to-close returns at 1/3/5 d from local prices only — late
snapshots are forward-censored, never fabricated.

Metrics per candidate:
  1. Pooled Spearman IC of SR vs |fwd_h|; PER-DATE cross-sectional IC averaged
     over dates (n≥8 names) — kills the size/vol cross-sectional confound.
  2. Vol-normalized IC: SR vs |fwd_1d| / EM_1d (EM = spot·median ATM IV/√365).
  3. Quintile means of |fwd_1d| + monotonicity score.
  4. Per-ADV-stratum IC (small < $0.5B, mid $0.5–2B, liquid ≥ $2B ADV).
  5. Display coverage with fuel_scale retuned so p90(SR) → fuel 0.85: pct of
     fuel < 0.05 (floor-pinned) and ≥ 0.10 / 0.35 (production copy gates).

Artifacts: runs/squeeze_fuel_calibration/panel.parquet + metrics.json.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from edge.daily_plays.gex_core import bs_gamma, short_premium_gex_1pct_m  # noqa: E402
from edge.research.squeeze_validation import (  # noqa: E402
    _forward_returns,
    _load_price,
    _norm_right,
)

EDGE_ROOT = Path(__file__).resolve().parents[1]
CHAIN_ROOT = EDGE_ROOT / "data" / "option_chains"
PRICE_DIRS = (EDGE_ROOT / "data" / "1d", EDGE_ROOT / "data" / "1d_wide")
OUT_DIR = EDGE_ROOT / "runs" / "squeeze_fuel_calibration"
HORIZONS = (1, 3, 5)
RATE = 0.045
ADV_WINDOW = 20
NEAR_BAND_PCT = 0.05
HARNESS_MAX_DTE = 45
HARNESS_MIN_OI = 50

CANDIDATES = {
    "base": {"c": 0.05, "dte": "full"},
    "c01_full": {"c": 0.01, "dte": "full"},
    "c02_full": {"c": 0.02, "dte": "full"},
    "c05_near5": {"c": 0.05, "dte": "near5"},
    "c02_near5": {"c": 0.02, "dte": "near5"},
    "c01_near5": {"c": 0.01, "dte": "near5"},
    "c05_front40": {"c": 0.05, "dte": "front40"},
    "c02_front40": {"c": 0.02, "dte": "front40"},
    "c05_clip10": {"c": 0.05, "dte": "clip10"},
    "no_urgency": {"c": 0.0, "dte": "full"},
    "liq_only": None,
}

DISPLAY_GATES = (0.05, 0.10, 0.35)


def _finite(x, default=None):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _enrich(df: pd.DataFrame, *, spot: float, asof: pd.Timestamp, rate: float,
            max_dte: float | None, min_oi: float):
    """Production-style enrichment; NaN OI/IV/gamma coerced instead of poisoning sums."""
    rows = []
    for rec in df.to_dict(orient="records"):
        right = _norm_right(rec.get("right") or rec.get("option_type"))
        strike = _finite(rec.get("strike"))
        if not right or not strike or strike <= 0:
            continue
        dte = _finite(rec.get("dte"))
        if dte is None and rec.get("expiry") is not None:
            try:
                dte = float((pd.Timestamp(rec["expiry"]).normalize() - asof.normalize()).days)
            except Exception:
                dte = None
        dte_f = dte if dte is not None else 30.0
        if max_dte is not None and (dte_f < 0 or dte_f > max_dte):
            continue
        oi = _finite(rec.get("openInterest") if rec.get("openInterest") is not None
                     else rec.get("open_interest"), 0.0)
        if oi < min_oi:
            continue
        iv = _finite(rec.get("impliedVolatility") if rec.get("impliedVolatility") is not None
                     else rec.get("iv"))
        gamma = _finite(rec.get("gamma"))
        if gamma is None or gamma <= 0:
            gamma = bs_gamma(spot=spot, strike=strike, years=max(dte_f, 0.5) / 365.0,
                             iv=iv or 0.0, rate=rate)
        if gamma is None or gamma <= 0:
            continue
        rows.append({
            "right": right, "strike": strike, "gamma": float(gamma),
            "open_interest": oi, "multiplier": _finite(rec.get("multiplier"), 100.0),
            "dte": dte_f, "iv": iv,
        })
    return rows


def _near_and_front_dte(rows, *, spot: float):
    """|GEX|-weighted DTE of the ±5% book and of the front 40% of |GEX| by expiry."""
    w_near = s_near = 0.0
    front = []
    for r in rows:
        oi, gamma = r["open_interest"], r["gamma"]
        if oi <= 0 or gamma <= 0:
            continue
        dg_m = oi * r["multiplier"] * gamma * spot * spot * 0.01 / 1_000_000.0
        w = abs(dg_m)
        front.append((r["dte"], w))
        if abs(r["strike"] - spot) <= NEAR_BAND_PCT * spot:
            w_near += w
            s_near += r["dte"] * w
    near = (s_near / w_near) if w_near > 1e-12 else None
    front.sort(key=lambda t: t[0])
    total = sum(w for _, w in front)
    f40 = None
    if total > 1e-12:
        cap = 0.40 * total
        acc = s_f = w_f = 0.0
        for dte, w in front:
            if acc >= cap:
                break
            acc += w
            s_f += dte * w
            w_f += w
        f40 = (s_f / w_f) if w_f > 1e-12 else None
    return near, f40


def _atm_iv_em1d(rows, *, spot: float):
    ivs = [r["iv"] for r in rows
           if r["iv"] and 0 < r["iv"] < 5.0 and abs(r["strike"] - spot) <= 0.02 * spot
           and 1 <= r["dte"] <= 21]
    if not ivs:
        return None, None
    atm_iv = float(np.median(ivs))
    return atm_iv, spot * atm_iv / math.sqrt(365.0)


def build_panel() -> pd.DataFrame:
    records = []
    date_dirs = sorted(p for p in CHAIN_ROOT.iterdir() if p.is_dir() and p.name.startswith("date="))
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
            prices = _load_price(symbol, PRICE_DIRS)
            if prices is None or prices.empty or spot <= 0:
                records.append({"symbol": symbol, "asof": asof_str, "error": "no_price_or_spot"})
                continue
            end = asof.normalize() + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
            hist = prices.loc[prices.index <= end]
            if len(hist) < ADV_WINDOW:
                records.append({"symbol": symbol, "asof": asof_str, "error": "thin_price_history"})
                continue
            dollar = hist["close"] * hist.get("volume", hist["close"] * 0)
            adv = float(dollar.tail(ADV_WINDOW).mean())
            adv_m = adv / 1_000_000.0
            fwd = _forward_returns(prices, asof=asof, horizons=HORIZONS)
            rec = {
                "symbol": symbol, "asof": asof_str, "spot": spot, "adv_m": adv_m,
                "atm_iv": None, "em_1d": None,
            }
            for h in HORIZONS:
                rec[f"fwd_{h}d"] = fwd.get(f"fwd_{h}d")
            if adv <= 0:
                rec["error"] = "no_adv"
                records.append(rec)
                continue
            for tag, max_dte, min_oi in (
                ("prod", None, 0.0),
                ("harness", HARNESS_MAX_DTE, HARNESS_MIN_OI),
            ):
                rows = _enrich(cdf, spot=spot, asof=asof, rate=RATE,
                               max_dte=max_dte, min_oi=min_oi)
                gex = short_premium_gex_1pct_m(rows, spot=spot)
                dte_near, dte_f40 = _near_and_front_dte(rows, spot=spot)
                rec[f"{tag}_liq"] = abs(gex["total_gex_m"]) / adv_m if adv_m > 0 else None
                rec[f"{tag}_atm_share"] = gex["atm_share"]
                rec[f"{tag}_dte_full"] = gex["weighted_dte"] if gex["abs_gex_m"] > 0 else None
                rec[f"{tag}_dte_near5"] = dte_near
                rec[f"{tag}_dte_front40"] = dte_f40
                rec[f"{tag}_neg_gex_1pct_m"] = gex["total_gex_m"]
                rec[f"{tag}_abs_gex_m"] = gex["abs_gex_m"]
                rec[f"{tag}_n_contracts"] = len(rows)
            prod_rows = _enrich(cdf, spot=spot, asof=asof, rate=RATE, max_dte=None, min_oi=0.0)
            atm_iv, em_1d = _atm_iv_em1d(prod_rows, spot=spot)
            rec["atm_iv"] = atm_iv
            rec["em_1d"] = em_1d
            records.append(rec)
    return pd.DataFrame(records)


def _sr_cols(rec, tag, spec):
    liq = rec.get(f"{tag}_liq")
    atm = rec.get(f"{tag}_atm_share")
    if liq is None or not math.isfinite(liq) or atm is None:
        return float("nan")
    if spec is None:
        return liq
    c, dkey = spec["c"], spec["dte"]
    if dkey == "clip10":
        t = rec.get(f"{tag}_dte_full")
        if t is None or not math.isfinite(t):
            return float("nan")
        t = min(t, 10.0)
    else:
        t = rec.get(f"{tag}_dte_full") if dkey == "full" else rec.get(f"{tag}_dte_{dkey}")
    if t is None or not math.isfinite(t):
        # near/front book empty → fall back to the full-book weighting
        t = rec.get(f"{tag}_dte_full")
        if t is None or not math.isfinite(t):
            return float("nan")
    return liq * math.exp(-c * t) * atm


def _spearman(x: pd.Series, y: pd.Series, min_n: int = 12):
    ok = x.notna() & y.notna()
    if ok.sum() < min_n or x[ok].nunique() < 5 or y[ok].nunique() < 5:
        return None, int(ok.sum())
    from scipy.stats import spearmanr
    return float(spearmanr(x[ok].astype(float), y[ok].astype(float)).statistic), int(ok.sum())


def _per_date_ic(df: pd.DataFrame, sr: pd.Series, ycol: pd.Series, min_names: int = 8):
    vals = []
    for asof, grp in df.groupby("asof"):
        rho, n = _spearman(sr.loc[grp.index], ycol.loc[grp.index], min_n=min_names)
        if rho is not None:
            vals.append(rho)
    return (float(np.mean(vals)) if vals else None, len(vals))


def evaluate(panel: pd.DataFrame) -> dict:
    ok = panel[panel["error"].isna()].copy()
    out = {"n_records": int(len(ok)), "n_symbols": int(ok["symbol"].nunique()),
           "n_dates": int(ok["asof"].nunique()), "universes": {}}
    for tag in ("prod", "harness"):
        sub = ok[ok[f"{tag}_liq"].notna()]
        ures = {"n": int(len(sub)), "candidates": {}}
        for name, spec in CANDIDATES.items():
            sr = pd.Series([_sr_cols(r, tag, spec) for _, r in sub.iterrows()],
                           index=sub.index, dtype=float)
            res = {"n_nan_sr": int(sr.isna().sum())}
            for h in HORIZONS:
                abs_fwd = sub[f"fwd_{h}d"].astype(float).abs()
                rho, n = _spearman(sr, abs_fwd)
                res[f"ic_{h}d"] = rho
                res[f"n_{h}d"] = n
                ic_pd, nd = _per_date_ic(sub, sr, abs_fwd)
                res[f"ic_xs_{h}d"] = ic_pd
                res[f"n_dates_{h}d"] = nd
            # vol-normalized 1d move
            vn = (sub["fwd_1d"].astype(float).abs()
                  / (sub["em_1d"].astype(float) / sub["spot"].astype(float)))
            rho, n = _spearman(sr, vn)
            res["ic_vn_1d"] = rho
            res["n_vn_1d"] = n
            ic_pd, nd = _per_date_ic(sub, sr, vn)
            res["ic_xs_vn_1d"] = ic_pd
            res["n_dates_vn_1d"] = nd
            # per-SYMBOL time-series IC (vs vol-normalized move) — removes the
            # cross-sectional book-depth confound entirely
            ts_vals = []
            for sym, grp in sub.groupby("symbol"):
                rho_s, n_s = _spearman(sr.loc[grp.index], vn.loc[grp.index], min_n=5)
                if rho_s is not None:
                    ts_vals.append(rho_s)
            res["ic_ts_vn_1d"] = float(np.mean(ts_vals)) if ts_vals else None
            res["n_symbols_ts"] = len(ts_vals)
            # tail-move enrichment: top vs bottom SR quintile share of
            # |fwd_1d| > 2 × EM_1d (a "beyond-priced" squeeze day)
            mt = sr.notna() & vn.notna() & np.isfinite(vn)
            if mt.sum() >= 25:
                dft = pd.DataFrame({"sr": sr[mt], "v": vn[mt]})
                dft["q"] = pd.qcut(dft["sr"].rank(method="first"), 5, labels=False)
                tail = dft["v"] > 2.0
                res["tail2x_em_top_q"] = float(tail[dft["q"] == 4].mean())
                res["tail2x_em_bottom_q"] = float(tail[dft["q"] == 0].mean())
                res["tail2x_em_n"] = int(mt.sum())
            # quintile monotonicity on 1d
            m = sr.notna() & sub["fwd_1d"].notna()
            if m.sum() >= 25:
                dfq = pd.DataFrame({"sr": sr[m], "a": sub.loc[m, "fwd_1d"].astype(float).abs()})
                dfq["q"] = pd.qcut(dfq["sr"].rank(method="first"), 5, labels=False)
                qmean = dfq.groupby("q")["a"].mean()
                from scipy.stats import spearmanr
                res["quintile_mean_absret_1d"] = {int(k): float(v) for k, v in qmean.items()}
                res["mono_1d"] = float(spearmanr(qmean.index, qmean.values).statistic)
            # ADV strata pooled IC 1d
            res["by_adv_stratum_ic_1d"] = {}
            for sname, mask in (
                ("small", sub["adv_m"] < 500),
                ("mid", (sub["adv_m"] >= 500) & (sub["adv_m"] < 2000)),
                ("liquid", sub["adv_m"] >= 2000),
            ):
                rho, n = _spearman(sr[mask], sub.loc[mask, "fwd_1d"].astype(float).abs())
                res["by_adv_stratum_ic_1d"][sname] = {"ic": rho, "n": n}
            # SR quantiles + display mapping
            srq = sr.dropna()
            if len(srq):
                qs = {str(q): float(srq.quantile(q)) for q in (0.25, 0.5, 0.75, 0.9, 0.95)}
                res["sr_quantiles"] = qs
                res["fuel_at_shipped_scale_40"] = {
                    "median": float(math.tanh(40.0 * qs["0.5"])),
                    "p90": float(math.tanh(40.0 * qs["0.9"])),
                    "pct_lt_0.05": float(srq.map(lambda v: math.tanh(40.0 * v) < 0.05).mean()),
                }
                p90 = qs["0.9"]
                if p90 > 1e-9:
                    fs = math.atanh(0.85) / p90
                    res["fuel_scale_tuned"] = fs
                    fuel = srq.map(lambda v: math.tanh(fs * v))
                    res["fuel_tuned"] = {"median": float(fuel.quantile(0.5)),
                                         "p90": float(fuel.quantile(0.9))}
                    for g in DISPLAY_GATES:
                        res["fuel_tuned"][f"pct_lt_{g}"] = float((fuel < g).mean())
            ures["candidates"][name] = res
        out["universes"][tag] = ures
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    panel = build_panel()
    panel.to_parquet(OUT_DIR / "panel.parquet", index=False)
    n_err = int(panel["error"].notna().sum())
    print(f"panel rows={len(panel)} errors={n_err} scored={len(panel) - n_err}")

    metrics = evaluate(panel)
    metrics["generated_at"] = pd.Timestamp.utcnow().isoformat()
    (OUT_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))

    for tag in ("prod", "harness"):
        print(f"\n=== universe: {tag} (n={metrics['universes'][tag]['n']}) ===")
        print("candidate          ic_1d    n    xs_ic1 dts  vn_ic1  xs_vn  ts_vn tsym tail_top tail_bot  medFuel@tuned pinT<5%")
        for name, res in metrics["universes"][tag]["candidates"].items():
            def f(k):
                v = res.get(k)
                return f"{v:+.3f}" if isinstance(v, float) else "  --  "
            ft = res.get("fuel_tuned") or {}
            print(f"{name:<18} {f('ic_1d')} {res.get('n_1d', 0):>4} "
                  f"{f('ic_xs_1d')} {res.get('n_dates_1d', 0):>3} "
                  f"{f('ic_vn_1d')} {f('ic_xs_vn_1d')} {f('ic_ts_vn_1d')} "
                  f"{res.get('n_symbols_ts', 0):>4} "
                  f"{f('tail2x_em_top_q')} {f('tail2x_em_bottom_q')} "
                  f"{ft.get('median', 0.0):.2f} "
                  f"{ft.get('pct_lt_0.05', 0.0):.2f}")

    # NVDA worked-example reproduction (latest snapshot)
    nv = panel[(panel["symbol"] == "NVDA") & panel["error"].isna()]
    if not nv.empty:
        r = nv.sort_values("asof").iloc[-1]
        liq = r["prod_liq"]
        atm = r["prod_atm_share"]
        dtef = r["prod_dte_full"]
        urg = math.exp(-0.05 * dtef)
        sr = liq * urg * atm
        print(f"\nNVDA {r['asof']} (prod rows={r['prod_n_contracts']}): "
              f"spot={r['spot']:.2f} ADV=${r['adv_m'] / 1e3:.2f}B "
              f"|GEX-|=${-r['prod_neg_gex_1pct_m'] / 1e3:.2f}B/1% liq={liq:.4f} "
              f"atm_share={atm:.3f} dte_full={dtef:.1f} near5={r['prod_dte_near5'] and round(r['prod_dte_near5'], 1)} "
              f"front40={r['prod_dte_front40'] and round(r['prod_dte_front40'], 1)}")
        print(f"  urgency={urg:.4f} SR={sr:.5f} fuel@40={math.tanh(40.0 * sr) * 100:.1f}%")
        for name in ("c05_near5", "c02_near5", "c05_front40", "no_urgency"):
            v = _sr_cols(r, "prod", CANDIDATES[name])
            print(f"  {name}: SR={v:.5f} fuel@40={math.tanh(40.0 * v) * 100:.1f}%")
    print(f"\nartifacts → {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
