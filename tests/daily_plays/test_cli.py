from datetime import datetime, timezone

from edge.daily_plays.cli import run


def test_cli_real_pipeline_parses_json_and_injects_runner(tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_PLAYS_DISABLE_DOTENV", "1")
    monkeypatch.delenv("LSE_API_KEY", raising=False)
    now = datetime(2026, 7, 30, 14, 5, tzinfo=timezone.utc)
    status, result, as_json = run(["today", "--account", "1000", "--json", "--output-root", str(tmp_path)], now=now)
    assert status == 0 and as_json
    # Without the live LSE credential the local baseline may still produce
    # ordinal research rows, but the CLI must remain degraded and non-enterable.
    assert result["mode"] == "degraded"
    assert result["plays"] == []
    assert result["status"] == "NO_PLAY"

    def fake_runner(**kwargs):
        return {"status": "INJECTED", "market_session": "regular", "mode": "replay", "plays": []}

    _, injected, _ = run(["today", "--account", "1000"], runner=fake_runner, now=now)
    assert injected["status"] == "INJECTED"
