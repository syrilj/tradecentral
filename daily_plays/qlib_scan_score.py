"""Qlib-backed cross-sectional ordinal scores for deep-scan routing and Market tab.

This is a pure as-of scoring unit: given a symbol catalog and an as-of date it
returns {symbol: score/rank} using only bars available at that date. Scores are
research/ordinal — never calibrated probabilities or ENTER authorization.

Design
------
* Features match the five literature-signed factors registered in
  ``tools/factor_probe.py`` (rev1, rev5, mom12_1, lowvol, liq). Those formulas
  were chosen because short-term reversal and related effects are the load-
  bearing sanity check for the wide catalog that also feeds the qlib provider.
* Default path reads local daily parquet under ``data/1d_wide`` / ``data/1d``
  (the same source ingested into ``data/qlib_us_1d_wide``). Optional qlib
  provider backend can be forced when the package imports cleanly; deep scan
  never blocks on a full Alpha158 rebuild.
* Missing provider, missing bars, or init failure fail closed: empty scores,
  diagnostics populated, existing PEAD / activity / v90 paths untouched.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd


SCORE_KIND = "ordinal_qlib_xs"
# Default source when only the fixed-factor blend is available.
SOURCE_ID_FACTORS = "qlib_alpha_factor_probe_v1"
SOURCE_ID_LGB = "qlib_scan_lgb_v2"
SOURCE_ID = SOURCE_ID_FACTORS  # updated at runtime when LGB artifact loads
SCHEMA_VERSION = "qlib-scan-score-v1"

# Literature-signed factors from factor_probe.py (fallback blend weights).
FACTOR_WEIGHTS: dict[str, float] = {
    "rev5": 0.40,
    "rev1": 0.25,
    "mom12_1": 0.15,
    "lowvol": 0.12,
    "liq": 0.08,
}
# Full feature set for trained LGB / ensemble (must match train_qlib_scan_lgb.py).
FEATURE_NAMES: tuple[str, ...] = (
    "rev1", "rev5", "mom12_1", "lowvol", "liq",
    "ret_5", "ret_21", "ret_63", "mom_accel",
    "vol_20", "vol_ratio", "volume_z", "hl_range",
    "gap_open", "log_adv", "max_dd_21",
)
MIN_HISTORY_BARS = 60
# mom12_1 needs ~252 trading days of history; symbols without it still score
# on the short-horizon factors.
MOM_MIN_BARS = 260

# Trained LightGBM artifact (written by tools/train_qlib_scan_lgb.py).
_DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "qlib_scan_lgb"
_LGB_CACHE: dict[str, Any] = {"booster": None, "meta": None, "path": None, "error": None}


def _symbol(value: Any) -> str:
    return str(value or "").strip().upper().removesuffix(".US")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


import concurrent.futures

def _normalize_frame(raw: Any) -> pd.DataFrame:
    if not hasattr(raw, "columns") or not hasattr(raw, "index"):
        return pd.DataFrame()
    cols = list(raw.columns)
    col_map = {c: str(c).lower() for c in cols}
    if any(c != col_map[c] for c in cols):
        frame = raw.rename(columns=col_map)
    else:
        frame = raw.copy()
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(set(frame.columns)):
        return pd.DataFrame()
    if not isinstance(frame.index, pd.DatetimeIndex):
        for col in ("date", "datetime", "timestamp"):
            if col in frame.columns:
                frame = frame.set_index(col)
                break
        if not isinstance(frame.index, pd.DatetimeIndex):
            frame.index = pd.to_datetime(frame.index, errors="coerce")
    if frame.index.isna().any():
        frame = frame[~frame.index.isna()]
    if not frame.index.is_monotonic_increasing:
        frame = frame.sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        if not np.issubdtype(frame[col].dtype, np.number):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame.dropna(subset=["close"])


def _asof_ts(asof: str | pd.Timestamp | datetime | None) -> pd.Timestamp | None:
    if asof is None or asof == "":
        return None
    ts = pd.Timestamp(asof)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.normalize()


def truncate_to_asof(frame: pd.DataFrame, asof: str | pd.Timestamp | datetime | None) -> pd.DataFrame:
    """Keep only bars on or before asof (point-in-time)."""
    if frame.empty:
        return frame
    cut = _asof_ts(asof)
    if cut is None:
        return frame
    idx = frame.index
    if getattr(idx, "tz", None) is not None:
        idx_naive = idx.tz_convert("UTC").tz_localize(None)
        mask = idx_naive <= cut
    else:
        mask = pd.to_datetime(idx).normalize() <= cut
    return frame.loc[mask]


def feature_row_from_frame(frame: pd.DataFrame) -> dict[str, float | None]:
    """Compute literature-signed + extended factor values at the last bar.

    Core signs match ``tools/factor_probe.py`` (higher => predicted higher
    forward return). Extended fields feed the trained LightGBM scorer.
    """
    empty = {name: None for name in FEATURE_NAMES}
    n = len(frame)
    if n < MIN_HISTORY_BARS:
        return empty

    c = np.asarray(frame["close"], dtype=float)
    v = np.asarray(frame["volume"], dtype=float) if "volume" in frame.columns else np.ones(n, dtype=float)
    h = np.asarray(frame["high"], dtype=float) if "high" in frame.columns else c
    l = np.asarray(frame["low"], dtype=float) if "low" in frame.columns else c

    rev1 = _finite(-((c[-1] / c[-2]) - 1.0)) if n >= 2 and c[-2] != 0 else None
    
    rev5 = None
    ret_5 = None
    if n >= 6 and c[-6] != 0:
        r5 = float((c[-1] / c[-6]) - 1.0)
        rev5 = _finite(-r5)
        ret_5 = _finite(r5)

    mom12_1 = None
    if n >= MOM_MIN_BARS:
        c_lag21 = c[-22]
        c_lag252 = c[-253]
        if c_lag252 and math.isfinite(float(c_lag252)) and float(c_lag252) != 0:
            mom12_1 = _finite(float(c_lag21) / float(c_lag252) - 1.0)

    lowvol = None
    vol_20 = None
    vol_ratio = None
    if n >= 21:
        c_win = c[-21:]
        r_win = (c_win[1:] / c_win[:-1]) - 1.0
        valid_r = r_win[np.isfinite(r_win)]
        if len(valid_r) >= 10:
            std20 = float(np.std(valid_r, ddof=0))
            if math.isfinite(std20):
                lowvol = -std20
                if len(valid_r) >= 15:
                    vol_20 = _finite(std20)
                if len(valid_r) >= 20:
                    r5_win = valid_r[-5:]
                    std5 = float(np.std(r5_win, ddof=0))
                    if std20 > 1e-12:
                        vol_ratio = _finite(std5 / std20)

    liq = None
    log_adv = None
    if n >= 20:
        c20 = c[-20:]
        v20 = v[-20:]
        dollar = float(np.mean(c20 * v20))
        if math.isfinite(dollar):
            liq = -dollar
            if dollar > 0:
                log_adv = _finite(math.log10(dollar))

    ret_21 = _finite(float(c[-1] / c[-22] - 1.0)) if n >= 22 and c[-22] != 0 else None
    ret_63 = _finite(float(c[-1] / c[-64] - 1.0)) if n >= 64 and c[-64] != 0 else None
    mom_accel = None
    if ret_5 is not None and ret_21 is not None:
        mom_accel = _finite(float(ret_5) - float(ret_21))

    volume_z = None
    if n >= 40:
        prior = v[-40:-1]
        valid_v = prior[np.isfinite(prior)]
        if len(valid_v) > 0:
            mu, sd = float(np.mean(valid_v)), float(np.std(valid_v, ddof=0))
            if sd > 1e-12 and math.isfinite(v[-1]):
                volume_z = _finite((float(v[-1]) - mu) / sd)

    hl_range = None
    if n >= 5 and c[-1] != 0 and math.isfinite(c[-1]):
        hl_range = _finite(float(h[-1] - l[-1]) / float(c[-1]))

    gap_open = None
    if "open" in frame.columns and n >= 2 and c[-2] != 0:
        op = np.asarray(frame["open"], dtype=float)
        gap_open = _finite(float(op[-1] / c[-2] - 1.0))

    max_dd_21 = None
    if n >= 22:
        window_c = c[-21:]
        peak = np.maximum.accumulate(window_c)
        peak[peak <= 0] = np.nan
        dds = (window_c / peak) - 1.0
        dd = float(np.nanmin(dds))
        max_dd_21 = _finite(dd)

    return {
        "rev1": rev1,
        "rev5": rev5,
        "mom12_1": mom12_1,
        "lowvol": lowvol,
        "liq": liq,
        "ret_5": ret_5,
        "ret_21": ret_21,
        "ret_63": ret_63,
        "mom_accel": mom_accel,
        "vol_20": vol_20,
        "vol_ratio": vol_ratio,
        "volume_z": volume_z,
        "hl_range": hl_range,
        "gap_open": gap_open,
        "log_adv": log_adv,
        "max_dd_21": max_dd_21,
    }


def _cross_section_z(values: dict[str, float]) -> dict[str, float]:
    if len(values) < 2:
        return {k: 0.0 for k in values}
    arr = np.asarray(list(values.values()), dtype=float)
    mu = float(arr.mean())
    sd = float(arr.std(ddof=0))
    if not math.isfinite(sd) or sd <= 1e-12:
        return {k: 0.0 for k in values}
    return {k: (v - mu) / sd for k, v in values.items()}


def load_lgb_scorer(
    model_dir: str | Path | None = None,
    *,
    force_reload: bool = False,
) -> tuple[Any, dict[str, Any]] | None:
    """Load trained scorer + provenance (LightGBM, sklearn Ridge, or numpy).

    Prefer LightGBM when importable; fall back to sklearn joblib or a pure
    numpy coefficient file so the dashboard works without the qlib venv.
    """
    import json

    path = Path(model_dir) if model_dir else _DEFAULT_MODEL_DIR
    model_file = path / "model.txt"
    sk_file = path / "sklearn_model.joblib"
    npz_file = path / "linear_weights.npz"
    prov_file = path / "PROVENANCE.json"
    cache_key = str(path)
    if (
        not force_reload
        and _LGB_CACHE.get("booster") is not None
        and _LGB_CACHE.get("path") == cache_key
    ):
        return _LGB_CACHE["booster"], _LGB_CACHE["meta"] or {}

    meta: dict[str, Any] = {}
    if prov_file.is_file():
        try:
            meta = json.loads(prov_file.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    # 1) LightGBM
    if model_file.is_file():
        try:
            import lightgbm as lgb
            booster = lgb.Booster(model_file=str(model_file))
            handle = {"kind": "lightgbm", "model": booster}
            _LGB_CACHE.update(booster=handle, meta=meta, path=cache_key, error=None)
            return handle, meta
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001
            _LGB_CACHE["error"] = f"lgb_load:{type(exc).__name__}:{exc}"

    # 2) sklearn Ridge joblib
    if sk_file.is_file():
        try:
            import joblib
            payload = joblib.load(sk_file)
            handle = {
                "kind": "sklearn",
                "model": payload["model"],
                "feature_names": payload.get("feature_names") or list(FEATURE_NAMES),
            }
            meta = {
                **meta,
                "source_id": meta.get("source_id") or SOURCE_ID_LGB,
                "feature_names": handle["feature_names"],
            }
            _LGB_CACHE.update(booster=handle, meta=meta, path=cache_key, error=None)
            return handle, meta
        except Exception as exc:  # noqa: BLE001
            _LGB_CACHE["error"] = f"sklearn_load:{type(exc).__name__}:{exc}"

    # 3) pure numpy linear weights
    if npz_file.is_file():
        try:
            data = np.load(npz_file)
            names = [str(x) for x in data["feature_names"].tolist()]
            handle = {
                "kind": "numpy_linear",
                "coef": np.asarray(data["coef"], dtype=float),
                "intercept": float(data["intercept"]),
                "feature_names": names,
            }
            meta = {
                **meta,
                "source_id": meta.get("source_id") or SOURCE_ID_LGB,
                "feature_names": names,
            }
            _LGB_CACHE.update(booster=handle, meta=meta, path=cache_key, error=None)
            return handle, meta
        except Exception as exc:  # noqa: BLE001
            _LGB_CACHE["error"] = f"numpy_load:{type(exc).__name__}:{exc}"
            return None

    _LGB_CACHE["error"] = f"missing_model_artifact:{path}"
    return None


def _shipped_factor_blend_scores(
    feature_table: dict[str, dict[str, float | None]],
) -> dict[str, float]:
    """Original FACTOR_WEIGHTS blend (raw CS z). Partner for the LGB ensemble."""
    z_by_factor: dict[str, dict[str, float]] = {}
    for factor in FACTOR_WEIGHTS:
        raw_vals = {
            sym: float(feats[factor])
            for sym, feats in feature_table.items()
            if feats.get(factor) is not None
        }
        z_by_factor[factor] = _cross_section_z(raw_vals)

    scores: dict[str, float] = {}
    for symbol, feats in feature_table.items():
        num = 0.0
        den = 0.0
        for factor, weight in FACTOR_WEIGHTS.items():
            if symbol in z_by_factor[factor]:
                num += weight * z_by_factor[factor][symbol]
                den += weight
        if den > 0:
            scores[symbol] = num / den
    return scores


def _desk_ranker_scores(
    feature_table: dict[str, dict[str, float | None]],
    *,
    vol_regime: str = "MEDIUM",
) -> dict[str, float]:
    from edge.daily_plays.desk_ranker import score_feature_table

    return dict(score_feature_table(feature_table, vol_regime=vol_regime).scores)


def _factor_blend_scores(
    feature_table: dict[str, dict[str, float | None]],
    *,
    vol_regime: str = "MEDIUM",
    recipe: str = "shipped",
) -> dict[str, float]:
    """Dispatch the literature blend. Desk ranker is opt-in, never a silent swap."""
    if str(recipe) == "desk_ranker":
        try:
            return _desk_ranker_scores(feature_table, vol_regime=vol_regime)
        except Exception:
            return {}
    return _shipped_factor_blend_scores(feature_table)


def _lgb_predict_scores(
    feature_table: dict[str, dict[str, float | None]],
    *,
    booster: Any,
    feature_names: Sequence[str],
) -> dict[str, float]:
    """CS z-score features then model predict (matches training pipeline)."""
    symbols = list(feature_table)
    z_feats: dict[str, dict[str, float]] = {s: {} for s in symbols}
    for name in feature_names:
        raw = {
            s: float(feature_table[s][name])
            for s in symbols
            if feature_table[s].get(name) is not None
        }
        z = _cross_section_z(raw)
        for s, v in z.items():
            z_feats[s][name] = v
        for s in symbols:
            if name not in z_feats[s]:
                z_feats[s][name] = 0.0

    mat = np.asarray(
        [[z_feats[s].get(n, 0.0) for n in feature_names] for s in symbols],
        dtype=float,
    )
    handle = booster
    if isinstance(handle, dict):
        kind = handle.get("kind")
        if kind == "lightgbm":
            preds = np.asarray(handle["model"].predict(mat), dtype=float)
        elif kind == "sklearn":
            preds = np.asarray(handle["model"].predict(mat), dtype=float)
        elif kind == "numpy_linear":
            preds = mat @ np.asarray(handle["coef"], dtype=float) + float(handle["intercept"])
        else:
            raise ValueError(f"unknown model kind {kind!r}")
    else:
        # Raw lightgbm Booster
        preds = np.asarray(handle.predict(mat), dtype=float)
    return {s: float(p) for s, p in zip(symbols, preds) if math.isfinite(float(p))}


def _default_loader(symbol: str, data_dirs: Sequence[Path]) -> Any:
    cols = ["open", "high", "low", "close", "volume"]
    for base in data_dirs:
        path = Path(base) / f"{symbol}.parquet"
        if path.is_file():
            try:
                return pd.read_parquet(path, columns=cols)
            except Exception:
                try:
                    return pd.read_parquet(path)
                except Exception:
                    return None
    return None


def _empty_panel(
    *,
    asof: str | None,
    requested: int,
    warnings: list[str],
    quality: str = "missing",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "quality": quality,
        "score_kind": SCORE_KIND,
        "source": SOURCE_ID,
        "asof": asof,
        "rows": [],
        "by_symbol": {},
        "coverage": {
            "requested": requested,
            "attempted": 0,
            "scored": 0,
            "failed": requested,
            "skipped_insufficient_history": 0,
        },
        "warnings": warnings,
        "decision_authorized": False,
        "caveat": (
            "Ordinal qlib-style cross-sectional research score; not a calibrated "
            "probability or entry authorization."
        ),
    }


def _market_vol_regime(
    *,
    asof: str | pd.Timestamp | datetime | None,
    paths: Sequence[Path],
    candle_loader: Callable[[str], Any] | None,
) -> str:
    """Causal SPY vol regime for the desk ranker; MEDIUM if SPY is unavailable."""
    try:
        from edge.daily_plays.desk_ranker import classify_market_vol_regime
    except Exception:
        return "MEDIUM"
    raw = None
    try:
        if candle_loader is not None:
            raw = candle_loader("SPY")
        elif paths:
            raw = _default_loader("SPY", paths)
    except Exception:
        raw = None
    if raw is None or (hasattr(raw, "empty") and raw.empty):
        return "MEDIUM"
    try:
        frame = truncate_to_asof(_normalize_frame(raw), asof)
        if frame.empty or "close" not in frame.columns:
            return "MEDIUM"
        return classify_market_vol_regime(frame["close"], asof=asof)
    except Exception:
        return "MEDIUM"


def score_cross_section_asof(
    *,
    symbols: Sequence[str],
    asof: str | pd.Timestamp | datetime | None = None,
    data_dirs: Sequence[str | Path] = (),
    candle_loader: Callable[[str], Any] | None = None,
    provider: str = "local",
    model_dir: str | Path | None = None,
    engine: str = "auto",
) -> dict[str, Any]:
    """Score the catalog as-of a date. Shared by deep scan and Market tab.

    Parameters
    ----------
    symbols:
        Universe to score (typically the wide local catalog).
    asof:
        Inclusive cutoff for bars. ``None`` uses the latest bar present per name
        (still PIT within each series; cross-section asof is the max available).
    data_dirs / candle_loader:
        Local OHLCV source. Loader wins when provided (tests inject frames).
    provider:
        ``"local"`` (default) uses parquet/loader. ``"qlib"`` attempts the
        binary provider under ``data/qlib_us_1d_wide`` and fails closed on error.
    model_dir:
        Optional ranker artifact directory for champion/challenger feedback
        iteration. Defaults to ``models/qlib_scan_lgb``.
    engine:
        ``"auto"`` uses LightGBM when the artifact loads, else the desk
        ranker. ``"desk_ranker"`` forces the zero-fit rev5+mom12_1 recipe.
        ``"lgb_ensemble"`` always prefers the trained model path.
    """
    requested = list(dict.fromkeys(_symbol(s) for s in symbols if _symbol(s)))
    warnings: list[str] = []
    paths = [Path(p) for p in data_dirs]

    if provider == "qlib":
        # Optional slow path — not used by default deep scan; available for
        # offline batch jobs. Fail closed into empty panel on any error.
        try:
            return _score_via_qlib_provider(symbols=requested, asof=asof, warnings=warnings)
        except Exception as exc:  # noqa: BLE001 - fail closed, never invent ranks
            warnings.append(f"qlib_provider_failed: {type(exc).__name__}: {exc}")
            return _empty_panel(
                asof=str(asof) if asof is not None else None,
                requested=len(requested),
                warnings=warnings,
            )

    if not paths and candle_loader is None:
        warnings.append("no_data_dirs_or_loader")
        return _empty_panel(
            asof=str(asof) if asof is not None else None,
            requested=len(requested),
            warnings=warnings,
        )

    def load(symbol: str) -> Any:
        if candle_loader is not None:
            return candle_loader(symbol)
        return _default_loader(symbol, paths)

    feature_table: dict[str, dict[str, float | None]] = {}
    bar_asofs: dict[str, str] = {}
    attempted = 0
    failed = 0
    skipped = 0

    def _process_one_symbol(sym: str) -> tuple[str, dict[str, float | None] | None, str | None, str]:
        try:
            raw = load(sym)
            if raw is None or (hasattr(raw, "empty") and raw.empty):
                return sym, None, None, "failed"
            frame = truncate_to_asof(_normalize_frame(raw), asof)
        except Exception:
            return sym, None, None, "failed"
        if len(frame) < MIN_HISTORY_BARS:
            return sym, None, None, "skipped"
        feats = feature_row_from_frame(frame)
        if all(v is None for v in feats.values()):
            return sym, None, None, "skipped"
        last_idx = pd.Timestamp(frame.index[-1])
        bar_asof = last_idx.strftime("%Y-%m-%d")
        return sym, feats, bar_asof, "scored"

    workers = min(12, max(1, len(requested)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(_process_one_symbol, requested))

    for symbol, feats, bar_asof, status in results:
        attempted += 1
        if status == "scored" and feats is not None and bar_asof is not None:
            feature_table[symbol] = feats
            bar_asofs[symbol] = bar_asof
        elif status == "skipped":
            skipped += 1
        else:
            failed += 1

    if not feature_table:
        warnings.append("no_symbols_scored")
        panel_asof = str(asof) if asof is not None else None
        return _empty_panel(
            asof=panel_asof,
            requested=len(requested),
            warnings=warnings,
        )

    # Prefer trained model (+ optional ensemble with factor blend).
    source = SOURCE_ID_FACTORS
    model_meta: dict[str, Any] = {}
    vol_regime = _market_vol_regime(asof=asof, paths=paths, candle_loader=candle_loader)
    engine_name = str(engine or "auto").strip().lower()
    if engine_name == "desk_ranker":
        factor_scores = _factor_blend_scores(
            feature_table, vol_regime=vol_regime, recipe="desk_ranker",
        )
        if not factor_scores:
            warnings.append("no_scores_after_model")
            return _empty_panel(
                asof=str(asof) if asof is not None else None,
                requested=len(requested),
                warnings=warnings,
            )
        scores = factor_scores
        source = "desk_ranker_v1"
        loaded = None
    else:
        factor_scores = _factor_blend_scores(
            feature_table, vol_regime=vol_regime, recipe="shipped",
        )
        loaded = load_lgb_scorer(model_dir, force_reload=model_dir is not None)
    if loaded is not None:
        booster, model_meta = loaded
        feat_names = list(model_meta.get("feature_names") or FEATURE_NAMES)
        try:
            ml_scores = _lgb_predict_scores(
                feature_table, booster=booster, feature_names=feat_names,
            )
            source = str(model_meta.get("source_id") or SOURCE_ID_LGB)
            # Ensemble weight w on ML score, (1-w) on literature factor blend.
            # Default 0.65 favors the trained model; provenance can override.
            w = float(model_meta.get("ensemble_ml_weight", 0.65))
            w = min(1.0, max(0.0, w))
            if w >= 0.999 or not factor_scores:
                scores = ml_scores
            else:
                # CS-rank both then blend for scale-free combination.
                def _pct_ranks(d: dict[str, float]) -> dict[str, float]:
                    if not d:
                        return {}
                    ordered_s = sorted(d.items(), key=lambda kv: kv[1])
                    n = len(ordered_s)
                    return {s: (i + 1) / n for i, (s, _) in enumerate(ordered_s)}
                r_ml = _pct_ranks(ml_scores)
                r_fac = _pct_ranks(factor_scores)
                keys = set(r_ml) | set(r_fac)
                scores = {
                    s: w * r_ml.get(s, 0.5) + (1.0 - w) * r_fac.get(s, 0.5)
                    for s in keys
                }
                source = f"{source}+factor_ensemble"
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"lgb_predict_failed:{type(exc).__name__}:{exc}")
            scores = factor_scores
            source = SOURCE_ID_FACTORS
    else:
        if engine_name != "desk_ranker" and _LGB_CACHE.get("error"):
            warnings.append(f"lgb_unavailable:{_LGB_CACHE['error']}")
        scores = factor_scores
        if engine_name == "desk_ranker":
            source = "desk_ranker_v1"

    if not scores:
        warnings.append("no_scores_after_model")
        return _empty_panel(
            asof=str(asof) if asof is not None else None,
            requested=len(requested),
            warnings=warnings,
        )

    # Rank 1 = highest score (best predicted forward return).
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    ranks = {sym: rank for rank, (sym, _) in enumerate(ordered, start=1)}

    panel_asof = max(bar_asofs.values()) if bar_asofs else (
        str(_asof_ts(asof).date()) if _asof_ts(asof) is not None else None
    )

    rows: list[dict[str, Any]] = []
    by_symbol: dict[str, dict[str, Any]] = {}
    for symbol, score in ordered:
        row = {
            "symbol": symbol,
            "qlib_score": round(float(score), 6),
            "qlib_rank": int(ranks[symbol]),
            "score_kind": SCORE_KIND,
            "source": source,
            "asof": bar_asofs.get(symbol) or panel_asof,
            "features": {
                name: (round(float(v), 6) if v is not None else None)
                for name, v in feature_table[symbol].items()
            },
            "decision_authorized": False,
        }
        rows.append(row)
        by_symbol[symbol] = row

    return {
        "schema_version": SCHEMA_VERSION,
        "quality": "ok",
        "score_kind": SCORE_KIND,
        "source": source,
        "model": {
            "source_id": source,
            "train_end": model_meta.get("train_end"),
            "val_end": model_meta.get("val_end"),
            "val_mean_rank_ic": model_meta.get("val_mean_rank_ic"),
            "best_iteration": model_meta.get("best_iteration"),
        } if source == SOURCE_ID_LGB or source.startswith("qlib_scan_lgb") else None,
        "asof": panel_asof,
        "rows": rows,
        "by_symbol": by_symbol,
        "coverage": {
            "requested": len(requested),
            "attempted": attempted,
            "scored": len(rows),
            "failed": failed,
            "skipped_insufficient_history": skipped,
        },
        "warnings": warnings,
        "decision_authorized": False,
        "caveat": (
            "Ordinal qlib-style cross-sectional research score (trained LGB when "
            "artifact present, else factor blend); not a calibrated probability "
            "or entry authorization."
        ),
    }


def lookup_symbol_qlib_context(
    symbol: str,
    *,
    panel: Mapping[str, Any] | None = None,
    asof: str | pd.Timestamp | datetime | None = None,
    data_dirs: Sequence[str | Path] = (),
    candle_loader: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Return qlib score context for one symbol, or an explicit missing state.

    When ``panel`` is provided (already scored for the same as-of), reuse it so
    Market tab and deep scan cannot disagree on provenance.
    """
    sym = _symbol(symbol)
    base = {
        "symbol": sym,
        "qlib_score": None,
        "qlib_rank": None,
        "score_kind": SCORE_KIND,
        "source": SOURCE_ID,
        "asof": None,
        "quality": "missing",
        "decision_authorized": False,
        "features": None,
        "warnings": [],
    }
    if not sym:
        base["warnings"] = ["empty_symbol"]
        return base

    active = panel
    if active is None:
        active = score_cross_section_asof(
            symbols=[sym],
            asof=asof,
            data_dirs=data_dirs,
            candle_loader=candle_loader,
        )

    by_symbol = active.get("by_symbol") if isinstance(active, Mapping) else None
    if isinstance(by_symbol, Mapping) and sym in by_symbol:
        row = by_symbol[sym]
        return {
            "symbol": sym,
            "qlib_score": row.get("qlib_score"),
            "qlib_rank": row.get("qlib_rank"),
            "score_kind": row.get("score_kind") or SCORE_KIND,
            "source": row.get("source") or SOURCE_ID,
            "asof": row.get("asof") or active.get("asof"),
            "quality": "ok",
            "decision_authorized": False,
            "features": row.get("features"),
            "coverage": active.get("coverage"),
            "warnings": list(active.get("warnings") or []),
        }

    return {
        **base,
        "asof": active.get("asof") if isinstance(active, Mapping) else None,
        "warnings": list((active or {}).get("warnings") or []) + [f"symbol_not_scored:{sym}"],
        "coverage": (active or {}).get("coverage") if isinstance(active, Mapping) else None,
    }


def merge_qlib_into_activity_rows(
    rows: Sequence[Mapping[str, Any]],
    panel: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Attach qlib fields to activity board rows without inventing ranks."""
    by_symbol = panel.get("by_symbol") if isinstance(panel.get("by_symbol"), Mapping) else {}
    out: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        sym = _symbol(row.get("symbol"))
        qrow = by_symbol.get(sym) if sym else None
        if qrow:
            row["qlib_score"] = qrow.get("qlib_score")
            row["qlib_rank"] = qrow.get("qlib_rank")
            row["qlib_score_kind"] = qrow.get("score_kind") or SCORE_KIND
            row["qlib_source"] = qrow.get("source") or panel.get("source") or SOURCE_ID
            row["qlib_asof"] = qrow.get("asof") or panel.get("asof")
            sources = list(row.get("sources") or [])
            label = str(row["qlib_source"])
            if label and label not in sources:
                sources.append(label)
            row["sources"] = sources
        else:
            row["qlib_score"] = None
            row["qlib_rank"] = None
            row["qlib_score_kind"] = SCORE_KIND
            row["qlib_source"] = panel.get("source") or SOURCE_ID
            row["qlib_asof"] = panel.get("asof")
        out.append(row)
    return out


def qlib_priority_symbols(
    panel: Mapping[str, Any],
    *,
    limit: int,
    allowed_symbols: set[str] | None = None,
) -> list[str]:
    """Highest-ranked qlib names for live-target routing (research tier)."""
    rows = list(panel.get("rows") or [])
    allowed = {_symbol(s) for s in (allowed_symbols or set()) if _symbol(s)}
    out: list[str] = []
    for row in rows:
        sym = _symbol(row.get("symbol"))
        if not sym:
            continue
        if allowed and sym not in allowed:
            continue
        out.append(sym)
        if len(out) >= max(0, int(limit)):
            break
    return out


def _score_via_qlib_provider(
    *,
    symbols: Sequence[str],
    asof: str | pd.Timestamp | datetime | None,
    warnings: list[str],
) -> dict[str, Any]:
    """Optional backend: read closes from the checked-in qlib binary provider.

    Intentionally narrow — loads $close/$volume only for the requested symbols
    and reuses the same feature math as the local path so score identity holds.
    """
    import qlib
    from qlib.data import D

    edge_root = Path(__file__).resolve().parents[1]
    provider_uri = edge_root / "data" / "qlib_us_1d_wide"
    if not provider_uri.is_dir():
        raise FileNotFoundError(f"missing qlib provider: {provider_uri}")

    qlib.init(provider_uri=str(provider_uri), region="us")
    cut = _asof_ts(asof)
    end = (cut or pd.Timestamp.utcnow().normalize()).strftime("%Y-%m-%d")
    # Enough history for mom12_1 + cushion.
    start_ts = (cut or pd.Timestamp(end)) - pd.Timedelta(days=420)
    start = start_ts.strftime("%Y-%m-%d")

    # qlib instruments are bare tickers in this provider.
    inst = [s for s in symbols]
    raw = D.features(
        inst,
        ["$close", "$volume", "$open", "$high", "$low"],
        start_time=start,
        end_time=end,
        freq="day",
    )
    if raw is None or raw.empty:
        warnings.append("qlib_features_empty")
        return _empty_panel(asof=end, requested=len(symbols), warnings=warnings)

    frames: dict[str, pd.DataFrame] = {}
    # MultiIndex (instrument, datetime) typical of qlib.
    if isinstance(raw.index, pd.MultiIndex):
        for sym, group in raw.groupby(level=0):
            g = group.droplevel(0).sort_index()
            g = g.rename(columns={
                "$close": "close", "$volume": "volume",
                "$open": "open", "$high": "high", "$low": "low",
            })
            frames[_symbol(sym)] = g
    else:
        warnings.append("qlib_unexpected_index")
        return _empty_panel(asof=end, requested=len(symbols), warnings=warnings)

    def loader(symbol: str) -> Any:
        return frames.get(_symbol(symbol), pd.DataFrame())

    panel = score_cross_section_asof(
        symbols=symbols,
        asof=asof or end,
        candle_loader=loader,
        provider="local",
    )
    panel["source"] = SOURCE_ID + "+qlib_provider"
    for row in panel.get("rows") or []:
        row["source"] = panel["source"]
    for row in (panel.get("by_symbol") or {}).values():
        row["source"] = panel["source"]
    return panel


def rank_ic_series(
    scores_by_date: Mapping[str, Mapping[str, float]],
    forward_returns_by_date: Mapping[str, Mapping[str, float]],
    *,
    min_names: int = 15,
) -> list[float]:
    """Spearman Rank IC per as-of date between score map and forward-return map."""
    ics: list[float] = []
    for date, scores in scores_by_date.items():
        rets = forward_returns_by_date.get(date) or {}
        common = [s for s in scores if s in rets and _finite(scores[s]) is not None and _finite(rets[s]) is not None]
        if len(common) < min_names:
            continue
        s = pd.Series({k: float(scores[k]) for k in common})
        r = pd.Series({k: float(rets[k]) for k in common})
        ic = float(s.rank().corr(r.rank(), method="pearson"))
        if math.isfinite(ic):
            ics.append(ic)
    return ics


def mean_rank_ic(ics: Sequence[float]) -> float | None:
    if not ics:
        return None
    return float(np.mean(np.asarray(ics, dtype=float)))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Process-level panel cache shared by deep scan, Market trajectory, and analyze.
# Ranks are only comparable inside one cross-section; caching the full catalog
# panel prevents Market from ranking AAPL in a 220-name slice while deep uses
# 576 names (or returning missing for late-alphabet tickers outside a partial
# focus list).
# ---------------------------------------------------------------------------
_SHARED_PANEL: dict[str, Any] = {
    "panel": None,
    "asof_key": None,
    "n_symbols": 0,
    "built_at": 0.0,
    "symbol_set": frozenset(),
}
DEFAULT_PANEL_TTL_SEC = 300.0


def peek_shared_qlib_panel() -> dict[str, Any] | None:
    """Return the published deep-scan panel, or None. Never rebuilds."""
    panel = _SHARED_PANEL.get("panel")
    return dict(panel) if isinstance(panel, dict) else None


def publish_shared_qlib_panel(panel: Mapping[str, Any] | None) -> None:
    """Publish a freshly built panel (e.g. deep scan) for Market reuse."""
    import time as _time

    if not isinstance(panel, Mapping) or panel.get("quality") != "ok":
        return
    by_symbol = panel.get("by_symbol") if isinstance(panel.get("by_symbol"), Mapping) else {}
    _SHARED_PANEL["panel"] = dict(panel)
    _SHARED_PANEL["asof_key"] = str(panel.get("asof") or "")
    _SHARED_PANEL["n_symbols"] = len(by_symbol)
    _SHARED_PANEL["built_at"] = _time.time()
    _SHARED_PANEL["symbol_set"] = frozenset(str(s).upper() for s in by_symbol)


def clear_shared_qlib_panel() -> None:
    """Test helper — drop the process cache."""
    _SHARED_PANEL["panel"] = None
    _SHARED_PANEL["asof_key"] = None
    _SHARED_PANEL["n_symbols"] = 0
    _SHARED_PANEL["built_at"] = 0.0
    _SHARED_PANEL["symbol_set"] = frozenset()


def get_shared_qlib_panel(
    *,
    data_dirs: Sequence[str | Path] = (),
    asof: str | pd.Timestamp | datetime | None = None,
    candle_loader: Callable[[str], Any] | None = None,
    force_include: Sequence[str] = (),
    ttl_sec: float = DEFAULT_PANEL_TTL_SEC,
    min_catalog_fraction: float = 0.95,
    match_asof: bool = False,
) -> dict[str, Any]:
    """Return a full-catalog (or near-full) qlib panel for Market + deep scan.

    Always scores the local market catalog from ``data_dirs`` (same universe
    deep scan uses). Cached panels are reused when fresh and cover the catalog
    and any ``force_include`` symbols; otherwise rebuilt.

    ``match_asof`` defaults False for the live Market path: a published deep-scan
    panel is reused even when a symbol's local last bar predates the panel asof
    (staggered data ends). Re-cutting the whole cross-section on that earlier
    date would change ranks and disagree with deep scan. Pass ``match_asof=True``
    only for explicit historical as-of research rebuilds.
    """
    import time as _time

    from .live_activity import load_market_symbol_catalog

    paths = [Path(p) for p in data_dirs]
    catalog = load_market_symbol_catalog(data_dirs=paths) if paths else []
    extra = [_symbol(s) for s in force_include if _symbol(s)]
    universe = list(dict.fromkeys([*catalog, *extra]))
    if not universe and candle_loader is None:
        return _empty_panel(
            asof=str(asof) if asof is not None else None,
            requested=0,
            warnings=["empty_market_catalog"],
        )

    asof_key = ""
    cut = _asof_ts(asof)
    if cut is not None:
        asof_key = cut.strftime("%Y-%m-%d")

    now = _time.time()
    cached = _SHARED_PANEL.get("panel")
    cached_set = _SHARED_PANEL.get("symbol_set") or frozenset()
    required = {_symbol(s) for s in extra}
    ttl_ok = (now - float(_SHARED_PANEL.get("built_at") or 0.0)) <= float(ttl_sec)
    if match_asof and asof_key:
        asof_ok = (
            str(_SHARED_PANEL.get("asof_key") or "") in ("", asof_key)
            or str((cached or {}).get("asof") or "").startswith(asof_key)
        )
    else:
        # Live Market / deep publish reuse: ignore per-symbol last-bar asof.
        asof_ok = True
    fresh = (
        isinstance(cached, dict)
        and cached.get("quality") == "ok"
        and ttl_ok
        and asof_ok
    )
    covers_required = required <= set(cached_set)
    # Require near-full catalog coverage so a partial focus panel is never kept.
    n_cat = len(catalog) or len(universe)
    covers_catalog = (
        n_cat == 0
        or len(cached_set) >= max(1, int(min_catalog_fraction * n_cat))
    )
    if fresh and covers_required and covers_catalog:
        return cached  # type: ignore[return-value]

    # Build like deep scan: only apply asof when explicitly matching a historical
    # cut. Otherwise use each series' latest available bar (asof=None).
    build_asof = asof if match_asof else None
    panel = score_cross_section_asof(
        symbols=universe,
        asof=build_asof,
        data_dirs=paths,
        candle_loader=candle_loader,
    )
    publish_shared_qlib_panel(panel)
    return panel


def lookup_symbol_on_shared_panel(
    symbol: str,
    *,
    data_dirs: Sequence[str | Path] = (),
    asof: str | pd.Timestamp | datetime | None = None,
    candle_loader: Callable[[str], Any] | None = None,
    ttl_sec: float = DEFAULT_PANEL_TTL_SEC,
    match_asof: bool = False,
) -> dict[str, Any]:
    """Market entry: full-catalog panel lookup (rebuild when symbol not covered).

    Default ``match_asof=False`` reuses the published deep-scan panel without
    re-cutting on the symbol's local last bar, so ranks stay identical to deep.
    """
    sym = _symbol(symbol)
    panel = get_shared_qlib_panel(
        data_dirs=data_dirs,
        asof=asof,
        candle_loader=candle_loader,
        force_include=[sym] if sym else (),
        ttl_sec=ttl_sec,
        match_asof=match_asof,
    )
    by_symbol = panel.get("by_symbol") if isinstance(panel.get("by_symbol"), Mapping) else {}
    # Stale partial cache safety net: if symbol is in the local catalog but not
    # in the panel, force a full rebuild once (never invent a rank).
    if sym and sym not in by_symbol and data_dirs:
        try:
            from .live_activity import load_market_symbol_catalog
            catalog = set(load_market_symbol_catalog(data_dirs=data_dirs))
        except Exception:
            catalog = set()
        if sym in catalog or candle_loader is not None:
            clear_shared_qlib_panel()
            panel = get_shared_qlib_panel(
                data_dirs=data_dirs,
                asof=asof,
                candle_loader=candle_loader,
                force_include=[sym],
                ttl_sec=ttl_sec,
                match_asof=match_asof,
            )
    # Lookup against the panel as-is — do not re-score with a different asof.
    return lookup_symbol_qlib_context(
        sym,
        panel=panel,
        data_dirs=data_dirs,
        candle_loader=candle_loader,
    )
