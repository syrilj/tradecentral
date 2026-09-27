from __future__ import annotations

from copy import deepcopy

from edge.daily_plays import lse_budget


def test_iso_quota_latch_is_cleared_when_api_key_changes(monkeypatch):
    original = deepcopy(lse_budget._STATE)
    try:
        monkeypatch.setenv("LSE_API_KEY", "lse_live_old")
        lse_budget._STATE.update(
            {
                "api_key_fingerprint": lse_budget._api_key_fingerprint(),
                "iso_quota_exhausted_month": lse_budget._utc_month(),
                "iso_requests_skipped": 42,
            }
        )
        assert lse_budget.iso_quota_exhausted() is True

        monkeypatch.setenv("LSE_API_KEY", "lse_live_replacement")

        assert lse_budget.iso_quota_exhausted() is False
        assert lse_budget._STATE["iso_quota_exhausted_month"] == ""
        assert lse_budget._STATE["iso_requests_skipped"] == 0
        assert lse_budget._STATE["api_key_fingerprint"] == lse_budget._api_key_fingerprint()
    finally:
        lse_budget._STATE.clear()
        lse_budget._STATE.update(original)
