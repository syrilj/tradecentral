#!/usr/bin/env python3
"""Bakeoff for GATE_DESK_RANKER.md — one frozen recipe, skip-day labels.

Compares desk_ranker_v1 to the shipped FACTOR_WEIGHTS blend and, when the
artifact loads, the shipped qlib_scan_lgb linear twin. Does not search weights.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

EDGE_DIR = Path(__file__).resolve().parents[1]
ROOT = EDGE_DIR.parent
if "edge" not in sys.modules:
    _m = types.ModuleType("edge")
    _m.__path__ = [str(EDGE_DIR)]
    sys.modules["edge"] = _m
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EDGE_DIR))

from edge.daily_plays.desk_ranker import (  # noqa: E402
    ENTER_PERCENTILE,
    EXIT_PERCENTILE,
    HORIZON_DAYS,
    SOURCE_ID,
    classify_market_vol_regime,
    hysteresis_holdings,
    regime_weights,
)
from edge.daily_plays.qlib_scan_score import FACTOR_WEIGHTS  # noqa: E402
from edge.research.statistics import newey_west_tstat  # noqa: E402


DEV_START, DEV_END = "2022-01-18", "2023-12-29"
CONF_START, CONF_END = "2025-01-02", "2026-06-30"
ONE_WAY_COST = 0.0005  # 5 bp/side → 10 bp RT
MIN_XS = 30
DEFAULT_DATA = (EDGE_DIR / "data" / "1d_wide", EDGE_DIR / "data" / "1d")
DEFAULT_OUT = EDGE_DIR / "runs" / "desk_ranker"


def _cs_z(frame: pd.DataFrame) -> pd.DataFrame:
    ranks = frame.rank(axis=1)
    mean = ranks.mean(axis=1)
    std = ranks.std(axis=1).replace(0, np.nan)
    return ranks.sub(mean, axis=0).div(std, axis=0)


def _raw_cs_z(frame: pd.DataFrame) -> pd.DataFrame:
    mean = frame.mean(axis=1)
    std = frame.std(axis=1, ddof=0).replace(0, np.nan)
    return frame.sub(mean, axis=0).div(std, axis=0)


def _pct_ranks(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rank(axis=1, pct=True)


def _load_panels(data_dirs: tuple[Path, ...], max_symbols: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    closes: dict[str, pd.Series] = {}
    volumes: dict[str, pd.Series] = {}
    seen: set[str] = set()
    for base in data_dirs:
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.parquet")):
            symbol = path.stem.upper()
            if symbol in seen:
                continue
            if max_symbols and len(seen) >= max_symbols:
                break
            try:
                raw = pd.read_parquet(path)
            except Exception:
                continue
            raw = raw.rename(columns={str(c): str(c).lower() for c in raw.columns})
            if "close" not in raw.columns:
                continue
            if not isinstance(raw.index, pd.DatetimeIndex):
                raw.index = pd.to_datetime(raw.index, errors="coerce")
            raw = raw[~raw.index.isna()].sort_index()
            close = pd.to_numeric(raw["close"], errors="coerce")
            if close.dropna().shape[0] < 80:
                continue
            vol = (
                pd.to_numeric(raw["volume"], errors="coerce")
                if "volume" in raw.columns
                else pd.Series(np.nan, index=raw.index)
            )
            closes[symbol] = close
            volumes[symbol] = vol
            seen.add(symbol)
        if max_symbols and len(seen) >= max_symbols:
            break
    close_df = pd.DataFrame(closes).sort_index()
    vol_df = pd.DataFrame(volumes).reindex(close_df.index).sort_index()
    return close_df, vol_df


def _factor_frames(close: pd.DataFrame, volume: pd.DataFrame) -> dict[str, pd.DataFrame]:
    ret1 = close.pct_change(fill_method=None)
    return {
        "rev1": -ret1,
        "rev5": -close.pct_change(5, fill_method=None),
        "mom12_1": close.shift(21) / close.shift(252) - 1.0,
        "lowvol": -ret1.rolling(20).std(),
        "liq": -(close * volume).rolling(20).mean(),
        "ret_5": close.pct_change(5, fill_method=None),
        "ret_21": close.pct_change(21, fill_method=None),
        "ret_63": close.pct_change(63, fill_method=None),
    }


def _blend(z_map: dict[str, pd.DataFrame], weights: Mapping[str, float], dates: pd.DatetimeIndex) -> pd.DataFrame:
    acc = None
    wsum = None
    for name, weight in weights.items():
        z = z_map[name].reindex(dates)
        piece = z * float(weight)
        mask = z.notna().astype(float) * float(weight)
        acc = piece if acc is None else acc.add(piece, fill_value=0.0)
        wsum = mask if wsum is None else wsum.add(mask, fill_value=0.0)
    assert acc is not None and wsum is not None
    return acc.div(wsum.replace(0, np.nan))


def _skip_day_forward(close: pd.DataFrame, horizon: int = HORIZON_DAYS) -> pd.DataFrame:
    """As-of t, return from next close to the close ``horizon`` sessions after that."""
    return close.shift(-1 - horizon) / close.shift(-1) - 1.0


def _friday_index(index: pd.DatetimeIndex, start: str, end: str) -> pd.DatetimeIndex:
    window = index[(index >= pd.Timestamp(start)) & (index <= pd.Timestamp(end))]
    fridays = window[window.weekday == 4]
    return pd.DatetimeIndex(fridays)


def _daily_rank_ic(pred: pd.Series, fwd: pd.Series) -> float | None:
    aligned = pd.concat([pred, fwd], axis=1).dropna()
    if len(aligned) < MIN_XS:
        return None
    ic = float(aligned.iloc[:, 0].rank().corr(aligned.iloc[:, 1].rank()))
    return ic if math.isfinite(ic) else None


def _ic_stats(ics: list[float]) -> dict[str, Any]:
    arr = np.asarray(ics, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {"n": 0, "mean": None, "icir": None, "nw_t": None, "pct_pos": None}
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if arr.size > 1 else float("nan")
    return {
        "n": int(arr.size),
        "mean": mean,
        "icir": (mean / std) if std and math.isfinite(std) and std > 1e-12 else None,
        "nw_t": float(newey_west_tstat(arr, max_lags=5)),
        "pct_pos": float((arr > 0).mean()),
    }


def _one_way_turnover(old: set[str], new: set[str]) -> float:
    names = old | new
    if not names:
        return 0.0
    total = 0.0
    for name in names:
        w0 = (1.0 / len(old)) if old and name in old else 0.0
        w1 = (1.0 / len(new)) if new and name in new else 0.0
        total += abs(w1 - w0)
    return 0.5 * total


def _book_path(
    scores: pd.DataFrame,
    fwd: pd.DataFrame,
    dates: pd.DatetimeIndex,
) -> dict[str, Any]:
    held: set[str] = set()
    period_nets: list[float] = []
    period_gross: list[float] = []
    turnovers: list[float] = []
    n_names: list[int] = []
    for date in dates:
        if date not in scores.index:
            continue
        row = scores.loc[date].dropna()
        if len(row) < MIN_XS:
            continue
        nxt = hysteresis_holdings(row.to_dict(), held=held)
        turn = _one_way_turnover(held, nxt)
        cost = turn * (2.0 * ONE_WAY_COST)
        if not nxt:
            gross = 0.0
        else:
            rets = fwd.loc[date, list(nxt)].astype(float) if date in fwd.index else pd.Series(dtype=float)
            rets = rets[np.isfinite(rets)]
            if rets.empty:
                held = nxt
                continue
            gross = float(rets.mean())
        period_gross.append(gross)
        period_nets.append(gross - cost)
        turnovers.append(turn)
        n_names.append(len(nxt))
        held = nxt
    nets = np.asarray(period_nets, dtype=float)
    if nets.size == 0:
        return {"n_periods": 0, "net_mean": None, "gross_mean": None, "hit": None, "ann_turnover": None, "net_compound": None}
    weeks = max(nets.size, 1)
    return {
        "n_periods": int(nets.size),
        "net_mean": float(nets.mean()),
        "gross_mean": float(np.mean(period_gross)),
        "hit": float((nets > 0).mean()),
        "ann_turnover": float(np.mean(turnovers) * (252.0 / 5.0)) if turnovers else None,
        "net_compound": float(np.prod(1.0 + nets) - 1.0),
        "avg_names": float(np.mean(n_names)) if n_names else 0.0,
        "weeks_per_year_scale": 252.0 / 5.0,
        "net_ann": float((1.0 + float(nets.mean())) ** (252.0 / 5.0) - 1.0) if math.isfinite(float(nets.mean())) else None,
    }


def _load_linear_ranker() -> tuple[np.ndarray, float, list[str], float] | None:
    path = EDGE_DIR / "models" / "qlib_scan_lgb" / "linear_weights.npz"
    if not path.is_file():
        return None
    try:
        blob = np.load(path, allow_pickle=True)
        coef = np.asarray(blob["coef"], dtype=float)
        intercept = float(blob["intercept"])
        names = [str(x) for x in blob["feature_names"].tolist()]
        weight = 0.85
        prov = EDGE_DIR / "models" / "qlib_scan_lgb" / "PROVENANCE.json"
        if prov.is_file():
            meta = json.loads(prov.read_text(encoding="utf-8"))
            raw_w = meta.get("ensemble_ml_weight")
            if raw_w is not None:
                weight = float(min(1.0, max(0.0, float(raw_w))))
        return coef, intercept, names, weight
    except Exception:
        return None


def _linear_scores(
    z_map: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    coef: np.ndarray,
    intercept: float,
    names: list[str],
) -> pd.DataFrame:
    aligned = []
    for name in names:
        if name in z_map:
            aligned.append(z_map[name].reindex(dates).fillna(0.0))
        else:
            aligned.append(pd.DataFrame(0.0, index=dates, columns=z_map[next(iter(z_map))].columns))
    # stack last axis
    base_cols = aligned[0].columns
    acc = pd.DataFrame(intercept, index=dates, columns=base_cols)
    for weight, frame in zip(coef, aligned):
        acc = acc.add(frame.reindex(columns=base_cols) * float(weight), fill_value=0.0)
    return acc


def evaluate_window(
    *,
    close: pd.DataFrame,
    factors: dict[str, pd.DataFrame],
    fwd: pd.DataFrame,
    start: str,
    end: str,
    spy: pd.Series | None,
    linear: tuple[np.ndarray, float, list[str], float] | None,
) -> dict[str, Any]:
    dates = _friday_index(close.index, start, end)
    rank_z = {name: _cs_z(frame) for name, frame in factors.items()}
    raw_z = {name: _raw_cs_z(frame) for name, frame in factors.items()}
    shipped = _blend(raw_z, FACTOR_WEIGHTS, dates)

    desk_rows = []
    regimes: list[str] = []
    for date in dates:
        regime = classify_market_vol_regime(spy if spy is not None else close.mean(axis=1), asof=date)
        weights = regime_weights(regime)
        row = _blend(rank_z, weights, pd.DatetimeIndex([date])).loc[date]
        desk_rows.append(row)
        regimes.append(regime)
    desk = pd.DataFrame(desk_rows, index=dates)

    arms: dict[str, pd.DataFrame] = {
        SOURCE_ID: desk,
        "shipped_factor_blend": shipped,
    }
    if linear is not None:
        coef, intercept, names, ml_w = linear
        linear_raw = _linear_scores(raw_z, dates, coef, intercept, names)
        # Approximate the live LGB ensemble: rank-blend ML with the shipped factor
        # partner. This is the linear twin, not booster.model.txt.
        arms["shipped_lgb_linear_ensemble"] = (
            ml_w * _pct_ranks(linear_raw) + (1.0 - ml_w) * _pct_ranks(shipped)
        )

    report: dict[str, Any] = {
        "start": start,
        "end": end,
        "n_fridays": int(len(dates)),
        "regime_counts": {k: int(regimes.count(k)) for k in ("HIGH", "MEDIUM", "LOW")},
        "arms": {},
    }
    for name, scores in arms.items():
        ics: list[float] = []
        for date in dates:
            if date not in scores.index or date not in fwd.index:
                continue
            ic = _daily_rank_ic(scores.loc[date], fwd.loc[date])
            if ic is not None:
                ics.append(ic)
        report["arms"][name] = {
            "rank_ic": _ic_stats(ics),
            "book": _book_path(scores, fwd, dates),
        }
    return report


def _pass_dev(dev: dict[str, Any]) -> dict[str, Any]:
    desk = dev["arms"][SOURCE_ID]
    shipped = dev["arms"]["shipped_factor_blend"]
    desk_ic = desk["rank_ic"]["mean"]
    ship_ic = shipped["rank_ic"]["mean"]
    desk_net = desk["book"]["net_mean"]
    ship_net = shipped["book"]["net_mean"]
    turn = desk["book"]["ann_turnover"]
    checks = {
        "ic_beats_shipped_blend": bool(desk_ic is not None and ship_ic is not None and desk_ic > ship_ic),
        "net_beats_shipped_blend": bool(desk_net is not None and ship_net is not None and desk_net > ship_net),
        "turnover_under_20x": bool(turn is not None and turn < 20.0),
    }
    if "shipped_lgb_linear_ensemble" in dev["arms"]:
        lgb_ic = dev["arms"]["shipped_lgb_linear_ensemble"]["rank_ic"]["mean"]
        checks["ic_beats_shipped_lgb"] = bool(desk_ic is not None and lgb_ic is not None and desk_ic > lgb_ic)
    else:
        checks["ic_beats_shipped_lgb"] = None
    checks["pass"] = all(v is True for k, v in checks.items() if k != "ic_beats_shipped_lgb") and (
        checks["ic_beats_shipped_lgb"] in (True, None)
    )
    return checks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-symbols", type=int, default=0, help="0 = all local symbols")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    data_dirs = tuple(p for p in DEFAULT_DATA if p.is_dir())
    if not data_dirs:
        print("ERROR: no price directories", file=sys.stderr)
        return 2

    print(f"loading catalog from {', '.join(str(p) for p in data_dirs)}")
    close, volume = _load_panels(data_dirs, args.max_symbols)
    print(f"loaded {close.shape[1]} names x {close.shape[0]} days "
          f"({close.index.min().date()} .. {close.index.max().date()})")
    factors = _factor_frames(close, volume)
    fwd = _skip_day_forward(close)
    spy = close["SPY"] if "SPY" in close.columns else close.mean(axis=1)
    linear = _load_linear_ranker()
    print("linear twin:", "loaded" if linear else "missing")

    dev = evaluate_window(
        close=close, factors=factors, fwd=fwd,
        start=DEV_START, end=DEV_END, spy=spy, linear=linear,
    )
    conf = evaluate_window(
        close=close, factors=factors, fwd=fwd,
        start=CONF_START, end=CONF_END, spy=spy, linear=linear,
    )
    checks = _pass_dev(dev)
    payload = {
        "schema_version": "desk-ranker-bakeoff-v1",
        "source_id": SOURCE_ID,
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "hypothesis": "regime-conditioned rev5+mom12_1 beats shipped blend on skip-day IC and net@10bp",
        "label": f"close[t+1+{HORIZON_DAYS}]/close[t+1]-1",
        "enter_percentile": ENTER_PERCENTILE,
        "exit_percentile": EXIT_PERCENTILE,
        "one_way_cost": ONE_WAY_COST,
        "n_symbols": int(close.shape[1]),
        "development": dev,
        "confirmation_report_not_a_gate": conf,
        "checks": checks,
        "decision_authorized": False,
        "note": (
            "Confirmation window overlaps FACTOR_PROBE recent data for these two "
            "factors and is not a clean GO. Pass only replaces the ordinal scan score."
        ),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / "results.json"
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checks": checks, "dev": {k: v["rank_ic"] for k, v in dev["arms"].items()}}, indent=2))
    print(f"wrote {out_path}")
    return 0 if checks["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
