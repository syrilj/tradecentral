from datetime import datetime, timezone

from edge.daily_plays.adapters.options import LSEOptionsAdapter, YFinanceOptionsAdapter


ASOF = datetime(2026, 7, 30, 14, 5, tzinfo=timezone.utc)


def _row():
    return {"ticker": "NVDA260821C00180000", "contract_type": "call", "expiry": "2026-08-21",
            "strike": 180, "bid": 4.5, "ask": 5.0, "volume_today": 21, "open_interest": 240,
            "iv": 0.42, "quote_asof_utc": "2026-07-30T14:04:50Z", "multiplier": 100}


def test_lse_adapter_normalizes_injected_live_payload_without_network():
    adapter = LSEOptionsAdapter(fetcher=lambda symbol: {"spot": 175.25, "contracts": [_row()]})
    snapshot = adapter.snapshot("nvda", asof_utc=ASOF)
    contract = snapshot["contracts"][0]
    assert snapshot["provider"] == "lse"
    assert snapshot["degraded"] is False
    assert snapshot["underlying"]["price"] == 175.25
    assert contract["right"] == "call"
    assert contract["occ_symbol"] == "NVDA260821C00180000"
    assert contract["spread_pct"] == 0.10526315789473684
    assert contract["quote_live"] is True
    assert contract["quote_source"] == "lse"
    assert snapshot["capabilities"]["execution_complete_contracts"] == 1


def test_lse_schema_does_not_invent_quote_freshness_multiplier_or_nbbo():
    row = {
        "ticker": "QQQ260918P00640000", "underlying": "QQQ",
        "underlying_price": 683.47, "contract_type": "put",
        "expiry": "2026-09-18", "strike": 640, "last_price": 2.1,
        "last_trade_at": "2026-07-30T19:40:57Z", "volume_today": 120,
        "iv": .28, "delta": -.25, "gamma": .01,
    }
    snapshot = LSEOptionsAdapter(fetcher=lambda _symbol: {"contracts": [row]}).snapshot(
        "QQQ", asof_utc=ASOF
    )
    contract = snapshot["contracts"][0]
    assert snapshot["underlying"]["price"] == 683.47
    assert contract["last_trade_asof_utc"] == "2026-07-30T19:40:57+00:00"
    assert contract["quote_asof_utc"] is None
    assert contract["bid"] is None and contract["ask"] is None
    assert contract["open_interest"] is None
    assert contract["multiplier"] is None
    assert snapshot["capabilities"]["executable_nbbo_available"] is False


def test_yfinance_adapter_is_explicitly_degraded_even_with_complete_fixture():
    adapter = YFinanceOptionsAdapter(fetcher=lambda symbol: {"contracts": [_row()]})
    snapshot = adapter.snapshot("NVDA", asof_utc=ASOF)
    assert snapshot["provider"] == "yfinance"
    assert snapshot["degraded"] is True
    assert snapshot["contracts"][0]["provider"] == "yfinance"
    assert snapshot["contracts"][0]["quote_live"] is False
