"""Auditable, idempotent persistence for decision-support runs only."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
import json

from .contracts import RunManifest, canonical_json

DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "runs" / "daily_plays"


def persist_run(*, manifest: RunManifest, candidates: Sequence[Mapping[str, Any]],
                option_snapshots: Sequence[Mapping[str, Any]], plays: Sequence[Mapping[str, Any]],
                decisions: Sequence[Mapping[str, Any]] | None = None,
                discovery: Mapping[str, Any] | None = None,
                flow_activity: Mapping[str, Any] | None = None,
                research_board: Sequence[Mapping[str, Any]] | None = None,
                output_root: str | Path | None = None) -> Path:
    """Write a complete immutable run and append its one shadow-ledger entry.

    Replaying the same deterministic run id replaces its identical artifacts and
    does not duplicate the ledger line. ``research_board.json`` is a separate
    contextual artifact; it is deliberately excluded from the decision ledger.
    Nothing in this module talks to a broker.
    """
    root = Path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
    run_dir = root / manifest.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    decision_records = list(decisions) if decisions is not None else list(plays)
    payloads = {
        "manifest.json": manifest.to_dict(), "candidates.json": list(candidates),
        "option_snapshots.json": list(option_snapshots), "plays.json": list(plays),
        "decisions.json": decision_records,
        "discovery.json": dict(discovery or {}),
        "flow_activity.json": dict(flow_activity or {}),
        "research_board.json": list(research_board or ()),
    }
    for name, value in payloads.items():
        (run_dir / name).write_text(canonical_json(value) + "\n", encoding="utf-8")
    ledger = root / "shadow_decisions.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    entry = {"run_id": manifest.run_id, "requested_for": manifest.requested_for,
             "asof_utc": manifest.asof_utc, "mode": manifest.mode,
             "warnings": list(manifest.warnings), "plays": decision_records}
    line = canonical_json(entry)
    old = ledger.read_text(encoding="utf-8").splitlines() if ledger.exists() else []
    if not any(_line_run_id(existing) == manifest.run_id for existing in old):
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    # Entries are hypothetical audit records only.  The lifecycle helper has
    # no broker dependency and will abstain rather than infer missing option
    # NBBO/Greek/corporate-action data.
    from .shadow_lifecycle import append_option_entries
    append_option_entries(output_root=root, plays=decision_records, asof_utc=manifest.asof_utc)
    return run_dir


def _line_run_id(line: str) -> str | None:
    try:
        value = json.loads(line)
        return value.get("run_id") if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None
