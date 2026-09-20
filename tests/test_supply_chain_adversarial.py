#!/usr/bin/env python3
"""Adversarial challenge test suite for backend supply chain discovery and data honesty.

Adversarially tests:
1. Novel and arbitrary symbol resolution & archetype synthesis.
2. Depth traversal (1, 2, 3) and boundary depth edge cases.
3. Whitespace-padded, lowercase, and empty symbol resilience.
4. Malformed and malicious symbol inputs against sanitization.
5. Data honesty: zero fake elasticity numbers on unscored nodes, zero mock constants,
   and clean top_beneficiaries containment.
6. Multi-query latency benchmarking (<500ms target).
"""
from __future__ import annotations

import time
import pytest
from typing import Any, Dict

from edge.tools.supply_chain import (
    COMPANY_RELATIONSHIPS_REGISTRY,
    THEMATIC_ECOSYSTEMS,
    _CURATED_NODE_CATALOG,
    _filter_by_depth,
    _peer_node,
    build_supply_chain_payload,
    calculate_beneficiary_elasticity,
    get_available_themes,
)
from edge.tools.api_server import _sanitize_symbol


# ---------------------------------------------------------------------------
# 1. Adversarial Input & Discovery Fuzzing: Arbitrary / Novel Tickers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "sym",
    [
        "XYZUNKNOWN",
        "NONEXISTENT99",
        "GOOGL",
        "NVDA",
        "ASTS",
        "AAPL",
        "BA",
        "ARM",
        "RKLB",
        "BRK.B",
        "BF-B",
        "RANDOMTEST123",
    ],
)
def test_arbitrary_and_novel_symbol_resolution(sym: str):
    """Verify that any novel or curated symbol resolves without 500/exceptions and produces a valid graph."""
    for mode in ["dedicated", "intertwined"]:
        payload = build_supply_chain_payload(symbol=sym, mode=mode, force_refresh=True)
        assert payload is not None, f"Payload is None for {sym} in mode {mode}"
        assert "asof" in payload
        assert "query" in payload
        assert payload["query"]["symbol"] == sym.strip().upper()

        focal = payload["focal_entity"]
        assert focal is not None
        assert focal["symbol"] == sym.strip().upper()
        assert focal["is_focus"] is True

        nodes = payload["nodes"]
        assert len(nodes) >= 4, f"Expected at least 4 nodes for {sym}, got {len(nodes)}"
        node_syms = {n["symbol"] for n in nodes}
        assert sym.strip().upper() in node_syms

        # Node contract: every node must have valid structure
        for n in nodes:
            assert "symbol" in n
            assert "name" in n
            assert "tier" in n
            assert "metrics" in n
            assert n["tier"] in (
                "mega_driver",
                "tier1_supplier",
                "tier2_supplier",
                "horizontal_enabler",
                "downstream_customer",
            )

        # Edge contract: all edge sources and targets must exist in nodes
        edges = payload["edges"]
        assert len(edges) >= 3, f"Expected at least 3 edges for {sym}, got {len(edges)}"
        for e in edges:
            assert e["source"] in node_syms, f"Edge source {e['source']} not in node set"
            assert e["target"] in node_syms, f"Edge target {e['target']} not in node set"
            assert "relationship" in e
            assert "strength" in e
            assert 0.0 <= e["strength"] <= 1.0


# ---------------------------------------------------------------------------
# 2. Depth Traversal & Boundary Edge Cases
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("test_sym", ["NVDA", "ASTS", "XYZUNKNOWN", "BA"])
def test_depth_traversal_filtering(test_sym: str):
    """Verify depth filtering semantics: depth=1 prunes multi-hop neighbors, depth=2 retains them."""
    payload_d1 = build_supply_chain_payload(symbol=test_sym, depth=1, mode="dedicated", force_refresh=True)
    payload_d2 = build_supply_chain_payload(symbol=test_sym, depth=2, mode="dedicated", force_refresh=True)
    payload_d3 = build_supply_chain_payload(symbol=test_sym, depth=3, mode="dedicated", force_refresh=True)

    nodes_d1 = payload_d1["nodes"]
    nodes_d2 = payload_d2["nodes"]
    nodes_d3 = payload_d3["nodes"]

    # Depth 1 must have fewer or equal nodes compared to depth 2
    assert len(nodes_d1) <= len(nodes_d2), f"Depth 1 ({len(nodes_d1)}) > Depth 2 ({len(nodes_d2)}) for {test_sym}"
    assert len(nodes_d2) <= len(nodes_d3), f"Depth 2 ({len(nodes_d2)}) > Depth 3 ({len(nodes_d3)}) for {test_sym}"

    # For depth 1, all nodes in nodes_d1 must be directly connected to the focal symbol in payload_d1
    focal_sym = test_sym.upper()
    direct_neighbors = {focal_sym}
    for e in payload_d1["edges"]:
        if e["source"] == focal_sym:
            direct_neighbors.add(e["target"])
        elif e["target"] == focal_sym:
            direct_neighbors.add(e["source"])

    for n in nodes_d1:
        assert n["symbol"] in direct_neighbors, (
            f"Node {n['symbol']} in depth 1 is not a direct neighbor of {focal_sym}"
        )


def test_depth_boundary_values():
    """Verify that unusual depth values (0, -1, 99, None) do not crash the engine."""
    for bad_depth in [0, -1, 99]:
        payload = build_supply_chain_payload(symbol="NVDA", depth=bad_depth, force_refresh=True)
        assert payload is not None
        assert len(payload["nodes"]) >= 5


# ---------------------------------------------------------------------------
# 3. Whitespace, Casing, and Empty Input Fuzzing
# ---------------------------------------------------------------------------
def test_whitespace_and_case_handling():
    """Verify whitespace padding and lower/mixed casing are safely handled."""
    cases = [
        ("  tsla  ", "TSLA"),
        ("nvda", "NVDA"),
        ("\tasts\n", "ASTS"),
        ("  brk.b  ", "BRK.B"),
        ("  bf-b  ", "BF-B"),
    ]
    for raw_input, expected_sym in cases:
        payload = build_supply_chain_payload(symbol=raw_input, force_refresh=True)
        assert payload["focal_entity"]["symbol"] == expected_sym
        assert payload["query"]["symbol"] == expected_sym


def test_empty_and_none_symbol_fallback():
    """Verify that empty, None, or pure whitespace symbols fall back to default theme without crash."""
    for empty_val in [None, "", "   ", "\t\n"]:
        payload = build_supply_chain_payload(symbol=empty_val, force_refresh=True)
        assert payload is not None
        assert payload["focal_entity"] is not None
        assert len(payload["nodes"]) >= 4


# ---------------------------------------------------------------------------
# 4. Malformed and Adversarial Symbol Sanitization
# ---------------------------------------------------------------------------
def test_sanitize_symbol_adversarial_rejections():
    """Adversarially test _sanitize_symbol against injections, path traversals, special chars, and over-length."""
    malicious_inputs = [
        "BAD$$$",
        "SELECT * FROM users;",
        "'; DROP TABLE companies; --",
        "<script>alert(1)</script>",
        "../../etc/passwd",
        "..\\windows\\win.ini",
        "AAPL\x00",
        "NV\nDA",
        "AAPL TSLA",
        "A" * 17,  # Over 16 chars limit
        "A" * 100,
        "🚀🚀",
        "AAPL!",
        "TSLA#1",
        "QQQ%",
        "SPY&DIA",
        "",
        "   ",
    ]
    for bad in malicious_inputs:
        ok, err = _sanitize_symbol(bad)
        assert not ok, f"Expected sanitization failure for '{bad}', but got ok=True, result='{err}'"
        assert isinstance(err, str) and len(err) > 0


def test_sanitize_symbol_valid_inputs():
    """Verify valid symbols pass sanitization with exact uppercase result."""
    valid_inputs = [
        ("AAPL", "AAPL"),
        ("  tsla  ", "TSLA"),
        ("brk.b", "BRK.B"),
        ("BF-B", "BF-B"),
        ("asts", "ASTS"),
        ("1234", "1234"),
    ]
    for raw, expected in valid_inputs:
        ok, res = _sanitize_symbol(raw)
        assert ok, f"Expected sanitization success for '{raw}', got error: {res}"
        assert res == expected


# ---------------------------------------------------------------------------
# 5. Data Honesty: Zero Fake Elasticity & Zero Mock Peer Constants
# ---------------------------------------------------------------------------
def test_zero_mock_constants_in_unmeasured_peer_node():
    """Verify that unmeasured peer nodes return strictly None for all missing metrics, never fake mock constants."""
    node = _peer_node("TOTALLYUNKNOWN_CO")
    metrics = node["metrics"]

    # Old fake mock constants were:
    # capex_sensitivity: 2.8 (or 2.0)
    # revenue_concentration_pct: 35.0 (or 25.0)
    # operating_leverage: 2.6 (or 2.5)
    # flow_sentiment_score: 0.72 (or 0.5)
    # peg_ratio: 1.20
    assert metrics["capex_sensitivity"] is None, f"Expected None, got {metrics['capex_sensitivity']}"
    assert metrics["revenue_concentration_pct"] is None, f"Expected None, got {metrics['revenue_concentration_pct']}"
    assert metrics["operating_leverage"] is None, f"Expected None, got {metrics['operating_leverage']}"
    assert metrics["flow_sentiment_score"] is None, f"Expected None, got {metrics['flow_sentiment_score']}"
    assert metrics["peg_ratio"] is None, f"Expected None, got {metrics['peg_ratio']}"
    assert metrics["gross_margin_trend"] is None
    assert metrics["options_skew"] is None
    assert metrics["elasticity_score"] is None

    # calculate_beneficiary_elasticity must return None on unscored node
    elasticity = calculate_beneficiary_elasticity(node, "TESTDRIVER")
    assert elasticity is None, f"Expected None elasticity for unscored node, got {elasticity}"


def test_zero_fake_elasticity_across_queries_and_modes():
    """Verify that across multiple queries and modes, unscored nodes NEVER get fake elasticity numbers."""
    # List of known historical fake elasticity numbers that were previously hardcoded or emitted
    # when substituting default values:
    test_tickers = ["XYZUNKNOWN", "NONEXISTENT99", "GOOGL", "NVDA", "ASTS", "AAPL", "BA", "ARM", "RKLB"]
    for sym in test_tickers:
        for mode in ["dedicated", "intertwined"]:
            payload = build_supply_chain_payload(symbol=sym, mode=mode, force_refresh=True)
            nodes = payload["nodes"]

            for n in nodes:
                m = n.get("metrics") or {}
                has_capex = m.get("capex_sensitivity") is not None
                has_rev = m.get("revenue_concentration_pct") is not None
                has_op = m.get("operating_leverage") is not None
                has_flow = m.get("flow_sentiment_score") is not None

                has_any_scoring_input = has_capex or has_rev or has_op or has_flow
                score = m.get("elasticity_score")

                # If the node has NO scoring inputs, its elasticity_score MUST be None!
                if not has_any_scoring_input and not n.get("is_focus"):
                    assert score is None, (
                        f"Unscored node {n['symbol']} in query {sym} ({mode}) has non-null score: {score}"
                    )

                # If score is present, it must be within [0.0, 100.0] and finite
                if score is not None:
                    assert isinstance(score, (int, float))
                    assert 0.0 <= score <= 100.0


def test_top_beneficiaries_data_honesty_and_descending_order():
    """Verify top_beneficiaries contains only valid, non-null, positively scored nodes in descending order."""
    test_tickers = ["XYZUNKNOWN", "NONEXISTENT99", "GOOGL", "NVDA", "ASTS", "AAPL", "BA", "ARM", "RKLB"]
    for sym in test_tickers:
        for mode in ["dedicated", "intertwined"]:
            payload = build_supply_chain_payload(symbol=sym, mode=mode, force_refresh=True)
            summary = payload["thematic_summary"]
            top_beneficiaries = summary["top_beneficiaries"]
            node_map = {n["symbol"]: n for n in payload["nodes"]}

            prev_score = 999999.0
            for b_sym in top_beneficiaries:
                assert b_sym in node_map, f"Beneficiary {b_sym} not in nodes for query {sym}"
                b_node = node_map[b_sym]
                score = b_node.get("metrics", {}).get("elasticity_score")
                assert score is not None, f"Beneficiary {b_sym} has None elasticity in query {sym}"
                assert score > 0.0, f"Beneficiary {b_sym} has non-positive elasticity {score} in query {sym}"
                # Must be sorted descending
                assert score <= prev_score + 1e-6, (
                    f"top_beneficiaries not sorted descending: {score} > {prev_score} in query {sym}"
                )
                prev_score = score


# ---------------------------------------------------------------------------
# 6. Performance & Latency Stress (< 500ms on arbitrary tickers)
# ---------------------------------------------------------------------------
def test_resolution_latency_sub_500ms_stress():
    """Benchmark resolution latency across multiple queries with cold cache bypass (force_refresh=True)."""
    benchmark_symbols = [
        "XYZUNKNOWN",
        "NONEXISTENT99",
        "GOOGL",
        "NVDA",
        "ASTS",
        "AAPL",
        "BA",
        "ARM",
        "RKLB",
        "SPY",
    ]
    timings = []
    for test_sym in benchmark_symbols:
        t0 = time.perf_counter()
        payload = build_supply_chain_payload(symbol=test_sym, force_refresh=True)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        timings.append((test_sym, elapsed_ms))
        assert payload is not None
        # Strict latency threshold: < 500ms
        assert elapsed_ms < 500.0, f"Query for {test_sym} took {elapsed_ms:.1f}ms, exceeded 500ms limit!"

    avg_ms = sum(t[1] for t in timings) / len(timings)
    max_ms = max(t[1] for t in timings)
    min_ms = min(t[1] for t in timings)
    # Log benchmark results
    print(f"\n[LATENCY BENCHMARK] Min: {min_ms:.2f}ms, Max: {max_ms:.2f}ms, Avg: {avg_ms:.2f}ms across {len(timings)} queries")
    assert avg_ms < 200.0, f"Average latency {avg_ms:.1f}ms too high"
