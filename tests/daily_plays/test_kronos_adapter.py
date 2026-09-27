import json
from pathlib import Path

from edge.daily_plays.adapters.kronos import normalize_kronos_payload


def test_kronos_is_ordinal_research_evidence_only():
    raw = json.loads((Path(__file__).parent / "fixtures/kronos_report.json").read_text())
    result = normalize_kronos_payload(raw)
    assert result["direction"] == "long"
    assert result["research_confidence"]["kind"] == "ordinal_score"
    assert "calibrated_probability" not in result
    assert result["forecast"]["interval_80"] == [175, 195]
