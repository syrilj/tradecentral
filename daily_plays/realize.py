"""Fail-closed, idempotent realization of shadow decisions.

This module is deliberately provider-agnostic.  Its caller supplies prices or
binary outcomes; it has no broker or order-routing dependency.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Mapping, Protocol

from .contracts import canonical_json
from .ledger import DEFAULT_OUTPUT_ROOT

DEFAULT_HORIZON_DAYS = 5


class OutcomePriceProvider(Protocol):
    def outcome_for(self, *, play: Mapping[str, Any], due_utc: datetime) -> Mapping[str, Any] | None: ...


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _horizon(play: Mapping[str, Any]) -> int:
    value = (play.get("provenance") or {}).get("shadow_horizon_days", play.get("shadow_horizon_days", DEFAULT_HORIZON_DAYS))
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 365:
        raise ValueError("shadow horizon must be an integer between 1 and 365 days")
    return value


def _provider_outcome(provider: Any, play: Mapping[str, Any], due_utc: datetime) -> Mapping[str, Any] | None:
    if hasattr(provider, "outcome_for"):
        return provider.outcome_for(play=play, due_utc=due_utc)
    if callable(provider):
        return provider(play=play, due_utc=due_utc)
    raise TypeError("outcome provider must implement outcome_for or be callable")


def _realized_record(play: Mapping[str, Any], *, decision_asof: datetime, due_utc: datetime,
                     outcome: Mapping[str, Any]) -> dict[str, Any]:
    play_id = play.get("play_id")
    if not isinstance(play_id, str) or not play_id:
        raise ValueError("play_id is missing")
    outcome_asof = _timestamp(outcome.get("asof_utc"))
    if outcome_asof < due_utc:
        raise ValueError("outcome timestamp precedes configured horizon")
    state = str(play.get("state") or "")
    if state not in {"ENTER", "WATCH", "ABSTAIN"}:
        raise ValueError("play state is invalid")
    confidence = play.get("confidence") or {}
    record: dict[str, Any] = {
        "schema_version": "daily-play-outcome-v1", "play_id": play_id,
        # This legacy realization path evaluates the underlying directional
        # target only.  It is explicitly not an option premium/P&L record.
        "instrument": "underlying", "underlying_only_manual": True,
        "decision_asof_utc": decision_asof.isoformat().replace("+00:00", "Z"),
        "due_utc": due_utc.isoformat().replace("+00:00", "Z"),
        "outcome_asof_utc": outcome_asof.isoformat().replace("+00:00", "Z"),
        "state": state, "confidence_kind": confidence.get("confidence_kind"),
        "calibrated_probability": confidence.get("calibrated_probability"),
    }
    if "outcome" in outcome:
        if not isinstance(outcome["outcome"], bool):
            raise ValueError("binary outcome must be boolean")
        record["outcome"] = outcome["outcome"]
    entry = (play.get("entry") or {}).get("underlying_reference")
    exit_price = outcome.get("price")
    if exit_price is not None:
        if not isinstance(entry, (int, float)) or entry <= 0 or not isinstance(exit_price, (int, float)) or exit_price <= 0:
            raise ValueError("entry and outcome prices must be positive")
        direction = 1 if play.get("side") == "long" else -1 if play.get("side") == "short" else 0
        if not direction:
            raise ValueError("play side is invalid")
        gross = direction * (float(exit_price) / float(entry) - 1.0)
        record.update({"entry_price": float(entry), "exit_price": float(exit_price), "gross_return_pct": gross * 100.0})
        record.setdefault("outcome", gross > 0)
    if "outcome" not in record:
        raise ValueError("outcome requires price or binary outcome")
    return record


def realize_due_decisions(*, output_root: str | Path | None = None, provider: OutcomePriceProvider | Any,
                          asof_utc: datetime | None = None) -> dict[str, Any]:
    """Realize all due decisions once; malformed data is recorded, never guessed."""
    now = (asof_utc or datetime.now(timezone.utc))
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("asof_utc must be timezone-aware")
    now = now.astimezone(timezone.utc)
    root = Path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
    ledger = root / "shadow_decisions.jsonl"
    outcomes_path = root / "shadow_outcomes.jsonl"
    existing: set[str] = set()
    if outcomes_path.exists():
        for line in outcomes_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict) and isinstance(row.get("play_id"), str): existing.add(row["play_id"])
            except json.JSONDecodeError:
                continue
    realized: list[dict[str, Any]] = []; errors: list[dict[str, str]] = []; pending = 0
    if not ledger.exists():
        return {"status": "COMPLETE", "realized": 0, "pending": 0, "errors": [], "outcomes_path": str(outcomes_path)}
    for line_number, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
        try:
            decision = json.loads(line)
            decision_asof = _timestamp(decision.get("asof_utc"))
            plays = decision.get("plays")
            if not isinstance(plays, list): raise ValueError("plays is missing")
            for play in plays:
                if not isinstance(play, Mapping): raise ValueError("play is invalid")
                play_id = play.get("play_id")
                if not isinstance(play_id, str) or not play_id: raise ValueError("play_id is missing")
                if play_id in existing: continue
                due = decision_asof + timedelta(days=_horizon(play))
                if due > now:
                    pending += 1; continue
                if play.get("legs"):
                    errors.append({"play_id": play_id, "error": "option_lifecycle_required"}); continue
                try:
                    outcome = _provider_outcome(provider, play, due)
                except Exception as exc:
                    errors.append({"play_id": play_id, "error": f"outcome_provider_failure:{type(exc).__name__}"}); continue
                if outcome is None:
                    errors.append({"play_id": play_id, "error": "outcome_unavailable"}); continue
                if not isinstance(outcome, Mapping):
                    errors.append({"play_id": play_id, "error": "invalid_outcome:TypeError"}); continue
                try:
                    realized.append(_realized_record(play, decision_asof=decision_asof, due_utc=due, outcome=outcome))
                except (ValueError, TypeError, KeyError) as exc:
                    errors.append({"play_id": play_id, "error": f"invalid_outcome:{type(exc).__name__}"})
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            errors.append({"line": str(line_number), "error": f"invalid_decision:{type(exc).__name__}"})
    if realized:
        outcomes_path.parent.mkdir(parents=True, exist_ok=True)
        with outcomes_path.open("a", encoding="utf-8") as handle:
            for row in realized: handle.write(canonical_json(row) + "\n")
    if errors:
        error_path = root / "shadow_realization_errors.jsonl"
        error_path.parent.mkdir(parents=True, exist_ok=True)
        with error_path.open("a", encoding="utf-8") as handle:
            for row in errors:
                handle.write(canonical_json({"asof_utc": now, **row}) + "\n")
    return {"status": "COMPLETE", "realized": len(realized), "pending": pending, "errors": errors,
            "outcomes_path": str(outcomes_path)}
