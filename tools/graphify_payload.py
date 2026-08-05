"""Turn raw `graphify` output (edge/runs/graph/) into a frontend-ready payload.

This module has exactly one public entry point, `build_graph_payload`. It is
pure: given a directory, it reads whatever graphify wrote there (a networkx
node-link `graph.json`, optionally `.graphify_labels.json` and
`index_manifest.json`) and returns a small, JSON-serialisable dict shaped for
a browser-side graph viewer. It never raises — missing or malformed graph
output is reported as `available: False` with a `reason`, never as fabricated
data.

graph.json layout observed from a real run of graphify 0.9.12 (networkx
node-link format):
  {"directed": bool, "multigraph": bool, "graph": {}, "built_at_commit": str,
   "nodes": [{"id": str, "label": str, "community": int, "file_type": str,
              "source_file": str, ...}, ...],
   "links": [{"source": str, "target": str, "relation": str, "weight": float,
              ...}, ...]}
"""
from __future__ import annotations

import json
from pathlib import Path

GRAPH_FILENAME = "graph.json"
LABELS_FILENAME = ".graphify_labels.json"
INDEX_MANIFEST_FILENAME = "index_manifest.json"


def _load_json(path: Path) -> object | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _unavailable(reason: str) -> dict:
    return {
        "available": False,
        "reason": reason,
        "generated_at": None,
        "stats": {"n_nodes": 0, "n_edges": 0, "n_communities": 0, "truncated": False},
        "communities": [],
        "nodes": [],
        "edges": [],
    }


def _label_for_community(labels: dict, community_id: str) -> str:
    value = labels.get(community_id) if isinstance(labels, dict) else None
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, dict):
        for key in ("label", "name", "title"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
    # Matches graphify's own placeholder convention for un-labeled
    # communities (see `graphify cluster-only --no-label`).
    return f"Community {community_id}"


def build_graph_payload(graph_dir: Path, *, max_nodes: int = 400) -> dict:
    graph_dir = Path(graph_dir)

    if not graph_dir.exists() or not graph_dir.is_dir():
        return _unavailable(f"graph directory not found: {graph_dir}")

    graph_path = graph_dir / GRAPH_FILENAME
    if not graph_path.exists():
        return _unavailable(
            f"{GRAPH_FILENAME} not found in {graph_dir} — run graphify_index.py first"
        )

    raw = _load_json(graph_path)
    if raw is None:
        return _unavailable(f"{graph_path} is not valid JSON")
    if not isinstance(raw, dict):
        return _unavailable(f"{graph_path} does not contain a JSON object")

    raw_nodes = raw.get("nodes")
    raw_links = raw.get("links")
    if not isinstance(raw_nodes, list):
        return _unavailable(f"{graph_path} is missing a 'nodes' array")
    if not isinstance(raw_links, list):
        return _unavailable(f"{graph_path} is missing a 'links' array")

    generated_at = None
    manifest = _load_json(graph_dir / INDEX_MANIFEST_FILENAME)
    if isinstance(manifest, dict):
        value = manifest.get("last_indexed_utc")
        if isinstance(value, str):
            generated_at = value

    # --- normalize nodes -------------------------------------------------
    nodes_by_id: dict[str, dict] = {}
    for entry in raw_nodes:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id")
        if raw_id is None:
            continue
        node_id = str(raw_id)
        community = entry.get("community")
        label = entry.get("label")
        if not isinstance(label, str) or not label:
            label = entry.get("norm_label") if isinstance(entry.get("norm_label"), str) else node_id
        source_file = entry.get("source_file")
        nodes_by_id[node_id] = {
            "id": node_id,
            "label": label,
            "community": str(community) if community is not None else "unknown",
            "kind": str(entry.get("file_type") or "unknown"),
            "path": source_file if isinstance(source_file, str) else None,
        }

    # --- normalize edges, keep only well-formed ones with known endpoints --
    all_edges: list[dict] = []
    for entry in raw_links:
        if not isinstance(entry, dict):
            continue
        src = entry.get("source")
        tgt = entry.get("target")
        if src is None or tgt is None:
            continue
        src = str(src)
        tgt = str(tgt)
        if src not in nodes_by_id or tgt not in nodes_by_id:
            continue
        weight = entry.get("weight", 1.0)
        try:
            weight = float(weight)
        except (TypeError, ValueError):
            weight = 1.0
        all_edges.append(
            {
                "source": src,
                "target": tgt,
                "weight": weight,
                "kind": str(entry.get("relation") or "related"),
            }
        )

    # Degree computed over the FULL graph so the top-`max_nodes` ranking
    # reflects true importance rather than an artifact of truncation order.
    degree: dict[str, int] = {node_id: 0 for node_id in nodes_by_id}
    for edge in all_edges:
        degree[edge["source"]] = degree.get(edge["source"], 0) + 1
        degree[edge["target"]] = degree.get(edge["target"], 0) + 1

    all_ids = list(nodes_by_id)
    truncated = len(all_ids) > max_nodes
    if truncated:
        kept_ids = set(sorted(all_ids, key=lambda nid: (-degree.get(nid, 0), nid))[:max_nodes])
    else:
        kept_ids = set(all_ids)

    out_nodes = [
        {**nodes_by_id[node_id], "degree": degree.get(node_id, 0)} for node_id in kept_ids
    ]
    out_nodes.sort(key=lambda n: (-n["degree"], n["id"]))

    # A browser cannot lay out a dangling edge — both endpoints must survive.
    out_edges = [e for e in all_edges if e["source"] in kept_ids and e["target"] in kept_ids]

    # --- communities, derived from the surviving node set only -----------
    community_sizes: dict[str, int] = {}
    for node in out_nodes:
        community_sizes[node["community"]] = community_sizes.get(node["community"], 0) + 1

    labels_raw = _load_json(graph_dir / LABELS_FILENAME)
    labels = labels_raw if isinstance(labels_raw, dict) else {}

    community_ids_sorted = sorted(
        community_sizes, key=lambda cid: (-community_sizes[cid], cid)
    )
    communities = [
        {
            "id": cid,
            "label": _label_for_community(labels, cid),
            "size": community_sizes[cid],
            "color_index": idx,
        }
        for idx, cid in enumerate(community_ids_sorted)
    ]

    stats = {
        "n_nodes": len(out_nodes),
        "n_edges": len(out_edges),
        "n_communities": len(communities),
        "truncated": truncated,
    }

    return {
        "available": True,
        "reason": None,
        "generated_at": generated_at,
        "stats": stats,
        "communities": communities,
        "nodes": out_nodes,
        "edges": out_edges,
    }
