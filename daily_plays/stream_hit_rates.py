"""Rolling stream hit-rates from shadow outcomes for closed-loop weight adapt.

For each realized directional shadow event we:

1. Cut bars at the decision as-of (no lookahead).
2. Re-score price-native streams (technical, fundamental).
3. Score sector/sentiment only when the event recorded context, otherwise skip.
4. Count a hit when the stream's signed direction agrees with the trade
   direction *and* the trade won, or disagrees and the trade lost.

The result is a map ``{stream: hit_rate in [0,1]}`` suitable for
``adapt_weights(..., stream_performance=...)``.  Missing history degrades to
an empty map (regime weights only) — never invented performance.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from .adaptive_signal import (
    STREAM_NAMES,
    _NEUTRAL_BAND,
    _finite,
    _normalize_frame,
    score_fundamental,
    score_sector,
    score_sentiment,
    score_technical,
)


@dataclass(frozen=True)
class ShadowRealizedEvent:
    symbol: str
    side: str  # long | short
    asof: pd.Timestamp
    win: bool
    net_return: float | None
    source: str
    sector_context: Mapping[str, Any] | None = None
    market_sentiment: Mapping[str, Any] | None = None
    fundamental_context: Mapping[str, Any] | None = None


def _parse_ts(value: Any) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    # Drop timezone for bar-index alignment (local parquets are typically naive).
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def _side_from_raw(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if raw in {"buy", "long", "bullish", "call"}:
        return "long"
    if raw in {"sell", "short", "bearish", "put"}:
        return "short"
    return None


def _rows_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def load_v90_shadow_events(path: Path | str) -> list[ShadowRealizedEvent]:
    """Parse ``runs/shadow_decisions.jsonl`` (v90 shadow journal) realized rows."""
    events: list[ShadowRealizedEvent] = []
    for row in _rows_jsonl(Path(path)):
        realized = row.get("realized")
        if not isinstance(realized, Mapping):
            continue
        side = _side_from_raw(row.get("side"))
        if side is None:
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        asof = _parse_ts(row.get("asof_bar") or row.get("recorded_at_utc"))
        if asof is None:
            continue
        win = realized.get("win")
        net = _finite(realized.get("net_return") if realized.get("net_return") is not None else realized.get("gross_return"))
        if not isinstance(win, bool):
            if net is None:
                continue
            win = bool(net > 0)
        events.append(
            ShadowRealizedEvent(
                symbol=symbol,
                side=side,
                asof=asof,
                win=win,
                net_return=net,
                source="v90_shadow_decisions",
            )
        )
    return events


def load_daily_plays_shadow_events(
    *,
    decisions_path: Path | str,
    outcomes_path: Path | str | None = None,
) -> list[ShadowRealizedEvent]:
    """Parse daily-plays ledger + outcomes into realized directional events."""
    decisions_path = Path(decisions_path)
    outcomes_path = Path(outcomes_path) if outcomes_path else decisions_path.parent / "shadow_outcomes.jsonl"
    outcomes = {
        str(row.get("play_id")): row
        for row in _rows_jsonl(outcomes_path)
        if isinstance(row.get("play_id"), str)
    }
    events: list[ShadowRealizedEvent] = []
    for decision in _rows_jsonl(decisions_path):
        decision_asof = _parse_ts(decision.get("asof_utc") or decision.get("requested_for"))
        for play in decision.get("plays") or []:
            if not isinstance(play, Mapping):
                continue
            play_id = play.get("play_id")
            if not isinstance(play_id, str):
                continue
            outcome = outcomes.get(play_id)
            if not isinstance(outcome, Mapping):
                continue
            side = _side_from_raw(play.get("side") or (play.get("entry") or {}).get("side"))
            if side is None:
                continue
            symbol = str(play.get("symbol") or play.get("underlying") or "").strip().upper()
            if not symbol:
                continue
            asof = _parse_ts(outcome.get("decision_asof_utc")) or decision_asof
            if asof is None:
                continue
            win = outcome.get("outcome")
            net = _finite(outcome.get("gross_return_pct"))
            if net is not None:
                net = net / 100.0
            if not isinstance(win, bool):
                if net is None:
                    continue
                win = bool(net > 0)
            evidence = play.get("evidence") if isinstance(play.get("evidence"), Mapping) else {}
            provenance = play.get("provenance") if isinstance(play.get("provenance"), Mapping) else {}
            sector = evidence.get("sector") or provenance.get("sector")
            sentiment = evidence.get("sentiment") or provenance.get("market_sentiment")
            events.append(
                ShadowRealizedEvent(
                    symbol=symbol,
                    side=side,
                    asof=asof,
                    win=win,
                    net_return=net,
                    source="daily_plays_shadow",
                    sector_context=sector if isinstance(sector, Mapping) else None,
                    market_sentiment=sentiment if isinstance(sentiment, Mapping) else None,
                    fundamental_context=None,
                )
            )
    return events


def collect_shadow_events(roots: Sequence[Path | str] | None = None) -> list[ShadowRealizedEvent]:
    """Load realized events from the standard edge/runs locations."""
    edge_runs = Path(__file__).resolve().parents[1] / "runs"
    search = [Path(p) for p in roots] if roots else [
        edge_runs / "shadow_decisions.jsonl",
        edge_runs / "daily_plays" / "shadow_decisions.jsonl",
    ]
    events: list[ShadowRealizedEvent] = []
    for path in search:
        if path.name == "shadow_decisions.jsonl" and path.parent.name == "daily_plays":
            events.extend(
                load_daily_plays_shadow_events(
                    decisions_path=path,
                    outcomes_path=path.parent / "shadow_outcomes.jsonl",
                )
            )
        elif path.is_file():
            events.extend(load_v90_shadow_events(path))
    # Newest last for rolling window; stable sort by asof.
    events.sort(key=lambda e: (e.asof, e.symbol))
    return events


def _bars_asof(frame: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    if frame is None or len(frame) == 0:
        return pd.DataFrame()
    work = _normalize_frame(frame)
    if work.empty:
        return work
    idx = pd.to_datetime(work.index, errors="coerce")
    work = work.copy()
    work.index = idx
    work = work[~work.index.isna()].sort_index()
    # Inclusive of the decision bar; no future bars.
    return work.loc[work.index <= asof]


def _stream_direction(score: float | None) -> int:
    if score is None:
        return 0
    if score > _NEUTRAL_BAND:
        return 1
    if score < -_NEUTRAL_BAND:
        return -1
    return 0


def stream_hit_for_event(
    event: ShadowRealizedEvent,
    *,
    bars: Any,
) -> dict[str, bool | None]:
    """Return per-stream hit (True/False) or None when stream was neutral/missing."""
    frame = _bars_asof(bars if isinstance(bars, pd.DataFrame) else _normalize_frame(bars), event.asof)
    trade_dir = 1 if event.side == "long" else -1
    technical = score_technical(frame)
    fundamental = score_fundamental(frame, fundamental_context=event.fundamental_context)
    sector = score_sector(
        technical_score=_finite(technical.get("score")),
        sector_context=event.sector_context,
    )
    sentiment = score_sentiment(event.market_sentiment)

    scores = {
        "technical": _finite(technical.get("score")),
        "fundamental": _finite(fundamental.get("score")),
        "sector": _finite(sector.get("score")),
        "sentiment": _finite(sentiment.get("score")),
    }
    hits: dict[str, bool | None] = {}
    for name, score in scores.items():
        direction = _stream_direction(score)
        if direction == 0:
            hits[name] = None
            continue
        agreed = direction == trade_dir
        # Stream that agreed with a winner, or disagreed with a loser, was right.
        hits[name] = bool(agreed == event.win)
    return hits


def rolling_stream_hit_rates(
    events: Sequence[ShadowRealizedEvent],
    *,
    candle_loader: Callable[[str], Any],
    lookback_events: int = 60,
    min_events: int = 8,
) -> dict[str, Any]:
    """Compute rolling hit-rates over the most recent realized shadow events."""
    if lookback_events < 1 or min_events < 1:
        raise ValueError("lookback_events and min_events must be positive")
    recent = list(events)[-lookback_events:]
    tallies: dict[str, list[bool]] = {name: [] for name in STREAM_NAMES}
    used = 0
    skipped = 0
    for event in recent:
        try:
            bars = candle_loader(event.symbol)
            hits = stream_hit_for_event(event, bars=bars)
        except Exception:
            skipped += 1
            continue
        used += 1
        for name in STREAM_NAMES:
            value = hits.get(name)
            if isinstance(value, bool):
                tallies[name].append(value)

    rates: dict[str, float] = {}
    counts: dict[str, int] = {}
    for name, series in tallies.items():
        counts[name] = len(series)
        if len(series) >= min_events:
            rates[name] = round(sum(series) / len(series), 4)

    return {
        "schema_version": "stream-hit-rates-v1",
        "score_kind": "rolling_shadow_hit_rate",
        "decision_authorized": False,
        "lookback_events": lookback_events,
        "min_events": min_events,
        "events_considered": len(recent),
        "events_scored": used,
        "events_skipped": skipped,
        "stream_counts": counts,
        "stream_performance": rates,
        "asof": recent[-1].asof.isoformat() if recent else None,
        "sources": sorted({e.source for e in recent}),
        "caveat": (
            "Hit-rates are reconstructed point-in-time from shadow outcomes; "
            "sector/sentiment only count when the event stored that context. "
            "Used only for soft weight tilt, never for capital authorization."
        ),
    }


def load_stream_performance_from_shadow(
    *,
    candle_loader: Callable[[str], Any],
    roots: Sequence[Path | str] | None = None,
    lookback_events: int = 60,
    min_events: int = 8,
) -> dict[str, Any]:
    """Convenience: collect shadow events and return the hit-rate payload."""
    events = collect_shadow_events(roots)
    return rolling_stream_hit_rates(
        events,
        candle_loader=candle_loader,
        lookback_events=lookback_events,
        min_events=min_events,
    )
