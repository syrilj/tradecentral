"""Shared pytest fixtures for TradeCentral E2E multi-tier test suites."""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tools import api_server


# --------------------------------------------------------------------------
# Path Constants
# --------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parents[2]
DASHBOARD_SRC = ROOT_DIR / "dashboard" / "src"
TOKENS_CSS = DASHBOARD_SRC / "styles" / "tokens.css"
DESK_VIEW = DASHBOARD_SRC / "views" / "DeskView.vue"
RISK_3D_MODEL = DASHBOARD_SRC / "components" / "RiskNeutral3DModel.vue"
API_TS = DASHBOARD_SRC / "api.ts"


# --------------------------------------------------------------------------
# Direct API Client (In-Memory HTTP Handler Invocation)
# --------------------------------------------------------------------------
class FakeSocket:
    """In-memory socket stream for BaseHTTPRequestHandler dispatch."""
    def __init__(self, request_bytes: bytes):
        self.rfile = io.BytesIO(request_bytes)
        self.wfile = io.BytesIO()

    def makefile(self, mode="r", buffering=None):
        if "r" in mode:
            return self.rfile
        return self.wfile

    def sendall(self, b: bytes):
        self.wfile.write(b)


class FakeServer:
    server_name = "127.0.0.1"
    server_port = 8787


class DirectResponse:
    def __init__(self, status_code: int, headers: dict[str, str], body: bytes):
        self.status_code = status_code
        self.headers = headers
        self.content = body

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class DirectApiClient:
    """Fast, socket-free in-memory client invoking ApiRequestHandler verbatim."""
    def get(self, path: str, headers: dict[str, str] | None = None) -> DirectResponse:
        return self._request("GET", path, headers=headers)

    def post(self, path: str, body: bytes | str = b"", headers: dict[str, str] | None = None) -> DirectResponse:
        if isinstance(body, str):
            body = body.encode("utf-8")
        return self._request("POST", path, body=body, headers=headers)

    def options(self, path: str, headers: dict[str, str] | None = None) -> DirectResponse:
        return self._request("OPTIONS", path, headers=headers)

    def _request(
        self, method: str, path: str, body: bytes = b"", headers: dict[str, str] | None = None
    ) -> DirectResponse:
        hdrs = headers or {}
        hdr_lines = "".join(f"{k}: {v}\r\n" for k, v in hdrs.items())
        raw = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\nContent-Length: {len(body)}\r\n{hdr_lines}\r\n".encode("utf-8") + body
        sock = FakeSocket(raw)
        server = FakeServer()
        api_server.ApiRequestHandler(sock, ("127.0.0.1", 12345), server)  # type: ignore
        sock.wfile.seek(0)
        res_bytes = sock.wfile.read()
        parts = res_bytes.split(b"\r\n\r\n", 1)
        header_part = parts[0].decode("utf-8", errors="replace")
        body_part = parts[1] if len(parts) > 1 else b""
        lines = header_part.split("\r\n")
        status_line = lines[0]
        status_code = int(status_line.split(" ")[1]) if " " in status_line else 500
        res_headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                res_headers[k.strip()] = v.strip()
        return DirectResponse(status_code, res_headers, body_part)


@pytest.fixture(scope="session")
def api_client() -> DirectApiClient:
    """In-memory API client fixture executing ApiRequestHandler directly."""
    return DirectApiClient()


# --------------------------------------------------------------------------
# Sample Data & Generator Fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def sample_symbols() -> list[str]:
    """Standard liquid US equities symbol universe for testing."""
    return ["AAPL", "MSFT", "NVDA", "SPY", "QQQ", "TSLA", "META", "AMZN"]


@pytest.fixture
def mock_daily_frame() -> pd.DataFrame:
    """Deterministic 60-bar OHLCV daily frame with realistic market movement."""
    dates = pd.bdate_range(end=pd.Timestamp.now(tz=None).date(), periods=60)
    np.random.seed(42)
    
    # Geometric Brownian Motion-like price series
    returns = np.random.normal(0.0005, 0.015, size=60)
    close = 150.0 * np.cumprod(1.0 + returns)
    high = close * (1.0 + np.abs(np.random.normal(0.005, 0.005, size=60)))
    low = close * (1.0 - np.abs(np.random.normal(0.005, 0.005, size=60)))
    open_p = low + (high - low) * np.random.uniform(0.2, 0.8, size=60)
    volume = np.random.uniform(5_000_000, 25_000_000, size=60)
    
    df = pd.DataFrame(
        {
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )
    df.index.name = "date"
    return df


@pytest.fixture
def synthetic_parquet_dir(tmp_path: Path, mock_daily_frame: pd.DataFrame) -> Path:
    """Directory populated with synthetic Parquet files for multiple test tickers."""
    syms = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"]
    for i, sym in enumerate(syms):
        df = mock_daily_frame.copy()
        df["close"] = df["close"] * (1.0 + (i * 0.1))
        df["open"] = df["open"] * (1.0 + (i * 0.1))
        df["high"] = df["high"] * (1.0 + (i * 0.1))
        df["low"] = df["low"] * (1.0 + (i * 0.1))
        df.to_parquet(tmp_path / f"{sym}.parquet")
    return tmp_path


@pytest.fixture
def mock_run_context() -> Any:
    """Mock RunContext object with current UTC asof timestamp."""
    return SimpleNamespace(
        asof_utc=datetime.now(timezone.utc),
        market_session="regular",
        mode="live",
    )


@pytest.fixture
def mock_calibrated_model_payload() -> dict:
    """Authoritative valid model payload authorized for entry."""
    return {
        "symbol": "NVDA",
        "side": "long",
        "setup_ok": True,
        "model": {
            "confidence_kind": "calibrated_probability",
            "probability": 0.72,
            "raw_score": 0.68,
            "horizon_days": 10,
            "probability_target": "underlying_directional_return",
            "entry_threshold": 0.65,
            "threshold_version": "v90_wide_isotonic_v1",
            "artifact_sha256": "a" * 64,
            "promotion_authorized": True,
            "reasons": [],
        },
    }


# --------------------------------------------------------------------------
# Frontend File Path Fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def frontend_src_dir() -> Path:
    return DASHBOARD_SRC


@pytest.fixture
def tokens_css_path() -> Path:
    return TOKENS_CSS


@pytest.fixture
def desk_view_path() -> Path:
    return DESK_VIEW


@pytest.fixture
def risk_neutral_3d_path() -> Path:
    return RISK_3D_MODEL


@pytest.fixture
def api_ts_path() -> Path:
    return API_TS
