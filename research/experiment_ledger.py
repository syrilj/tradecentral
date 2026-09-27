"""Persistent, append-only provenance for research experiments and trials.

This module records research intent and results; it deliberately contains no
data loading, fitting, model selection, or holdout scoring implementation.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .hashing import experiment_hash, stable_hash, trial_hash

SCHEMA_VERSION = "edge-research-experiment-ledger-v1"
_TRIAL_RESULT_STATUSES = frozenset({"COMPLETED", "FAILED", "ABSTAINED"})


def _json_value(value: Any) -> Any:
    """Restrict persisted records to deterministic, portable JSON values."""
    if isinstance(value, Mapping):
        return {str(key): _json_value(value[key]) for key in sorted(value, key=lambda key: str(key))}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("ledger records cannot contain NaN or infinity")
        return value
    raise TypeError(f"ledger records must be JSON values, got {type(value).__name__}")


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def _return_series(values: Sequence[Any]) -> list[float]:
    """Validate and normalize an optional per-trial return series.

    Every element must be castable to a finite float; the series must not be
    empty when the caller has chosen to supply one at all (omit the argument
    entirely for "no series recorded" -- see ``record_trial_result``).
    """
    series = [float(value) for value in values]
    if not series:
        raise ValueError("return_series must not be empty when provided")
    for value in series:
        if not math.isfinite(value):
            raise ValueError("return_series values must be finite")
    return series


def _boundaries(value: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    required = ("train", "validation", "terminal_holdout")
    if set(value) != set(required):
        raise ValueError("boundaries must contain exactly train, validation, and terminal_holdout")
    normalized: dict[str, dict[str, str]] = {}
    for name in required:
        boundary = value[name]
        if not isinstance(boundary, Mapping) or set(boundary) != {"start", "end"}:
            raise ValueError(f"{name} boundary must contain exactly start and end")
        start = _require_text(boundary["start"], f"{name}.start")
        end = _require_text(boundary["end"], f"{name}.end")
        if start > end:
            raise ValueError(f"{name} boundary start must not be after end")
        normalized[name] = {"start": start, "end": end}
    # Lexical ISO-8601 ordering makes this a useful guard while retaining the
    # exact boundary strings supplied by the preregistration record.
    if normalized["train"]["end"] >= normalized["validation"]["start"]:
        raise ValueError("train and validation boundaries must not overlap")
    if normalized["validation"]["end"] >= normalized["terminal_holdout"]["start"]:
        raise ValueError("validation and terminal_holdout boundaries must not overlap")
    return normalized


def _upstream_sources(values: Sequence[Mapping[str, Any] | Any]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for source in values:
        raw = source.to_dict() if hasattr(source, "to_dict") else source
        if not isinstance(raw, Mapping):
            raise TypeError("upstream provenance must be mappings or UpstreamSource values")
        item = {field: _require_text(raw.get(field), f"upstream.{field}") for field in ("name", "url", "commit", "license")}
        if len(item["commit"]) != 40 or any(char not in "0123456789abcdef" for char in item["commit"]):
            raise ValueError("upstream.commit must be a full lowercase 40-character SHA")
        if bool(raw.get("code_imported", False)):
            raise ValueError("external source code must not be recorded as imported")
        normalized.append(item)
    if not normalized:
        raise ValueError("at least one pinned upstream provenance source is required")
    normalized.sort(key=lambda item: (item["name"], item["commit"], item["license"], item["url"]))
    if len({item["name"] for item in normalized}) != len(normalized):
        raise ValueError("upstream provenance source names must be unique")
    return normalized


@dataclass(frozen=True)
class LedgerRecord:
    sequence: int
    kind: str
    record_id: str
    payload: dict[str, Any]
    record_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "sequence": self.sequence,
            "kind": self.kind,
            "record_id": self.record_id,
            "payload": self.payload,
            "record_hash": self.record_hash,
        }


class ExperimentLedger:
    """Append-only JSONL ledger with idempotent replay and conflict detection."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._records: list[LedgerRecord] = []
        self._by_id: dict[str, LedgerRecord] = {}
        self._reload()

    @property
    def records(self) -> tuple[LedgerRecord, ...]:
        return tuple(self._records)

    def _reload(self) -> None:
        records: list[LedgerRecord] = []
        by_id: dict[str, LedgerRecord] = {}
        if self.path.exists():
            for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    if not isinstance(raw, Mapping) or raw.get("schema_version") != SCHEMA_VERSION:
                        raise ValueError("invalid schema")
                    sequence, kind, record_id = raw["sequence"], raw["kind"], raw["record_id"]
                    payload, record_hash = raw["payload"], raw["record_hash"]
                    if not isinstance(sequence, int) or sequence != len(records):
                        raise ValueError("non-contiguous sequence")
                    if not isinstance(kind, str) or not isinstance(record_id, str) or not isinstance(payload, Mapping) or not isinstance(record_hash, str):
                        raise ValueError("invalid record fields")
                    expected_hash = stable_hash(
                        {"kind": kind, "record_id": record_id, "payload": _json_value(payload)},
                        namespace="edge-experiment-ledger-record-v1",
                    )
                    if record_hash != expected_hash:
                        raise ValueError("record hash mismatch")
                    record = LedgerRecord(sequence, kind, record_id, _json_value(payload), record_hash)
                    existing = by_id.get(record_id)
                    if existing is not None and existing != record:
                        raise ValueError("conflicting record id")
                    records.append(record)
                    by_id[record_id] = record
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(f"invalid ledger record at line {line_number}: {exc}") from exc
        self._records, self._by_id = records, by_id

    def _append(self, *, kind: str, record_id: str, payload: Mapping[str, Any]) -> LedgerRecord:
        # Re-read first: a later process's append is visible before idempotency
        # or conflict decisions are made.  This operation never truncates files.
        self._reload()
        canonical_payload = _json_value(payload)
        record_hash = stable_hash(
            {"kind": kind, "record_id": record_id, "payload": canonical_payload},
            namespace="edge-experiment-ledger-record-v1",
        )
        existing = self._by_id.get(record_id)
        if existing is not None:
            if existing.kind != kind or existing.payload != canonical_payload or existing.record_hash != record_hash:
                raise ValueError(f"append-only conflict for record id {record_id}")
            return existing
        record = LedgerRecord(len(self._records), kind, record_id, canonical_payload, record_hash)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(record.to_dict()) + "\n")
            handle.flush()
        self._records.append(record)
        self._by_id[record_id] = record
        return record

    def preregister_experiment(
        self,
        *,
        features: Sequence[str],
        model: str,
        config: Mapping[str, Any],
        upstream_provenance: Sequence[Mapping[str, Any] | Any],
        dataset_fingerprint: str,
        boundaries: Mapping[str, Any],
        code_version: str,
    ) -> LedgerRecord:
        """Record an experiment before attempting a model or evaluating data."""
        feature_list = [_require_text(feature, "feature") for feature in features]
        if not feature_list or len(set(feature_list)) != len(feature_list):
            raise ValueError("features must be a non-empty unique sequence")
        material = {
            "features": feature_list,
            "model": _require_text(model, "model"),
            "config": _json_value(config),
            "upstream_provenance": _upstream_sources(upstream_provenance),
            "boundaries": _boundaries(boundaries),
        }
        data_fingerprint = _require_text(dataset_fingerprint, "dataset_fingerprint")
        version = _require_text(code_version, "code_version")
        identifier = experiment_hash(material, data_fingerprint=data_fingerprint, code_version=version)
        return self._append(
            kind="experiment_preregistered",
            record_id=identifier,
            payload={**material, "dataset_fingerprint": data_fingerprint, "code_version": version, "status": "PREREGISTERED"},
        )

    def preregister_trial(
        self,
        experiment_id: str,
        *,
        features: Sequence[str],
        model: str,
        config: Mapping[str, Any],
    ) -> LedgerRecord:
        """Record every attempted feature/model/configuration before its result."""
        experiment = self._require_kind(experiment_id, "experiment_preregistered")
        payload = {
            "experiment_id": experiment.record_id,
            "features": [_require_text(feature, "feature") for feature in features],
            "model": _require_text(model, "model"),
            "config": _json_value(config),
            "status": "PREREGISTERED",
        }
        if not payload["features"] or len(set(payload["features"])) != len(payload["features"]):
            raise ValueError("features must be a non-empty unique sequence")
        identifier = trial_hash(experiment.record_id, {key: payload[key] for key in ("features", "model", "config")})
        return self._append(kind="trial_preregistered", record_id=identifier, payload=payload)

    def record_trial_result(
        self,
        trial_id: str,
        *,
        status: str,
        metrics: Mapping[str, Any] | None = None,
        errors: Sequence[str] = (),
        return_series: Sequence[float] | None = None,
    ) -> LedgerRecord:
        """Append one immutable result/error record for a preregistered trial.

        ``return_series`` is an optional per-trial return series (e.g. daily
        net returns) persisted alongside the scalar ``metrics``, for
        statistics that need the full series rather than a summary (e.g. an
        effective-trial-count correction). It defaults to ``None``, in which
        case the payload omits the key entirely -- identical to a record
        written before this field existed -- so existing records, and any
        code that keeps calling this method without it, are unaffected.
        """
        self._require_kind(trial_id, "trial_preregistered")
        if status not in _TRIAL_RESULT_STATUSES:
            raise ValueError(f"trial result status must be one of {sorted(_TRIAL_RESULT_STATUSES)}")
        error_list = [_require_text(error, "error") for error in errors]
        if status == "COMPLETED" and error_list:
            raise ValueError("completed trial cannot include errors")
        if status == "FAILED" and not error_list:
            raise ValueError("failed trial must include errors")
        payload = {"trial_id": trial_id, "status": status, "metrics": _json_value(metrics or {}), "errors": error_list}
        if return_series is not None:
            payload["return_series"] = _return_series(return_series)
        identifier = stable_hash({"trial_id": trial_id, "record_type": "result"}, namespace="edge-trial-result-v1")
        return self._append(kind="trial_result", record_id=identifier, payload=payload)

    def preregister_terminal_holdout(
        self,
        experiment_id: str,
        *,
        dataset_fingerprint: str,
        source_panel: str | None = None,
    ) -> LedgerRecord:
        """Seal the experiment's fresh terminal holdout before its sole evaluation.

        Conflict detection has two independent keys; either one alone raises:

        1. ``dataset_fingerprint`` identity (original behaviour, unchanged):
           the same fingerprint registered to a different experiment raises.
        2. ``source_panel`` + terminal-holdout calendar-range overlap (new).
           Two pipelines can read the *same* underlying data through
           different code paths -- e.g. a raw parquet directory and a qlib
           provider staged from it -- and compute different fingerprints for
           identical calendar dates, which (1) alone cannot see. Pass the
           root/origin data path, not a derived copy, as ``source_panel`` so
           two such pipelines still collide correctly; an overlapping
           ``terminal_holdout`` range registered by a different experiment
           against the same ``source_panel`` raises.

        ``source_panel`` defaults to ``None``, which skips check (2) entirely
        and reproduces the exact original payload shape and identifier hash
        -- this keeps existing callers (and already-persisted ledger files
        written before this field existed, e.g.
        ``edge/runs/research/directional_daily_v1/experiments.jsonl``) fully
        idempotent and unaffected. New callers should always pass it; check
        (2) only protects registrations that opt in.
        """
        experiment = self._require_kind(experiment_id, "experiment_preregistered")
        fingerprint = _require_text(dataset_fingerprint, "dataset_fingerprint")
        panel = _require_text(source_panel, "source_panel") if source_panel is not None else None
        boundary = experiment.payload["boundaries"]["terminal_holdout"]
        for record in self._records:
            if record.kind != "terminal_holdout_preregistered":
                continue
            if record.payload["dataset_fingerprint"] == fingerprint and record.payload["experiment_id"] != experiment_id:
                raise ValueError("terminal holdout fingerprint is already registered to another experiment")
            if panel is None or record.payload.get("source_panel") != panel:
                continue
            if record.payload["experiment_id"] == experiment_id:
                continue
            other = record.payload["boundaries"]
            if boundary["start"] <= other["end"] and other["start"] <= boundary["end"]:
                raise ValueError(
                    f"terminal holdout calendar range {boundary['start']}..{boundary['end']} on source "
                    f"panel {panel!r} overlaps an already-registered holdout {other['start']}..{other['end']} "
                    f"from experiment {record.payload['experiment_id']!r} on the same panel -- that "
                    "calendar range has already been spent and cannot be re-registered"
                )
        payload = {"experiment_id": experiment_id, "boundaries": boundary, "dataset_fingerprint": fingerprint, "status": "PREREGISTERED"}
        if panel is not None:
            payload["source_panel"] = panel
        identifier = stable_hash(payload, namespace="edge-terminal-holdout-v1")
        return self._append(kind="terminal_holdout_preregistered", record_id=identifier, payload=payload)

    def record_terminal_holdout_evaluation(
        self,
        holdout_id: str,
        *,
        trial_id: str,
        metrics: Mapping[str, Any],
        errors: Sequence[str] = (),
    ) -> LedgerRecord:
        """Append the single allowed terminal-holdout evaluation for a holdout."""
        holdout = self._require_kind(holdout_id, "terminal_holdout_preregistered")
        trial = self._require_kind(trial_id, "trial_preregistered")
        if trial.payload["experiment_id"] != holdout.payload["experiment_id"]:
            raise ValueError("trial must belong to the terminal holdout experiment")
        error_list = [_require_text(error, "error") for error in errors]
        payload = {"holdout_id": holdout_id, "trial_id": trial_id, "status": "EVALUATED", "metrics": _json_value(metrics), "errors": error_list}
        identifier = stable_hash({"holdout_id": holdout_id, "record_type": "evaluation"}, namespace="edge-terminal-holdout-evaluation-v1")
        return self._append(kind="terminal_holdout_evaluation", record_id=identifier, payload=payload)

    def _require_kind(self, record_id: str, kind: str) -> LedgerRecord:
        self._reload()
        record = self._by_id.get(record_id)
        if record is None or record.kind != kind:
            raise ValueError(f"expected registered {kind}: {record_id}")
        return record
