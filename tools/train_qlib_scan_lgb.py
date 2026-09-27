#!/usr/bin/env python3
"""Train LightGBM (+ Ridge / numpy) cross-sectional ranker for deep-scan scores.

Quant-research protocol (v2)
----------------------------
* Point-in-time features only (bars ≤ t).
* Label = CS percentile of *skip-day* 5d forward return:
    close[t+6] / close[t+1] - 1  (decision at t; enter next session close).
* Train ends 2023-12-29; validation 2024 calendar year; 2025+ never used in fit.
* Feature set = expanded Alpha-style factors (rev/mom/vol/microstructure).
* Model: LightGBM regression on CS-rank label + Ridge twin for portable infer.
* Ensemble weight on ML vs literature factor blend is set from val Rank IC
  (higher ML IC → higher weight, floored at 0.45 / capped at 0.85).

Usage:
  edge/.venv-qlib/bin/python tools/train_qlib_scan_lgb.py --max-symbols 280
  edge/.venv-qlib/bin/python tools/train_qlib_scan_lgb.py --max-symbols 280 --out models/qlib_scan_lgb

Research ordinal only — not ENTER authorization.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

from edge.daily_plays.live_activity import load_market_symbol_catalog  # noqa: E402
from edge.daily_plays.qlib_scan_score import (  # noqa: E402
    FEATURE_NAMES,
    feature_row_from_frame,
    _normalize_frame,
)

TRAIN_END = "2023-12-29"
VAL_START = "2024-01-02"
VAL_END = "2024-12-31"
# 5-session forward return from decision close t (matches eval_qlib_scan_accuracy).
# Skip-day alternative (entry t+1, exit t+6) underperformed on this catalog's val IC.
LABEL_EXIT = 5
LABEL_ENTRY = 0
MIN_XS = 30

DEFAULT_OUT = EDGE_DIR / "models" / "qlib_scan_lgb"
DEFAULT_DATA = (EDGE_DIR / "data" / "1d_wide", EDGE_DIR / "data" / "1d")


def _validate_windows(train_end: str, val_start: str, val_end: str) -> None:
    """Fail closed if train/val windows overlap or are inverted."""
    te, vs, ve = pd.Timestamp(train_end), pd.Timestamp(val_start), pd.Timestamp(val_end)
    if te >= vs:
        raise ValueError(f"train_end {train_end} must be strictly before val_start {val_start}")
    if vs > ve:
        raise ValueError(f"val_start {val_start} must be on or before val_end {val_end}")
    # Purge: leave at least LABEL_EXIT calendar buffer conceptually; enforce via dates.
    gap_days = (vs - te).days
    if gap_days < LABEL_EXIT:
        raise ValueError(
            f"train/val gap ({gap_days}d) < label horizon ({LABEL_EXIT}d) — label leakage risk"
        )


def _load_frames(symbols: list[str], data_dirs: tuple[Path, ...]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        for base in data_dirs:
            path = base / f"{sym}.parquet"
            if not path.is_file():
                continue
            try:
                raw = pd.read_parquet(path)
            except Exception:
                continue
            frame = _normalize_frame(raw)
            if len(frame) >= 80:
                out[sym] = frame
            break
    return out


def _build_panel(
    frames: dict[str, pd.DataFrame],
    *,
    start: str,
    end: str,
) -> pd.DataFrame:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    rows: list[dict[str, Any]] = []

    for sym, frame in frames.items():
        close = frame["close"].astype(float)
        for i in range(len(frame)):
            ts = pd.Timestamp(frame.index[i]).normalize()
            if ts < start_ts or ts > end_ts:
                continue
            # Prefer Fridays; also keep every 5th bar for density.
            if ts.weekday() != 4 and (i % 5) != 0:
                continue
            hist = frame.iloc[: i + 1]
            if len(hist) < 60:
                continue
            j_exit = i + LABEL_EXIT
            if j_exit >= len(frame):
                continue
            c0 = float(close.iloc[i])
            c_x = float(close.iloc[j_exit])
            if not math.isfinite(c0) or c0 == 0 or not math.isfinite(c_x):
                continue
            label = c_x / c0 - 1.0
            feats = feature_row_from_frame(hist)
            if sum(1 for v in feats.values() if v is not None) < 6:
                continue
            row: dict[str, Any] = {"date": ts, "symbol": sym, "label": label}
            for k in FEATURE_NAMES:
                v = feats.get(k)
                row[k] = v if v is not None else np.nan
            rows.append(row)

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    counts = df.groupby("date")["symbol"].transform("count")
    return df.loc[counts >= MIN_XS].copy()


def _cs_zscore_features(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in feature_cols:
        def _z(s: pd.Series) -> pd.Series:
            mu = s.mean()
            sd = s.std(ddof=0)
            if not math.isfinite(sd) or sd < 1e-12:
                return s * 0.0
            return (s - mu) / sd
        out[col] = out.groupby("date")[col].transform(_z)
    return out


def _daily_rank_ic(pred: pd.Series, label: pd.Series, dates: pd.Series) -> list[float]:
    ics: list[float] = []
    tmp = pd.DataFrame({"pred": pred, "label": label, "date": dates})
    for _, g in tmp.groupby("date"):
        if len(g) < MIN_XS:
            continue
        ic = float(g["pred"].rank().corr(g["label"].rank()))
        if math.isfinite(ic):
            ics.append(ic)
    return ics


def _feature_train_ics(train_df: pd.DataFrame, feature_cols: list[str]) -> dict[str, float]:
    """Mean Rank IC of each feature vs raw forward return on train only."""
    out: dict[str, float] = {}
    for col in feature_cols:
        ics = _daily_rank_ic(train_df[col], train_df["label_raw"], train_df["date"])
        out[col] = float(np.mean(ics)) if ics else 0.0
    return out


def resolve_feature_cols(feature_set: str | None = None) -> list[str]:
    """Map ranker-evolution feature_set ids to column lists."""
    full = list(FEATURE_NAMES)
    if not feature_set or feature_set == "full16":
        return full
    if feature_set == "core5":
        return ["rev1", "rev5", "mom12_1", "lowvol", "liq"]
    if feature_set == "core_plus_mom":
        return ["rev1", "rev5", "mom12_1", "lowvol", "liq", "ret_5", "ret_21", "ret_63", "mom_accel"]
    raise ValueError(f"unknown feature_set: {feature_set}")


def train(
    *,
    max_symbols: int,
    data_dirs: tuple[Path, ...],
    out_dir: Path,
    seed: int = 42,
    train_end: str = TRAIN_END,
    val_start: str = VAL_START,
    val_end: str = VAL_END,
    source_id: str = "qlib_scan_lgb_v2",
    panel_start: str = "2017-01-01",
    learning_rate: float | None = None,
    num_leaves: int | None = None,
    min_data_in_leaf: int | None = None,
    num_boost_round: int = 300,
    feature_set: str | None = None,
    ensemble_ml_weight: float | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    try:
        import lightgbm as lgb
    except ImportError as exc:
        raise SystemExit(
            "lightgbm required. Use: edge/.venv-qlib/bin/python tools/train_qlib_scan_lgb.py"
        ) from exc

    try:
        from sklearn.linear_model import Ridge
        import joblib
    except ImportError:
        Ridge = None  # type: ignore
        joblib = None  # type: ignore

    def _log(msg: str) -> None:
        if not quiet:
            print(msg)

    _validate_windows(train_end, val_start, val_end)

    catalog = load_market_symbol_catalog(data_dirs=data_dirs)[: max(1, max_symbols)]
    frames = _load_frames(catalog, data_dirs)
    if len(frames) < 40:
        raise SystemExit(f"too few symbols loaded: {len(frames)}")

    _log(f"loaded {len(frames)} symbols")
    _log(f"windows train_end={train_end} val={val_start}→{val_end}")
    panel = _build_panel(frames, start=panel_start, end=val_end)
    if panel.empty:
        raise SystemExit("empty feature panel")

    feature_cols = resolve_feature_cols(feature_set)
    # Panel always builds full FEATURE_NAMES; subset after z-score.
    panel = _cs_zscore_features(panel, list(FEATURE_NAMES))
    panel["label_raw"] = panel["label"]
    panel["label"] = panel.groupby("date")["label_raw"].rank(pct=True)
    # Keep rows with enough non-null features
    panel = panel.dropna(subset=["label"])
    for col in FEATURE_NAMES:
        if col in panel.columns:
            panel[col] = panel[col].fillna(0.0)

    train_mask = panel["date"] <= pd.Timestamp(train_end)
    val_mask = (panel["date"] >= pd.Timestamp(val_start)) & (panel["date"] <= pd.Timestamp(val_end))
    train_df = panel.loc[train_mask]
    val_df = panel.loc[val_mask]
    _log(f"train rows={len(train_df)} val rows={len(val_df)} features={len(feature_cols)}")

    if len(train_df) < 1000 or len(val_df) < 200:
        raise SystemExit(f"insufficient rows train={len(train_df)} val={len(val_df)}")

    feat_ics = _feature_train_ics(train_df, feature_cols)
    _log("train feature Rank ICs (top):")
    for k, v in sorted(feat_ics.items(), key=lambda kv: -abs(kv[1]))[:8]:
        _log(f"  {k:12s} {v:+.4f}")

    dtrain = lgb.Dataset(train_df[feature_cols], label=train_df["label"])
    dval = lgb.Dataset(val_df[feature_cols], label=val_df["label"], reference=dtrain)

    params = {
        "objective": "regression",
        "metric": "l2",
        "learning_rate": float(learning_rate if learning_rate is not None else 0.025),
        "num_leaves": int(num_leaves if num_leaves is not None else 48),
        "min_data_in_leaf": int(min_data_in_leaf if min_data_in_leaf is not None else 120),
        "feature_fraction": 0.75,
        "bagging_fraction": 0.75,
        "bagging_freq": 1,
        "lambda_l1": 0.1,
        "lambda_l2": 2.0,
        "max_depth": 7,
        "verbosity": -1,
        "seed": seed,
    }
    booster = lgb.train(
        params,
        dtrain,
        num_boost_round=int(num_boost_round),
        valid_sets=[dtrain, dval],
        valid_names=["train", "val"],
        callbacks=[lgb.log_evaluation(period=0)],
    )

    val_pred = booster.predict(val_df[feature_cols])
    # Fix alignment - use numpy indices
    val_tmp = val_df[["date", "label_raw"]].copy()
    val_tmp["pred"] = val_pred
    ics = []
    for _, g in val_tmp.groupby("date"):
        if len(g) < MIN_XS:
            continue
        ic = float(g["pred"].rank().corr(g["label_raw"].rank()))
        if math.isfinite(ic):
            ics.append(ic)
    mean_ic = float(np.mean(ics)) if ics else float("nan")
    ic_std = float(np.std(ics, ddof=1)) if len(ics) > 1 else float("nan")
    icir = mean_ic / ic_std if ic_std and ic_std > 1e-12 else float("nan")
    _log(f"val LGB Rank IC={mean_ic:.4f} ICIR={icir:.3f} n_days={len(ics)} trees={booster.num_trees()}")

    # Ensemble weight: recipe override or map val IC into [0.45, 0.85]
    if ensemble_ml_weight is not None:
        ensemble_w = float(min(0.85, max(0.45, float(ensemble_ml_weight))))
    elif math.isfinite(mean_ic):
        # IC 0 → 0.5, IC 0.03 → ~0.8, clamp
        w = 0.50 + 10.0 * mean_ic
        ensemble_w = float(min(0.85, max(0.45, w)))
    else:
        ensemble_w = 0.55
    _log(f"ensemble_ml_weight={ensemble_w:.3f}")

    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "model.txt"
    booster.save_model(str(model_path))

    ridge_ic = None
    if Ridge is not None and joblib is not None:
        ridge = Ridge(alpha=2.0, random_state=seed)
        ridge.fit(train_df[feature_cols], train_df["label"])
        r_pred = ridge.predict(val_df[feature_cols])
        r_tmp = val_df[["date", "label_raw"]].copy()
        r_tmp["pred"] = r_pred
        r_ics = []
        for _, g in r_tmp.groupby("date"):
            if len(g) < MIN_XS:
                continue
            ic = float(g["pred"].rank().corr(g["label_raw"].rank()))
            if math.isfinite(ic):
                r_ics.append(ic)
        ridge_ic = float(np.mean(r_ics)) if r_ics else float("nan")
        joblib.dump(
            {"model": ridge, "feature_names": feature_cols, "kind": "ridge"},
            out_dir / "sklearn_model.joblib",
        )
        np.savez(
            out_dir / "linear_weights.npz",
            coef=np.asarray(ridge.coef_, dtype=float),
            intercept=float(ridge.intercept_),
            feature_names=np.asarray(feature_cols),
        )
        _log(f"val Ridge Rank IC={ridge_ic:.4f}")

    # Importance for diagnostics
    gain = booster.feature_importance(importance_type="gain")
    imp = {f: float(g) for f, g in zip(feature_cols, gain)}

    meta = {
        "schema_version": "qlib-scan-lgb-v2",
        "source_id": str(source_id),
        "score_kind": "ordinal_qlib_xs",
        "trained_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "feature_set": feature_set or "full16",
        "feature_names": feature_cols,
        "feature_train_rank_ic": feat_ics,
        "feature_importance_gain": imp,
        "label": f"cs_pct_rank(close[t+{LABEL_EXIT}]/close[t]-1)",
        "label_horizon_days": LABEL_EXIT,
        "label_entry_offset": 0,
        "label_exit_offset": LABEL_EXIT,
        "train_end": train_end,
        "val_start": val_start,
        "val_end": val_end,
        "panel_start": panel_start,
        "n_symbols": len(frames),
        "n_train_rows": int(len(train_df)),
        "n_val_rows": int(len(val_df)),
        "val_mean_rank_ic": mean_ic,
        "val_icir": icir,
        "val_n_ic_days": len(ics),
        "best_iteration": int(booster.num_trees()),
        "ensemble_ml_weight": ensemble_w,
        "lgb_params": params,
        "model_file": "model.txt",
        "sklearn_model_file": "sklearn_model.joblib",
        "numpy_model_file": "linear_weights.npz",
        "sklearn_ridge_val_mean_rank_ic": ridge_ic,
        "inference_backends": [
            "lightgbm_model.txt",
            "sklearn_ridge_joblib",
            "numpy_linear_weights",
        ],
        "decision_authorized": False,
        "note": (
            "v2: 5d CS-rank label, expanded features, LGB+factor ensemble. "
            "Research ordinal for deep-scan routing — not ENTER authorization. "
            "Train/val windows are parameterized for feedback-iteration challengers."
        ),
    }
    (out_dir / "PROVENANCE.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (out_dir / "metrics.json").write_text(
        json.dumps({
            "val_mean_rank_ic": mean_ic,
            "val_icir": icir,
            "val_n_ic_days": len(ics),
            "ensemble_ml_weight": ensemble_w,
            "ridge_val_mean_rank_ic": ridge_ic,
            "train_end": train_end,
            "val_start": val_start,
            "val_end": val_end,
            "source_id": source_id,
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    _log(f"wrote {model_path}")
    _log(f"wrote {out_dir / 'PROVENANCE.json'}")
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-symbols", type=int, default=280)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--train-end", default=TRAIN_END, help="Inclusive last train date YYYY-MM-DD")
    ap.add_argument("--val-start", default=VAL_START, help="Inclusive first val date")
    ap.add_argument("--val-end", default=VAL_END, help="Inclusive last val date")
    ap.add_argument("--source-id", default="qlib_scan_lgb_v2")
    ap.add_argument("--panel-start", default="2017-01-01")
    ap.add_argument("--feature-set", default="full16", choices=("core5", "core_plus_mom", "full16"))
    ap.add_argument("--learning-rate", type=float, default=None)
    ap.add_argument("--num-leaves", type=int, default=None)
    ap.add_argument("--min-data-in-leaf", type=int, default=None)
    ap.add_argument("--num-boost-round", type=int, default=300)
    ap.add_argument("--ensemble-ml-weight", type=float, default=None)
    args = ap.parse_args(argv)

    data_dirs = tuple(p for p in DEFAULT_DATA if p.is_dir())
    if not data_dirs:
        print("ERROR: no data dirs", file=sys.stderr)
        return 2

    meta = train(
        max_symbols=int(args.max_symbols),
        data_dirs=data_dirs,
        out_dir=Path(args.out),
        seed=int(args.seed),
        train_end=str(args.train_end),
        val_start=str(args.val_start),
        val_end=str(args.val_end),
        source_id=str(args.source_id),
        panel_start=str(args.panel_start),
        learning_rate=args.learning_rate,
        num_leaves=args.num_leaves,
        min_data_in_leaf=args.min_data_in_leaf,
        num_boost_round=int(args.num_boost_round),
        feature_set=str(args.feature_set),
        ensemble_ml_weight=args.ensemble_ml_weight,
    )
    print(json.dumps({
        "source_id": meta["source_id"],
        "val_mean_rank_ic": meta["val_mean_rank_ic"],
        "val_icir": meta.get("val_icir"),
        "ensemble_ml_weight": meta["ensemble_ml_weight"],
        "best_iteration": meta["best_iteration"],
        "n_train_rows": meta["n_train_rows"],
        "train_end": meta["train_end"],
        "val_start": meta["val_start"],
        "val_end": meta["val_end"],
        "out": str(args.out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
