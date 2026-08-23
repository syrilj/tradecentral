"""Dependency-injected daily decision-support pipeline; it never places orders."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .adapters.flow import load_live_flow_activity, load_live_forward_flow
from .adapters.internal_models import ChainFreeInternalModelsAdapter
from .adapters.promoted_models import PromotedLSEModelsAdapter
from .adapters.directional_research import FrozenDirectionalResearchAdapter
from .adapters.kronos import load_point_in_time_kronos
from .adapters.options import LSEOptionsAdapter, OptionsProvider, fetch_provider_snapshots
from .adapters.sector_flow import load_sector_flow_discovery
from .clock import RunContext
from .config import DailyPlaysConfig
from .contracts import (
    Confidence,
    ConfidenceKind,
    Entry,
    EvidenceGrade,
    LegSide,
    OptionLeg,
    OptionRight,
    Play,
    PlayState,
    Risk,
    RunMode,
)
from .fusion import entry_authorization_failures, rank_candidates
from .ledger import DEFAULT_OUTPUT_ROOT, persist_run
from .pullback_flow_engine import persist_pullback_plays_run, run_pullback_flow_engine
from .options_validation import (
    OptionsPolicy,
    select_directional_contract,
    validate_structure,
    validate_underlying_quote,
)

RecordLoader = Callable[..., Iterable[Mapping[str, Any]]]
EvidenceLoader = Callable[..., Mapping[str, Any] | None]


@dataclass(frozen=True)
class PipelineAdapters:
    internal_models: RecordLoader
    # Research is intentionally a separate, non-decision surface.  It can
    # broaden an operator's context, but it cannot create a trade or cause an
    # option-chain request.
    research_models: RecordLoader | None = None
    kronos: EvidenceLoader | None = None
    flow: EvidenceLoader | None = None
    flow_activity: EvidenceLoader | None = None
    options: OptionsProvider | None = None
    discovery: EvidenceLoader | None = None


def _call(loader: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Support small fixture lambdas and production adapters without magic globals."""
    try:
        return loader(*args, **kwargs)
    except TypeError:
        try:
            return loader(*args)
        except TypeError:
            return loader()


def empty_live_adapters() -> PipelineAdapters:
    """Use the manifest-selected LSE model when credentialed; fail closed otherwise."""
    models = (
        PromotedLSEModelsAdapter() if os.getenv("LSE_API_KEY") else ChainFreeInternalModelsAdapter()
    )
    return PipelineAdapters(
        internal_models=models,
        research_models=FrozenDirectionalResearchAdapter(),
        kronos=load_point_in_time_kronos,
        flow=load_live_forward_flow,
        flow_activity=load_live_flow_activity,
        options=LSEOptionsAdapter(),
        discovery=load_sector_flow_discovery,
    )


def _policy(config: DailyPlaysConfig) -> OptionsPolicy:
    return OptionsPolicy(
        max_quote_age_seconds=config.regular_quote_max_age_seconds,
        min_dte=config.swing_dte_min,
        max_dte=config.swing_dte_max,
        max_spread_pct=config.max_spread_pct,
        min_open_interest=config.min_open_interest,
        min_volume=config.min_volume,
        min_abs_delta=config.min_abs_delta,
        max_abs_delta=config.max_abs_delta,
        max_position_risk_pct=config.max_position_risk_pct,
        max_underlying_risk_pct=config.max_underlying_risk_pct,
        max_aggregate_open_risk_pct=config.max_aggregate_open_risk_pct,
        shadow_only=config.shadow_only,
    )


def _state(value: str) -> PlayState:
    return PlayState(value) if value in {item.value for item in PlayState} else PlayState.ABSTAIN


def _stable_unique(values: Iterable[str]) -> list[str]:
    """Deduplicate operator messages without changing their causal order."""
    seen: set[str] = set()
    return [value for value in values if value and not (value in seen or seen.add(value))]


_ADVISORY_EVIDENCE_WARNING_PREFIXES = (
    "kronos_",
    "flow_",
    "sector_flow_",
    "research_models_",
    "directional_research_",
    "promoted_model_manifest_advisory:",
)
_MODEL_SYMBOL_WARNING_PREFIXES = (
    "unsupported_promoted_symbol:",
    "promoted_model_unavailable:",
    "internal_model_unavailable:",
)


def _is_advisory_evidence_warning(warning: str) -> bool:
    """Evidence enrichment must never change execution-health semantics."""
    return warning.startswith(_ADVISORY_EVIDENCE_WARNING_PREFIXES)


def _warning_symbol(warning: str) -> str | None:
    """Read a model symbol from the structured adapter warnings, if present."""
    for prefix in _MODEL_SYMBOL_WARNING_PREFIXES:
        if warning.startswith(prefix):
            symbol = warning[len(prefix) :].split(":", 1)[0].upper()
            return symbol or None
    return None


def _rank_research_record(record: Mapping[str, Any]) -> tuple[float, str]:
    """Keep research output reproducible without imposing a decision score."""
    try:
        rank_score = float(record.get("rank_score"))
    except (TypeError, ValueError):
        rank_score = 0.0
    if rank_score != rank_score or rank_score in (float("inf"), float("-inf")):
        rank_score = 0.0
    return (-rank_score, str(record.get("symbol") or ""))


def _confidence(
    candidate: Mapping[str, Any], state: PlayState, failures: Sequence[str] = ()
) -> Confidence:
    row = dict(candidate.get("confidence") or {})
    kind = ConfidenceKind(row.get("confidence_kind", "unavailable"))
    grade = EvidenceGrade(row.get("evidence_grade", "F"))
    reasons = tuple(dict.fromkeys([*(row.get("reasons") or ()), *failures]))
    return Confidence(
        state=state,
        confidence_kind=kind,
        evidence_grade=grade,
        model_probability=row.get("model_probability"),
        calibrated_probability=row.get("calibrated_probability"),
        calibration_version=row.get("calibration_version"),
        reasons=reasons,
        failed_checks=tuple(failures),
        probability_target=row.get("probability_target"),
        horizon_days=row.get("horizon_days"),
        entry_threshold=row.get("entry_threshold"),
        threshold_version=row.get("threshold_version"),
        model_artifact_sha256=row.get("model_artifact_sha256"),
        promotion_authorized=row.get("promotion_authorized") is True,
    )


def _leg(raw: Mapping[str, Any], side: LegSide) -> OptionLeg:
    return OptionLeg(
        side,
        OptionRight(raw["right"]),
        str(raw["occ_symbol"]),
        str(raw["underlying"]),
        date.fromisoformat(str(raw["expiry"])[:10]),
        int(raw["dte"]),
        float(raw["strike"]),
        int(raw["multiplier"]),
        float(raw["bid"]),
        float(raw["ask"]),
        float(raw.get("mid") or (float(raw["bid"]) + float(raw["ask"])) / 2),
        float(raw["spread_pct"]),
        int(raw["volume"]),
        int(raw["open_interest"]),
        datetime.fromisoformat(str(raw["quote_asof_utc"]).replace("Z", "+00:00")),
        str(raw["provider"]),
        raw.get("provider_contract_id"),
        raw.get("iv"),
        raw.get("delta"),
        raw.get("gamma"),
    )


def _make_play(
    candidate: Mapping[str, Any],
    snapshot: Mapping[str, Any] | None,
    *,
    context: RunContext,
    account: float,
    config: DailyPlaysConfig,
    run_id: str,
    existing_underlying_risk_dollars: float = 0.0,
    aggregate_open_risk_dollars: float = 0.0,
) -> Play:
    side = str(candidate.get("side") or "neutral")
    failures: list[str] = []
    legs_raw: list[dict[str, Any]] = []
    confidence_row = candidate.get("confidence") or {}
    is_calibrated = (
        confidence_row.get("confidence_kind") == ConfidenceKind.CALIBRATED_PROBABILITY.value
    )
    semantic_probability = (
        is_calibrated
        and confidence_row.get("probability_target") == "underlying_directional_return"
        and confidence_row.get("horizon_days") in {5, 10, 20}
        and not entry_authorization_failures(confidence_row)
    )
    if (
        semantic_probability
        and context.mode is RunMode.LIVE
        and context.market_session.value != "regular"
    ):
        failures.append("market_session_not_regular")
    elif snapshot is None and semantic_probability:
        failures.append("options_provider_unavailable")
    elif snapshot is not None:
        failures.extend(
            validate_underlying_quote(
                snapshot,
                asof_utc=context.asof_utc,
                max_age_seconds=config.regular_quote_max_age_seconds,
            )
        )
        selection = select_directional_contract(
            [dict(x, side="buy") for x in snapshot.get("contracts", []) if isinstance(x, Mapping)],
            direction=side,
            asof_utc=context.asof_utc,
            account_value=account,
            existing_underlying_risk_dollars=existing_underlying_risk_dollars,
            aggregate_open_risk_dollars=aggregate_open_risk_dollars,
            policy=_policy(config),
            promotion_eligible=True,
        )
        if selection.eligible and selection.leg:
            legs_raw = [dict(selection.leg, side="buy")]
        else:
            failures.extend(selection.failed_checks)
    result = (
        validate_structure(
            legs_raw,
            asof_utc=context.asof_utc,
            max_loss_dollars=account * config.max_account_risk_pct,
            policy=_policy(config),
            degraded=bool(snapshot and snapshot.get("degraded")),
        )
        if legs_raw
        else None
    )
    if result:
        failures.extend(result.failed_checks)
    prelim = str((candidate.get("confidence") or {}).get("state", "ABSTAIN"))
    can_enter = (
        prelim == "WATCH"
        and semantic_probability
        and result is not None
        and result.eligible
        and context.mode is RunMode.LIVE
        and context.market_session.value == "regular"
    )
    state = (
        PlayState.ENTER
        if can_enter
        else (PlayState.WATCH if not failures and prelim == "WATCH" else PlayState.ABSTAIN)
    )
    # Replay is allowed to demonstrate an execution-valid ticket, but never changes the non-live safety state.
    if (
        context.mode is RunMode.REPLAY
        and semantic_probability
        and result
        and result.eligible
        and not failures
    ):
        state = PlayState.ENTER
    leg_objs: list[OptionLeg] = []
    for raw in legs_raw:
        try:
            leg_objs.append(_leg(raw, LegSide.BUY))
        except (KeyError, TypeError, ValueError):
            failures.append("invalid_canonical_option_leg")
    quote_time = leg_objs[0].quote_asof_utc if leg_objs else context.asof_utc
    max_loss = result.max_loss_dollars if result and result.max_loss_dollars is not None else 0.0
    confidence = _confidence(candidate, state, failures)
    return Play(
        f"{run_id}:{candidate.get('symbol')}:{'long_call' if side == 'long' else 'long_put'}",
        str(candidate.get("symbol")),
        side,
        "long_call" if side == "long" else "long_put",
        state,
        int(candidate["rank"]),
        ("Model and research candidate; decision support only.",),
        tuple(failures) or ("execution validation required",),
        Entry(
            float((legs_raw[0].get("ask") if legs_raw else 0) or 0),
            float(((snapshot or {}).get("underlying") or {}).get("price") or 0),
            quote_time,
            config.regular_quote_max_age_seconds,
        ),
        tuple(leg_objs),
        Risk(account, max_loss, max_loss / account if account else 0, 1 if leg_objs else 0),
        confidence,
        candidate.get("evidence") or {},
        {"options_snapshot_asof_utc": (snapshot or {}).get("asof_utc")},
        {
            "decision_support_only": True,
            "shadow_only": config.shadow_only,
            "shadow_horizon_days": confidence.horizon_days or 10,
            "probability_target": confidence.probability_target,
        },
    )


def run_pipeline(
    *,
    context: RunContext,
    account: float,
    config: DailyPlaysConfig,
    adapters: PipelineAdapters | None = None,
    output_root: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    adapters = adapters or empty_live_adapters()
    warnings: list[str] = []
    research_warnings: list[str] = []
    discovery: dict[str, Any] = {}
    flow_activity: dict[str, Any] = {}
    research_board: list[Mapping[str, Any]] = []
    if adapters.discovery:
        try:
            value = _call(adapters.discovery, context=context, config=config)
            if isinstance(value, Mapping):
                discovery = dict(value)
                if discovery.get("_evidence_warning"):
                    warnings.append(str(discovery["_evidence_warning"]))
        except Exception as exc:
            warnings.append(f"sector_flow_unavailable:{type(exc).__name__}")
    if adapters.flow_activity and discovery.get("target_symbols"):
        try:
            value = _call(
                adapters.flow_activity,
                symbols=list(discovery.get("target_symbols") or ()),
                context=context,
                asof_utc=context.asof_utc,
            )
            if isinstance(value, Mapping):
                flow_activity = dict(value)
                activity_warnings = list(flow_activity.get("warnings") or ())
                if activity_warnings:
                    warnings.append(f"flow_activity_partial:{len(activity_warnings)}")
                routing_order = [
                    str(symbol).upper()
                    for symbol in flow_activity.get("routing_order") or ()
                    if symbol
                ]
                if routing_order:
                    discovery["target_symbols"] = routing_order
        except Exception as exc:
            warnings.append(f"flow_activity_unavailable:{type(exc).__name__}")
    if (
        isinstance(adapters.options, LSEOptionsAdapter)
        and adapters.options.fetcher is None
        and not (adapters.options.api_key or os.getenv("LSE_API_KEY"))
    ):
        warnings.append("lse_credential_missing")
    try:
        internals = list(
            _call(
                adapters.internal_models,
                context=context,
                asof_utc=context.asof_utc,
                config=config,
                symbols=discovery.get("target_symbols") or None,
                symbol_context=discovery.get("symbol_context") or None,
            )
        )
        warnings.extend(getattr(adapters.internal_models, "last_warnings", []))
    except Exception as exc:
        internals = []
        warnings.append(f"internal_models_unavailable:{type(exc).__name__}:{exc}")
    if adapters.research_models:
        try:
            research_rows = _call(
                adapters.research_models,
                context=context,
                asof_utc=context.asof_utc,
                config=config,
                symbols=discovery.get("target_symbols") or None,
                symbol_context=discovery.get("symbol_context") or None,
            )
            # A research board remains source-owned context.  The pipeline only
            # normalizes it enough to make its display order deterministic.
            research_board = sorted(
                [dict(row) for row in research_rows if isinstance(row, Mapping)],
                key=_rank_research_record,
            )
            research_warnings.extend(getattr(adapters.research_models, "last_warnings", []))
            warnings.extend(research_warnings)
        except Exception as exc:
            warning = f"research_models_unavailable:{type(exc).__name__}:{exc}"
            research_warnings.append(warning)
            warnings.append(warning)
    kronos: dict[str, Mapping[str, Any]] = {}
    flow: dict[str, Mapping[str, Any]] = {
        str(row.get("symbol") or "").upper(): row
        for row in flow_activity.get("rows") or ()
        if isinstance(row, Mapping) and row.get("symbol")
    }
    flow_activity_attempted = {
        str(symbol).upper() for symbol in flow_activity.get("requested_symbols") or () if symbol
    }
    symbols = _stable_unique(str(raw.get("symbol") or "").upper() for raw in internals)
    for symbol in symbols:
        if adapters.kronos:
            try:
                value = _call(adapters.kronos, symbol, context=context, asof_utc=context.asof_utc)
                if value and isinstance(value, Mapping) and value.get("_evidence_warning"):
                    warnings.append(str(value["_evidence_warning"]))
                elif value:
                    kronos[symbol] = value
            except Exception as exc:
                warnings.append(f"kronos_unavailable:{symbol}:{type(exc).__name__}")
        if adapters.flow and symbol not in flow and symbol not in flow_activity_attempted:
            try:
                value = _call(adapters.flow, symbol, context=context, asof_utc=context.asof_utc)
                if value and isinstance(value, Mapping) and value.get("_evidence_warning"):
                    warnings.append(str(value["_evidence_warning"]))
                elif value:
                    flow[symbol] = value
            except Exception as exc:
                warnings.append(f"flow_unavailable:{symbol}:{type(exc).__name__}")
    candidates = rank_candidates(
        internals, kronos_by_symbol=kronos, flow_by_symbol=flow, limit=config.shortlist_limit
    )
    snapshots: list[Mapping[str, Any]] = []
    plays: list[Play] = []
    chain_requests = 0
    chain_eligible_candidates = 0
    open_risk_by_underlying: dict[str, float] = defaultdict(float)
    aggregate_open_risk = 0.0
    fetched_snapshots: dict[str, Mapping[str, Any]] = {}
    snapshot_errors: dict[str, Exception] = {}
    if adapters.options:
        no_lse_key = (
            isinstance(adapters.options, LSEOptionsAdapter)
            and adapters.options.fetcher is None
            and not (adapters.options.api_key or os.getenv("LSE_API_KEY"))
        )
        if not no_lse_key:
            candidate_symbols = [str(c["symbol"]).upper() for c in candidates if c.get("symbol")]
            fetched_snapshots, snapshot_errors = fetch_provider_snapshots(
                adapters.options, candidate_symbols, asof_utc=context.asof_utc
            )

    mode = context.mode
    for candidate in candidates:
        snapshot = None
        confidence_row = candidate.get("confidence") or {}
        chain_eligible = (
            candidate.get("state") == "WATCH"
            and candidate.get("side") in {"long", "short"}
            and confidence_row.get("confidence_kind") == ConfidenceKind.CALIBRATED_PROBABILITY.value
            and confidence_row.get("probability_target") == "underlying_directional_return"
            and confidence_row.get("horizon_days") in {5, 10, 20}
            and not entry_authorization_failures(confidence_row)
            and (context.mode is RunMode.REPLAY or context.market_session.value == "regular")
        )
        if adapters.options:
            no_lse_key = (
                isinstance(adapters.options, LSEOptionsAdapter)
                and adapters.options.fetcher is None
                and not (adapters.options.api_key or os.getenv("LSE_API_KEY"))
            )
            if not no_lse_key:
                if chain_eligible:
                    chain_requests += 1
                sym_key = str(candidate["symbol"]).upper()
                if sym_key in snapshot_errors:
                    exc = snapshot_errors[sym_key]
                    warnings.append(
                        f"options_unavailable:{candidate['symbol']}:{type(exc).__name__}"
                    )
                else:
                    snapshot = fetched_snapshots.get(sym_key)
                    if snapshot:
                        snapshots.append(snapshot)
        if chain_eligible:
            chain_eligible_candidates += 1
        symbol = str(candidate.get("symbol") or "").upper()
        play = _make_play(
            candidate,
            snapshot,
            context=RunContext(
                context.requested_for, context.asof_utc, context.market_session, mode
            ),
            account=account,
            config=config,
            run_id=context.run_id(account=account, config_hash=config.config_hash),
            existing_underlying_risk_dollars=open_risk_by_underlying[symbol],
            aggregate_open_risk_dollars=aggregate_open_risk,
        )
        plays.append(play)
        if play.state is PlayState.ENTER:
            open_risk_by_underlying[symbol] += play.risk.max_loss_dollars
            aggregate_open_risk += play.risk.max_loss_dollars
    warnings = _stable_unique(warnings)
    advisory_evidence_warnings = [
        warning
        for warning in warnings
        if _is_advisory_evidence_warning(warning) or warning in research_warnings
    ]
    # An unsupported symbol is a coverage fact, not an outage of the symbols
    # that were successfully scanned.  Kronos, flow, sector routing, and the
    # optional research board are likewise non-gating context.
    execution_health_warnings = [
        warning
        for warning in warnings
        if warning not in advisory_evidence_warnings
        and not warning.startswith("unsupported_promoted_symbol:")
    ]
    if execution_health_warnings and mode is RunMode.LIVE:
        mode = RunMode.DEGRADED
    manifest = replace(
        context.manifest(account=account, config_hash=config.config_hash, mode=mode),
        warnings=tuple(warnings),
    )
    manifest_data = manifest.to_dict()
    manifest_data["warnings"] = warnings
    decision_dicts = [p.to_dict() for p in plays]
    actionable_plays = [p for p in decision_dicts if p["state"] == "ENTER"]
    watchlist = [p for p in decision_dicts if p["state"] == "WATCH"]
    rejections = [p for p in decision_dicts if p["state"] == "ABSTAIN"]
    decision_reasons = _stable_unique(
        str(reason)
        for decision in decision_dicts
        for reason in (decision.get("confidence") or {}).get("reasons", [])
    )
    decision_blockers = list(decision_reasons)
    # The pullback flow engine is a complementary live discovery path.  When
    # the model funnel produced no actionable ticket (nothing reached
    # execution validation), it contributes its own honestly-labelled,
    # policy-gated technical-screen tickets so the operator surface is not
    # empty all session.  Model decisions stay authoritative: they remain in
    # watchlist/rejections with their validated evidence, and engine tickets
    # are appended alongside them under a distinct provenance.
    #
    # Gating: persist=True separates production/API invocations from isolated
    # test runs (which use persist=False and must never trigger an engine scan
    # against real repo data).  When the pipeline runs against an explicit
    # output_root, the engine scans that same tree so it cannot leak real repo
    # data into an isolated run.
    if not actionable_plays and persist:
        engine_root = (
            Path(output_root).resolve() if output_root else Path(__file__).resolve().parents[1]
        )
        try:
            pb_res = run_pullback_flow_engine(
                account=account,
                context=context,
                config=config,
                root_dir=engine_root,
            )
            pb_plays = [row for row in (pb_res.get("plays") or []) if isinstance(row, Mapping)]
            pb_watch = [row for row in (pb_res.get("watchlist") or []) if isinstance(row, Mapping)]
            if pb_plays or pb_watch:
                persist_pullback_plays_run(pb_res, output_root=output_root or DEFAULT_OUTPUT_ROOT)
            # The model funnel's own artifacts still persist under this run id
            # so replay/audit tooling finds a complete run either way.
            persist_run(
                manifest=manifest,
                candidates=candidates,
                option_snapshots=snapshots,
                plays=[],
                decisions=decision_dicts,
                discovery=discovery,
                flow_activity=flow_activity,
                research_board=research_board,
                output_root=output_root,
            )
            model_covered = [
                str(symbol).upper()
                for symbol in discovery.get("model_covered_symbols") or []
                if symbol
            ]
            merged_warnings = _stable_unique(
                [*warnings, f"fallback_engine_used:{pb_res.get('run_id')}"]
            )
            execution_health_warnings = _stable_unique(
                [
                    warning
                    for warning in merged_warnings
                    if not _is_advisory_evidence_warning(warning)
                ]
                + list(pb_res.get("execution_health_warnings") or ())
            )
            manifest = replace(
                context.manifest(account=account, config_hash=config.config_hash, mode=mode),
                warnings=tuple(merged_warnings),
            )
            manifest_data = manifest.to_dict()
            manifest_data["warnings"] = merged_warnings
            return {
                **manifest_data,
                "status": "COMPLETE" if pb_plays else "NO_PLAY",
                "engine": "pullback_flow_engine" if (pb_plays or pb_watch) else None,
                "market_map": discovery.get("market_map") or {},
                "scan_scope": {
                    "sector_books_scored": discovery.get("sector_books_scored", 0),
                    "broad_universe_count": discovery.get("broad_universe_count", 0),
                    "targeted_count": discovery.get("targeted_count", 0),
                    "model_covered_count": discovery.get("model_covered_count", 0),
                    "sector_books": discovery.get("sector_books_scored", 0),
                    "routed_targets": discovery.get("targeted_count", 0),
                    "model_domain_supported": len(model_covered),
                    "model_domain_supported_symbols": model_covered,
                    "successfully_scanned_candidates": len(internals),
                    "fused_candidates": len(candidates),
                    "directional_setups": sum(
                        bool(row.get("setup_ok")) and str(row.get("side") or "neutral") != "neutral"
                        for row in internals
                    ),
                    "chain_eligible_candidates": chain_eligible_candidates,
                    "chain_requests": chain_requests,
                    "chain_snapshots": len(snapshots)
                    + int((pb_res.get("scan_scope") or {}).get("chain_snapshots") or 0),
                    "unavailable_model_symbols": _stable_unique(
                        symbol for symbol in (_warning_symbol(w) for w in merged_warnings) if symbol
                    ),
                    "flow_activity_requested": int(
                        (flow_activity.get("coverage") or {}).get("requested") or 0
                    ),
                    "flow_activity_observed": int(
                        (flow_activity.get("coverage") or {}).get("with_activity") or 0
                    ),
                },
                "candidates": candidates,
                "flow_activity": flow_activity,
                "research_board": research_board,
                "research_board_count": len(research_board),
                "plays": pb_plays,
                "watchlist": [*watchlist, *pb_watch],
                "rejections": rejections,
                "decision_count": len(decision_dicts) + len(pb_plays) + len(pb_watch),
                "rejected_count": len(rejections),
                "decision_blockers": [] if pb_plays else decision_blockers,
                "advisory_evidence_warnings": advisory_evidence_warnings,
                "execution_health_warnings": execution_health_warnings,
                "abstention_reasons": [] if pb_plays else _stable_unique(decision_blockers),
                "engine_run_id": pb_res.get("run_id"),
            }
        except Exception as exc:
            warnings.append(f"pullback_flow_engine_unavailable:{type(exc).__name__}:{exc}")

    if not actionable_plays and not decision_blockers:
        decision_blockers.append(
            "no_successfully_scanned_model_candidates"
            if not internals
            else "no_live_validated_actionable_plays"
        )
    model_domain_symbols = [
        str(symbol).upper() for symbol in discovery.get("model_covered_symbols") or [] if symbol
    ]
    unavailable_model_symbols = _stable_unique(
        symbol for symbol in (_warning_symbol(warning) for warning in warnings) if symbol
    )
    result = {
        **manifest_data,
        "status": "COMPLETE" if actionable_plays else "NO_PLAY",
        "market_map": discovery.get("market_map") or {},
        "scan_scope": {
            "sector_books_scored": discovery.get("sector_books_scored", 0),
            "broad_universe_count": discovery.get("broad_universe_count", 0),
            "targeted_count": discovery.get("targeted_count", 0),
            "model_covered_count": discovery.get("model_covered_count", 0),
            # Explicit funnel names are retained alongside the established
            # fields above for API compatibility.
            "sector_books": discovery.get("sector_books_scored", 0),
            "routed_targets": discovery.get("targeted_count", 0),
            "model_domain_supported": len(model_domain_symbols),
            "model_domain_supported_symbols": model_domain_symbols,
            "successfully_scanned_candidates": len(internals),
            "fused_candidates": len(candidates),
            "directional_setups": sum(
                bool(row.get("setup_ok")) and str(row.get("side") or "neutral") != "neutral"
                for row in internals
            ),
            "chain_eligible_candidates": chain_eligible_candidates,
            "chain_requests": chain_requests,
            "chain_snapshots": len(snapshots),
            "unavailable_model_symbols": unavailable_model_symbols,
            "flow_activity_requested": int(
                (flow_activity.get("coverage") or {}).get("requested") or 0
            ),
            "flow_activity_observed": int(
                (flow_activity.get("coverage") or {}).get("with_activity") or 0
            ),
        },
        "candidates": candidates,
        "flow_activity": flow_activity,
        "research_board": research_board,
        "research_board_count": len(research_board),
        # Operator/API semantics: a "play" is actionable. WATCH and ABSTAIN
        # records remain separately named and available for audit.
        "plays": actionable_plays,
        "watchlist": watchlist,
        "rejections": rejections,
        "decision_count": len(decision_dicts),
        "rejected_count": len(rejections),
        "decision_blockers": [] if actionable_plays else decision_blockers,
        "advisory_evidence_warnings": advisory_evidence_warnings,
        "execution_health_warnings": execution_health_warnings,
        "abstention_reasons": ([] if actionable_plays else _stable_unique([*decision_blockers])),
    }
    if persist:
        persist_run(
            manifest=manifest,
            candidates=candidates,
            option_snapshots=snapshots,
            plays=actionable_plays,
            decisions=decision_dicts,
            discovery=discovery,
            flow_activity=flow_activity,
            research_board=research_board,
            output_root=output_root,
        )
    return result
