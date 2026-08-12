from __future__ import annotations

from edge.research.squeeze_validation import _hit


def test_missing_forward_return_is_censored_not_counted_as_a_miss() -> None:
    assert _hit(25.0, None, 10.0) is None
    assert _hit(25.0, float("nan"), 10.0) is None
    assert _hit(float("nan"), 0.05, 10.0) is None


def test_hit_uses_direction_only_for_finite_threshold_crossings() -> None:
    assert _hit(25.0, 0.05, 10.0) is True
    assert _hit(25.0, -0.05, 10.0) is False
    assert _hit(-25.0, -0.05, 10.0) is True
    assert _hit(-25.0, 0.05, 10.0) is False
    assert _hit(5.0, 0.05, 10.0) is None
