"""Shadow-only inference for the frozen wide daily directional challenger.

This adapter exists to make the broad-market research surface visible without
silently promoting it.  The artifact is trained for fixed 5/10/20-session
underlying direction, but its terminal holdout remains sealed.  Consequently
every emitted row is research-only and can never enter the option execution
path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from edge.research.artifact_predictor import load_frozen_artifact, score_frozen_artifact


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LATEST_PATH = ROOT / "edge" / "runs" / "research" / "directional_daily_v1" / "latest.json"
DEFAULT_DAILY_DATA_PATH = ROOT / "edge" / "data" / "1d"
DEFAULT_UNIVERSE_PATH = ROOT / "edge" / "config" / "universe_wide.json"
SUPPORTED_HORIZONS = (5, 10, 20)
ARTIFACT_SCHEMA = "edge-daily-directional-artifact-v1"


def _symbols(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    return [
        symbol
        for symbol in (str(value or "").strip().upper().replace(".US", "") for value in values)
        if symbol and not (symbol in seen or seen.add(symbol))
    ]


def _universe_metadata(path: str | Path) -> tuple[list[str], dict[str, str]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or not isinstance(raw.get("symbols"), list):
        raise ValueError("daily_directional_universe_missing_symbols")
    symbols = _symbols(raw["symbols"])
    if not symbols:
        raise ValueError("daily_directional_universe_empty")
    sectors: dict[str, str] = {}
    for sector, members in (raw.get("sectors") or {}).items():
        for symbol in members if isinstance(members, list) else ():
            sectors.setdefault(str(symbol).upper(), str(sector))
    return symbols, sectors


def _universe_symbols(path: str | Path) -> list[str]:
    return _universe_metadata(path)[0]


def _load_artifact(latest_path: str | Path) -> tuple[dict[str, Any], Path]:
    latest_file = Path(latest_path)
    latest = json.loads(latest_file.read_text(encoding="utf-8"))
    raw_path = latest.get("artifact_path")
    if not raw_path:
        raise ValueError("daily_directional_latest_missing_artifact_path")
    artifact_path = Path(str(raw_path))
    if not artifact_path.is_absolute():
        artifact_path = ROOT / artifact_path
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    load_frozen_artifact(artifact)
    if (
        artifact.get("status") != "FROZEN_RESEARCH_CHALLENGER"
        or artifact.get("shadow_only") is not True
        or artifact.get("broker_authorized") is not False
    ):
        raise ValueError("daily_directional_artifact_not_frozen_shadow_challenger")
    if artifact.get("underlying_gate") == "FAIL_DEVELOPMENT":
        raise ValueError("daily_directional_artifact_failed_development")
    if artifact.get("underlying_gate") != "PENDING_UNTOUCHED_HOLDOUT":
        raise ValueError("daily_directional_artifact_not_frozen_shadow_challenger")
    return dict(artifact), artifact_path


def _frame(candles: Any) -> Any:
    import pandas as pd

    frame = candles.copy() if hasattr(candles, "copy") else pd.DataFrame(list(candles or []))
    if frame.empty:
        return pd.DataFrame()
    frame = frame.rename(
        columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
    )
    if not isinstance(frame.index, pd.DatetimeIndex):
        timestamp = next((name for name in ("timestamp", "date", "Date") if name in frame), None)
        if timestamp is None:
            return pd.DataFrame()
        frame[timestamp] = pd.to_datetime(frame[timestamp], utc=True, errors="coerce")
        frame = frame.dropna(subset=[timestamp]).set_index(timestamp)
    else:
        frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")
        frame = frame.loc[~frame.index.isna()]
    required = ("open", "high", "low", "close", "volume")
    if any(column not in frame for column in required):
        return pd.DataFrame()
    return frame.loc[:, required].apply(pd.to_numeric, errors="coerce").dropna().sort_index()


def _local_daily(symbol: str, *, data_path: Path) -> Any:
    import pandas as pd

    path = data_path / f"{symbol}.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"local_daily_parquet_missing:{symbol}")
    return pd.read_parquet(path)


def _latest_features(frame: Any, symbol: str) -> tuple[dict[str, Any], datetime]:
    import pandas as pd

    from edge.research.features import causal_daily_features, feature_columns
    from edge.research.simple_hypotheses import shock_reversal_features_5d

    single = frame.copy()
    single["symbol"] = symbol
    panel = single.reset_index(names="timestamp").set_index(["timestamp", "symbol"]).sort_index()
    features = causal_daily_features(panel)
    shock = shock_reversal_features_5d(panel)
    row = features.iloc[-1]
    values = {name: float(row[name]) for name in feature_columns()}
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("non_finite_daily_directional_features")
    shock_row = shock.iloc[-1]
    values["shock_reversal_score_5d"] = float(shock_row["shock_reversal_score_5d"])
    values["shock_reversal_eligible_5d"] = bool(shock_row["shock_reversal_eligible_5d"])
    if not math.isfinite(values["shock_reversal_score_5d"]):
        raise ValueError("non_finite_shock_reversal_features")
    asof = pd.Timestamp(features.index[-1][0]).to_pydatetime()
    return values, asof.astimezone(timezone.utc)


def _needs_sector_residual(artifact: Mapping[str, Any]) -> bool:
    for spec in (artifact.get("horizons") or {}).values():
        model = spec.get("model") if isinstance(spec, Mapping) else None
        if isinstance(model, Mapping) and model.get("type") == "fixed_feature_score" and model.get("score_feature") == "sector_residual_score_20d":
            return True
    return False


def _attach_sector_residual_features(
    snapshots: Mapping[str, tuple[dict[str, Any], datetime]],
    *, sectors: Mapping[str, str],
) -> None:
    """Attach same-date leave-one-out sector features, never raw-momentum fallbacks."""
    import pandas as pd

    from edge.research.sector_residual import sector_residual_momentum_20d

    records = []
    for symbol, (features, asof) in snapshots.items():
        records.append({"timestamp": asof, "symbol": symbol, "sector": sectors.get(symbol, ""),
                        "momentum_20d": features.get("momentum_20d"),
                        "realized_volatility_20d": features.get("realized_volatility_20d")})
    residual = sector_residual_momentum_20d(pd.DataFrame(records))
    for row in residual.itertuples(index=False):
        features = snapshots[str(row.symbol)][0]
        features["sector_residual_score_20d"] = float(row.sector_residual_score_20d)
        features["sector_residual_eligible_20d"] = bool(row.sector_residual_eligible_20d)
        features["sector_residual_score_percentile_20d"] = float(row.sector_residual_score_percentile_20d)
        features["sector_residual_peer_count_20d"] = int(row.sector_residual_peer_count_20d)


def _session_age(last_date: date, asof_date: date) -> int:
    if last_date >= asof_date:
        return 0
    cursor, count = last_date, 0
    while cursor < asof_date:
        cursor = date.fromordinal(cursor.toordinal() + 1)
        count += cursor.weekday() < 5
    return count


@dataclass
class FrozenDirectionalResearchAdapter:
    """Score routed symbols with a sealed artifact, never as executable plays."""

    latest_path: str | Path = DEFAULT_LATEST_PATH
    data_path: str | Path = DEFAULT_DAILY_DATA_PATH
    universe_path: str | Path = DEFAULT_UNIVERSE_PATH
    candidate_limit: int = 25
    max_session_age: int = 2
    candle_fetcher: Callable[..., Any] | None = None
    artifact_loader: Callable[[], Mapping[str, Any]] | None = None
    last_warnings: list[str] = field(default_factory=list, init=False)

    def __call__(
        self,
        *,
        context: Any,
        symbols: Sequence[str] | None = None,
        symbol_context: Mapping[str, Mapping[str, Any]] | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        self.last_warnings = []
        try:
            if self.artifact_loader:
                artifact = dict(self.artifact_loader())
                artifact_path = Path("<injected>")
                if artifact.get("schema_version") != ARTIFACT_SCHEMA:
                    raise ValueError("unsupported_daily_directional_artifact")
            else:
                artifact, artifact_path = _load_artifact(self.latest_path)
        except Exception as exc:
            self.last_warnings.append(f"directional_research_artifact_unavailable:{type(exc).__name__}:{exc}")
            return []

        holdout = dict(artifact.get("terminal_holdout") or {})
        validation_status = str(holdout.get("status") or "UNKNOWN")
        if (
            artifact.get("status") != "FROZEN_RESEARCH_CHALLENGER"
            or artifact.get("shadow_only") is not True
            or artifact.get("broker_authorized") is not False
            or artifact.get("underlying_gate") != "PENDING_UNTOUCHED_HOLDOUT"
            or artifact.get("option_shadow_collection_authorized") is not False
            or validation_status != "SEALED_UNEVALUATED"
        ):
            self.last_warnings.append("directional_research_artifact_not_shadow_eligible")
            return []

        try:
            requested_symbols = _symbols(symbols or ())
            requested = (requested_symbols or _universe_symbols(self.universe_path))[: max(1, int(self.candidate_limit))]
        except Exception as exc:
            self.last_warnings.append(f"directional_research_universe_unavailable:{type(exc).__name__}:{exc}")
            return []
        context_by_symbol = symbol_context or {}
        snapshots: dict[str, tuple[dict[str, Any], datetime]] = {}
        for symbol in requested:
            try:
                candles = (
                    self.candle_fetcher(symbol, context=context)
                    if self.candle_fetcher
                    else _local_daily(symbol, data_path=Path(self.data_path))
                )
                frame = _frame(candles).loc[lambda value: value.index <= context.asof_utc]
                if len(frame) < 41:
                    raise ValueError("insufficient_daily_candles")
                features, data_asof = _latest_features(frame, symbol)
                if _session_age(data_asof.date(), context.asof_utc.date()) > self.max_session_age:
                    raise ValueError("stale_daily_candles")
                snapshots[symbol] = (features, data_asof)
            except Exception as exc:
                self.last_warnings.append(
                    f"directional_research_unavailable:{symbol}:{type(exc).__name__}:{exc}"
                )
        if _needs_sector_residual(artifact):
            try:
                universe, sectors = _universe_metadata(self.universe_path)
                # The peer cross-section is always local and fixed.  It is not
                # an evidence/provider call and cannot reach an option chain.
                for symbol in universe:
                    if symbol in snapshots:
                        continue
                    try:
                        peer_frame = _frame(_local_daily(symbol, data_path=Path(self.data_path)))
                        peer_frame = peer_frame.loc[peer_frame.index <= context.asof_utc]
                        if len(peer_frame) < 41:
                            continue
                        peer_features, peer_asof = _latest_features(peer_frame, symbol)
                        if _session_age(peer_asof.date(), context.asof_utc.date()) <= self.max_session_age:
                            snapshots[symbol] = (peer_features, peer_asof)
                    except Exception:
                        # An unavailable peer is represented by its absence;
                        # sector_residual_momentum_20d then marks singleton/no-
                        # peer targets ineligible rather than using momentum.
                        continue
                _attach_sector_residual_features(snapshots, sectors=sectors)
            except Exception as exc:
                self.last_warnings.append(f"directional_research_sector_residual_unavailable:{type(exc).__name__}:{exc}")
        rows: list[dict[str, Any]] = []
        for symbol in requested:
            try:
                features, data_asof = snapshots[symbol]
                for horizon in SUPPORTED_HORIZONS:
                    spec = dict((artifact.get("horizons") or {}).get(str(horizon)) or {})
                    if int(spec.get("horizon_days") or 0) != horizon:
                        raise ValueError(f"missing_frozen_horizon:{horizon}")
                    scored = score_frozen_artifact(
                        artifact,
                        {**features, "feature_asof": data_asof.isoformat()},
                        horizon_days=horizon,
                        asof_utc=context.asof_utc,
                    )
                    probability_up = float(scored["probability"])
                    side = str(scored["side"])
                    directional = probability_up if side == "long" else 1.0 - probability_up if side == "short" else max(probability_up, 1.0 - probability_up)
                    rows.append(
                        {
                            "symbol": symbol,
                            "side": side,
                            "horizon_days": horizon,
                            "state": "RESEARCH_ONLY",
                            "eligible_for_play": False,
                            "research_signal_eligible": bool(scored.get("eligible", False)),
                            "rank_score": round(abs(probability_up - 0.5) * 2.0, 8),
                            "development_calibrated_probability_up": probability_up,
                            "directional_confidence": directional,
                            "probability_target": scored["probability_target"],
                            "validation_status": validation_status,
                            "blocker": f"terminal_holdout_sealed_until_{holdout.get('end')}",
                            "training_asof": artifact.get("training_asof"),
                            "data_asof_utc": data_asof.isoformat(),
                            "artifact_id": artifact.get("experiment_id"),
                            "artifact_path": str(artifact_path),
                            "calibration_version": scored["calibration_version"],
                            "sector_flow": dict(context_by_symbol.get(symbol) or {}),
                            "development_metrics": dict(spec.get("development_metrics") or {}),
                        }
                    )
            except Exception as exc:
                self.last_warnings.append(
                    f"directional_research_unavailable:{symbol}:{type(exc).__name__}:{exc}"
                )
        rows.sort(
            key=lambda row: (
                -float(row["rank_score"]),
                str(row["symbol"]),
                int(row["horizon_days"]),
            )
        )
        return rows
