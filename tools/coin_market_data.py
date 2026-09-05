"""Coin and historical-equity marks for the digital-asset treasury forecast.

Kept out of :mod:`research.treasury_nav_forecast` deliberately: the model stays
pure and testable, and every network fetch lives here behind a cache, the same
split the earnings engine already uses for ``resolve_forecast_intel``.

Two series are needed and neither can be guessed:

* the coin price **on each reported period end**, which turns a fair-value
  carrying amount back into a unit count, and
* the equity close on those same dates, which is what makes each historical
  mNAV point a real premium rather than today's price over a stale book.

A missing series returns empty. The model then publishes an explicit
unmodelable state instead of a NAV built on an invented price.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

COIN_TTL_S = 300.0
_COIN_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

# Which coin a treasury holds is not in the statements — the carrying value is
# one undifferentiated fair-value line. Bitcoin is the default because it is
# what the overwhelming majority of these structures hold; the exceptions are
# named here so a non-BTC treasury is not silently marked against BTC. Anything
# resolved by default is stamped ``inferred`` so the surface can say so.
COIN_BY_SYMBOL: dict[str, str] = {
    "BMNR": "ETH-USD",
    "SBET": "ETH-USD",
    "ETHZ": "ETH-USD",
    "BTBT": "ETH-USD",
    "DFDV": "SOL-USD",
    "UPXI": "SOL-USD",
    "STSS": "SOL-USD",
    "HYPD": "HYPE-USD",
}
DEFAULT_COIN = "BTC-USD"

VOL_LOOKBACK_DAYS = 365
HISTORY_PERIOD = "3y"


def coin_for_symbol(symbol: str) -> tuple[str, bool]:
    """(coin ticker, inferred). ``inferred`` is True when the default was used."""
    sym = str(symbol or "").strip().upper()
    if sym in COIN_BY_SYMBOL:
        return COIN_BY_SYMBOL[sym], False
    return DEFAULT_COIN, True


def _as_of(series: Any, date: str) -> float | None:
    """Last close at or before ``date``. None when the series starts later."""
    try:
        import pandas as pd  # type: ignore[import-not-found]

        seg = series.loc[: pd.Timestamp(date)]
        if len(seg) == 0:
            return None
        val = float(seg.iloc[-1])
        return val if math.isfinite(val) and val > 0 else None
    except Exception:  # noqa: BLE001 - a missing date is a None, not a failure
        return None


def _closes(ticker_symbol: str, period: str = HISTORY_PERIOD) -> Any | None:
    try:
        import yfinance as yf  # type: ignore[import-not-found]

        frame = yf.Ticker(ticker_symbol).history(period=period, interval="1d")
        if frame is None or frame.empty or "Close" not in frame.columns:
            return None
        closes = frame["Close"].dropna()
        if closes.empty:
            return None
        try:
            closes.index = closes.index.tz_localize(None)
        except (TypeError, AttributeError):
            pass
        return closes
    except Exception as exc:  # noqa: BLE001 - yfinance is a soft dependency
        logger.debug("close history fetch failed for %s: %s", ticker_symbol, exc)
        return None


def _annual_vol(closes: Any) -> float | None:
    """Realised annualised vol from daily log-ish returns over the last year."""
    try:
        window = closes.tail(VOL_LOOKBACK_DAYS)
        rets = window.pct_change().dropna()
        if len(rets) < 30:
            return None
        # Coins trade 365 days a year; equities do not. Callers pass coin series.
        vol = float(rets.std() * math.sqrt(365))
        return vol if math.isfinite(vol) and vol > 0 else None
    except Exception:  # noqa: BLE001
        return None


def resolve_treasury_intel(
    symbol: str,
    period_end_dates: Sequence[str],
    *,
    live_spot: float | None = None,
) -> dict[str, Any]:
    """Coin marks plus the equity closes on the same reported period ends.

    ``period_end_dates`` is newest-first, matching the statement row ordering,
    and the returned price lists are aligned to it index-for-index so the model
    never has to re-align two series by date.
    """
    sym = str(symbol or "").strip().upper()
    dates = [str(d)[:10] for d in period_end_dates if d]
    if not sym or not dates:
        return {}

    cache_key = f"{sym}|{'|'.join(dates)}"
    now = time.time()
    cached = _COIN_CACHE.get(cache_key)
    if cached and now - cached[0] < COIN_TTL_S:
        return dict(cached[1])

    coin_symbol, inferred = coin_for_symbol(sym)
    out: dict[str, Any] = {}

    coin_closes = _closes(coin_symbol)
    if coin_closes is not None:
        spot = float(coin_closes.iloc[-1])
        coin_block: dict[str, Any] = {
            "symbol": coin_symbol,
            "inferred": inferred,
            "spot": round(spot, 4),
            "asof": str(coin_closes.index[-1])[:10],
            "period_prices": [_as_of(coin_closes, d) for d in dates],
        }
        vol = _annual_vol(coin_closes)
        if vol is not None:
            coin_block["annual_vol"] = round(vol, 6)
        out["coin"] = coin_block

    equity_closes = _closes(sym)
    if equity_closes is not None:
        out["period_prices"] = [_as_of(equity_closes, d) for d in dates]
        # Only a fallback. The live mark from the real-time feed always wins;
        # a daily close is a session-stale print, and the model says so.
        if live_spot is None:
            out["history_last_close"] = round(float(equity_closes.iloc[-1]), 4)

    _COIN_CACHE[cache_key] = (now, out)
    return dict(out)


def period_end_dates(payload: Mapping[str, Any] | None) -> list[str]:
    """ISO period ends from a financials payload, newest-first."""
    if not isinstance(payload, Mapping):
        return []
    periods = payload.get("periods")
    if not isinstance(periods, (list, tuple)):
        return []
    out: list[str] = []
    for p in periods:
        text = str(p)[:10]
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            out.append(text)
    return out
