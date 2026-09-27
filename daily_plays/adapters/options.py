"""Options-market adapters for daily plays.

The adapter boundary deliberately returns ordinary mappings: the core contracts
may evolve independently, while raw provider shapes must not leak past here.
``LSEOptionsAdapter`` is the only adapter that can return a live snapshot.
``YFinanceOptionsAdapter`` is explicitly development/replay-only and always
marks its output degraded.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import date, datetime, timezone
import io
import os
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence


class OptionsProvider(Protocol):
    """Small injectable boundary used by the pipeline and fixture tests."""

    def snapshot(self, symbol: str, *, asof_utc: datetime | None = None) -> Mapping[str, Any]: ...

    def snapshots(
        self, symbols: Sequence[str], *, asof_utc: datetime | None = None
    ) -> Mapping[str, Mapping[str, Any]]: ...


def _utc(value: Any, default: datetime | None = None) -> str | None:
    if value is None:
        return default.astimezone(timezone.utc).isoformat() if default else None
    if isinstance(value, datetime):
        value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def _integer(value: Any) -> int | None:
    number = _float(value)
    return int(number) if number is not None and number >= 0 else None


def _pick(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def _right(value: Any) -> str | None:
    value = str(value or "").strip().lower()
    return {"c": "call", "call": "call", "p": "put", "put": "put"}.get(value)


def _expiry(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError):
        return None


def normalize_contract(
    row: Mapping[str, Any], *, underlying: str, provider: str, asof_utc: datetime | None = None
) -> dict[str, Any]:
    """Normalize an LSE/gamma/yfinance row without inventing identity fields."""
    bid, ask = _float(_pick(row, "bid", "best_bid")), _float(_pick(row, "ask", "best_ask"))
    mid = (bid + ask) / 2 if bid is not None and ask is not None else None
    spread_pct = ((ask - bid) / mid) if mid and bid is not None and ask is not None else None
    expiry = _expiry(_pick(row, "expiry", "expiration", "expiration_date"))
    strike = _float(_pick(row, "strike", "strike_price"))
    contract_underlying = (
        str(_pick(row, "underlying", "symbol") or underlying).upper().replace(".US", "")
    )
    dte: int | None = None
    if expiry and asof_utc:
        dte = (date.fromisoformat(expiry) - asof_utc.astimezone(timezone.utc).date()).days
    quote_asof = _utc(_pick(row, "quote_asof_utc", "quote_timestamp", "nbbo_updated_at"))
    quote_live = bool(
        bid is not None and ask is not None and quote_asof is not None and provider == "lse"
    )
    return {
        "underlying": contract_underlying,
        "right": _right(_pick(row, "right", "option_type", "contract_type", "type")),
        "expiry": expiry,
        # This is derived from the immutable run clock; provider DTE values
        # vary by timezone and are intentionally not trusted as authoritative.
        "dte": dte,
        "strike": strike,
        "occ_symbol": _pick(row, "occ_symbol", "contract_symbol", "contractSymbol", "ticker"),
        "provider_contract_id": _pick(row, "provider_contract_id", "id", "contract_id"),
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "last_price": _float(_pick(row, "last_price", "lastPrice", "price")),
        "premium_today": _float(_pick(row, "premium_today", "session_premium")),
        "spread_pct": spread_pct,
        "volume": _integer(_pick(row, "volume", "volume_today")),
        "open_interest": _integer(_pick(row, "open_interest", "openInterest", "oi")),
        "iv": _float(_pick(row, "iv", "implied_vol", "impliedVolatility")),
        "delta": _float(_pick(row, "delta")),
        "gamma": _float(_pick(row, "gamma")),
        # A request timestamp, record-update timestamp, or last-trade time is
        # not an NBBO timestamp.  Missing quote time must stay missing so the
        # execution gate cannot manufacture freshness from the run clock.
        "quote_asof_utc": quote_asof,
        "quote_live": quote_live,
        "quote_source": str(_pick(row, "quote_source") or provider),
        "last_trade_asof_utc": _utc(_pick(row, "last_trade_at", "last_trade_date")),
        "provider": provider,
        # Adjusted options do not always use the standard deliverable.  Never
        # infer a 100 multiplier when the provider did not supply it.
        "multiplier": _integer(_pick(row, "multiplier", "contract_multiplier")),
        "adjusted": _pick(row, "adjusted", "is_adjusted", "split_adjusted"),
        "deliverable": _pick(row, "deliverable", "contract_deliverable"),
    }


def _capabilities(contracts: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Describe observed fields without treating reference data as quotes."""
    total = len(contracts)
    fields = (
        "occ_symbol",
        "bid",
        "ask",
        "quote_asof_utc",
        "open_interest",
        "volume",
        "iv",
        "delta",
        "gamma",
        "multiplier",
    )
    counts = {
        field: sum(row.get(field) is not None and row.get(field) != "" for row in contracts)
        for field in fields
    }
    complete = sum(
        all(
            row.get(field) is not None and row.get(field) != ""
            for field in (
                "occ_symbol",
                "bid",
                "ask",
                "quote_asof_utc",
                "open_interest",
                "volume",
                "multiplier",
            )
        )
        for row in contracts
    )
    return {
        "contract_count": total,
        "field_counts": counts,
        "execution_complete_contracts": complete,
        "executable_nbbo_available": complete > 0,
    }


def normalize_snapshot(
    raw: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    *,
    symbol: str,
    provider: str,
    degraded: bool,
    asof_utc: datetime | None = None,
) -> dict[str, Any]:
    """Normalize supported provider payload variants into one snapshot shape."""
    if isinstance(raw, Mapping):
        rows = _pick(raw, "contracts", "options", "chain", "data") or []
        underlying = _pick(raw, "underlying", "spot", "underlying_quote")
        if isinstance(underlying, Mapping):
            price = _float(_pick(underlying, "price", "last", "close"))
            underlying_asof = _utc(_pick(underlying, "asof_utc", "quote_timestamp", "timestamp"))
        else:
            price = _float(underlying)
            underlying_asof = _utc(_pick(raw, "underlying_asof_utc", "underlying_quote_timestamp"))
        source_asof = _utc(_pick(raw, "asof_utc", "timestamp", "updated_at"), asof_utc)
    else:
        rows, price, underlying_asof, source_asof = raw, None, None, _utc(None, asof_utc)
    if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes, Mapping)):
        rows = []
    # Contract DTE is calculated against the caller's immutable run clock;
    # source_asof is a serialized provider timestamp, not a clock object.
    raw_rows = [row for row in rows if isinstance(row, Mapping)]
    contracts = [
        normalize_contract(row, underlying=symbol, provider=provider, asof_utc=asof_utc)
        for row in raw_rows
    ]
    if price is None:
        price = next(
            (
                observed
                for row in raw_rows
                for observed in (_float(_pick(row, "underlying_price", "spot")),)
                if observed is not None
            ),
            None,
        )
    return {
        "symbol": symbol.upper(),
        "provider": provider,
        "degraded": degraded,
        "asof_utc": source_asof,
        "underlying": {"symbol": symbol.upper(), "price": price, "quote_asof_utc": underlying_asof},
        "contracts": contracts,
        "capabilities": _capabilities(contracts),
    }


@dataclass
class LSEOptionsAdapter:
    """Primary live adapter; ``fetcher`` makes it deterministic and testable."""

    api_key: str | None = None
    fetcher: Callable[[str], Mapping[str, Any] | Iterable[Mapping[str, Any]]] | None = None
    bulk_fetcher: Callable[[Sequence[str]], Mapping[str, Mapping[str, Any]]] | None = None
    min_dte: int = 30
    max_dte: int = 60

    def _fetch(self, symbol: str) -> Mapping[str, Any] | Iterable[Mapping[str, Any]]:
        if self.fetcher:
            return self.fetcher(symbol)
        key = self.api_key or os.getenv("LSE_API_KEY")
        if not key:
            raise RuntimeError("LSE_API_KEY is required for live options data")
        # Reuse TradingWork's established production seam (SDK -> ISO -> vault)
        # instead of duplicating an edge-local REST client.
        source = Path(__file__).resolve().parents[3] / "TradingWork" / "src"
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
        from lse_provider import fetch_lse_options_chain  # type: ignore[import-not-found]

        with redirect_stdout(io.StringIO()):
            rows = fetch_lse_options_chain(
                symbol.upper(), min_dte=self.min_dte, max_dte=self.max_dte, api_key=key
            )
        if not rows:
            raise RuntimeError("LSE options chain unavailable or empty")
        return {"contracts": rows}

    def snapshot(self, symbol: str, *, asof_utc: datetime | None = None) -> Mapping[str, Any]:
        return normalize_snapshot(
            self._fetch(symbol), symbol=symbol, provider="lse", degraded=False, asof_utc=asof_utc
        )

    def snapshots(
        self, symbols: Sequence[str], *, asof_utc: datetime | None = None
    ) -> Mapping[str, Mapping[str, Any]]:
        if self.bulk_fetcher:
            raw_map = self.bulk_fetcher(symbols)
            return {
                str(sym).upper(): normalize_snapshot(
                    raw, symbol=str(sym), provider="lse", degraded=False, asof_utc=asof_utc
                )
                for sym, raw in raw_map.items()
            }
        snaps, errs = fetch_provider_snapshots(self, symbols, asof_utc=asof_utc)
        if errs and not snaps:
            first_exc = next(iter(errs.values()))
            raise first_exc
        return snaps


@dataclass
class YFinanceOptionsAdapter:
    """Delayed development fallback. Its output can never be ENTER-eligible."""

    fetcher: Callable[[str], Mapping[str, Any] | Iterable[Mapping[str, Any]]] | None = None
    bulk_fetcher: Callable[[Sequence[str]], Mapping[str, Mapping[str, Any]]] | None = None

    def snapshot(self, symbol: str, *, asof_utc: datetime | None = None) -> Mapping[str, Any]:
        if self.fetcher:
            raw = self.fetcher(symbol)
        else:
            import yfinance as yf  # type: ignore[import-not-found]

            ticker = yf.Ticker(symbol)
            spot: float | None = None
            try:
                spot = _float(ticker.fast_info.get("last_price"))
            except Exception:
                pass
            if spot is None or spot <= 0:
                try:
                    hist = ticker.history(period="1d")
                    if not hist.empty and "Close" in hist.columns:
                        spot = _float(hist["Close"].iloc[-1])
                except Exception:
                    pass

            contracts: list[dict[str, Any]] = []
            for expiry in ticker.options or []:
                chain = ticker.option_chain(expiry)
                for right, frame in (("call", chain.calls), ("put", chain.puts)):
                    for row in frame.to_dict("records"):
                        row.update({"expiry": expiry, "right": right, "spot": spot})
                        contracts.append(row)
            raw = {"underlying": {"symbol": symbol.upper(), "price": spot}, "contracts": contracts}
        return normalize_snapshot(
            raw, symbol=symbol, provider="yfinance", degraded=True, asof_utc=asof_utc
        )

    def snapshots(
        self, symbols: Sequence[str], *, asof_utc: datetime | None = None
    ) -> Mapping[str, Mapping[str, Any]]:
        if self.bulk_fetcher:
            raw_map = self.bulk_fetcher(symbols)
            return {
                str(sym).upper(): normalize_snapshot(
                    raw, symbol=str(sym), provider="yfinance", degraded=True, asof_utc=asof_utc
                )
                for sym, raw in raw_map.items()
            }
        snaps, errs = fetch_provider_snapshots(self, symbols, asof_utc=asof_utc)
        if errs and not snaps:
            first_exc = next(iter(errs.values()))
            raise first_exc
        return snaps


def fetch_provider_snapshots(
    provider: OptionsProvider,
    symbols: Sequence[str],
    *,
    asof_utc: datetime | None = None,
    max_workers: int = 10,
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Exception]]:
    """Fetch snapshots for multiple symbols concurrently or via batch interface.

    Returns a tuple of (snapshots_by_symbol, errors_by_symbol).
    """
    cleaned_symbols = [str(s).upper() for s in symbols if s]
    if not cleaned_symbols:
        return {}, {}

    snapshots: dict[str, Mapping[str, Any]] = {}
    errors: dict[str, Exception] = {}

    # If provider explicitly implements a native snapshots() method, try it first
    snapshots_method = getattr(provider, "snapshots", None)
    if callable(snapshots_method) and getattr(snapshots_method, "__func__", None) not in (
        LSEOptionsAdapter.snapshots,
        YFinanceOptionsAdapter.snapshots,
        OptionsProvider.snapshots,
    ):
        try:
            batch_result = provider.snapshots(cleaned_symbols, asof_utc=asof_utc)
            if isinstance(batch_result, Mapping):
                for sym, snap in batch_result.items():
                    snapshots[str(sym).upper()] = snap
                return snapshots, errors
        except Exception as exc:
            # If batch method fails as a whole, fallback to parallel individual calls
            pass

    workers = min(max_workers, len(cleaned_symbols))
    if workers <= 1:
        for sym in cleaned_symbols:
            try:
                snapshots[sym] = provider.snapshot(sym, asof_utc=asof_utc)
            except Exception as exc:
                errors[sym] = exc
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_sym = {
                executor.submit(provider.snapshot, sym, asof_utc=asof_utc): sym
                for sym in cleaned_symbols
            }
            for future in as_completed(future_to_sym):
                sym = future_to_sym[future]
                try:
                    snapshots[sym] = future.result()
                except Exception as exc:
                    errors[sym] = exc

    return snapshots, errors
