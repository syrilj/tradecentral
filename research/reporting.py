"""Render GATE_*_RESULT.md documents mechanically from run-artifact JSON.

Why this module exists (see edge/docs/STATUS.md:21 and :113): twice, a result
document announced **GO** with figures that "match no artifact" --
`GATE_XS3_RESULT.md` and `GATE_PEAD_RESULT.md`, both retracted. One of them
(`GATE_XS3_RESULT.md:54`) asked to unblock GPU budget on a result that never
happened. In both cases the document was assembled by hand, separately from
whatever run actually produced numbers, so nothing enforced that a figure
printed in the doc corresponded to a figure a run had actually written down.

The fix is structural, not procedural: a gate result document is *rendered*
from an artifact JSON file already sitting on disk. Every figure the renderer
can place in the output text was pulled from that file by an explicit, named
key path (see `get_metric`). A figure with no such key **raises** --
`MetricNotFoundError` -- instead of rendering blank, `None`, or a value the
caller supplied out of band. There is no code path through which a number
that does not exist in the artifact can appear in the rendered doc. That is
the whole point: a claim with no backing artifact must be unrepresentable,
the same design choice `research/portfolio.py` makes for `execution_lag < 1`.

The rendered doc always carries the artifact's path and its sha256 hash (see
`load_artifact`), so any figure in the doc is traceable back to the exact
bytes it came from. Passing `expected_artifact_hash` to `render_gate_doc`
additionally lets a caller *pin* a hash and have a later render raise
(`ArtifactHashMismatchError`) if the artifact underneath has since changed
without an explicit re-render -- catching a doc that has silently drifted
from the artifact it claims to describe. A plain re-render (no expected hash)
always reflects whatever is currently on disk.

Usage pattern (generalizes `build_pead_catalyst_model.py`'s
`generate_gate_pead_result_doc`, which wrote its table by hand from an
in-memory dict immediately after computing it -- safe there only because nothing
could intervene between computing `res` and writing the doc from it; this
module makes that safety structural rather than incidental, so a doc-writer
that reads a possibly-stale or differently-produced artifact gets the same
protection):

    artifact_path = out_dir / "results.json"
    artifact_path.write_text(json.dumps(res, indent=2))
    write_gate_doc(artifact_path=artifact_path, spec=MY_GATE_SPEC, doc_path=doc_path)
"""
from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


class ReportingError(Exception):
    """Base class for every failure mode in this module.

    Every subclass below corresponds to a way a rendered doc could otherwise
    have said something no artifact supports. They are all deliberate: this
    module raises rather than degrading, matching the surrounding style in
    `research/portfolio.py` (`execution_lag < 1` raises, it does not clamp).
    """


class ArtifactNotFoundError(ReportingError):
    """The artifact JSON file the spec was told to render from does not exist."""


class ArtifactHashMismatchError(ReportingError):
    """A pinned `expected_artifact_hash` no longer matches the artifact on disk."""


class MetricNotFoundError(ReportingError):
    """A figure's key path is missing, or descends into a non-object value,
    somewhere in the artifact. Raised instead of KeyError/TypeError so a
    partial or nested artifact fails cleanly with a message that names
    exactly where the lookup broke, not a raw traceback mid-render."""


def load_artifact(path: str | Path) -> tuple[dict[str, Any], str]:
    """Load a run-artifact JSON file and the sha256 hex digest of its exact bytes.

    The hash is the traceability anchor `render_gate_doc` embeds in every
    rendered doc, and the value `expected_artifact_hash` is checked against.
    """
    artifact_path = Path(path)
    if not artifact_path.exists():
        raise ArtifactNotFoundError(f"artifact not found: {artifact_path}")
    raw = artifact_path.read_bytes()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReportingError(f"artifact at {artifact_path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ReportingError(
            f"artifact at {artifact_path} must be a JSON object at the top level, "
            f"got {type(data).__name__}"
        )
    return data, hashlib.sha256(raw).hexdigest()


def get_metric(artifact: Mapping[str, Any], key_path: str) -> Any:
    """Look up a dot-separated key path in a (possibly nested) artifact dict.

    Raises `MetricNotFoundError` -- never `KeyError`/`TypeError` -- for an
    empty path, a missing key at any depth, or a path that tries to descend
    through a non-object (e.g. a number or list) value. This is the single
    enforcement point every figure in a rendered doc passes through.
    """
    if not key_path:
        raise MetricNotFoundError("empty key_path")
    node: Any = artifact
    walked: list[str] = []
    for part in key_path.split("."):
        if not isinstance(node, Mapping):
            raise MetricNotFoundError(
                f"key path {key_path!r} not found: "
                f"{'.'.join(walked) or '<artifact root>'} is a {type(node).__name__}, "
                f"not an object, so {part!r} cannot be looked up inside it"
            )
        if part not in node:
            raise MetricNotFoundError(
                f"key path {key_path!r} not found: no key {part!r} at "
                f"{'.'.join(walked) or '<artifact root>'} "
                f"(available keys there: {sorted(map(str, node.keys()))})"
            )
        node = node[part]
        walked.append(part)
    return node


def has_metric(artifact: Mapping[str, Any], key_path: str) -> bool:
    """Non-raising existence check, for optional figures / conditional sections."""
    try:
        get_metric(artifact, key_path)
        return True
    except MetricNotFoundError:
        return False


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _fmt_pct(value: Any) -> str:
    """A fraction (0.05 -> '5.00%')."""
    return f"{float(value) * 100:.2f}%"


def _fmt_pct1(value: Any) -> str:
    return f"{float(value) * 100:.1f}%"


def _fmt_pct_already(value: Any) -> str:
    """A number that is already a percentage (12.3 -> '12.30%'), not a fraction."""
    return f"{float(value):.2f}%"


def _fmt_ratio2(value: Any) -> str:
    return f"{float(value):+.2f}"


def _fmt_ratio3(value: Any) -> str:
    return f"{float(value):+.3f}"


def _fmt_ratio4(value: Any) -> str:
    return f"{float(value):+.4f}"


def _fmt_int(value: Any) -> str:
    return f"{int(value):,}"


def _fmt_str(value: Any) -> str:
    return str(value)


def _fmt_bool_yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"


# Every formatter is a total function on the raw JSON value it is given --
# it must not itself decide "missing means 0" or similar; missingness is
# handled once, upstream, by get_metric raising.
FORMATTERS: dict[str, Callable[[Any], str]] = {
    "pct": _fmt_pct,
    "pct1": _fmt_pct1,
    "pct_already": _fmt_pct_already,
    "ratio2": _fmt_ratio2,
    "ratio3": _fmt_ratio3,
    "ratio4": _fmt_ratio4,
    "int": _fmt_int,
    "str": _fmt_str,
    "bool": _fmt_bool_yes_no,
}


def _default_verdict_badge(verdict: Any) -> str:
    text = str(verdict).strip().upper()
    if text == "GO":
        return "\U0001f7e2 **GO**"
    if text in {"NO-GO", "NO_GO", "NOGO"}:
        return "\U0001f534 **NO-GO**"
    return f"**{verdict}**"


# ---------------------------------------------------------------------------
# Spec + renderer
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Figure:
    """One number a rendered doc may contain, sourced from exactly one
    artifact key path -- there is no other way for a value to reach the
    template than through this declaration and `get_metric`.

    `threshold`, when set, is inserted as `{name}_threshold` -- free-text
    describing the pre-registered bar (e.g. "> 0.040"), not itself pulled
    from the artifact (the threshold is part of the gate's pre-registration,
    e.g. GATE_PEAD.md / GATE_XS3.md, not a run output).
    `passed_key_path`, when set, must resolve to a bool in the artifact and
    is exposed as `{name}_pass` ("PASS"/"FAIL") and `{name}_badge`.
    """

    name: str
    key_path: str
    format: str = "ratio4"
    threshold: str | None = None
    passed_key_path: str | None = None


@dataclass(frozen=True)
class GateReportSpec:
    """Everything `render_gate_doc` needs to turn one artifact into one doc.

    `template` is a `str.format()`-style template. The only substitutions
    ever available to it are: each `figure.name` in `figures` (plus, where
    declared, `{name}_threshold` / `{name}_pass` / `{name}_badge`), and the
    fixed set `{verdict}`, `{verdict_badge}`, `{artifact_path}`,
    `{artifact_hash}`, `{generated_at}`. A template referencing anything else
    raises at render time rather than rendering a literal `{typo}`.
    """

    gate_family: str
    verdict_key_path: str
    figures: Sequence[Figure]
    template: str
    verdict_badge_fn: Callable[[Any], str] = field(default=_default_verdict_badge)


def _utcnow_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def render_gate_doc(
    *,
    artifact_path: str | Path,
    spec: GateReportSpec,
    expected_artifact_hash: str | None = None,
    generated_at: str | None = None,
) -> str:
    """Render a gate result doc body from an artifact JSON file.

    Raises `MetricNotFoundError` if any `Figure` in `spec.figures` (or
    `spec.verdict_key_path`) names a key path absent from the artifact, at
    any depth -- a metric that cannot be sourced from the artifact must not
    render. Raises `ArtifactHashMismatchError` if `expected_artifact_hash` is
    given and does not match the artifact's current hash.
    """
    artifact, actual_hash = load_artifact(artifact_path)
    if expected_artifact_hash is not None and actual_hash != expected_artifact_hash:
        raise ArtifactHashMismatchError(
            f"{artifact_path} hashes to {actual_hash}, expected {expected_artifact_hash}. "
            "The artifact changed since this hash was pinned. If this is a fresh, "
            "intentional run, re-render without expected_artifact_hash; do not paper "
            "over a doc silently describing a different run than the one it names."
        )

    values: dict[str, str] = {}
    for figure in spec.figures:
        formatter = FORMATTERS.get(figure.format)
        if formatter is None:
            raise ReportingError(
                f"figure {figure.name!r} declares unknown format {figure.format!r}; "
                f"known formats: {sorted(FORMATTERS)}"
            )
        raw_value = get_metric(artifact, figure.key_path)
        try:
            values[figure.name] = formatter(raw_value)
        except (TypeError, ValueError) as exc:
            raise ReportingError(
                f"figure {figure.name!r} (key path {figure.key_path!r}) has value "
                f"{raw_value!r}, which format {figure.format!r} cannot render: {exc}"
            ) from exc
        if figure.threshold is not None:
            values[f"{figure.name}_threshold"] = figure.threshold
        if figure.passed_key_path is not None:
            passed = bool(get_metric(artifact, figure.passed_key_path))
            values[f"{figure.name}_pass"] = "PASS" if passed else "FAIL"
            values[f"{figure.name}_badge"] = "✅ PASS" if passed else "❌ FAIL"

    verdict = get_metric(artifact, spec.verdict_key_path)
    values["verdict"] = str(verdict)
    values["verdict_badge"] = spec.verdict_badge_fn(verdict)
    values["artifact_path"] = str(artifact_path)
    values["artifact_hash"] = actual_hash
    values["generated_at"] = generated_at or _utcnow_iso()

    try:
        return spec.template.format(**values)
    except KeyError as exc:
        raise ReportingError(
            f"template for gate family {spec.gate_family!r} references placeholder "
            f"{exc} that no Figure in spec.figures declares (declared names: "
            f"{sorted(values)}). Add a Figure for it, or fix the template -- a "
            f"template typo must not silently render a blank/literal brace."
        ) from exc


def write_gate_doc(
    *,
    artifact_path: str | Path,
    spec: GateReportSpec,
    doc_path: str | Path,
    expected_artifact_hash: str | None = None,
    generated_at: str | None = None,
) -> str:
    """`render_gate_doc`, then write the result to `doc_path`. Returns the text."""
    content = render_gate_doc(
        artifact_path=artifact_path,
        spec=spec,
        expected_artifact_hash=expected_artifact_hash,
        generated_at=generated_at,
    )
    out_path = Path(doc_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return content
