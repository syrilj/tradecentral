import json
from pathlib import Path
import time

from edge.daily_plays.adapters.flow import (
    load_live_flow_activity,
    load_live_forward_flow,
    lse_circuit_is_open,
    normalize_flow_payload,
    reset_lse_circuit,
)


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
