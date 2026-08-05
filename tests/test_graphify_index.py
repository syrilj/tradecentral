from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from edge.tools import graphify_index
from edge.tools.graphify_payload import build_graph_payload


def _write(path: Path, content: str = "x = 1\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_recording_run(returncode: int = 0, stderr: str = ""):
    """Fake subprocess.run: records every invocation, answers --version calls
    and graphify extract/update calls without ever touching a real binary."""
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if len(cmd) > 1 and cmd[1] == "--version":
            return subprocess.CompletedProcess(cmd, 0, stdout="graphify 9.9.9\n", stderr="")
        return subprocess.CompletedProcess(cmd, returncode, stdout="ok\n", stderr=stderr)

    return fake_run, calls


@pytest.fixture
def source_and_graph(tmp_path):
    source_root = tmp_path / "src"
    graph_dir = tmp_path / "graph"
    _write(source_root / "pkg" / "mod.py", "def f():\n    return 1\n")
    return source_root, graph_dir


def test_unchanged_tree_does_not_invoke_graphify(monkeypatch, source_and_graph):
    source_root, graph_dir = source_and_graph
    fake_run, calls = _make_recording_run()
    monkeypatch.setattr(graphify_index.subprocess, "run", fake_run)

    # Prime: first run has no manifest, must do a full index.
    rc = graphify_index.run(source_root=source_root, graph_dir=graph_dir)
    assert rc == 0
    assert calls, "priming run should have invoked graphify"

    calls.clear()
    rc = graphify_index.run(source_root=source_root, graph_dir=graph_dir)
    assert rc == 0
    assert calls == []


def test_one_file_touched_invokes_graphify(monkeypatch, source_and_graph):
    source_root, graph_dir = source_and_graph
    fake_run, calls = _make_recording_run()
    monkeypatch.setattr(graphify_index.subprocess, "run", fake_run)

    graphify_index.run(source_root=source_root, graph_dir=graph_dir)
    calls.clear()

    _write(source_root / "pkg" / "mod.py", "def f():\n    return 2\n")  # content change
    rc = graphify_index.run(source_root=source_root, graph_dir=graph_dir)
    assert rc == 0
    assert calls, "changed file should have triggered a graphify invocation"
    graphify_calls = [c for c in calls if len(c) > 1 and c[1] in ("extract", "update")]
    assert graphify_calls, calls
    assert graphify_calls[0][1] == "update"  # incremental, not a full rebuild


def test_force_invokes_even_when_current(monkeypatch, source_and_graph):
    source_root, graph_dir = source_and_graph
    fake_run, calls = _make_recording_run()
    monkeypatch.setattr(graphify_index.subprocess, "run", fake_run)

    graphify_index.run(source_root=source_root, graph_dir=graph_dir)
    calls.clear()

    rc = graphify_index.run(source_root=source_root, graph_dir=graph_dir, force=True)
    assert rc == 0
    graphify_calls = [c for c in calls if len(c) > 1 and c[1] in ("extract", "update")]
    assert graphify_calls, "force=True must invoke graphify even when nothing changed"
    assert graphify_calls[0][1] == "extract"  # forced -> full rebuild


def test_sensitive_and_junk_paths_excluded_from_scan(tmp_path):
    source_root = tmp_path / "src"
    _write(source_root / "keep.py", "x = 1\n")
    _write(source_root / ".env", "SECRET=abc123\n")
    _write(source_root / "config" / "credentials.json", '{"token": "x"}\n')
    _write(source_root / "config" / "secret_tokens.json", '{"a": "b"}\n')
    _write(source_root / "node_modules" / "pkg" / "index.json", "{}\n")
    _write(source_root / "runs" / "output.json", "{}\n")
    _write(source_root / "data" / "prices.json", "{}\n")
    _write(source_root / "__pycache__" / "mod.cpython-310.json", "{}\n")

    files = graphify_index.scan_source_files(source_root)

    assert set(files) == {"keep.py"}


def test_nonzero_exit_does_not_write_manifest(monkeypatch, source_and_graph):
    source_root, graph_dir = source_and_graph
    fake_run, calls = _make_recording_run()
    monkeypatch.setattr(graphify_index.subprocess, "run", fake_run)

    # First run fails outright: no manifest should ever be written.
    fail_run, _ = _make_recording_run(returncode=3, stderr="boom: extraction blew up")
    monkeypatch.setattr(graphify_index.subprocess, "run", fail_run)
    rc = graphify_index.run(source_root=source_root, graph_dir=graph_dir)
    assert rc != 0
    assert not (graph_dir / graphify_index.MANIFEST_NAME).exists()

    # Now succeed, so a manifest exists, then break a subsequent incremental run.
    monkeypatch.setattr(graphify_index.subprocess, "run", fake_run)
    rc = graphify_index.run(source_root=source_root, graph_dir=graph_dir)
    assert rc == 0
    manifest_path = graph_dir / graphify_index.MANIFEST_NAME
    before = manifest_path.read_text(encoding="utf-8")

    _write(source_root / "pkg" / "mod.py", "def f():\n    return 999\n")
    monkeypatch.setattr(graphify_index.subprocess, "run", fail_run)
    rc = graphify_index.run(source_root=source_root, graph_dir=graph_dir)
    assert rc != 0
    after = manifest_path.read_text(encoding="utf-8")
    assert before == after, "a failed run must never overwrite a good manifest"


def test_corrupt_manifest_falls_back_to_full_rebuild(monkeypatch, source_and_graph):
    source_root, graph_dir = source_and_graph
    graph_dir.mkdir(parents=True)
    (graph_dir / graphify_index.MANIFEST_NAME).write_text("{not valid json", encoding="utf-8")

    fake_run, calls = _make_recording_run()
    monkeypatch.setattr(graphify_index.subprocess, "run", fake_run)

    rc = graphify_index.run(source_root=source_root, graph_dir=graph_dir)
    assert rc == 0
    graphify_calls = [c for c in calls if len(c) > 1 and c[1] in ("extract", "update")]
    assert graphify_calls and graphify_calls[0][1] == "extract"

    # And the manifest is now valid JSON again.
    data = json.loads((graph_dir / graphify_index.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert data["file_count"] == 1


def test_build_graph_payload_missing_dir_returns_unavailable(tmp_path):
    payload = build_graph_payload(tmp_path / "does-not-exist")
    assert payload["available"] is False
    assert isinstance(payload["reason"], str) and payload["reason"]
    assert payload["nodes"] == []
    assert payload["edges"] == []


def test_build_graph_payload_missing_graph_json_returns_unavailable(tmp_path):
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    payload = build_graph_payload(graph_dir)
    assert payload["available"] is False
    assert "graph.json" in payload["reason"]


def test_build_graph_payload_truncates_by_degree(tmp_path):
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()

    n_nodes = 500
    max_nodes = 400
    nodes = [
        {
            "id": f"n{i}",
            "label": f"node {i}",
            "community": i % 7,
            "file_type": "code",
            "source_file": f"pkg/mod{i}.py",
        }
        for i in range(n_nodes)
    ]
    # Give the first 400 nodes higher degree than the rest by chaining them,
    # and add a few edges into the low-degree tail so we can confirm dropped
    # edges never dangle.
    links = []
    for i in range(max_nodes - 1):
        links.append({"source": f"n{i}", "target": f"n{i + 1}", "relation": "calls", "weight": 1.0})
    for i in range(max_nodes, n_nodes):
        links.append({"source": "n0", "target": f"n{i}", "relation": "calls", "weight": 1.0})

    (graph_dir / "graph.json").write_text(
        json.dumps({"nodes": nodes, "links": links}), encoding="utf-8"
    )

    payload = build_graph_payload(graph_dir, max_nodes=max_nodes)

    assert payload["available"] is True
    assert len(payload["nodes"]) == max_nodes
    assert payload["stats"]["n_nodes"] == max_nodes
    assert payload["stats"]["truncated"] is True

    surviving_ids = {n["id"] for n in payload["nodes"]}
    for edge in payload["edges"]:
        assert edge["source"] in surviving_ids
        assert edge["target"] in surviving_ids
