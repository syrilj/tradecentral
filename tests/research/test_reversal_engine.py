"""Live reversal read: payload shape and the no-probability-without-a-pass rule."""

from __future__ import annotations

import numpy as np
import pandas as pd

from edge.research import reversal_engine as engine
from edge.research import reversal_study as study


def _daily(n: int = 700, seed: int = 3, drift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-04", periods=n)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.015, n) + 0.01 * np.sin(np.arange(n) / 25.0)))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 0.008, n)) * close
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + spread,
            "low": np.minimum(open_, close) - spread,
            "close": close,
            "volume": rng.lognormal(15, 0.3, n),
        },
        index=idx,
    )


def _summary(passes: bool) -> dict:
    side = {
        "base_test": {"rate": 0.33},
        "signals": [{"key": k, "test": {"rate": 0.34, "n": 100, "lift": 0.01, "lo": -0.02, "hi": 0.04}} for k in study.BINARY],
        "model": {"passes": passes, "test_auc": {"auc": 0.51, "lo": 0.49, "hi": 0.53}, "chosen": "logit_all"},
        "lag": None,
    }
    return {"version": 2, "sides": {"bottom": side, "top": side}, "trades": {"bottom": [], "top": []}}


class _Const:
    def predict(self, X):
        return np.full(len(X), 0.61)


def test_probability_withheld_when_model_fails(monkeypatch):
    monkeypatch.setattr(engine, "load_artifacts", lambda tf: (_summary(False), {"bottom": _Const(), "top": _Const()}))
    bars = _daily()
    p = engine.read_symbol("TEST", bars, bars, _daily(seed=9), "1d", source="synthetic", breadth=None)
    assert p["measurable"]
    for side in ("bottom", "top"):
        assert p["reads"][side]["probability"] is None
        assert "did not pass" in p["reads"][side]["probability_reason"]
    assert "breadth_below" in p["missing_context"]


def test_probability_shown_only_when_model_passes(monkeypatch):
    monkeypatch.setattr(engine, "load_artifacts", lambda tf: (_summary(True), {"bottom": _Const(), "top": _Const()}))
    bars = _daily()
    p = engine.read_symbol("TEST", bars, bars, _daily(seed=9), "1d", source="synthetic", breadth=None)
    assert p["reads"]["bottom"]["probability"] == 0.61
    assert p["reads"]["bottom"]["probability_reason"] is None


def test_no_artifact_means_nothing_measured(monkeypatch):
    monkeypatch.setattr(engine, "load_artifacts", lambda tf: (None, None))
    bars = _daily()
    p = engine.read_symbol("TEST", bars, bars, _daily(seed=9), "1d", source="synthetic", breadth=None)
    assert p["study"]["available"] is False
    read = p["reads"]["bottom"]
    assert read["probability"] is None
    assert all(s["measured_edge"] == "unmeasured" and s["test_rate"] is None for s in read["signals"])
    assert len(p["chart"]) == engine.CHART_BARS["1d"]


def test_short_history_refuses():
    bars = _daily(n=120)
    p = engine.read_symbol("TEST", bars, bars, bars, "1d", source="synthetic")
    assert p["measurable"] is False
    assert "need" in p["reason"]
