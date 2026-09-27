import json
from pathlib import Path
import time
from typing import Any

import pytest

from edge.daily_plays.adapters.flow import (
    load_live_flow_activity,
    load_live_forward_flow,
    load_market_flow_activity,
    load_symbol_flow_tape,
    lse_circuit_is_open,
    normalize_flow_payload,
    reset_lse_circuit,
)


@pytest.fixture(autouse=True)
def _reset_lse_circuit():
    reset_lse_circuit()
    yield
    reset_lse_circuit()


def test_market_flow_uses_one_provider_window_and_groups_underlyings():
    calls = 0

    def fetcher(*, min_premium, limit, timeout):
        nonlocal calls
        calls += 1
        assert min_premium == 25_000
        assert limit == 500
        assert timeout == 10
        return [
            {
                "id": "a1", "underlying": "AAA", "contract_type": "call",
                "premium": 100_000, "volume": 10, "ts": "2026-08-11T15:00:00Z",
            },
            {
                "id": "b1", "underlying": "BBB", "contract_type": "put",
                "premium": 200_000, "volume": 20, "ts": "2026-08-11T15:00:01Z",
            },
        ]

    result = load_market_flow_activity(
        fetcher=fetcher,
        min_premium=25_000,
        limit=500,
        timeout_seconds=10,
    )

    assert calls == 1
    assert {row["symbol"] for row in result["rows"]} == {"AAA", "BBB"}
    assert result["coverage"] == {
        "request_completed": 1,
        "provider_prints": 2,
        "observed_symbols": 2,
        "with_activity": 2,
    }


def test_normalizes_live_uoa_alert_as_non_decisive_evidence():
    raw = json.loads((Path(__file__).parent / "fixtures/flow_symbol.json").read_text())
    result = normalize_flow_payload(raw)
    assert result["direction"] == "long"
    assert result["evidence"]["delayed_or_proxy"] is False
    assert result["evidence"]["premium"] == 125000


def test_optional_flow_times_out_without_blocking_scan():
    reset_lse_circuit()

    def slow_fetcher(**_kwargs):
        time.sleep(.1)
        return []

    started = time.monotonic()
    result = load_live_forward_flow("SPY", fetcher=slow_fetcher, timeout_seconds=.01)
    assert time.monotonic() - started < .08
    assert result == {"_evidence_warning": "flow_timeout"}
    reset_lse_circuit()


def test_lse_circuit_opens_after_consecutive_timeouts_and_skips_rest():
    reset_lse_circuit()
    calls = {"n": 0}

    def always_timeout(**_):
        calls["n"] += 1
        time.sleep(0.05)
        return []

    for sym in ("A", "B", "C"):
        out = load_live_forward_flow(sym, fetcher=always_timeout, timeout_seconds=0.01)
        assert out["_evidence_warning"] == "flow_timeout"
    assert lse_circuit_is_open() is True
    # Further calls short-circuit without invoking fetcher.
    before = calls["n"]
    skipped = load_live_forward_flow("D", fetcher=always_timeout, timeout_seconds=0.01)
    assert skipped == {"_evidence_warning": "flow_lse_circuit_open"}
    assert calls["n"] == before
    reset_lse_circuit()
    assert lse_circuit_is_open() is False


def test_live_flow_rejects_provider_page_for_the_wrong_underlying():
    result = load_live_forward_flow(
        "SPY",
        fetcher=lambda **_kwargs: [
            {"underlying": "eq.NVDA", "sentiment": "BULLISH", "premium": 250_000},
            {"symbol": "TSLA", "sentiment": "BEARISH", "premium": 180_000},
        ],
    )
    assert result == {"_evidence_warning": "flow_symbol_mismatch"}


def test_normalization_uses_only_alerts_matching_the_requested_underlying():
    result = normalize_flow_payload(
        {
            "symbol": "SPY",
            "alerts": [
                {"underlying": "NVDA", "sentiment": "BEARISH", "score": 0.99},
                {"underlying": "eq.SPY", "sentiment": "BULLISH", "score": 0.71},
            ],
        }
    )
    assert result["direction"] == "long"
    assert result["evidence"]["alert_count"] == 1
    assert result["evidence"]["score"] == 0.71


def test_actual_lse_prints_are_aggregated_but_remain_direction_neutral():
    result = normalize_flow_payload(
        {
            "symbol": "QQQ",
            "data_source": "lse_live",
            "alerts": [
                {
                    "underlying": "QQQ", "ticker": "QQQ260930P00640000",
                    "contract_type": "put", "premium": 604_572,
                    "volume_today": 100, "ts": "2026-07-30T19:40:57Z",
                },
                {
                    "underlying": "QQQ", "ticker": "QQQ260930C00700000",
                    "contract_type": "call", "premium": 120_000,
                    "volume_today": 20, "ts": "2026-07-30T19:39:00Z",
                },
            ],
        }
    )
    assert result["direction"] == "neutral"
    assert result["asof_utc"] == "2026-07-30T19:40:57Z"
    assert result["evidence"]["premium"] == 724_572
    assert result["evidence"]["volume"] == 120
    assert result["evidence"]["call_print_count"] == 1
    assert result["evidence"]["put_print_count"] == 1
    assert result["evidence"]["direction_signed"] is False


def test_print_metrics_deduplicate_and_keep_otm_distance_separate_from_share():
    alert = {
        "id": "trade-1", "underlying": "SPY", "contract_type": "call",
        "premium": 200_000, "volume": 20, "price": 100,
        "strike": 600, "underlying_price": 500,
        "expiry": "2026-09-18", "ts": "2026-08-11T15:00:00Z",
    }
    result = normalize_flow_payload({"symbol": "SPY", "alerts": [alert, dict(alert)]})

    assert result["evidence"]["alert_count"] == 1
    assert result["evidence"]["premium"] == 200_000
    assert result["evidence"]["contract_count"] == 20
    assert result["evidence"]["otm_flow_pct"] == 1.0
    assert result["evidence"]["average_otm_pct"] == 0.2
    assert result["evidence"]["premium_basis"] == "provider_contract_tape"
    assert len(result["prints"]) == 1


def test_signed_direction_and_coverage_use_explicit_aggressors_only():
    result = normalize_flow_payload({
        "symbol": "QQQ",
        "alerts": [
            {
                "id": "c1", "underlying": "QQQ", "contract_type": "call",
                "premium": 300_000, "volume": 30, "aggressor": "BUY",
                "ts": "2026-08-11T15:00:00Z",
            },
            {
                "id": "p1", "underlying": "QQQ", "contract_type": "put",
                "premium": 100_000, "volume": 10,
                "ts": "2026-08-11T15:00:01Z",
            },
        ],
    })

    assert result["direction"] == "long"
    assert result["evidence"]["direction_signed"] is True
    assert result["evidence"]["signed_net_premium"] == 300_000
    assert result["evidence"]["signed_premium_coverage"] == 0.75


def test_broad_flow_activity_ranks_routed_names_without_authorizing_direction():
    premiums = {"AAA": 100_000, "BBB": 350_000, "CCC": 0}

    def fetcher(*, symbol, timeout):
        premium = premiums[symbol]
        return [] if premium == 0 else [{
            "underlying": symbol,
            "contract_type": "put",
            "premium": premium,
            "ts": "2026-07-30T19:40:57Z",
        }]

    board = load_live_flow_activity(
        symbols=["AAA", "BBB", "CCC"],
        fetcher=fetcher,
        per_symbol_timeout_seconds=1,
        max_workers=3,
    )
    assert [row["symbol"] for row in board["rows"]] == ["BBB", "AAA"]
    assert board["routing_order"] == ["BBB", "AAA", "CCC"]
    assert board["coverage"] == {
        "requested": 3, "completed": 3, "with_activity": 2, "direction_signed": 0,
    }
    assert all(row["direction"] == "neutral" for row in board["rows"])
    assert all(row["decision_authorized"] is False for row in board["rows"])
    assert board["rows"][0]["evidence"]["activity_lean"] == "bearish"
    assert board["rows"][0]["evidence"]["activity_lean_source"] == "call_put_premium"
    assert board["rows"][0]["evidence"]["activity_lean_label"] == "BEARISH"


def test_market_flow_fail_closed_on_timeout():
    reset_lse_circuit()

    def slow_fetcher(**_kwargs):
        time.sleep(0.1)
        return [{"underlying": "SPY", "premium": 100_000, "contract_type": "call"}]

    result = load_market_flow_activity(
        fetcher=slow_fetcher,
        timeout_seconds=0.01,
    )
    assert result["rows"] == []
    assert result["coverage"]["request_completed"] == 0
    assert result["warnings"] == ["flow_market_timeout"]
    reset_lse_circuit()


def test_market_flow_fail_closed_without_credentials(monkeypatch):
    monkeypatch.delenv("LSE_API_KEY", raising=False)
    result = load_market_flow_activity()
    assert result["rows"] == []
    assert result["warnings"] == ["flow_lse_credential_missing"]
    assert result["coverage"] == {
        "request_completed": 0,
        "provider_prints": 0,
        "observed_symbols": 0,
        "with_activity": 0,
    }


def test_symbol_flow_tape_fail_closed_without_credentials(monkeypatch):
    monkeypatch.delenv("LSE_API_KEY", raising=False)
    result = load_symbol_flow_tape("SPY")
    assert result["symbol"] == "SPY"
    assert result["tape"] == []
    assert result["decision_authorized"] is False
    assert result["feed_status"] == "unavailable"
    assert result["warnings"] == ["flow_lse_credential_missing"]


def test_symbol_flow_tape_filters_window_and_keeps_classification():
    seen = {}

    def fetcher(*, symbol, min_premium, limit, timeout, since, until):
        seen.update(symbol=symbol, since=since, until=until, min_premium=min_premium)
        return [
            {
                "id": "old", "underlying": "NVDA", "contract_type": "call",
                "premium": 90_000, "volume": 10, "strike": 180,
                "underlying_price": 100, "expiry": "2026-08-20",
                "ts": "2026-08-01T14:00:00Z",
            },
            {
                "id": "in", "underlying": "NVDA", "contract_type": "put",
                "premium": 120_000, "volume": 30, "strike": 80,
                "underlying_price": 100, "expiry": "2026-08-20",
                "trade_class": "sweep", "ts": "2026-08-10T15:00:00Z",
            },
            {
                "id": "new", "underlying": "NVDA", "contract_type": "call",
                "premium": 70_000, "volume": 8, "ts": "2026-08-14T16:00:00Z",
            },
        ]

    result = load_symbol_flow_tape(
        "nvda",
        min_premium=25_000,
        since="2026-08-09",
        until="2026-08-10",
        fetcher=fetcher,
    )
    assert seen["symbol"] == "NVDA"
    assert seen["since"] == "2026-08-09"
    assert seen["until"] == "2026-08-10"
    assert result["feed_status"] == "live"
    assert result["print_count"] == 1
    row = result["tape"][0]
    assert row["right"] == "put"
    assert row["is_sweep"] is True
    assert row["is_unusual"] is True
    assert "sweeps" in row["presets"]


def test_symbol_flow_tape_parses_occ_symbol_for_historical_prints() -> None:
    def fetcher(*, symbol: str, min_premium: float, limit: int, timeout: float, since: str | None, until: str | None) -> list[dict[str, Any]]:
        return [
            {
                "id": "occ_print",
                "ticker": "NVDA260821C00120000",
                "premium": 150_000,
                "volume": 50,
                "ts": "2026-08-10T14:30:00Z",
                "underlying_price": 115.0,
            }
        ]

    result = load_symbol_flow_tape("NVDA", min_premium=10_000, fetcher=fetcher)
    assert result["print_count"] == 1
    row = result["tape"][0]
    assert row["symbol"] == "NVDA"
    assert row["right"] == "call"
    assert row["strike"] == 120.0
    assert row["expiry"] == "2026-08-21"
    assert row["contracts"] == 50
    assert row["price"] == 30.0  # 150000 / (50 * 100)


def _amd_print() -> dict[str, Any]:
    return {
        "id": "p1", "underlying": "AMD", "contract_type": "call",
        "premium": 80_000, "volume": 10, "ts": "2026-08-11T15:00:00Z",
    }


def test_symbol_flow_tape_serves_repeat_polls_from_memo_within_ttl():
    calls = {"n": 0}

    def fetcher(*, symbol, min_premium, limit, timeout, since, until):
        calls["n"] += 1
        return [_amd_print()]

    first = load_symbol_flow_tape("amd", fetcher=fetcher)
    second = load_symbol_flow_tape("AMD", fetcher=fetcher)
    assert first["feed_status"] == "live"
    assert second["print_count"] == 1
    assert calls["n"] == 1
    # A different question is a different memo key and must re-fetch.
    third = load_symbol_flow_tape("AMD", min_premium=100_000, fetcher=fetcher)
    assert third["feed_status"] == "live"
    assert calls["n"] == 2


def test_symbol_flow_tape_memoizes_degraded_envelope_for_the_short_ttl():
    calls = {"n": 0}

    def broken_fetcher(**_kwargs):
        calls["n"] += 1
        raise RuntimeError("provider exploded")

    first = load_symbol_flow_tape("AMD", fetcher=broken_fetcher)
    assert first["feed_status"] == "unavailable"
    assert first["tape"] == []
    assert first["warnings"] == ["flow_unavailable:RuntimeError"]
    # The hot failure loop is memoized: the repeat poll does not re-fetch.
    second = load_symbol_flow_tape("AMD", fetcher=broken_fetcher)
    assert second["warnings"] == first["warnings"]
    assert calls["n"] == 1


def test_degraded_memo_does_not_mask_provider_recovery(monkeypatch):
    monkeypatch.setattr(
        "edge.daily_plays.adapters.flow.EDGE_TAPE_DEGRADED_MEMO_TTL", -1.0,
    )

    def broken_fetcher(**_kwargs):
        raise RuntimeError("burst")

    first = load_symbol_flow_tape("AMD", fetcher=broken_fetcher)
    assert first["warnings"] == ["flow_unavailable:RuntimeError"]

    calls = {"n": 0}

    def working_fetcher(**_kwargs):
        calls["n"] += 1
        return [_amd_print()]

    second = load_symbol_flow_tape("AMD", fetcher=working_fetcher)
    assert second["feed_status"] == "live"
    assert second["print_count"] == 1
    assert calls["n"] == 1


class _FakeHttpResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.text = ""

    def json(self):
        return []

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"http {self.status_code}", response=self)


@pytest.fixture
def _lse_vault_burst_limited(monkeypatch):
    """Real-path run: ISO window declines, the vault fallback 429s."""
    import sys as _sys
    import types

    import requests as real_requests

    provider = types.ModuleType("lse_provider")
    provider.LSE_ISO_BASE = "https://iso.invalid"
    provider.get_api_key = lambda: "test-key"
    monkeypatch.setitem(_sys.modules, "lse_provider", provider)
    monkeypatch.setenv("LSE_API_KEY", "test-key")

    stats = {"iso": 0, "vault": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        if str(url).startswith("https://iso.invalid"):
            stats["iso"] += 1
            return _FakeHttpResponse(404)
        stats["vault"] += 1
        return _FakeHttpResponse(429)

    monkeypatch.setattr(real_requests, "get", fake_get)
    return stats


def test_vault_fallback_429_is_burst_rate_limit_not_daily_latch(_lse_vault_burst_limited):
    result = load_symbol_flow_tape("NVDA")
    assert result["feed_status"] == "unavailable"
    assert result["tape"] == []
    assert result["decision_authorized"] is False
    assert result["warnings"] == ["flow_lse_rate_limited"]
    assert _lse_vault_burst_limited == {"iso": 1, "vault": 1}
    # The degraded memo stops the polling storm from re-hitting the vault.
    again = load_symbol_flow_tape("NVDA")
    assert again["warnings"] == ["flow_lse_rate_limited"]
    assert _lse_vault_burst_limited == {"iso": 1, "vault": 1}


def test_market_vault_429_has_its_own_rate_limit_warning(_lse_vault_burst_limited):
    result = load_market_flow_activity()
    assert result["rows"] == []
    assert result["coverage"]["request_completed"] == 0
    assert result["warnings"] == ["flow_market_lse_rate_limited"]


def test_render_names_vault_burst_rate_limit_for_operators():
    from edge.daily_plays.render import render_report

    report = render_report({"status": "COMPLETE", "decision_blockers": ["flow_lse_rate_limited"]})
    assert "burst rate limit" in report

