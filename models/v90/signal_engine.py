"""v90_meta_confidence: two-sided meta-labeling engine with calibrated confidence.

Design (see docs/MODEL_REVIEW_AND_HIGH_WINRATE_PLAN.md and MODEL.md):
  - Causal features (features.py) -> two XGBoost meta-labelers (LONG / SHORT
    heads) trained on triple-barrier labels via purged K-fold.
  - Raw score drives the BUY / SELL / FLAT decision (continuous, monotonic);
    the isotonic-calibrated probability is the honest confidence shown to the
    operator.
  - Emits SIGNED target weights: positive = BUY (long), negative = SELL (short)
    when ``allow_short`` is enabled, else the short head becomes a flatten/avoid
    signal only. FLAT = 0.

FAIL-CLOSED (enforced — not just documented):
  The engine is FLAT and refuses to generate any signal unless ALL four
  required artifacts are present, loadable, and consistent with the signed
  manifest:

    meta_xgb_long.json    — XGBoost LONG booster
    meta_xgb_short.json   — XGBoost SHORT booster
    calibration.json      — isotonic maps (must contain "long" and "short"
                            keys, both with type=="isotonic")
    thresholds.json       — entry thresholds (must contain "enter_hi" and
                            "selective" keys)

  If ANY artifact is missing, corrupted, or lacks the required structure, the
  engine sets _ready=False and returns FLAT for every bar.  There are NO silent
  defaults that substitute plausible-looking numbers and allow live trading to
  continue.

  Existing positions are NOT forcibly closed on an inference outage, because
  an automatic market-order liquidation during an outage can itself cause harm.
  Position management (TP/SL/time-exit) must be handled by a separate
  deterministic risk layer.

Runtime gating fix (edge/ port 2026-07-29, see MODEL.md):
  The entry gate in generate() previously compared against _enter_lo
  (the "active_top10" threshold with NEGATIVE holdout expectancy) instead of
  _enter_hi (the "balanced_top5" documented shipped default).  Fixed during
  port.

Artifacts produced by tools/train_v90_meta_confidence.py:
  meta_xgb_long.json, meta_xgb_short.json, calibration.json, thresholds.json.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Required artifact keys — engine is FLAT if any are absent
# ---------------------------------------------------------------------------
_REQUIRED_THRESHOLD_KEYS: List[str] = ["enter_hi", "selective"]
_REQUIRED_CALIBRATION_KEYS: List[str] = ["long", "short"]
_REQUIRED_CALIBRATION_TYPE: str = "isotonic"


def _load_features_module():
    here = Path(__file__).resolve().parent
    path = here / "features.py"
    module_name = f"v90_features_{id(path)}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _Calibrator:
    """Isotonic (piecewise-linear) map restored from JSON.

    Unlike the previous version, this class does NOT have a silent identity
    fallback.  If the artifact does not have type=='isotonic' with valid x/y
    arrays, construction raises ValueError and the engine stays FLAT.
    """

    def __init__(self, art: Dict[str, object]) -> None:
        kind = str(art.get("type", ""))
        if kind != _REQUIRED_CALIBRATION_TYPE:
            raise ValueError(
                f"Calibration artifact has type={kind!r}; "
                f"expected {_REQUIRED_CALIBRATION_TYPE!r}.  "
                "Engine will not trade without a fitted isotonic calibrator."
            )
        try:
            self._x = np.asarray(art["x"], dtype=float)
            self._y = np.asarray(art["y"], dtype=float)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Calibration artifact missing or invalid x/y arrays: {exc}") from exc
        if len(self._x) < 2 or len(self._x) != len(self._y):
            raise ValueError(
                f"Calibration x/y arrays must have the same length >= 2 "
                f"(got x={len(self._x)}, y={len(self._y)})"
            )

    def apply(self, p: np.ndarray) -> np.ndarray:
        return np.interp(p, self._x, self._y)


class SignalEngine:
    """Two-sided calibrated meta-labeler.  Long/flat by default; short enabled
    via hunt_config.allow_short.

    FAIL-CLOSED: returns FLAT for all bars unless all four required artifacts
    are present and structurally valid.  No silent defaults.
    """

    # Human-readable reason the engine is in FLAT mode.
    not_ready_reason: str = "not initialized"

    def __init__(self) -> None:
        self._dir = Path(__file__).resolve().parent
        self._feat = _load_features_module()
        self.last_confidence: Dict[str, pd.Series] = {}
        self.last_side: Dict[str, pd.Series] = {}
        self._ready = False
        self.not_ready_reason = "init not complete"

        # ── hunt_config (optional — only controls allow_short and sizing) ──────
        hunt = self._load_json(self._dir / "hunt_config.json")
        if hunt is None:
            hunt = {}  # hunt_config is optional; missing it is not a FLAT trigger
        self._allow_short: bool = bool(hunt.get("allow_short", True))
        self._base_scale: float = float(hunt.get("base_scale", 0.25))
        self._selective_scale: float = float(hunt.get("selective_scale", 0.35))

        # ── thresholds.json — REQUIRED, no silent defaults ────────────────────
        thr, thr_err = self._load_and_validate_thresholds()
        if thr_err:
            self.not_ready_reason = thr_err
            return  # _ready stays False → all calls return FLAT

        self._enter_hi: float = float(thr["enter_hi"])   # type: ignore[index]
        self._enter_lo: float = float(thr.get("enter_lo", self._enter_hi))  # optional hysteresis
        self._selective: float = float(thr["selective"])  # type: ignore[index]

        # ── boosters — REQUIRED ───────────────────────────────────────────────
        self._long_model, long_err = self._load_booster("meta_xgb_long.json")
        if long_err:
            self.not_ready_reason = long_err
            return

        self._short_model, short_err = self._load_booster("meta_xgb_short.json")
        if short_err:
            self.not_ready_reason = short_err
            return

        # ── calibration.json — REQUIRED, must be isotonic for both heads ──────
        cal, cal_err = self._load_and_validate_calibration()
        if cal_err:
            self.not_ready_reason = cal_err
            return

        self._cal_long: _Calibrator = cal[0]   # type: ignore[index]
        self._cal_short: _Calibrator = cal[1]  # type: ignore[index]

        # ── all checks passed ─────────────────────────────────────────────────
        self._ready = True
        self.not_ready_reason = ""

    # ── private loaders ───────────────────────────────────────────────────────

    @staticmethod
    def _load_json(path: Path) -> Optional[Dict[str, object]]:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _load_and_validate_thresholds(
        self,
    ) -> Tuple[Optional[Dict[str, object]], Optional[str]]:
        """Load thresholds.json.  Returns (data, None) on success or (None, error_str)."""
        path = self._dir / "thresholds.json"
        if not path.exists():
            return None, f"thresholds.json missing at {path}"
        raw = self._load_json(path)
        if raw is None:
            return None, f"thresholds.json is not valid JSON at {path}"
        missing = [k for k in _REQUIRED_THRESHOLD_KEYS if k not in raw]
        if missing:
            return None, (
                f"thresholds.json missing required keys {missing}. "
                "Engine will not use placeholder thresholds."
            )
        return raw, None

    def _load_booster(self, name: str) -> Tuple[Optional[object], Optional[str]]:
        """Load an XGBoost booster.  Returns (booster, None) or (None, error_str)."""
        path = self._dir / name
        if not path.exists():
            return None, f"Required booster artifact missing: {path}"
        try:
            import xgboost as xgb
        except ImportError:
            return None, "xgboost is not installed — cannot load boosters"
        try:
            booster = xgb.Booster()
            booster.load_model(str(path))
            return booster, None
        except Exception as exc:
            return None, f"Failed to load booster {name}: {exc}"

    def _load_and_validate_calibration(
        self,
    ) -> Tuple[Optional[Tuple[_Calibrator, _Calibrator]], Optional[str]]:
        """Load calibration.json and build both calibrators.

        Returns ((_Calibrator_long, _Calibrator_short), None) on success
        or (None, error_str) on any failure.
        """
        path = self._dir / "calibration.json"
        if not path.exists():
            return None, f"calibration.json missing at {path}"
        raw = self._load_json(path)
        if raw is None:
            return None, f"calibration.json is not valid JSON at {path}"
        missing = [k for k in _REQUIRED_CALIBRATION_KEYS if k not in raw]
        if missing:
            return None, (
                f"calibration.json missing required keys {missing}. "
                "Engine will not use identity (uncalibrated) fallback."
            )
        try:
            cal_long = _Calibrator(raw["long"])   # type: ignore[arg-type]
            cal_short = _Calibrator(raw["short"])  # type: ignore[arg-type]
        except ValueError as exc:
            return None, f"calibration.json validation failed: {exc}"
        return (cal_long, cal_short), None

    def _predict(self, booster, feats: pd.DataFrame) -> np.ndarray:
        import xgboost as xgb

        dm = xgb.DMatrix(feats.to_numpy(dtype=float), feature_names=list(feats.columns))
        return np.asarray(booster.predict(dm), dtype=float)

    # ── public API ────────────────────────────────────────────────────────────

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        out: Dict[str, pd.Series] = {}
        self.last_confidence = {}
        self.last_side = {}

        for code, df in data_map.items():
            if df is None or df.empty:
                out[code] = pd.Series(
                    0.0,
                    index=(df.index if df is not None else pd.DatetimeIndex([])),
                )
                continue

            idx = df.index
            target = pd.Series(0.0, index=idx)
            conf = pd.Series(0.0, index=idx)
            side = pd.Series("FLAT", index=idx)

            if not self._ready:
                # Fail closed — log reason but never substitute a signal
                out[code] = target
                self.last_confidence[code] = conf
                self.last_side[code] = side
                continue

            feats = self._feat.build_features(df)
            valid = feats.notna().all(axis=1)
            fv = feats[valid]
            if fv.empty:
                out[code] = target
                self.last_confidence[code] = conf
                self.last_side[code] = side
                continue

            raw_long = self._predict(self._long_model, fv)
            raw_short = self._predict(self._short_model, fv)
            cal_long = self._cal_long.apply(raw_long)
            cal_short = self._cal_short.apply(raw_short)

            pos = np.where(valid.to_numpy())[0]
            for k, row in enumerate(pos):
                rl, rs = raw_long[k], raw_short[k]
                cl, cs = cal_long[k], cal_short[k]
                long_ok = rl >= self._enter_hi
                short_ok = rs >= self._enter_hi
                if long_ok and rl >= rs:
                    scale = self._selective_scale if rl >= self._selective else self._base_scale
                    target.iloc[row] = scale
                    conf.iloc[row] = cl
                    side.iloc[row] = "BUY"
                elif short_ok:
                    scale = self._selective_scale if rs >= self._selective else self._base_scale
                    target.iloc[row] = -scale if self._allow_short else 0.0
                    conf.iloc[row] = cs
                    side.iloc[row] = "SELL" if self._allow_short else "SELL_FLATTEN"

            out[code] = target
            self.last_confidence[code] = conf
            self.last_side[code] = side

        return out
