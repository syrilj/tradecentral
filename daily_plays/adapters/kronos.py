"""Kronos research-payload normalization.

Kronos is deliberately represented as research evidence.  Its confidence is
an ordinal research score and is never exposed as model/calibrated probability.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping


def load_point_in_time_kronos(symbol: str, *, context: Any, forecasts_root: str | Path | None = None, **_: Any) -> Mapping[str, Any]:
    """Load only a same-session fusion artifact; never backfill research."""
    root = Path(forecasts_root) if forecasts_root else Path(__file__).resolve().parents[3] / "Kronos" / "forecasts"
    path = root / f"LIVE_FUSION_{context.requested_for.isoformat()}.json"
    if not path.is_file():
        return {"_evidence_warning": "kronos_same_session_artifact_missing"}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        stamp = raw.get("asof") or raw.get("as_of")
        if not stamp:
            return {"_evidence_warning": "kronos_artifact_asof_missing"}
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            from zoneinfo import ZoneInfo
            parsed = parsed.replace(tzinfo=ZoneInfo("America/New_York"))
        parsed = parsed.astimezone(timezone.utc)
        if parsed.date() != context.requested_for:
            return {"_evidence_warning": "kronos_artifact_stale_or_wrong_session"}
        if parsed > context.asof_utc:
            return {"_evidence_warning": "kronos_artifact_from_future"}
        rows = raw.get("rows") if isinstance(raw.get("rows"), list) else []
        row = next((item for item in rows if isinstance(item, Mapping) and str(item.get("ticker") or item.get("symbol") or "").upper() == symbol.upper()), None)
        if row is None:
            return {"_evidence_warning": "kronos_symbol_not_in_same_session_artifact"}
        model = row.get("model") if isinstance(row.get("model"), Mapping) else {}
        return normalize_kronos_payload({"ticker": symbol.upper(), "asof_utc": parsed.isoformat(),
            "tmr_point_pct": model.get("tmr_point_pct"), "regime": model.get("regime"),
            "gex_regime": model.get("gex_regime"), "conf_score": model.get("conf_score"),
            "conf_label": model.get("conf_label"), "actionable": model.get("actionable")})
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"_evidence_warning": "kronos_artifact_invalid"}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _direction(point_pct: float | None) -> str:
    if point_pct is None:
        return "neutral"
    if point_pct > 0.15:
        return "long"
    if point_pct < -0.15:
        return "short"
    return "neutral"


def normalize_kronos_payload(payload: Mapping[str, Any] | None, *, asof_utc: str | None = None) -> dict[str, Any]:
    """Return a stable research-evidence record from Kronos report/summary rows.

    This intentionally does not contain ``calibrated_probability``.  Kronos'
    score may influence agreement/evidence grade only downstream.
    """
    raw = dict(payload or {})
    tmr = raw.get("tmr") if isinstance(raw.get("tmr"), Mapping) else {}
    confidence = raw.get("confidence") if isinstance(raw.get("confidence"), Mapping) else {}
    selective = raw.get("selective") if isinstance(raw.get("selective"), Mapping) else {}
    point_pct = _number(tmr.get("point_pct", raw.get("tmr_point_pct")))
    pi80 = tmr.get("pi80") if isinstance(tmr.get("pi80"), (list, tuple)) else None
    return {
        "source": "kronos",
        "symbol": str(raw.get("ticker") or raw.get("symbol") or "").upper() or None,
        "asof_utc": raw.get("as_of") or raw.get("asof_utc") or asof_utc,
        "direction": _direction(point_pct),
        "forecast": {
            "horizon": "next_session",
            "point": _number(tmr.get("point")),
            "point_pct": point_pct,
            "interval_80": list(pi80) if pi80 else None,
            "point_tag": tmr.get("point_tag"),
        },
        "regime": raw.get("regime") or raw.get("regime_label"),
        "gex": {
            "regime": raw.get("gex_regime"),
            "call_wall": _number(raw.get("call_wall")),
            "put_wall": _number(raw.get("put_wall")),
        },
        "research_confidence": {
            "kind": "ordinal_score",
            "score": _number(confidence.get("score", raw.get("conf_score"))),
            "label": confidence.get("label", raw.get("conf_label")),
            "selective_actionable": bool(selective.get("actionable", raw.get("actionable", False))),
        },
        "provenance": {"raw_source": "Kronos/forecast_calibrated.py"},
    }
