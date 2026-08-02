"""Canonical, deterministic identities for experiments and attempted trials."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np


def _canonical(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=lambda item: str(item))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, set):
        return [_canonical(item) for item in sorted(value, key=repr)]
    if isinstance(value, np.generic):
        return _canonical(value.item())
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, float):
        if not np.isfinite(value):
            raise ValueError("experiment identity cannot contain NaN or infinity")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported value in deterministic hash: {type(value).__name__}")


def stable_hash(value: Any, *, namespace: str = "edge-research-v1") -> str:
    """SHA-256 of canonical JSON, independent of mapping insertion order."""
    payload = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(f"{namespace}:{payload}".encode("utf-8")).hexdigest()


def experiment_hash(config: Mapping[str, Any], *, data_fingerprint: str, code_version: str) -> str:
    """Identity of a preregistered research experiment, not its results."""
    return stable_hash({"config": config, "data_fingerprint": data_fingerprint, "code_version": code_version}, namespace="edge-experiment-v1")


def trial_hash(experiment_id: str, trial_config: Mapping[str, Any]) -> str:
    """Identity of one attempted configuration inside an experiment."""
    if not experiment_id:
        raise ValueError("experiment_id is required")
    return stable_hash({"experiment_id": experiment_id, "trial_config": trial_config}, namespace="edge-trial-v1")


@dataclass(frozen=True)
class RegistryEntry:
    sequence: int
    kind: str
    identifier: str
    payload: dict[str, Any]


class ExperimentRegistry:
    """An in-memory append-only-style ledger for planned attempts.

    It intentionally does no file I/O or training.  Re-recording the identical
    identity is idempotent; a conflicting payload with the same identity raises.
    Persist callers may serialize ``entries`` as JSON Lines in their own layer.
    """

    def __init__(self) -> None:
        self._entries: list[RegistryEntry] = []
        self._by_id: dict[str, RegistryEntry] = {}

    @property
    def entries(self) -> tuple[RegistryEntry, ...]:
        return tuple(self._entries)

    def _append(self, kind: str, identifier: str, payload: Mapping[str, Any]) -> RegistryEntry:
        canonical_payload = _canonical(dict(payload))
        existing = self._by_id.get(identifier)
        if existing is not None:
            if existing.kind != kind or existing.payload != canonical_payload:
                raise ValueError(f"append-only registry conflict for {identifier}")
            return existing
        entry = RegistryEntry(len(self._entries), kind, identifier, canonical_payload)
        self._entries.append(entry)
        self._by_id[identifier] = entry
        return entry

    def record_experiment(
        self,
        config: Mapping[str, Any],
        *,
        data_fingerprint: str,
        code_version: str,
    ) -> RegistryEntry:
        identifier = experiment_hash(config, data_fingerprint=data_fingerprint, code_version=code_version)
        return self._append(
            "experiment",
            identifier,
            {"config": config, "data_fingerprint": data_fingerprint, "code_version": code_version},
        )

    def record_trial(self, experiment_id: str, trial_config: Mapping[str, Any]) -> RegistryEntry:
        if experiment_id not in self._by_id or self._by_id[experiment_id].kind != "experiment":
            raise ValueError("trial must reference a registered experiment")
        identifier = trial_hash(experiment_id, trial_config)
        return self._append("trial", identifier, {"experiment_id": experiment_id, "trial_config": trial_config})
