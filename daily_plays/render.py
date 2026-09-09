"""Operator rendering deliberately separates plays from rejected research rows."""
from __future__ import annotations
from typing import Any, Mapping


_REASON_LABELS = {
    "lse_credential_missing": "live options feed unavailable (LSE_API_KEY is not configured)",
    "flow_lse_credential_missing": "live options-flow confirmation unavailable",
    "flow_lse_provider_cooldown": "live options-flow confirmation unavailable (LSE provider in failure cooldown; the key is configured)",
    "kronos_same_session_artifact_missing": "same-session Kronos research artifact unavailable",
    "kronos_symbol_not_in_same_session_artifact": "some candidates lack same-session Kronos coverage",
    "setup_not_ready": "the promoted models produced no directional setup",
    "no_directional_model_setup": "the promoted models produced no directional setup",
    "model_probability_not_calibrated": "no entry-eligible fixed-horizon probability is available",
    "calibrated_probability_operating_point_missing": "the model has no frozen entry operating point",
    "model_probability_below_entry_threshold": "the model probability is below its frozen entry threshold",
    "model_artifact_not_promotion_authorized": "the model artifact is not authorized for option validation",
    "market_session_not_regular": "the options market is outside the regular-session entry window",
    "no_successfully_scanned_model_candidates": "no model candidates were successfully scanned",
    "options_provider_unavailable": "live option-chain validation was unavailable for a directional setup",
    "no_live_validated_actionable_plays": "no candidate passed every model, quote, liquidity, and risk gate",
}


def _operator_reasons(result: Mapping[str, Any]) -> list[str]:
    seen: set[str] = set()
    reasons: list[str] = []
    # New pipeline results carry only causal blockers here.  Retain the old
    # abstention list as a compatibility fallback for saved historical runs.
    for raw in result.get("decision_blockers") or result.get("abstention_reasons") or ():
        text = str(raw)
        label = _REASON_LABELS.get(text)
        if label is None and text.startswith("options_unavailable:"):
            label = "live option-chain validation failed"
        if label is None and text.startswith("internal_models_unavailable:"):
            label = "promoted live model scan unavailable"
        if label and label not in seen:
            seen.add(label)
            reasons.append(label)
    return reasons


def _execution_health_notes(result: Mapping[str, Any]) -> list[str]:
    labels: list[str] = []
    for warning in result.get("execution_health_warnings") or ():
        text = str(warning)
        if text in {"lse_credential_missing", "promoted_models_lse_credential_missing"}:
            label = "live LSE execution feed is unavailable"
        elif text.startswith("options_unavailable:"):
            label = "a requested live option chain was unavailable"
        elif text.startswith(("internal_models_unavailable:", "promoted_model_unavailable:")):
            label = "part of the live model scan was unavailable"
        else:
            continue
        if label not in labels:
            labels.append(label)
    return labels


def _research_board_lines(result: Mapping[str, Any]) -> list[str]:
    """Render a small, explicitly non-executable sealed-holdout board."""
    rows: list[Mapping[str, Any]] = []
    seen_symbols: set[str] = set()
    for raw in result.get("research_board") or ():
        if not isinstance(raw, Mapping):
            continue
        symbol = str(raw.get("symbol") or "").upper()
        if not symbol or symbol in seen_symbols:
            continue
        seen_symbols.add(symbol)
        rows.append(raw)
        if len(rows) == 5:
            break
    if not rows:
        return []
    lines = ["Research board (sealed holdout — not plays):"]
    for row in rows:
        symbol = str(row.get("symbol") or "-").upper()
        side = str(row.get("side") or "neutral").lower()
        try:
            horizon = int(row.get("horizon_days"))
        except (TypeError, ValueError):
            horizon = 0
        probability = row.get("directional_confidence", row.get("development_calibrated_probability_up"))
        label = f"{float(probability):.1%}" if isinstance(probability, (int, float)) else "unavailable"
        lines.append(f"{symbol} {side} H{horizon} dev-calibrated {label}")
    lines.append("These are not live-validated and cannot be acted on until the terminal holdout clears.")
    return lines


def _research_health_notes(result: Mapping[str, Any]) -> list[str]:
    """Explain why broad-market context is absent without calling it a blocker."""
    for raw in result.get("advisory_evidence_warnings") or ():
        warning = str(raw)
        if "daily_directional_artifact_failed_development" in warning:
            return ["Broad-market research scan: latest challenger failed development validation."]
        if warning.startswith(("directional_research_artifact_unavailable:", "research_models_unavailable:")):
            return ["Broad-market research scan: frozen challenger was unavailable."]
    return []


def _money(value: Any) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "—"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:.0f}"


def render_report(result: Mapping[str, Any]) -> str:
    lines = [f"Daily plays: {result.get('status', 'COMPLETE')} ({result.get('market_session')}, {result.get('mode')})"]
    market_map = result.get("market_map") if isinstance(result.get("market_map"), Mapping) else {}
    rotation = market_map.get("rotation") if isinstance(market_map.get("rotation"), Mapping) else {}
    money_in = [str(row.get("etf")) for row in market_map.get("money_in") or [] if row.get("etf")]
    money_out = [str(row.get("etf")) for row in market_map.get("money_out") or [] if row.get("etf")]
    if rotation or money_in or money_out:
        kind = str(rotation.get("kind") or "unclear").replace("_", " ").upper()
        lines.append(
            f"Market map: {kind} | money in {', '.join(money_in[:4]) or '—'} "
            f"| money out {', '.join(money_out[:4]) or '—'}"
        )
    flow_activity = result.get("flow_activity") if isinstance(result.get("flow_activity"), Mapping) else {}
    activity_rows = [row for row in flow_activity.get("rows") or () if isinstance(row, Mapping)]
    coverage = flow_activity.get("coverage") if isinstance(flow_activity.get("coverage"), Mapping) else {}
    if coverage.get("requested"):
        leaders = ", ".join(
            f"{str(row.get('symbol') or '-').upper()} {_money((row.get('evidence') or {}).get('premium'))}"
            for row in activity_rows[:4]
        )
        lines.append(
            f"Options activity route: {int(coverage.get('with_activity') or 0)}/"
            f"{int(coverage.get('requested') or 0)} names with prints"
            f" | leaders {leaders or '—'} | unsigned tape, routing only"
        )
    scope = result.get("scan_scope") if isinstance(result.get("scan_scope"), Mapping) else {}
    if any(key in scope for key in ("sector_books_scored", "targeted_count", "sector_books", "routed_targets")):
        detailed_keys = (
            "successfully_scanned_candidates", "directional_setups",
            "chain_requests", "chain_snapshots",
        )
        if any(key in scope for key in detailed_keys):
            lines.append(
                f"Scan funnel: {int(scope.get('sector_books') or scope.get('sector_books_scored') or 0)} sector books → "
                f"{int(scope.get('routed_targets') or scope.get('targeted_count') or 0)} routed targets → "
                f"{int(scope.get('model_domain_supported') or scope.get('model_covered_count') or 0)} model-domain → "
                f"{int(scope.get('successfully_scanned_candidates') or 0)} scanned → "
                f"{int(scope.get('directional_setups') or 0)} directional → "
                f"{int(scope.get('chain_requests') or 0)}/{int(scope.get('chain_snapshots') or 0)} chains (requested/snapshots)"
            )
        else:
            lines.append(
                f"Scan funnel: {int(scope.get('sector_books_scored') or 0)} sector/theme books → "
                f"{int(scope.get('targeted_count') or 0)} flow targets → "
                f"{int(scope.get('model_covered_count') or 0)} model-covered symbols"
            )
    plays = [play for play in (result.get("plays") or []) if play.get("state") == "ENTER"]
    if not plays:
        lines.append("No live-validated actionable plays today.")
        reasons = _operator_reasons(result)
        if reasons:
            lines.append("Why: " + "; ".join(reasons[:3]) + ".")
        health_notes = _execution_health_notes(result)
        if health_notes:
            lines.append("Execution health: " + "; ".join(health_notes[:2]) + ".")
        unavailable = [str(symbol) for symbol in scope.get("unavailable_model_symbols") or [] if symbol]
        if unavailable:
            lines.append("Unavailable model symbols: " + ", ".join(unavailable[:8]) + ".")
        lines.extend(_research_health_notes(result))
        rejected = int(result.get("rejected_count") or 0)
        watched = len(result.get("watchlist") or [])
        if rejected or watched:
            lines.append(
                f"Audit only: {rejected} rejected candidate(s), {watched} watch candidate(s). "
                "They are not plays."
            )
        lines.extend(_research_board_lines(result))
        return "\n".join(lines)
    lines.append("Validated actionable plays")
    lines.append("Rank  Symbol  Strategy                 Confidence  Max loss")
    for play in plays:
        confidence = play.get("confidence") or {}
        probability = confidence.get("calibrated_probability")
        label = f"{probability:.1%}" if isinstance(probability, (int, float)) else "unavailable"
        risk = play.get("risk") or {}
        max_loss = risk.get("max_loss_dollars")
        loss_label = f"${max_loss:,.2f}" if isinstance(max_loss, (int, float)) else "—"
        lines.append(
            f"{play.get('rank', '-'):>4}  {play.get('symbol', '-'):<6}  "
            f"{play.get('strategy', '-'):<23} {label:<10}  {loss_label}"
        )
        if play.get("legs"):
            lines.append(
                "      Ticket: "
                + ", ".join(
                    f"{leg['side'].upper()} {leg['occ_symbol']} @ limit ≤ ${float(leg['ask']):.2f}"
                    for leg in play["legs"]
                )
            )
    return "\n".join(lines)
