"""Canonical, dependency-free data contracts for the daily plays pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Any, Mapping, Sequence


RUN_SCHEMA_VERSION = "daily-plays-run-v1"
PLAY_SCHEMA_VERSION = "daily-play-v1"


class _StringEnum(str, Enum):
    pass


class MarketSession(_StringEnum):
    PREMARKET = "premarket"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"
    CLOSED = "closed"
    REPLAY = "replay"


class RunMode(_StringEnum):
    LIVE = "live"
    DEGRADED = "degraded"
    REPLAY = "replay"


class PlayState(_StringEnum):
    ENTER = "ENTER"
    WATCH = "WATCH"
    ABSTAIN = "ABSTAIN"


class ConfidenceKind(_StringEnum):
    CALIBRATED_PROBABILITY = "calibrated_probability"
    ORDINAL_SCORE = "ordinal_score"
    UNAVAILABLE = "unavailable"


class EvidenceGrade(_StringEnum):
    A = "A"
    B = "B"
    C = "C"
    F = "F"


class LegSide(_StringEnum):
    BUY = "buy"
    SELL = "sell"


class OptionRight(_StringEnum):
    CALL = "call"
    PUT = "put"


def utc_datetime(value: datetime) -> datetime:
    """Require a timezone-aware datetime and normalize it to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime values must be timezone-aware")
    return value.astimezone(timezone.utc)


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return utc_datetime(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("canonical JSON cannot contain NaN or infinity")
    return value


def canonical_json(value: Any) -> str:
    """Stable JSON for hashing, fixtures, and operator-machine output."""
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    requested_for: date
    asof_utc: datetime
    market_session: MarketSession
    account: float
    mode: RunMode
    config_hash: str
    providers: Mapping[str, Any] = field(default_factory=dict)
    model_versions: Mapping[str, Any] = field(default_factory=dict)
    code_provenance: Mapping[str, Any] = field(default_factory=dict)
    warnings: Sequence[str] = field(default_factory=tuple)
    schema_version: str = RUN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RUN_SCHEMA_VERSION:
            raise ValueError(f"unsupported run schema: {self.schema_version}")
        if not self.run_id or not self.config_hash:
            raise ValueError("run_id and config_hash are required")
        if not math.isfinite(self.account) or self.account <= 0:
            raise ValueError("account must be a positive finite number")
        object.__setattr__(self, "asof_utc", utc_datetime(self.asof_utc))

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


@dataclass(frozen=True)
class OptionLeg:
    side: LegSide
    right: OptionRight
    occ_symbol: str
    underlying: str
    expiry: date
    dte: int
    strike: float
    multiplier: int
    bid: float
    ask: float
    mid: float
    spread_pct: float
    volume: int
    open_interest: int
    quote_asof_utc: datetime
    provider: str
    provider_contract_id: str | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None

    def __post_init__(self) -> None:
        missing = [name for name in ("occ_symbol", "underlying", "provider") if not getattr(self, name)]
        if missing:
            raise ValueError(f"option leg missing identity: {', '.join(missing)}")
        if self.dte < 0 or self.multiplier <= 0 or self.strike <= 0:
            raise ValueError("option leg has invalid expiry, multiplier, or strike")
        for name in ("bid", "ask", "mid", "spread_pct"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"option leg {name} must be finite and non-negative")
        if self.volume < 0 or self.open_interest < 0:
            raise ValueError("volume and open_interest must be non-negative")
        object.__setattr__(self, "underlying", self.underlying.upper())
        object.__setattr__(self, "quote_asof_utc", utc_datetime(self.quote_asof_utc))

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


@dataclass(frozen=True)
class Entry:
    limit_reference: float
    underlying_reference: float
    quote_asof_utc: datetime
    max_quote_age_seconds: int

    def __post_init__(self) -> None:
        if self.max_quote_age_seconds < 0:
            raise ValueError("max_quote_age_seconds must be non-negative")
        object.__setattr__(self, "quote_asof_utc", utc_datetime(self.quote_asof_utc))


@dataclass(frozen=True)
class Risk:
    account: float
    max_loss_dollars: float
    max_loss_pct: float
    contracts: int
    reward_risk_reference: float | None = None

    def __post_init__(self) -> None:
        if self.account <= 0 or self.max_loss_dollars < 0 or self.max_loss_pct < 0 or self.contracts < 0:
            raise ValueError("invalid risk values")


@dataclass(frozen=True)
class Confidence:
    state: PlayState
    confidence_kind: ConfidenceKind
    evidence_grade: EvidenceGrade
    model_probability: float | None = None
    calibrated_probability: float | None = None
    calibration_version: str | None = None
    reasons: Sequence[str] = field(default_factory=tuple)
    failed_checks: Sequence[str] = field(default_factory=tuple)
    # A calibrated number is meaningful only together with the event it
    # estimates.  These values deliberately describe the *underlying* return,
    # never an option's eventual profit and loss.
    probability_target: str | None = None
    horizon_days: int | None = None
    entry_threshold: float | None = None
    threshold_version: str | None = None
    model_artifact_sha256: str | None = None
    promotion_authorized: bool = False

    def __post_init__(self) -> None:
        for name in ("model_probability", "calibrated_probability"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"{name} must be in [0, 1]")
        if self.confidence_kind is ConfidenceKind.ORDINAL_SCORE and self.calibrated_probability is not None:
            raise ValueError("ordinal confidence cannot include calibrated_probability")
        if self.confidence_kind is ConfidenceKind.UNAVAILABLE and self.calibrated_probability is not None:
            raise ValueError("unavailable confidence cannot include calibrated_probability")
        if self.probability_target is not None and not self.probability_target.startswith("underlying_"):
            raise ValueError("probability_target must describe an underlying event")
        if self.horizon_days is not None and self.horizon_days <= 0:
            raise ValueError("horizon_days must be positive when provided")
        if self.entry_threshold is not None and (
            not math.isfinite(self.entry_threshold) or not 0.5 <= self.entry_threshold <= 1
        ):
            raise ValueError("entry_threshold must be in [0.5, 1]")
        if self.state is PlayState.ENTER and self.confidence_kind is not ConfidenceKind.CALIBRATED_PROBABILITY:
            raise ValueError("ENTER requires a calibrated probability")
        if self.state is PlayState.ENTER and (not self.probability_target or self.horizon_days is None):
            raise ValueError("ENTER requires calibrated probability target semantics")
        if self.state is PlayState.ENTER and (
            self.entry_threshold is None
            or self.calibrated_probability is None
            or self.calibrated_probability < self.entry_threshold
            or not self.threshold_version
        ):
            raise ValueError("ENTER requires a passed frozen probability operating point")
        if self.state is PlayState.ENTER and (
            not self.promotion_authorized
            or not self.model_artifact_sha256
            or len(self.model_artifact_sha256) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in self.model_artifact_sha256)
        ):
            raise ValueError("ENTER requires a promotion-authorized model artifact")


@dataclass(frozen=True)
class Play:
    play_id: str
    symbol: str
    side: str
    strategy: str
    state: PlayState
    rank: int
    thesis: Sequence[str]
    invalidation: Sequence[str]
    entry: Entry
    legs: Sequence[OptionLeg]
    risk: Risk
    confidence: Confidence
    evidence: Mapping[str, Any] = field(default_factory=dict)
    freshness: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PLAY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PLAY_SCHEMA_VERSION:
            raise ValueError(f"unsupported play schema: {self.schema_version}")
        if not self.play_id or not self.symbol or not self.strategy or self.rank < 1:
            raise ValueError("play_id, symbol, strategy, and positive rank are required")
        if self.state is not self.confidence.state:
            raise ValueError("play state must match confidence state")
        object.__setattr__(self, "symbol", self.symbol.upper())

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)
