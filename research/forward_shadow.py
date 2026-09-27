"""Append-only, forward-only ledger for already-scored underlying WATCH forecasts.

This module never loads options, outcomes, prices, or terminal-holdout data. It
is intentionally a forecast journal, not an execution or realization service.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from .hashing import stable_hash
from .labels import FROZEN_HORIZONS


SCHEMA_VERSION = "edge-forward-underlying-shadow-v1"
_REQUIRED = frozenset({"artifact_id", "symbol", "feature_asof", "generated_at", "horizon_days",
                       "probability_target", "calibration_version", "side", "probability", "threshold",
                       "state", "shadow_only"})


def _timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be a timezone-aware ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware ISO timestamp")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _finite_probability(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite probability")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite probability") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be a finite probability")
    return number


def normalize_forward_forecast(forecast: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize a single non-actionable scored forecast."""
    if not isinstance(forecast, Mapping):
        raise TypeError("forward forecast must be a mapping")
    keys = set(forecast)
    missing, extra = sorted(_REQUIRED - keys), sorted(keys - _REQUIRED)
    if missing or extra:
        raise ValueError(f"invalid forward forecast fields; missing={missing}, extra={extra}")
    if forecast["state"] != "WATCH" or forecast["shadow_only"] is not True:
        raise ValueError("forward ledger accepts WATCH shadow forecasts only; actionable or broker states are rejected")
    feature_asof = _timestamp(forecast["feature_asof"], field="feature_asof")
    generated_at = _timestamp(forecast["generated_at"], field="generated_at")
    if feature_asof > generated_at:
        raise ValueError("feature_asof cannot be after generated_at")
    horizon = forecast["horizon_days"]
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon not in FROZEN_HORIZONS:
        raise ValueError(f"horizon_days must be one of {FROZEN_HORIZONS}")
    probability_target = _text(forecast["probability_target"], field="probability_target")
    if not probability_target.startswith("underlying_"):
        raise ValueError("probability_target must describe an underlying event")
    side = _text(forecast["side"], field="side").lower()
    if side not in {"long", "short"}:
        raise ValueError("side must be long or short")
    threshold = _finite_probability(forecast["threshold"], field="threshold")
    if not 0.5 <= threshold < 1.0:
        raise ValueError("threshold must be in [0.5, 1)")
    normalized = {
        "artifact_id": _text(forecast["artifact_id"], field="artifact_id"),
        "symbol": _text(forecast["symbol"], field="symbol").upper(),
        "feature_asof": _iso(feature_asof),
        "generated_at": _iso(generated_at),
        "horizon_days": horizon,
        "probability_target": probability_target,
        "calibration_version": _text(forecast["calibration_version"], field="calibration_version"),
        "side": side,
        "probability": _finite_probability(forecast["probability"], field="probability"),
        "threshold": threshold,
        "state": "WATCH",
        "shadow_only": True,
    }
    return normalized


@dataclass(frozen=True)
class ForwardShadowRecord:
    sequence: int
    record_id: str
    record_hash: str
    forecast: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "sequence": self.sequence, "record_id": self.record_id,
                "record_hash": self.record_hash, "forecast": self.forecast}


class ForwardShadowLedger:
    """JSONL forecast journal with deterministic identity and append-only replay."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._records: list[ForwardShadowRecord] = []
        self._by_id: dict[str, ForwardShadowRecord] = {}
        self._reload()

    @property
    def records(self) -> tuple[ForwardShadowRecord, ...]:
        return tuple(self._records)

    @staticmethod
    def _record_id(forecast: Mapping[str, Any]) -> str:
        # This is the natural identity of exactly one model artifact's scored
        # forecast at one feature cutoff and horizon.  A changed payload with
        # the same identity is an explicit conflict, never a second forecast.
        return stable_hash({key: forecast[key] for key in ("artifact_id", "symbol", "feature_asof", "horizon_days")},
                           namespace="edge-forward-underlying-shadow-id-v1")

    @staticmethod
    def _record_hash(record_id: str, forecast: Mapping[str, Any]) -> str:
        return stable_hash({"record_id": record_id, "forecast": dict(forecast)},
                           namespace="edge-forward-underlying-shadow-record-v1")

    def _reload(self) -> None:
        records: list[ForwardShadowRecord] = []; by_id: dict[str, ForwardShadowRecord] = {}
        if self.path.exists():
            for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    if not isinstance(raw, Mapping) or raw.get("schema_version") != SCHEMA_VERSION:
                        raise ValueError("invalid schema")
                    sequence, record_id, record_hash, forecast = raw["sequence"], raw["record_id"], raw["record_hash"], raw["forecast"]
                    if not isinstance(sequence, int) or sequence != len(records):
                        raise ValueError("non-contiguous sequence")
                    normalized = normalize_forward_forecast(forecast)
                    expected_id = self._record_id(normalized)
                    expected_hash = self._record_hash(expected_id, normalized)
                    if record_id != expected_id or record_hash != expected_hash:
                        raise ValueError("record identity/hash mismatch")
                    record = ForwardShadowRecord(sequence, record_id, record_hash, normalized)
                    if record_id in by_id:
                        raise ValueError("duplicate record id")
                    records.append(record); by_id[record_id] = record
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(f"invalid forward shadow record at line {line_number}: {exc}") from exc
        self._records, self._by_id = records, by_id

    def append(self, forecast: Mapping[str, Any]) -> ForwardShadowRecord:
        """Atomically append one canonical WATCH record or return its replay."""
        normalized = normalize_forward_forecast(forecast)
        record_id = self._record_id(normalized)
        record_hash = self._record_hash(record_id, normalized)
        # Match ExperimentLedger's append protocol: re-read before deciding,
        # never rewrite/truncate, then flush the one new complete JSONL line.
        self._reload()
        existing = self._by_id.get(record_id)
        if existing is not None:
            if existing.forecast != normalized or existing.record_hash != record_hash:
                raise ValueError(f"append-only conflict for forward forecast {record_id}")
            return existing
        record = ForwardShadowRecord(len(self._records), record_id, record_hash, normalized)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._records.append(record); self._by_id[record_id] = record
        return record
