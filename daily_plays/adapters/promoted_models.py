"""Live, chain-free adapter for the promoted TradingAlgoWork signal engine.

Candidate discovery uses LSE candles and the *hash-verified* deployment
manifest.  The active v72 dual-sleeve model is ordinal-only: no confidence it
emits is represented as an options-execution probability.  A damaged active
bundle can use only the manifest's ordered fail-closed fallback list.  Both
engines operate on copied OHLCV frames and no engine state is saved.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from threading import Thread
from typing import Any, Callable, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[3]
TAW_ROOT = ROOT / "TradingAlgoWork"
DEPLOYMENT_MANIFEST_PATH = TAW_ROOT / "models" / "poc_va_macdha" / "DEPLOYMENT_MANIFEST.json"
SUPPORTED_MODELS = ("v72_dual_sleeve", "v39d_confluence", "v71_live_confidence", "v39b_live_adapt", "v50_high_win_rate")
# v71's Platt artifact estimates ``realized_r > 0`` over the strategy's
# variable entry-to-exit holding period.  It is not a frozen 5/10/20-day
# underlying-direction probability and therefore cannot authorize an option.
V71_DIAGNOSTIC_TARGET = "strategy_trade_realized_r_positive"
V71_DIAGNOSTIC_HORIZON = "entry_to_strategy_exit"
EQUITY_WINNER_BAG_ORDERED = ("TSLA", "MU", "SPY", "IONQ", "APLD", "XLP", "QQQ")
EQUITY_WINNER_BAG = frozenset(EQUITY_WINNER_BAG_ORDERED)
REGULAR_SESSION_TZ = "America/New_York"
PROVIDER_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class PromotedModelSelection:
    """Manifest routing decision, including why a non-active model was used."""

    model: str | None
    active: bool
    reason: str | None = None
    advisories: tuple[str, ...] = ()


def _source_runtime() -> tuple[Any, Any, Any, Any]:
    if str(TAW_ROOT) not in sys.path:
        sys.path.insert(0, str(TAW_ROOT))
    if str(TAW_ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(TAW_ROOT / "tools"))
    from confidence_runtime import assess_data_freshness, evaluate_confidence, load_active_calibrator  # type: ignore[import-not-found]
    return assess_data_freshness, evaluate_confidence, load_active_calibrator, None


def _symbols(path: str | Path, limit: int) -> list[str]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = raw.get("symbols", []) if isinstance(raw, Mapping) else []
    seen: set[str] = set()
    return [x for x in (str(s).strip().upper() for s in rows) if x and not (x in seen or seen.add(x))][:limit]


def _symbols_from_values(values: Sequence[str], limit: int) -> list[str]:
    seen: set[str] = set()
    return [
        symbol
        for symbol in (str(value).strip().upper().replace(".US", "") for value in values)
        if symbol and not (symbol in seen or seen.add(symbol))
    ][:max(1, int(limit))]


def _promoted_symbols(values: Sequence[str], limit: int) -> tuple[list[str], list[str]]:
    """Filter to the frozen serving domain before applying the scan limit."""
    normalized = _symbols_from_values(values, max(len(values), 1))
    unsupported = [symbol for symbol in normalized if symbol not in EQUITY_WINNER_BAG]
    present = set(normalized)
    selected = [symbol for symbol in EQUITY_WINNER_BAG_ORDERED if symbol in present]
    return selected[:max(1, int(limit))], unsupported


def _frame(candles: Any) -> Any:
    import pandas as pd
    if isinstance(candles, pd.DataFrame):
        df = candles.copy()
        df.columns = [str(column).lower().replace(" ", "_") for column in df.columns]
        if isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
        elif str(df.index.name or "").lower() in {"timestamp", "datetime", "date", "time"}:
            df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
        else:
            timestamp = next((name for name in ("timestamp", "datetime", "date", "time") if name in df), None)
            if timestamp is None:
                return pd.DataFrame()
            df[timestamp] = pd.to_datetime(df[timestamp], utc=True, errors="coerce")
            df = df.dropna(subset=[timestamp]).set_index(timestamp)
    else:
        df = pd.DataFrame(list(candles or []))
        if df.empty or "timestamp" not in df:
            return pd.DataFrame()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"]).set_index("timestamp")
    if df.empty:
        return pd.DataFrame()
    df = df.sort_index()
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    needed = ("open", "high", "low", "close", "volume")
    return pd.DataFrame() if any(x not in df for x in needed) else df.loc[:, needed].apply(pd.to_numeric, errors="coerce").dropna().copy()


def _bounded_call(call: Callable[[], Any], *, timeout_seconds: float) -> Any:
    """Return promptly even if a provider ignores its timeout argument."""
    result: dict[str, Any] = {}

    def run() -> None:
        try:
            result["value"] = call()
        except BaseException as exc:  # sent back to the adapter's fail-closed boundary
            result["error"] = exc

    worker = Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=max(0.01, float(timeout_seconds)))
    if worker.is_alive():
        raise TimeoutError("promoted_candle_provider_timeout")
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _regular_session_hourly(frame: Any, *, asof_utc: datetime) -> Any:
    """Aggregate point-in-time 30m LSE bars into v71's frozen NY 1H bars.

    The training contract uses regular-session 1H bars anchored at 09:30 New
    York, not vendor calendar-hour bars.  Both 30-minute components must be
    present and the completed 1H bucket must end no later than ``asof_utc``.
    """
    import pandas as pd

    if frame.empty:
        return frame.copy()
    asof = asof_utc.astimezone(timezone.utc)
    point_in_time = frame.loc[frame.index <= asof].copy()
    if point_in_time.empty:
        return point_in_time
    local = point_in_time.tz_convert(REGULAR_SESSION_TZ)
    parts: list[dict[str, Any]] = []
    for session_day, day in local.groupby(local.index.date):
        start = pd.Timestamp(datetime.combine(session_day, time(9, 30)), tz=REGULAR_SESSION_TZ)
        end = pd.Timestamp(datetime.combine(session_day, time(16, 0)), tz=REGULAR_SESSION_TZ)
        day = day.loc[(day.index >= start) & (day.index < end)]
        for hour in range(7):
            bucket_start = start + pd.Timedelta(hours=hour)
            bucket_end = bucket_start + pd.Timedelta(hours=1)
            # A partially formed current hour is not an input to the frozen
            # model and neither are incomplete/misaligned provider bars.
            if bucket_end.tz_convert("UTC").to_pydatetime() > asof:
                continue
            expected = {bucket_start, bucket_start + pd.Timedelta(minutes=30)}
            bars = day.loc[day.index.isin(expected)]
            if len(bars) != 2 or set(bars.index) != expected:
                continue
            bars = bars.sort_index()
            parts.append({"timestamp": bucket_start.tz_convert("UTC"), "open": bars["open"].iloc[0],
                          "high": bars["high"].max(), "low": bars["low"].min(),
                          "close": bars["close"].iloc[-1], "volume": bars["volume"].sum()})
    if not parts:
        return pd.DataFrame(columns=("open", "high", "low", "close", "volume"))
    return pd.DataFrame(parts).set_index("timestamp").sort_index()


def _lse_candles(symbol: str, *, context: Any, timeout_seconds: float = PROVIDER_TIMEOUT_SECONDS) -> Any:
    if not os.getenv("LSE_API_KEY"):
        raise RuntimeError("LSE_API_KEY is required for promoted live candles")
    if str(TAW_ROOT) not in sys.path:
        sys.path.insert(0, str(TAW_ROOT))
    start = (context.asof_utc - timedelta(days=365)).strftime("%Y-%m-%d")
    # LSE's ``end`` date is exclusive. Request the following calendar date,
    # then enforce the immutable as-of timestamp in ``_regular_session_hourly``.
    end = (context.asof_utc + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        from services.market_runtime import LSEAdapter  # type: ignore[import-not-found]
        # The LSE catalog/SDK uses provider symbols such as ``SPY`` and
        # ``AAPL``.  ``.US`` is reserved for the promoted model's internal
        # series key below, so do not send it to the market-data API.  The
        # one-year window is larger than the SDK row cap, so request the newest
        # bars; ``_frame`` restores chronological order for the model.
        client = LSEAdapter(api_key=os.environ["LSE_API_KEY"]).client
        return _bounded_call(lambda: client.candles(
            symbol, "30m", start=start, end=end, limit=4000, order="desc"
        ), timeout_seconds=timeout_seconds)
    except ImportError:
        # The root workspace interpreter may not share TradingAlgoWork's venv.
        # Reuse TradingWork's established SDK -> ISO -> vault REST seam rather
        # than degrading a configured live run merely because the SDK wheel is
        # installed in the sibling environment.
        source = ROOT / "TradingWork" / "src"
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
        from lse_provider import fetch_lse_candles  # type: ignore[import-not-found]
        # TradingWork's legacy seam prints transport diagnostics. Keep the
        # daily-plays stdout contract clean (especially for ``--json``);
        # failures are represented by structured adapter warnings instead.
        with redirect_stdout(io.StringIO()):
            return _bounded_call(lambda: fetch_lse_candles(
                symbol.upper(), start=context.asof_utc - timedelta(days=365), end=context.asof_utc,
                timeframe="30m", timeout=max(1, int(timeout_seconds)), use_cache=False, refresh=True,
            ), timeout_seconds=timeout_seconds)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_root(path: Path) -> Path:
    """Return the TradingAlgoWork root for a standard deployment manifest."""
    # <TradingAlgoWork>/models/poc_va_macdha/DEPLOYMENT_MANIFEST.json
    if path.name != "DEPLOYMENT_MANIFEST.json" or len(path.parents) < 3:
        raise ValueError("invalid_deployment_manifest_location")
    return path.parents[2]


def _normalise_manifest_domain(raw: Any) -> tuple[str, ...] | None:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return None
    values = tuple(str(value).strip().upper().removesuffix(".US") for value in raw)
    if not values or any(not value for value in values) or len(set(values)) != len(values):
        return None
    return values


def _verified_active_model(manifest_path: Path) -> PromotedModelSelection:
    """Verify every pinned active-bundle input before allowing it to run.

    The daily adapter deliberately does not read the mutable winner metadata.
    It accepts the active model only when its manifest, frozen seven-symbol
    domain, bundle, required dependencies, calibration artifact, and promotion
    evidence all verify.  This mirrors the production model-registry contract
    while keeping the adapter independently fail-closed.
    """
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, Mapping) or int(data.get("schema_version", 0)) != 1:
            return PromotedModelSelection(None, False, "manifest_schema_invalid")
        active = data.get("active")
        if not isinstance(active, Mapping):
            return PromotedModelSelection(None, False, "manifest_active_missing")
        model = str(active.get("equity_model") or "")
        if model not in SUPPORTED_MODELS:
            return PromotedModelSelection(None, False, "manifest_active_model_unsupported")
        data_contract = data.get("data_contract")
        domain = _normalise_manifest_domain(data_contract.get("universe") if isinstance(data_contract, Mapping) else None)
        if domain != EQUITY_WINNER_BAG_ORDERED:
            return PromotedModelSelection(None, False, "manifest_frozen_domain_invalid")
        bundle = active.get("bundle")
        if not isinstance(bundle, Mapping):
            return PromotedModelSelection(None, False, "manifest_bundle_missing")
        manifest_root = _manifest_root(manifest_path)
        models_root = manifest_path.parent
        expected_bundle_path = f"models/poc_va_macdha/{model}"
        if str(bundle.get("path") or "") != expected_bundle_path:
            return PromotedModelSelection(None, False, "manifest_bundle_path_invalid")
        engine = models_root / model / "signal_engine.py"
        engine_pin = str(bundle.get("signal_engine_sha256") or "")
        if not engine_pin or not engine.is_file() or _sha256(engine) != engine_pin:
            return PromotedModelSelection(None, False, "manifest_active_checksum_invalid")
        config_pin = bundle.get("config_sha256")
        config = models_root / model / "config.json"
        if config_pin and (not config.is_file() or _sha256(config) != str(config_pin)):
            return PromotedModelSelection(None, False, "manifest_config.json_checksum_invalid")
        dependencies = bundle.get("dependencies") or []
        if str(bundle.get("dependency_policy") or "").lower() == "required" and not dependencies:
            return PromotedModelSelection(None, False, "manifest_dependencies_missing")
        if not isinstance(dependencies, list):
            return PromotedModelSelection(None, False, "manifest_dependencies_invalid")
        for dependency in dependencies:
            if not isinstance(dependency, Mapping):
                return PromotedModelSelection(None, False, "manifest_dependency_invalid")
            relative = dependency.get("path")
            pinned = str(dependency.get("sha256") or "")
            if not isinstance(relative, str) or not relative or not pinned:
                return PromotedModelSelection(None, False, "manifest_dependency_invalid")
            artifact = (manifest_root / relative).resolve()
            if manifest_root not in artifact.parents or not artifact.is_file() or _sha256(artifact) != pinned:
                return PromotedModelSelection(None, False, "manifest_dependency_checksum_invalid")
        # Result cards and promotion/calibration evidence are auditable
        # metrics, not executable code. Their drift must be visible but must
        # not silently replace an otherwise verified active model. v72 remains
        # ordinal-only regardless, so no probability-execution authority is
        # derived from these artifacts.
        advisories: list[str] = []
        results_pin = bundle.get("results_sha256")
        results = models_root / model / "results.json"
        if results_pin and (not results.is_file() or _sha256(results) != str(results_pin)):
            advisories.append("manifest_results.json_checksum_invalid")
        external = [data.get("calibration"), *(data.get("promotion_evidence") or [])]
        for record in external:
            if not isinstance(record, Mapping) or not record.get("artifact"):
                continue
            relative = Path(str(record["artifact"]))
            artifact = relative if relative.is_absolute() else manifest_root / relative
            pinned = str(record.get("sha256") or "")
            if not pinned or not artifact.is_file() or _sha256(artifact) != pinned:
                advisories.append("manifest_evidence_checksum_invalid")
        return PromotedModelSelection(model, True, advisories=tuple(advisories))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return PromotedModelSelection(None, False, "manifest_unreadable")


def _manifest_fallback(manifest_path: Path, reason: str | None) -> PromotedModelSelection:
    """Permit only a declared, installed fallback after active verification fails."""
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        fallbacks = data.get("fallbacks") if isinstance(data, Mapping) else None
        if not isinstance(fallbacks, Mapping) or fallbacks.get("policy") != "ordered_fail_closed":
            return PromotedModelSelection(None, False, reason or "manifest_fallback_policy_invalid")
        raw = [data.get("rollback_model"), *(fallbacks.get("equity") or [])]
        candidates = list(dict.fromkeys(str(model) for model in raw if model))
        for model in candidates:
            if model not in SUPPORTED_MODELS:
                continue
            if (manifest_path.parent / model / "signal_engine.py").is_file():
                return PromotedModelSelection(model, False, reason or "manifest_active_invalid")
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    return PromotedModelSelection(None, False, reason or "manifest_no_declared_fallback")


def resolve_promoted_model(*, manifest_path: str | Path = DEPLOYMENT_MANIFEST_PATH) -> PromotedModelSelection:
    """Resolve the live model through the manifest; no implicit winner fallback."""
    path = Path(manifest_path)
    active = _verified_active_model(path)
    return active if active.active else _manifest_fallback(path, active.reason)


def select_promoted_model(
    *, horizon: str = "swing", calibrator_loader: Callable[[str], Mapping[str, Any]] | None = None,
    manifest_path: str | Path = DEPLOYMENT_MANIFEST_PATH, production: bool = True,
) -> str | None:
    """Return the manifest-routed production model or a legacy injected seam.

    ``production=False`` preserves deterministic unit-test/model-runner seams;
    production never falls back to a calibrator-selected model outside the
    deployment control plane.
    """
    del horizon
    if production:
        return resolve_promoted_model(manifest_path=manifest_path).model
    if calibrator_loader is None:
        _, _, calibrator_loader, _ = _source_runtime()
    active = [model for model in ("v71_live_confidence", "v50_high_win_rate") if calibrator_loader(model).get("available")]
    return active[0] if active else "v50_high_win_rate"


def _engine(model: str) -> Any:
    if model not in SUPPORTED_MODELS:
        raise ValueError(f"unsupported_promoted_model:{model}")
    path = TAW_ROOT / "models" / "poc_va_macdha" / model / "signal_engine.py"
    spec = importlib.util.spec_from_file_location(f"edge_promoted_{model}", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot_load_promoted_engine:{model}")
    module = importlib.util.module_from_spec(spec)
    # The source v71 loader expects its module to be importable while loading
    # sibling pure modules.  This is only reached in the production path.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.SignalEngine()


@dataclass
class PromotedLSEModelsAdapter:
    universe_path: str | Path = ROOT / "edge" / "config" / "universe_wide.json"
    candidate_limit: int = 25
    candle_fetcher: Callable[..., Any] | None = None
    model_runner: Callable[..., Mapping[str, Any]] | None = None
    calibrator_loader: Callable[[str], Mapping[str, Any]] | None = None
    confidence_evaluator: Callable[..., Mapping[str, Any]] | None = None
    deployment_manifest_path: str | Path = DEPLOYMENT_MANIFEST_PATH
    provider_timeout_seconds: float = PROVIDER_TIMEOUT_SECONDS
    last_warnings: list[str] = field(default_factory=list, init=False)

    def __call__(
        self, *, context: Any, config: Any | None = None,
        symbols: Sequence[str] | None = None,
        symbol_context: Mapping[str, Mapping[str, Any]] | None = None,
        **_: Any,
    ) -> Iterable[Mapping[str, Any]]:
        self.last_warnings = []
        if self.candle_fetcher is None and not os.getenv("LSE_API_KEY"):
            self.last_warnings.append("promoted_models_lse_credential_missing")
            return []
        injected = self.model_runner is not None and self.calibrator_loader is not None and self.confidence_evaluator is not None
        if injected:
            loader, evaluator = self.calibrator_loader, self.confidence_evaluator
        else:
            freshness_fn, evaluator, loader, _ = _source_runtime()
        path = getattr(config, "universe_path", None) or self.universe_path
        if symbols is not None:
            source_symbols = list(symbols)
        else:
            raw_universe = json.loads(Path(path).read_text(encoding="utf-8"))
            source_symbols = list(raw_universe.get("symbols", [])) if isinstance(raw_universe, Mapping) else []
        requested, unsupported = _promoted_symbols(source_symbols, self.candidate_limit)
        selection = (
            PromotedModelSelection(select_promoted_model(calibrator_loader=loader, production=False), True)
            if injected else resolve_promoted_model(manifest_path=self.deployment_manifest_path)
        )
        if selection.model is None:
            self.last_warnings.append(f"promoted_model_manifest_unavailable:{selection.reason or 'unknown'}")
            return []
        self.last_warnings.extend(f"promoted_model_manifest_advisory:{advisory}" for advisory in selection.advisories)
        if not selection.active:
            self.last_warnings.append(f"promoted_model_manifest_fallback:{selection.model}:{selection.reason or 'active_invalid'}")
        if symbols is None:
            self.last_warnings.extend(f"unsupported_promoted_symbol:{symbol}" for symbol in unsupported)
        sector_context = symbol_context or {}
        out: list[Mapping[str, Any]] = []
        for symbol in requested:
            try:
                if self.candle_fetcher:
                    try:
                        candles = self.candle_fetcher(symbol, context=context, end_utc=context.asof_utc)
                    except TypeError:
                        candles = self.candle_fetcher(symbol, context=context)
                else:
                    candles = _lse_candles(symbol, context=context, timeout_seconds=self.provider_timeout_seconds)
                frame = _regular_session_hourly(_frame(candles), asof_utc=context.asof_utc)
                if len(frame) < 30:
                    raise ValueError("insufficient_regular_session_candles")
                asof = frame.index[-1].to_pydatetime().astimezone(timezone.utc)
                if injected:
                    age = (context.asof_utc - asof).total_seconds() / 60
                    freshness = {"available": True, "stale": age > 180 or age < -5, "future_timestamp": age < -5, "age_minutes": max(age, 0)}
                else:
                    freshness = freshness_fn(asof, now=context.asof_utc, max_age_minutes=180)
                if freshness.get("stale") or freshness.get("future_timestamp"):
                    raise ValueError("future_candle" if freshness.get("future_timestamp") else "stale_candle")
                model = selection.model
                if self.model_runner:
                    signal = dict(self.model_runner(symbol=symbol, frame=frame.copy(), model=model) or {})
                else:
                    eng = _engine(model)
                    weights = eng.generate({f"{symbol}.US": frame.copy()})
                    weight = float(weights[f"{symbol}.US"].iloc[-1])
                    series = getattr(eng, "last_confidence", {}).get(f"{symbol}.US")
                    signal = {"weight": weight, "raw_probability": float(series.iloc[-1]) if series is not None else abs(weight), "setup_ok": weight != 0}
                raw = signal.get("raw_probability")
                raw = float(raw) if raw is not None else None
                weight = float(signal.get("weight") or 0.0)
                side = str(signal.get("side") or ("long" if weight > 0 else "short" if weight < 0 else "neutral"))
                setup_ok = bool(signal.get("setup_ok", side != "neutral"))
                confidence = dict(evaluator(raw, model_ok=raw is not None, setup_ok=setup_ok, freshness=freshness, model=model,
                                            calibrator=loader(model), horizon="swing",
                                            raw_probability_source=f"promoted_{model}_engine") or {})
                diagnostic_probability = (
                    confidence.get("calibrated_probability")
                    if model == "v71_live_confidence"
                    and confidence.get("confidence_kind") == "calibrated_probability"
                    and not confidence.get("uncalibrated")
                    else None
                )
                diagnostic_confidence = (
                    {"value": raw, "semantics": "ordinal_confidence_not_guaranteed_probability", "actionable": False}
                    if model == "v72_dual_sleeve" and raw is not None
                    else None
                )
                out.append({"source": "trading_algo_work_promoted_lse", "symbol": symbol, "asof_utc": asof.isoformat(),
                            "side": side, "setup_ok": setup_ok, "freshness": freshness,
                            "sector_flow": dict(sector_context.get(symbol) or {}),
                            "model": {"id": model, "version": model, "probability": None, "raw_score": raw,
                                      "confidence_kind": "ordinal_score",
                                      "calibration_version": None,
                                      "probability_target": None, "horizon_days": None,
                                      "diagnostic_probability": {
                                          "value": diagnostic_probability,
                                          "target": V71_DIAGNOSTIC_TARGET,
                                          "horizon": V71_DIAGNOSTIC_HORIZON,
                                          "calibration_version": confidence.get("calibration_version"),
                                          "actionable": False,
                                      } if diagnostic_probability is not None else None,
                                      "diagnostic_confidence": diagnostic_confidence,
                                      "state": confidence.get("state"), "reasons": list(confidence.get("reasons") or [])},
                            "provenance": {"data_source": "LSE market runtime (SDK/ISO/vault)", "model_version": model,
                                           "calibration_version": confidence.get("calibration_version"), "candle_asof_utc": asof.isoformat()}})
            except Exception as exc:
                self.last_warnings.append(f"promoted_model_unavailable:{symbol}:{type(exc).__name__}:{exc}")
        return out
