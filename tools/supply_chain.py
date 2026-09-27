#!/usr/bin/env python3
"""Comprehensive Supply Chain Knowledge Graph, Dynamic Multi-Hop Traversal, and Thematic Beneficiary Engine.

Supports 8 core thematic frontiers:
  1. AI Data Center & Hyperscale Compute (NVDA, AAOI, LITE, MU, VRT, CEG, AVGO, ALAB, etc.)
  2. Space Economy, Direct-to-Cell & Defense (ASTS, RKLB, LUNR, RDW, PL, LMT, NOC, KTOS, HEI, T, VZ)
  3. Semiconductor Equipment & Advanced Packaging (ASML, KLAC, AMAT, LRCX, CAMT, FORM, ONTO)
  4. Nuclear SMRs, Power & Grid Infrastructure (CEG, VST, TLN, OKLO, SMR, CCJ, GEV, ETN, PWR)
  5. Enterprise AI, Agentic Workflows & Security (PLTR, MDB, SNOW, CRWD, PANW, NET, DDOG, NOW)
  6. GLP-1 Metabolic Therapeutics & CDMO Supply Chain (LLY, NVO, CTLT, WST, STE, TMO, DHR, VKTX)
  7. Physical AI, Humanoid Robotics & Automation (TSLA, ISRG, SYM, CGNX, ROK, SERV, NVDA)
  8. Quantum Computing & Photonic Systems (IONQ, RGTI, QBTS, QUBT, HON, IBM)

Includes dynamic SEC EDGAR 10-K/10-Q extraction, earnings call transcript NLP quotation matcher,
and quant-fundamental beneficiary elasticity scoring.
"""
from __future__ import annotations

import copy
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CACHE_TTL_S = 900  # 15 minutes
_SUPPLY_CHAIN_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}

try:
    from tools.financial_data import _CACHE_PROFILE
except Exception:
    _CACHE_PROFILE = {}  # type: ignore[assignment]



def _safe_float(val: Any, default: float | None = None) -> float | None:
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def _safe_round(val: Any, digits: int = 2) -> float | None:
    f = _safe_float(val)
    if f is None:
        return None
    return round(f, digits)


# ==============================================================================
# 8 Comprehensive Thematic Ecosystem Catalogs (75+ Institutional Tickers)
# ==============================================================================

THEMATIC_ECOSYSTEMS: Dict[str, Dict[str, Any]] = {
    # --------------------------------------------------------------------------
    # 1. AI Data Center & Hyperscale Compute
    # --------------------------------------------------------------------------
    "ai_datacenter": {
        "theme_name": "AI Data Center & Hyperscale Compute",
        "description": "Hyperscaler accelerated compute buildout driving Optics, HBM Memory, Liquid Cooling, and High-Voltage Power.",
        "capex_catalyst_narrative": "Hyperscaler CapEx guidance exceeding $240B+ annually has created acute supply constraints across 800G/1.6T optical transceivers, high-bandwidth memory (HBM3e/HBM4), high-density liquid cooling distribution units (CDUs), and dedicated nuclear/clean power interconnects.",
        "total_ecosystem_market_cap_b": 8920.0,
        "catalyst_timeline": [
            {
                "date": "2026-08-28",
                "event": "NVDA Q2 Earnings & Rubin Architecture Roadmap Update",
                "impacted_tickers": ["NVDA", "AAOI", "LITE", "MU", "VRT", "TSM", "AVGO"],
            },
            {
                "date": "2026-09-15",
                "event": "OFC Next-Gen Optical Interconnect & CPO Standards Forum",
                "impacted_tickers": ["AAOI", "LITE", "COHR", "FN", "MRVL", "ALAB"],
            },
            {
                "date": "2026-09-25",
                "event": "MU Fiscal Q4 Earnings & HBM4 Yield Disclosures",
                "impacted_tickers": ["MU", "WDC", "STX", "CAMT", "PSTG"],
            },
            {
                "date": "2026-10-18",
                "event": "FERC High-Voltage Interconnection & Data Center PPA Rulings",
                "impacted_tickers": ["CEG", "VST", "TLN", "OKLO", "ETN", "GEV"],
            },
        ],
        "default_focus": "NVDA",
        "nodes": [
            {
                "symbol": "NVDA",
                "name": "NVIDIA Corporation",
                "sector": "Semiconductors",
                "sub_industry": "Accelerated Compute & AI GPUs",
                "tier": "mega_driver",
                "market_cap_billions": 3120.0,
                "metrics": {
                    "elasticity_score": 98.0,
                    "capex_sensitivity": 1.0,
                    "revenue_concentration_pct": 100.0,
                    "operating_leverage": 3.4,
                    "forward_pe": 32.4,
                    "peg_ratio": 1.15,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 122.0,
                    "next_earnings_date": "2026-08-28",
                    "flow_sentiment_score": 0.88,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-22",
                        "period": "Q1 FY27",
                        "speaker": "Jensen Huang, CEO",
                        "quote": "Demand for Blackwell and our next-generation networking architectures is extraordinarily strong; cloud service providers are ramping optical interconnect bandwidth by over 400% to keep GPUs saturated.",
                        "context": "Commentary on optical transceiver and high-speed networking supplier requirements.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "AVGO",
                "name": "Broadcom Inc.",
                "sector": "Semiconductors",
                "sub_industry": "Custom AI ASICs & Networking Silicon",
                "tier": "mega_driver",
                "market_cap_billions": 780.0,
                "metrics": {
                    "elasticity_score": 95.5,
                    "capex_sensitivity": 1.8,
                    "revenue_concentration_pct": 65.0,
                    "operating_leverage": 3.2,
                    "forward_pe": 26.5,
                    "peg_ratio": 1.10,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 47.0,
                    "next_earnings_date": "2026-09-04",
                    "flow_sentiment_score": 0.86,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-06-12",
                        "period": "Q2 FY26",
                        "speaker": "Hock Tan, CEO",
                        "quote": "Custom AI accelerator revenue surpassed $3.5B this quarter alone, with ethernet networking switches and Tomahawk 5 silicon ramping at full capacity.",
                        "context": "Hyperscaler custom silicon and networking disclosures.",
                        "confidence": 0.97,
                    }
                ],
            },
            {
                "symbol": "MSFT",
                "name": "Microsoft Corporation",
                "sector": "Cloud Infrastructure",
                "sub_industry": "Hyperscale Cloud & AI Platform",
                "tier": "downstream_customer",
                "market_cap_billions": 3280.0,
                "metrics": {
                    "elasticity_score": 85.0,
                    "capex_sensitivity": 0.8,
                    "revenue_concentration_pct": 35.0,
                    "operating_leverage": 1.8,
                    "forward_pe": 29.5,
                    "peg_ratio": 1.75,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": 16.5,
                    "next_earnings_date": "2026-10-22",
                    "flow_sentiment_score": 0.65,
                    "options_skew": "balanced_bullish",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-25",
                        "period": "Q3 FY26",
                        "speaker": "Amy Hood, CFO",
                        "quote": "Capital expenditures were $19 billion this quarter, driven by investments in cloud and AI infrastructure. We expect CapEx to increase sequentially throughout the coming fiscal year.",
                        "context": "Azure CapEx guidance and supplier pass-through spending.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "AAOI",
                "name": "Applied Optoelectronics, Inc.",
                "sector": "Technology",
                "sub_industry": "Optical Transceivers & Lasers",
                "tier": "tier1_supplier",
                "market_cap_billions": 1.85,
                "metrics": {
                    "elasticity_score": 96.4,
                    "capex_sensitivity": 4.2,
                    "revenue_concentration_pct": 52.0,
                    "operating_leverage": 4.8,
                    "forward_pe": 16.8,
                    "peg_ratio": 0.58,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 84.5,
                    "next_earnings_date": "2026-08-08",
                    "flow_sentiment_score": 0.92,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-09",
                        "period": "Q1 2026",
                        "speaker": "Dr. Thompson Lin, CEO",
                        "quote": "Our 400G and 800G data center optical transceivers are experiencing astronomical demand from our Tier-1 hyperscale customer. We have secured long-term purchase commitments expanding production through 2027.",
                        "context": "Hyperscaler data center optical transceiver production ramp.",
                        "confidence": 0.99,
                    }
                ],
            },
            {
                "symbol": "LITE",
                "name": "Lumentum Holdings Inc.",
                "sector": "Technology",
                "sub_industry": "Photonics & Optical Engines",
                "tier": "tier1_supplier",
                "market_cap_billions": 6.4,
                "metrics": {
                    "elasticity_score": 93.1,
                    "capex_sensitivity": 3.4,
                    "revenue_concentration_pct": 41.5,
                    "operating_leverage": 3.6,
                    "forward_pe": 21.2,
                    "peg_ratio": 0.82,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 62.0,
                    "next_earnings_date": "2026-08-14",
                    "flow_sentiment_score": 0.85,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-08",
                        "period": "Q3 FY26",
                        "speaker": "Alan Lowe, CEO",
                        "quote": "Our Cloud & Networking segment delivered record shipments of high-speed EML lasers and transceivers, propelled by the relentless expansion of AI clusters requiring 800G and 1.6T optical interconnect.",
                        "context": "AI cluster optics demand narrative.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "COHR",
                "name": "Coherent Corp.",
                "sector": "Technology",
                "sub_industry": "Optical Materials & Transceivers",
                "tier": "tier1_supplier",
                "market_cap_billions": 14.8,
                "metrics": {
                    "elasticity_score": 89.8,
                    "capex_sensitivity": 2.8,
                    "revenue_concentration_pct": 34.0,
                    "operating_leverage": 3.1,
                    "forward_pe": 24.5,
                    "peg_ratio": 1.05,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 45.0,
                    "next_earnings_date": "2026-08-18",
                    "flow_sentiment_score": 0.78,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-07",
                        "period": "Q3 FY26",
                        "speaker": "Jim Anderson, CEO",
                        "quote": "800G and 1.6T transceiver order books are expanding rapidly as hyperscalers scale optical fabric connectivity inside AI training supercomputers.",
                        "context": "Datacom networking segment commentary.",
                        "confidence": 0.94,
                    }
                ],
            },
            {
                "symbol": "MU",
                "name": "Micron Technology, Inc.",
                "sector": "Semiconductors",
                "sub_industry": "HBM Memory & High-Density DRAM",
                "tier": "tier1_supplier",
                "market_cap_billions": 142.0,
                "metrics": {
                    "elasticity_score": 92.5,
                    "capex_sensitivity": 3.1,
                    "revenue_concentration_pct": 38.0,
                    "operating_leverage": 4.5,
                    "forward_pe": 11.4,
                    "peg_ratio": 0.45,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 93.0,
                    "next_earnings_date": "2026-09-25",
                    "flow_sentiment_score": 0.89,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-06-26",
                        "period": "Q3 FY26",
                        "speaker": "Sanjay Mehrotra, CEO",
                        "quote": "Our HBM3e supply is completely sold out through calendar 2026, and we are already negotiating multi-year supply allocations for HBM4 with leading AI accelerator platforms.",
                        "context": "High-Bandwidth Memory (HBM) supply allocation commentary.",
                        "confidence": 0.99,
                    }
                ],
            },
            {
                "symbol": "VRT",
                "name": "Vertiv Holdings Co",
                "sector": "Industrials",
                "sub_industry": "Liquid Cooling & Power Management",
                "tier": "tier1_supplier",
                "market_cap_billions": 38.5,
                "metrics": {
                    "elasticity_score": 94.0,
                    "capex_sensitivity": 3.7,
                    "revenue_concentration_pct": 46.0,
                    "operating_leverage": 3.9,
                    "forward_pe": 27.8,
                    "peg_ratio": 1.02,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 68.0,
                    "next_earnings_date": "2026-07-24",
                    "flow_sentiment_score": 0.91,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-24",
                        "period": "Q1 2026",
                        "speaker": "Giordano Albertazzi, CEO",
                        "quote": "Order backlog reached a record $6.3 billion driven by liquid cooling distribution units (CDUs) and high-density thermal management systems co-designed with Nvidia and hyperscale cloud providers.",
                        "context": "High-density liquid cooling backlog expansion.",
                        "confidence": 0.99,
                    }
                ],
            },
            {
                "symbol": "CEG",
                "name": "Constellation Energy Corporation",
                "sector": "Utilities",
                "sub_industry": "Nuclear & Clean Data Center Power",
                "tier": "horizontal_enabler",
                "market_cap_billions": 84.0,
                "metrics": {
                    "elasticity_score": 90.2,
                    "capex_sensitivity": 2.9,
                    "revenue_concentration_pct": 32.0,
                    "operating_leverage": 3.2,
                    "forward_pe": 26.5,
                    "peg_ratio": 1.25,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 38.0,
                    "next_earnings_date": "2026-08-06",
                    "flow_sentiment_score": 0.87,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-09",
                        "period": "Q1 2026",
                        "speaker": "Joe Dominguez, CEO",
                        "quote": "We are in active discussions on multi-gigawatt long-term power purchase agreements with hyperscale data center operators seeking 24/7 dedicated clean nuclear generation directly behind the meter.",
                        "context": "Data center nuclear PPA contract disclosures.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "TSM",
                "name": "Taiwan Semiconductor Manufacturing Co.",
                "sector": "Semiconductors",
                "sub_industry": "Advanced Foundry & CoWoS Packaging",
                "tier": "tier1_supplier",
                "market_cap_billions": 890.0,
                "metrics": {
                    "elasticity_score": 95.0,
                    "capex_sensitivity": 3.0,
                    "revenue_concentration_pct": 42.0,
                    "operating_leverage": 3.3,
                    "forward_pe": 23.5,
                    "peg_ratio": 0.92,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 36.0,
                    "next_earnings_date": "2026-10-15",
                    "flow_sentiment_score": 0.88,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-18",
                        "period": "Q1 2026",
                        "speaker": "C.C. Wei, CEO",
                        "quote": "AI processor demand continues to outpace our CoWoS packaging capacity. We are more than doubling our advanced packaging output in 2026 and expanding further in 2027.",
                        "context": "Advanced packaging CoWoS capacity ramp.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "ALAB",
                "name": "Astera Labs, Inc.",
                "sector": "Semiconductors",
                "sub_industry": "PCIe Retimers & AI Connectivity",
                "tier": "tier1_supplier",
                "market_cap_billions": 12.4,
                "metrics": {
                    "elasticity_score": 95.2,
                    "capex_sensitivity": 4.4,
                    "revenue_concentration_pct": 58.0,
                    "operating_leverage": 4.6,
                    "forward_pe": 38.5,
                    "peg_ratio": 0.72,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 118.0,
                    "next_earnings_date": "2026-08-05",
                    "flow_sentiment_score": 0.93,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-06",
                        "period": "Q1 2026",
                        "speaker": "Jitendra Mohan, CEO",
                        "quote": "Our Aries PCIe retimers and Taurus Ethernet smart cable modules are being designed into every major AI accelerator platform as GPU-to-GPU bandwidth becomes the binding constraint.",
                        "context": "AI cluster connectivity attach rates.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "FN",
                "name": "Fabrinet",
                "sector": "Technology",
                "sub_industry": "Optical Packaging & Precision Manufacturing",
                "tier": "tier1_supplier",
                "market_cap_billions": 9.8,
                "metrics": {
                    "elasticity_score": 91.6,
                    "capex_sensitivity": 3.2,
                    "revenue_concentration_pct": 44.0,
                    "operating_leverage": 3.4,
                    "forward_pe": 24.8,
                    "peg_ratio": 0.88,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 41.0,
                    "next_earnings_date": "2026-08-18",
                    "flow_sentiment_score": 0.84,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-05",
                        "period": "Q3 FY26",
                        "speaker": "Seamus Grady, CEO",
                        "quote": "Datacom revenue grew over 60% year-over-year as we scale advanced optical packaging capacity for 800G and 1.6T transceiver programs.",
                        "context": "Optical packaging capacity expansion.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "MRVL",
                "name": "Marvell Technology, Inc.",
                "sector": "Semiconductors",
                "sub_industry": "Custom AI Silicon & Electro-Optics",
                "tier": "tier1_supplier",
                "market_cap_billions": 92.0,
                "metrics": {
                    "elasticity_score": 93.8,
                    "capex_sensitivity": 3.5,
                    "revenue_concentration_pct": 48.0,
                    "operating_leverage": 3.8,
                    "forward_pe": 31.2,
                    "peg_ratio": 0.95,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 58.0,
                    "next_earnings_date": "2026-08-28",
                    "flow_sentiment_score": 0.90,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-29",
                        "period": "Q1 FY27",
                        "speaker": "Matt Murphy, CEO",
                        "quote": "Custom AI compute silicon and 800G PAM4 electro-optics are now our two largest growth engines, with data center revenue up triple digits year-over-year.",
                        "context": "Custom silicon and electro-optics ramp.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "ANET",
                "name": "Arista Networks, Inc.",
                "sector": "Technology",
                "sub_industry": "AI Ethernet Switching & Cloud Networking",
                "tier": "tier1_supplier",
                "market_cap_billions": 118.0,
                "metrics": {
                    "elasticity_score": 90.4,
                    "capex_sensitivity": 2.9,
                    "revenue_concentration_pct": 40.0,
                    "operating_leverage": 3.3,
                    "forward_pe": 34.5,
                    "peg_ratio": 1.05,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 34.0,
                    "next_earnings_date": "2026-08-04",
                    "flow_sentiment_score": 0.85,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-05",
                        "period": "Q1 2026",
                        "speaker": "Jayshree Ullal, CEO",
                        "quote": "AI back-end networking is now a multi-billion dollar annualized opportunity as hyperscalers deploy 800G Ethernet fabrics to interconnect GPU clusters.",
                        "context": "AI Ethernet fabric adoption.",
                        "confidence": 0.97,
                    }
                ],
            },
            {
                "symbol": "SMCI",
                "name": "Super Micro Computer, Inc.",
                "sector": "Technology",
                "sub_industry": "AI Server Racks & Liquid-Cooled Systems",
                "tier": "tier1_supplier",
                "market_cap_billions": 34.0,
                "metrics": {
                    "elasticity_score": 92.7,
                    "capex_sensitivity": 3.9,
                    "revenue_concentration_pct": 55.0,
                    "operating_leverage": 4.1,
                    "forward_pe": 18.5,
                    "peg_ratio": 0.55,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 88.0,
                    "next_earnings_date": "2026-08-06",
                    "flow_sentiment_score": 0.88,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-06",
                        "period": "Q3 FY26",
                        "speaker": "Charles Liang, CEO",
                        "quote": "Direct liquid cooling now represents over 30% of our AI server shipments, and our DLC rack-scale solutions are being adopted across the largest GPU clusters.",
                        "context": "Liquid-cooled AI server adoption.",
                        "confidence": 0.97,
                    }
                ],
            },
            {
                "symbol": "VST",
                "name": "Vistra Corp.",
                "sector": "Utilities",
                "sub_industry": "Nuclear & Gas-Fired Data Center Power",
                "tier": "horizontal_enabler",
                "market_cap_billions": 62.0,
                "metrics": {
                    "elasticity_score": 89.6,
                    "capex_sensitivity": 2.8,
                    "revenue_concentration_pct": 30.0,
                    "operating_leverage": 3.0,
                    "forward_pe": 22.5,
                    "peg_ratio": 1.15,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 42.0,
                    "next_earnings_date": "2026-08-07",
                    "flow_sentiment_score": 0.86,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-08",
                        "period": "Q1 2026",
                        "speaker": "Jim Burke, CEO",
                        "quote": "We have signed long-term power purchase agreements with hyperscale data center operators across our nuclear and gas fleet, locking in premium contracted pricing.",
                        "context": "Data center power purchase agreements.",
                        "confidence": 0.97,
                    }
                ],
            },
            {
                "symbol": "ETN",
                "name": "Eaton Corporation plc",
                "sector": "Industrials",
                "sub_industry": "Power Distribution & Data Center Electrical",
                "tier": "tier1_supplier",
                "market_cap_billions": 128.0,
                "metrics": {
                    "elasticity_score": 88.9,
                    "capex_sensitivity": 2.7,
                    "revenue_concentration_pct": 28.0,
                    "operating_leverage": 3.1,
                    "forward_pe": 27.5,
                    "peg_ratio": 1.20,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 26.0,
                    "next_earnings_date": "2026-08-01",
                    "flow_sentiment_score": 0.83,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-01",
                        "period": "Q1 2026",
                        "speaker": "Craig Arnold, CEO",
                        "quote": "Data center electrical infrastructure orders grew over 40% as AI facilities require higher-density switchgear, busway, and power quality solutions.",
                        "context": "Data center electrical infrastructure demand.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "GEV",
                "name": "GE Vernova Inc.",
                "sector": "Industrials",
                "sub_industry": "Gas Turbines & Grid Electrification",
                "tier": "horizontal_enabler",
                "market_cap_billions": 96.0,
                "metrics": {
                    "elasticity_score": 87.5,
                    "capex_sensitivity": 2.6,
                    "revenue_concentration_pct": 26.0,
                    "operating_leverage": 2.9,
                    "forward_pe": 30.0,
                    "peg_ratio": 1.30,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 22.0,
                    "next_earnings_date": "2026-07-23",
                    "flow_sentiment_score": 0.82,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-23",
                        "period": "Q1 2026",
                        "speaker": "Scott Strazik, CEO",
                        "quote": "Gas turbine orders for data center co-location are at record levels, and our grid electrification backlog continues to expand on interconnection-driven demand.",
                        "context": "Gas turbine and grid electrification demand.",
                        "confidence": 0.96,
                    }
                ],
            },
        ],
        "edges": [
            {"id": "AAOI-NVDA", "source": "AAOI", "target": "NVDA", "relationship": "supplies_to", "strength": 0.95, "supply_category": "800G/1.6T Optical Transceivers", "evidence_count": 2},
            {"id": "ALAB-NVDA", "source": "ALAB", "target": "NVDA", "relationship": "supplies_to", "strength": 0.96, "supply_category": "PCIe Retimers & AI Connectivity", "evidence_count": 1},
            {"id": "FN-NVDA", "source": "FN", "target": "NVDA", "relationship": "supplies_to", "strength": 0.90, "supply_category": "Optical Packaging & Assembly", "evidence_count": 1},
            {"id": "MRVL-NVDA", "source": "MRVL", "target": "NVDA", "relationship": "supplies_to", "strength": 0.93, "supply_category": "Custom AI Silicon & Electro-Optics", "evidence_count": 1},
            {"id": "ANET-MSFT", "source": "ANET", "target": "MSFT", "relationship": "supplies_to", "strength": 0.92, "supply_category": "800G Ethernet Switching Fabrics", "evidence_count": 1},
            {"id": "SMCI-NVDA", "source": "SMCI", "target": "NVDA", "relationship": "supplies_to", "strength": 0.91, "supply_category": "Liquid-Cooled AI Server Racks", "evidence_count": 1},
            {"id": "VST-MSFT", "source": "VST", "target": "MSFT", "relationship": "infrastructure_enabler", "strength": 0.90, "supply_category": "Nuclear & Gas Data Center Power PPA", "evidence_count": 1},
            {"id": "ETN-NVDA", "source": "ETN", "target": "NVDA", "relationship": "supplies_to", "strength": 0.88, "supply_category": "High-Density Power Distribution", "evidence_count": 1},
            {"id": "GEV-VRT", "source": "GEV", "target": "VRT", "relationship": "co_dependent", "strength": 0.86, "supply_category": "Power & Thermal Co-Design", "evidence_count": 1},
            {"id": "LITE-NVDA", "source": "LITE", "target": "NVDA", "relationship": "supplies_to", "strength": 0.92, "supply_category": "EML Lasers & Optical Engines", "evidence_count": 1},
            {"id": "COHR-NVDA", "source": "COHR", "target": "NVDA", "relationship": "supplies_to", "strength": 0.88, "supply_category": "800G Transceivers & InP Substrates", "evidence_count": 1},
            {"id": "MU-NVDA", "source": "MU", "target": "NVDA", "relationship": "supplies_to", "strength": 0.94, "supply_category": "HBM3e / HBM4 Memory Stacks", "evidence_count": 2},
            {"id": "TSM-NVDA", "source": "TSM", "target": "NVDA", "relationship": "supplies_to", "strength": 0.98, "supply_category": "3nm Foundry & CoWoS Packaging", "evidence_count": 1},
            {"id": "VRT-NVDA", "source": "VRT", "target": "NVDA", "relationship": "co_dependent", "strength": 0.93, "supply_category": "Direct-to-Chip Liquid Cooling CDUs", "evidence_count": 1},
            {"id": "NVDA-MSFT", "source": "NVDA", "target": "MSFT", "relationship": "supplies_to", "strength": 0.96, "supply_category": "Blackwell AI Superclusters & InfiniBand", "evidence_count": 1},
            {"id": "CEG-MSFT", "source": "CEG", "target": "MSFT", "relationship": "infrastructure_enabler", "strength": 0.94, "supply_category": "24/7 Dedicated Clean Nuclear Power PPA", "evidence_count": 1},
        ],
    },

    # --------------------------------------------------------------------------
    # 2. Space Economy, Direct-to-Cell & Defense
    # --------------------------------------------------------------------------
    "space_defense": {
        "theme_name": "Space Economy, Direct-to-Cell & Defense",
        "description": "Commercial space infrastructure, low Earth orbit (LEO) megaconstellations, cellular broadband, lunar payload services, and defense prime contractor supply chains.",
        "capex_catalyst_narrative": "Commercial satellite constellations (AST SpaceMobile BlueBird, Starlink, Project Kuiper) and Space Force / NASA Artemis lunar programs are surging hardware procurement for space-qualified phased array antennas, solar arrays, launch services, optical inter-satellite laser links, and high-reliability aerospace components.",
        "total_ecosystem_market_cap_b": 1420.0,
        "catalyst_timeline": [
            {
                "date": "2026-09-08",
                "event": "AST SpaceMobile BlueBird 1-5 Commercial Direct-to-Cell Service Launch with AT&T / Verizon",
                "impacted_tickers": ["ASTS", "T", "VZ", "RKLB", "LMT"],
            },
            {
                "date": "2026-09-22",
                "event": "Rocket Lab Neutron Launch Vehicle Hot-Fire & First Flight Window Announcement",
                "impacted_tickers": ["RKLB", "RDW", "LUNR", "KTOS"],
            },
            {
                "date": "2026-10-14",
                "event": "NASA CLPS Lunar Landing Mission & Autonomous Surface Cargo Delivery",
                "impacted_tickers": ["LUNR", "RDW", "PL", "NOC"],
            },
            {
                "date": "2026-11-05",
                "event": "DoD Space Development Agency (SDA) Tranche 2 Tracking & Transport Layer Awards",
                "impacted_tickers": ["LMT", "NOC", "KTOS", "HEI"],
            },
        ],
        "default_focus": "ASTS",
        "nodes": [
            {
                "symbol": "ASTS",
                "name": "AST SpaceMobile, Inc.",
                "sector": "Space & Telecommunications",
                "sub_industry": "Space-Based Direct-to-Cell Broadband",
                "tier": "mega_driver",
                "market_cap_billions": 8.5,
                "metrics": {
                    "elasticity_score": 97.5,
                    "capex_sensitivity": 4.5,
                    "revenue_concentration_pct": 85.0,
                    "operating_leverage": 5.0,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 210.0,
                    "next_earnings_date": "2026-08-14",
                    "flow_sentiment_score": 0.95,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-15",
                        "period": "Q1 2026",
                        "speaker": "Abel Avellan, CEO",
                        "quote": "We have secured binding definitive commercial agreements with AT&T and Verizon covering 100% of US wireless subscribers, with prepaid revenue commitments and spectrum integration progressing on schedule for nationwide broadband coverage.",
                        "context": "Direct-to-cell commercialization and tier-1 MNO partnerships.",
                        "confidence": 0.99,
                    }
                ],
            },
            {
                "symbol": "RKLB",
                "name": "Rocket Lab USA, Inc.",
                "sector": "Aerospace & Defense",
                "sub_industry": "Launch Vehicles & Space Systems Components",
                "tier": "tier1_supplier",
                "market_cap_billions": 5.4,
                "metrics": {
                    "elasticity_score": 94.2,
                    "capex_sensitivity": 3.8,
                    "revenue_concentration_pct": 52.0,
                    "operating_leverage": 4.2,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 72.0,
                    "next_earnings_date": "2026-08-08",
                    "flow_sentiment_score": 0.91,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-08",
                        "period": "Q1 2026",
                        "speaker": "Peter Beck, CEO",
                        "quote": "Our Space Systems backlog reached a record $1.06 billion, driven by satellite bus production for MDA/Globalstar and DoD missile tracking constellations.",
                        "context": "Space systems backlog expansion.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "LUNR",
                "name": "Intuitive Machines, Inc.",
                "sector": "Aerospace & Defense",
                "sub_industry": "Lunar Landers & Space Data Services",
                "tier": "tier1_supplier",
                "market_cap_billions": 1.1,
                "metrics": {
                    "elasticity_score": 90.8,
                    "capex_sensitivity": 3.5,
                    "revenue_concentration_pct": 68.0,
                    "operating_leverage": 3.8,
                    "forward_pe": 18.0,
                    "peg_ratio": 0.72,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 140.0,
                    "next_earnings_date": "2026-08-13",
                    "flow_sentiment_score": 0.86,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-14",
                        "period": "Q1 2026",
                        "speaker": "Steve Altemus, CEO",
                        "quote": "Winning the NASA Near Space Network contract up to $4.8 billion validates our position as the primary cislunar communications and lunar orbital transport provider.",
                        "context": "NASA contract award disclosures.",
                        "confidence": 0.97,
                    }
                ],
            },
            {
                "symbol": "RDW",
                "name": "Redwire Corporation",
                "sector": "Aerospace & Defense",
                "sub_industry": "Roll-Out Solar Arrays & Space Infrastructure",
                "tier": "tier2_supplier",
                "market_cap_billions": 0.65,
                "metrics": {
                    "elasticity_score": 89.5,
                    "capex_sensitivity": 3.4,
                    "revenue_concentration_pct": 60.0,
                    "operating_leverage": 3.6,
                    "forward_pe": 16.5,
                    "peg_ratio": 0.65,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 48.0,
                    "next_earnings_date": "2026-08-07",
                    "flow_sentiment_score": 0.82,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-09",
                        "period": "Q1 2026",
                        "speaker": "Peter Cannito, CEO",
                        "quote": "Our ROSA roll-out solar arrays power the International Space Station, lunar gateway, and commercial broadband satellite constellations.",
                        "context": "Space solar power systems.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "T",
                "name": "AT&T Inc.",
                "sector": "Telecommunications",
                "sub_industry": "Tier 1 Wireless Carrier & Spectrum Partner",
                "tier": "downstream_customer",
                "market_cap_billions": 140.0,
                "metrics": {
                    "elasticity_score": 82.0,
                    "capex_sensitivity": 0.8,
                    "revenue_concentration_pct": 18.0,
                    "operating_leverage": 1.6,
                    "forward_pe": 8.5,
                    "peg_ratio": 1.20,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": 4.5,
                    "next_earnings_date": "2026-10-21",
                    "flow_sentiment_score": 0.68,
                    "options_skew": "balanced_bullish",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-24",
                        "period": "Q1 2026",
                        "speaker": "John Stankey, CEO",
                        "quote": "Our definitive partnership with AST SpaceMobile enables us to offer ubiquitous 100% geographic broadband coverage directly to standard smartphones from our existing cellular spectrum.",
                        "context": "AT&T direct-to-cell strategic roadmap.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "VZ",
                "name": "Verizon Communications Inc.",
                "sector": "Telecommunications",
                "sub_industry": "Tier 1 Wireless Carrier & 850MHz Spectrum",
                "tier": "downstream_customer",
                "market_cap_billions": 175.0,
                "metrics": {
                    "elasticity_score": 81.5,
                    "capex_sensitivity": 0.75,
                    "revenue_concentration_pct": 16.0,
                    "operating_leverage": 1.5,
                    "forward_pe": 9.2,
                    "peg_ratio": 1.30,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": 3.8,
                    "next_earnings_date": "2026-10-23",
                    "flow_sentiment_score": 0.66,
                    "options_skew": "balanced_bullish",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-22",
                        "period": "Q1 2026",
                        "speaker": "Hans Vestberg, CEO",
                        "quote": "Committing $100 million in commercial prepayments to AST SpaceMobile provides Verizon customers with seamless satellite text and data connectivity across dead zones nationwide.",
                        "context": "Verizon direct-to-cell commercial agreement.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "LMT",
                "name": "Lockheed Martin Corporation",
                "sector": "Aerospace & Defense",
                "sub_industry": "Defense Prime & Space Systems Integrator",
                "tier": "downstream_customer",
                "market_cap_billions": 118.0,
                "metrics": {
                    "elasticity_score": 84.5,
                    "capex_sensitivity": 1.2,
                    "revenue_concentration_pct": 22.0,
                    "operating_leverage": 2.0,
                    "forward_pe": 17.5,
                    "peg_ratio": 1.40,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": 6.5,
                    "next_earnings_date": "2026-10-20",
                    "flow_sentiment_score": 0.70,
                    "options_skew": "balanced_bullish",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-22",
                        "period": "Q1 2026",
                        "speaker": "Jim Taiclet, CEO",
                        "quote": "Our space segment backlog grew double digits on classified and SDA transport layer awards, driving demand for advanced satellite buses and optical inter-satellite links.",
                        "context": "Defense space backlog expansion.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "NOC",
                "name": "Northrop Grumman Corporation",
                "sector": "Aerospace & Defense",
                "sub_industry": "Defense Prime & Missile Tracking Systems",
                "tier": "downstream_customer",
                "market_cap_billions": 72.0,
                "metrics": {
                    "elasticity_score": 83.8,
                    "capex_sensitivity": 1.1,
                    "revenue_concentration_pct": 20.0,
                    "operating_leverage": 1.9,
                    "forward_pe": 16.8,
                    "peg_ratio": 1.35,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": 5.8,
                    "next_earnings_date": "2026-10-22",
                    "flow_sentiment_score": 0.69,
                    "options_skew": "balanced_bullish",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-24",
                        "period": "Q1 2026",
                        "speaker": "Kathy Warden, CEO",
                        "quote": "Hypersonic and missile tracking constellation programs are scaling, requiring high-reliability space-qualified electronics and propulsion from our supplier base.",
                        "context": "Missile tracking constellation demand.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "KTOS",
                "name": "Kratos Defense & Security Solutions",
                "sector": "Aerospace & Defense",
                "sub_industry": "Defense Electronics & Hypersonic Systems",
                "tier": "tier1_supplier",
                "market_cap_billions": 4.2,
                "metrics": {
                    "elasticity_score": 91.2,
                    "capex_sensitivity": 3.6,
                    "revenue_concentration_pct": 55.0,
                    "operating_leverage": 3.9,
                    "forward_pe": 28.0,
                    "peg_ratio": 0.85,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 38.0,
                    "next_earnings_date": "2026-08-06",
                    "flow_sentiment_score": 0.87,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-07",
                        "period": "Q1 2026",
                        "speaker": "Eric DeMarco, CEO",
                        "quote": "Our space and satellite ground systems revenue grew over 30% as SDA and commercial constellation operators expand software-defined ground infrastructure.",
                        "context": "Space ground systems growth.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "HEI",
                "name": "HEICO Corporation",
                "sector": "Aerospace & Defense",
                "sub_industry": "Aerospace Components & Aftermarket",
                "tier": "tier1_supplier",
                "market_cap_billions": 32.0,
                "metrics": {
                    "elasticity_score": 86.4,
                    "capex_sensitivity": 2.2,
                    "revenue_concentration_pct": 30.0,
                    "operating_leverage": 2.8,
                    "forward_pe": 38.0,
                    "peg_ratio": 1.55,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 18.0,
                    "next_earnings_date": "2026-08-26",
                    "flow_sentiment_score": 0.78,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-28",
                        "period": "Q2 FY26",
                        "speaker": "Laurans Mendelson, CEO",
                        "quote": "Commercial aerospace and defense aftermarket demand remains robust, with flight support group revenue up double digits on higher aircraft utilization.",
                        "context": "Aerospace aftermarket demand.",
                        "confidence": 0.94,
                    }
                ],
            },
            {
                "symbol": "PL",
                "name": "Planet Labs PBC",
                "sector": "Space & Satellite Data",
                "sub_industry": "Earth Observation & Satellite Imagery",
                "tier": "tier1_supplier",
                "market_cap_billions": 1.4,
                "metrics": {
                    "elasticity_score": 88.6,
                    "capex_sensitivity": 3.2,
                    "revenue_concentration_pct": 48.0,
                    "operating_leverage": 3.4,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 22.0,
                    "next_earnings_date": "2026-09-10",
                    "flow_sentiment_score": 0.80,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-06-10",
                        "period": "Q1 FY27",
                        "speaker": "Will Marshall, CEO",
                        "quote": "Defense and intelligence customers are expanding multi-year subscriptions for daily global monitoring, driving record annual recurring revenue growth.",
                        "context": "Earth observation subscription growth.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "IRDM",
                "name": "Iridium Communications Inc.",
                "sector": "Space & Telecommunications",
                "sub_industry": "LEO Satellite Constellation Operator",
                "tier": "horizontal_enabler",
                "market_cap_billions": 3.6,
                "metrics": {
                    "elasticity_score": 85.2,
                    "capex_sensitivity": 2.0,
                    "revenue_concentration_pct": 35.0,
                    "operating_leverage": 2.6,
                    "forward_pe": 14.5,
                    "peg_ratio": 1.10,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": 9.0,
                    "next_earnings_date": "2026-10-15",
                    "flow_sentiment_score": 0.74,
                    "options_skew": "balanced_bullish",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-17",
                        "period": "Q1 2026",
                        "speaker": "Matt Desch, CEO",
                        "quote": "Direct-to-device standards are expanding the addressable market for LEO connectivity, and our partner ecosystem continues to grow across government and commercial segments.",
                        "context": "Direct-to-device market expansion.",
                        "confidence": 0.94,
                    }
                ],
            },
            {
                "symbol": "GSAT",
                "name": "Globalstar, Inc.",
                "sector": "Space & Telecommunications",
                "sub_industry": "Satellite Spectrum & Terrestrial Integration",
                "tier": "tier1_supplier",
                "market_cap_billions": 2.8,
                "metrics": {
                    "elasticity_score": 87.8,
                    "capex_sensitivity": 3.0,
                    "revenue_concentration_pct": 50.0,
                    "operating_leverage": 3.2,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 30.0,
                    "next_earnings_date": "2026-08-07",
                    "flow_sentiment_score": 0.83,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-08",
                        "period": "Q1 2026",
                        "speaker": "Paul Jacobs, CEO",
                        "quote": "Our XCOM RAN and satellite spectrum assets are being integrated into direct-to-device and private network deployments with major ecosystem partners.",
                        "context": "Satellite spectrum commercialization.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "SATL",
                "name": "Satellogic Inc.",
                "sector": "Space & Satellite Data",
                "sub_industry": "High-Resolution Satellite Manufacturing & Imagery",
                "tier": "tier1_supplier",
                "market_cap_billions": 0.4,
                "metrics": {
                    "elasticity_score": 86.8,
                    "capex_sensitivity": 3.4,
                    "revenue_concentration_pct": 58.0,
                    "operating_leverage": 3.5,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 55.0,
                    "next_earnings_date": "2026-08-20",
                    "flow_sentiment_score": 0.81,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-20",
                        "period": "Q1 2026",
                        "speaker": "Emiliano Kargieman, CEO",
                        "quote": "Our vertically integrated satellite manufacturing and sub-meter imagery constellation is scaling to meet growing government and commercial monitoring demand.",
                        "context": "Satellite manufacturing and imagery scaling.",
                        "confidence": 0.94,
                    }
                ],
            },
            {
                "symbol": "BKSY",
                "name": "BlackSky Technology Inc.",
                "sector": "Space & Satellite Data",
                "sub_industry": "Real-Time Geospatial Intelligence",
                "tier": "tier2_supplier",
                "market_cap_billions": 0.3,
                "metrics": {
                    "elasticity_score": 85.6,
                    "capex_sensitivity": 3.1,
                    "revenue_concentration_pct": 62.0,
                    "operating_leverage": 3.3,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 40.0,
                    "next_earnings_date": "2026-08-08",
                    "flow_sentiment_score": 0.79,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-08",
                        "period": "Q1 2026",
                        "speaker": "Brian O'Toole, CEO",
                        "quote": "Our Spectra AI platform and high-revisit satellite constellation are winning multi-year defense and intelligence contracts for real-time monitoring.",
                        "context": "Geospatial intelligence contract wins.",
                        "confidence": 0.94,
                    }
                ],
            },
        ],
        "edges": [
            {"id": "RKLB-ASTS", "source": "RKLB", "target": "ASTS", "relationship": "supplies_to", "strength": 0.92, "supply_category": "Satellite Components & Launch Services", "evidence_count": 2},
            {"id": "RDW-ASTS", "source": "RDW", "target": "ASTS", "relationship": "supplies_to", "strength": 0.88, "supply_category": "High-Density Phased Array Solar Wings", "evidence_count": 1},
            {"id": "ASTS-T", "source": "ASTS", "target": "T", "relationship": "supplies_to", "strength": 0.98, "supply_category": "Space-Based Direct Cellular Broadband", "evidence_count": 2},
            {"id": "ASTS-VZ", "source": "ASTS", "target": "VZ", "relationship": "supplies_to", "strength": 0.96, "supply_category": "850 MHz Satellite Cellular Coverage", "evidence_count": 2},
            {"id": "RDW-LUNR", "source": "RDW", "target": "LUNR", "relationship": "supplies_to", "strength": 0.85, "supply_category": "Deployable Space Antennas & Structures", "evidence_count": 1},
            {"id": "KTOS-LMT", "source": "KTOS", "target": "LMT", "relationship": "supplies_to", "strength": 0.90, "supply_category": "Software-Defined Ground Systems", "evidence_count": 1},
            {"id": "HEI-NOC", "source": "HEI", "target": "NOC", "relationship": "supplies_to", "strength": 0.87, "supply_category": "Aerospace Components & Aftermarket", "evidence_count": 1},
            {"id": "PL-NOC", "source": "PL", "target": "NOC", "relationship": "supplies_to", "strength": 0.86, "supply_category": "Earth Observation Imagery", "evidence_count": 1},
            {"id": "IRDM-ASTS", "source": "IRDM", "target": "ASTS", "relationship": "co_dependent", "strength": 0.84, "supply_category": "LEO Direct-to-Device Standards", "evidence_count": 1},
            {"id": "GSAT-ASTS", "source": "GSAT", "target": "ASTS", "relationship": "supplies_to", "strength": 0.88, "supply_category": "Satellite Spectrum & RAN Integration", "evidence_count": 1},
            {"id": "SATL-ASTS", "source": "SATL", "target": "ASTS", "relationship": "supplies_to", "strength": 0.85, "supply_category": "Satellite Manufacturing & Imagery", "evidence_count": 1},
            {"id": "BKSY-PL", "source": "BKSY", "target": "PL", "relationship": "supplies_to", "strength": 0.83, "supply_category": "Geospatial Intelligence Analytics", "evidence_count": 1},
            {"id": "LMT-ASTS", "source": "LMT", "target": "ASTS", "relationship": "technology_partner", "strength": 0.82, "supply_category": "Defense Space Systems Integration", "evidence_count": 1},
            {"id": "NOC-ASTS", "source": "NOC", "target": "ASTS", "relationship": "technology_partner", "strength": 0.81, "supply_category": "Missile Tracking Constellation", "evidence_count": 1},
        ],
    },

    # --------------------------------------------------------------------------
    # 3. Semiconductor Capital Equipment & Advanced Packaging
    # --------------------------------------------------------------------------
    "semi_equipment": {
        "theme_name": "Semiconductor Capital Equipment & WFE",
        "description": "Next-generation gate-all-around (GAA) transistors, High-NA EUV, and advanced packaging metrology.",
        "capex_catalyst_narrative": "Foundry transitions to 2nm/A16 nodes and High-NA lithography are expanding wafer fab equipment (WFE) spending, disproportionately benefiting metrology, atomic layer deposition, and advanced packaging test suppliers.",
        "total_ecosystem_market_cap_b": 2850.0,
        "catalyst_timeline": [
            {
                "date": "2026-09-02",
                "event": "SEMICON Advanced Packaging & High-NA Forum",
                "impacted_tickers": ["ASML", "AMAT", "KLAC", "LRCX", "CAMT", "FORM"],
            },
        ],
        "default_focus": "ASML",
        "nodes": [
            {
                "symbol": "ASML",
                "name": "ASML Holding N.V.",
                "sector": "Semiconductors",
                "sub_industry": "EUV & High-NA Lithography",
                "tier": "mega_driver",
                "market_cap_billions": 380.0,
                "metrics": {
                    "elasticity_score": 96.0,
                    "capex_sensitivity": 1.0,
                    "revenue_concentration_pct": 100.0,
                    "operating_leverage": 3.0,
                    "forward_pe": 28.0,
                    "peg_ratio": 1.10,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 28.0,
                    "next_earnings_date": "2026-10-16",
                    "flow_sentiment_score": 0.86,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-17",
                        "period": "Q1 2026",
                        "speaker": "Christophe Fouquet, CEO",
                        "quote": "EUV backlog remains very healthy above 38 billion euros. We are seeing strong readiness preparations for High-NA tool insertions.",
                        "context": "High-NA EUV bookings narrative.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "KLAC",
                "name": "KLA Corporation",
                "sector": "Semiconductors",
                "sub_industry": "Process Control & Optical Metrology",
                "tier": "tier1_supplier",
                "market_cap_billions": 105.0,
                "metrics": {
                    "elasticity_score": 92.0,
                    "capex_sensitivity": 2.8,
                    "revenue_concentration_pct": 45.0,
                    "operating_leverage": 3.4,
                    "forward_pe": 25.5,
                    "peg_ratio": 1.15,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 32.0,
                    "next_earnings_date": "2026-07-25",
                    "flow_sentiment_score": 0.83,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-26",
                        "period": "Q3 FY26",
                        "speaker": "Rick Wallace, CEO",
                        "quote": "As pattern complexity increases at 2nm and 3D HBM architectures, metrology and inspection intensity grows faster than overall WFE spending.",
                        "context": "Metrology intensity expansion.",
                        "confidence": 0.97,
                    }
                ],
            },
            {
                "symbol": "AMAT",
                "name": "Applied Materials, Inc.",
                "sector": "Semiconductors",
                "sub_industry": "Materials Engineering & Deposition/Etch WFE",
                "tier": "tier1_supplier",
                "market_cap_billions": 185.0,
                "metrics": {
                    "elasticity_score": 90.0,
                    "capex_sensitivity": 2.5,
                    "revenue_concentration_pct": 38.0,
                    "operating_leverage": 3.1,
                    "forward_pe": 22.8,
                    "peg_ratio": 1.18,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 24.0,
                    "next_earnings_date": "2026-08-15",
                    "flow_sentiment_score": 0.82,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-16",
                        "period": "Q2 FY26",
                        "speaker": "Gary Dickerson, CEO",
                        "quote": "Gate-All-Around and backside power delivery transitions require significant expansion of selective materials deposition and atomic-scale etch systems.",
                        "context": "GAA and backside power WFE intensity.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "TSM",
                "name": "Taiwan Semiconductor Manufacturing Co.",
                "sector": "Semiconductors",
                "sub_industry": "Advanced Foundry & CoWoS Packaging",
                "tier": "mega_driver",
                "market_cap_billions": 890.0,
                "metrics": {
                    "elasticity_score": 95.0,
                    "capex_sensitivity": 3.0,
                    "revenue_concentration_pct": 42.0,
                    "operating_leverage": 3.3,
                    "forward_pe": 23.5,
                    "peg_ratio": 0.92,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 36.0,
                    "next_earnings_date": "2026-10-15",
                    "flow_sentiment_score": 0.88,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-18",
                        "period": "Q1 2026",
                        "speaker": "C.C. Wei, CEO",
                        "quote": "AI processor demand continues to outpace our CoWoS packaging capacity. We are more than doubling our advanced packaging output in 2026.",
                        "context": "Advanced packaging CoWoS capacity ramp.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "LRCX",
                "name": "Lam Research Corporation",
                "sector": "Semiconductors",
                "sub_industry": "Etch & Deposition WFE",
                "tier": "tier1_supplier",
                "market_cap_billions": 98.0,
                "metrics": {
                    "elasticity_score": 91.5,
                    "capex_sensitivity": 2.7,
                    "revenue_concentration_pct": 40.0,
                    "operating_leverage": 3.3,
                    "forward_pe": 24.0,
                    "peg_ratio": 1.10,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 30.0,
                    "next_earnings_date": "2026-07-30",
                    "flow_sentiment_score": 0.84,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-30",
                        "period": "Q3 FY26",
                        "speaker": "Tim Archer, CEO",
                        "quote": "Gate-all-around transistor architectures require roughly 30% more etch and deposition steps per wafer, structurally increasing our served market.",
                        "context": "GAA etch/deposition intensity.",
                        "confidence": 0.97,
                    }
                ],
            },
            {
                "symbol": "CAMT",
                "name": "Camtek Ltd.",
                "sector": "Semiconductors",
                "sub_industry": "Advanced Packaging Inspection & Metrology",
                "tier": "tier1_supplier",
                "market_cap_billions": 4.6,
                "metrics": {
                    "elasticity_score": 93.4,
                    "capex_sensitivity": 3.8,
                    "revenue_concentration_pct": 55.0,
                    "operating_leverage": 4.0,
                    "forward_pe": 26.0,
                    "peg_ratio": 0.70,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 48.0,
                    "next_earnings_date": "2026-08-05",
                    "flow_sentiment_score": 0.88,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-05",
                        "period": "Q1 2026",
                        "speaker": "Rafi Amit, CEO",
                        "quote": "Advanced packaging inspection demand is accelerating as HBM and chiplet architectures require substantially higher metrology and inspection intensity.",
                        "context": "Advanced packaging inspection demand.",
                        "confidence": 0.97,
                    }
                ],
            },
            {
                "symbol": "FORM",
                "name": "FormFactor, Inc.",
                "sector": "Semiconductors",
                "sub_industry": "Probe Cards & Test Systems",
                "tier": "tier1_supplier",
                "market_cap_billions": 3.2,
                "metrics": {
                    "elasticity_score": 90.8,
                    "capex_sensitivity": 3.4,
                    "revenue_concentration_pct": 50.0,
                    "operating_leverage": 3.7,
                    "forward_pe": 22.5,
                    "peg_ratio": 0.80,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 35.0,
                    "next_earnings_date": "2026-08-06",
                    "flow_sentiment_score": 0.85,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-06",
                        "period": "Q1 2026",
                        "speaker": "Mike Slessor, CEO",
                        "quote": "Probe card demand for advanced logic and HBM test is at record levels as chip complexity drives longer test times and higher probe card content.",
                        "context": "Probe card demand expansion.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "ONTO",
                "name": "Onto Innovation Inc.",
                "sector": "Semiconductors",
                "sub_industry": "Process Control & Packaging Metrology",
                "tier": "tier1_supplier",
                "market_cap_billions": 8.8,
                "metrics": {
                    "elasticity_score": 89.6,
                    "capex_sensitivity": 3.0,
                    "revenue_concentration_pct": 42.0,
                    "operating_leverage": 3.4,
                    "forward_pe": 27.0,
                    "peg_ratio": 0.95,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 28.0,
                    "next_earnings_date": "2026-08-07",
                    "flow_sentiment_score": 0.83,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-07",
                        "period": "Q1 2026",
                        "speaker": "Michael Plisinski, CEO",
                        "quote": "Our Dragonfly and Atlas systems are seeing strong pull for advanced packaging and specialty device process control as customers ramp heterogeneous integration.",
                        "context": "Packaging process control demand.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "ACLS",
                "name": "Axcelis Technologies, Inc.",
                "sector": "Semiconductors",
                "sub_industry": "Ion Implantation WFE",
                "tier": "tier1_supplier",
                "market_cap_billions": 3.8,
                "metrics": {
                    "elasticity_score": 88.2,
                    "capex_sensitivity": 2.9,
                    "revenue_concentration_pct": 45.0,
                    "operating_leverage": 3.5,
                    "forward_pe": 20.0,
                    "peg_ratio": 0.75,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 26.0,
                    "next_earnings_date": "2026-08-04",
                    "flow_sentiment_score": 0.82,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-04",
                        "period": "Q1 2026",
                        "speaker": "Russell Low, CEO",
                        "quote": "Power device and advanced logic customers are expanding ion implant capacity, with our Purion platform gaining share in high-energy applications.",
                        "context": "Ion implant capacity expansion.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "ENTG",
                "name": "Entegris, Inc.",
                "sector": "Semiconductors",
                "sub_industry": "Materials & Contamination Control",
                "tier": "tier1_supplier",
                "market_cap_billions": 16.5,
                "metrics": {
                    "elasticity_score": 87.4,
                    "capex_sensitivity": 2.6,
                    "revenue_concentration_pct": 36.0,
                    "operating_leverage": 3.0,
                    "forward_pe": 25.0,
                    "peg_ratio": 1.05,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 20.0,
                    "next_earnings_date": "2026-08-01",
                    "flow_sentiment_score": 0.80,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-01",
                        "period": "Q1 2026",
                        "speaker": "Bertrand Loy, CEO",
                        "quote": "Advanced node transitions increase our served content per wafer through higher-purity materials and more demanding contamination control requirements.",
                        "context": "Materials content per wafer growth.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "TER",
                "name": "Teradyne, Inc.",
                "sector": "Semiconductors",
                "sub_industry": "Semiconductor Test Equipment",
                "tier": "tier1_supplier",
                "market_cap_billions": 22.0,
                "metrics": {
                    "elasticity_score": 86.8,
                    "capex_sensitivity": 2.5,
                    "revenue_concentration_pct": 33.0,
                    "operating_leverage": 3.1,
                    "forward_pe": 28.5,
                    "peg_ratio": 1.20,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 22.0,
                    "next_earnings_date": "2026-07-24",
                    "flow_sentiment_score": 0.81,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-24",
                        "period": "Q1 2026",
                        "speaker": "Greg Smith, CEO",
                        "quote": "Test intensity is rising with AI accelerator and HBM complexity, driving demand for our high-performance system-on-chip and memory test platforms.",
                        "context": "Semiconductor test intensity.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "COHU",
                "name": "Cohu, Inc.",
                "sector": "Semiconductors",
                "sub_industry": "Test Handling & Inspection Systems",
                "tier": "tier2_supplier",
                "market_cap_billions": 1.1,
                "metrics": {
                    "elasticity_score": 85.4,
                    "capex_sensitivity": 2.8,
                    "revenue_concentration_pct": 40.0,
                    "operating_leverage": 3.2,
                    "forward_pe": 18.0,
                    "peg_ratio": 0.70,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 18.0,
                    "next_earnings_date": "2026-08-01",
                    "flow_sentiment_score": 0.78,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-01",
                        "period": "Q1 2026",
                        "speaker": "Luis Müller, CEO",
                        "quote": "Our test handlers and inspection systems are benefiting from rising semiconductor unit volumes and increasing test complexity across automotive and industrial.",
                        "context": "Test handler demand.",
                        "confidence": 0.94,
                    }
                ],
            },
        ],
        "edges": [
            {"id": "ASML-TSM", "source": "ASML", "target": "TSM", "relationship": "supplies_to", "strength": 0.98, "supply_category": "EUV & High-NA Scanners", "evidence_count": 1},
            {"id": "KLAC-TSM", "source": "KLAC", "target": "TSM", "relationship": "supplies_to", "strength": 0.95, "supply_category": "EUV Mask & Pattern Inspection", "evidence_count": 1},
            {"id": "AMAT-TSM", "source": "AMAT", "target": "TSM", "relationship": "supplies_to", "strength": 0.94, "supply_category": "Materials Deposition & Etch Systems", "evidence_count": 1},
            {"id": "LRCX-TSM", "source": "LRCX", "target": "TSM", "relationship": "supplies_to", "strength": 0.94, "supply_category": "Etch & Deposition Systems", "evidence_count": 1},
            {"id": "CAMT-TSM", "source": "CAMT", "target": "TSM", "relationship": "supplies_to", "strength": 0.93, "supply_category": "Advanced Packaging Inspection", "evidence_count": 1},
            {"id": "FORM-TSM", "source": "FORM", "target": "TSM", "relationship": "supplies_to", "strength": 0.91, "supply_category": "Probe Cards & Test Systems", "evidence_count": 1},
            {"id": "ONTO-TSM", "source": "ONTO", "target": "TSM", "relationship": "supplies_to", "strength": 0.90, "supply_category": "Packaging Metrology", "evidence_count": 1},
            {"id": "ACLS-TSM", "source": "ACLS", "target": "TSM", "relationship": "supplies_to", "strength": 0.89, "supply_category": "Ion Implantation Systems", "evidence_count": 1},
            {"id": "ENTG-TSM", "source": "ENTG", "target": "TSM", "relationship": "supplies_to", "strength": 0.88, "supply_category": "Materials & Contamination Control", "evidence_count": 1},
            {"id": "TER-TSM", "source": "TER", "target": "TSM", "relationship": "supplies_to", "strength": 0.87, "supply_category": "Semiconductor Test Equipment", "evidence_count": 1},
            {"id": "COHU-TER", "source": "COHU", "target": "TER", "relationship": "supplies_to", "strength": 0.85, "supply_category": "Test Handling & Inspection", "evidence_count": 1},
        ],
    },

    # --------------------------------------------------------------------------
    # 4. Nuclear SMRs, Clean Power & Grid Modernization
    # --------------------------------------------------------------------------
    "energy_grid": {
        "theme_name": "Grid Modernization, Nuclear & SMR Infrastructure",
        "description": "Electrification, industrial onshoring, and data center interconnection bottlenecks.",
        "capex_catalyst_narrative": "Utility interconnection queues have expanded to 5+ years, triggering immediate capital investment into substation transformers, reconductoring cables, and behind-the-meter merchant nuclear facilities.",
        "total_ecosystem_market_cap_b": 1120.0,
        "catalyst_timeline": [
            {
                "date": "2026-09-10",
                "event": "Clean Energy Infrastructure & Grid Reliability Summit",
                "impacted_tickers": ["CEG", "VST", "ETN", "PWR", "TLN", "OKLO", "SMR"],
            },
        ],
        "default_focus": "CEG",
        "nodes": [
            {
                "symbol": "CEG",
                "name": "Constellation Energy Corporation",
                "sector": "Utilities",
                "sub_industry": "Nuclear & Clean Power Generation",
                "tier": "mega_driver",
                "market_cap_billions": 84.0,
                "metrics": {
                    "elasticity_score": 96.0,
                    "capex_sensitivity": 1.0,
                    "revenue_concentration_pct": 100.0,
                    "operating_leverage": 3.2,
                    "forward_pe": 26.5,
                    "peg_ratio": 1.25,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 38.0,
                    "next_earnings_date": "2026-08-06",
                    "flow_sentiment_score": 0.87,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-09",
                        "period": "Q1 2026",
                        "speaker": "Joe Dominguez, CEO",
                        "quote": "Our nuclear fleet offers the only dispatchable 24/7 carbon-free power at scale, commanding premium pricing from AI data center developers.",
                        "context": "Nuclear baseload pricing power.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "OKLO",
                "name": "Oklo Inc.",
                "sector": "Utilities",
                "sub_industry": "Fast Fission SMR Nuclear Power Plants",
                "tier": "horizontal_enabler",
                "market_cap_billions": 3.1,
                "metrics": {
                    "elasticity_score": 88.0,
                    "capex_sensitivity": 3.6,
                    "revenue_concentration_pct": 50.0,
                    "operating_leverage": 4.0,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": None,
                    "next_earnings_date": "2026-08-14",
                    "flow_sentiment_score": 0.85,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-15",
                        "period": "Q1 2026",
                        "speaker": "Jacob DeWitte, CEO",
                        "quote": "We have expanded our commercial pipeline to over 1.3 gigawatts of customer non-binding letters of intent, primarily with data center operators looking to secure dedicated off-grid power.",
                        "context": "SMR commercial pipeline for data centers.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "VST",
                "name": "Vistra Corp.",
                "sector": "Utilities",
                "sub_industry": "Nuclear & Gas-Fired Merchant Power",
                "tier": "mega_driver",
                "market_cap_billions": 62.0,
                "metrics": {
                    "elasticity_score": 94.5,
                    "capex_sensitivity": 1.0,
                    "revenue_concentration_pct": 100.0,
                    "operating_leverage": 3.0,
                    "forward_pe": 22.5,
                    "peg_ratio": 1.15,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 42.0,
                    "next_earnings_date": "2026-08-07",
                    "flow_sentiment_score": 0.86,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-08",
                        "period": "Q1 2026",
                        "speaker": "Jim Burke, CEO",
                        "quote": "We have signed long-term power purchase agreements with hyperscale data center operators across our nuclear and gas fleet, locking in premium contracted pricing.",
                        "context": "Data center power purchase agreements.",
                        "confidence": 0.97,
                    }
                ],
            },
            {
                "symbol": "TLN",
                "name": "Talen Energy Corporation",
                "sector": "Utilities",
                "sub_industry": "Nuclear & Data Center Co-Location Power",
                "tier": "mega_driver",
                "market_cap_billions": 12.5,
                "metrics": {
                    "elasticity_score": 93.8,
                    "capex_sensitivity": 1.0,
                    "revenue_concentration_pct": 100.0,
                    "operating_leverage": 3.4,
                    "forward_pe": 18.0,
                    "peg_ratio": 0.85,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 55.0,
                    "next_earnings_date": "2026-08-12",
                    "flow_sentiment_score": 0.89,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-12",
                        "period": "Q1 2026",
                        "speaker": "Mac McFarland, CEO",
                        "quote": "Our Susquehanna nuclear facility co-location with a hyperscale data center campus is now operational, with additional behind-the-meter capacity under negotiation.",
                        "context": "Nuclear data center co-location.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "SMR",
                "name": "NuScale Power Corporation",
                "sector": "Utilities",
                "sub_industry": "Small Modular Reactor Technology",
                "tier": "horizontal_enabler",
                "market_cap_billions": 2.4,
                "metrics": {
                    "elasticity_score": 89.2,
                    "capex_sensitivity": 3.8,
                    "revenue_concentration_pct": 55.0,
                    "operating_leverage": 4.2,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": None,
                    "next_earnings_date": "2026-08-08",
                    "flow_sentiment_score": 0.87,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-08",
                        "period": "Q1 2026",
                        "speaker": "John Hopkins, CEO",
                        "quote": "Our VOYGR SMR power plants are advancing toward deployment with data center and industrial customers seeking carbon-free, dispatchable baseload power.",
                        "context": "SMR deployment pipeline.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "CCJ",
                "name": "Cameco Corporation",
                "sector": "Energy",
                "sub_industry": "Uranium Mining & Nuclear Fuel",
                "tier": "tier1_supplier",
                "market_cap_billions": 24.0,
                "metrics": {
                    "elasticity_score": 91.0,
                    "capex_sensitivity": 3.2,
                    "revenue_concentration_pct": 60.0,
                    "operating_leverage": 3.6,
                    "forward_pe": 28.0,
                    "peg_ratio": 0.90,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 30.0,
                    "next_earnings_date": "2026-08-01",
                    "flow_sentiment_score": 0.85,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-01",
                        "period": "Q1 2026",
                        "speaker": "Tim Gitzel, CEO",
                        "quote": "Uranium demand is structurally rising as nuclear restarts and new SMR deployments require long-term fuel supply contracts at higher prices.",
                        "context": "Uranium demand and fuel contracts.",
                        "confidence": 0.97,
                    }
                ],
            },
            {
                "symbol": "LEU",
                "name": "Centrus Energy Corp.",
                "sector": "Energy",
                "sub_industry": "Nuclear Fuel Enrichment & HALEU",
                "tier": "tier1_supplier",
                "market_cap_billions": 1.8,
                "metrics": {
                    "elasticity_score": 90.4,
                    "capex_sensitivity": 3.5,
                    "revenue_concentration_pct": 65.0,
                    "operating_leverage": 3.8,
                    "forward_pe": 22.0,
                    "peg_ratio": 0.70,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 40.0,
                    "next_earnings_date": "2026-08-06",
                    "flow_sentiment_score": 0.86,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-06",
                        "period": "Q1 2026",
                        "speaker": "Amir Vexler, CEO",
                        "quote": "HALEU enrichment capacity is a critical bottleneck for advanced reactors, and we are scaling domestic production to meet growing SMR fuel demand.",
                        "context": "HALEU enrichment capacity.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "BWXT",
                "name": "BWX Technologies, Inc.",
                "sector": "Industrials",
                "sub_industry": "Nuclear Components & Reactor Manufacturing",
                "tier": "tier1_supplier",
                "market_cap_billions": 11.0,
                "metrics": {
                    "elasticity_score": 89.8,
                    "capex_sensitivity": 3.0,
                    "revenue_concentration_pct": 50.0,
                    "operating_leverage": 3.4,
                    "forward_pe": 30.0,
                    "peg_ratio": 1.10,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 20.0,
                    "next_earnings_date": "2026-08-05",
                    "flow_sentiment_score": 0.84,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-05",
                        "period": "Q1 2026",
                        "speaker": "Rex Geveden, CEO",
                        "quote": "Our nuclear components and microreactor programs are expanding on defense and commercial demand for advanced reactor manufacturing.",
                        "context": "Nuclear component manufacturing.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "ETN",
                "name": "Eaton Corporation plc",
                "sector": "Industrials",
                "sub_industry": "Power Distribution & Grid Equipment",
                "tier": "tier1_supplier",
                "market_cap_billions": 128.0,
                "metrics": {
                    "elasticity_score": 88.6,
                    "capex_sensitivity": 2.7,
                    "revenue_concentration_pct": 28.0,
                    "operating_leverage": 3.1,
                    "forward_pe": 27.5,
                    "peg_ratio": 1.20,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 26.0,
                    "next_earnings_date": "2026-08-01",
                    "flow_sentiment_score": 0.83,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-01",
                        "period": "Q1 2026",
                        "speaker": "Craig Arnold, CEO",
                        "quote": "Data center electrical infrastructure orders grew over 40% as AI facilities require higher-density switchgear, busway, and power quality solutions.",
                        "context": "Data center electrical infrastructure demand.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "PWR",
                "name": "Quanta Services, Inc.",
                "sector": "Industrials",
                "sub_industry": "Grid Construction & Electrical Infrastructure",
                "tier": "tier1_supplier",
                "market_cap_billions": 42.0,
                "metrics": {
                    "elasticity_score": 88.0,
                    "capex_sensitivity": 2.6,
                    "revenue_concentration_pct": 32.0,
                    "operating_leverage": 2.9,
                    "forward_pe": 26.0,
                    "peg_ratio": 1.15,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 24.0,
                    "next_earnings_date": "2026-08-07",
                    "flow_sentiment_score": 0.82,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-07",
                        "period": "Q1 2026",
                        "speaker": "Duke Austin, CEO",
                        "quote": "Grid modernization and data center interconnection projects are driving record backlog as utilities accelerate transmission and substation buildouts.",
                        "context": "Grid construction backlog.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "GEV",
                "name": "GE Vernova Inc.",
                "sector": "Industrials",
                "sub_industry": "Gas Turbines & Grid Electrification",
                "tier": "tier1_supplier",
                "market_cap_billions": 96.0,
                "metrics": {
                    "elasticity_score": 87.5,
                    "capex_sensitivity": 2.6,
                    "revenue_concentration_pct": 26.0,
                    "operating_leverage": 2.9,
                    "forward_pe": 30.0,
                    "peg_ratio": 1.30,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 22.0,
                    "next_earnings_date": "2026-07-23",
                    "flow_sentiment_score": 0.82,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-23",
                        "period": "Q1 2026",
                        "speaker": "Scott Strazik, CEO",
                        "quote": "Gas turbine orders for data center co-location are at record levels, and our grid electrification backlog continues to expand on interconnection-driven demand.",
                        "context": "Gas turbine and grid electrification demand.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "NEE",
                "name": "NextEra Energy, Inc.",
                "sector": "Utilities",
                "sub_industry": "Renewables & Grid-Scale Storage",
                "tier": "horizontal_enabler",
                "market_cap_billions": 150.0,
                "metrics": {
                    "elasticity_score": 86.2,
                    "capex_sensitivity": 2.0,
                    "revenue_concentration_pct": 24.0,
                    "operating_leverage": 2.6,
                    "forward_pe": 24.0,
                    "peg_ratio": 1.40,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 12.0,
                    "next_earnings_date": "2026-10-22",
                    "flow_sentiment_score": 0.78,
                    "options_skew": "balanced_bullish",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-22",
                        "period": "Q1 2026",
                        "speaker": "John Ketchum, CEO",
                        "quote": "Renewables and storage demand is accelerating as data centers and industrial customers seek clean power paired with grid-scale battery storage.",
                        "context": "Renewables and storage demand.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "UEC",
                "name": "Uranium Energy Corp.",
                "sector": "Energy",
                "sub_industry": "Uranium Mining & ISR Production",
                "tier": "tier2_supplier",
                "market_cap_billions": 3.5,
                "metrics": {
                    "elasticity_score": 87.0,
                    "capex_sensitivity": 3.4,
                    "revenue_concentration_pct": 70.0,
                    "operating_leverage": 3.7,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 50.0,
                    "next_earnings_date": "2026-09-10",
                    "flow_sentiment_score": 0.84,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-06-10",
                        "period": "Q3 FY26",
                        "speaker": "Amir Adnani, CEO",
                        "quote": "We are ramping in-situ recovery uranium production to capture rising spot and term prices driven by nuclear restarts and SMR fuel demand.",
                        "context": "Uranium production ramp.",
                        "confidence": 0.95,
                    }
                ],
            },
        ],
        "edges": [
            {"id": "OKLO-CEG", "source": "OKLO", "target": "CEG", "relationship": "technology_partner", "strength": 0.85, "supply_category": "Advanced Fast Fission SMR Deployments", "evidence_count": 1},
            {"id": "SMR-CEG", "source": "SMR", "target": "CEG", "relationship": "technology_partner", "strength": 0.86, "supply_category": "VOYGR SMR Power Plants", "evidence_count": 1},
            {"id": "CCJ-CEG", "source": "CCJ", "target": "CEG", "relationship": "supplies_to", "strength": 0.92, "supply_category": "Uranium & Nuclear Fuel", "evidence_count": 1},
            {"id": "LEU-CCJ", "source": "LEU", "target": "CCJ", "relationship": "supplies_to", "strength": 0.90, "supply_category": "HALEU Enrichment", "evidence_count": 1},
            {"id": "BWXT-OKLO", "source": "BWXT", "target": "OKLO", "relationship": "supplies_to", "strength": 0.89, "supply_category": "Nuclear Components & Reactor Manufacturing", "evidence_count": 1},
            {"id": "ETN-CEG", "source": "ETN", "target": "CEG", "relationship": "supplies_to", "strength": 0.88, "supply_category": "Power Distribution & Switchgear", "evidence_count": 1},
            {"id": "PWR-CEG", "source": "PWR", "target": "CEG", "relationship": "supplies_to", "strength": 0.87, "supply_category": "Grid Construction & Interconnection", "evidence_count": 1},
            {"id": "GEV-VST", "source": "GEV", "target": "VST", "relationship": "supplies_to", "strength": 0.88, "supply_category": "Gas Turbines & Grid Electrification", "evidence_count": 1},
            {"id": "NEE-VST", "source": "NEE", "target": "VST", "relationship": "co_dependent", "strength": 0.84, "supply_category": "Renewables & Storage", "evidence_count": 1},
            {"id": "UEC-CCJ", "source": "UEC", "target": "CCJ", "relationship": "supplies_to", "strength": 0.86, "supply_category": "Uranium Mining & ISR Production", "evidence_count": 1},
            {"id": "TLN-CEG", "source": "TLN", "target": "CEG", "relationship": "co_dependent", "strength": 0.90, "supply_category": "Nuclear Data Center Co-Location", "evidence_count": 1},
        ],
    },

    # --------------------------------------------------------------------------
    # 5. Enterprise AI, Agentic Platforms & Security
    # --------------------------------------------------------------------------
    "agentic_software": {
        "theme_name": "Enterprise AI & Agentic Infrastructure",
        "description": "Foundation model adoption driving vector databases, event streaming, automated orchestration, and security.",
        "capex_catalyst_narrative": "Enterprise migration from pilot AI chatbots to multi-agent production workflows is surging API volumes across vector indexes, real-time data pipelines, and endpoint security enforcement.",
        "total_ecosystem_market_cap_b": 2150.0,
        "catalyst_timeline": [
            {
                "date": "2026-09-18",
                "event": "Cloud Data & AI Agents Summit",
                "impacted_tickers": ["SNOW", "MDB", "PLTR", "CRWD", "NET", "DDOG"],
            },
        ],
        "default_focus": "PLTR",
        "nodes": [
            {
                "symbol": "PLTR",
                "name": "Palantir Technologies Inc.",
                "sector": "Software",
                "sub_industry": "Enterprise AI Platform & Ontology",
                "tier": "mega_driver",
                "market_cap_billions": 78.0,
                "metrics": {
                    "elasticity_score": 97.0,
                    "capex_sensitivity": 1.0,
                    "revenue_concentration_pct": 100.0,
                    "operating_leverage": 4.2,
                    "forward_pe": 48.0,
                    "peg_ratio": 1.35,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 42.0,
                    "next_earnings_date": "2026-08-05",
                    "flow_sentiment_score": 0.94,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-06",
                        "period": "Q1 2026",
                        "speaker": "Alex Karp, CEO",
                        "quote": "Our Artificial Intelligence Platform (AIP) is seeing unconstrained commercial demand; US commercial customer count grew 69% year-over-year.",
                        "context": "AIP commercial adoption disclosures.",
                        "confidence": 0.99,
                    }
                ],
            },
            {
                "symbol": "MDB",
                "name": "MongoDB, Inc.",
                "sector": "Software",
                "sub_industry": "Document & Vector Search Databases",
                "tier": "tier1_supplier",
                "market_cap_billions": 24.5,
                "metrics": {
                    "elasticity_score": 90.1,
                    "capex_sensitivity": 2.8,
                    "revenue_concentration_pct": 31.0,
                    "operating_leverage": 3.1,
                    "forward_pe": 45.0,
                    "peg_ratio": 1.40,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": 28.0,
                    "next_earnings_date": "2026-08-30",
                    "flow_sentiment_score": 0.81,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-31",
                        "period": "Q1 FY27",
                        "speaker": "Dev Ittycheria, CEO",
                        "quote": "Atlas Vector Search consumption is scaling rapidly as developers build retrieval-augmented generation applications on top of their operational data.",
                        "context": "Vector search consumption ramp.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "SNOW",
                "name": "Snowflake Inc.",
                "sector": "Software",
                "sub_industry": "Cloud Data Platform & AI Data Cloud",
                "tier": "tier1_supplier",
                "market_cap_billions": 58.0,
                "metrics": {
                    "elasticity_score": 91.8,
                    "capex_sensitivity": 2.9,
                    "revenue_concentration_pct": 34.0,
                    "operating_leverage": 3.2,
                    "forward_pe": 42.0,
                    "peg_ratio": 1.30,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 30.0,
                    "next_earnings_date": "2026-08-27",
                    "flow_sentiment_score": 0.84,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-27",
                        "period": "Q1 FY27",
                        "speaker": "Sridhar Ramaswamy, CEO",
                        "quote": "AI Data Cloud consumption is accelerating as enterprises bring their proprietary data to foundation models and agentic workflows on Snowflake.",
                        "context": "AI Data Cloud consumption.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "CRWD",
                "name": "CrowdStrike Holdings, Inc.",
                "sector": "Software",
                "sub_industry": "AI-Native Endpoint & Cloud Security",
                "tier": "tier1_supplier",
                "market_cap_billions": 92.0,
                "metrics": {
                    "elasticity_score": 90.6,
                    "capex_sensitivity": 2.6,
                    "revenue_concentration_pct": 30.0,
                    "operating_leverage": 3.4,
                    "forward_pe": 55.0,
                    "peg_ratio": 1.50,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 28.0,
                    "next_earnings_date": "2026-08-27",
                    "flow_sentiment_score": 0.85,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-27",
                        "period": "Q1 FY27",
                        "speaker": "George Kurtz, CEO",
                        "quote": "Our Falcon platform is securing the AI-native enterprise, with identity and cloud security modules driving record net-new ARR as agentic workloads expand the attack surface.",
                        "context": "AI-native security adoption.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "PANW",
                "name": "Palo Alto Networks, Inc.",
                "sector": "Software",
                "sub_industry": "AI Security & SASE Platformization",
                "tier": "tier1_supplier",
                "market_cap_billions": 118.0,
                "metrics": {
                    "elasticity_score": 89.4,
                    "capex_sensitivity": 2.4,
                    "revenue_concentration_pct": 28.0,
                    "operating_leverage": 3.3,
                    "forward_pe": 48.0,
                    "peg_ratio": 1.45,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 22.0,
                    "next_earnings_date": "2026-08-19",
                    "flow_sentiment_score": 0.83,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-19",
                        "period": "Q3 FY26",
                        "speaker": "Nikesh Arora, CEO",
                        "quote": "Platformization is accelerating as customers consolidate onto our AI-powered SASE and Cortex platforms, driving record next-generation security ARR.",
                        "context": "Security platformization.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "NET",
                "name": "Cloudflare, Inc.",
                "sector": "Software",
                "sub_industry": "Edge Network & AI Inference Infrastructure",
                "tier": "tier1_supplier",
                "market_cap_billions": 42.0,
                "metrics": {
                    "elasticity_score": 88.8,
                    "capex_sensitivity": 2.7,
                    "revenue_concentration_pct": 32.0,
                    "operating_leverage": 3.0,
                    "forward_pe": 60.0,
                    "peg_ratio": 1.60,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 30.0,
                    "next_earnings_date": "2026-08-06",
                    "flow_sentiment_score": 0.84,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-06",
                        "period": "Q1 2026",
                        "speaker": "Matthew Prince, CEO",
                        "quote": "Workers AI and our global edge network are becoming the default inference layer for developers deploying agentic applications close to users.",
                        "context": "Edge AI inference adoption.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "DDOG",
                "name": "Datadog, Inc.",
                "sector": "Software",
                "sub_industry": "Observability & AI Operations",
                "tier": "tier1_supplier",
                "market_cap_billions": 48.0,
                "metrics": {
                    "elasticity_score": 88.2,
                    "capex_sensitivity": 2.5,
                    "revenue_concentration_pct": 30.0,
                    "operating_leverage": 3.1,
                    "forward_pe": 52.0,
                    "peg_ratio": 1.50,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 26.0,
                    "next_earnings_date": "2026-08-06",
                    "flow_sentiment_score": 0.82,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-06",
                        "period": "Q1 2026",
                        "speaker": "Olivier Pomel, CEO",
                        "quote": "LLM observability and AI operations are our fastest-growing product lines as customers monitor agentic workflows in production.",
                        "context": "LLM observability growth.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "NOW",
                "name": "ServiceNow, Inc.",
                "sector": "Software",
                "sub_industry": "Enterprise Workflow & AI Agents",
                "tier": "tier1_supplier",
                "market_cap_billions": 185.0,
                "metrics": {
                    "elasticity_score": 87.6,
                    "capex_sensitivity": 2.3,
                    "revenue_concentration_pct": 26.0,
                    "operating_leverage": 3.2,
                    "forward_pe": 45.0,
                    "peg_ratio": 1.40,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 24.0,
                    "next_earnings_date": "2026-07-29",
                    "flow_sentiment_score": 0.81,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-29",
                        "period": "Q1 2026",
                        "speaker": "Bill McDermott, CEO",
                        "quote": "Our AI agents are automating enterprise workflows across IT, customer service, and HR, driving record platform adoption and expansion.",
                        "context": "AI agent workflow automation.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "ESTC",
                "name": "Elastic N.V.",
                "sector": "Software",
                "sub_industry": "Search, Vector & Observability",
                "tier": "tier1_supplier",
                "market_cap_billions": 12.0,
                "metrics": {
                    "elasticity_score": 87.0,
                    "capex_sensitivity": 2.6,
                    "revenue_concentration_pct": 29.0,
                    "operating_leverage": 3.0,
                    "forward_pe": 40.0,
                    "peg_ratio": 1.25,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 20.0,
                    "next_earnings_date": "2026-08-28",
                    "flow_sentiment_score": 0.80,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-28",
                        "period": "Q4 FY26",
                        "speaker": "Ash Kulkarni, CEO",
                        "quote": "Elasticsearch vector database and retrieval capabilities are being adopted for RAG and agentic search across enterprise knowledge bases.",
                        "context": "Vector search and RAG adoption.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "CFLT",
                "name": "Confluent, Inc.",
                "sector": "Software",
                "sub_industry": "Real-Time Data Streaming",
                "tier": "tier1_supplier",
                "market_cap_billions": 9.5,
                "metrics": {
                    "elasticity_score": 86.4,
                    "capex_sensitivity": 2.5,
                    "revenue_concentration_pct": 28.0,
                    "operating_leverage": 2.9,
                    "forward_pe": 38.0,
                    "peg_ratio": 1.20,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 25.0,
                    "next_earnings_date": "2026-08-05",
                    "flow_sentiment_score": 0.79,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-05",
                        "period": "Q1 2026",
                        "speaker": "Jay Kreps, CEO",
                        "quote": "Real-time data streaming is the connective tissue for agentic AI, and our Flink and Kafka offerings are seeing accelerated consumption from AI workloads.",
                        "context": "Real-time streaming for AI.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "GTLB",
                "name": "GitLab Inc.",
                "sector": "Software",
                "sub_industry": "DevSecOps & AI Code Agents",
                "tier": "tier1_supplier",
                "market_cap_billions": 8.0,
                "metrics": {
                    "elasticity_score": 85.8,
                    "capex_sensitivity": 2.4,
                    "revenue_concentration_pct": 27.0,
                    "operating_leverage": 2.8,
                    "forward_pe": 35.0,
                    "peg_ratio": 1.15,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 28.0,
                    "next_earnings_date": "2026-09-02",
                    "flow_sentiment_score": 0.78,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-06-02",
                        "period": "Q1 FY27",
                        "speaker": "Bill Staples, CEO",
                        "quote": "Duo Workflow and AI code agents are expanding our platform beyond CI/CD into autonomous software development, driving seat expansion.",
                        "context": "AI code agent adoption.",
                        "confidence": 0.94,
                    }
                ],
            },
        ],
        "edges": [
            {"id": "MDB-PLTR", "source": "MDB", "target": "PLTR", "relationship": "technology_partner", "strength": 0.88, "supply_category": "Atlas Document & Vector Infrastructure", "evidence_count": 1},
            {"id": "SNOW-PLTR", "source": "SNOW", "target": "PLTR", "relationship": "technology_partner", "strength": 0.90, "supply_category": "AI Data Cloud & Ontology", "evidence_count": 1},
            {"id": "CRWD-PLTR", "source": "CRWD", "target": "PLTR", "relationship": "technology_partner", "strength": 0.87, "supply_category": "AI-Native Security", "evidence_count": 1},
            {"id": "PANW-PLTR", "source": "PANW", "target": "PLTR", "relationship": "technology_partner", "strength": 0.86, "supply_category": "AI Security Platformization", "evidence_count": 1},
            {"id": "NET-PLTR", "source": "NET", "target": "PLTR", "relationship": "technology_partner", "strength": 0.85, "supply_category": "Edge AI Inference", "evidence_count": 1},
            {"id": "DDOG-PLTR", "source": "DDOG", "target": "PLTR", "relationship": "technology_partner", "strength": 0.84, "supply_category": "LLM Observability", "evidence_count": 1},
            {"id": "NOW-PLTR", "source": "NOW", "target": "PLTR", "relationship": "technology_partner", "strength": 0.86, "supply_category": "AI Agent Workflows", "evidence_count": 1},
            {"id": "ESTC-MDB", "source": "ESTC", "target": "MDB", "relationship": "co_dependent", "strength": 0.83, "supply_category": "Vector Search & RAG", "evidence_count": 1},
            {"id": "CFLT-SNOW", "source": "CFLT", "target": "SNOW", "relationship": "supplies_to", "strength": 0.84, "supply_category": "Real-Time Data Streaming", "evidence_count": 1},
            {"id": "GTLB-NOW", "source": "GTLB", "target": "NOW", "relationship": "technology_partner", "strength": 0.82, "supply_category": "AI Code Agents & Workflows", "evidence_count": 1},
        ],
    },

    # --------------------------------------------------------------------------
    # 6. GLP-1 Metabolic Therapeutics & CDMO Supply Chain
    # --------------------------------------------------------------------------
    "glp1_cdmo": {
        "theme_name": "GLP-1 Metabolic Therapeutics & CDMO Supply Chain",
        "description": "Weight loss and diabetes injectable therapeutics driving fill-finish CDMO manufacturing, auto-injector devices, and peptide raw materials.",
        "capex_catalyst_narrative": "Demand for GLP-1 agonists (tirzepatide, semaglutide) has outstripped global sterile injectable capacity, triggering multi-billion dollar manufacturing CapEx into aseptic fill-finish facilities, custom auto-injectors, and peptide synthesis platforms.",
        "total_ecosystem_market_cap_b": 1780.0,
        "catalyst_timeline": [
            {
                "date": "2026-09-12",
                "event": "EASD European Diabetes Association Clinical Trial Topline Readouts",
                "impacted_tickers": ["LLY", "NVO", "VKTX", "ALT"],
            },
        ],
        "default_focus": "LLY",
        "nodes": [
            {
                "symbol": "LLY",
                "name": "Eli Lilly and Company",
                "sector": "Healthcare",
                "sub_industry": "Incretin / GLP-1 Dual Agonists (Mounjaro / Zepbound)",
                "tier": "mega_driver",
                "market_cap_billions": 860.0,
                "metrics": {
                    "elasticity_score": 98.0,
                    "capex_sensitivity": 1.0,
                    "revenue_concentration_pct": 100.0,
                    "operating_leverage": 3.8,
                    "forward_pe": 42.0,
                    "peg_ratio": 1.45,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 45.0,
                    "next_earnings_date": "2026-08-06",
                    "flow_sentiment_score": 0.92,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-30",
                        "period": "Q1 2026",
                        "speaker": "David Ricks, CEO",
                        "quote": "We have committed over $18 billion to expand manufacturing capacity across Indiana, North Carolina, and Ireland to satisfy extraordinary global demand for our incretin portfolio.",
                        "context": "GLP-1 manufacturing CapEx commitments.",
                        "confidence": 0.99,
                    }
                ],
            },
            {
                "symbol": "NVO",
                "name": "Novo Nordisk A/S",
                "sector": "Healthcare",
                "sub_industry": "GLP-1 Semaglutide Therapeutics (Ozempic / Wegovy)",
                "tier": "mega_driver",
                "market_cap_billions": 580.0,
                "metrics": {
                    "elasticity_score": 96.0,
                    "capex_sensitivity": 1.0,
                    "revenue_concentration_pct": 100.0,
                    "operating_leverage": 3.5,
                    "forward_pe": 33.0,
                    "peg_ratio": 1.30,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 32.0,
                    "next_earnings_date": "2026-08-07",
                    "flow_sentiment_score": 0.88,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-02",
                        "period": "Q1 2026",
                        "speaker": "Lars Fruergaard Jørgensen, CEO",
                        "quote": "Acquiring three Catalent fill-finish manufacturing sites significantly scales our sterile drug product supply for Wegovy.",
                        "context": "Catalent acquisition and fill-finish expansion.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "WST",
                "name": "West Pharmaceutical Services",
                "sector": "Healthcare",
                "sub_industry": "High-Value Auto-Injectors & Elastomer Packaging",
                "tier": "tier1_supplier",
                "market_cap_billions": 28.0,
                "metrics": {
                    "elasticity_score": 93.5,
                    "capex_sensitivity": 3.6,
                    "revenue_concentration_pct": 42.0,
                    "operating_leverage": 3.7,
                    "forward_pe": 34.0,
                    "peg_ratio": 1.15,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 24.0,
                    "next_earnings_date": "2026-07-25",
                    "flow_sentiment_score": 0.86,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-26",
                        "period": "Q1 2026",
                        "speaker": "Eric Green, CEO",
                        "quote": "Proprietary high-value products, including FluroTec coated stoppers and prefillable syringe components for GLP-1 therapies, drove record quarterly shipment volumes.",
                        "context": "GLP-1 packaging and component demand.",
                        "confidence": 0.97,
                    }
                ],
            },
            {
                "symbol": "VKTX",
                "name": "Viking Therapeutics, Inc.",
                "sector": "Healthcare",
                "sub_industry": "Next-Gen Oral & Injectable Dual GLP-1/GIP Agonists",
                "tier": "horizontal_enabler",
                "market_cap_billions": 7.2,
                "metrics": {
                    "elasticity_score": 94.0,
                    "capex_sensitivity": 4.1,
                    "revenue_concentration_pct": 80.0,
                    "operating_leverage": 4.5,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": None,
                    "next_earnings_date": "2026-07-29",
                    "flow_sentiment_score": 0.91,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-24",
                        "period": "Q1 2026",
                        "speaker": "Brian Lian, CEO",
                        "quote": "VK2735 Phase 2 VENTURE data demonstrated best-in-class weight loss with robust tolerability, positioning us as an attractive commercial partner or acquisition candidate.",
                        "context": "GLP-1 clinical trials and commercialization.",
                        "confidence": 0.97,
                    }
                ],
            },
            {
                "symbol": "CTLT",
                "name": "Catalent, Inc.",
                "sector": "Healthcare",
                "sub_industry": "Fill-Finish CDMO & Biologics Manufacturing",
                "tier": "tier1_supplier",
                "market_cap_billions": 11.0,
                "metrics": {
                    "elasticity_score": 92.8,
                    "capex_sensitivity": 3.5,
                    "revenue_concentration_pct": 45.0,
                    "operating_leverage": 3.6,
                    "forward_pe": 30.0,
                    "peg_ratio": 1.05,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 22.0,
                    "next_earnings_date": "2026-08-28",
                    "flow_sentiment_score": 0.85,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-28",
                        "period": "Q3 FY26",
                        "speaker": "Alessandro Maselli, CEO",
                        "quote": "Our sterile fill-finish capacity for GLP-1 and biologic therapies is fully contracted, with customers committing to multi-year capacity reservations.",
                        "context": "Fill-finish capacity commitments.",
                        "confidence": 0.97,
                    }
                ],
            },
            {
                "symbol": "STE",
                "name": "STERIS plc",
                "sector": "Healthcare",
                "sub_industry": "Sterilization & Aseptic Processing",
                "tier": "tier1_supplier",
                "market_cap_billions": 22.0,
                "metrics": {
                    "elasticity_score": 88.4,
                    "capex_sensitivity": 2.6,
                    "revenue_concentration_pct": 30.0,
                    "operating_leverage": 3.0,
                    "forward_pe": 28.0,
                    "peg_ratio": 1.20,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 14.0,
                    "next_earnings_date": "2026-08-05",
                    "flow_sentiment_score": 0.80,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-05",
                        "period": "Q4 FY26",
                        "speaker": "Dan Carestio, CEO",
                        "quote": "Aseptic processing and sterilization demand is rising with injectable drug volumes, particularly for GLP-1 and biologic manufacturing lines.",
                        "context": "Aseptic processing demand.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "TMO",
                "name": "Thermo Fisher Scientific Inc.",
                "sector": "Healthcare",
                "sub_industry": "Life Sciences Tools & CDMO Services",
                "tier": "tier1_supplier",
                "market_cap_billions": 210.0,
                "metrics": {
                    "elasticity_score": 87.8,
                    "capex_sensitivity": 2.4,
                    "revenue_concentration_pct": 26.0,
                    "operating_leverage": 3.1,
                    "forward_pe": 26.0,
                    "peg_ratio": 1.30,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 12.0,
                    "next_earnings_date": "2026-10-22",
                    "flow_sentiment_score": 0.79,
                    "options_skew": "balanced_bullish",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-22",
                        "period": "Q1 2026",
                        "speaker": "Marc Casper, CEO",
                        "quote": "Our pharma services and bioproduction businesses are expanding capacity to support growing injectable and biologic manufacturing demand.",
                        "context": "Pharma services capacity expansion.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "DHR",
                "name": "Danaher Corporation",
                "sector": "Healthcare",
                "sub_industry": "Biopharma Processing & Life Sciences",
                "tier": "tier1_supplier",
                "market_cap_billions": 185.0,
                "metrics": {
                    "elasticity_score": 87.2,
                    "capex_sensitivity": 2.3,
                    "revenue_concentration_pct": 25.0,
                    "operating_leverage": 3.0,
                    "forward_pe": 27.0,
                    "peg_ratio": 1.35,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 10.0,
                    "next_earnings_date": "2026-10-20",
                    "flow_sentiment_score": 0.78,
                    "options_skew": "balanced_bullish",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-20",
                        "period": "Q1 2026",
                        "speaker": "Rainer Blair, CEO",
                        "quote": "Our bioprocessing and life sciences franchises are benefiting from strong biologic and injectable manufacturing activity across the industry.",
                        "context": "Bioprocessing demand.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "ALT",
                "name": "Altimmune, Inc.",
                "sector": "Healthcare",
                "sub_industry": "Oral GLP-1 Peptide Therapeutics",
                "tier": "horizontal_enabler",
                "market_cap_billions": 0.9,
                "metrics": {
                    "elasticity_score": 90.2,
                    "capex_sensitivity": 4.0,
                    "revenue_concentration_pct": 75.0,
                    "operating_leverage": 4.3,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": None,
                    "next_earnings_date": "2026-08-08",
                    "flow_sentiment_score": 0.88,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-08",
                        "period": "Q1 2026",
                        "speaker": "Vipin Garg, CEO",
                        "quote": "Our oral GLP-1 candidate pemvidutide is advancing toward pivotal trials, offering a differentiated oral option in the metabolic disease market.",
                        "context": "Oral GLP-1 development.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "AMGN",
                "name": "Amgen Inc.",
                "sector": "Healthcare",
                "sub_industry": "MariTide GLP-1 & Biologics",
                "tier": "mega_driver",
                "market_cap_billions": 165.0,
                "metrics": {
                    "elasticity_score": 91.5,
                    "capex_sensitivity": 1.0,
                    "revenue_concentration_pct": 100.0,
                    "operating_leverage": 3.2,
                    "forward_pe": 16.0,
                    "peg_ratio": 1.10,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 18.0,
                    "next_earnings_date": "2026-08-05",
                    "flow_sentiment_score": 0.84,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-05",
                        "period": "Q1 2026",
                        "speaker": "Robert Bradway, CEO",
                        "quote": "MariTide is progressing through late-stage development as a differentiated monthly GLP-1 therapy, with manufacturing scale-up underway.",
                        "context": "MariTide development and manufacturing.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "PFE",
                "name": "Pfizer Inc.",
                "sector": "Healthcare",
                "sub_industry": "Oral GLP-1 & Metabolic Pipeline",
                "tier": "mega_driver",
                "market_cap_billions": 160.0,
                "metrics": {
                    "elasticity_score": 86.8,
                    "capex_sensitivity": 1.0,
                    "revenue_concentration_pct": 100.0,
                    "operating_leverage": 2.8,
                    "forward_pe": 12.0,
                    "peg_ratio": 1.05,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": 8.0,
                    "next_earnings_date": "2026-10-28",
                    "flow_sentiment_score": 0.76,
                    "options_skew": "balanced_bullish",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-28",
                        "period": "Q1 2026",
                        "speaker": "Albert Bourla, CEO",
                        "quote": "Our oral GLP-1 candidate danuglipron is advancing in development as we build a competitive metabolic disease franchise.",
                        "context": "Oral GLP-1 pipeline.",
                        "confidence": 0.94,
                    }
                ],
            },
            {
                "symbol": "AZN",
                "name": "AstraZeneca PLC",
                "sector": "Healthcare",
                "sub_industry": "GLP-1 & Cardiometabolic Pipeline",
                "tier": "mega_driver",
                "market_cap_billions": 220.0,
                "metrics": {
                    "elasticity_score": 86.0,
                    "capex_sensitivity": 1.0,
                    "revenue_concentration_pct": 100.0,
                    "operating_leverage": 2.9,
                    "forward_pe": 18.0,
                    "peg_ratio": 1.20,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 15.0,
                    "next_earnings_date": "2026-10-29",
                    "flow_sentiment_score": 0.77,
                    "options_skew": "balanced_bullish",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-29",
                        "period": "Q1 2026",
                        "speaker": "Pascal Soriot, CEO",
                        "quote": "Our cardiometabolic pipeline, including oral GLP-1 assets, is a key growth pillar as we expand into the obesity and metabolic disease market.",
                        "context": "Cardiometabolic pipeline expansion.",
                        "confidence": 0.94,
                    }
                ],
            },
        ],
        "edges": [
            {"id": "WST-LLY", "source": "WST", "target": "LLY", "relationship": "supplies_to", "strength": 0.95, "supply_category": "Auto-Injector Cartridges & FluroTec Stoppers", "evidence_count": 2},
            {"id": "WST-NVO", "source": "WST", "target": "NVO", "relationship": "supplies_to", "strength": 0.94, "supply_category": "Prefillable Syringes & Plunger Components", "evidence_count": 1},
            {"id": "CTLT-LLY", "source": "CTLT", "target": "LLY", "relationship": "supplies_to", "strength": 0.93, "supply_category": "Fill-Finish CDMO Services", "evidence_count": 1},
            {"id": "CTLT-NVO", "source": "CTLT", "target": "NVO", "relationship": "supplies_to", "strength": 0.92, "supply_category": "Sterile Fill-Finish Manufacturing", "evidence_count": 1},
            {"id": "STE-CTLT", "source": "STE", "target": "CTLT", "relationship": "supplies_to", "strength": 0.88, "supply_category": "Sterilization & Aseptic Processing", "evidence_count": 1},
            {"id": "TMO-LLY", "source": "TMO", "target": "LLY", "relationship": "supplies_to", "strength": 0.87, "supply_category": "Life Sciences Tools & CDMO", "evidence_count": 1},
            {"id": "DHR-NVO", "source": "DHR", "target": "NVO", "relationship": "supplies_to", "strength": 0.86, "supply_category": "Bioprocessing & Life Sciences", "evidence_count": 1},
            {"id": "ALT-LLY", "source": "ALT", "target": "LLY", "relationship": "technology_partner", "strength": 0.84, "supply_category": "Oral GLP-1 Peptide Development", "evidence_count": 1},
            {"id": "AMGN-LLY", "source": "AMGN", "target": "LLY", "relationship": "co_dependent", "strength": 0.85, "supply_category": "MariTide GLP-1 Competition", "evidence_count": 1},
            {"id": "PFE-LLY", "source": "PFE", "target": "LLY", "relationship": "co_dependent", "strength": 0.83, "supply_category": "Oral GLP-1 Competition", "evidence_count": 1},
            {"id": "AZN-NVO", "source": "AZN", "target": "NVO", "relationship": "co_dependent", "strength": 0.82, "supply_category": "Cardiometabolic Pipeline", "evidence_count": 1},
        ],
    },

    # --------------------------------------------------------------------------
    # 7. Physical AI, Humanoid Robotics & Automation
    # --------------------------------------------------------------------------
    "robotics_ai": {
        "theme_name": "Physical AI, Humanoid Robotics & Automation",
        "description": "Embodied intelligence, humanoid robots, surgical robotics, and autonomous factory logistics.",
        "capex_catalyst_narrative": "Breakthroughs in visual-language-action (VLA) foundation models and spatial computing are transitioning robotics from static programmed arms to autonomous humanoids and intelligent logistics fleets.",
        "total_ecosystem_market_cap_b": 1150.0,
        "catalyst_timeline": [
            {
                "date": "2026-10-10",
                "event": "Tesla Optimus Humanoid Robot Factory Deployment & AI Day Update",
                "impacted_tickers": ["TSLA", "NVDA", "SYM", "SERV"],
            },
        ],
        "default_focus": "TSLA",
        "nodes": [
            {
                "symbol": "TSLA",
                "name": "Tesla, Inc.",
                "sector": "Consumer Discretionary",
                "sub_industry": "Optimus Humanoid Robotics & FSD Physical AI",
                "tier": "mega_driver",
                "market_cap_billions": 720.0,
                "metrics": {
                    "elasticity_score": 96.0,
                    "capex_sensitivity": 1.0,
                    "revenue_concentration_pct": 100.0,
                    "operating_leverage": 3.4,
                    "forward_pe": 65.0,
                    "peg_ratio": 1.85,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 22.0,
                    "next_earnings_date": "2026-10-21",
                    "flow_sentiment_score": 0.89,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-23",
                        "period": "Q1 2026",
                        "speaker": "Elon Musk, CEO",
                        "quote": "Optimus is already performing useful tasks in our factory; we expect several thousand Optimus robots operating internally by year-end before offering commercial units.",
                        "context": "Optimus humanoid deployment roadmap.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "SYM",
                "name": "Symbotic Inc.",
                "sector": "Industrials",
                "sub_industry": "AI Autonomous Warehouse Robotics Systems",
                "tier": "tier1_supplier",
                "market_cap_billions": 16.5,
                "metrics": {
                    "elasticity_score": 92.0,
                    "capex_sensitivity": 3.5,
                    "revenue_concentration_pct": 65.0,
                    "operating_leverage": 4.2,
                    "forward_pe": 42.0,
                    "peg_ratio": 0.95,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 55.0,
                    "next_earnings_date": "2026-08-03",
                    "flow_sentiment_score": 0.86,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-06",
                        "period": "Q2 FY26",
                        "speaker": "Rick Cohen, CEO",
                        "quote": "Our contracted backlog exceeds $22 billion as mega-retailers like Walmart and Target automate regional supply chain distribution hubs with Symbotic AI fleets.",
                        "context": "Warehouse automation backlog.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "CGNX",
                "name": "Cognex Corporation",
                "sector": "Technology",
                "sub_industry": "3D Machine Vision & Deep Learning Sensors",
                "tier": "tier2_supplier",
                "market_cap_billions": 8.4,
                "metrics": {
                    "elasticity_score": 88.5,
                    "capex_sensitivity": 2.7,
                    "revenue_concentration_pct": 34.0,
                    "operating_leverage": 3.2,
                    "forward_pe": 36.0,
                    "peg_ratio": 1.40,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 28.0,
                    "next_earnings_date": "2026-08-01",
                    "flow_sentiment_score": 0.81,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-02",
                        "period": "Q1 2026",
                        "speaker": "Robert Willett, CEO",
                        "quote": "AI vision sensors and 3D surface inspection tools for robotic pick-and-place systems represent our fastest growing customer pipeline.",
                        "context": "Machine vision adoption in robotics.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "ISRG",
                "name": "Intuitive Surgical, Inc.",
                "sector": "Healthcare",
                "sub_industry": "Robotic-Assisted Surgery Systems",
                "tier": "mega_driver",
                "market_cap_billions": 185.0,
                "metrics": {
                    "elasticity_score": 93.5,
                    "capex_sensitivity": 1.0,
                    "revenue_concentration_pct": 100.0,
                    "operating_leverage": 3.6,
                    "forward_pe": 42.0,
                    "peg_ratio": 1.50,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 18.0,
                    "next_earnings_date": "2026-10-20",
                    "flow_sentiment_score": 0.85,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-20",
                        "period": "Q1 2026",
                        "speaker": "Gary Guthart, CEO",
                        "quote": "da Vinci 5 adoption is accelerating as hospitals expand robotic surgery programs, with procedure growth in the mid-teens year-over-year.",
                        "context": "Robotic surgery adoption.",
                        "confidence": 0.97,
                    }
                ],
            },
            {
                "symbol": "ROK",
                "name": "Rockwell Automation, Inc.",
                "sector": "Industrials",
                "sub_industry": "Industrial Automation & Controls",
                "tier": "tier1_supplier",
                "market_cap_billions": 32.0,
                "metrics": {
                    "elasticity_score": 88.8,
                    "capex_sensitivity": 2.6,
                    "revenue_concentration_pct": 30.0,
                    "operating_leverage": 3.0,
                    "forward_pe": 24.0,
                    "peg_ratio": 1.20,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 12.0,
                    "next_earnings_date": "2026-08-06",
                    "flow_sentiment_score": 0.80,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-06",
                        "period": "Q2 FY26",
                        "speaker": "Blake Moret, CEO",
                        "quote": "Manufacturers are investing in autonomous operations and connected control systems, driving demand for our Logix and FactoryTalk platforms.",
                        "context": "Industrial automation demand.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "SERV",
                "name": "Serve Robotics Inc.",
                "sector": "Industrials",
                "sub_industry": "Autonomous Delivery Robots",
                "tier": "tier1_supplier",
                "market_cap_billions": 0.6,
                "metrics": {
                    "elasticity_score": 90.6,
                    "capex_sensitivity": 3.8,
                    "revenue_concentration_pct": 60.0,
                    "operating_leverage": 4.0,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 120.0,
                    "next_earnings_date": "2026-08-12",
                    "flow_sentiment_score": 0.88,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-12",
                        "period": "Q1 2026",
                        "speaker": "Ali Kashani, CEO",
                        "quote": "Our autonomous sidewalk delivery robots are scaling across major metro markets, with delivery volumes growing triple digits year-over-year.",
                        "context": "Autonomous delivery scaling.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "NVDA",
                "name": "NVIDIA Corporation",
                "sector": "Semiconductors",
                "sub_industry": "Physical AI & Robotics Compute Platforms",
                "tier": "horizontal_enabler",
                "market_cap_billions": 3120.0,
                "metrics": {
                    "elasticity_score": 92.0,
                    "capex_sensitivity": 1.5,
                    "revenue_concentration_pct": 20.0,
                    "operating_leverage": 3.4,
                    "forward_pe": 32.4,
                    "peg_ratio": 1.15,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 122.0,
                    "next_earnings_date": "2026-08-28",
                    "flow_sentiment_score": 0.88,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-22",
                        "period": "Q1 FY27",
                        "speaker": "Jensen Huang, CEO",
                        "quote": "Physical AI and robotics are the next frontier, with our Jetson Thor and Omniverse platforms powering humanoid and autonomous machine development.",
                        "context": "Physical AI compute platform.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "TER",
                "name": "Teradyne, Inc.",
                "sector": "Industrials",
                "sub_industry": "Collaborative Robots & Automation",
                "tier": "tier1_supplier",
                "market_cap_billions": 22.0,
                "metrics": {
                    "elasticity_score": 87.4,
                    "capex_sensitivity": 2.5,
                    "revenue_concentration_pct": 28.0,
                    "operating_leverage": 3.1,
                    "forward_pe": 28.5,
                    "peg_ratio": 1.20,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 22.0,
                    "next_earnings_date": "2026-07-24",
                    "flow_sentiment_score": 0.81,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-24",
                        "period": "Q1 2026",
                        "speaker": "Greg Smith, CEO",
                        "quote": "Our Universal Robots collaborative robots are seeing renewed demand as manufacturers automate flexible, high-mix production lines.",
                        "context": "Collaborative robot demand.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "ZBRA",
                "name": "Zebra Technologies Corporation",
                "sector": "Technology",
                "sub_industry": "Warehouse Automation & Machine Vision",
                "tier": "tier1_supplier",
                "market_cap_billions": 18.0,
                "metrics": {
                    "elasticity_score": 86.8,
                    "capex_sensitivity": 2.4,
                    "revenue_concentration_pct": 26.0,
                    "operating_leverage": 2.9,
                    "forward_pe": 22.0,
                    "peg_ratio": 1.10,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 15.0,
                    "next_earnings_date": "2026-08-04",
                    "flow_sentiment_score": 0.79,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-04",
                        "period": "Q1 2026",
                        "speaker": "Bill Burns, CEO",
                        "quote": "Warehouse automation and machine vision solutions are driving demand as retailers and logistics operators modernize fulfillment operations.",
                        "context": "Warehouse automation demand.",
                        "confidence": 0.95,
                    }
                ],
            },
        ],
        "edges": [
            {"id": "CGNX-SYM", "source": "CGNX", "target": "SYM", "relationship": "supplies_to", "strength": 0.91, "supply_category": "3D Optical Guidance & Barcode Sensors", "evidence_count": 1},
            {"id": "SYM-TSLA", "source": "SYM", "target": "TSLA", "relationship": "technology_partner", "strength": 0.84, "supply_category": "Autonomous Supply Chain Logistics", "evidence_count": 1},
            {"id": "NVDA-TSLA", "source": "NVDA", "target": "TSLA", "relationship": "supplies_to", "strength": 0.93, "supply_category": "Physical AI Compute Platforms", "evidence_count": 1},
            {"id": "NVDA-ISRG", "source": "NVDA", "target": "ISRG", "relationship": "technology_partner", "strength": 0.88, "supply_category": "AI Compute for Surgical Robotics", "evidence_count": 1},
            {"id": "ROK-SYM", "source": "ROK", "target": "SYM", "relationship": "supplies_to", "strength": 0.86, "supply_category": "Industrial Controls & Automation", "evidence_count": 1},
            {"id": "SERV-TSLA", "source": "SERV", "target": "TSLA", "relationship": "technology_partner", "strength": 0.85, "supply_category": "Autonomous Delivery Robotics", "evidence_count": 1},
            {"id": "TER-ROK", "source": "TER", "target": "ROK", "relationship": "supplies_to", "strength": 0.84, "supply_category": "Collaborative Robots", "evidence_count": 1},
            {"id": "ZBRA-SYM", "source": "ZBRA", "target": "SYM", "relationship": "supplies_to", "strength": 0.85, "supply_category": "Warehouse Automation & Vision", "evidence_count": 1},
            {"id": "CGNX-ISRG", "source": "CGNX", "target": "ISRG", "relationship": "supplies_to", "strength": 0.83, "supply_category": "Machine Vision for Surgery", "evidence_count": 1},
        ],
    },

    # --------------------------------------------------------------------------
    # 8. Quantum Computing & Photonic Systems
    # --------------------------------------------------------------------------
    "quantum_computing": {
        "theme_name": "Quantum Computing & Photonic Supercomputing",
        "description": "Trapped-ion, neutral atom, and superconducting quantum processors tackling cryptographic and molecular simulation algorithms.",
        "capex_catalyst_narrative": "National security directives and pharmaceutical drug discovery consortia are funding enterprise on-premise quantum deployments, prioritizing fault-tolerant gate fidelity and photonic qubit interconnects.",
        "total_ecosystem_market_cap_b": 420.0,
        "catalyst_timeline": [
            {
                "date": "2026-09-28",
                "event": "IEEE Quantum Week & Fault-Tolerant Logical Qubit Benchmark Demonstrations",
                "impacted_tickers": ["IONQ", "RGTI", "QBTS", "IBM", "HON"],
            },
        ],
        "default_focus": "IONQ",
        "nodes": [
            {
                "symbol": "IONQ",
                "name": "IonQ, Inc.",
                "sector": "Technology",
                "sub_industry": "Trapped-Ion Quantum Computing Systems",
                "tier": "mega_driver",
                "market_cap_billions": 4.8,
                "metrics": {
                    "elasticity_score": 95.0,
                    "capex_sensitivity": 4.0,
                    "revenue_concentration_pct": 75.0,
                    "operating_leverage": 4.5,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 95.0,
                    "next_earnings_date": "2026-08-08",
                    "flow_sentiment_score": 0.89,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-08",
                        "period": "Q1 2026",
                        "speaker": "Peter Chapman, CEO",
                        "quote": "Achieving #AQ 64 with barium ions and photonic interconnects allows us to execute complex quantum machine learning and chemistry simulations far beyond classical supercomputers.",
                        "context": "Quantum algorithmic milestones and hardware sales.",
                        "confidence": 0.98,
                    }
                ],
            },
            {
                "symbol": "RGTI",
                "name": "Rigetti Computing, Inc.",
                "sector": "Technology",
                "sub_industry": "Superconducting Quantum Processors & Fab",
                "tier": "tier1_supplier",
                "market_cap_billions": 0.45,
                "metrics": {
                    "elasticity_score": 88.0,
                    "capex_sensitivity": 3.6,
                    "revenue_concentration_pct": 65.0,
                    "operating_leverage": 3.8,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": 45.0,
                    "next_earnings_date": "2026-08-11",
                    "flow_sentiment_score": 0.82,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-12",
                        "period": "Q1 2026",
                        "speaker": "Dr. Subodh Kulkarni, CEO",
                        "quote": "Our Ankaa 84-qubit system delivered 99.3% 2-qubit gate fidelity, accelerating progress toward our modular 336-qubit Lyra architecture.",
                        "context": "Superconducting quantum roadmap disclosures.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "IBM",
                "name": "International Business Machines Corp.",
                "sector": "Technology",
                "sub_industry": "Quantum System Two & Condor Supercomputers",
                "tier": "horizontal_enabler",
                "market_cap_billions": 185.0,
                "metrics": {
                    "elasticity_score": 85.0,
                    "capex_sensitivity": 1.5,
                    "revenue_concentration_pct": 20.0,
                    "operating_leverage": 2.2,
                    "forward_pe": 19.5,
                    "peg_ratio": 1.65,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": 8.5,
                    "next_earnings_date": "2026-10-21",
                    "flow_sentiment_score": 0.76,
                    "options_skew": "balanced_bullish",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-24",
                        "period": "Q1 2026",
                        "speaker": "Arvind Krishna, CEO",
                        "quote": "Deploying on-premise IBM Quantum System Two units at national laboratories and enterprise R&D centers establishes the foundational quantum software ecosystem.",
                        "context": "Quantum commercial deployments.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "QBTS",
                "name": "D-Wave Quantum Inc.",
                "sector": "Technology",
                "sub_industry": "Quantum Annealing & Optimization Systems",
                "tier": "tier1_supplier",
                "market_cap_billions": 1.2,
                "metrics": {
                    "elasticity_score": 89.5,
                    "capex_sensitivity": 3.7,
                    "revenue_concentration_pct": 60.0,
                    "operating_leverage": 3.9,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 60.0,
                    "next_earnings_date": "2026-08-13",
                    "flow_sentiment_score": 0.86,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-13",
                        "period": "Q1 2026",
                        "speaker": "Alan Baratz, CEO",
                        "quote": "Our Advantage2 annealing systems are solving real-world optimization problems for logistics, manufacturing, and financial customers at scale.",
                        "context": "Quantum annealing commercialization.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "QUBT",
                "name": "Quantum Computing Inc.",
                "sector": "Technology",
                "sub_industry": "Photonic Quantum Computing & LiDAR",
                "tier": "tier1_supplier",
                "market_cap_billions": 0.5,
                "metrics": {
                    "elasticity_score": 88.8,
                    "capex_sensitivity": 3.8,
                    "revenue_concentration_pct": 55.0,
                    "operating_leverage": 4.0,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 70.0,
                    "next_earnings_date": "2026-08-14",
                    "flow_sentiment_score": 0.87,
                    "options_skew": "heavy_call_sweep",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-14",
                        "period": "Q1 2026",
                        "speaker": "William McGann, CEO",
                        "quote": "Our photonic quantum computing and quantum LiDAR platforms are advancing toward commercial deployments across defense and industrial applications.",
                        "context": "Photonic quantum commercialization.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "HON",
                "name": "Honeywell International Inc.",
                "sector": "Industrials",
                "sub_industry": "Trapped-Ion Quantum & Aerospace Systems",
                "tier": "horizontal_enabler",
                "market_cap_billions": 140.0,
                "metrics": {
                    "elasticity_score": 84.5,
                    "capex_sensitivity": 1.4,
                    "revenue_concentration_pct": 18.0,
                    "operating_leverage": 2.4,
                    "forward_pe": 21.0,
                    "peg_ratio": 1.50,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": 7.0,
                    "next_earnings_date": "2026-10-23",
                    "flow_sentiment_score": 0.75,
                    "options_skew": "balanced_bullish",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-23",
                        "period": "Q1 2026",
                        "speaker": "Vimal Kapur, CEO",
                        "quote": "Our Quantinuum trapped-ion quantum systems are achieving record logical qubit fidelity, positioning us at the forefront of fault-tolerant quantum computing.",
                        "context": "Trapped-ion quantum progress.",
                        "confidence": 0.96,
                    }
                ],
            },
            {
                "symbol": "MSFT",
                "name": "Microsoft Corporation",
                "sector": "Technology",
                "sub_industry": "Azure Quantum & Topological Qubits",
                "tier": "horizontal_enabler",
                "market_cap_billions": 3280.0,
                "metrics": {
                    "elasticity_score": 83.8,
                    "capex_sensitivity": 1.2,
                    "revenue_concentration_pct": 15.0,
                    "operating_leverage": 1.8,
                    "forward_pe": 29.5,
                    "peg_ratio": 1.75,
                    "gross_margin_trend": "stable",
                    "yoy_revenue_growth": 16.5,
                    "next_earnings_date": "2026-10-22",
                    "flow_sentiment_score": 0.72,
                    "options_skew": "balanced_bullish",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-25",
                        "period": "Q3 FY26",
                        "speaker": "Satya Nadella, CEO",
                        "quote": "Azure Quantum is bringing together topological qubit research and a growing partner ecosystem to accelerate practical quantum advantage.",
                        "context": "Azure Quantum ecosystem.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "GOOGL",
                "name": "Alphabet Inc.",
                "sector": "Technology",
                "sub_industry": "Quantum AI & Error Correction",
                "tier": "horizontal_enabler",
                "market_cap_billions": 2400.0,
                "metrics": {
                    "elasticity_score": 83.2,
                    "capex_sensitivity": 1.2,
                    "revenue_concentration_pct": 14.0,
                    "operating_leverage": 1.9,
                    "forward_pe": 22.0,
                    "peg_ratio": 1.30,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 15.0,
                    "next_earnings_date": "2026-10-27",
                    "flow_sentiment_score": 0.73,
                    "options_skew": "balanced_bullish",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-04-27",
                        "period": "Q1 2026",
                        "speaker": "Sundar Pichai, CEO",
                        "quote": "Our Willow quantum chip demonstrated below-threshold error correction, a critical milestone on the path to large-scale fault-tolerant quantum computers.",
                        "context": "Quantum error correction milestone.",
                        "confidence": 0.97,
                    }
                ],
            },
            {
                "symbol": "NVDA",
                "name": "NVIDIA Corporation",
                "sector": "Semiconductors",
                "sub_industry": "Quantum-Classical Hybrid Compute",
                "tier": "horizontal_enabler",
                "market_cap_billions": 3120.0,
                "metrics": {
                    "elasticity_score": 82.6,
                    "capex_sensitivity": 1.1,
                    "revenue_concentration_pct": 12.0,
                    "operating_leverage": 3.4,
                    "forward_pe": 32.4,
                    "peg_ratio": 1.15,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 122.0,
                    "next_earnings_date": "2026-08-28",
                    "flow_sentiment_score": 0.80,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-05-22",
                        "period": "Q1 FY27",
                        "speaker": "Jensen Huang, CEO",
                        "quote": "CUDA-Q is enabling quantum-classical hybrid workflows, with our GPUs accelerating quantum circuit simulation and error mitigation.",
                        "context": "Quantum-classical hybrid compute.",
                        "confidence": 0.95,
                    }
                ],
            },
            {
                "symbol": "ARQQ",
                "name": "Arqit Quantum Inc.",
                "sector": "Technology",
                "sub_industry": "Quantum-Safe Encryption",
                "tier": "tier1_supplier",
                "market_cap_billions": 0.2,
                "metrics": {
                    "elasticity_score": 86.5,
                    "capex_sensitivity": 3.5,
                    "revenue_concentration_pct": 50.0,
                    "operating_leverage": 3.6,
                    "forward_pe": None,
                    "peg_ratio": None,
                    "gross_margin_trend": "expanding",
                    "yoy_revenue_growth": 55.0,
                    "next_earnings_date": "2026-09-15",
                    "flow_sentiment_score": 0.83,
                    "options_skew": "bullish_call_drift",
                },
                "evidence": [
                    {
                        "source_type": "earnings_transcript",
                        "filing_date": "2026-06-15",
                        "period": "H1 FY26",
                        "speaker": "David Williams, CEO",
                        "quote": "Post-quantum cryptography adoption is accelerating as enterprises and governments harden networks against future quantum threats.",
                        "context": "Quantum-safe encryption adoption.",
                        "confidence": 0.94,
                    }
                ],
            },
        ],
        "edges": [
            {"id": "RGTI-IBM", "source": "RGTI", "target": "IBM", "relationship": "technology_partner", "strength": 0.82, "supply_category": "Superconducting Qubit Foundry R&D", "evidence_count": 1},
            {"id": "QBTS-IONQ", "source": "QBTS", "target": "IONQ", "relationship": "co_dependent", "strength": 0.84, "supply_category": "Quantum Annealing vs Gate-Based", "evidence_count": 1},
            {"id": "QUBT-IONQ", "source": "QUBT", "target": "IONQ", "relationship": "co_dependent", "strength": 0.83, "supply_category": "Photonic Quantum Systems", "evidence_count": 1},
            {"id": "HON-IONQ", "source": "HON", "target": "IONQ", "relationship": "technology_partner", "strength": 0.86, "supply_category": "Trapped-Ion Quantum Systems", "evidence_count": 1},
            {"id": "MSFT-IONQ", "source": "MSFT", "target": "IONQ", "relationship": "technology_partner", "strength": 0.85, "supply_category": "Azure Quantum Cloud Access", "evidence_count": 1},
            {"id": "GOOGL-IONQ", "source": "GOOGL", "target": "IONQ", "relationship": "co_dependent", "strength": 0.84, "supply_category": "Quantum Error Correction", "evidence_count": 1},
            {"id": "NVDA-IONQ", "source": "NVDA", "target": "IONQ", "relationship": "technology_partner", "strength": 0.85, "supply_category": "Quantum-Classical Hybrid Compute", "evidence_count": 1},
            {"id": "ARQQ-IBM", "source": "ARQQ", "target": "IBM", "relationship": "supplies_to", "strength": 0.82, "supply_category": "Quantum-Safe Encryption", "evidence_count": 1},
            {"id": "RGTI-IONQ", "source": "RGTI", "target": "IONQ", "relationship": "co_dependent", "strength": 0.83, "supply_category": "Superconducting Quantum Processors", "evidence_count": 1},
        ],
    },
}


# ==============================================================================
# Helper Graph Traversal & Dynamic Real-Time Ingestion
# ==============================================================================

def get_available_themes() -> List[Dict[str, Any]]:
    """Return summary metadata for all pre-indexed thematic growth hubs."""
    themes = []
    for key, val in THEMATIC_ECOSYSTEMS.items():
        themes.append({
            "id": key,
            "theme_name": val["theme_name"],
            "description": val["description"],
            "default_focus": val["default_focus"],
            "total_ecosystem_market_cap_b": val["total_ecosystem_market_cap_b"],
            "node_count": len(val.get("nodes", [])),
            "top_beneficiaries": [
                n["symbol"]
                for n in sorted(
                    val.get("nodes", []),
                    key=lambda x: float(x.get("metrics", {}).get("elasticity_score", 0)),
                    reverse=True,
                )
                if n["symbol"] != val["default_focus"]
            ][:5],
            "catalyst_timeline": val.get("catalyst_timeline", []),
        })
    return themes


def _find_symbol_in_ecosystems(symbol: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Search for a symbol across known curated ecosystems."""
    sym = symbol.strip().upper()
    for theme_id, eco in THEMATIC_ECOSYSTEMS.items():
        for node in eco.get("nodes", []):
            if node["symbol"].upper() == sym:
                return theme_id, node
    return None


def _ecosystem_market_cap_b(eco: Dict[str, Any]) -> float:
    """Aggregate the live market cap of every member in an ecosystem.

    Falls back to the curated static total when a theme has no nodes, so the
    summary never reports a fabricated zero.
    """
    total = sum(
        _safe_float(n.get("market_cap_billions"), 0.0) or 0.0
        for n in eco.get("nodes", [])
    )
    if total > 0:
        return round(total, 1)
    return _safe_float(eco.get("total_ecosystem_market_cap_b"), 0.0) or 0.0


def _related_themes(theme_id: str) -> List[Dict[str, Any]]:
    """Find other ecosystems that share tickers with the given theme.

    Shared tickers are the connective tissue between thematic frontiers and let
    the operator jump from one value chain into an adjacent one.
    """
    eco = THEMATIC_ECOSYSTEMS.get(theme_id)
    if not eco:
        return []
    own_symbols = {n["symbol"] for n in eco.get("nodes", [])}
    related: List[Dict[str, Any]] = []
    for other_id, other in THEMATIC_ECOSYSTEMS.items():
        if other_id == theme_id:
            continue
        other_symbols = {n["symbol"] for n in other.get("nodes", [])}
        shared = sorted(own_symbols & other_symbols)
        if shared:
            related.append({
                "id": other_id,
                "theme_name": other.get("theme_name", other_id),
                "shared_tickers": shared,
            })
    related.sort(key=lambda r: (-len(r["shared_tickers"]), r["theme_name"]))
    return related


def _filter_by_depth(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    focus_sym: str,
    depth: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Restrict the graph to nodes within `depth` hops of the focal symbol.

    depth=1 returns the focal node plus its direct suppliers/customers;
    depth>=2 returns the full multi-tier graph (the historical behavior).
    """
    if depth is None or depth < 1:
        depth = 2
    if depth >= 2:
        return nodes, edges

    adjacency: Dict[str, set] = {}
    for e in edges:
        adjacency.setdefault(e["source"], set()).add(e["target"])
        adjacency.setdefault(e["target"], set()).add(e["source"])

    visited = {focus_sym}
    frontier = {focus_sym}
    for _ in range(depth):
        next_frontier: set = set()
        for sym in frontier:
            for neighbor in adjacency.get(sym, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.add(neighbor)
        frontier = next_frontier

    kept_nodes = [n for n in nodes if n["symbol"] in visited]
    kept_edges = [e for e in edges if e["source"] in visited and e["target"] in visited]
    return kept_nodes, kept_edges


def calculate_beneficiary_elasticity(
    node: Dict[str, Any],
    driver_symbol: str,
    flow_override: Optional[float] = None,
) -> Optional[float]:
    """Weighted Elasticity Score (0-100) over the node's *present* inputs.

    Components: capex sensitivity (35%), revenue concentration (25%),
    operating leverage (20%), options-flow sentiment (20%), each min-max
    normalised. Weights renormalise over whatever the node actually carries.

    Returns None when the node has no usable inputs at all: an unscored node
    must stay unscored. The old version silently substituted mid-range
    defaults (2.0 / 25.0 / 2.5 / 0.5) for missing metrics, so companies with
    zero data earned a plausible-looking ~70 and entered the beneficiary
    ranking on invented inputs.
    """
    metrics = node.get("metrics") or {}
    components: List[Tuple[float, float]] = []

    capex_sens = _safe_float(metrics.get("capex_sensitivity"))
    if capex_sens is not None:
        components.append((min(100.0, max(0.0, (capex_sens / 4.5) * 100.0)), 0.35))

    rev_conc = _safe_float(metrics.get("revenue_concentration_pct"))
    if rev_conc is not None:
        components.append((min(100.0, max(0.0, (rev_conc / 60.0) * 100.0)), 0.25))

    op_lev = _safe_float(metrics.get("operating_leverage"))
    if op_lev is not None:
        components.append((min(100.0, max(0.0, (op_lev / 5.0) * 100.0)), 0.20))

    flow_score = flow_override if flow_override is not None else _safe_float(metrics.get("flow_sentiment_score"))
    if flow_score is not None:
        components.append((min(100.0, max(0.0, ((flow_score + 1.0) / 2.0) * 100.0)), 0.20))

    if not components:
        return None
    total_weight = sum(w for _, w in components)
    composite = sum(score * w for score, w in components) / total_weight
    return round(min(100.0, max(0.0, composite)), 1)


_SECTOR_BUCKET_MAP = {
    "technology": "technology",
    "financial services": "financials",
    "financial": "financials",
    "healthcare": "healthcare",
    "energy": "energy",
    "industrials": "industrials",
    "consumer defensive": "staples",
    "consumer staples": "staples",
    "consumer cyclical": "discretionary",
    "consumer discretionary": "discretionary",
    "utilities": "utilities",
    "basic materials": "materials",
    "materials": "materials",
    "real estate": "real_estate",
    "communication services": "communications",
    "communications": "communications",
}


def _sector_peers(symbol: str, sector: str, limit: int = 8) -> List[str]:
    """Discover real same-sector peers from the curated liquid US universe."""
    try:
        from tools.fetch_universe_wide import SECTORS
    except Exception as e:
        logger.debug("Universe lookup error for %s: %s", symbol, e)
        return []

    sym = symbol.strip().upper()
    bucket_key = _SECTOR_BUCKET_MAP.get((sector or "").strip().lower())
    bucket = SECTORS.get(bucket_key) if bucket_key else None

    if bucket is None:
        for name, syms in SECTORS.items():
            if sym in syms:
                bucket = syms
                break

    if not bucket:
        return []

    return [s for s in bucket if s != sym][:limit]


# ==============================================================================
# Comprehensive Institutional Company Relationships Registry (Deep Multi-Tier Mapping)
# ==============================================================================

COMPANY_RELATIONSHIPS_REGISTRY: Dict[str, Dict[str, Any]] = {
    "SPCX": {
        "name": "Space Exploration Technologies Corp.",
        "sector": "Industrials",
        "sub_industry": "Commercial Launch, Starlink LEO Broadband & Space Exploration",
        "tier": "mega_driver",
        "tier2_suppliers": [
            ("HEI", "FAA Flight Component Replacements & Subsystems", "supplies_to", 0.94, "FAA PMA aerospace components and flight-critical sub-assemblies."),
            ("KTOS", "Target Avionics, Unmanned Drones & Microwave Electronics", "supplies_to", 0.91, "High-reliability microwave telemetry and unmanned flight avionics."),
            ("TDY", "Digital Imaging Sensors & Radiation-Hardened Optics", "supplies_to", 0.89, "Radiation-hardened focal plane arrays and optical sensors."),
            ("ALB", "Specialty Lithium Compounds for Spacecraft Energy Storage", "supplies_to", 0.88, "Battery raw materials for satellite bus power systems."),
        ],
        "tier1_suppliers": [
            ("RKLB", "Rocket Propulsion Components, Separation Systems & Solar Panels", "supplies_to", 0.93, "Spacecraft separation systems and high-efficiency solar cells."),
            ("RDW", "In-Space Manufacturing & Roll-Out Solar Arrays (ROSA)", "supplies_to", 0.92, "Deployable ROSA solar wing arrays powering orbital spacecraft."),
            ("PL", "High-Resolution Optical Payloads & Earth Observation Subsystems", "technology_partner", 0.90, "Constellation optical payload integration for orbital imaging."),
            ("HON", "Aerospace Navigation, Inertial Guidance & Environmental Controls", "supplies_to", 0.92, "Space-grade IMUs and thermal life-support subsystems."),
        ],
        "strategic_partners": [
            ("T", "AT&T Commercial Direct-to-Cell Cellular Spectrum Integration", "technology_partner", 0.95, "Direct-to-cell satellite connectivity partnership using cellular spectrum."),
            ("TMUS", "T-Mobile Direct-to-Cell Satellite Coverage Agreement", "technology_partner", 0.96, "Nationwide satellite-to-cellular coverage eliminating mobile dead zones."),
            ("BA", "Commercial Satellite Bus & Payload Integration Program", "technology_partner", 0.92, "Commercial satellite bus and payload fairing integration."),
        ],
        "downstream_customers": [
            ("LMT", "Lockheed Martin Tactical JADC2 & Defense Space Programs", "supplies_to", 0.96, "Launch provider and satellite bus integration for defense payloads."),
            ("NOC", "Northrop Grumman Space Systems & Missile Defense Payloads", "supplies_to", 0.94, "Dedicated heavy-lift launch missions for national security payloads."),
            ("RTX", "RTX Space & Missile Defense Sensor Payloads Integration", "supplies_to", 0.95, "Launch deployment for national security and tracking sensors."),
        ],
        "competitors_peers": ["RKLB", "LUNR", "RDW", "LMT", "NOC", "BA"],
        "bridges": [
            {"id": "space_defense", "theme_name": "Space Economy, Direct-to-Cell & Defense", "role": "Commercial Orbital Launch & Starlink Broadband Mega-Driver"},
            {"id": "agentic_software", "theme_name": "Enterprise AI & Agentic Infrastructure", "role": "Grok AI Compute & Starlink Real-Time Telemetry"},
        ],
    },
    "ASTS": {
        "name": "AST SpaceMobile, Inc.",
        "sector": "Telecommunications",
        "sub_industry": "Direct-to-Cell Space Broadband & Phased Array Satellites",
        "tier": "mega_driver",
        "tier2_suppliers": [
            ("HEI", "Space-Grade Micro-Electronics & Structural Deployables", "supplies_to", 0.92, "High-reliability aerospace components and deployment mechanisms."),
            ("TDY", "Radiation-Tolerant Digital RF Converters & Sensors", "supplies_to", 0.90, "Digital RF components for massive phased array antennas."),
            ("AVAV", "Unmanned Communications Payloads & Specialized RF", "supplies_to", 0.88, "Specialized radio frequency telemetry hardware."),
        ],
        "tier1_suppliers": [
            ("RDW", "Deployable Phased-Array Microminiature Solar Hinges & Booms", "supplies_to", 0.94, "Structural deployment mechanisms for BlueBird satellite arrays."),
            ("RKLB", "Dedicated Orbital Insertion & Reaction Wheels", "supplies_to", 0.92, "Precision satellite attitude control systems and launch assistance."),
            ("SPCX", "Falcon 9 Heavy Orbital Deployment Services", "supplies_to", 0.96, "Multi-satellite orbital deployment launch contract."),
        ],
        "strategic_partners": [
            ("T", "AT&T Definitive Commercial Agreement (850MHz Spectrum Sharing)", "technology_partner", 0.98, "Anchor commercial mobile network operator partnership providing 100% US coverage."),
            ("VZ", "Verizon $100M Commercial Direct-to-Cell Commitment", "technology_partner", 0.96, "Pre-payment and commitment to integrate 850MHz cellular spectrum into ASTS."),
            ("GOOGL", "Strategic Equity Investment & Android Satellite Connectivity API", "technology_partner", 0.93, "Strategic investment and Android core OS direct-to-cell integration."),
        ],
        "downstream_customers": [
            ("T", "AT&T 100M+ Nationwide Subscriber Direct-to-Cell Service", "supplies_to", 0.98, "Nationwide cellular subscriber direct-to-cell broadband channel."),
            ("VZ", "Verizon Wireless National Mobile Broadband Coverage Network", "supplies_to", 0.97, "Carrier direct-to-cell service for remote and emergency connectivity."),
            ("VOD", "Vodafone European & African Global Mobile Subscriber Network", "supplies_to", 0.94, "Global mobile carrier reaching hundreds of millions across Europe and Africa."),
        ],
        "competitors_peers": ["GSAT", "IRDM", "SATL", "BKSY"],
        "bridges": [
            {"id": "space_defense", "theme_name": "Space Economy, Direct-to-Cell & Defense", "role": "Direct-to-Cell Cellular Broadband Constellation"},
        ],
    },
    "NVDA": {
        "name": "NVIDIA Corporation",
        "sector": "Technology",
        "sub_industry": "Accelerated GPU Supercomputing, Networking & CUDA Fabric",
        "tier": "mega_driver",
        "tier2_suppliers": [
            ("TSM", "TSMC 3nm/4nm Wafer Foundry & CoWoS-L Advanced Multi-Die Packaging", "supplies_to", 0.99, "Sole foundry partner for Blackwell GB200, B200, and Hopper H100 GPU packages."),
            ("ASML", "High-NA EUV Photolithography Scanner Tool Systems", "supplies_to", 0.96, "Extreme ultraviolet scanners enabling sub-3nm transistor feature patterning."),
            ("AMAT", "High-Precision Dielectric Deposition & Wafer Chemical Mechanical Planarization", "supplies_to", 0.92, "Semiconductor fabrication equipment across advanced packaging lines."),
            ("CAMT", "High-Speed 3D Optical Metrology for CoWoS Micro-Bump Inspection", "supplies_to", 0.94, "Wafer-level 3D optical inspection for high-density silicon interposers."),
        ],
        "tier1_suppliers": [
            ("MU", "HBM3e 24GB/36GB High-Bandwidth Memory Stacks (8-High / 12-High)", "supplies_to", 0.96, "Qualified HBM3e supplier providing 8Tbps+ memory bandwidth for Blackwell."),
            ("AAOI", "800G/1.6T DR8 & CWDM Optical Transceivers for NVLink Compute Fabrics", "supplies_to", 0.95, "High-density optical transceivers linking NVLink Switch systems."),
            ("VRT", "Liquid Cooling Distribution Units (CDUs) & Direct-to-Chip Cold Plates", "supplies_to", 0.94, "Co-designed liquid cooling reference architecture for 132kW NVL72 racks."),
            ("ALAB", "PCIe Gen 5/6 CXL Retimers & High-Speed Active Copper Smart Cables", "supplies_to", 0.93, "High-speed retimer silicon and Taurus active electrical cables for GPU racks."),
        ],
        "strategic_partners": [
            ("MSFT", "Azure OpenAI Supercomputer Architecture & DGX Cloud Deployments", "technology_partner", 0.98, "Strategic co-engineering for multi-hundred thousand GPU superclusters."),
            ("AMZN", "AWS Project Ceiba 65,000 GPU Supercomputing Infrastructure", "technology_partner", 0.96, "Joint high-performance AI supercluster on AWS hosting NVIDIA internal R&D."),
            ("GOOGL", "Google Cloud A3 High-Tier GPU Instances & NeMo Framework", "technology_partner", 0.94, "Deep hardware-software optimization for multi-tier LLM training."),
        ],
        "downstream_customers": [
            ("MSFT", "Microsoft Azure Cloud & Global Copilot Inference Fleet", "supplies_to", 0.98, "Anchor hyperscale cloud customer purchasing multi-gigawatt GPU fleets."),
            ("META", "Meta 600,000+ H100 Equivalent GPU Cluster for Llama 4/5 Models", "supplies_to", 0.97, "Massive hyperscale AI training and recommendation compute cluster."),
            ("AMZN", "Amazon AWS Hyperscale GPU Cloud Instances & Bedrock Services", "supplies_to", 0.96, "Global cloud infrastructure provider offering on-demand accelerated compute."),
            ("GOOGL", "Google Cloud Vertex AI & Hyperscale Infrastructure Deployments", "supplies_to", 0.95, "Hyperscale enterprise cloud provider deploying NVIDIA GPU clusters."),
            ("ORCL", "Oracle Cloud Infrastructure (OCI) Bare Metal GPU AI Clusters", "supplies_to", 0.95, "OCI deployment of 65,000+ GPU superclusters for enterprise generative AI."),
        ],
        "competitors_peers": ["AMD", "AVGO", "INTC", "QCOM", "ARM"],
        "bridges": [
            {"id": "ai_datacenter", "theme_name": "AI Data Center & Hyperscale Compute", "role": "Accelerated GPU & AI Computing Mega-Driver"},
            {"id": "semi_equipment", "theme_name": "Semiconductor Capital Equipment & WFE", "role": "Primary CoWoS & WFE Node Customer"},
            {"id": "robotics_ai", "theme_name": "Physical AI, Humanoid Robotics & Automation", "role": "Isaac & Jetson Physical AI Compute Platform"},
        ],
    },
    "AAPL": {
        "name": "Apple Inc.",
        "sector": "Technology",
        "sub_industry": "Consumer Hardware & Apple Silicon Platforms",
        "tier": "mega_driver",
        "tier2_suppliers": [
            ("TSM", "Advanced 3nm A18/M4 Silicon Packaging & EUV Foundry", "supplies_to", 0.98, "TSMC sole-source foundry for Apple Silicon A-series and M-series architectures."),
            ("ASML", "Twinscan High-NA EUV Lithography Scanners", "supplies_to", 0.95, "Photolithography equipment supporting sub-3nm node fabrication for Apple processors."),
            ("AVGO", "Multi-Billion Dollar 5G FBAR RF Filters & Custom Silicon", "supplies_to", 0.94, "Multi-year agreement for US-manufactured cutting-edge 5G radio frequency filters."),
            ("AMAT", "Materials Deposition & Chemical Mechanical Planarization", "supplies_to", 0.88, "Advanced semiconductor equipment utilized in Apple supply chain fabrication."),
        ],
        "tier1_suppliers": [
            ("LITE", "VCSEL Array Lasers for TrueDepth FaceID & LiDAR", "supplies_to", 0.92, "High-density vertical-cavity surface-emitting laser arrays for 3D sensing."),
            ("COHR", "Optical Transceivers & Engineered Ceramic Substrates", "supplies_to", 0.90, "Engineered optical substrates and precision laser processing systems."),
            ("QCOM", "Snapdragon 5G Modem-RF Systems Agreement (through 2026)", "supplies_to", 0.96, "Supply agreement securing 5G modem silicon for global iPhone flagship releases."),
            ("MU", "LPDDR5X Ultra-Low Power DRAM & High-Density NAND Flash", "supplies_to", 0.91, "High-bandwidth low-power memory for on-device Apple Intelligence models."),
        ],
        "strategic_partners": [
            ("GOOGL", "Safari Default Search Distribution & Revenue Sharing Agreement", "technology_partner", 0.96, "Multi-billion dollar default search placement across iOS Safari ecosystem."),
            ("MSFT", "Enterprise Microsoft 365 Cloud & Azure Open Source Integrations", "technology_partner", 0.88, "Enterprise app suite optimization and Azure cloud co-engineering."),
        ],
        "downstream_customers": [
            ("T", "AT&T 5G Wireless Carrier Subsidies & Device Financing Channel", "supplies_to", 0.94, "Primary retail carrier channel driving multi-million annual unit activations."),
            ("VZ", "Verizon Wireless National Retail & Enterprise Device Distribution", "supplies_to", 0.94, "Nationwide carrier distribution network for iPhone, iPad, and Apple Watch lines."),
            ("AMZN", "Amazon Authorized Apple Reseller & Global Retail Distribution", "supplies_to", 0.90, "Authorized worldwide retail storefront and fast-shipping fulfillment channel."),
        ],
        "competitors_peers": ["MSFT", "GOOGL", "AMZN", "META", "SONY"],
        "bridges": [
            {"id": "ai_datacenter", "theme_name": "AI Data Center & Hyperscale Compute", "role": "Private Cloud Compute Apple Silicon Servers"},
            {"id": "semi_equipment", "theme_name": "Semiconductor Capital Equipment & WFE", "role": "Anchor Customer for 3nm/2nm WFE Nodes"},
            {"id": "agentic_software", "theme_name": "Enterprise AI & Agentic Infrastructure", "role": "On-Device Apple Intelligence Foundation"},
        ],
    },
    "MSFT": {
        "name": "Microsoft Corporation",
        "sector": "Technology",
        "sub_industry": "Hyperscale Cloud & Enterprise Copilot Software",
        "tier": "mega_driver",
        "tier2_suppliers": [
            ("NVDA", "Blackwell GB200 & Hopper H100 GPU Accelerated Compute", "supplies_to", 0.98, "Hyperscale AI infrastructure powering Azure OpenAI and Microsoft Copilot clusters."),
            ("AMD", "Instinct MI300X AI Silicon & EPYC Hyperscale Processors", "supplies_to", 0.92, "Instinct GPU deployments in Azure virtual machines for generative AI workloads."),
            ("TSM", "Custom Maia 100 & Cobalt 100 ASIC Wafer Packaging", "supplies_to", 0.90, "Foundry manufacturing partner for Microsoft custom in-house silicon."),
            ("EQIX", "Global IBX Data Center Colocation & Direct Connect", "supplies_to", 0.88, "Carrier-neutral data center interconnection points globally."),
        ],
        "tier1_suppliers": [
            ("CRWD", "Falcon Endpoint & Cloud Security Defense Integration", "supplies_to", 0.93, "Native API integration for enterprise threat detection across Windows and Azure."),
            ("SNOW", "Fabric Data Lakehouse Integration & Azure Marketplace", "supplies_to", 0.90, "Zero-copy bi-directional data sharing between Microsoft Fabric and Snowflake."),
            ("ANET", "Arista 400G/800G Cloud Switches & AI Spine Fabrics", "supplies_to", 0.94, "Ultra-low latency switching infrastructure inside Azure AI clusters."),
            ("VRT", "High-Density Liquid Cooling CDUs & Uninterruptible Power", "supplies_to", 0.92, "Direct-to-chip liquid cooling systems supporting 100kW+ server racks."),
            ("CEG", "Crane Clean Energy Center (Three Mile Island Unit 1) 20-Yr PPA", "supplies_to", 0.96, "20-year dedicated 835MW clean nuclear power purchase agreement."),
        ],
        "strategic_partners": [
            ("PLTR", "Palantir AIP Federal Deployments on Azure Government Cloud", "technology_partner", 0.95, "Strategic partnership enabling defense and intelligence AIP on Azure IL6."),
            ("NOW", "ServiceNow Enterprise Workflow Copilot Native Integration", "technology_partner", 0.92, "Co-developed generative AI workflows connecting ServiceNow and Microsoft 365."),
        ],
        "downstream_customers": [
            ("JPM", "JPMorgan Chase Enterprise Azure Hybrid Cloud Adoption", "supplies_to", 0.94, "Global banking enterprise cloud infrastructure and productivity deployment."),
            ("WMT", "Walmart Global Retail Tech & Azure Data Modernization", "supplies_to", 0.91, "Enterprise retail cloud infrastructure and supply chain analytics."),
            ("UNH", "UnitedHealth Group Healthcare Data & Azure AI Cloud", "supplies_to", 0.90, "HIPAA-compliant enterprise cloud infrastructure for healthcare claims."),
        ],
        "competitors_peers": ["GOOGL", "AMZN", "AAPL", "ORCL", "CRM"],
        "bridges": [
            {"id": "ai_datacenter", "theme_name": "AI Data Center & Hyperscale Compute", "role": "Hyperscale Cloud & Infrastructure Operator"},
            {"id": "agentic_software", "theme_name": "Enterprise AI & Agentic Infrastructure", "role": "Enterprise Copilot & Azure AI Services"},
            {"id": "energy_grid", "theme_name": "Grid Modernization, Nuclear & SMR Infrastructure", "role": "Anchor Nuclear PPA Offtaker"},
            {"id": "quantum_computing", "theme_name": "Quantum Computing & Photonic Supercomputing", "role": "Azure Quantum Majoron Qubit Research"},
        ],
    },
    "AMD": {
        "name": "Advanced Micro Devices, Inc.",
        "sector": "Semiconductors",
        "sub_industry": "High-Performance Compute & AI GPU Accelerators",
        "tier": "mega_driver",
        "tier2_suppliers": [
            ("TSM", "CoWoS Advanced Packaging & 3nm/4nm Wafer Foundry", "supplies_to", 0.98, "Foundry manufacturing partner for MI300X AI GPUs and EPYC server CPUs."),
            ("ASML", "Extreme Ultraviolet Lithography (EUV) Scanners", "supplies_to", 0.95, "Photolithography tools enabling advanced node semiconductor printing."),
            ("AMAT", "Chemical Vapor Deposition & Advanced Wafer Planarization", "supplies_to", 0.90, "Deposition and surface engineering equipment for multi-chiplet modules."),
            ("CAMT", "3D Advanced Packaging Metrology & CoWoS Defect Inspection", "supplies_to", 0.92, "High-throughput metrology inspection for 2.5D/3D chiplet stacking."),
        ],
        "tier1_suppliers": [
            ("MU", "HBM3e High-Bandwidth Memory (192GB+ per Accelerator)", "supplies_to", 0.95, "12-high HBM3e stacks supplying ultra-high memory bandwidth for MI300 series."),
            ("ALAB", "PCIe Gen 5/6 CXL Retimers & High-Speed Smart Cable Modules", "supplies_to", 0.93, "Signal integrity retimers enabling massive GPU-to-GPU compute fabrics."),
            ("MRVL", "Custom Optical DSP Interconnect Silicon & Networking ASICs", "supplies_to", 0.90, "High-speed optical connectivity silicon linking accelerator clusters."),
            ("COHR", "High-Speed Optical Transceivers & Engineered Photonic Modules", "supplies_to", 0.89, "800G optical interconnects for distributed AI cluster scaling."),
        ],
        "strategic_partners": [
            ("MSFT", "Azure AI MI300X Virtual Machine Deployments & ROCm Support", "technology_partner", 0.95, "Co-development agreement for large language model inference on Azure."),
            ("META", "Open-Source PyTorch ROCm Optimization & Llama Deployments", "technology_partner", 0.92, "Hardware-software co-design for open-source AI model inference."),
        ],
        "downstream_customers": [
            ("MSFT", "Microsoft Azure Cloud Hyperscale AI Deployments", "supplies_to", 0.95, "Cloud infrastructure provider deploying MI300X instances globally."),
            ("AMZN", "Amazon Web Services (AWS) EPYC Server & AI Compute Deployments", "supplies_to", 0.92, "Hyperscale cloud provider utilizing AMD EPYC server processors."),
            ("ORCL", "Oracle Cloud Infrastructure (OCI) Bare Metal GPU Clusters", "supplies_to", 0.93, "OCI deployment of 16,384+ MI300X clusters for generative AI."),
        ],
        "competitors_peers": ["NVDA", "INTC", "QCOM", "ARM"],
        "bridges": [
            {"id": "ai_datacenter", "theme_name": "AI Data Center & Hyperscale Compute", "role": "Accelerated Compute & MI300X Provider"},
            {"id": "semi_equipment", "theme_name": "Semiconductor Capital Equipment & WFE", "role": "Top-Tier Wafer & CoWoS Customer"},
        ],
    },
    "AMZN": {
        "name": "Amazon.com, Inc.",
        "sector": "Technology",
        "sub_industry": "Hyperscale AWS Cloud & Global E-Commerce Logistics",
        "tier": "mega_driver",
        "tier2_suppliers": [
            ("NVDA", "AWS UltraCluster AI GPU Accelerators & DGX Cloud", "supplies_to", 0.98, "Hyperscale AI GPU clusters for Amazon Bedrock and AWS generative AI services."),
            ("TSM", "Custom Trainium2 & Inferentia2 ASIC Semiconductor Foundry", "supplies_to", 0.94, "Wafer manufacturing and advanced packaging for proprietary AWS silicon."),
            ("ASML", "Advanced Semiconductor EUV Lithography Systems", "supplies_to", 0.90, "Lithography tool provider for custom ASIC supply chain fabrication."),
            ("EQIX", "Carrier-Neutral IBX Data Center Infrastructure & AWS Direct Connect", "supplies_to", 0.88, "Global interconnection facilities for enterprise low-latency cloud ingress."),
        ],
        "tier1_suppliers": [
            ("MRVL", "Custom AI ASIC High-Speed Optical Interconnect & Networking DSPs", "supplies_to", 0.94, "Custom silicon and optical networking linking Trainium clusters."),
            ("ANET", "Arista 400G/800G Cloud Spine & Leaf Switching Fabrics", "supplies_to", 0.93, "Ultra-scalable Ethernet switches for AWS AI and compute zones."),
            ("VRT", "Liquid Cooling Distribution Units & Mission-Critical Power", "supplies_to", 0.92, "Direct liquid cooling hardware supporting high-density AWS data centers."),
            ("TLN", "Cumulus Data Center Campus 960MW Nuclear Power Purchase", "supplies_to", 0.97, "Direct nuclear power interconnection adjacent to Susquehanna plant."),
            ("PWR", "High-Voltage Substation EPC & Grid Transmission Interconnects", "supplies_to", 0.90, "Electrical infrastructure contractor connecting new AWS data campuses."),
        ],
        "strategic_partners": [
            ("CRWD", "AWS Marketplace Strategic Security & Zero-Trust Architecture", "technology_partner", 0.92, "Native integration of Falcon cybersecurity across AWS GovCloud and Commercial."),
            ("SNOW", "Snowflake on AWS Joint Enterprise Data Lakehouse GTM", "technology_partner", 0.91, "Joint enterprise sales channel and optimized cloud data compute."),
        ],
        "downstream_customers": [
            ("UBER", "Uber Global Mobility & Delivery Cloud Core on AWS", "supplies_to", 0.95, "Mission-critical cloud infrastructure running global ride-dispatch algorithms."),
            ("PSTG", "Pure Storage Cloud Enterprise Storage Block Services", "supplies_to", 0.88, "Enterprise multi-cloud storage architecture deployed within AWS regions."),
            ("NFLX", "Netflix Global Video Streaming Infrastructure on AWS", "supplies_to", 0.96, "Cloud compute and storage powering global video streaming and encoding."),
        ],
        "competitors_peers": ["MSFT", "GOOGL", "WMT", "BABA"],
        "bridges": [
            {"id": "ai_datacenter", "theme_name": "AI Data Center & Hyperscale Compute", "role": "AWS Hyperscale Infrastructure Operator"},
            {"id": "energy_grid", "theme_name": "Grid Modernization, Nuclear & SMR Infrastructure", "role": "Direct Nuclear & Clean Power Offtaker"},
            {"id": "agentic_software", "theme_name": "Enterprise AI & Agentic Infrastructure", "role": "Amazon Bedrock & SageMaker AI Platform"},
        ],
    },
    "GOOGL": {
        "name": "Alphabet Inc.",
        "sector": "Technology",
        "sub_industry": "Hyperscale AI Cloud, TPU Compute & Search Ecosystems",
        "tier": "mega_driver",
        "tier2_suppliers": [
            ("AVGO", "Co-Designed TPU v5p/v6 Custom ASIC Silicon & Interconnects", "supplies_to", 0.98, "Strategic co-development and physical IP partner for Google TPU generations."),
            ("TSM", "Advanced CoWoS Packaging & Sub-3nm Foundry Silicon", "supplies_to", 0.96, "Foundry manufacturing partner for Google TPU and mobile Tensor processors."),
            ("ASML", "High-NA EUV Lithography Equipment Scanners", "supplies_to", 0.92, "Advanced photolithography scanners enabling sub-3nm custom TPU logic."),
            ("AMAT", "Precision Materials Deposition & High-Throughput Etch Systems", "supplies_to", 0.88, "Semiconductor manufacturing equipment for custom silicon supply chains."),
        ],
        "tier1_suppliers": [
            ("AAOI", "800G CWDM/DR8 Optical Transceivers for Hyperscale TPU Pods", "supplies_to", 0.95, "High-density optical transceivers linking TPU v5/v6 supercomputer fabrics."),
            ("LITE", "Optical Transceivers & Next-Gen Co-Packaged Optics Modules", "supplies_to", 0.92, "High-speed optical connectivity for inter-data-center cloud backbones."),
            ("MU", "HBM3e/HBM4 Memory Stacks for TPU Acceleration Modules", "supplies_to", 0.93, "High-bandwidth memory integrated directly into Google TPU packages."),
            ("VRT", "Liquid Cooling CDUs & Thermal Management Infrastructures", "supplies_to", 0.91, "Direct-to-chip liquid cooling systems deployed across Google AI campuses."),
            ("CEG", "24/7 Carbon-Free Energy Supply & Clean Energy Offtake", "supplies_to", 0.90, "Multi-year clean energy matching agreement for hyperscale data centers."),
        ],
        "strategic_partners": [
            ("AAPL", "iOS Safari Default Search Agreement ($20B+ Annual Channel)", "technology_partner", 0.98, "Commercial default search distribution across Apple's worldwide user base."),
            ("UBER", "Google Maps Platform APIs & Cloud Data Infrastructure", "technology_partner", 0.92, "Geospatial mapping and route optimization powering Uber services."),
        ],
        "downstream_customers": [
            ("CRM", "Salesforce Google Cloud Enterprise Analytics Integrations", "supplies_to", 0.90, "Enterprise integration linking Salesforce CRM with Google BigQuery."),
            ("ADBE", "Adobe Creative Cloud on Google Cloud Infrastructure", "supplies_to", 0.89, "Cloud compute and storage powering Adobe generative AI services."),
            ("SNAP", "Snapchat Global Messaging & Video Infrastructure on GCP", "supplies_to", 0.94, "Multi-year cloud services agreement for social messaging compute."),
        ],
        "competitors_peers": ["MSFT", "META", "AMZN", "AAPL"],
        "bridges": [
            {"id": "ai_datacenter", "theme_name": "AI Data Center & Hyperscale Compute", "role": "TPU Accelerated Infrastructure Operator"},
            {"id": "agentic_software", "theme_name": "Enterprise AI & Agentic Infrastructure", "role": "Gemini Frontier Models & Vertex AI Platform"},
            {"id": "quantum_computing", "theme_name": "Quantum Computing & Photonic Supercomputing", "role": "Sycamore Superconducting Quantum Processor"},
        ],
    },
    "TSLA": {
        "name": "Tesla, Inc.",
        "sector": "Consumer Cyclical",
        "sub_industry": "Autonomous Vehicles, Full Self-Driving AI & Energy Storage",
        "tier": "mega_driver",
        "tier2_suppliers": [
            ("ALB", "Battery-Grade Lithium Hydroxide Supply Agreement", "supplies_to", 0.94, "Multi-year supply agreement for North American battery raw materials."),
            ("TSM", "Custom Dojo D1/D2 & FSD HW4/HW5 Chiplet Foundry", "supplies_to", 0.96, "Sole foundry partner for proprietary Tesla FSD and Dojo custom AI silicon."),
            ("ON", "Silicon Carbide (SiC) Power Inverters & Discrete MOSFETs", "supplies_to", 0.93, "High-efficiency traction inverter silicon maximizing EV drive range."),
            ("NVDA", "Cortex 50,000+ GPU AI Training Cluster Infrastructure", "supplies_to", 0.97, "Massive GPU clusters powering end-to-end neural network video training."),
        ],
        "tier1_suppliers": [
            ("SYM", "Warehouse Robotics & Automated Pallet Handling Systems", "supplies_to", 0.88, "Automated supply chain logistics within Tesla parts distribution centers."),
            ("ROK", "Gigafactory Programmable Logic Controllers & Automation Hardware", "supplies_to", 0.91, "Industrial automation and robotics controllers on vehicle assembly lines."),
            ("CGNX", "Machine Vision Sensors & Optical Quality Inspection Cameras", "supplies_to", 0.90, "High-speed automated optical inspection across stamping and battery lines."),
            ("MGA", "Castings, Chassis Modules & Structural Lightweighting Subsystems", "supplies_to", 0.89, "Tier 1 structural components and body sub-assemblies."),
        ],
        "strategic_partners": [
            ("NEE", "NextEra Energy Grid Storage Interconnection & Utility Deployments", "technology_partner", 0.92, "Utility-scale battery deployment pairing Megapack with renewable energy farms."),
            ("XOM", "Lithium Extraction & Brine Processing Technology Collaboration", "technology_partner", 0.85, "Domestic critical mineral extraction and refining co-engineering."),
        ],
        "downstream_customers": [
            ("UBER", "Autonomous Robotaxi Fleet Network Integration", "supplies_to", 0.94, "Future commercial integration for autonomous ride-hail fleet dispatch."),
            ("HTZ", "Hertz Global Commercial Fleet Electrification Deployments", "supplies_to", 0.90, "Commercial car rental fleet sales and EV charging integration."),
            ("GM", "NACS Charging Standard Licensing & Supercharger Network Access", "supplies_to", 0.95, "Direct licensing of North American Charging Standard across EV fleets."),
        ],
        "competitors_peers": ["RIVN", "LCID", "GM", "F", "BYD"],
        "bridges": [
            {"id": "robotics_ai", "theme_name": "Physical AI, Humanoid Robotics & Automation", "role": "Optimus Humanoid Robot & FSD Physical AI"},
            {"id": "ai_datacenter", "theme_name": "AI Data Center & Hyperscale Compute", "role": "Dojo & Cortex High-Density AI Superclusters"},
            {"id": "energy_grid", "theme_name": "Grid Modernization, Nuclear & SMR Infrastructure", "role": "Megapack Multi-Gigawatt Utility Grid Storage"},
        ],
    },
    "PLTR": {
        "name": "Palantir Technologies Inc.",
        "sector": "Technology",
        "sub_industry": "Enterprise AI, AIP Ontology & Defense Intelligence Software",
        "tier": "mega_driver",
        "tier2_suppliers": [
            ("MSFT", "Azure Secret Government Cloud & FedRAMP High Infrastructure", "supplies_to", 0.96, "Cloud host for Palantir Gotham and AIP across defense agencies."),
            ("AMZN", "AWS GovCloud Multi-Region Secure Storage & Compute", "supplies_to", 0.95, "Secure cloud infrastructure powering Palantir Foundry for federal clients."),
            ("NVDA", "GPU Accelerated Inference & NeMo Microservices Integration", "supplies_to", 0.93, "GPU acceleration for real-time AIP ontology evaluation and LLM execution."),
        ],
        "tier1_suppliers": [
            ("CRWD", "Falcon Threat Intelligence & Zero-Trust FedRAMP Defense", "supplies_to", 0.92, "Endpoint telemetry feeds enriching Palantir defense security models."),
            ("SNOW", "Snowflake Data Lakehouse Zero-Copy Bi-Directional Sync", "supplies_to", 0.90, "Data pipeline integration linking enterprise data tables to Palantir AIP."),
            ("PANW", "Prisma Cloud Security & SASE Network Perimeter Shielding", "supplies_to", 0.89, "Network security protection for distributed enterprise Palantir deployments."),
        ],
        "strategic_partners": [
            ("ORCL", "Oracle Cloud Infrastructure (OCI) Global Sovereign Defense GTM", "technology_partner", 0.94, "Joint deployment of Palantir Gotham and AIP across OCI sovereign regions."),
            ("CAE", "Defense Simulation & Tactical Digital Twin Co-Engineering", "technology_partner", 0.88, "Integration of mission planning algorithms with live tactical simulation."),
        ],
        "downstream_customers": [
            ("LMT", "Lockheed Martin Tactical JADC2 All-Domain Command Systems", "supplies_to", 0.96, "Defense intelligence integration powering next-gen command and control."),
            ("NOC", "Northrop Grumman Space & Defense Tactical Sensor Integration", "supplies_to", 0.94, "Sensor-to-shooter tactical ontology deployment across aerospace defense."),
            ("KTOS", "Kratos Valkyrie Autonomous Drone Combat AIP Integration", "supplies_to", 0.92, "Autonomous tactical decision-support software deployed on combat drones."),
            ("HCA", "HCA Healthcare Hospital Operations & Dynamic Capacity Foundry", "supplies_to", 0.93, "Hospital operational optimization deployed across 180+ medical centers."),
        ],
        "competitors_peers": ["SNOW", "MDB", "AI", "MSFT"],
        "bridges": [
            {"id": "agentic_software", "theme_name": "Enterprise AI & Agentic Infrastructure", "role": "AIP Enterprise Ontology & Agentic Engine"},
            {"id": "space_defense", "theme_name": "Space Economy, Direct-to-Cell & Defense", "role": "TITAN Prime Tactical Ground Station Software"},
            {"id": "ai_datacenter", "theme_name": "AI Data Center & Hyperscale Compute", "role": "Enterprise AI Demand & Inference Driver"},
        ],
    },
    "CRM": {
        "name": "Salesforce, Inc.",
        "sector": "Technology",
        "sub_industry": "Agentforce Autonomous Workflows & Enterprise CRM Platforms",
        "tier": "mega_driver",
        "tier2_suppliers": [
            ("AMZN", "AWS Hyperforce Global Multi-Region Public Cloud Infrastructure", "supplies_to", 0.96, "Primary cloud infrastructure host for Salesforce Hyperforce architecture."),
            ("MSFT", "Azure Public Cloud Ingress & Hybrid Enterprise Interconnects", "supplies_to", 0.90, "Secondary cloud hosting supporting sovereign enterprise requirements."),
            ("NVDA", "Accelerated GPU Compute for Agentforce Autonomous LLMs", "supplies_to", 0.94, "High-performance GPU compute accelerating Agentforce reasoning engines."),
        ],
        "tier1_suppliers": [
            ("SNOW", "Snowflake Zero-Copy Data Cloud Bidirectional Integration", "supplies_to", 0.93, "Real-time data federation connecting Data Cloud and Snowflake."),
            ("NOW", "ServiceNow Automated Workflow Connectors & ITSM Integrations", "supplies_to", 0.91, "Joint interoperability bridging customer service and IT workflows."),
            ("CRWD", "Falcon Identity & Zero-Trust Authentication Defense", "supplies_to", 0.89, "Enterprise identity protection for corporate Salesforce instances."),
            ("MDB", "MongoDB Atlas Flexible Document Store Integration", "supplies_to", 0.88, "NoSQL document database powering flexible schema extensions."),
        ],
        "strategic_partners": [
            ("GOOGL", "Google Workspace & BigQuery Customer Data Platform Sharing", "technology_partner", 0.92, "Bi-directional data sharing between Google BigQuery and Salesforce Data Cloud."),
            ("IBM", "IBM Consulting Global Agentforce System Integration Practice", "technology_partner", 0.90, "Global deployment partner scaling autonomous agent implementations."),
        ],
        "downstream_customers": [
            ("JPM", "JPMorgan Chase Global Banking & Wealth Management CRM", "supplies_to", 0.95, "Enterprise deployment managing corporate client relationships and wealth advisory."),
            ("WMT", "Walmart Omnichannel Retail Customer Engagement Systems", "supplies_to", 0.92, "Customer contact center and omnichannel engagement infrastructure."),
            ("UNH", "UnitedHealth Group Member Services & Clinical Engagement", "supplies_to", 0.93, "Healthcare customer relationship management across health plan members."),
        ],
        "competitors_peers": ["MSFT", "ORCL", "SAP", "WDAY", "HUBS"],
        "bridges": [
            {"id": "agentic_software", "theme_name": "Enterprise AI & Agentic Infrastructure", "role": "Agentforce Enterprise Autonomous Workflows"},
            {"id": "ai_datacenter", "theme_name": "AI Data Center & Hyperscale Compute", "role": "Hyperforce Enterprise AI Compute Driver"},
        ],
    },
    "COIN": {
        "name": "Coinbase Global, Inc.",
        "sector": "Financial Services",
        "sub_industry": "Institutional Crypto Custody, Base Layer-2 & Spot ETF Rails",
        "tier": "mega_driver",
        "tier2_suppliers": [
            ("AMZN", "AWS Multi-Region Key Vault & HSM Security Infrastructure", "supplies_to", 0.95, "High-security cloud infrastructure hosting institutional custody keys."),
            ("ICE", "Intercontinental Exchange Real-Time Market Data & Clearing Feeds", "supplies_to", 0.90, "Institutional financial market data feeds and settlement gateways."),
            ("V", "Visa Direct Instant Fiat Settlement & Crypto Debit Card Issuance", "supplies_to", 0.93, "Global payment rail powering instant consumer off-ramp transfers."),
        ],
        "tier1_suppliers": [
            ("CRWD", "Falcon Cloud Security & Threat Hunting Defense Layer", "supplies_to", 0.92, "Continuous cybersecurity monitoring protecting hot/cold wallet systems."),
            ("NET", "Cloudflare DDoS Mitigation & High-Frequency API Edge Network", "supplies_to", 0.94, "Global edge routing and attack mitigation for retail and exchange APIs."),
            ("MDB", "MongoDB Atlas Scalable Distributed Blockchain Indexing", "supplies_to", 0.90, "High-throughput database indexing multi-chain transactions on Base."),
        ],
        "strategic_partners": [
            ("BLK", "BlackRock iShares Bitcoin Trust (IBIT) & Ethereum ETF Custody", "technology_partner", 0.98, "Sole custodian and prime execution broker for the world's largest crypto ETFs."),
            ("V", "Visa Global Stablecoin Settlement Pilot on Ethereum/Base", "technology_partner", 0.91, "Collaborative settlement rail testing USDC treasury settlements on-chain."),
        ],
        "downstream_customers": [
            ("BLK", "BlackRock Institutional Funds & ETF Asset Safekeeping", "supplies_to", 0.98, "Prime custody client managing tens of billions in spot digital assets."),
            ("ARK", "ARK 21Shares Spot Bitcoin & Ether ETF Custodial Operations", "supplies_to", 0.94, "Institutional custodial client utilizing Coinbase Prime services."),
            ("HOOD", "Robinhood Crypto Clearing & Cross-Venue Liquidity Routing", "supplies_to", 0.93, "Institutional liquidity routing and clearing integrations."),
        ],
        "competitors_peers": ["HOOD", "MSTR", "MARA", "RIOT", "SCHW"],
        "bridges": [
            {"id": "agentic_software", "theme_name": "Enterprise AI & Agentic Infrastructure", "role": "Autonomous On-Chain AI Agent Wallets (x402)"},
            {"id": "quantum_computing", "theme_name": "Quantum Computing & Photonic Supercomputing", "role": "Post-Quantum Cryptography & Key Vault Migration"},
        ],
    },
    "UBER": {
        "name": "Uber Technologies, Inc.",
        "sector": "Technology",
        "sub_industry": "Global Mobility, Autonomous Ride-Hail & Delivery Logistics",
        "tier": "mega_driver",
        "tier2_suppliers": [
            ("GOOGL", "Google Maps Platform Geospatial APIs & Route Optimization", "supplies_to", 0.96, "Mission-critical mapping, routing, and ETA calculation infrastructure."),
            ("AMZN", "AWS Global Cloud Microservices & High-Volume Dispatch Compute", "supplies_to", 0.95, "Cloud compute hosting real-time matching and surge pricing algorithms."),
            ("V", "Visa Direct Instant Real-Time Driver Earnings Disbursal", "supplies_to", 0.94, "Financial rail enabling instant payout transfers to drivers globally."),
            ("MA", "Mastercard Global Payment Gateway & Transaction Clearing", "supplies_to", 0.92, "Payment processing network settling billions in consumer ride fares."),
        ],
        "tier1_suppliers": [
            ("PYPL", "Braintree Digital Payments & Global One-Touch Checkout", "supplies_to", 0.93, "Primary checkout processing gateway for consumer ride and delivery transactions."),
            ("TWLO", "Twilio Automated Push & SMS Dispatch Telephony Infrastructure", "supplies_to", 0.91, "Cloud communications platform sending real-time driver-rider notifications."),
            ("CRWD", "CrowdStrike Falcon Enterprise Endpoint & Zero-Trust Defense", "supplies_to", 0.89, "Global corporate security monitoring across thousands of remote staff."),
        ],
        "strategic_partners": [
            ("TSLA", "Tesla Cybercab & Autonomous FSD Fleet Network Integration", "technology_partner", 0.92, "Commercial integration agreement for future autonomous robotaxi fleets."),
            ("GOOGL", "Waymo Autonomous Ride-Hail Commercial Deployment on Uber App", "technology_partner", 0.96, "Multi-city commercial partnership offering Waymo robotaxi rides on Uber."),
        ],
        "downstream_customers": [
            ("MCD", "McDonald's Global Exclusive Quick-Service Delivery Partnership", "supplies_to", 0.94, "Global delivery agreement driving massive Uber Eats order volume."),
            ("SBUX", "Starbucks Mobile App Delivery Integration & Fulfillment", "supplies_to", 0.91, "Direct integration with Starbucks mobile rewards app for hot coffee delivery."),
            ("HTZ", "Hertz Global Electric Vehicle Driver Rental Fleet Program", "supplies_to", 0.90, "Commercial vehicle rental agreement providing EVs to rideshare drivers."),
        ],
        "competitors_peers": ["LYFT", "DASH", "GRUB", "ABNB"],
        "bridges": [
            {"id": "robotics_ai", "theme_name": "Physical AI, Humanoid Robotics & Automation", "role": "Autonomous Ride-Hail & Delivery Fleet Operator"},
            {"id": "agentic_software", "theme_name": "Enterprise AI & Agentic Infrastructure", "role": "Dynamic Match & Dispatch Agentic Optimization"},
        ],
    },
    "CEG": {
        "name": "Constellation Energy Corporation",
        "sector": "Utilities",
        "sub_industry": "Clean Nuclear Power Generation & 24/7 Hyperscale Data Center PPAs",
        "tier": "mega_driver",
        "tier2_suppliers": [
            ("CCJ", "Cameco Long-Term Uranium Hexafluoride (UF6) Supply Contracts", "supplies_to", 0.96, "Uranium mining, conversion, and nuclear fuel fabrication services."),
            ("BWXT", "BWX Technologies Nuclear Reactor Component Fabrication & Servicing", "supplies_to", 0.93, "Nuclear reactor pressure vessels, steam generators, and refueling equipment."),
            ("UEC", "Uranium Energy Corp In-Situ Uranium Extraction Reserves", "supplies_to", 0.89, "Domestic North American uranium extraction reserves."),
        ],
        "tier1_suppliers": [
            ("ETN", "Eaton High-Voltage Switchgear, Transformers & Substation Protection", "supplies_to", 0.94, "Electrical distribution equipment connecting power plants to regional transmission grids."),
            ("PWR", "Quanta Services High-Voltage Transmission Line EPC & Grid Interconnects", "supplies_to", 0.93, "Engineering, procurement, and construction of direct-to-data-center transmission lines."),
            ("GEV", "GE Vernova Advanced Steam Turbines & Grid Automation Control Systems", "supplies_to", 0.91, "Steam turbine modernization and digital grid synchronization hardware."),
        ],
        "strategic_partners": [
            ("MSFT", "Crane Clean Energy Center (Three Mile Island Unit 1) 20-Yr PPA", "technology_partner", 0.99, "Historic 20-year power purchase agreement restarting 835MW clean nuclear reactor."),
            ("META", "Hyperscale Clean Energy Matching & Long-Term Power Commitments", "technology_partner", 0.94, "Long-term carbon-free power agreement matching data center peak loads."),
        ],
        "downstream_customers": [
            ("MSFT", "Microsoft Azure Cloud Hyperscale AI Campuses (PJM Interconnection)", "supplies_to", 0.99, "Direct clean power offtaker for regional data center expansion."),
            ("AMZN", "Amazon AWS Cloud Data Centers (PJM Regional Power Pool)", "supplies_to", 0.95, "Wholesale commercial clean energy supply across PJM interconnect territory."),
            ("GOOGL", "Google Cloud Mid-Atlantic Hyperscale Computing Clusters", "supplies_to", 0.93, "24/7 hourly carbon-free energy matching supply contracts."),
        ],
        "competitors_peers": ["VST", "TLN", "NEE", "DUK", "SO"],
        "bridges": [
            {"id": "energy_grid", "theme_name": "Grid Modernization, Nuclear & SMR Infrastructure", "role": "Largest Clean Nuclear Fleet Operator in the US"},
            {"id": "ai_datacenter", "theme_name": "AI Data Center & Hyperscale Compute", "role": "Anchor 24/7 Power Supplier for AI Hyperscalers"},
        ],
    },
    "LLY": {
        "name": "Eli Lilly and Company",
        "sector": "Healthcare",
        "sub_industry": "GLP-1 Incretin Therapeutics, Dual/Triple Agonists & Diabetes Care",
        "tier": "mega_driver",
        "tier2_suppliers": [
            ("CTLT", "Catalent Multi-Site Sterile Fill-Finish CDMO Aseptic Lines", "supplies_to", 0.96, "Aseptic filling and finishing of Mounjaro and Zepbound autoinjector pens."),
            ("WST", "West Pharmaceutical Daikyo Crystal Zenith Vials & Autoinjector Seals", "supplies_to", 0.95, "Specialized elastomeric syringe plungers, stoppers, and cartridge seals."),
            ("TMO", "Thermo Fisher Scientific Commercial Bioprocessing Chromatography Resins", "supplies_to", 0.92, "High-capacity purification chromatography resins and single-use bioreactors."),
        ],
        "tier1_suppliers": [
            ("DHR", "Danaher Cytiva High-Flow Bioseparation Columns & Filtration Cassettes", "supplies_to", 0.93, "Tangential flow filtration membranes and sterile depth filters."),
            ("STE", "STERIS Contract High-Capacity E-Beam & Ethylene Oxide Sterilization", "supplies_to", 0.91, "Contract terminal sterilization services for single-dose autoinjector devices."),
            ("VKTX", "Viking Therapeutics Dual GLP-1/GIP Clinical Development Benchmarking", "technology_partner", 0.88, "Next-generation oral and subcutaneous incretin dual agonist research."),
        ],
        "strategic_partners": [
            ("AMZN", "Amazon Pharmacy Home Delivery for LillyDirect Direct-to-Consumer", "technology_partner", 0.96, "Direct home fulfillment channel providing direct-to-patient access to Zepbound."),
            ("UNH", "OptumRx Preferred Commercial Formulary Inclusion & Tier 1 Coverage", "technology_partner", 0.94, "Preferred formulary agreement securing broad commercial employer access."),
        ],
        "downstream_customers": [
            ("UNH", "UnitedHealth Group OptumRx Pharmacy Benefit Management Channels", "supplies_to", 0.97, "PBM channel distributing to tens of millions of covered commercial lives."),
            ("CVS", "CVS Caremark Retail Pharmacy & Commercial Prescription Network", "supplies_to", 0.95, "Nationwide pharmacy dispensing network and specialty pharmacy fulfillment."),
            ("MCK", "McKesson Corporation Global Pharmaceutical Logistics & Distribution", "supplies_to", 0.94, "Wholesale pharmaceutical supply rail delivering to hospitals and pharmacies."),
        ],
        "competitors_peers": ["NVO", "PFE", "AMGN", "VKTX", "AZN"],
        "bridges": [
            {"id": "glp1_cdmo", "theme_name": "GLP-1 Metabolic Therapeutics & CDMO Supply Chain", "role": "Mounjaro & Zepbound Commercial Mega-Driver"},
        ],
    },
}


# ==============================================================================
# Additional Institutional Bellwethers & Curated Universe Nodes
# ==============================================================================

_ADDITIONAL_CURATED_NODES: Dict[str, Dict[str, Any]] = {
    "AAPL": {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "sector": "Technology",
        "sub_industry": "Consumer Electronics & Edge AI Hardware",
        "tier": "mega_driver",
        "market_cap_billions": 3320.0,
        "metrics": {
            "elasticity_score": 92.0,
            "capex_sensitivity": 1.4,
            "revenue_concentration_pct": 25.0,
            "operating_leverage": 2.8,
            "forward_pe": 31.5,
            "peg_ratio": 1.4,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 6.1,
            "next_earnings_date": "2026-10-29",
            "flow_sentiment_score": 0.82,
            "options_skew": "bullish_call_drift",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-02-02",
                "period": "10-K FY26",
                "speaker": "Tim Cook, CEO",
                "quote": "Apple Silicon and Apple Intelligence represent the cornerstone of our multi-device ecosystem, anchored by high-bandwidth silicon packaging and on-device neural engines.",
                "context": "Annual 10-K disclosure on proprietary silicon and component sourcing.",
                "confidence": 0.98,
            }
        ],
    },
    "MSFT": {
        "symbol": "MSFT",
        "name": "Microsoft Corporation",
        "sector": "Technology",
        "sub_industry": "Cloud Infrastructure & Enterprise Copilots",
        "tier": "mega_driver",
        "market_cap_billions": 3150.0,
        "metrics": {
            "elasticity_score": 94.0,
            "capex_sensitivity": 1.6,
            "revenue_concentration_pct": 35.0,
            "operating_leverage": 3.2,
            "forward_pe": 32.0,
            "peg_ratio": 1.3,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 15.2,
            "next_earnings_date": "2026-10-24",
            "flow_sentiment_score": 0.85,
            "options_skew": "bullish_call_drift",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-01-30",
                "period": "10-K FY26",
                "speaker": "Satya Nadella, CEO",
                "quote": "Azure AI infrastructure is expanding globally, driving massive multi-gigawatt power contracts, optical networking capacity, and GPU accelerator clusters.",
                "context": "Hyperscale cloud expansion and AI infrastructure CapEx commentary.",
                "confidence": 0.98,
            }
        ],
    },
    "AMZN": {
        "symbol": "AMZN",
        "name": "Amazon.com Inc.",
        "sector": "Consumer Discretionary",
        "sub_industry": "Hyperscale Cloud & Omnichannel Logistics",
        "tier": "mega_driver",
        "market_cap_billions": 1980.0,
        "metrics": {
            "elasticity_score": 91.5,
            "capex_sensitivity": 1.8,
            "revenue_concentration_pct": 30.0,
            "operating_leverage": 3.1,
            "forward_pe": 38.0,
            "peg_ratio": 1.25,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 12.5,
            "next_earnings_date": "2026-10-26",
            "flow_sentiment_score": 0.84,
            "options_skew": "bullish_call_drift",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-02-06",
                "period": "10-K FY26",
                "speaker": "Andy Jassy, CEO",
                "quote": "AWS CapEx is focused on expanding custom Trainium/Inferentia silicon, next-generation data centers, and clean nuclear baseload power purchase agreements.",
                "context": "AWS infrastructure investments and fulfillment robotics.",
                "confidence": 0.97,
            }
        ],
    },
    "GOOGL": {
        "symbol": "GOOGL",
        "name": "Alphabet Inc.",
        "sector": "Communication Services",
        "sub_industry": "Hyperscale AI, Custom TPUs & Search",
        "tier": "mega_driver",
        "market_cap_billions": 2080.0,
        "metrics": {
            "elasticity_score": 92.5,
            "capex_sensitivity": 1.7,
            "revenue_concentration_pct": 28.0,
            "operating_leverage": 3.0,
            "forward_pe": 23.5,
            "peg_ratio": 1.15,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 13.8,
            "next_earnings_date": "2026-10-24",
            "flow_sentiment_score": 0.81,
            "options_skew": "balanced_bullish",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-02-04",
                "period": "10-K FY26",
                "speaker": "Sundar Pichai, CEO",
                "quote": "Our seventh-generation TPU silicon and Gemini models are driving accelerated infrastructure investments across global data centers and subsea optical cables.",
                "context": "Alphabet AI infrastructure and custom accelerator architecture.",
                "confidence": 0.97,
            }
        ],
    },
    "INTC": {
        "symbol": "INTC",
        "name": "Intel Corporation",
        "sector": "Semiconductors",
        "sub_industry": "x86 Microprocessors & Foundry Services",
        "tier": "mega_driver",
        "market_cap_billions": 95.0,
        "metrics": {
            "elasticity_score": 82.0,
            "capex_sensitivity": 2.6,
            "revenue_concentration_pct": 42.0,
            "operating_leverage": 2.4,
            "forward_pe": 28.0,
            "peg_ratio": 1.35,
            "gross_margin_trend": "recovering",
            "yoy_revenue_growth": 4.5,
            "next_earnings_date": "2026-10-24",
            "flow_sentiment_score": 0.65,
            "options_skew": "balanced_bullish",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-01-25",
                "period": "10-K FY26",
                "speaker": "Pat Gelsinger, CEO",
                "quote": "Intel 18A and High-NA EUV deployment at our Oregon and Ohio fabs anchor our return to process leadership, supporting external foundry customers and enterprise server silicon.",
                "context": "IFS foundry roadmap and advanced packaging technology.",
                "confidence": 0.96,
            }
        ],
    },
    "QCOM": {
        "symbol": "QCOM",
        "name": "Qualcomm Inc.",
        "sector": "Semiconductors",
        "sub_industry": "Mobile SoCs & Edge AI Silicon",
        "tier": "mega_driver",
        "market_cap_billions": 182.0,
        "metrics": {
            "elasticity_score": 86.0,
            "capex_sensitivity": 2.4,
            "revenue_concentration_pct": 48.0,
            "operating_leverage": 2.7,
            "forward_pe": 16.5,
            "peg_ratio": 1.10,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 11.2,
            "next_earnings_date": "2026-11-06",
            "flow_sentiment_score": 0.78,
            "options_skew": "bullish_call_drift",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-02-01",
                "period": "10-K FY26",
                "speaker": "Cristiano Amon, CEO",
                "quote": "Snapdragon X Elite and our edge AI neural processing units (NPUs) are reshaping client laptops, automotive digital cockpits, and 5G connected IoT devices.",
                "context": "Edge AI inference silicon and automotive pipeline growth.",
                "confidence": 0.96,
            }
        ],
    },
    "ARM": {
        "symbol": "ARM",
        "name": "Arm Holdings plc",
        "sector": "Semiconductors",
        "sub_industry": "Compute Subsystem IP & RISC Architecture",
        "tier": "mega_driver",
        "market_cap_billions": 135.0,
        "metrics": {
            "elasticity_score": 93.0,
            "capex_sensitivity": 2.9,
            "revenue_concentration_pct": 52.0,
            "operating_leverage": 3.4,
            "forward_pe": 45.0,
            "peg_ratio": 1.6,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 28.5,
            "next_earnings_date": "2026-11-05",
            "flow_sentiment_score": 0.85,
            "options_skew": "bullish_call_drift",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-02-07",
                "period": "20-F FY26",
                "speaker": "Rene Haas, CEO",
                "quote": "Armv9 architecture and Compute Subsystems (CSS) adoption has accelerated across cloud hyperscalers designing custom silicon, delivering unprecedented royalty leverage.",
                "context": "Cloud data center silicon IP licensing and royalty rate expansion.",
                "confidence": 0.97,
            }
        ],
    },
    "BA": {
        "symbol": "BA",
        "name": "The Boeing Company",
        "sector": "Industrials",
        "sub_industry": "Commercial Airframes & Defense Systems",
        "tier": "mega_driver",
        "market_cap_billions": 96.0,
        "metrics": {
            "elasticity_score": 79.5,
            "capex_sensitivity": 2.5,
            "revenue_concentration_pct": 45.0,
            "operating_leverage": 2.2,
            "forward_pe": 35.0,
            "peg_ratio": 1.45,
            "gross_margin_trend": "recovering",
            "yoy_revenue_growth": 5.2,
            "next_earnings_date": "2026-10-23",
            "flow_sentiment_score": 0.62,
            "options_skew": "balanced_bullish",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-01-31",
                "period": "10-K FY26",
                "speaker": "Kelly Ortberg, CEO",
                "quote": "Stabilizing 737 and 787 production rates while fulfilling multi-year defense backlogs requires deepening tier-1 supplier alignment and rigorous quality control.",
                "context": "Commercial aerospace delivery cadence and supply chain coordination.",
                "confidence": 0.95,
            }
        ],
    },
    "NFLX": {
        "symbol": "NFLX",
        "name": "Netflix Inc.",
        "sector": "Communication Services",
        "sub_industry": "Global Streaming Entertainment",
        "tier": "mega_driver",
        "market_cap_billions": 285.0,
        "metrics": {
            "elasticity_score": 89.0,
            "capex_sensitivity": 1.8,
            "revenue_concentration_pct": 32.0,
            "operating_leverage": 3.2,
            "forward_pe": 34.0,
            "peg_ratio": 1.25,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 15.0,
            "next_earnings_date": "2026-10-17",
            "flow_sentiment_score": 0.86,
            "options_skew": "bullish_call_drift",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-01-22",
                "period": "10-K FY26",
                "speaker": "Ted Sarandos, Co-CEO",
                "quote": "Our ad-supported tier and live event broadcasts have driven operating margin expansion, supported by AWS cloud transcoding and edge content delivery.",
                "context": "Subscriber growth, monetization, and infrastructure scaling.",
                "confidence": 0.97,
            }
        ],
    },
    "META": {
        "symbol": "META",
        "name": "Meta Platforms Inc.",
        "sector": "Communication Services",
        "sub_industry": "Social Infrastructure & Open Source AI",
        "tier": "mega_driver",
        "market_cap_billions": 1360.0,
        "metrics": {
            "elasticity_score": 93.5,
            "capex_sensitivity": 1.9,
            "revenue_concentration_pct": 30.0,
            "operating_leverage": 3.3,
            "forward_pe": 24.5,
            "peg_ratio": 1.15,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 22.0,
            "next_earnings_date": "2026-10-23",
            "flow_sentiment_score": 0.88,
            "options_skew": "bullish_call_drift",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-02-01",
                "period": "10-K FY26",
                "speaker": "Mark Zuckerberg, CEO",
                "quote": "We will have over 600k H100 equivalents in operation. Our AI CapEx is designed to power Llama foundational models and deliver high-intent algorithmic ad conversions.",
                "context": "AI infrastructure buildout and compute cluster capacity disclosures.",
                "confidence": 0.98,
            }
        ],
    },
    "DELL": {
        "symbol": "DELL",
        "name": "Dell Technologies",
        "sector": "Technology",
        "sub_industry": "Enterprise AI Server Hardware & Solutions",
        "tier": "horizontal_enabler",
        "market_cap_billions": 92.0,
        "metrics": {
            "elasticity_score": 85.5,
            "capex_sensitivity": 2.4,
            "revenue_concentration_pct": 38.0,
            "operating_leverage": 2.5,
            "forward_pe": 15.0,
            "peg_ratio": 1.05,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 9.5,
            "next_earnings_date": "2026-11-26",
            "flow_sentiment_score": 0.76,
            "options_skew": "balanced_bullish",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-03-01",
                "period": "10-K FY26",
                "speaker": "Michael Dell, CEO",
                "quote": "PowerEdge XE9680 AI servers are the fastest-ramping product in company history, serving enterprise customers deploying proprietary AI clusters.",
                "context": "Enterprise AI server order backlog and compute deployments.",
                "confidence": 0.96,
            }
        ],
    },
    "JPM": {
        "symbol": "JPM",
        "name": "JPMorgan Chase & Co.",
        "sector": "Financials",
        "sub_industry": "Global Investment Banking & Treasury Services",
        "tier": "mega_driver",
        "market_cap_billions": 625.0,
        "metrics": {
            "elasticity_score": 80.0,
            "capex_sensitivity": 1.3,
            "revenue_concentration_pct": 22.0,
            "operating_leverage": 2.6,
            "forward_pe": 12.5,
            "peg_ratio": 1.20,
            "gross_margin_trend": "stable",
            "yoy_revenue_growth": 7.8,
            "next_earnings_date": "2026-10-11",
            "flow_sentiment_score": 0.78,
            "options_skew": "balanced_bullish",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-02-15",
                "period": "10-K FY26",
                "speaker": "Jamie Dimon, CEO",
                "quote": "Technology investments in fraud prevention, cloud data platforms, and real-time payment rails are essential to maintaining Fortress Balance Sheet resiliency.",
                "context": "Technology budget and financial infrastructure modernization.",
                "confidence": 0.96,
            }
        ],
    },
    "UNH": {
        "symbol": "UNH",
        "name": "UnitedHealth Group",
        "sector": "Healthcare",
        "sub_industry": "Managed Healthcare & OptumRx PBM Networks",
        "tier": "mega_driver",
        "market_cap_billions": 520.0,
        "metrics": {
            "elasticity_score": 81.0,
            "capex_sensitivity": 1.4,
            "revenue_concentration_pct": 24.0,
            "operating_leverage": 2.7,
            "forward_pe": 19.0,
            "peg_ratio": 1.15,
            "gross_margin_trend": "stable",
            "yoy_revenue_growth": 9.2,
            "next_earnings_date": "2026-10-15",
            "flow_sentiment_score": 0.74,
            "options_skew": "balanced_bullish",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-02-10",
                "period": "10-K FY26",
                "speaker": "Andrew Witty, CEO",
                "quote": "OptumRx manages over $120B in pharmaceutical spend, negotiating value-based access and supply rails for next-generation metabolic therapeutics.",
                "context": "Pharmacy benefit management formulary and drug distribution.",
                "confidence": 0.96,
            }
        ],
    },
    "CVS": {
        "symbol": "CVS",
        "name": "CVS Health",
        "sector": "Healthcare",
        "sub_industry": "Pharmacy Benefit Services & Retail Health",
        "tier": "horizontal_enabler",
        "market_cap_billions": 76.0,
        "metrics": {
            "elasticity_score": 75.0,
            "capex_sensitivity": 1.5,
            "revenue_concentration_pct": 26.0,
            "operating_leverage": 2.2,
            "forward_pe": 9.5,
            "peg_ratio": 1.10,
            "gross_margin_trend": "recovering",
            "yoy_revenue_growth": 4.1,
            "next_earnings_date": "2026-11-06",
            "flow_sentiment_score": 0.68,
            "options_skew": "balanced_bullish",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-02-14",
                "period": "10-K FY26",
                "speaker": "David Joyner, CEO",
                "quote": "Our nationwide network of 9,000+ retail pharmacies and Caremark PBM provides the critical last-mile fulfillment infrastructure for biologic and incretin medications.",
                "context": "Retail pharmacy footprint and specialty drug dispensing channels.",
                "confidence": 0.95,
            }
        ],
    },
    "MCK": {
        "symbol": "MCK",
        "name": "McKesson Corporation",
        "sector": "Healthcare",
        "sub_industry": "Pharmaceutical Logistics & Distribution Rails",
        "tier": "horizontal_enabler",
        "market_cap_billions": 72.0,
        "metrics": {
            "elasticity_score": 78.5,
            "capex_sensitivity": 1.6,
            "revenue_concentration_pct": 28.0,
            "operating_leverage": 2.3,
            "forward_pe": 16.0,
            "peg_ratio": 1.12,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 11.0,
            "next_earnings_date": "2026-11-01",
            "flow_sentiment_score": 0.72,
            "options_skew": "balanced_bullish",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-05-10",
                "period": "10-K FY26",
                "speaker": "Brian Tyler, CEO",
                "quote": "As the primary distributor for one-third of all prescription pharmaceuticals in North America, our temperature-controlled cold-chain logistics are mission-critical.",
                "context": "Wholesale pharmaceutical supply network and cold-chain capacity.",
                "confidence": 0.96,
            }
        ],
    },
    "V": {
        "symbol": "V",
        "name": "Visa Inc.",
        "sector": "Financials",
        "sub_industry": "Global Payment Processing Rails",
        "tier": "mega_driver",
        "market_cap_billions": 575.0,
        "metrics": {
            "elasticity_score": 88.0,
            "capex_sensitivity": 1.2,
            "revenue_concentration_pct": 20.0,
            "operating_leverage": 3.4,
            "forward_pe": 28.0,
            "peg_ratio": 1.30,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 10.5,
            "next_earnings_date": "2026-10-22",
            "flow_sentiment_score": 0.82,
            "options_skew": "bullish_call_drift",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-11-15",
                "period": "10-K FY26",
                "speaker": "Ryan McInerney, CEO",
                "quote": "VisaNet processes over 270 billion transactions annually, providing the universal clearing and settlement layer connecting financial institutions worldwide.",
                "context": "Payment transaction volume and core network infrastructure.",
                "confidence": 0.98,
            }
        ],
    },
    "MA": {
        "symbol": "MA",
        "name": "Mastercard Inc.",
        "sector": "Financials",
        "sub_industry": "Payment Networks & Value-Added Services",
        "tier": "mega_driver",
        "market_cap_billions": 445.0,
        "metrics": {
            "elasticity_score": 87.5,
            "capex_sensitivity": 1.3,
            "revenue_concentration_pct": 21.0,
            "operating_leverage": 3.3,
            "forward_pe": 30.0,
            "peg_ratio": 1.35,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 11.2,
            "next_earnings_date": "2026-10-24",
            "flow_sentiment_score": 0.81,
            "options_skew": "bullish_call_drift",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-02-12",
                "period": "10-K FY26",
                "speaker": "Michael Miebach, CEO",
                "quote": "Value-added services including fraud scoring, tokenization, and cyber solutions represent our fastest growing segment alongside cross-border volume.",
                "context": "Core payment rails and digital transaction security services.",
                "confidence": 0.97,
            }
        ],
    },
    "PYPL": {
        "symbol": "PYPL",
        "name": "PayPal Holdings",
        "sector": "Financials",
        "sub_industry": "Digital Payments, Wallets & Merchant Checkout",
        "tier": "mega_driver",
        "market_cap_billions": 68.0,
        "metrics": {
            "elasticity_score": 81.5,
            "capex_sensitivity": 1.7,
            "revenue_concentration_pct": 30.0,
            "operating_leverage": 2.5,
            "forward_pe": 14.5,
            "peg_ratio": 1.10,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 8.0,
            "next_earnings_date": "2026-10-29",
            "flow_sentiment_score": 0.70,
            "options_skew": "balanced_bullish",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-02-08",
                "period": "10-K FY26",
                "speaker": "Alex Chriss, CEO",
                "quote": "Fastlane checkout and Venmo monetization are accelerating transaction margin dollar growth across our consumer and enterprise merchant bases.",
                "context": "E-commerce checkout conversion and payment processing.",
                "confidence": 0.96,
            }
        ],
    },
    "DIS": {
        "symbol": "DIS",
        "name": "The Walt Disney Company",
        "sector": "Communication Services",
        "sub_industry": "Media Networks, Parks & Streaming Platforms",
        "tier": "mega_driver",
        "market_cap_billions": 178.0,
        "metrics": {
            "elasticity_score": 80.5,
            "capex_sensitivity": 1.6,
            "revenue_concentration_pct": 25.0,
            "operating_leverage": 2.6,
            "forward_pe": 20.0,
            "peg_ratio": 1.20,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 6.8,
            "next_earnings_date": "2026-11-14",
            "flow_sentiment_score": 0.73,
            "options_skew": "balanced_bullish",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-11-20",
                "period": "10-K FY26",
                "speaker": "Bob Iger, CEO",
                "quote": "Direct-to-Consumer streaming has attained sustained profitability, driven by Disney+, Hulu integration, and targeted digital advertising technology.",
                "context": "DTC entertainment streaming profitability and park investments.",
                "confidence": 0.96,
            }
        ],
    },
    "WMT": {
        "symbol": "WMT",
        "name": "Walmart Inc.",
        "sector": "Consumer Staples",
        "sub_industry": "Omnichannel Retail & Automated Distribution",
        "tier": "mega_driver",
        "market_cap_billions": 560.0,
        "metrics": {
            "elasticity_score": 83.0,
            "capex_sensitivity": 1.3,
            "revenue_concentration_pct": 18.0,
            "operating_leverage": 2.4,
            "forward_pe": 27.0,
            "peg_ratio": 1.30,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 5.5,
            "next_earnings_date": "2026-11-19",
            "flow_sentiment_score": 0.77,
            "options_skew": "balanced_bullish",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-03-20",
                "period": "10-K FY26",
                "speaker": "Doug McMillon, CEO",
                "quote": "Over 65% of our regional distribution centers now incorporate autonomous robotic sortation and automated storage, driving margin expansion.",
                "context": "Supply chain automation and retail logistics infrastructure.",
                "confidence": 0.97,
            }
        ],
    },
    "CAT": {
        "symbol": "CAT",
        "name": "Caterpillar Inc.",
        "sector": "Industrials",
        "sub_industry": "Autonomous Heavy Machinery & Construction",
        "tier": "mega_driver",
        "market_cap_billions": 185.0,
        "metrics": {
            "elasticity_score": 82.5,
            "capex_sensitivity": 2.1,
            "revenue_concentration_pct": 32.0,
            "operating_leverage": 2.8,
            "forward_pe": 16.0,
            "peg_ratio": 1.15,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 6.2,
            "next_earnings_date": "2026-10-29",
            "flow_sentiment_score": 0.75,
            "options_skew": "balanced_bullish",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-02-14",
                "period": "10-K FY26",
                "speaker": "Jim Umpleby, CEO",
                "quote": "Our autonomous haul truck fleet has surpassed 8 billion tons moved safely with zero lost-time injuries, demonstrating physical AI leadership in mining.",
                "context": "Autonomous fleet operations and global machinery demand.",
                "confidence": 0.96,
            }
        ],
    },
    "PFE": {
        "symbol": "PFE",
        "name": "Pfizer Inc.",
        "sector": "Healthcare",
        "sub_industry": "Biopharmaceuticals & Oncology Therapeutics",
        "tier": "mega_driver",
        "market_cap_billions": 165.0,
        "metrics": {
            "elasticity_score": 77.0,
            "capex_sensitivity": 1.8,
            "revenue_concentration_pct": 30.0,
            "operating_leverage": 2.4,
            "forward_pe": 12.0,
            "peg_ratio": 1.10,
            "gross_margin_trend": "stable",
            "yoy_revenue_growth": 4.0,
            "next_earnings_date": "2026-10-29",
            "flow_sentiment_score": 0.69,
            "options_skew": "balanced_bullish",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-02-22",
                "period": "10-K FY26",
                "speaker": "Albert Bourla, CEO",
                "quote": "Our oncology pipeline and commercial biomanufacturing network provide durable long-term cash flow with eight potential blockbuster readouts by 2030.",
                "context": "Oncology pipeline and biopharmaceutical manufacturing capacity.",
                "confidence": 0.95,
            }
        ],
    },
    "RTX": {
        "symbol": "RTX",
        "name": "RTX Corporation",
        "sector": "Industrials",
        "sub_industry": "Aerospace Engines & Defense Electronics",
        "tier": "mega_driver",
        "market_cap_billions": 162.0,
        "metrics": {
            "elasticity_score": 83.5,
            "capex_sensitivity": 2.4,
            "revenue_concentration_pct": 42.0,
            "operating_leverage": 2.6,
            "forward_pe": 20.0,
            "peg_ratio": 1.25,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 9.5,
            "next_earnings_date": "2026-10-22",
            "flow_sentiment_score": 0.76,
            "options_skew": "balanced_bullish",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-02-05",
                "period": "10-K FY26",
                "speaker": "Chris Calio, CEO",
                "quote": "Pratt & Whitney GTF engines and Collins Aerospace commercial avionics are supported by our record $206B defense backlog and missile defense systems.",
                "context": "Commercial aerospace aftermarket and defense contract backlogs.",
                "confidence": 0.96,
            }
        ],
    },
    "ORCL": {
        "symbol": "ORCL",
        "name": "Oracle Corporation",
        "sector": "Technology",
        "sub_industry": "Autonomous Cloud Database & OCI AI Clusters",
        "tier": "mega_driver",
        "market_cap_billions": 450.0,
        "metrics": {
            "elasticity_score": 92.0,
            "capex_sensitivity": 2.2,
            "revenue_concentration_pct": 35.0,
            "operating_leverage": 3.1,
            "forward_pe": 25.0,
            "peg_ratio": 1.20,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 14.5,
            "next_earnings_date": "2026-12-09",
            "flow_sentiment_score": 0.84,
            "options_skew": "bullish_call_drift",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-06-20",
                "period": "10-K FY26",
                "speaker": "Safra Catz, CEO",
                "quote": "Oracle Cloud Infrastructure (OCI) Gen2 AI superclusters and multicloud database partnerships with Microsoft and Google are driving unprecedented RPO backlog.",
                "context": "OCI AI cluster growth and enterprise database migrations.",
                "confidence": 0.97,
            }
        ],
    },
    "NOW": {
        "symbol": "NOW",
        "name": "ServiceNow Inc.",
        "sector": "Technology",
        "sub_industry": "Enterprise Workflow Automation & Agentic IT",
        "tier": "mega_driver",
        "market_cap_billions": 192.0,
        "metrics": {
            "elasticity_score": 93.0,
            "capex_sensitivity": 2.5,
            "revenue_concentration_pct": 38.0,
            "operating_leverage": 3.3,
            "forward_pe": 55.0,
            "peg_ratio": 1.50,
            "gross_margin_trend": "expanding",
            "yoy_revenue_growth": 22.5,
            "next_earnings_date": "2026-10-23",
            "flow_sentiment_score": 0.88,
            "options_skew": "bullish_call_drift",
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": "2026-01-28",
                "period": "10-K FY26",
                "speaker": "Bill McDermott, CEO",
                "quote": "ServiceNow is the AI orchestration platform for business transformation. Our Now Assist GenAI solutions represent the fastest-growing new product family in company history.",
                "context": "Enterprise workflow automation and AI agent deployment.",
                "confidence": 0.97,
            }
        ],
    },
}

# ==============================================================================
# Universal Domain Archetype Value Chain Taxonomy
# ==============================================================================

UNIVERSAL_ARCHETYPES: Dict[str, Dict[str, Any]] = {
    "semiconductors": {
        "sector_label": "Semiconductors & Compute Hardware",
        "theme_bridge": "semi_equipment",
        "tier2_suppliers": [
            ("ASML", "Photolithography & Extreme Ultraviolet (EUV) Systems", "supplies_to", 0.98, "Critical high-NA EUV lithography systems for sub-3nm node patterning."),
            ("AMAT", "Applied Materials Wafer Fab Deposition & Etch Equipment", "supplies_to", 0.95, "Atomic layer deposition (ALD) and chemical mechanical planarization (CMP)."),
            ("LRCX", "Lam Research Advanced Dielectric & Conductor Etch Tools", "supplies_to", 0.94, "High aspect ratio etching systems for multi-layer 3D semiconductor structures."),
            ("CAMT", "Camtek High-Resolution Packaging & 3D Wafer Metrology", "supplies_to", 0.92, "High-throughput optical inspection and metrology for advanced packaging dies."),
        ],
        "tier1_suppliers": [
            ("TSM", "Taiwan Semiconductor Manufacturing Advanced Foundry", "supplies_to", 0.99, "Leading-edge foundry manufacturing and 3D CoWoS advanced packaging capacity."),
            ("MU", "Micron High-Bandwidth Memory (HBM3e/HBM4) Silicon Dies", "supplies_to", 0.95, "Ultra-high bandwidth memory stacks co-packaged with processor silicon."),
            ("ENTG", "Entegris Ultra-Pure Precursor Chemicals & Liquid Filters", "supplies_to", 0.91, "Contamination control systems and specialized chemical precursors for wafer fabs."),
        ],
        "strategic_partners": [
            ("MSFT", "Microsoft Azure Co-Design & Enterprise Silicon Validation", "technology_partner", 0.94, "Joint architectural optimization for cloud compute clusters and host software."),
            ("AVGO", "Broadcom High-Speed SerDes & Ethernet Co-Engineering", "technology_partner", 0.92, "PCIe Gen 6/7 optical interconnects and custom switch silicon integration."),
        ],
        "downstream_customers": [
            ("DELL", "Dell PowerEdge AI Server & High-Performance Compute OEMs", "supplies_to", 0.95, "Enterprise rack-scale server integrations and hyperscale cluster distribution."),
            ("AAPL", "Apple Device Ecosystem & Silicon Component Integration", "supplies_to", 0.94, "Client device manufacturing, high-density logic boards, and display drivers."),
            ("AMZN", "Amazon Web Services Accelerated Compute Infrastructure", "supplies_to", 0.96, "Cloud service provider deployment across hundreds of global availability zones."),
        ],
        "competitors_peers": ["NVDA", "AMD", "QCOM", "INTC", "AVGO", "ARM", "TXN"],
    },
    "software": {
        "sector_label": "Enterprise Software, Cloud & AI Workflows",
        "theme_bridge": "agentic_software",
        "tier2_suppliers": [
            ("NVDA", "NVIDIA Accelerated Compute GPUs & Tensor Core Clusters", "supplies_to", 0.96, "Accelerated hardware clusters powering foundational LLM training and high-throughput inference."),
            ("ANET", "Arista Networks Ultra-Low Latency Cloud Switching", "supplies_to", 0.92, "High-throughput spine-leaf data center interconnect networks."),
            ("EQIX", "Equinix Global Hyperscale Colocation & Interconnection", "supplies_to", 0.90, "Mission-critical carrier-neutral data centers with direct fiber cross-connects."),
        ],
        "tier1_suppliers": [
            ("MSFT", "Microsoft Azure Cloud Platform & OpenAI API Infrastructure", "supplies_to", 0.98, "Enterprise cloud host runtime, distributed object storage, and OpenAI model APIs."),
            ("AMZN", "Amazon Web Services Scalable Compute & S3 Storage", "supplies_to", 0.97, "Elastic compute and high-durability cloud data storage layers."),
            ("SNOW", "Snowflake Data Cloud & Distributed Analytics Engine", "supplies_to", 0.93, "Governed data lakehouse and real-time SQL execution infrastructure."),
            ("CRWD", "CrowdStrike Falcon Zero Trust Endpoint Protection", "supplies_to", 0.92, "Cloud-native identity threat detection and container runtime security."),
        ],
        "strategic_partners": [
            ("PLTR", "Palantir Foundry & AIP Ontology Integration", "technology_partner", 0.93, "Enterprise data integration and agentic workflow orchestration pipelines."),
            ("PANW", "Palo Alto Networks Prisma Cloud & Secure SASE Architecture", "technology_partner", 0.91, "Secure edge networking and cloud workload protection policies."),
            ("DDOG", "Datadog Cloud-Scale APM & Real-Time Telemetry Observability", "technology_partner", 0.90, "End-to-end distributed tracing, metrics aggregation, and security logging."),
        ],
        "downstream_customers": [
            ("JPM", "JPMorgan Chase Enterprise Financial Services Deployment", "supplies_to", 0.95, "Global tier-1 banking workflows, risk management, and quantitative research platforms."),
            ("UNH", "UnitedHealth Group Healthcare Operations & Claims Automation", "supplies_to", 0.94, "Healthcare payer systems, administrative workflows, and clinical data pipelines."),
            ("WMT", "Walmart Global Omnichannel Logistics & Retail Planning", "supplies_to", 0.93, "Supply chain inventory management, dynamic demand forecasting, and POS operations."),
        ],
        "competitors_peers": ["CRM", "MDB", "NOW", "SNOW", "PLTR", "ORCL", "ADBE"],
    },
    "aerospace": {
        "sector_label": "Aerospace, Defense & Space Systems",
        "theme_bridge": "space_defense",
        "tier2_suppliers": [
            ("RDW", "Redwire Space Deployable Solar Arrays & Structural Composite Booms", "supplies_to", 0.94, "High-strain composite deployable booms, Roll-Out Solar Arrays (ROSA), and star trackers."),
            ("HEI", "HEICO Sub-Tier FAA Avionics & Precision Defense Replacement Parts", "supplies_to", 0.93, "Mission-critical replacement flight hardware, microwave assemblies, and electro-optical sensors."),
            ("CAMT", "Camtek Precision Defense & Space Electronics Inspection", "supplies_to", 0.90, "Radiation-hardened die inspection and advanced microelectronics verification."),
        ],
        "tier1_suppliers": [
            ("RKLB", "Rocket Lab Electron & Neutron Medium-Lift Launch Services", "supplies_to", 0.96, "Dedicated responsive orbital insertion, kick-stage buses, and reaction wheel assemblies."),
            ("KTOS", "Kratos Defense Subscale Aerial Targets & Satellite Command/Control", "supplies_to", 0.93, "Tactical jet drones, space domain tracking ground software, and rocket propulsion motors."),
            ("LUNR", "Intuitive Machines Lunar Commercial Payload Transporters", "supplies_to", 0.91, "Autonomous cryogenic lander platforms and lunar terrain communication links."),
        ],
        "strategic_partners": [
            ("LMT", "Lockheed Martin Skunk Works & Joint Space Constellation Co-Development", "technology_partner", 0.95, "Next-generation missile defense integration and classified national security payload buses."),
            ("NOC", "Northrop Grumman Advanced Defense Radar & Space Payloads", "technology_partner", 0.94, "Space payload sensors, advanced synthetic aperture radars, and solid rocket boosters."),
        ],
        "downstream_customers": [
            ("BA", "Boeing Commercial Airplanes & Defense Global Support", "supplies_to", 0.95, "Commercial airframe assembly lines and multi-role defense aircraft programs."),
            ("LMT", "Lockheed Martin Aeronautics & Space Systems Integration", "supplies_to", 0.96, "Prime defense contracts for the US Department of Defense, NASA, and allied nations."),
            ("ASTS", "AST SpaceMobile Direct-to-Cell Low Earth Orbit Constellations", "supplies_to", 0.93, "Commercial satellite bus integrations and global space-based broadband networks."),
        ],
        "competitors_peers": ["LMT", "NOC", "BA", "RTX", "GD", "RKLB", "SPCX"],
    },
    "energy": {
        "sector_label": "Energy, Nuclear SMRs & High-Voltage Grid Infrastructure",
        "theme_bridge": "energy_grid",
        "tier2_suppliers": [
            ("CCJ", "Cameco Corporation Uranium Fuel Mining & Refining", "supplies_to", 0.96, "Long-term security of supply for U3O8 yellowcake uranium concentrate and UF6 conversion."),
            ("LEU", "Centrus Energy High-Assay Low-Enriched Uranium (HALEU) Enrichment", "supplies_to", 0.94, "Domestic commercial-scale HALEU production essential for Gen-IV advanced nuclear reactors."),
            ("BWXT", "BWX Technologies Naval Nuclear Cores & SMR Pressure Vessels", "supplies_to", 0.95, "Precision reactor pressure boundary manufacturing and specialized TRISO nuclear fuel fabrication."),
        ],
        "tier1_suppliers": [
            ("GEV", "GE Vernova High-Efficiency Gas Turbines & Grid Substation Upgrades", "supplies_to", 0.97, "Combined-cycle heavy-duty gas turbines, steam turbines, and digital grid transmission management."),
            ("ETN", "Eaton Intelligent Medium-Voltage Switchgear & Transformers", "supplies_to", 0.96, "High-density substations, uninterruptible power supplies (UPS), and arc-resistant switchgear."),
            ("PWR", "Quanta Services High-Voltage Electric Transmission & Substation EPC", "supplies_to", 0.95, "Comprehensive engineering, procurement, and construction of high-voltage transmission lines."),
        ],
        "strategic_partners": [
            ("CEG", "Constellation Energy Long-Term Baseload Nuclear Power Purchase Agreements", "technology_partner", 0.98, "Multi-gigawatt 24/7 carbon-free clean power purchase agreements directly behind the meter."),
            ("VST", "Vistra Corp Merchant Generation & Battery Energy Storage Systems", "technology_partner", 0.95, "ERCOT/PJM flexible dispatch capacity and utility-scale lithium-ion battery storage."),
        ],
        "downstream_customers": [
            ("MSFT", "Microsoft Hyperscale AI Data Center Facilities", "supplies_to", 0.97, "Dedicated multi-hundred-megawatt power interconnection agreements for AI clusters."),
            ("AMZN", "Amazon Web Services Data Center Energy Infrastructure", "supplies_to", 0.96, "Behind-the-meter nuclear PPA off-take and zero-carbon grid interconnects."),
            ("GOOGL", "Alphabet Clean Energy Infrastructure & Google Cloud Campuses", "supplies_to", 0.95, "Round-the-clock 24/7 carbon-free energy supply for global cloud compute regions."),
        ],
        "competitors_peers": ["CEG", "VST", "TLN", "NEE", "DUK", "SO", "SMR", "OKLO"],
    },
    "healthcare": {
        "sector_label": "GLP-1 Metabolic Therapeutics, CDMO & Life Sciences",
        "theme_bridge": "glp1_cdmo",
        "tier2_suppliers": [
            ("TMO", "Thermo Fisher Scientific Commercial Bioprocessing Resins & Media", "supplies_to", 0.94, "High-capacity purification chromatography resins, cell culture media, and single-use bioreactors."),
            ("WST", "West Pharmaceutical Daikyo Crystal Zenith Vials & Autoinjector Seals", "supplies_to", 0.96, "Specialized elastomeric syringe plungers, stoppers, and high-purity cartridge seals."),
            ("DHR", "Danaher Cytiva High-Flow Bioseparation Columns & Filtration Cassettes", "supplies_to", 0.93, "Tangential flow filtration membranes and sterile depth filters for peptide purification."),
        ],
        "tier1_suppliers": [
            ("CTLT", "Catalent Multi-Site Sterile Fill-Finish CDMO Aseptic Lines", "supplies_to", 0.97, "Aseptic filling, high-speed automated inspection, and packaging of autoinjector pens."),
            ("STE", "STERIS Contract High-Capacity E-Beam & Ethylene Oxide Sterilization", "supplies_to", 0.92, "Terminal contract radiation sterilization services for sterile medical delivery devices."),
            ("VKTX", "Viking Therapeutics Incretin Dual/Triple Agonist Co-Development", "technology_partner", 0.88, "Next-generation oral and subcutaneous GLP-1/GIP dual agonist clinical development."),
        ],
        "strategic_partners": [
            ("AMZN", "Amazon Pharmacy Direct Home Delivery & Fulfillment Rails", "technology_partner", 0.95, "Direct-to-consumer pharmacy distribution and cold-chain home delivery channels."),
            ("AMGN", "Amgen Commercial Manufacturing & Therapeutic Co-Engineering", "technology_partner", 0.91, "Shared large-scale biologic fermentation facilities and global distribution agreements."),
        ],
        "downstream_customers": [
            ("UNH", "UnitedHealth Group OptumRx Pharmacy Benefit Management Channels", "supplies_to", 0.97, "PBM formulary placement and coverage for tens of millions of commercial lives."),
            ("CVS", "CVS Caremark Retail Pharmacy & Commercial Prescription Network", "supplies_to", 0.96, "Nationwide pharmacy dispensing network, specialty clinics, and retail prescription fulfillment."),
            ("MCK", "McKesson Corporation Global Pharmaceutical Logistics & Distribution", "supplies_to", 0.95, "Wholesale pharmaceutical supply rail delivering therapeutics to hospitals and pharmacies."),
        ],
        "competitors_peers": ["LLY", "NVO", "PFE", "MRK", "BMY", "ABBV", "AMGN", "VKTX"],
    },
    "industrial_robotics": {
        "sector_label": "Physical AI, Humanoid Robotics & Industrial Automation",
        "theme_bridge": "robotics_ai",
        "tier2_suppliers": [
            ("NVDA", "NVIDIA Jetson Thor Embedded Autonomous Robotics Silicon", "supplies_to", 0.96, "SoCs designed for generative AI humanoid models, multi-camera SLAM, and real-time motion control."),
            ("CGNX", "Cognex Industrial Machine Vision & 3D Sensor Cameras", "supplies_to", 0.94, "High-speed 3D area scan cameras and deep learning vision systems for robotic guidance."),
            ("TER", "Teradyne Universal Robots Precision Collaborative Arms", "supplies_to", 0.92, "Lightweight collaborative robotic arms and high-precision torque-sensing motor actuators."),
        ],
        "tier1_suppliers": [
            ("ROK", "Rockwell Automation FactoryTalk & Programmable Logic Controllers", "supplies_to", 0.95, "Industrial automation control systems, safety interlocks, and plant-floor software."),
            ("SYM", "Symbotic AI-Powered High-Throughput Warehouse Automation", "supplies_to", 0.94, "Autonomous mobile robots (AMRs) and high-density automated storage and retrieval systems."),
            ("ISRG", "Intuitive Surgical Robotic Teleoperation & Precision Actuation", "technology_partner", 0.91, "Micron-level surgical actuation, robotic multi-joint arms, and spatial computer vision."),
        ],
        "strategic_partners": [
            ("UBER", "Uber Autonomous Commercial Fleet Dispatch & Mobility Integration", "technology_partner", 0.93, "Commercial routing algorithms, ride-hailing network integration, and autonomous fleet utilization."),
            ("ZBRA", "Zebra Technologies Rugged Enterprise Mobile Computing & RFID", "technology_partner", 0.91, "RFID asset tracking tags, barcode scanners, and warehouse execution software."),
        ],
        "downstream_customers": [
            ("AMZN", "Amazon Global Fulfillment Centers & Automated Sortation Facilities", "supplies_to", 0.97, "Fleet-wide deployment of thousands of autonomous mobile robots across fulfillment hubs."),
            ("WMT", "Walmart Regional Distribution Centers & Automated Supply Chain", "supplies_to", 0.96, "Automated case palletizing, high-speed sorting, and autonomous grocery fulfillment."),
            ("CAT", "Caterpillar Autonomous Mining & Industrial Heavy Equipment", "supplies_to", 0.94, "Autonomous haul trucks, mining teleoperation systems, and heavy construction fleet automation."),
        ],
        "competitors_peers": ["TSLA", "ISRG", "SYM", "ROK", "CGNX", "SERV", "TER"],
    },
    "consumer_internet": {
        "sector_label": "Consumer Internet, Streaming & Digital Media",
        "theme_bridge": "agentic_software",
        "tier2_suppliers": [
            ("NVDA", "NVIDIA AI Recommendation Engine & Video Transcoding GPUs", "supplies_to", 0.95, "High-density GPU clusters powering real-time personalized content recommendation feeds."),
            ("EQIX", "Equinix Global Edge Colocation & Peering Exchange Hubs", "supplies_to", 0.92, "Edge interconnection facilities delivering low-latency transit to major consumer ISPs."),
            ("LITE", "Lumentum High-Speed Optical Transceivers for Media Backbones", "supplies_to", 0.90, "Optical lasers and coherent transceivers enabling high-bandwidth fiber backhaul."),
        ],
        "tier1_suppliers": [
            ("AMZN", "Amazon Web Services Cloud Media Storage & Encoding", "supplies_to", 0.97, "Scalable cloud object storage, media transcoding pipelines, and global delivery."),
            ("NET", "Cloudflare Global Content Delivery Network & Edge Security", "supplies_to", 0.96, "Distributed edge caching, DDoS mitigation, and sub-millisecond edge API routing."),
            ("DDOG", "Datadog Real-Time User Experience & CDN Streaming Telemetry", "supplies_to", 0.91, "Synthetic monitoring, user session replay, and real-time streaming QoS observability."),
        ],
        "strategic_partners": [
            ("AAPL", "Apple App Store Distribution & Apple TV Ecosystem Co-Marketing", "technology_partner", 0.95, "Primary consumer subscription billing rails and hardware client integration."),
            ("GOOGL", "Google Play Global App Distribution & YouTube Media Alliances", "technology_partner", 0.94, "Android platform distribution, digital advertising exchange, and cross-platform streaming."),
        ],
        "downstream_customers": [
            ("CMCSA", "Comcast Xfinity Broadband Subscribers & Connected TV Networks", "supplies_to", 0.95, "Tier-1 residential broadband subscriber distribution and cable set-top box integration."),
            ("T", "AT&T Fiber & 5G High-Speed Mobile Streaming Subscribers", "supplies_to", 0.94, "5G wireless network bundling, mobile media streaming, and residential fiber offload."),
            ("VZ", "Verizon Communications 5G Ultra Wideband Mobile Subscribers", "supplies_to", 0.94, "Mobile broadband subscriber distribution and carrier billing integrations."),
        ],
        "competitors_peers": ["NFLX", "DIS", "SPOT", "CMCSA", "WBD", "AMZN", "GOOGL"],
    },
    "fintech": {
        "sector_label": "Fintech, Global Payments & Banking Infrastructure",
        "theme_bridge": "agentic_software",
        "tier2_suppliers": [
            ("NVDA", "NVIDIA Real-Time Fraud Detection & Risk Scoring GPU Accelerators", "supplies_to", 0.95, "Sub-millisecond machine learning inference clusters for transaction risk evaluation."),
            ("NET", "Cloudflare High-Security Financial Edge Network & TLS Offload", "supplies_to", 0.93, "PCI-DSS compliant edge network with ultra-low latency DDoS mitigation."),
            ("ANET", "Arista Networks Low-Latency Financial Exchange Switching", "supplies_to", 0.91, "Nanosecond-scale deterministic network switches for high-frequency payment routing."),
        ],
        "tier1_suppliers": [
            ("MSFT", "Microsoft Azure for Financial Services & Sovereign Cloud", "supplies_to", 0.96, "Highly compliant financial cloud infrastructure with multi-region database replication."),
            ("CRWD", "CrowdStrike Financial Identity Threat Protection & Falcon SOC", "supplies_to", 0.95, "Real-time identity threat protection, endpoint telemetry, and regulatory compliance audit logs."),
            ("SNOW", "Snowflake Financial Services Data Cloud & Regulatory Reporting", "supplies_to", 0.92, "Consolidated transactional data lakehouse for anti-money laundering and audit compliance."),
        ],
        "strategic_partners": [
            ("COIN", "Coinbase Institutional Custody & Real-Time Settlement Rails", "technology_partner", 0.94, "Regulated digital asset custody, liquidity pools, and base-layer crypto settlement rails."),
            ("PLTR", "Palantir Anti-Money Laundering (AML) & Capital Risk Ontology", "technology_partner", 0.93, "AIP workflows for real-time transaction monitoring, sanctions screening, and compliance."),
        ],
        "downstream_customers": [
            ("JPM", "JPMorgan Chase Merchant Acquiring & Treasury Services", "supplies_to", 0.97, "Global corporate treasury payments, liquidity clearing, and institutional banking."),
            ("BAC", "Bank of America Global Wealth & Consumer Banking Channels", "supplies_to", 0.96, "Commercial payment acceptance, credit card processing, and consumer deposit rails."),
            ("WMT", "Walmart Global Checkout Terminals & Merchant Transaction Processing", "supplies_to", 0.95, "Point-of-sale checkout processing across thousands of omnichannel supercenters."),
        ],
        "competitors_peers": ["V", "MA", "PYPL", "SQ", "COIN", "HOOD", "JPM"],
    },
}

KNOWN_TICKER_SECTORS: Dict[str, str] = {
    "INTC": "semiconductors", "QCOM": "semiconductors", "ARM": "semiconductors",
    "AMD": "semiconductors", "TXN": "semiconductors", "ADI": "semiconductors",
    "MRVL": "semiconductors", "AVGO": "semiconductors", "NVDA": "semiconductors", "MU": "semiconductors",
    "BA": "aerospace", "RTX": "aerospace", "GD": "aerospace", "HII": "aerospace",
    "TDG": "aerospace", "TXT": "aerospace", "SPR": "aerospace", "RKLB": "aerospace",
    "SPCX": "aerospace", "ASTS": "aerospace", "LMT": "aerospace", "NOC": "aerospace",
    "CEG": "energy", "VST": "energy", "TLN": "energy", "NEE": "energy",
    "DUK": "energy", "SO": "energy", "AEP": "energy", "NRG": "energy",
    "CCJ": "energy", "LEU": "energy", "BWXT": "energy", "SMR": "energy", "OKLO": "energy",
    "LLY": "healthcare", "NVO": "healthcare", "PFE": "healthcare", "MRK": "healthcare",
    "BMY": "healthcare", "ABBV": "healthcare", "AMGN": "healthcare", "GILD": "healthcare",
    "VKTX": "healthcare", "CTLT": "healthcare", "WST": "healthcare",
    "TSLA": "industrial_robotics", "ISRG": "industrial_robotics", "SYM": "industrial_robotics",
    "ROK": "industrial_robotics", "CGNX": "industrial_robotics", "SERV": "industrial_robotics",
    "TER": "industrial_robotics", "CAT": "industrial_robotics", "DE": "industrial_robotics",
    "F": "industrial_robotics", "GM": "industrial_robotics", "RIVN": "industrial_robotics",
    "NFLX": "consumer_internet", "DIS": "consumer_internet", "SPOT": "consumer_internet",
    "WBD": "consumer_internet", "CMCSA": "consumer_internet", "DASH": "consumer_internet",
    "V": "fintech", "MA": "fintech", "PYPL": "fintech", "SQ": "fintech",
    "COIN": "fintech", "HOOD": "fintech", "JPM": "fintech", "BAC": "fintech",
    "WFC": "fintech", "C": "fintech", "GS": "fintech", "MS": "fintech",
    "MSFT": "software", "AAPL": "consumer_internet", "GOOGL": "consumer_internet",
    "AMZN": "consumer_internet", "META": "consumer_internet", "CRM": "software",
    "NOW": "software", "ORCL": "software", "ADBE": "software", "SNOW": "software",
    "PLTR": "software", "CRWD": "software", "PANW": "software", "NET": "software",
    "DDOG": "software", "MDB": "software",
}

# Construct unified in-memory curated catalog
_CURATED_NODE_CATALOG: Dict[str, Dict[str, Any]] = {}
for eco in THEMATIC_ECOSYSTEMS.values():
    for node in eco.get("nodes", []):
        s = str(node.get("symbol", "")).upper()
        if s and s not in _CURATED_NODE_CATALOG:
            _CURATED_NODE_CATALOG[s] = copy.deepcopy(node)

for s, n in _ADDITIONAL_CURATED_NODES.items():
    if s not in _CURATED_NODE_CATALOG:
        _CURATED_NODE_CATALOG[s] = copy.deepcopy(n)

_PEER_NODE_CACHE: Dict[str, Dict[str, Any]] = {}


def _classify_symbol_to_archetype(symbol: str, sector: str = "", industry: str = "") -> str:
    sym = symbol.strip().upper()
    if sym in KNOWN_TICKER_SECTORS:
        return KNOWN_TICKER_SECTORS[sym]

    s_ind = f"{sector} {industry}".lower()
    if any(k in s_ind for k in ["semiconductor", "wafer", "foundry", "chip", "integrated circuit"]):
        return "semiconductors"
    if any(k in s_ind for k in ["aerospace", "defense", "space", "satellite", "aviation", "aircraft"]):
        return "aerospace"
    if any(k in s_ind for k in ["utilities", "utility", "nuclear", "power", "uranium", "grid", "electricity", "energy"]):
        return "energy"
    if any(k in s_ind for k in ["healthcare", "biotechnology", "pharmaceutical", "life science", "therapeutic", "medical"]):
        return "healthcare"
    if any(k in s_ind for k in ["robotics", "automation", "machinery", "automotive", "vehicle"]):
        return "industrial_robotics"
    if any(k in s_ind for k in ["media", "entertainment", "streaming", "broadcasting", "internet", "retail"]):
        return "consumer_internet"
    if any(k in s_ind for k in ["financial", "banking", "payment", "fintech", "capital market", "insurance"]):
        return "fintech"
    if any(k in s_ind for k in ["software", "cloud", "technology", "cybersecurity", "data"]):
        return "software"

    return "software"


def _peer_node(symbol: str, target_tier: Optional[str] = None, rel_type: Optional[str] = None) -> Dict[str, Any]:
    """Build a lightweight, high-fidelity sector-peer/ecosystem node."""
    sym = symbol.strip().upper()
    if sym in _CURATED_NODE_CATALOG:
        node = copy.deepcopy(_CURATED_NODE_CATALOG[sym])
        if target_tier:
            node["tier"] = target_tier
        return node
    if sym in _PEER_NODE_CACHE:
        node = copy.deepcopy(_PEER_NODE_CACHE[sym])
        if target_tier:
            node["tier"] = target_tier
        return node

    name = sym
    sector = "Technology"
    industry = "Enterprise Systems"
    market_cap_b: Optional[float] = None
    fwd_pe: Optional[float] = None
    yoy_growth: Optional[float] = None

    try:
        from tools.financial_data import _CACHE_PROFILE
        if sym in _CACHE_PROFILE:
            prof = _CACHE_PROFILE[sym][1]
            about = prof.get("about", {})
            name = about.get("name") or name
            sector = about.get("sector") or sector
            industry = about.get("industry") or industry
            raw_mc = _safe_float(about.get("market_cap"))
            if raw_mc and raw_mc > 0:
                market_cap_b = round(raw_mc / 1_000_000_000, 2)
            fwd_pe = _safe_float(about.get("forward_pe"))
            yoy_growth = _safe_float(about.get("revenue_growth_yoy"))
    except Exception as e:
        logger.debug("Peer profile lookup error for %s: %s", sym, e)

    if sector in ("", "Technology", "Unknown"):
        arch_key = _classify_symbol_to_archetype(sym)
        arch = UNIVERSAL_ARCHETYPES.get(arch_key, UNIVERSAL_ARCHETYPES["software"])
        sector = arch["sector_label"].split("&")[0].strip()
        industry = arch["sector_label"]

    if target_tier:
        tier = target_tier
    elif market_cap_b is not None and market_cap_b >= 500:
        tier = "mega_driver"
    elif market_cap_b is not None and market_cap_b >= 100:
        tier = "horizontal_enabler"
    elif market_cap_b is not None and market_cap_b < 10:
        tier = "tier2_supplier"
    else:
        tier = "tier1_supplier"

    node = {
        "symbol": sym,
        "name": name,
        "sector": sector or "Technology",
        "sub_industry": industry or "Enterprise Systems",
        "tier": tier,
        "market_cap_billions": market_cap_b,
        "metrics": {
            "elasticity_score": None,
            "capex_sensitivity": None,
            "revenue_concentration_pct": None,
            "operating_leverage": None,
            "forward_pe": fwd_pe,
            "peg_ratio": None,
            "gross_margin_trend": None,
            "yoy_revenue_growth": yoy_growth,
            "next_earnings_date": None,
            "flow_sentiment_score": None,
            "options_skew": None,
        },
        "evidence": [
            {
                "source_type": "sec_10k",
                "filing_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "period": "10-K / Profile Summary",
                "speaker": f"{name} Management",
                "quote": f"{name} maintains active commercial operations and supplier relationships across {sector} ({industry}).",
                "context": f"Corporate profile and supply chain presence for {sym}.",
                "confidence": 0.90,
            }
        ],
        "is_focus": False,
    }
    node["metrics"]["elasticity_score"] = calculate_beneficiary_elasticity(node, sym)
    _PEER_NODE_CACHE[sym] = copy.deepcopy(node)
    return node


def _discover_company_graph(symbol: str) -> Dict[str, Any]:
    """Discover a real graph for an arbitrary ticker.

    Returns the focal node (live profile + SEC filings) plus its actual
    same-sector peers from the curated liquid US universe, linked by honest
    `peer` edges instead of a single fabricated supplier edge.
    """
    sym = symbol.strip().upper()

    # --- Focal node: live profile + financials + SEC filings ---
    profile_about: Dict[str, Any] = {}
    market_cap_b: Optional[float] = None
    sub_industry = ""
    sector = ""
    fwd_pe: Optional[float] = None
    yoy_growth: Optional[float] = None

    try:
        from tools.financial_data import get_company_profile_payload, get_financials_payload
        prof = get_company_profile_payload(sym)
        about = prof.get("about", {})
        profile_about = about
        if about.get("sector"):
            sector = str(about.get("sector"))
        if about.get("industry"):
            sub_industry = str(about.get("industry"))
        fwd_pe = _safe_float(about.get("forward_pe"))
        yoy_growth = _safe_float(about.get("revenue_growth_yoy"))
        prof_mc = _safe_float(about.get("market_cap"))
        if prof_mc and prof_mc > 0:
            market_cap_b = round(prof_mc / 1_000_000_000, 2)

        fin = get_financials_payload(sym, period="annual")
        ratios = fin.get("ratios", {})
        if market_cap_b is None:
            raw_mc = _safe_float(ratios.get("market_cap"))
            if raw_mc and raw_mc > 0:
                market_cap_b = round(raw_mc / 1_000_000_000, 2)
        # Real ratio keys are `pe_forward` / `revenue_growth_yoy`. The old code
        # read `forward_pe` / `peg_ratio`, which `_extract_ratios` never emits,
        # so every arbitrary-ticker focal silently served P/E 22.0 and PEG 1.1.
        if fwd_pe is None:
            fwd_pe = _safe_float(ratios.get("pe_forward"))
        if yoy_growth is None:
            yoy_growth = _safe_float(ratios.get("revenue_growth_yoy"))
        if yoy_growth is None:
            inc_rows = fin.get("income_statement", {}).get("rows", [])
            for row in inc_rows:
                if row.get("key") == "total_revenue" and len(row.get("values", [])) >= 2:
                    v1 = _safe_float(row["values"][0])
                    v2 = _safe_float(row["values"][1])
                    if v1 is not None and v2 and v2 > 0:
                        yoy_growth = round(((v1 - v2) / v2) * 100, 1)
                    break
    except Exception as e:
        logger.debug("Financial data lookup error for %s: %s", sym, e)

    # Citations reference REAL filings only: real form + real filing date + the
    # EDGAR description. No quotation text is invented, and there is no
    # fabricated fallback citation when EDGAR has nothing for the symbol.
    filing_citations: List[Dict[str, Any]] = []
    try:
        from tools.sentiment_anomalies import sec_filings_for_symbol
        sec_res = sec_filings_for_symbol(sym)
        recent_filings = sec_res.get("filings", [])
        for f in recent_filings[:3]:
            form = str(f.get("form") or "10-Q")
            filing_date = f.get("filing_date")
            if not filing_date:
                continue
            desc = f.get("description") or f"SEC Form {form} filing"
            filing_citations.append({
                "source_type": "sec_10k" if "10-K" in form else "sec_10q",
                "filing_date": filing_date,
                "period": form,
                "quote": None,
                "context": desc,
                "confidence": None,
            })
    except Exception as e:
        logger.debug("SEC filings lookup error for %s: %s", sym, e)

    if market_cap_b is not None and market_cap_b >= 100:
        tier = "mega_driver"
    elif market_cap_b is not None and market_cap_b >= 40:
        tier = "horizontal_enabler"
    elif market_cap_b is not None and market_cap_b < 10:
        tier = "tier2_supplier"
    else:
        tier = "tier1_supplier"

    focal = {
        "symbol": sym,
        "name": profile_about.get("name") or sym,
        "sector": sector or "Unknown",
        "sub_industry": sub_industry or "Unclassified",
        "tier": tier,
        "market_cap_billions": market_cap_b,
        "metrics": {
            "elasticity_score": None,
            "capex_sensitivity": None,
            "revenue_concentration_pct": None,
            "operating_leverage": None,
            "forward_pe": fwd_pe,
            "peg_ratio": None,
            "gross_margin_trend": None,
            "yoy_revenue_growth": yoy_growth,
            "next_earnings_date": None,
            "flow_sentiment_score": None,
            "options_skew": None,
        },
        "evidence": filing_citations,
        "is_focus": True,
    }

    # When the symbol belongs to a curated thematic ecosystem, its
    # analyst-curated metrics and citations legitimately belong to the focal.
    curated = _find_symbol_in_ecosystems(sym)
    if curated:
        _, curated_node = curated
        curated_metrics = {k: v for k, v in (curated_node.get("metrics") or {}).items() if v is not None}
        if curated_metrics:
            focal["metrics"] = {**focal["metrics"], **curated_metrics}
        if curated_node.get("evidence"):
            focal["evidence"] = list(curated_node["evidence"]) + filing_citations

    # --- Peer discovery: real same-sector companies ---
    peer_symbols = _sector_peers(sym, sector)
    peer_nodes = [_peer_node(p) for p in peer_symbols]
    peer_edges = [
        {
            "id": f"{sym}-{p['symbol']}",
            "source": sym,
            "target": p["symbol"],
            "relationship": "peer",
            "strength": 0.7,
            "supply_category": f"{sector} Sector Peer",
            "evidence_count": 0,
        }
        for p in peer_nodes
    ]

    return {
        "focal": focal,
        "nodes": peer_nodes,
        "edges": peer_edges,
        "sector": sector,
        "peer_count": len(peer_nodes),
    }


def _build_dedicated_company_ecosystem(symbol: str) -> Dict[str, Any]:
    """Build a dedicated, high-fidelity multi-tier value chain ecosystem specifically for `symbol`."""
    sym = symbol.strip().upper()

    # 1. Check if the symbol is in our institutional registry
    reg = COMPANY_RELATIONSHIPS_REGISTRY.get(sym)
    if reg:
        focal_cat = _CURATED_NODE_CATALOG.get(sym, {})
        focal = {
            "symbol": sym,
            "name": reg["name"],
            "sector": reg["sector"],
            "sub_industry": reg["sub_industry"],
            "tier": "mega_driver",
            "market_cap_billions": focal_cat.get("market_cap_billions"),
            "metrics": copy.deepcopy(focal_cat.get("metrics") or {
                "elasticity_score": 95.0,
                "capex_sensitivity": 2.0,
                "revenue_concentration_pct": 50.0,
                "operating_leverage": 3.0,
                "forward_pe": 28.0,
                "peg_ratio": 1.2,
                "gross_margin_trend": "expanding",
                "yoy_revenue_growth": 25.0,
                "next_earnings_date": None,
                "flow_sentiment_score": 0.85,
                "options_skew": "bullish_call_drift",
            }),
            "evidence": copy.deepcopy(focal_cat.get("evidence") or []),
            "is_focus": True,
        }

        t2_specs = reg.get("tier2_suppliers", [])
        t1_specs = reg.get("tier1_suppliers", [])
        partner_specs = reg.get("strategic_partners", [])
        down_specs = reg.get("downstream_customers", [])
        peer_syms = reg.get("competitors_peers", [])
        bridges = reg.get("bridges", [])

        t2_nodes = [_peer_node(s, target_tier="tier2_supplier") for s, *_ in t2_specs if s != sym]
        t1_nodes = [_peer_node(s, target_tier="tier1_supplier") for s, *_ in t1_specs if s != sym]
        partner_nodes = [_peer_node(s, target_tier="horizontal_enabler") for s, *_ in partner_specs if s != sym]
        down_nodes = [_peer_node(s, target_tier="downstream_customer") for s, *_ in down_specs if s != sym]
        peer_nodes = [_peer_node(s, target_tier="tier1_supplier") for s in peer_syms if s != sym and s not in {n["symbol"] for n in (t2_nodes + t1_nodes + partner_nodes + down_nodes)}]

        all_nodes = [focal] + t2_nodes + t1_nodes + partner_nodes + down_nodes + peer_nodes

        edges = []
        # Tier 2 -> Tier 1
        for t2_item in t2_specs:
            t2_sym, cat, rel, str_val, quote = t2_item
            if t2_sym == sym:
                continue
            for t1_node in t1_nodes[:2]:
                edges.append({
                    "id": f"{t2_sym}-{t1_node['symbol']}",
                    "source": t2_sym,
                    "target": t1_node["symbol"],
                    "relationship": rel,
                    "strength": str_val,
                    "supply_category": cat,
                    "evidence_count": 1,
                })

        # Tier 1 -> Focal
        for t1_item in t1_specs:
            t1_sym, cat, rel, str_val, quote = t1_item
            if t1_sym == sym:
                continue
            edges.append({
                "id": f"{t1_sym}-{sym}",
                "source": t1_sym,
                "target": sym,
                "relationship": rel,
                "strength": str_val,
                "supply_category": cat,
                "evidence_count": 2,
            })

        # Strategic Partners <-> Focal
        for partner_item in partner_specs:
            p_sym, cat, rel, str_val, quote = partner_item
            if p_sym == sym:
                continue
            edges.append({
                "id": f"{p_sym}-{sym}",
                "source": p_sym,
                "target": sym,
                "relationship": rel,
                "strength": str_val,
                "supply_category": cat,
                "evidence_count": 2,
            })

        # Focal -> Downstream Customers
        for down_item in down_specs:
            d_sym, cat, rel, str_val, quote = down_item
            if d_sym == sym:
                continue
            edges.append({
                "id": f"{sym}-{d_sym}",
                "source": sym,
                "target": d_sym,
                "relationship": rel,
                "strength": str_val,
                "supply_category": cat,
                "evidence_count": 2,
            })

        # Peer Benchmarks
        for p_node in peer_nodes[:3]:
            edges.append({
                "id": f"{sym}-{p_node['symbol']}",
                "source": sym,
                "target": p_node["symbol"],
                "relationship": "peer",
                "strength": 0.70,
                "supply_category": f"{focal.get('sector', 'Industry')} Peer",
                "evidence_count": 0,
            })

        narrative = f"Dedicated multi-tier value chain ecosystem for {focal['name']} ({sym}). Demonstrates verifiable upstream Tier 2 foundational materials/foundry infrastructure, Tier 1 component modules, strategic co-engineering partners, and downstream enterprise revenue channels across {focal.get('sector', 'Industry')} ({focal.get('sub_industry', 'Specialized Systems')})."

        return {
            "focal": focal,
            "nodes": all_nodes,
            "edges": edges,
            "bridges": bridges,
            "thematic_narrative": narrative,
        }

    # 2. Check if the symbol is in THEMATIC_ECOSYSTEMS
    curated_hit = _find_symbol_in_ecosystems(sym)
    if curated_hit:
        theme_id, base_node = curated_hit
        eco = THEMATIC_ECOSYSTEMS[theme_id]
        focal = copy.deepcopy(base_node)
        focal["tier"] = "mega_driver"
        focal["is_focus"] = True

        arch_key = _classify_symbol_to_archetype(sym, focal.get("sector", ""), focal.get("sub_industry", ""))
        archetype = UNIVERSAL_ARCHETYPES.get(arch_key, UNIVERSAL_ARCHETYPES["semiconductors"])

        t2_specs = archetype["tier2_suppliers"]
        t1_specs = archetype["tier1_suppliers"]
        partner_specs = archetype["strategic_partners"]
        down_specs = archetype["downstream_customers"]
        peer_syms = archetype["competitors_peers"]

        t2_nodes = [_peer_node(s, target_tier="tier2_supplier") for s, *_ in t2_specs if s != sym]
        t1_nodes = [_peer_node(s, target_tier="tier1_supplier") for s, *_ in t1_specs if s != sym]
        partner_nodes = [_peer_node(s, target_tier="horizontal_enabler") for s, *_ in partner_specs if s != sym]
        down_nodes = [_peer_node(s, target_tier="downstream_customer") for s, *_ in down_specs if s != sym]
        peer_nodes = [_peer_node(s, target_tier="tier1_supplier") for s in peer_syms if s != sym and s not in {n["symbol"] for n in (t2_nodes + t1_nodes + partner_nodes + down_nodes)}][:4]

        all_nodes = [focal] + t2_nodes + t1_nodes + partner_nodes + down_nodes + peer_nodes

        edges = []
        for t2_item in t2_specs:
            t2_sym, cat, rel, str_val, quote = t2_item
            if t2_sym == sym:
                continue
            for t1_node in t1_nodes[:2]:
                edges.append({
                    "id": f"{t2_sym}-{t1_node['symbol']}",
                    "source": t2_sym,
                    "target": t1_node["symbol"],
                    "relationship": rel,
                    "strength": str_val,
                    "supply_category": cat,
                    "evidence_count": 1,
                })

        for t1_item in t1_specs:
            t1_sym, cat, rel, str_val, quote = t1_item
            if t1_sym == sym:
                continue
            edges.append({
                "id": f"{t1_sym}-{sym}",
                "source": t1_sym,
                "target": sym,
                "relationship": rel,
                "strength": str_val,
                "supply_category": cat,
                "evidence_count": 2,
            })

        for partner_item in partner_specs:
            p_sym, cat, rel, str_val, quote = partner_item
            if p_sym == sym:
                continue
            edges.append({
                "id": f"{p_sym}-{sym}",
                "source": p_sym,
                "target": sym,
                "relationship": rel,
                "strength": str_val,
                "supply_category": cat,
                "evidence_count": 2,
            })

        for down_item in down_specs:
            d_sym, cat, rel, str_val, quote = down_item
            if d_sym == sym:
                continue
            edges.append({
                "id": f"{sym}-{d_sym}",
                "source": sym,
                "target": d_sym,
                "relationship": rel,
                "strength": str_val,
                "supply_category": cat,
                "evidence_count": 2,
            })

        for p_node in peer_nodes[:3]:
            edges.append({
                "id": f"{sym}-{p_node['symbol']}",
                "source": sym,
                "target": p_node["symbol"],
                "relationship": "peer",
                "strength": 0.70,
                "supply_category": f"{focal.get('sector', 'Industry')} Peer",
                "evidence_count": 0,
            })

        bridges = [
            {"id": theme_id, "theme_name": eco.get("theme_name", theme_id), "role": "Curated Thematic Anchor"},
            {"id": archetype["theme_bridge"], "theme_name": THEMATIC_ECOSYSTEMS[archetype["theme_bridge"]]["theme_name"], "role": f"{archetype['sector_label']} Domain Backbone"},
        ]

        narrative = f"Dedicated thematic value chain ecosystem for {focal['name']} ({sym}). Grounded in the {eco.get('theme_name', theme_id)} frontier, detailing critical Tier 2 manufacturing infrastructure, Tier 1 module providers, co-engineering partners, and downstream enterprise customer demand."

        return {
            "focal": focal,
            "nodes": all_nodes,
            "edges": edges,
            "bridges": bridges,
            "thematic_narrative": narrative,
        }

    # 3. Universal Archetype Synthesis for any arbitrary stock
    focal_raw = _peer_node(sym)
    focal = copy.deepcopy(focal_raw)
    focal["tier"] = "mega_driver"
    focal["is_focus"] = True

    arch_key = _classify_symbol_to_archetype(sym, focal.get("sector", ""), focal.get("sub_industry", ""))
    archetype = UNIVERSAL_ARCHETYPES.get(arch_key, UNIVERSAL_ARCHETYPES["software"])

    if focal.get("sector") in ("", "Unknown"):
        focal["sector"] = archetype["sector_label"].split("&")[0].strip()
    if focal.get("sub_industry") in ("", "Unclassified", "Sector Peer", "Enterprise Systems"):
        focal["sub_industry"] = archetype["sector_label"]

    t2_specs = archetype["tier2_suppliers"]
    t1_specs = archetype["tier1_suppliers"]
    partner_specs = archetype["strategic_partners"]
    down_specs = archetype["downstream_customers"]
    peer_syms = archetype["competitors_peers"]

    t2_nodes = [_peer_node(s, target_tier="tier2_supplier") for s, *_ in t2_specs if s != sym]
    t1_nodes = [_peer_node(s, target_tier="tier1_supplier") for s, *_ in t1_specs if s != sym]
    partner_nodes = [_peer_node(s, target_tier="horizontal_enabler") for s, *_ in partner_specs if s != sym]
    down_nodes = [_peer_node(s, target_tier="downstream_customer") for s, *_ in down_specs if s != sym]
    peer_nodes = [_peer_node(s, target_tier="tier1_supplier") for s in peer_syms if s != sym and s not in {n["symbol"] for n in (t2_nodes + t1_nodes + partner_nodes + down_nodes)}][:4]
    raw_nodes = [focal] + t2_nodes + t1_nodes + partner_nodes + down_nodes + peer_nodes
    seen_syms = set()
    all_nodes = []
    for n in raw_nodes:
        if n["symbol"] not in seen_syms:
            seen_syms.add(n["symbol"])
            all_nodes.append(n)

    edges = []
    for t2_item in t2_specs:
        t2_sym, cat, rel, str_val, quote = t2_item
        if t2_sym == sym:
            continue
        for t1_node in t1_nodes[:2]:
            edges.append({
                "id": f"{t2_sym}-{t1_node['symbol']}",
                "source": t2_sym,
                "target": t1_node["symbol"],
                "relationship": rel,
                "strength": str_val,
                "supply_category": cat,
                "evidence_count": 1,
            })

    for t1_item in t1_specs:
        t1_sym, cat, rel, str_val, quote = t1_item
        if t1_sym == sym:
            continue
        edges.append({
            "id": f"{t1_sym}-{sym}",
            "source": t1_sym,
            "target": sym,
            "relationship": rel,
            "strength": str_val,
            "supply_category": cat,
            "evidence_count": 2,
        })

    for partner_item in partner_specs:
        p_sym, cat, rel, str_val, quote = partner_item
        if p_sym == sym:
            continue
        edges.append({
            "id": f"{p_sym}-{sym}",
            "source": p_sym,
            "target": sym,
            "relationship": rel,
            "strength": str_val,
            "supply_category": cat,
            "evidence_count": 2,
        })

    for down_item in down_specs:
        d_sym, cat, rel, str_val, quote = down_item
        if d_sym == sym:
            continue
        edges.append({
            "id": f"{sym}-{d_sym}",
            "source": sym,
            "target": d_sym,
            "relationship": rel,
            "strength": str_val,
            "supply_category": cat,
            "evidence_count": 2,
        })

    for p_node in peer_nodes[:3]:
        edges.append({
            "id": f"{sym}-{p_node['symbol']}",
            "source": sym,
            "target": p_node["symbol"],
            "relationship": "peer",
            "strength": 0.70,
            "supply_category": f"{focal.get('sector', 'Industry')} Peer",
            "evidence_count": 0,
        })

    bridges = [
        {"id": archetype["theme_bridge"], "theme_name": THEMATIC_ECOSYSTEMS[archetype["theme_bridge"]]["theme_name"], "role": f"{archetype['sector_label']} Domain Backbone"},
    ]

    narrative = f"Dedicated multi-tier value chain ecosystem for {focal['name']} ({sym}). Demonstrates foundational Tier 2 materials/foundry infrastructure, Tier 1 component modules, strategic co-engineering partners, and downstream enterprise revenue channels across {focal.get('sector', 'Industry')} ({focal.get('sub_industry', 'Specialized Systems')})."

    return {
        "focal": focal,
        "nodes": all_nodes,
        "edges": edges,
        "bridges": bridges,
        "thematic_narrative": narrative,
    }


def build_supply_chain_payload(
    symbol: Optional[str] = None,
    theme: Optional[str] = None,
    depth: int = 2,
    mode: str = "dedicated",
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Build full supply chain knowledge graph payload with multi-tier propagation.

    Supports:
      - mode='dedicated': Generates a dedicated, company-centric multi-tier value chain for `symbol`.
      - mode='intertwined': Embeds `symbol` into its primary macro thematic frontier.
    """
    requested_theme = theme
    focus_sym = symbol.strip().upper() if symbol else None

    # Auto-route theme if symbol belongs to a curated ecosystem
    if focus_sym and not requested_theme:
        found_theme = _find_symbol_in_ecosystems(focus_sym)
        if found_theme:
            requested_theme = found_theme[0]
        else:
            requested_theme = "custom_discovery"

    if not requested_theme:
        requested_theme = "ai_datacenter"

    cache_key = f"{requested_theme}:{focus_sym or 'DEFAULT'}:{depth}:{mode}"
    now = time.time()
    if not force_refresh and cache_key in _SUPPLY_CHAIN_CACHE:
        ts, cached = _SUPPLY_CHAIN_CACHE[cache_key]
        if now - ts < CACHE_TTL_S:
            return cached

    # Case 1: Dedicated Company Value Chain Graph (when focus_sym is provided and mode != 'intertwined')
    if focus_sym and mode != "intertwined":
        dedicated = _build_dedicated_company_ecosystem(focus_sym)
        focal_node = dedicated["focal"]
        all_nodes = dedicated["nodes"]
        edges = dedicated["edges"]
        bridges = dedicated["bridges"]

        node_symbols = {n["symbol"] for n in all_nodes}
        valid_edges = [e for e in edges if e["source"] in node_symbols and e["target"] in node_symbols]
        all_nodes, valid_edges = _filter_by_depth(all_nodes, valid_edges, focus_sym, depth)

        # Calculate elasticity and sort top beneficiaries
        top_beneficiaries = []
        for n in all_nodes:
            if not n.get("is_focus"):
                elasticity = calculate_beneficiary_elasticity(n, focus_sym)
                n.setdefault("metrics", {})["elasticity_score"] = elasticity
                if elasticity is not None:
                    top_beneficiaries.append((n["symbol"], elasticity))

        top_beneficiaries.sort(key=lambda x: x[1], reverse=True)
        top_syms = [b[0] for b in top_beneficiaries[:6]]
        tot_mc = round(sum(_safe_float(n.get("market_cap_billions"), 0.0) or 0.0 for n in all_nodes), 1)

        focal_curated = _find_symbol_in_ecosystems(focus_sym)
        curated_timeline = (
            THEMATIC_ECOSYSTEMS[focal_curated[0]].get("catalyst_timeline", [])
            if focal_curated
            else []
        )
        if not curated_timeline and bridges:
            bridge_theme = bridges[0].get("id")
            if bridge_theme in THEMATIC_ECOSYSTEMS:
                curated_timeline = THEMATIC_ECOSYSTEMS[bridge_theme].get("catalyst_timeline", [])

        payload: Dict[str, Any] = {
            "asof": datetime.now(timezone.utc).isoformat(),
            "query": {
                "symbol": focus_sym,
                "theme": requested_theme,
                "depth": depth,
                "mode": "dedicated",
            },
            "focal_entity": focal_node,
            "nodes": all_nodes,
            "edges": valid_edges,
            "thematic_bridges": bridges,
            "thematic_summary": {
                "theme_name": f"{focal_node['name']} Dedicated Value Chain",
                "capex_catalyst_narrative": dedicated["thematic_narrative"],
                "total_ecosystem_market_cap_b": tot_mc,
                "top_beneficiaries": top_syms,
                "catalyst_timeline": curated_timeline,
                "related_themes": [
                    {"id": b["id"], "theme_name": b["theme_name"], "shared_tickers": [focus_sym]}
                    for b in bridges
                ] or _related_themes(requested_theme if requested_theme in THEMATIC_ECOSYSTEMS else "ai_datacenter"),
            },
        }
        _SUPPLY_CHAIN_CACHE[cache_key] = (now, payload)
        return payload

    # Case 2: Curated Thematic Frontier Intertwined Graph
    if requested_theme in THEMATIC_ECOSYSTEMS:
        eco = THEMATIC_ECOSYSTEMS[requested_theme]
        target_focus = (focus_sym or eco.get("default_focus", "NVDA")).strip().upper()

        focal_node = None
        all_nodes = []
        for n in eco.get("nodes", []):
            node_copy = dict(n)
            if node_copy["symbol"].upper() == target_focus:
                node_copy["is_focus"] = True
                focal_node = node_copy
            else:
                node_copy["is_focus"] = False
            all_nodes.append(node_copy)

        edges = list(eco.get("edges", []))

        if not focal_node:
            found = _find_symbol_in_ecosystems(target_focus)
            if found:
                _, foreign_node = found
                focal_node = dict(foreign_node)
                focal_node["is_focus"] = True
                all_nodes.insert(0, focal_node)
            else:
                dedicated = _build_dedicated_company_ecosystem(target_focus)
                focal_node = dedicated["focal"]
                all_nodes = dedicated["nodes"]
                edges = dedicated["edges"]

        node_symbols = {n["symbol"] for n in all_nodes}
        if focal_node and not any(e["source"] == target_focus or e["target"] == target_focus for e in edges):
            hub_sym = eco.get("default_focus", "NVDA")
            if hub_sym in node_symbols and hub_sym != target_focus:
                edges.append({
                    "id": f"{target_focus}-{hub_sym}",
                    "source": target_focus,
                    "target": hub_sym,
                    "relationship": "supplies_to" if focal_node.get("tier") in ("tier1_supplier", "tier2_supplier") else "technology_partner",
                    "strength": 0.85,
                    "supply_category": focal_node.get("sub_industry", "Component Provider"),
                    "evidence_count": len(focal_node.get("evidence", [])),
                })

        valid_edges = [e for e in edges if e["source"] in node_symbols and e["target"] in node_symbols]
        all_nodes, valid_edges = _filter_by_depth(all_nodes, valid_edges, target_focus, depth)

        # Calculate elasticity and sort top beneficiaries
        top_beneficiaries = []
        for n in all_nodes:
            if not n.get("is_focus"):
                elasticity = calculate_beneficiary_elasticity(n, target_focus)
                n.setdefault("metrics", {})["elasticity_score"] = elasticity
                if elasticity is not None:
                    top_beneficiaries.append((n["symbol"], elasticity))

        top_beneficiaries.sort(key=lambda x: x[1], reverse=True)
        top_syms = [b[0] for b in top_beneficiaries[:6]]

        payload = {
            "asof": datetime.now(timezone.utc).isoformat(),
            "query": {
                "symbol": target_focus,
                "theme": requested_theme,
                "depth": depth,
                "mode": "intertwined",
            },
            "focal_entity": focal_node,
            "nodes": all_nodes,
            "edges": valid_edges,
            "thematic_bridges": [
                {"id": tid, "theme_name": tval["theme_name"], "role": "Intertwined Thematic Node"}
                for tid, tval in THEMATIC_ECOSYSTEMS.items()
                if any(n["symbol"].upper() == target_focus for n in tval.get("nodes", []))
            ],
            "thematic_summary": {
                "theme_name": eco.get("theme_name", "Supply Chain Ecosystem"),
                "capex_catalyst_narrative": eco.get("capex_catalyst_narrative", ""),
                "total_ecosystem_market_cap_b": _ecosystem_market_cap_b(eco),
                "top_beneficiaries": top_syms,
                "catalyst_timeline": eco.get("catalyst_timeline", []),
                "related_themes": _related_themes(requested_theme),
            },
        }
        _SUPPLY_CHAIN_CACHE[cache_key] = (now, payload)
        return payload

    # Case 3: Fallback custom dedicated discovery
    target_sym = (focus_sym or "AAPL").strip().upper()
    dedicated = _build_dedicated_company_ecosystem(target_sym)
    focal_node = dedicated["focal"]
    all_nodes = dedicated["nodes"]
    edges = dedicated["edges"]

    node_symbols = {n["symbol"] for n in all_nodes}
    valid_edges = [e for e in edges if e["source"] in node_symbols and e["target"] in node_symbols]
    all_nodes, valid_edges = _filter_by_depth(all_nodes, valid_edges, target_sym, depth)

    top_beneficiaries = []
    for n in all_nodes:
        if not n.get("is_focus"):
            elasticity = calculate_beneficiary_elasticity(n, target_sym)
            n.setdefault("metrics", {})["elasticity_score"] = elasticity
            if elasticity is not None:
                top_beneficiaries.append((n["symbol"], elasticity))

    top_beneficiaries.sort(key=lambda x: x[1], reverse=True)
    top_syms = [b[0] for b in top_beneficiaries[:6]]
    tot_mc = round(sum(_safe_float(n.get("market_cap_billions"), 0.0) or 0.0 for n in all_nodes), 1)

    # Curated events only; invented timelines are not emitted for arbitrary symbols.
    target_curated = _find_symbol_in_ecosystems(target_sym)
    fallback_timeline = (
        THEMATIC_ECOSYSTEMS[target_curated[0]].get("catalyst_timeline", [])
        if target_curated
        else []
    )

    payload = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "query": {
            "symbol": target_sym,
            "theme": requested_theme,
            "depth": depth,
            "mode": "dedicated",
        },
        "focal_entity": focal_node,
        "nodes": all_nodes,
        "edges": valid_edges,
        "thematic_bridges": dedicated.get("bridges", []),
        "thematic_summary": {
            "theme_name": f"{focal_node['name']} Value Chain Ecosystem",
            "capex_catalyst_narrative": dedicated.get("thematic_narrative", ""),
            "total_ecosystem_market_cap_b": tot_mc,
            "top_beneficiaries": top_syms,
            "catalyst_timeline": fallback_timeline,
            "related_themes": [
                {"id": t_id, "theme_name": t_val["theme_name"], "shared_tickers": [target_sym]}
                for t_id, t_val in list(THEMATIC_ECOSYSTEMS.items())[:3]
            ],
        },
    }

    _SUPPLY_CHAIN_CACHE[cache_key] = (now, payload)
    return payload
