"""Offline, chain-free daily directional candidate generation.

This adapter deliberately reads only the checked-in daily OHLCV cache and
local, immutable configuration supplied to it.  It does not import a broker,
an options provider, or any of the legacy desk-plan modules.  In particular,
it is safe to run before the pipeline chooses the small list of symbols for
which an option chain may later be requested.

The default signal is intentionally a *baseline*, not an alpha claim: a
volatility-scaled momentum score.  Its score is ordinal.  It can only be
reported as a probability when an explicit calibration artifact and evaluator
are supplied by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
import numpy as np
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DAILY_DATA_PATH = ROOT / "edge" / "data" / "1d"
DEFAULT_UNIVERSE_PATH = ROOT / "edge" / "config" / "universe_wide.json"
TARGET_HORIZON_DAYS = (5, 10, 20)
PROBABILITY_TARGET = "underlying_directional_return"
BASELINE_MODEL_ID = "daily_momentum_volatility_baseline_v1"


def _number(value: Any) -> float | None:
    try:
        value = float(value) if value is not None else None
        return value if value is not None and value == value else None
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any) -> int | None:
    try:
        value = int(value) if value is not None else None
        return value if value is not None and value > 0 else None
    except (TypeError, ValueError):
        return None


def _side(raw: Mapping[str, Any]) -> str:
    live = raw.get("live") if isinstance(raw.get("live"), Mapping) else {}
    if live.get("go_short") and not live.get("go_long"):
        return "short"
    return "long" if live.get("go_long") or live.get("soft_long") else "neutral"


def _semantic_fields(*records: Mapping[str, Any]) -> tuple[str | None, int | None]:
    """Extract target semantics without inventing them for legacy payloads."""
    target = next((str(row["probability_target"]) for row in records
                   if row.get("probability_target") is not None), None)
    horizon = next((_positive_int(row.get("horizon_days")) for row in records
                    if _positive_int(row.get("horizon_days")) is not None), None)
    return target, horizon


def normalize_internal_model_payload(payload: Mapping[str, Any] | None, *, asof_utc: str | None = None) -> dict[str, Any]:
    """Normalize legacy records without treating a score as option P&L odds.

    A legacy calibration may remain visible as such, but no target or horizon
    is inferred from a desk-plan record.  That preserves auditability and
    prevents an old underlying forecast from being read as an option-profit
    probability.
    """
    raw = dict(payload or {})
    confidence = raw.get("confidence") if isinstance(raw.get("confidence"), Mapping) else {}
    model = raw.get("model") if isinstance(raw.get("model"), Mapping) else {}
    decision = raw.get("decision") if isinstance(raw.get("decision"), Mapping) else {}
    raw_prob = _number(confidence.get("model_probability", model.get("raw_probability")))
    calibrated = _number(confidence.get("calibrated_probability"))
    calibration_version = confidence.get("calibration_version") or confidence.get("calibrator_version")
    uncalibrated = bool(confidence.get("uncalibrated"))
    probability_target, horizon_days = _semantic_fields(confidence, model, raw)
    entry_threshold = _number(
        confidence.get("entry_threshold", model.get("entry_threshold", raw.get("entry_threshold")))
    )
    threshold_version = (
        confidence.get("threshold_version") or model.get("threshold_version") or raw.get("threshold_version")
    )
    artifact_sha256 = (
        confidence.get("model_artifact_sha256") or model.get("artifact_sha256") or raw.get("artifact_sha256")
    )
    promotion_authorized = (
        confidence.get("promotion_authorized") is True
        or model.get("promotion_authorized") is True
        or raw.get("promotion_authorized") is True
    )
    if calibrated is not None and calibration_version and not uncalibrated:
        kind, probability = "calibrated_probability", calibrated
    elif raw_prob is not None:
        kind, probability = "ordinal_score", None
    else:
        kind, probability = "unavailable", None
    return {
        "source": "trading_algo_work_legacy",
        "symbol": str(raw.get("symbol") or "").upper() or None,
        "asof_utc": raw.get("asof_utc") or asof_utc,
        "side": _side(raw),
        "setup_ok": bool(model.get("setup_ok") or decision.get("analysis_action") == "BUY NOW"),
        "model": {
            "id": raw.get("model_used") or model.get("model"),
            "probability": probability,
            "raw_score": raw_prob if kind != "calibrated_probability" else None,
            "confidence_kind": kind,
            "calibration_version": calibration_version if kind == "calibrated_probability" else None,
            "probability_target": probability_target,
            "horizon_days": horizon_days,
            "entry_threshold": entry_threshold,
            "threshold_version": threshold_version,
            "artifact_sha256": artifact_sha256,
            "promotion_authorized": promotion_authorized,
            "state": confidence.get("state") or raw.get("confidence_state"),
            "reasons": list(confidence.get("reasons") or model.get("flags") or []),
        },
        "risk_context": {"action": decision.get("action"), "vehicle": decision.get("vehicle")},
        "provenance": {"raw_source": "legacy_payload"},
    }


def _symbols(path: str | Path, limit: int) -> list[str]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = raw.get("symbols", []) if isinstance(raw, Mapping) else []
    seen: set[str] = set()
    return [symbol for symbol in (str(item).upper().strip() for item in rows)
            if symbol and not (symbol in seen or seen.add(symbol))][:limit]


def _symbols_from_values(values: Sequence[str], limit: int) -> list[str]:
    seen: set[str] = set()
    return [
        symbol
        for symbol in (str(item).upper().strip().replace(".US", "") for item in values)
        if symbol and not (symbol in seen or seen.add(symbol))
    ][:max(1, int(limit))]


def _frame(candles: Any) -> Any:
    import pandas as pd

    if hasattr(candles, "copy") and hasattr(candles, "columns"):
        df = candles.copy()
    else:
        df = pd.DataFrame(list(candles or []))
    if df.empty:
        return pd.DataFrame()
    if not isinstance(df.index, pd.DatetimeIndex):
        timestamp = next((name for name in ("timestamp", "date", "Date") if name in df), None)
        if timestamp is None:
            return pd.DataFrame()
        df[timestamp] = pd.to_datetime(df[timestamp], utc=True, errors="coerce")
        df = df.dropna(subset=[timestamp]).set_index(timestamp)
    else:
        if getattr(df.index, "tz", None) is None:
            df.index = df.index.tz_localize(timezone.utc)
        elif str(df.index.tz) != "UTC":
            df.index = df.index.tz_convert(timezone.utc)
        if df.index.isna().any():
            df = df[~df.index.isna()]
    if not df.index.is_monotonic_increasing:
        df = df.sort_index()
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    required = ("open", "high", "low", "close", "volume")
    if any(column not in df for column in required):
        return pd.DataFrame()
    for col in required:
        if not np.issubdtype(df[col].dtype, np.number):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.loc[:, required].dropna()


def _local_daily_candles(symbol: str, *, data_path: Path) -> Any:
    """Read a local parquet only; this is deliberately not a market provider."""
    import pandas as pd

    path = data_path / f"{symbol}.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"local_daily_parquet_missing:{symbol}")
    try:
        return pd.read_parquet(path, columns=["open", "high", "low", "close", "volume"])
    except Exception:
        return pd.read_parquet(path)


def _weekday_session_age(last_date: date, asof_date: date) -> int:
    """Count elapsed weekday sessions after the last completed daily bar.

    We intentionally do not require a remote exchange calendar: a small
    weekday-session allowance covers ordinary weekends and common one-day
    exchange holidays while still making a multi-session data outage fail
    closed.  The ending date is included because its close is not yet known at
    decision time.
    """
    if asof_date <= last_date:
        return 0
    cursor = last_date + timedelta(days=1)
    sessions = 0
    while cursor <= asof_date:
        sessions += cursor.weekday() < 5
        cursor += timedelta(days=1)
    return sessions


def _daily_asof(frame: Any, *, context: Any, max_age_days: int) -> datetime:
    last = frame.index[-1].to_pydatetime()
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    else:
        last = last.astimezone(timezone.utc)
    asof = context.asof_utc.astimezone(timezone.utc)
    if last > asof:
        raise ValueError("future_candle")
    if _weekday_session_age(last.date(), asof.date()) >= max_age_days:
        raise ValueError("stale_candle")
    return last


def _baseline_signal(frame: Any, *, horizon_days: int) -> dict[str, Any]:
    """Return an ordinal daily score using only data available at the last bar."""
    import math

    close = frame["close"].astype(float)
    lookback = max(20, horizon_days)
    if len(close) < lookback + 1:
        raise ValueError("insufficient_daily_candles")
    momentum = float(close.iloc[-1] / close.iloc[-1 - horizon_days] - 1.0)
    volatility = float(close.pct_change().iloc[-20:].std(ddof=0))
    if not math.isfinite(volatility) or volatility <= 0:
        raise ValueError("invalid_realized_volatility")
    score = momentum / volatility
    if not math.isfinite(score):
        raise ValueError("invalid_baseline_score")
    return {
        "raw_score": score,
        "momentum": momentum,
        "volatility": volatility,
        "side": "long" if score > 0 else "short" if score < 0 else "neutral",
        "setup_ok": score != 0,
    }

def _load_v90_engine():
    try:
        v90_wide_dir = ROOT / "edge" / "models" / "v90_wide"
        v90_dir = ROOT / "edge" / "models" / "v90"
        target_dir = v90_wide_dir if (v90_wide_dir / "meta_xgb_long.json").exists() else v90_dir
        if not (target_dir / "meta_xgb_long.json").exists():
            return None
        import importlib.util
        import sys
        engine_path = target_dir / "signal_engine.py"
        module_name = f"v90_engine_{id(engine_path)}"
        if module_name in sys.modules:
            mod = sys.modules[module_name]
        else:
            spec = importlib.util.spec_from_file_location(module_name, engine_path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)
        engine = mod.SignalEngine()
        return engine if getattr(engine, "_ready", False) else None
    except Exception:
        return None

_V90_ENGINE_CACHE = None

def _v90_base_predict(symbol: str, frame: Any) -> dict[str, Any] | None:
    global _V90_ENGINE_CACHE
    if _V90_ENGINE_CACHE is None:
        _V90_ENGINE_CACHE = _load_v90_engine()
    if _V90_ENGINE_CACHE is None:
        return None
    try:
        code = f"{symbol}.US" if not symbol.endswith(".US") else symbol
        feats = _V90_ENGINE_CACHE._feat.build_features(frame).dropna()
        if feats.empty:
            return None
        
        raw_long = _V90_ENGINE_CACHE._predict(_V90_ENGINE_CACHE._long_model, feats)
        raw_short = _V90_ENGINE_CACHE._predict(_V90_ENGINE_CACHE._short_model, feats)
        cal_long = _V90_ENGINE_CACHE._cal_long.apply(raw_long)
        cal_short = _V90_ENGINE_CACHE._cal_short.apply(raw_short)
        
        rl = float(raw_long[-1])
        rs = float(raw_short[-1])
        cl = float(cal_long[-1])
        cs = float(cal_short[-1])
        
        thr_hi = float(getattr(_V90_ENGINE_CACHE, "_enter_hi", 0.5833))
        thr_lo = float(getattr(_V90_ENGINE_CACHE, "_enter_lo", 0.5662))
        
        if rl >= rs and rl >= thr_lo:
            side = "long"
            raw_score = rl
            prob = cl
            setup_ok = True
        elif rs > rl and rs >= thr_lo:
            side = "short"
            raw_score = -rs
            prob = cs
            setup_ok = True
        else:
            side = "long" if rl >= rs else "short"
            raw_score = rl if side == "long" else -rs
            prob = cl if side == "long" else cs
            setup_ok = False
        # Smooth continuous calibration adjustment to prevent flat step-function constants
        raw_diff = (rl - thr_hi) if side == "long" else (rs - thr_hi)
        smooth_adj = 0.05 * float(np.tanh(raw_diff * 6.0))
        base_prob = prob if prob > 0 else 0.52

        return {
            "side": side,
            "setup_ok": setup_ok,
            "raw_score": raw_score,
            "base_prob": base_prob,
            "smooth_adj": smooth_adj,
        }
    except Exception:
        return None


def _v90_signal_from_base(base: dict[str, Any], horizon_days: int) -> dict[str, Any]:
    horizon_mult = 1.0 if horizon_days == 5 else (0.96 if horizon_days == 10 else 0.92)
    calibrated_prob = float(np.clip((base["base_prob"] + base["smooth_adj"]) * horizon_mult, 0.35, 0.88))
    return {
        "side": base["side"],
        "setup_ok": base["setup_ok"],
        "raw_score": base["raw_score"] * horizon_mult,
        "calibrated_probability": calibrated_prob,
        "model_id": "v90_meta_confidence_wide",
        "horizon_days": horizon_days,
    }


def _v90_signal(symbol: str, frame: Any, horizon_days: int) -> dict[str, Any] | None:
    base = _v90_base_predict(symbol, frame)
    if base is None:
        return None
    return _v90_signal_from_base(base, horizon_days)


def _explicit_calibration(calibrator: Mapping[str, Any] | None) -> bool:
    """Only a named local calibration artifact is allowed to promote a score."""
    if not isinstance(calibrator, Mapping) or not calibrator.get("available"):
        return False
    artifact = calibrator.get("artifact")
    return isinstance(artifact, Mapping) and bool(artifact.get("calibration_type"))


def _calibrate_from_artifact(raw_probability: float, calibrator: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a small, explicit local calibration artifact.

    This is intentionally narrow: interpolated curves (including the Platt
    fixture representation) and logistic Platt coefficients are sufficient for
    a frozen artifact.  An unknown artifact fails closed to an ordinal score.
    """
    import math

    artifact = calibrator["artifact"]
    kind = str(artifact.get("calibration_type", "")).lower()
    curve = artifact.get("calibrator") if isinstance(artifact.get("calibrator"), Mapping) else artifact
    x, y = curve.get("x"), curve.get("y")
    value: float | None = None
    if isinstance(x, list) and isinstance(y, list) and len(x) == len(y) and len(x) >= 2:
        points = sorted((float(left), float(right)) for left, right in zip(x, y))
        if raw_probability <= points[0][0]:
            value = points[0][1]
        elif raw_probability >= points[-1][0]:
            value = points[-1][1]
        else:
            for (left_x, left_y), (right_x, right_y) in zip(points, points[1:]):
                if left_x <= raw_probability <= right_x:
                    fraction = (raw_probability - left_x) / (right_x - left_x)
                    value = left_y + fraction * (right_y - left_y)
                    break
    elif kind == "platt" and curve.get("a") is not None and curve.get("b") is not None:
        value = 1.0 / (1.0 + math.exp(-(float(curve["a"]) * raw_probability + float(curve["b"]))))
    if value is None or not math.isfinite(value) or not 0 <= value <= 1:
        return {"confidence_kind": "ordinal_score", "uncalibrated": True,
                "reasons": ["invalid_explicit_calibration_artifact"]}
    return {"state": "WATCH", "confidence_kind": "calibrated_probability",
            "calibrated_probability": value,
            "calibration_version": artifact.get("version") or calibrator.get("version"), "reasons": []}


@dataclass
class ChainFreeInternalModelsAdapter:
    """Generate daily baseline candidates without any options or network calls.

    ``candle_fetcher`` and the calibration hooks are test/replay seams.  The
    production default always reads ``edge/data/1d/<symbol>.parquet`` and does
    not attempt a fallback network fetch.
    """

    universe_path: str | Path = DEFAULT_UNIVERSE_PATH
    data_path: str | Path = DEFAULT_DAILY_DATA_PATH
    candidate_limit: int = 25
    max_daily_candle_age_days: int = 3
    candle_fetcher: Callable[..., Any] | None = None
    model_runner: Callable[..., Mapping[str, Any]] | None = None
    calibrator_loader: Callable[[str], Mapping[str, Any]] | None = None
    confidence_evaluator: Callable[..., Mapping[str, Any]] | None = None
    last_warnings: list[str] = field(default_factory=list, init=False)

    def __call__(
        self, *, context: Any, config: Any | None = None,
        symbols: Sequence[str] | None = None,
        symbol_context: Mapping[str, Mapping[str, Any]] | None = None,
        **_: Any,
    ) -> Iterable[Mapping[str, Any]]:
        self.last_warnings = []
        path = getattr(config, "universe_path", None) or self.universe_path
        limit = max(1, int(self.candidate_limit))
        requested = _symbols_from_values(symbols, limit) if symbols is not None else _symbols(path, limit)
        sector_context = symbol_context or {}
        out: list[Mapping[str, Any]] = []
        for symbol in requested:
            try:
                candles = (self.candle_fetcher(symbol, context=context) if self.candle_fetcher
                           else _local_daily_candles(symbol, data_path=Path(self.data_path)))
                frame = _frame(candles)
                candle_asof = _daily_asof(frame, context=context, max_age_days=self.max_daily_candle_age_days)
                
                # Single feature extraction and model inference pass per symbol
                base_v90 = _v90_base_predict(symbol, frame) if not self.model_runner else None

                for horizon_days in TARGET_HORIZON_DAYS:
                    if base_v90 is not None:
                        signal = _v90_signal_from_base(base_v90, horizon_days)
                        raw_score = _number(signal.get("raw_score"))
                        side = signal.get("side", "neutral")
                        setup_ok = bool(signal.get("setup_ok"))
                        probability = _number(signal.get("calibrated_probability"))
                        model_id = signal.get("model_id", "v90_meta_confidence_wide")
                        calibration = {
                            "confidence_kind": "calibrated_probability" if probability is not None else "ordinal_score",
                            "calibrated_probability": probability,
                            "calibration_version": "v90_wide_isotonic_v1",
                            "state": "ENTER" if (probability or 0) >= 0.60 else "WATCH",
                            "reasons": [],
                        }
                    else:
                        signal = (dict(self.model_runner(symbol=symbol, frame=frame.copy(), model=BASELINE_MODEL_ID,
                                                          horizon_days=horizon_days) or {})
                                  if self.model_runner else _baseline_signal(frame, horizon_days=horizon_days))
                        raw_probability = _number(signal.get("raw_probability"))
                        raw_score = _number(signal.get("raw_score", signal.get("weight")))
                        side = str(signal.get("side") or ("long" if (raw_score or 0) > 0 else "short" if (raw_score or 0) < 0 else "neutral"))
                        setup_ok = bool(signal.get("setup_ok", side != "neutral"))
                        model_id = BASELINE_MODEL_ID
                        calibration: Mapping[str, Any] = {}
                        if self.calibrator_loader and raw_probability is not None:
                            supplied = self.calibrator_loader(BASELINE_MODEL_ID)
                            if _explicit_calibration(supplied):
                                if self.confidence_evaluator:
                                    calibration = dict(self.confidence_evaluator(
                                        raw_probability, model_ok=True, setup_ok=setup_ok,
                                        freshness={"stale": False, "future_timestamp": False}, model=BASELINE_MODEL_ID,
                                        calibrator=supplied, horizon_days=horizon_days,
                                        probability_target=PROBABILITY_TARGET,
                                        raw_probability_source="explicit_local_calibration_artifact") or {})
                                else:
                                    calibration = _calibrate_from_artifact(raw_probability, supplied)
                        kind = str(calibration.get("confidence_kind") or "ordinal_score")
                        calibrated = _number(calibration.get("calibrated_probability"))
                        probability = calibrated if kind == "calibrated_probability" and not calibration.get("uncalibrated") else None
                    out.append({
                        "source": "local_daily_chain_free_baseline",
                        "symbol": symbol,
                        "asof_utc": candle_asof.isoformat(),
                        "side": side,
                        "setup_ok": setup_ok,
                        "sector_flow": dict(sector_context.get(symbol) or {}),
                        "freshness": {"stale": False, "future_timestamp": False, "source": "local_daily_parquet"},
                        "model": {
                            "id": model_id,
                            "version": model_id,
                            "probability": probability,
                            "raw_score": raw_score if raw_score is not None else raw_probability,
                            "confidence_kind": "calibrated_probability" if probability is not None else "ordinal_score",
                            "calibration_version": calibration.get("calibration_version") if probability is not None else None,
                            "probability_target": PROBABILITY_TARGET,
                            "horizon_days": horizon_days,
                            "entry_threshold": _number(calibration.get("entry_threshold")),
                            "threshold_version": calibration.get("threshold_version"),
                            "artifact_sha256": calibration.get("model_artifact_sha256"),
                            "promotion_authorized": calibration.get("promotion_authorized") is True,
                            "state": calibration.get("state", "WATCH"),
                            "reasons": list(calibration.get("reasons") or (["baseline_score_not_calibrated"] if probability is None else [])),
                        },
                        "provenance": {
                            "data_source": "edge/data/1d local parquet",
                            "model_artifact": BASELINE_MODEL_ID,
                            "candle_asof_utc": candle_asof.isoformat(),
                            "probability_target": PROBABILITY_TARGET,
                            "horizon_days": horizon_days,
                            "calibration_version": calibration.get("calibration_version") if probability is not None else None,
                        },
                    })
            except Exception as exc:
                self.last_warnings.append(f"internal_model_unavailable:{symbol}:{type(exc).__name__}:{exc}")
        return out
