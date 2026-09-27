"""Validated, hashable configuration for daily plays policy defaults."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import stable_hash


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "daily_plays.json"
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


def load_project_environment(paths: Sequence[str | Path] | None = None) -> None:
    """Load known project env files without replacing explicit shell values."""
    if os.environ.get("DAILY_PLAYS_DISABLE_DOTENV", "").strip().lower() in {"1", "true", "yes"}:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_paths = paths or (
        WORKSPACE_ROOT / "TradingAlgoWork" / ".env",
        WORKSPACE_ROOT / "TradingWork" / ".env",
    )
    for env_path in env_paths:
        try:
            path = Path(env_path)
            if path.is_file():
                load_dotenv(dotenv_path=path, override=False)
        except PermissionError:
            pass


@dataclass(frozen=True)
class DailyPlaysConfig:
    schema_version: str
    shortlist_limit: int
    regular_quote_max_age_seconds: int
    swing_dte_min: int
    swing_dte_max: int
    intraday_enabled: bool
    shadow_only: bool
    min_abs_delta: float
    max_abs_delta: float
    max_spread_pct: float
    low_premium_spread_floor: float
    min_open_interest: int
    min_volume: int
    max_account_risk_pct: float
    max_position_risk_pct: float
    max_underlying_risk_pct: float
    max_aggregate_open_risk_pct: float
    universe_path: str

    def __post_init__(self) -> None:
        if self.schema_version != "daily-plays-config-v1":
            raise ValueError("unsupported daily plays config schema")
        if self.shortlist_limit < 1 or self.regular_quote_max_age_seconds < 0:
            raise ValueError("shortlist and quote-age policy must be non-negative")
        if not self.shadow_only:
            raise ValueError("daily plays must remain shadow-only")
        if self.swing_dte_min != 30 or self.swing_dte_max != 60:
            raise ValueError("shadow option DTE window must be 30-60 days")
        if not 0 < self.min_abs_delta <= self.max_abs_delta <= 1:
            raise ValueError("invalid absolute delta policy")
        if self.swing_dte_min < 0 or self.swing_dte_max < self.swing_dte_min:
            raise ValueError("invalid swing DTE window")
        if not 0 < self.max_spread_pct <= 0.10 or self.low_premium_spread_floor < 0:
            raise ValueError("invalid spread policy")
        if self.min_open_interest < 500 or self.min_volume < 50:
            raise ValueError("shadow liquidity policy must require OI >= 500 and volume >= 50")
        if (self.max_account_risk_pct != 0.005 or self.max_position_risk_pct != 0.005
                or self.max_underlying_risk_pct != 0.01 or self.max_aggregate_open_risk_pct != 0.03):
            raise ValueError("shadow risk policy must use preregistered limits")
        if not 0 < self.max_account_risk_pct <= 1:
            raise ValueError("invalid liquidity or risk policy")
        if not self.universe_path:
            raise ValueError("universe_path is required")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DailyPlaysConfig":
        required = {
            "schema_version", "shortlist_limit", "regular_quote_max_age_seconds", "swing_dte_min",
            "swing_dte_max", "intraday_enabled", "shadow_only", "min_abs_delta", "max_abs_delta",
            "max_spread_pct", "low_premium_spread_floor", "min_open_interest", "min_volume",
            "max_account_risk_pct", "max_position_risk_pct", "max_underlying_risk_pct",
            "max_aggregate_open_risk_pct", "universe_path",
        }
        missing = sorted(required - raw.keys())
        unknown = sorted(raw.keys() - required)
        if missing or unknown:
            raise ValueError(f"invalid config keys; missing={missing}, unknown={unknown}")
        return cls(**dict(raw))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "shortlist_limit": self.shortlist_limit,
            "regular_quote_max_age_seconds": self.regular_quote_max_age_seconds,
            "swing_dte_min": self.swing_dte_min, "swing_dte_max": self.swing_dte_max,
            "intraday_enabled": self.intraday_enabled, "shadow_only": self.shadow_only,
            "min_abs_delta": self.min_abs_delta, "max_abs_delta": self.max_abs_delta,
            "max_spread_pct": self.max_spread_pct,
            "low_premium_spread_floor": self.low_premium_spread_floor,
            "min_open_interest": self.min_open_interest, "min_volume": self.min_volume,
            "max_account_risk_pct": self.max_account_risk_pct,
            "max_position_risk_pct": self.max_position_risk_pct,
            "max_underlying_risk_pct": self.max_underlying_risk_pct,
            "max_aggregate_open_risk_pct": self.max_aggregate_open_risk_pct,
            "universe_path": self.universe_path,
        }

    @property
    def config_hash(self) -> str:
        return stable_hash(self.to_dict())


def load_config(path: str | Path | None = None) -> DailyPlaysConfig:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"daily plays config not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in daily plays config: {config_path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("daily plays config must be a JSON object")
    return DailyPlaysConfig.from_dict(raw)
