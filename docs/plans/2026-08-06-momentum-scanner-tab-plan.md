# Momentum Scanner Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Momentum" dashboard tab that runs Ross Cameron's Five Pillars pre-scan (RVOL, price, gap, float) as a nightly EOD watchlist against a new small-cap universe.

**Architecture:** Two new nightly fetch scripts build a small-cap OHLCV + float dataset; a pure computation module scores and ranks candidates; a TTL-cached backend endpoint serves it; a new Vue tab renders it. Phase 1 (pre-scan) only — no entry/exit logic, no live data.

**Tech Stack:** Python (pandas, yfinance, stdlib `http.server`), Vue 3 + TypeScript, pytest, vue-tsc.

## Global Constraints

- No new API keys, paid vendors, or live/websocket data sources.
- Float-unknown must render as `"unknown"` / `null` — never silently coerced to pass or fail a pillar (same rule as `tools/data_sources.py`'s `load_finra_short_vol()`).
- `data/1d_smallcap/` keeps a bounded ~70-session rolling window per symbol, not full history — this feeds the nightly scan only, not a backtest.
- Match existing conventions exactly: `tools/fetch_universe_wide.py`'s fetch/manifest pattern, `tools/api_server.py`'s TTL-cache + `_dispatch_api` routing pattern (stdlib `http.server`, **not** Flask), `dashboard/src/api.ts`'s typed-client pattern, `Panel.vue` / `useResource` for the UI.
- Design doc: `docs/plans/2026-08-06-momentum-scanner-tab-design.md`.
- All Python commands run with `edge/.venv-qlib/bin/python`. Tests import as `from edge.tools import <module>` and must be run with cwd at the **parent** of `edge/` (i.e. `alltrading/`) — this matches the working import in `tests/test_dashboard_scan.py` (`from edge.tools import render_dashboard`), since only `edge/__init__.py` exists (no `tests/__init__.py`, no local pytest.ini), so `alltrading/` must be on `sys.path` for that import to resolve. If invoking from inside `edge/` fails with `ModuleNotFoundError: No module named 'edge'`, `cd ..` first.

---

## Task 1: Momentum scan computation module (pure, TDD)

**Files:**
- Create: `tools/momentum_scan.py`
- Test: `tests/test_momentum_scan.py`

**Interfaces:**
- Produces: `momentum_scan.build_momentum_scan(price_data: dict[str, pd.DataFrame], float_data: dict[str, float | None], *, expected_universe_size: int) -> dict` — the function Task 5 calls. Returned dict shape: `{asof: str, universe_size: int, expected_universe_size: int, float_coverage_pct: float, candidates: list[dict]}`. Each candidate dict: `{symbol, price, gap_pct, day_change_pct, rvol, float_shares, float_badge, gap_sweet_spot, price_qualifies, gap_qualifies, rvol_qualifies, pillars_met}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_momentum_scan.py`:

```python
from __future__ import annotations

import pandas as pd
import pytest

from edge.tools import momentum_scan as ms


def _ohlcv(closes, volumes, opens=None):
    n = len(closes)
    opens = opens if opens is not None else closes
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": opens,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": volumes,
        },
        index=idx,
    )


def test_compute_rvol_basic():
    volumes = pd.Series([100_000] * 50 + [600_000])
    assert ms.compute_rvol(volumes) == pytest.approx(6.0)


def test_compute_rvol_insufficient_history():
    volumes = pd.Series([100_000] * 30)
    assert ms.compute_rvol(volumes) is None


def test_compute_gap_pct():
    assert ms.compute_gap_pct(11.0, 10.0) == pytest.approx(0.10)


def test_price_qualifies_band_edges():
    assert ms.price_qualifies(2.00) is True
    assert ms.price_qualifies(20.00) is True
    assert ms.price_qualifies(1.99) is False
    assert ms.price_qualifies(20.01) is False


def test_float_badge_thresholds():
    assert ms.float_badge(None) == "unknown"
    assert ms.float_badge(2_000_000) == "optimal"
    assert ms.float_badge(10_000_000) == "qualifies"
    assert ms.float_badge(50_000_000) == "no"


def test_build_candidate_unknown_float_never_silently_passes_or_fails():
    closes = [10.0] * 50 + [12.0]
    volumes = [100_000] * 50 + [700_000]
    opens = [10.0] * 50 + [11.5]
    df = _ohlcv(closes, volumes, opens)
    candidate = ms.build_candidate("TEST", df, None)
    assert candidate["float_shares"] is None
    assert candidate["float_badge"] == "unknown"
    # Float must never gate the qualify flags -- only price/gap/rvol do.
    assert candidate["price_qualifies"] is True
    assert candidate["gap_qualifies"] is True
    assert candidate["rvol_qualifies"] is True


def test_build_candidate_insufficient_history_returns_none():
    df = _ohlcv([10.0] * 20, [100_000] * 20)
    assert ms.build_candidate("TEST", df, None) is None


def test_rank_candidates_sorts_by_rvol_desc_and_drops_non_qualifying():
    records = [
        {"symbol": "A", "rvol": 6.0, "price_qualifies": True, "gap_qualifies": True, "rvol_qualifies": True},
        {"symbol": "B", "rvol": 9.0, "price_qualifies": True, "gap_qualifies": True, "rvol_qualifies": True},
        {"symbol": "C", "rvol": 20.0, "price_qualifies": True, "gap_qualifies": True, "rvol_qualifies": False},
    ]
    ranked = ms.rank_candidates(records)
    assert [r["symbol"] for r in ranked] == ["B", "A"]


def test_build_momentum_scan_reports_universe_and_float_coverage():
    closes = [10.0] * 50 + [12.0]
    volumes = [100_000] * 50 + [700_000]
    opens = [10.0] * 50 + [11.5]
    price_data = {
        "AAA": _ohlcv(closes, volumes, opens),
        "BBB": _ohlcv(closes, volumes, opens),
    }
    float_data = {"AAA": 5_000_000, "BBB": None}
    result = ms.build_momentum_scan(price_data, float_data, expected_universe_size=5000)
    assert result["universe_size"] == 2
    assert result["expected_universe_size"] == 5000
    assert result["float_coverage_pct"] == pytest.approx(50.0)
    assert len(result["candidates"]) == 2


def test_build_momentum_scan_zero_candidates_is_not_an_error():
    flat = _ohlcv([10.0] * 51, [100_000] * 51)  # no gap, no rvol spike
    result = ms.build_momentum_scan({"FLAT": flat}, {"FLAT": None}, expected_universe_size=1)
    assert result["candidates"] == []
    assert result["universe_size"] == 1
```

- [ ] **Step 2: Run tests, verify they fail**

From `alltrading/` (parent of `edge/`):

```bash
edge/.venv-qlib/bin/python -m pytest edge/tests/test_momentum_scan.py -v
```

Expected: `ModuleNotFoundError: No module named 'edge.tools.momentum_scan'` (or collection error) — the module doesn't exist yet.

- [ ] **Step 3: Write the implementation**

Create `tools/momentum_scan.py`:

```python
"""Pure computation for the Ross Cameron 'Five Pillars' momentum pre-scan.

No network, no filesystem writes -- callers hand this module in-memory
OHLCV frames and a float lookup, and get back a ranked candidate list. Kept
separate from api_server.py so it is testable without booting the server,
mirroring how render_dashboard.py holds get_dashboard_data's logic and
api_server.py only wraps/caches it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

RVOL_LOOKBACK = 50
RVOL_MIN_MULTIPLE = 5.0
PRICE_MIN = 2.0
PRICE_MAX = 20.0
GAP_MIN_PCT = 0.02
GAP_SWEET_LOW = 0.10
GAP_SWEET_HIGH = 0.30
FLOAT_QUALIFY_MAX = 20_000_000
FLOAT_OPTIMAL_MAX = 3_000_000


def compute_rvol(volumes: pd.Series) -> float | None:
    """Last session's volume / mean of the RVOL_LOOKBACK sessions before it.
    None if there isn't enough history yet."""
    if len(volumes) < RVOL_LOOKBACK + 1:
        return None
    last = float(volumes.iloc[-1])
    baseline = volumes.iloc[-(RVOL_LOOKBACK + 1):-1].mean()
    if not baseline or baseline <= 0:
        return None
    return last / float(baseline)


def compute_gap_pct(open_price: float, prior_close: float) -> float | None:
    if not prior_close:
        return None
    return (open_price - prior_close) / prior_close


def compute_day_change_pct(close: float, prior_close: float) -> float | None:
    if not prior_close:
        return None
    return (close - prior_close) / prior_close


def price_qualifies(price: float) -> bool:
    return PRICE_MIN <= price <= PRICE_MAX


def gap_qualifies(gap_pct: float | None) -> bool:
    return gap_pct is not None and gap_pct >= GAP_MIN_PCT


def rvol_qualifies(rvol: float | None) -> bool:
    return rvol is not None and rvol > RVOL_MIN_MULTIPLE


def float_badge(float_shares: float | None) -> str:
    if float_shares is None:
        return "unknown"
    if float_shares < FLOAT_OPTIMAL_MAX:
        return "optimal"
    if float_shares < FLOAT_QUALIFY_MAX:
        return "qualifies"
    return "no"


def build_candidate(symbol: str, df: pd.DataFrame, float_shares: float | None) -> dict | None:
    """One candidate record from a symbol's OHLCV history, or None if there
    isn't enough history to compute RVOL yet."""
    if len(df) < RVOL_LOOKBACK + 1:
        return None
    last = df.iloc[-1]
    prior_close = float(df.iloc[-2]["close"])
    rvol = compute_rvol(df["volume"])
    gap_pct = compute_gap_pct(float(last["open"]), prior_close)
    day_change_pct = compute_day_change_pct(float(last["close"]), prior_close)
    price = float(last["close"])
    return {
        "symbol": symbol,
        "price": price,
        "gap_pct": gap_pct,
        "day_change_pct": day_change_pct,
        "rvol": rvol,
        "float_shares": float_shares,
        "float_badge": float_badge(float_shares),
        "gap_sweet_spot": gap_pct is not None and GAP_SWEET_LOW <= gap_pct <= GAP_SWEET_HIGH,
        "price_qualifies": price_qualifies(price),
        "gap_qualifies": gap_qualifies(gap_pct),
        "rvol_qualifies": rvol_qualifies(rvol),
        "pillars_met": sum([price_qualifies(price), gap_qualifies(gap_pct), rvol_qualifies(rvol)]),
    }


def rank_candidates(records: list[dict]) -> list[dict]:
    """Candidates meeting all three always-computable pillars (price, gap,
    RVOL), ranked by RVOL descending. Float never gates -- it renders as a
    badge on every row instead (float_badge); a meaningful share of the
    universe will have unresolvable float and must not be hidden for it."""
    qualifying = [r for r in records if r["price_qualifies"] and r["gap_qualifies"] and r["rvol_qualifies"]]
    return sorted(qualifying, key=lambda r: r["rvol"], reverse=True)


def build_momentum_scan(
    price_data: dict[str, pd.DataFrame],
    float_data: dict[str, float | None],
    *,
    expected_universe_size: int,
) -> dict:
    """Top-level entry point. price_data maps symbol -> OHLCV DataFrame
    (columns open/high/low/close/volume, DatetimeIndex, most-recent-last).
    float_data maps symbol -> float_shares or None."""
    records = []
    for symbol, df in price_data.items():
        candidate = build_candidate(symbol, df, float_data.get(symbol))
        if candidate is not None:
            records.append(candidate)
    ranked = rank_candidates(records)
    known_float = sum(1 for r in records if r["float_shares"] is not None)
    float_coverage_pct = (known_float / len(records) * 100.0) if records else 0.0
    return {
        "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "universe_size": len(price_data),
        "expected_universe_size": expected_universe_size,
        "float_coverage_pct": round(float_coverage_pct, 1),
        "candidates": ranked,
    }
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
edge/.venv-qlib/bin/python -m pytest edge/tests/test_momentum_scan.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add edge/tools/momentum_scan.py edge/tests/test_momentum_scan.py
git commit -m "Add momentum_scan: pure Five Pillars pre-scan computation"
```

---

## Task 2: Small-cap universe fetch script

**Files:**
- Create: `tools/fetch_smallcap_universe.py`
- Test: `tests/test_fetch_smallcap_universe.py`

**Interfaces:**
- Consumes: none (network + stdlib only).
- Produces: `data/1d_smallcap/<SYMBOL>.parquet` (schema: `DatetimeIndex` + `open/high/low/close/volume`, tail-trimmed to 70 rows), `data/1d_smallcap/FETCH_MANIFEST_SMALLCAP.json` (`{generated_at, expected_universe_size, results: {symbol: {status, n_rows}}, summary: {landed, expected, landed_fraction}}`). Task 3 and Task 5 both read this directory; Task 5 also reads `expected_universe_size` from the manifest.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fetch_smallcap_universe.py` (covers the pure/local pieces only — no network):

```python
from __future__ import annotations

import pandas as pd

from edge.tools import fetch_smallcap_universe as fsu


NASDAQ_SAMPLE = (
    "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
    "AAAA|Alpha Test Co|Q|N|N|100|N|N\n"
    "BBBB|Beta ETF|Q|N|N|100|Y|N\n"
    "CCCC|Gamma Test Issue|Q|Y|N|100|N|N\n"
    "File Creation Time: 0801202608:00\n"
)


def test_parse_symbol_directory_excludes_etf_and_test_issue():
    symbols = fsu._parse_symbol_directory(NASDAQ_SAMPLE, symbol_col="Symbol", exchange_note="nasdaqlisted")
    assert symbols == ["AAAA"]


def test_normalize_renames_adj_close_and_lowercases():
    df = pd.DataFrame(
        {"Open": [1.0], "High": [1.1], "Low": [0.9], "Adj Close": [1.05], "Volume": [1000]},
        index=pd.to_datetime(["2026-01-02"]),
    )
    out = fsu._normalize(df)
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert out["close"].iloc[0] == 1.05


def test_normalize_trims_to_lookback_window():
    idx = pd.date_range("2026-01-01", periods=200, freq="B")
    df = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 100}, index=idx
    )
    out = fsu._normalize(df)
    assert len(out) == fsu.LOOKBACK_SESSIONS


def test_maybe_write_keeps_existing_when_new_pull_is_smaller(tmp_path):
    path = tmp_path / "AAAA.parquet"
    big = pd.DataFrame({"open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0], "close": [1.0, 2.0], "volume": [1, 2]})
    small = big.iloc[:1]
    fsu.maybe_write(path, big, force=False)
    status = fsu.maybe_write(path, small, force=False)
    assert status == "kept_existing"
    assert len(pd.read_parquet(path)) == 2


def test_maybe_write_force_overwrites_with_smaller(tmp_path):
    path = tmp_path / "AAAA.parquet"
    big = pd.DataFrame({"open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0], "close": [1.0, 2.0], "volume": [1, 2]})
    small = big.iloc[:1]
    fsu.maybe_write(path, big, force=False)
    status = fsu.maybe_write(path, small, force=True)
    assert status == "written"
    assert len(pd.read_parquet(path)) == 1
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
edge/.venv-qlib/bin/python -m pytest edge/tests/test_fetch_smallcap_universe.py -v
```

Expected: `ModuleNotFoundError` — script doesn't exist yet.

- [ ] **Step 3: Write the implementation**

Create `tools/fetch_smallcap_universe.py`:

```python
#!/usr/bin/env python3
"""Fetch a bounded rolling-window daily OHLCV panel for a broad small-cap
candidate universe into edge/data/1d_smallcap/.

Universe comes from NASDAQ Trader's public symbol directory (no auth) --
NASDAQ-listed + NYSE/AMEX-listed common stock, ETFs and test issues
excluded. Unlike edge/tools/fetch_universe_wide.py (which keeps full
history for the qlib factor pipeline), this keeps only the trailing
~70 sessions per symbol: this pipeline feeds a nightly momentum pre-scan
(edge/tools/momentum_scan.py), not a backtest, and bounding the window
keeps runtime and storage flat regardless of universe size.

Usage:
  edge/.venv-qlib/bin/python edge/tools/fetch_smallcap_universe.py
  edge/.venv-qlib/bin/python edge/tools/fetch_smallcap_universe.py --limit 30   # smoke test
  edge/.venv-qlib/bin/python edge/tools/fetch_smallcap_universe.py --force
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "edge" / "data" / "1d_smallcap"
MANIFEST = OUT / "FETCH_MANIFEST_SMALLCAP.json"

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

LOOKBACK_SESSIONS = 70
CHUNK_SIZE = 100
MAX_RETRIES = 3
RETRY_SLEEP = 2.0
NEED = ["open", "high", "low", "close", "volume"]

START = (datetime.now(timezone.utc) - timedelta(days=int(LOOKBACK_SESSIONS * 1.6))).strftime("%Y-%m-%d")


def _parse_symbol_directory(text: str, *, symbol_col: str, exchange_note: str) -> List[str]:
    """Pipe-delimited NASDAQ Trader format: header row, data rows, a
    'File Creation Time' footer row. Column-name lookup, not positional --
    tolerates minor column reordering."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    header = lines[0].split("|")
    try:
        sym_idx = header.index(symbol_col)
    except ValueError:
        print(f"  {exchange_note}: unexpected header {header!r}, skipping")
        return []
    etf_idx = header.index("ETF") if "ETF" in header else None
    test_idx = header.index("Test Issue") if "Test Issue" in header else None
    out = []
    for line in lines[1:]:
        if line.startswith("File Creation Time"):
            continue
        fields = line.split("|")
        if len(fields) <= sym_idx:
            continue
        if etf_idx is not None and etf_idx < len(fields) and fields[etf_idx].strip().upper() == "Y":
            continue
        if test_idx is not None and test_idx < len(fields) and fields[test_idx].strip().upper() == "Y":
            continue
        symbol = fields[sym_idx].strip()
        if symbol and "$" not in symbol and "." not in symbol:
            out.append(symbol)
    return out


def download_symbol_directory() -> List[str]:
    """Union of NASDAQ-listed + NYSE/AMEX-listed common stock symbols.
    Raises if BOTH sources fail -- an empty universe must never be mistaken
    for 'market has zero small caps today', matching the return-real-data-
    or-raise rule in edge/tools/data_sources.py."""
    symbols: set[str] = set()
    sources = [
        (NASDAQ_LISTED_URL, "Symbol", "nasdaqlisted"),
        (OTHER_LISTED_URL, "ACT Symbol", "otherlisted"),
    ]
    failures = []
    for url, symbol_col, note in sources:
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            found = _parse_symbol_directory(text, symbol_col=symbol_col, exchange_note=note)
            print(f"  {note}: {len(found)} symbols")
            symbols.update(found)
        except Exception as e:
            failures.append(f"{note}: {e}")
    if not symbols:
        raise RuntimeError("Could not fetch any symbol directory -- " + "; ".join(failures))
    if failures:
        print(f"  WARNING: partial symbol directory ({'; '.join(failures)})")
    return sorted(symbols)


def _chunks(seq: List[str], n: int) -> List[List[str]]:
    return [seq[i : i + n] for i in range(0, len(seq), n)]


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Match edge/data/1d_wide/ schema: DatetimeIndex, open/high/low/close/volume."""
    if df is None or df.empty:
        return pd.DataFrame(columns=NEED)
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [str(c[0]).lower() for c in out.columns]
    else:
        out.columns = [str(c).lower() for c in out.columns]
    rename = {c: "close" for c in out.columns if c in ("adj close", "adj_close")}
    if rename:
        out = out.rename(columns=rename)
    missing = [c for c in NEED if c not in out.columns]
    if missing:
        return pd.DataFrame(columns=NEED)
    out = out[NEED].astype(float)
    out.index = pd.to_datetime(out.index)
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out.dropna(subset=["close"])
    return out.tail(LOOKBACK_SESSIONS)


def fetch_chunk(symbols: List[str]) -> Dict[str, pd.DataFrame]:
    import yfinance as yf

    if len(symbols) == 1:
        raw = yf.download(symbols[0], start=START, interval="1d", auto_adjust=True, progress=False, threads=False)
        return {symbols[0]: _normalize(raw)}

    raw = yf.download(
        symbols, start=START, interval="1d",
        auto_adjust=True, group_by="ticker", threads=True, progress=False,
    )
    out: Dict[str, pd.DataFrame] = {}
    top = set(raw.columns.get_level_values(0)) if isinstance(raw.columns, pd.MultiIndex) else set()
    for sym in symbols:
        out[sym] = _normalize(raw[sym]) if sym in top else pd.DataFrame(columns=NEED)
    return out


def fetch_one_retry(symbol: str, max_retries: int = MAX_RETRIES) -> pd.DataFrame:
    import yfinance as yf

    for attempt in range(1, max_retries + 1):
        try:
            raw = yf.download(symbol, start=START, interval="1d", auto_adjust=True, progress=False, threads=False)
            df = _normalize(raw)
            if not df.empty:
                return df
        except Exception:
            pass
        time.sleep(RETRY_SLEEP * attempt)
    return pd.DataFrame(columns=NEED)


def maybe_write(path: Path, df: pd.DataFrame, force: bool) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        old = pd.read_parquet(path)
        if len(df) <= len(old):
            return "kept_existing"
    df.to_parquet(path)
    return "written"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="smoke-test: only fetch the first N symbols")
    parser.add_argument("--force", action="store_true", help="overwrite even if the new pull has fewer rows")
    args = parser.parse_args(argv)

    print("Downloading NASDAQ Trader symbol directory...")
    symbols = download_symbol_directory()
    if args.limit:
        symbols = symbols[: args.limit]
    print(f"Universe: {len(symbols)} symbols")

    manifest: Dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expected_universe_size": len(symbols),
        "results": {},
    }

    landed = 0
    missed: List[str] = []
    for i, chunk in enumerate(_chunks(symbols, CHUNK_SIZE)):
        print(f"  chunk {i + 1}: {len(chunk)} symbols")
        fetched = fetch_chunk(chunk)
        for sym in chunk:
            df = fetched.get(sym, pd.DataFrame(columns=NEED))
            if df.empty:
                missed.append(sym)
                continue
            status = maybe_write(OUT / f"{sym}.parquet", df, args.force)
            manifest["results"][sym] = {"status": status, "n_rows": len(df)}
            landed += 1

    for sym in missed:
        df = fetch_one_retry(sym)
        if df.empty:
            manifest["results"][sym] = {"status": "empty_or_failed"}
            continue
        status = maybe_write(OUT / f"{sym}.parquet", df, args.force)
        manifest["results"][sym] = {"status": status, "n_rows": len(df)}
        landed += 1

    manifest["summary"] = {
        "landed": landed,
        "expected": len(symbols),
        "landed_fraction": landed / len(symbols) if symbols else 0.0,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nlanded {landed} / {len(symbols)} ({manifest['summary']['landed_fraction']:.1%})")
    print(f"Manifest -> {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
edge/.venv-qlib/bin/python -m pytest edge/tests/test_fetch_smallcap_universe.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Smoke-test against the real network**

```bash
edge/.venv-qlib/bin/python edge/tools/fetch_smallcap_universe.py --limit 10
```

Expected: prints a landed fraction, writes up to 10 parquet files under `edge/data/1d_smallcap/` and `FETCH_MANIFEST_SMALLCAP.json`. If the NASDAQ Trader URLs are unreachable from this environment, this step will fail loudly with the `RuntimeError` from `download_symbol_directory()` — note that in the task result; it does not block Tasks 1, 3-7 since they consume the *shape* of this output, which the tests already validate against fixtures.

- [ ] **Step 6: Commit**

```bash
git add edge/tools/fetch_smallcap_universe.py edge/tests/test_fetch_smallcap_universe.py
git commit -m "Add fetch_smallcap_universe: NASDAQ Trader small-cap OHLCV fetcher"
```

---

## Task 3: Float data fetch script

**Files:**
- Create: `tools/fetch_float_data.py`
- Test: `tests/test_fetch_float_data.py`

**Interfaces:**
- Consumes: `data/1d_smallcap/*.parquet` (from Task 2).
- Produces: `data/float_data/float.csv` (columns: `symbol, float_shares, shares_outstanding, as_of_date`), and `fetch_float_data.load_float_data(csv_path=OUT_CSV) -> dict[str, float | None]` — the function Task 5 imports and calls.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fetch_float_data.py`:

```python
from __future__ import annotations

import csv

from edge.tools import fetch_float_data as ffd


def test_load_float_data_missing_file_returns_empty_dict(tmp_path):
    assert ffd.load_float_data(tmp_path / "nope.csv") == {}


def test_load_float_data_round_trips_known_and_unknown_float(tmp_path):
    csv_path = tmp_path / "float.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ffd.FIELDS)
        writer.writeheader()
        writer.writerow({"symbol": "AAA", "float_shares": 5_000_000, "shares_outstanding": 6_000_000, "as_of_date": "2026-08-06"})
        writer.writerow({"symbol": "BBB", "float_shares": "", "shares_outstanding": "", "as_of_date": "2026-08-06"})

    result = ffd.load_float_data(csv_path)
    assert result["AAA"] == 5_000_000.0
    assert result["BBB"] is None  # unresolved float loads as None, never 0 or dropped


def test_candidates_under_ceiling_filters_by_last_close(tmp_path, monkeypatch):
    import pandas as pd

    monkeypatch.setattr(ffd, "SMALLCAP_DIR", tmp_path)
    cheap = pd.DataFrame({"close": [1.0, 5.0]}, index=pd.date_range("2026-01-01", periods=2))
    expensive = pd.DataFrame({"close": [1.0, 500.0]}, index=pd.date_range("2026-01-01", periods=2))
    cheap.to_parquet(tmp_path / "CHEAP.parquet")
    expensive.to_parquet(tmp_path / "EXPENSIVE.parquet")

    result = ffd.candidates_under_ceiling()
    assert result == ["CHEAP"]
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
edge/.venv-qlib/bin/python -m pytest edge/tests/test_fetch_float_data.py -v
```

Expected: `ModuleNotFoundError` — script doesn't exist yet.

- [ ] **Step 3: Write the implementation**

Create `tools/fetch_float_data.py`:

```python
#!/usr/bin/env python3
"""Fetch float / shares-outstanding for the small-cap scan universe into
edge/data/float_data/float.csv.

Reads edge/data/1d_smallcap/ (written by fetch_smallcap_universe.py) to find
symbols whose last close is at or under FLOAT_FETCH_PRICE_CEILING, then
looks up float via yfinance's .info for just that subset -- the full
universe is ~8-11k tickers and .info is slow/rate-limited, so this narrows
to the price band the momentum scan cares about before paying that cost. A
symbol whose float can't be resolved is written with an empty float_shares
cell, never silently dropped or coerced to a number -- same rule as
edge/tools/data_sources.py's load_finra_short_vol().

Usage:
  edge/.venv-qlib/bin/python edge/tools/fetch_float_data.py
  edge/.venv-qlib/bin/python edge/tools/fetch_float_data.py --limit 30   # smoke test
"""

from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SMALLCAP_DIR = ROOT / "edge" / "data" / "1d_smallcap"
OUT_DIR = ROOT / "edge" / "data" / "float_data"
OUT_CSV = OUT_DIR / "float.csv"

FLOAT_FETCH_PRICE_CEILING = 25.0
MAX_RETRIES = 2
RETRY_SLEEP = 1.5
FIELDS = ["symbol", "float_shares", "shares_outstanding", "as_of_date"]


def candidates_under_ceiling() -> list[str]:
    out = []
    for path in sorted(SMALLCAP_DIR.glob("*.parquet")):
        try:
            df = pd.read_parquet(path, columns=["close"])
        except Exception:
            continue
        if df.empty:
            continue
        if float(df["close"].iloc[-1]) <= FLOAT_FETCH_PRICE_CEILING:
            out.append(path.stem)
    return out


def fetch_float(symbol: str) -> tuple[Optional[float], Optional[float]]:
    """Returns (float_shares, shares_outstanding); either may be None if
    yfinance has no value -- a missing value is real information (unknown),
    never coerced to 0 or dropped."""
    import yfinance as yf

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            info = yf.Ticker(symbol).get_info()
            float_shares = info.get("floatShares")
            shares_out = info.get("sharesOutstanding")
            return (
                float(float_shares) if float_shares is not None else None,
                float(shares_out) if shares_out is not None else None,
            )
        except Exception:
            time.sleep(RETRY_SLEEP * attempt)
    return (None, None)


def load_float_data(csv_path: Path = OUT_CSV) -> dict[str, Optional[float]]:
    """symbol -> float_shares, or None if unresolved. Never coerces a
    missing value to 0 or drops the row."""
    if not csv_path.exists():
        return {}
    out: dict[str, Optional[float]] = {}
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw = row.get("float_shares", "")
            out[row["symbol"]] = float(raw) if raw not in ("", None) else None
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    symbols = candidates_under_ceiling()
    if args.limit:
        symbols = symbols[: args.limit]
    print(f"Fetching float for {len(symbols)} symbols at or under ${FLOAT_FETCH_PRICE_CEILING:.0f}")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = []
    known = 0
    for i, sym in enumerate(symbols):
        float_shares, shares_out = fetch_float(sym)
        if float_shares is not None:
            known += 1
        rows.append({
            "symbol": sym,
            "float_shares": "" if float_shares is None else float_shares,
            "shares_outstanding": "" if shares_out is None else shares_out,
            "as_of_date": today,
        })
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(symbols)} ({known} resolved)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nresolved {known} / {len(symbols)} floats")
    print(f"-> {OUT_CSV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
edge/.venv-qlib/bin/python -m pytest edge/tests/test_fetch_float_data.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add edge/tools/fetch_float_data.py edge/tests/test_fetch_float_data.py
git commit -m "Add fetch_float_data: yfinance float lookup with honest nulls"
```

---

## Task 4: Wire both fetchers into the nightly pipeline

**Files:**
- Modify: `tools/update_all_data.sh`

**Interfaces:**
- Consumes: `tools/fetch_smallcap_universe.py`, `tools/fetch_float_data.py` (Tasks 2-3), both invoked with no args (full run, not `--limit`).

- [ ] **Step 1: Edit `update_all_data.sh`**

Current tail of the file (steps 1-5, then the closing banner):

```bash
echo "--> [1/5] Fetching main universe daily OHLCV prices..."
"$PYTHON_BIN" "$ROOT/tools/fetch_universe.py" --interval 1d --force || true

echo "--> [2/5] Fetching wide candidate universe daily OHLCV prices..."
"$PYTHON_BIN" "$ROOT/tools/fetch_universe_wide.py" --force || true

echo "--> [3/5] Re-indexing Qlib binary feature datasets..."
"$PYTHON_BIN" "$ROOT/tools/qlib_ingest.py"
"$PYTHON_BIN" "$ROOT/tools/qlib_ingest_wide.py"

echo "--> [4/5] Updating Volatility Complex dataset..."
"$PYTHON_BIN" "$ROOT/tools/fetch_vol_complex.py" --end "$TODAY" || true

echo "--> [5/5] Updating FINRA short volume dataset..."
"$PYTHON_BIN" "$ROOT/tools/fetch_finra_short_vol.py" --days 30 || true

echo "============================================================"
echo "  ✅ All market and research datasets are now up to date as of $TODAY!"
echo "============================================================"
```

Replace the whole block above with:

```bash
echo "--> [1/7] Fetching main universe daily OHLCV prices..."
"$PYTHON_BIN" "$ROOT/tools/fetch_universe.py" --interval 1d --force || true

echo "--> [2/7] Fetching wide candidate universe daily OHLCV prices..."
"$PYTHON_BIN" "$ROOT/tools/fetch_universe_wide.py" --force || true

echo "--> [3/7] Re-indexing Qlib binary feature datasets..."
"$PYTHON_BIN" "$ROOT/tools/qlib_ingest.py"
"$PYTHON_BIN" "$ROOT/tools/qlib_ingest_wide.py"

echo "--> [4/7] Updating Volatility Complex dataset..."
"$PYTHON_BIN" "$ROOT/tools/fetch_vol_complex.py" --end "$TODAY" || true

echo "--> [5/7] Updating FINRA short volume dataset..."
"$PYTHON_BIN" "$ROOT/tools/fetch_finra_short_vol.py" --days 30 || true

echo "--> [6/7] Fetching small-cap momentum-scan universe..."
"$PYTHON_BIN" "$ROOT/tools/fetch_smallcap_universe.py" || true

echo "--> [7/7] Fetching float data for the momentum scan..."
"$PYTHON_BIN" "$ROOT/tools/fetch_float_data.py" || true

echo "============================================================"
echo "  ✅ All market and research datasets are now up to date as of $TODAY!"
echo "============================================================"
```

- [ ] **Step 2: Verify shell syntax**

```bash
bash -n edge/tools/update_all_data.sh
```

Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add edge/tools/update_all_data.sh
git commit -m "Wire momentum-scan fetchers into the nightly data pipeline"
```

---

## Task 5: Backend endpoint

**Files:**
- Modify: `tools/api_server.py`
  - Add constant near `DATA_WIDE_DIR`/`DATA_CORE_DIR` (around line 184-185).
  - Add import near the existing `from render_dashboard import (...)` (line 204) — `TOOLS_DIR` is already on `sys.path` there (line 203), so a plain sibling import works exactly like `render_dashboard`'s.
  - Add the payload/cache functions near `_gates_payload` (around line 2365 in the current file; re-grep for `_gates_payload` before editing since Tasks 1-4 do not touch this file and line numbers here are otherwise stable).
  - Add one `elif` branch in `_dispatch_api` near the `/api/gates` branch (around line 2729).
- Test: `tests/test_momentum_scan_endpoint.py`

**Interfaces:**
- Consumes: `momentum_scan.build_momentum_scan(...)` (Task 1), `fetch_float_data.load_float_data()` (Task 3), `data/1d_smallcap/*.parquet` + `FETCH_MANIFEST_SMALLCAP.json` (Task 2).
- Produces: `GET /api/momentum-scan` — same JSON shape as `build_momentum_scan`'s return value.

- [ ] **Step 1: Write the failing test**

Create `tests/test_momentum_scan_endpoint.py`:

```python
from __future__ import annotations

from edge.tools import api_server


def test_momentum_scan_payload_uses_loaders_and_caches(monkeypatch):
    calls = {"price": 0, "float": 0}

    def fake_price_data():
        calls["price"] += 1
        return {}

    def fake_float_data():
        calls["float"] += 1
        return {}

    monkeypatch.setattr(api_server, "_load_smallcap_price_data", fake_price_data)
    monkeypatch.setattr(api_server, "load_float_data", fake_float_data)
    api_server._MOMENTUM_SCAN_CACHE = None
    api_server._MOMENTUM_SCAN_CACHE_TS = 0.0

    first = api_server._momentum_scan_payload()
    second = api_server._momentum_scan_payload()

    assert calls["price"] == 1  # second call served from cache, not refetched
    assert calls["float"] == 1
    assert first is second
    assert first["candidates"] == []


def test_momentum_scan_payload_force_bypasses_cache(monkeypatch):
    calls = {"price": 0}

    def fake_price_data():
        calls["price"] += 1
        return {}

    monkeypatch.setattr(api_server, "_load_smallcap_price_data", fake_price_data)
    monkeypatch.setattr(api_server, "load_float_data", lambda: {})
    api_server._MOMENTUM_SCAN_CACHE = None
    api_server._MOMENTUM_SCAN_CACHE_TS = 0.0

    api_server._momentum_scan_payload()
    api_server._momentum_scan_payload(force=True)

    assert calls["price"] == 2
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
edge/.venv-qlib/bin/python -m pytest edge/tests/test_momentum_scan_endpoint.py -v
```

Expected: `AttributeError: module 'edge.tools.api_server' has no attribute '_load_smallcap_price_data'`.

- [ ] **Step 3: Implement**

In `tools/api_server.py`, add next to the existing `DATA_WIDE_DIR`/`DATA_CORE_DIR` constants (~line 184-185):

```python
DATA_SMALLCAP_DIR = EDGE_DIR / "data" / "1d_smallcap"
```

Add next to the existing `from render_dashboard import (...)` block (~line 204):

```python
from momentum_scan import build_momentum_scan
from fetch_float_data import load_float_data
```

Add near `_gates_payload` (~line 2365, verify via `grep -n "_gates_payload" edge/tools/api_server.py` first since this task is applied after earlier tasks may have shifted nothing in this file — Tasks 1-4 touch other files only):

```python
_MOMENTUM_SCAN_CACHE: dict | None = None
_MOMENTUM_SCAN_CACHE_TS: float = 0.0
_MOMENTUM_SCAN_CACHE_TTL_S = 300.0
_MOMENTUM_SCAN_LOCK = threading.Lock()


def _load_smallcap_price_data() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if not DATA_SMALLCAP_DIR.is_dir():
        return out
    for path in DATA_SMALLCAP_DIR.glob("*.parquet"):
        try:
            out[path.stem] = pd.read_parquet(path)
        except Exception:
            continue
    return out


def _momentum_scan_payload(*, force: bool = False) -> dict:
    global _MOMENTUM_SCAN_CACHE, _MOMENTUM_SCAN_CACHE_TS
    now = time.time()
    if not force and _MOMENTUM_SCAN_CACHE is not None and (now - _MOMENTUM_SCAN_CACHE_TS) < _MOMENTUM_SCAN_CACHE_TTL_S:
        return _MOMENTUM_SCAN_CACHE
    with _MOMENTUM_SCAN_LOCK:
        now = time.time()
        if not force and _MOMENTUM_SCAN_CACHE is not None and (now - _MOMENTUM_SCAN_CACHE_TS) < _MOMENTUM_SCAN_CACHE_TTL_S:
            return _MOMENTUM_SCAN_CACHE
        price_data = _load_smallcap_price_data()
        float_data = load_float_data()
        expected = len(price_data)
        manifest_path = DATA_SMALLCAP_DIR / "FETCH_MANIFEST_SMALLCAP.json"
        if manifest_path.exists():
            try:
                expected = json.loads(manifest_path.read_text()).get("expected_universe_size", expected)
            except Exception:
                pass
        payload = build_momentum_scan(price_data, float_data, expected_universe_size=expected)
        _MOMENTUM_SCAN_CACHE = payload
        _MOMENTUM_SCAN_CACHE_TS = time.time()
        return payload
```

Add one `elif` branch in `_dispatch_api` (~line 2729, next to `/api/gates`):

```python
            elif path == "/api/momentum-scan":
                self._send_json(_momentum_scan_payload())
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
edge/.venv-qlib/bin/python -m pytest edge/tests/test_momentum_scan_endpoint.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Manual smoke test**

```bash
edge/.venv-qlib/bin/python edge/tools/api_server.py --port 8787 --no-browser &
sleep 2
curl -s http://localhost:8787/api/momentum-scan | head -c 500
kill %1
```

Expected: valid JSON with `asof`, `universe_size`, `expected_universe_size`, `float_coverage_pct`, `candidates` keys (candidates may be empty if Task 2/3's data hasn't been fetched yet in this environment — that is expected and consistent with the "0 candidates" honest-empty-state design).

- [ ] **Step 6: Commit**

```bash
git add edge/tools/api_server.py edge/tests/test_momentum_scan_endpoint.py
git commit -m "Add GET /api/momentum-scan endpoint"
```

---

## Task 6: Frontend API client

**Files:**
- Modify: `dashboard/src/api.ts` — add types before `export const api = {` (currently line 1198), add one entry inside that object.

**Interfaces:**
- Consumes: `GET /api/momentum-scan` (Task 5).
- Produces: `MomentumCandidate`, `MomentumScanPayload` types and `api.momentumScan()`, used by Task 7.

- [ ] **Step 1: Add the types and client function**

Add immediately before the `export const api = {` line:

```typescript
export interface MomentumCandidate {
  symbol: string
  price: number
  gap_pct: number | null
  day_change_pct: number | null
  rvol: number | null
  float_shares: number | null
  float_badge: 'optimal' | 'qualifies' | 'no' | 'unknown'
  gap_sweet_spot: boolean
  price_qualifies: boolean
  gap_qualifies: boolean
  rvol_qualifies: boolean
  pillars_met: number
}

export interface MomentumScanPayload {
  asof: string
  universe_size: number
  expected_universe_size: number
  float_coverage_pct: number
  candidates: MomentumCandidate[]
}
```

Inside the `export const api = { ... }` object, add:

```typescript
  momentumScan: () => req<MomentumScanPayload>('/api/momentum-scan'),
```

- [ ] **Step 2: Type-check**

```bash
cd dashboard && npx vue-tsc --noEmit
```

Expected: no new type errors (pre-existing unrelated errors, if any, are out of scope for this task).

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/api.ts
git commit -m "Add momentumScan client to dashboard api.ts"
```

---

## Task 7: Frontend tab, routing, and nav

**Files:**
- Create: `dashboard/src/views/MomentumView.vue`
- Modify: `dashboard/src/router.ts` — add a route entry before the catch-all redirect.
- Modify: `dashboard/src/App.vue` — add one entry to the `nav` array.

**Interfaces:**
- Consumes: `api.momentumScan()`, `MomentumCandidate` (Task 6); `Panel.vue` props (`label`, `meta`, `index`, `live`, `flush`); `useResource(fetcher, opts)` returning `{data, loading, error, fetchedAt}`; `num`, `usd` from `@/format`.

- [ ] **Step 1: Create the view**

Create `dashboard/src/views/MomentumView.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { api, type MomentumCandidate } from '@/api'
import { useResource } from '@/composables/useResource'
import Panel from '@/components/Panel.vue'
import { num, usd } from '@/format'

const scan = useResource(() => api.momentumScan(), { intervalMs: 300_000 })

const candidates = computed<MomentumCandidate[]>(() => scan.data.value?.candidates ?? [])

function pct(v: number | null): string {
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
}

function rvolTxt(v: number | null): string {
  return v == null ? '—' : `${v.toFixed(1)}×`
}

function floatTxt(shares: number | null): string {
  if (shares == null) return 'n/a'
  return `${(shares / 1_000_000).toFixed(1)}M`
}
</script>

<template>
  <div class="momentum-view">
    <Panel
      label="Momentum Pre-Scan"
      index="14"
      :meta="scan.data.value ? `as of ${scan.data.value.asof}` : ''"
      :live="!scan.error.value"
      flush
    >
      <div class="banner label">
        Pre-market watchlist, not a live feed · Five Pillars pre-scan (price, gap, RVOL, float) against
        {{ scan.data.value ? num(scan.data.value.universe_size) : '—' }} of
        {{ scan.data.value ? num(scan.data.value.expected_universe_size) : '—' }} expected symbols ·
        float known for {{ scan.data.value ? scan.data.value.float_coverage_pct.toFixed(0) : '—' }}%
      </div>

      <p v-if="scan.error.value" class="state label">{{ scan.error.value }}</p>
      <p v-else-if="scan.loading.value && !scan.data.value" class="state label">Loading momentum scan…</p>
      <p v-else-if="!candidates.length" class="state label">
        0 candidates met price + gap + RVOL criteria as of {{ scan.data.value?.asof ?? 'last close' }}.
      </p>

      <table v-else class="mtable">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Price</th>
            <th>Gap</th>
            <th>Day chg</th>
            <th>RVOL</th>
            <th>Float</th>
            <th>Pillars</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in candidates" :key="c.symbol">
            <td class="sym">{{ c.symbol }}</td>
            <td class="fig">{{ usd(c.price) }}</td>
            <td class="fig" :class="{ sweet: c.gap_sweet_spot }">{{ pct(c.gap_pct) }}</td>
            <td class="fig">{{ pct(c.day_change_pct) }}</td>
            <td class="fig">{{ rvolTxt(c.rvol) }}</td>
            <td class="fig">
              <span class="badge" :class="c.float_badge">{{ floatTxt(c.float_shares) }}</span>
            </td>
            <td class="fig">{{ c.pillars_met }}/3</td>
          </tr>
        </tbody>
      </table>
    </Panel>
  </div>
</template>

<style scoped>
.momentum-view {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}
.banner {
  padding: var(--s2);
  color: var(--ink-dim);
  border-bottom: var(--hair) solid var(--rule-faint);
}
.state {
  padding: var(--s4);
  color: var(--ink-faint);
  text-align: center;
}
.mtable {
  width: 100%;
  border-collapse: collapse;
}
.mtable th {
  text-align: right;
  padding: var(--s2);
  color: var(--ink-faint);
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  border-bottom: var(--hair) solid var(--rule);
}
.mtable th:first-child,
.mtable td.sym {
  text-align: left;
}
.mtable td {
  text-align: right;
  padding: var(--s2);
  border-bottom: var(--hair) solid var(--rule-faint);
  font-variant-numeric: tabular-nums;
}
.mtable td.fig.sweet {
  color: var(--phosphor);
  font-weight: 700;
}
.badge {
  padding: 1px 6px;
  border: var(--hair) solid var(--rule-hi);
  font-size: var(--t-micro);
}
.badge.optimal { color: var(--phosphor); border-color: var(--phosphor-dim); }
.badge.qualifies { color: var(--ink); }
.badge.no { color: var(--ink-faint); }
.badge.unknown { color: var(--ink-ghost); font-style: italic; }
</style>
```

- [ ] **Step 2: Add the router entry**

In `dashboard/src/router.ts`, add immediately after the `changepoints` route (before the `{ path: '/:pathMatch(.*)*', ... }` catch-all):

```typescript
  {
    path: '/momentum',
    name: 'momentum',
    component: () => import('@/views/MomentumView.vue'),
    meta: { title: 'Momentum', index: '14' },
  },
```

- [ ] **Step 3: Add the nav entry**

In `dashboard/src/App.vue`, add to the `nav` array (currently defined at line 21), immediately after the `changepoints` entry:

```typescript
  { name: 'momentum', idx: '14', title: 'Momentum', hint: 'Five Pillars · gap scan' },
```

- [ ] **Step 4: Type-check**

```bash
cd dashboard && npx vue-tsc --noEmit
```

Expected: no new type errors.

- [ ] **Step 5: Manual browser verification**

Start the dashboard dev server (Vite) and the API server (`edge/.venv-qlib/bin/python edge/tools/api_server.py --port 8787 --no-browser`) together. Navigate to `/momentum`. Confirm:
- The nav rail shows a "14 · Momentum" item and it routes correctly.
- The panel renders the banner line with real or honestly-empty universe/float numbers (not "undefined" or a blank).
- If `data/1d_smallcap/` is empty in this environment (Task 2's smoke test only fetched 10 symbols, or wasn't run), the empty state ("0 candidates met...") renders instead of an error — confirms the honest-empty-state path works, not just the happy path.
- No new console errors (`read_console_messages`, `onlyErrors: true`).

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/views/MomentumView.vue dashboard/src/router.ts dashboard/src/App.vue
git commit -m "Add Momentum tab: view, route, and nav entry"
```

---

## Plan Self-Review Notes

- **Spec coverage:** Non-goals (entry/exit/time-of-day/backtesting) — not implemented anywhere, confirmed by omission. Data pipeline (Task 2-4), pillar computation (Task 1), backend (Task 5), frontend (Task 6-7) — each has a task. Failure-behavior requirements from the design doc: partial universe surfaced via manifest `expected_universe_size` (Task 5 Step 3, Task 7 Step 5), float-null never coerced (Task 1 + Task 3 tests), stale-data via existing footer convention (deliberately reused, not reimplemented — no new task needed), zero-candidates honest empty state (Task 7 Step 1 template + Step 5 verification).
- **Type consistency:** `MomentumCandidate`/`MomentumScanPayload` field names in Task 6 match `build_momentum_scan`'s return dict keys from Task 1 exactly (`gap_pct`, `day_change_pct`, `rvol`, `float_shares`, `float_badge`, `gap_sweet_spot`, `*_qualifies`, `pillars_met`, `asof`, `universe_size`, `expected_universe_size`, `float_coverage_pct`, `candidates`) — checked field-by-field against Task 1's `build_candidate`/`build_momentum_scan`.
- **Placeholder scan:** no `TBD`/`TODO`/stub steps remain — every test function asserts a real outcome.
