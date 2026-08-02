"""Tests for edge.research.reporting -- gate docs rendered from artifact JSON.

The scenario this guards against (edge/docs/STATUS.md:21, :113): a result
document that announces GO with figures matching no artifact
(GATE_XS3_RESULT.md, GATE_PEAD_RESULT.md, both retracted). The required
coverage, called out explicitly in the P1-1 task: metric present -> renders
with source; metric ABSENT -> raises; artifact hash mismatch -> raises;
nested/partial artifact -> raises cleanly, not KeyError mid-render.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from edge.research.reporting import (
    ArtifactHashMismatchError,
    ArtifactNotFoundError,
    Figure,
    GateReportSpec,
    MetricNotFoundError,
    ReportingError,
    get_metric,
    has_metric,
    load_artifact,
    render_gate_doc,
    write_gate_doc,
)


def _write_artifact(tmp_path: Path, payload: dict, name: str = "results.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# get_metric / load_artifact
# ---------------------------------------------------------------------------

def test_get_metric_flat_key() -> None:
    assert get_metric({"mean_ic": 0.02}, "mean_ic") == 0.02


def test_get_metric_nested_key_path() -> None:
    artifact = {"metrics": {"rank_ic": {"mean_ic": 0.0052, "icir": 0.0349}}}
    assert get_metric(artifact, "metrics.rank_ic.mean_ic") == 0.0052
    assert get_metric(artifact, "metrics.rank_ic.icir") == 0.0349


def test_get_metric_key_with_punctuation_is_one_segment() -> None:
    """qlib's own report keys are stringified tuples, e.g.
    "('excess_return_with_cost', 'information_ratio')" -- verified against
    edge/runs/qlib_xs3/pitwide.json. Such a key contains no '.', so it is
    exactly one path segment and must be reachable as-is."""
    weird_key = "('excess_return_with_cost', 'information_ratio')"
    artifact = {"metrics": {"portfolio": {"risk": {weird_key: 0.3728}}}}
    assert get_metric(artifact, f"metrics.portfolio.risk.{weird_key}") == 0.3728


def test_get_metric_missing_key_raises_metric_not_found() -> None:
    with pytest.raises(MetricNotFoundError, match="mean_ic"):
        get_metric({"other": 1}, "mean_ic")


def test_get_metric_missing_nested_key_raises_cleanly() -> None:
    """Partial artifact: the outer object exists but the specific figure does
    not. Must raise MetricNotFoundError, not KeyError."""
    artifact = {"metrics": {"rank_ic": {"mean_ic": 0.01}}}
    with pytest.raises(MetricNotFoundError, match="icir"):
        get_metric(artifact, "metrics.rank_ic.icir")


def test_get_metric_descending_into_scalar_raises_cleanly_not_typeerror() -> None:
    """Nested/partial artifact: a path expects an object partway through but
    finds a scalar. Must raise MetricNotFoundError, not TypeError, and the
    message must say where it broke."""
    artifact = {"metrics": {"rank_ic": 0.0052}}  # a float, not an object
    with pytest.raises(MetricNotFoundError, match="metrics.rank_ic"):
        get_metric(artifact, "metrics.rank_ic.mean_ic")


def test_get_metric_descending_into_list_raises_cleanly() -> None:
    artifact = {"horizons": [{"horizon_days": 5}]}
    with pytest.raises(MetricNotFoundError):
        get_metric(artifact, "horizons.horizon_days")


def test_get_metric_empty_key_path_raises() -> None:
    with pytest.raises(MetricNotFoundError):
        get_metric({"a": 1}, "")


def test_has_metric_true_and_false() -> None:
    artifact = {"a": {"b": 1}}
    assert has_metric(artifact, "a.b") is True
    assert has_metric(artifact, "a.c") is False
    assert has_metric(artifact, "z") is False


def test_load_artifact_missing_file_raises() -> None:
    with pytest.raises(ArtifactNotFoundError):
        load_artifact("/does/not/exist/results.json")


def test_load_artifact_returns_data_and_stable_hash(tmp_path: Path) -> None:
    path = _write_artifact(tmp_path, {"a": 1})
    data1, hash1 = load_artifact(path)
    data2, hash2 = load_artifact(path)
    assert data1 == data2 == {"a": 1}
    assert hash1 == hash2
    assert len(hash1) == 64  # sha256 hex digest


def test_load_artifact_hash_changes_when_bytes_change(tmp_path: Path) -> None:
    path = _write_artifact(tmp_path, {"a": 1})
    _, hash1 = load_artifact(path)
    path.write_text(json.dumps({"a": 2}), encoding="utf-8")
    _, hash2 = load_artifact(path)
    assert hash1 != hash2


def test_load_artifact_rejects_non_object_top_level(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ReportingError):
        load_artifact(path)


def test_load_artifact_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ReportingError):
        load_artifact(path)


# ---------------------------------------------------------------------------
# render_gate_doc — the end-to-end contract
# ---------------------------------------------------------------------------

SIMPLE_SPEC = GateReportSpec(
    gate_family="test-family",
    verdict_key_path="verdict",
    figures=(
        Figure(name="mean_ic", key_path="mean_rank_ic", format="ratio4", threshold="> 0.040"),
        Figure(name="net_annual", key_path="net_annual_return_pct", format="pct_already"),
        Figure(
            name="sharpe", key_path="sharpe_ratio", format="ratio2",
            threshold="> 0.60", passed_key_path="gate_checks.sharpe_gt_06",
        ),
    ),
    template=(
        "# Test Gate Result\n\n"
        "Verdict: {verdict_badge}\n"
        "Artifact: `{artifact_path}` (sha256 `{artifact_hash}`)\n"
        "Rendered: {generated_at}\n\n"
        "| Metric | Threshold | Value | Status |\n"
        "|---|---|---|---|\n"
        "| Mean IC | {mean_ic_threshold} | {mean_ic} | - |\n"
        "| Net annual | - | {net_annual} | - |\n"
        "| Sharpe | {sharpe_threshold} | {sharpe} | {sharpe_badge} |\n"
    ),
)


def _pead_like_artifact(**overrides) -> dict:
    base = {
        "mean_rank_ic": 0.041,
        "net_annual_return_pct": 8.5,
        "sharpe_ratio": 0.65,
        "gate_checks": {"sharpe_gt_06": True},
        "verdict": "GO",
    }
    base.update(overrides)
    return base


def test_metric_present_renders_with_source(tmp_path: Path) -> None:
    """The core positive case: every figure the doc contains is sourced from
    the artifact, and the doc names the artifact path + hash."""
    artifact_path = _write_artifact(tmp_path, _pead_like_artifact())
    _, expected_hash = load_artifact(artifact_path)

    doc = render_gate_doc(artifact_path=artifact_path, spec=SIMPLE_SPEC)

    assert "0.0410" in doc  # mean_ic, ratio4
    assert "8.50%" in doc  # net_annual, pct_already
    assert "+0.65" in doc  # sharpe, ratio2
    assert "PASS" in doc
    assert str(artifact_path) in doc
    assert expected_hash in doc
    assert "GO" in doc


def test_metric_absent_raises(tmp_path: Path) -> None:
    """A Figure whose key_path is missing from the artifact must raise, not
    render a blank/None/'N/A'. This is the literal control for the retracted
    docs: a figure that cannot be sourced from an artifact is unrepresentable."""
    artifact_path = _write_artifact(tmp_path, {
        "mean_rank_ic": 0.041,
        "net_annual_return_pct": 8.5,
        # sharpe_ratio intentionally missing
        "gate_checks": {"sharpe_gt_06": True},
        "verdict": "GO",
    })
    with pytest.raises(MetricNotFoundError, match="sharpe_ratio"):
        render_gate_doc(artifact_path=artifact_path, spec=SIMPLE_SPEC)


def test_verdict_missing_raises(tmp_path: Path) -> None:
    artifact_path = _write_artifact(tmp_path, {
        "mean_rank_ic": 0.041, "net_annual_return_pct": 8.5, "sharpe_ratio": 0.65,
        "gate_checks": {"sharpe_gt_06": True},
        # verdict intentionally missing
    })
    with pytest.raises(MetricNotFoundError, match="verdict"):
        render_gate_doc(artifact_path=artifact_path, spec=SIMPLE_SPEC)


def test_artifact_hash_mismatch_raises(tmp_path: Path) -> None:
    """Pinning a stale hash and rendering again must raise -- a doc must not
    silently claim to describe an artifact that has since changed."""
    artifact_path = _write_artifact(tmp_path, _pead_like_artifact())
    _, original_hash = load_artifact(artifact_path)

    # Artifact changes underneath (e.g. someone hand-edits it, or a different
    # run overwrites it) without an intentional re-render.
    artifact_path.write_text(json.dumps(_pead_like_artifact(sharpe_ratio=99.0)), encoding="utf-8")

    with pytest.raises(ArtifactHashMismatchError, match="expected"):
        render_gate_doc(
            artifact_path=artifact_path, spec=SIMPLE_SPEC, expected_artifact_hash=original_hash,
        )


def test_rerender_after_intentional_edit_reflects_new_content(tmp_path: Path) -> None:
    """A plain re-render (no expected hash pinned) must reflect the current
    artifact -- this is what makes 'hand-edit a figure, re-render, confirm
    the doc changes' (the plan's own end-to-end check) possible."""
    artifact_path = _write_artifact(tmp_path, _pead_like_artifact(sharpe_ratio=0.65))
    doc_before = render_gate_doc(artifact_path=artifact_path, spec=SIMPLE_SPEC)
    assert "+0.65" in doc_before

    artifact_path.write_text(json.dumps(_pead_like_artifact(sharpe_ratio=1.23)), encoding="utf-8")
    doc_after = render_gate_doc(artifact_path=artifact_path, spec=SIMPLE_SPEC)
    assert "+1.23" in doc_after
    assert doc_before != doc_after


def test_nested_partial_artifact_raises_cleanly_not_keyerror_mid_render(tmp_path: Path) -> None:
    """A deeply-nested spec where an intermediate level is missing/wrong-typed
    must raise MetricNotFoundError, never a raw KeyError/TypeError bubbling
    out of a half-completed .format() call."""
    nested_spec = GateReportSpec(
        gate_family="nested-test",
        verdict_key_path="verdict",
        figures=(
            Figure(name="mean_ic", key_path="metrics.rank_ic.mean_ic", format="ratio4"),
        ),
        template="Verdict {verdict_badge}: IC {mean_ic}",
    )
    # metrics.rank_ic exists but is a scalar, not an object with mean_ic inside.
    artifact_path = _write_artifact(tmp_path, {"metrics": {"rank_ic": 0.5}, "verdict": "NO-GO"})
    with pytest.raises(MetricNotFoundError) as excinfo:
        render_gate_doc(artifact_path=artifact_path, spec=nested_spec)
    assert "KeyError" not in repr(excinfo.value)
    assert "metrics.rank_ic" in str(excinfo.value)

    # metrics exists but rank_ic is entirely absent.
    artifact_path2 = _write_artifact(tmp_path, {"metrics": {}, "verdict": "NO-GO"}, name="results2.json")
    with pytest.raises(MetricNotFoundError):
        render_gate_doc(artifact_path=artifact_path2, spec=nested_spec)


def test_template_placeholder_with_no_declared_figure_raises_not_silently(tmp_path: Path) -> None:
    """A template bug (typo'd placeholder, or a figure the author forgot to
    declare) must raise, not render a stray literal or crash with a raw
    KeyError."""
    bad_spec = GateReportSpec(
        gate_family="bad-template",
        verdict_key_path="verdict",
        figures=(Figure(name="mean_ic", key_path="mean_rank_ic", format="ratio4"),),
        template="IC={mean_ic} but also {undeclared_typo}",
    )
    artifact_path = _write_artifact(tmp_path, {"mean_rank_ic": 0.01, "verdict": "NO-GO"})
    with pytest.raises(ReportingError, match="undeclared_typo"):
        render_gate_doc(artifact_path=artifact_path, spec=bad_spec)


def test_unknown_format_raises(tmp_path: Path) -> None:
    bad_spec = GateReportSpec(
        gate_family="bad-format",
        verdict_key_path="verdict",
        figures=(Figure(name="x", key_path="x", format="not_a_real_format"),),
        template="{x}",
    )
    artifact_path = _write_artifact(tmp_path, {"x": 1, "verdict": "NO-GO"})
    with pytest.raises(ReportingError, match="not_a_real_format"):
        render_gate_doc(artifact_path=artifact_path, spec=bad_spec)


def test_verdict_badge_go_and_no_go() -> None:
    from edge.research.reporting import _default_verdict_badge
    assert "GO" in _default_verdict_badge("GO")
    assert "NO-GO" in _default_verdict_badge("NO-GO")
    assert "🔴" in _default_verdict_badge("NO-GO") or "NO-GO" in _default_verdict_badge("NO-GO")


def test_write_gate_doc_writes_file_and_creates_parent_dirs(tmp_path: Path) -> None:
    artifact_path = _write_artifact(tmp_path, _pead_like_artifact())
    doc_path = tmp_path / "nested" / "deeper" / "RESULT.md"
    content = write_gate_doc(artifact_path=artifact_path, spec=SIMPLE_SPEC, doc_path=doc_path)
    assert doc_path.exists()
    assert doc_path.read_text(encoding="utf-8") == content
    assert "GO" in content


def test_figure_with_bad_value_for_its_format_raises_reporting_error(tmp_path: Path) -> None:
    """A figure whose artifact value cannot be coerced by its declared
    formatter (e.g. a string where a ratio is expected) must raise a clear
    ReportingError, not propagate a raw ValueError from inside str.format."""
    bad_spec = GateReportSpec(
        gate_family="bad-value",
        verdict_key_path="verdict",
        figures=(Figure(name="x", key_path="x", format="ratio2"),),
        template="{x}",
    )
    artifact_path = _write_artifact(tmp_path, {"x": "not-a-number", "verdict": "NO-GO"})
    with pytest.raises(ReportingError, match="x"):
        render_gate_doc(artifact_path=artifact_path, spec=bad_spec)
