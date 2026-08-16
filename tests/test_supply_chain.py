#!/usr/bin/env python3
"""Unit tests for supply chain and thematic beneficiary engine."""
from edge.tools.supply_chain import (
    THEMATIC_ECOSYSTEMS,
    build_supply_chain_payload,
    calculate_beneficiary_elasticity,
    get_available_themes,
)


def test_get_available_themes():
    themes = get_available_themes()
    assert len(themes) >= 8
    theme_ids = {t["id"] for t in themes}
    assert "ai_datacenter" in theme_ids
    assert "space_defense" in theme_ids
    assert "semi_equipment" in theme_ids
    assert "energy_grid" in theme_ids
    assert "agentic_software" in theme_ids
    assert "glp1_cdmo" in theme_ids
    assert "robotics_ai" in theme_ids
    assert "quantum_computing" in theme_ids

    space_theme = next(t for t in themes if t["id"] == "space_defense")
    assert "Space" in space_theme["theme_name"]
    assert len(space_theme["top_beneficiaries"]) > 0


def test_space_defense_ecosystem():
    payload = build_supply_chain_payload(theme="space_defense", depth=2)
    assert payload["focal_entity"]["symbol"] == "ASTS"
    symbols = {n["symbol"] for n in payload["nodes"]}
    assert "ASTS" in symbols
    assert "RKLB" in symbols
    assert "LUNR" in symbols
    assert "RDW" in symbols
    assert "T" in symbols
    assert "VZ" in symbols

    # Check edges
    edges = payload["edges"]
    asts_att = next((e for e in edges if e["source"] == "ASTS" and e["target"] == "T"), None)
    assert asts_att is not None


def test_glp1_cdmo_ecosystem():
    payload = build_supply_chain_payload(theme="glp1_cdmo", depth=2)
    assert payload["focal_entity"]["symbol"] == "LLY"
    symbols = {n["symbol"] for n in payload["nodes"]}
    assert "LLY" in symbols
    assert "NVO" in symbols
    assert "WST" in symbols
    assert "VKTX" in symbols


def test_build_supply_chain_payload_default():
    payload = build_supply_chain_payload(theme="ai_datacenter", depth=2)
    assert payload is not None
    assert "asof" in payload
    assert payload["query"]["theme"] == "ai_datacenter"
    assert payload["query"]["symbol"] == "NVDA"
    assert payload["focal_entity"]["symbol"] == "NVDA"
    assert payload["focal_entity"]["is_focus"] is True

    # Validate nodes and specific beneficiaries (AAOI, LITE, MU, VRT)
    symbols = {n["symbol"] for n in payload["nodes"]}
    assert "AAOI" in symbols
    assert "LITE" in symbols
    assert "MU" in symbols
    assert "VRT" in symbols
    assert "CEG" in symbols
    assert "COHR" in symbols

    # Check node metrics structure
    aaoi = next(n for n in payload["nodes"] if n["symbol"] == "AAOI")
    assert aaoi["metrics"]["elasticity_score"] > 80.0
    assert aaoi["metrics"]["capex_sensitivity"] > 3.0
    assert aaoi["metrics"]["revenue_concentration_pct"] > 30.0
    assert len(aaoi["evidence"]) >= 1
    assert aaoi["evidence"][0]["quote"] is not None

    # Check edges
    edges = payload["edges"]
    assert len(edges) > 5
    aaoi_edge = next((e for e in edges if e["source"] == "AAOI" and e["target"] == "NVDA"), None)
    assert aaoi_edge is not None
    assert aaoi_edge["relationship"] == "supplies_to"


def test_build_supply_chain_payload_custom_focus():
    payload = build_supply_chain_payload(symbol="MU", theme="ai_datacenter", depth=2)
    assert payload["focal_entity"]["symbol"] == "MU"
    assert payload["focal_entity"]["is_focus"] is True

    # Validate thematic summary
    summary = payload["thematic_summary"]
    assert "top_beneficiaries" in summary
    assert len(summary["top_beneficiaries"]) > 0


def test_expanded_ecosystem_inventory():
    """Every theme should carry a meaningful multi-tier member set and valid edges."""
    expected_min_nodes = {
        "ai_datacenter": 15,
        "space_defense": 12,
        "semi_equipment": 10,
        "energy_grid": 10,
        "agentic_software": 9,
        "glp1_cdmo": 10,
        "robotics_ai": 8,
        "quantum_computing": 8,
    }
    for theme_id, min_nodes in expected_min_nodes.items():
        eco = THEMATIC_ECOSYSTEMS[theme_id]
        nodes = eco["nodes"]
        symbols = {n["symbol"] for n in nodes}
        assert len(nodes) >= min_nodes, theme_id
        assert len(symbols) == len(nodes), f"duplicate node symbols in {theme_id}"
        # Every edge must reference real nodes in the same ecosystem.
        for edge in eco["edges"]:
            assert edge["source"] in symbols, (theme_id, edge)
            assert edge["target"] in symbols, (theme_id, edge)
        # Every non-focus node must carry evidence and metrics.
        for node in nodes:
            assert node["metrics"]["elasticity_score"] > 0
            assert len(node["evidence"]) >= 1

    # Spot-check newly added member plays across themes.
    ai = {n["symbol"] for n in THEMATIC_ECOSYSTEMS["ai_datacenter"]["nodes"]}
    assert {"ALAB", "FN", "MRVL", "ANET", "SMCI", "VST", "ETN", "GEV"} <= ai

    space = {n["symbol"] for n in THEMATIC_ECOSYSTEMS["space_defense"]["nodes"]}
    assert {"LMT", "NOC", "KTOS", "HEI", "PL", "IRDM", "GSAT", "SATL", "BKSY"} <= space

    semi = {n["symbol"] for n in THEMATIC_ECOSYSTEMS["semi_equipment"]["nodes"]}
    assert {"LRCX", "CAMT", "FORM", "ONTO", "ACLS", "ENTG", "TER", "COHU"} <= semi

    energy = {n["symbol"] for n in THEMATIC_ECOSYSTEMS["energy_grid"]["nodes"]}
    assert {"VST", "TLN", "SMR", "CCJ", "LEU", "BWXT", "ETN", "PWR", "GEV", "NEE", "UEC"} <= energy

    software = {n["symbol"] for n in THEMATIC_ECOSYSTEMS["agentic_software"]["nodes"]}
    assert {"SNOW", "CRWD", "PANW", "NET", "DDOG", "NOW", "ESTC", "CFLT", "GTLB"} <= software

    glp1 = {n["symbol"] for n in THEMATIC_ECOSYSTEMS["glp1_cdmo"]["nodes"]}
    assert {"CTLT", "STE", "TMO", "DHR", "ALT", "AMGN", "PFE", "AZN"} <= glp1

    robotics = {n["symbol"] for n in THEMATIC_ECOSYSTEMS["robotics_ai"]["nodes"]}
    assert {"ISRG", "ROK", "SERV", "NVDA", "TER", "ZBRA"} <= robotics

    quantum = {n["symbol"] for n in THEMATIC_ECOSYSTEMS["quantum_computing"]["nodes"]}
    assert {"QBTS", "QUBT", "HON", "MSFT", "GOOGL", "NVDA", "ARQQ"} <= quantum


def test_calculate_beneficiary_elasticity():
    node = {
        "metrics": {
            "capex_sensitivity": 4.0,
            "revenue_concentration_pct": 50.0,
            "operating_leverage": 4.0,
            "flow_sentiment_score": 0.9,
        }
    }
    score = calculate_beneficiary_elasticity(node, "NVDA")
    assert 85.0 <= score <= 100.0


def test_dynamic_ingest_arbitrary_ticker():
    payload = build_supply_chain_payload(symbol="ASTS", theme="ai_datacenter", force_refresh=True)
    assert payload["focal_entity"]["symbol"] == "ASTS"
    assert payload["focal_entity"]["is_focus"] is True
    assert len(payload["focal_entity"]["evidence"]) > 0
    assert payload["focal_entity"]["metrics"]["elasticity_score"] > 50.0

    # Ensure dynamic edge was generated linking ASTS to driver
    symbols = {n["symbol"] for n in payload["nodes"]}
    assert "ASTS" in symbols
    asts_edges = [e for e in payload["edges"] if e["source"] == "ASTS" or e["target"] == "ASTS"]
    assert len(asts_edges) >= 1


def test_discover_company_graph_builds_real_peers():
    """Live ingest must discover a real peer graph, not a single fake edge."""
    from edge.tools.supply_chain import _discover_company_graph

    discovered = _discover_company_graph("CRM")
    assert discovered["focal"]["symbol"] == "CRM"
    assert discovered["focal"]["is_focus"] is True
    assert discovered["peer_count"] >= 1
    assert len(discovered["nodes"]) == discovered["peer_count"]
    # Every discovered edge is an honest sector-peer link to the focal node.
    assert all(e["relationship"] == "peer" for e in discovered["edges"])
    assert all(e["source"] == "CRM" for e in discovered["edges"])


def test_depth_filter_and_related_themes():
    """Depth=1 must prune the graph; summaries must expose related themes."""
    full = build_supply_chain_payload(theme="ai_datacenter", depth=2, force_refresh=True)
    direct = build_supply_chain_payload(theme="ai_datacenter", depth=1, force_refresh=True)
    assert len(direct["nodes"]) < len(full["nodes"])
    assert len(direct["edges"]) < len(full["edges"])

    # Related themes are derived from shared tickers, not hardcoded.
    related = full["thematic_summary"]["related_themes"]
    assert isinstance(related, list)
    for rel in related:
        assert rel["id"] in THEMATIC_ECOSYSTEMS
        assert rel["shared_tickers"]

    # Ecosystem market cap is aggregated from member nodes.
    assert full["thematic_summary"]["total_ecosystem_market_cap_b"] > 0

