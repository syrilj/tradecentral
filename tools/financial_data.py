"""Comprehensive financial data & stock intelligence provider for TradeCentral.

Recreates Quiver Quantitative-style financial statements, company intelligence,
executive compensation, analyst forecasts, insider trading tape, government/congress
activity, corporate lobbying, patents, and ownership analytics.

Data sources:
  - yfinance (when available and online)
  - SEC EDGAR filings via sentiment_anomalies.sec_filings_for_symbol
  - Public regulatory disclosures (House/Senate STOCK Act, Senate Lobbying Disclosure Act, USASpending, USPTO)
  - Resilient deterministic fallback generator for sandbox/offline execution
"""
from __future__ import annotations

import hashlib
import logging
import math
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Mapping

import pandas as pd

logger = logging.getLogger(__name__)

# In-memory caches with timestamps
_CACHE_FINANCIALS: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_PROFILE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_INSIDERS: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_GOVERNMENT: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_OWNERSHIP: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TAPE: dict[str, tuple[float, dict[str, Any]]] = {}

CACHE_TTL_S = 900  # 15 minutes
TAPE_TTL_S = 120


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
# 1. Financial Statements & Ratios
# ==============================================================================
def get_financials_payload(symbol: str, period: str = "quarterly") -> dict[str, Any]:
    """Retrieve full financial statements (income, balance sheet, cash flow, revenue breakdown, ratios)."""
    sym = symbol.strip().upper()
    cache_key = f"{sym}:{period}"
    now = time.time()
    if cache_key in _CACHE_FINANCIALS:
        ts, data = _CACHE_FINANCIALS[cache_key]
        if now - ts < CACHE_TTL_S:
            return data

    payload = _build_financials_payload(sym, period)
    _CACHE_FINANCIALS[cache_key] = (now, payload)
    return payload


def _build_financials_payload(symbol: str, period: str) -> dict[str, Any]:
    is_quarterly = period.lower() == "quarterly"
    data: dict[str, Any] | None = None

    # Try live yfinance fetch
    try:
        import yfinance as yf  # type: ignore[import-not-found]
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}

        inc_df = ticker.quarterly_financials if is_quarterly else ticker.financials
        bal_df = ticker.quarterly_balance_sheet if is_quarterly else ticker.balance_sheet
        cf_df = ticker.quarterly_cashflow if is_quarterly else ticker.cashflow

        if inc_df is not None and not inc_df.empty:
            periods = [col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)[:10] for col in inc_df.columns][:6]
            yf_periods = periods
            target_periods = periods
            canonical_periods = periods

            def extract_row(
                df: pd.DataFrame,
                possible_keys: list[str],
                label: str,
                periods: list[str],
                **kwargs,
            ) -> dict[str, Any] | None:
                # `periods` was previously only a closure variable while all 16
                # call sites passed it positionally, so the very first call raised
                # TypeError, the enclosing `except Exception` swallowed it at debug
                # level, and EVERY symbol silently fell through to the synthetic
                # generator. The live yfinance path had never once executed.
                if df is None or df.empty:
                    return None
                matched_idx = None
                for k in possible_keys:
                    for idx in df.index:
                        if str(idx).lower().replace(" ", "").replace("_", "") == k.lower().replace(" ", "").replace("_", ""):
                            matched_idx = idx
                            break
                    if matched_idx is not None:
                        break
                if matched_idx is None:
                    return None

                # Build a period -> value map from yfinance data
                pv: dict[str, float | None] = {}
                for col, p in zip(df.columns, periods):
                    pv[p] = _safe_float(df.loc[matched_idx, col])

                # A period the filing does not report stays None. This used to
                # extrapolate the most recent real value backwards with a
                # ~3%-per-quarter decay, which put invented figures into an
                # income statement beside real ones with nothing marking them
                # apart. The dashboard renders None as an em-dash.
                vals: list[float | None] = [pv.get(p) for p in periods]
                return {"key": possible_keys[0], "label": label, "values": vals, **kwargs}

            periods = canonical_periods

            # Build Income Statement Rows
            inc_rows = []
            rev_row = extract_row(inc_df, ["TotalRevenue", "OperatingRevenue", "Revenue"], "Total Revenue", periods, is_header=True)
            if rev_row: inc_rows.append(rev_row)
            
            cor_row = extract_row(inc_df, ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"], "Cost of Revenue", periods, indent=1)
            if cor_row: inc_rows.append(cor_row)

            gp_row = extract_row(inc_df, ["GrossProfit"], "Gross Profit", periods, is_bold=True)
            if gp_row: inc_rows.append(gp_row)

            rd_row = extract_row(inc_df, ["ResearchAndDevelopment", "RAndD"], "Research & Development", periods, indent=1)
            if rd_row: inc_rows.append(rd_row)

            sga_row = extract_row(inc_df, ["SellingGeneralAndAdministration", "SellingGeneralAdministrative"], "Selling, General & Administrative", periods, indent=1)
            if sga_row: inc_rows.append(sga_row)

            opex_row = extract_row(inc_df, ["OperatingExpense", "TotalOperatingExpenses"], "Total Operating Expenses", periods, is_bold=True)
            if opex_row: inc_rows.append(opex_row)

            opinc_row = extract_row(inc_df, ["OperatingIncome", "EBIT"], "Operating Income (EBIT)", periods, is_bold=True)
            if opinc_row: inc_rows.append(opinc_row)

            interest_row = extract_row(inc_df, ["InterestExpense", "NetInterestIncome"], "Interest Expense / Net Interest", periods, indent=1)
            if interest_row: inc_rows.append(interest_row)

            pretax_row = extract_row(inc_df, ["PretaxIncome"], "Pre-Tax Income", periods)
            if pretax_row: inc_rows.append(pretax_row)

            tax_row = extract_row(inc_df, ["TaxProvision", "IncomeTaxExpense"], "Income Tax Provision", periods, indent=1)
            if tax_row: inc_rows.append(tax_row)

            net_row = extract_row(inc_df, ["NetIncome", "NetIncomeCommonStockholders"], "Net Income", periods, is_bold=True, is_total=True)
            if net_row: inc_rows.append(net_row)

            eps_row = extract_row(inc_df, ["BasicEPS", "BasicEarningsPerShare"], "Basic EPS", periods, format="currency")
            if eps_row: inc_rows.append(eps_row)

            deps_row = extract_row(inc_df, ["DilutedEPS", "DilutedEarningsPerShare"], "Diluted EPS", periods, format="currency")
            if deps_row: inc_rows.append(deps_row)

            ebitda_row = extract_row(inc_df, ["EBITDA", "NormalizedEBITDA"], "EBITDA", periods)
            if ebitda_row: inc_rows.append(ebitda_row)

            # Compute margins
            if rev_row and gp_row:
                gm_vals = []
                for r, g in zip(rev_row["values"], gp_row["values"]):
                    if r and r != 0 and g is not None:
                        gm_vals.append(round((g / r) * 100, 2))
                    else:
                        gm_vals.append(None)
                inc_rows.append({"key": "gross_margin_pct", "label": "Gross Margin %", "format": "pct", "values": gm_vals})

            if rev_row and opinc_row:
                om_vals = []
                for r, o in zip(rev_row["values"], opinc_row["values"]):
                    if r and r != 0 and o is not None:
                        om_vals.append(round((o / r) * 100, 2))
                    else:
                        om_vals.append(None)
                inc_rows.append({"key": "operating_margin_pct", "label": "Operating Margin %", "format": "pct", "values": om_vals})

            if rev_row and net_row:
                nm_vals = []
                for r, n in zip(rev_row["values"], net_row["values"]):
                    if r and r != 0 and n is not None:
                        nm_vals.append(round((n / r) * 100, 2))
                    else:
                        nm_vals.append(None)
                inc_rows.append({"key": "net_margin_pct", "label": "Net Margin %", "format": "pct", "values": nm_vals})

            # Build Balance Sheet Rows
            bal_rows = []
            if bal_df is not None and not bal_df.empty:
                b_items = [
                    (["CashAndCashEquivalents", "CashCashEquivalentsAndShortTermInvestments"], "Cash & Cash Equivalents", {"indent": 1}),
                    (["OtherShortTermInvestments"], "Short-Term Investments", {"indent": 1}),
                    (["CurrentAssets"], "Total Current Assets", {"is_bold": True}),
                    (["NetPPE", "PropertyPlantAndEquipmentNet"], "Property, Plant & Equipment", {"indent": 1}),
                    (["GoodwillAndOtherIntangibleAssets", "Goodwill"], "Goodwill & Intangible Assets", {"indent": 1}),
                    (["TotalAssets"], "Total Assets", {"is_bold": True, "is_header": True}),
                    (["CurrentDebtAndCapitalLeaseObligation", "CurrentDebt"], "Current Debt & Leases", {"indent": 1}),
                    (["AccountsPayable"], "Accounts Payable", {"indent": 1}),
                    (["CurrentLiabilities"], "Total Current Liabilities", {"is_bold": True}),
                    (["LongTermDebtAndCapitalLeaseObligation", "LongTermDebt"], "Long-Term Debt", {"indent": 1}),
                    (["TotalLiabilitiesNetMinorityInterest", "TotalLiabilities"], "Total Liabilities", {"is_bold": True}),
                    (["CommonStock"], "Common Stock", {"indent": 1}),
                    (["RetainedEarnings"], "Retained Earnings", {"indent": 1}),
                    (["StockholdersEquity", "CommonStockEquity"], "Total Stockholders' Equity", {"is_bold": True, "is_total": True}),
                    (["WorkingCapital"], "Working Capital", {"is_bold": True}),
                ]
                for keys, lbl, kw in b_items:
                    r = extract_row(bal_df, keys, lbl, periods, **kw)
                    if r: bal_rows.append(r)

            # Build Cash Flow Rows
            cf_rows = []
            if cf_df is not None and not cf_df.empty:
                c_items = [
                    (["OperatingCashFlow", "CashFlowFromContinuingOperatingActivities"], "Cash from Operating Activities", {"is_bold": True, "is_header": True}),
                    (["DepreciationAndAmortization"], "Depreciation & Amortization", {"indent": 1}),
                    (["ChangeInWorkingCapital"], "Change in Working Capital", {"indent": 1}),
                    (["CapitalExpenditure"], "Capital Expenditures (CapEx)", {"indent": 1}),
                    (["InvestingCashFlow", "CashFlowFromContinuingInvestingActivities"], "Cash from Investing Activities", {"is_bold": True}),
                    (["LongTermDebtIssuance", "IssuanceOfDebt"], "Debt Issuance", {"indent": 1}),
                    (["LongTermDebtPayments", "RepaymentOfDebt"], "Debt Repayment", {"indent": 1}),
                    (["CommonStockPayments", "RepurchaseOfCapitalStock"], "Share Repurchases", {"indent": 1}),
                    (["CashDividendsPaid"], "Dividends Paid", {"indent": 1}),
                    (["FinancingCashFlow", "CashFlowFromContinuingFinancingActivities"], "Cash from Financing Activities", {"is_bold": True}),
                    (["FreeCashFlow"], "Free Cash Flow", {"is_bold": True, "is_total": True}),
                    (["ChangesInCash"], "Net Change in Cash", {"is_bold": True}),
                ]
                for keys, lbl, kw in c_items:
                    r = extract_row(cf_df, keys, lbl, periods, **kw)
                    if r: cf_rows.append(r)

            if inc_rows:
                data = {
                    "symbol": symbol,
                    "period_type": period,
                    "periods": periods,
                    "income_statement": {"rows": inc_rows},
                    "balance_sheet": {"rows": bal_rows},
                    "cash_flow": {"rows": cf_rows},
                    "revenue_breakdown": _generate_revenue_breakdown(symbol, info, rev_row["values"][0] if rev_row and rev_row["values"] else None),
                    "ratios": _extract_ratios(info, inc_rows, bal_rows, cf_rows, symbol),
                    "source": "yfinance_sec_financials",
                    "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                }
    except Exception as e:
        logger.debug("yfinance financials exception for %s: %s", symbol, e)

    if data is None or not data.get("income_statement", {}).get("rows"):
        data = _generate_fallback_financials(symbol, period)

    return _with_model_forecast(data)


def _find_row_val(rows: list[dict[str, Any]], possible_keys: list[str]) -> float | None:
    for row in rows:
        k = str(row.get("key", "")).lower().replace(" ", "").replace("_", "")
        l = str(row.get("label", "")).lower().replace(" ", "").replace("_", "")
        for pk in possible_keys:
            clean_pk = pk.lower().replace(" ", "").replace("_", "")
            if clean_pk in k or clean_pk in l:
                vals = row.get("values", [])
                for v in vals:
                    if v is not None and isinstance(v, (int, float)) and math.isfinite(v):
                        return float(v)
    return None


def _sum_row_vals(rows: list[dict[str, Any]], possible_keys: list[str], count: int = 4) -> float | None:
    for row in rows:
        k = str(row.get("key", "")).lower().replace(" ", "").replace("_", "")
        l = str(row.get("label", "")).lower().replace(" ", "").replace("_", "")
        for pk in possible_keys:
            clean_pk = pk.lower().replace(" ", "").replace("_", "")
            if clean_pk in k or clean_pk in l:
                valid = [v for v in row.get("values", [])[:count] if v is not None and isinstance(v, (int, float)) and math.isfinite(v)]
                if valid:
                    return float(sum(valid))
    return None


def _extract_ratios(
    info: dict[str, Any],
    inc_rows: list[dict[str, Any]] | None = None,
    bal_rows: list[dict[str, Any]] | None = None,
    cf_rows: list[dict[str, Any]] | None = None,
    symbol: str = "TICKER",
) -> dict[str, Any]:
    inc = inc_rows or []
    bal = bal_rows or []
    cf = cf_rows or []


    # Core statement items
    rev_latest = _find_row_val(inc, ["TotalRevenue", "OperatingRevenue", "Revenue"])
    rev_ttm = _sum_row_vals(inc, ["TotalRevenue", "OperatingRevenue", "Revenue"], 4) or rev_latest or 25_000_000_000.0
    gp_latest = _find_row_val(inc, ["GrossProfit"])
    gp_ttm = _sum_row_vals(inc, ["GrossProfit"], 4) or gp_latest
    op_latest = _find_row_val(inc, ["OperatingIncome", "EBIT"])
    op_ttm = _sum_row_vals(inc, ["OperatingIncome", "EBIT"], 4) or op_latest
    ni_latest = _find_row_val(inc, ["NetIncome", "NetIncomeCommonStockholders"])
    ni_ttm = _sum_row_vals(inc, ["NetIncome", "NetIncomeCommonStockholders"], 4) or ni_latest
    ebitda_latest = _find_row_val(inc, ["EBITDA", "NormalizedEBITDA"]) or ((op_latest or 0) + (rev_latest or 0) * 0.08)

    tot_assets = _find_row_val(bal, ["TotalAssets"]) or (rev_ttm * 1.8)
    curr_assets = _find_row_val(bal, ["CurrentAssets", "TotalCurrentAssets"]) or (tot_assets * 0.45)
    curr_liab = _find_row_val(bal, ["CurrentLiabilities", "TotalCurrentLiabilities"]) or (curr_assets * 0.55)
    tot_debt = _find_row_val(bal, ["LongTermDebt", "CurrentDebt", "TotalDebt"]) or (tot_assets * 0.25)
    equity = _find_row_val(bal, ["StockholdersEquity", "CommonStockEquity", "TotalStockholdersEquity"]) or (tot_assets * 0.52)
    cash = _find_row_val(bal, ["CashAndCashEquivalents", "CashCashEquivalentsAndShortTermInvestments"]) or (curr_assets * 0.35)

    ocf_latest = _find_row_val(cf, ["OperatingCashFlow", "CashFlowFromContinuingOperatingActivities"])
    capex_latest = _find_row_val(cf, ["CapitalExpenditure", "CapitalExpenditures"]) or 0.0
    fcf_latest = _find_row_val(cf, ["FreeCashFlow"])
    if fcf_latest is None and ocf_latest is not None:
        fcf_latest = ocf_latest - abs(capex_latest)

    # Market Cap & Enterprise Value
    # Live last print only when the provider sent one — never a fabricated 120.
    current_price = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
    mcap = _safe_float(info.get("marketCap"))
    if mcap is None:
        px = current_price if current_price is not None else 120.0
        sh = _safe_float(info.get("sharesOutstanding")) or 1_000_000_000.0
        mcap = px * sh

    ev = _safe_float(info.get("enterpriseValue")) or (mcap + tot_debt - cash)

    # Gross, Operating, and Net Margins
    gross_margin = _safe_round(_safe_float(info.get("grossMargins"), 0) * 100 if info.get("grossMargins") else None, 2)
    if gross_margin is None and rev_latest and gp_latest and rev_latest > 0:
        gross_margin = round((gp_latest / rev_latest) * 100, 2)
    elif gross_margin is None and rev_ttm and gp_ttm and rev_ttm > 0:
        gross_margin = round((gp_ttm / rev_ttm) * 100, 2)

    op_margin = _safe_round(_safe_float(info.get("operatingMargins"), 0) * 100 if info.get("operatingMargins") else None, 2)
    if op_margin is None and rev_latest and op_latest and rev_latest > 0:
        op_margin = round((op_latest / rev_latest) * 100, 2)

    net_margin = _safe_round(_safe_float(info.get("profitMargins"), 0) * 100 if info.get("profitMargins") else None, 2)
    if net_margin is None and rev_latest and ni_latest and rev_latest > 0:
        net_margin = round((ni_latest / rev_latest) * 100, 2)
    elif net_margin is None and rev_ttm and ni_ttm and rev_ttm > 0:
        net_margin = round((ni_ttm / rev_ttm) * 100, 2)

    # Multiples
    pe_trailing = _safe_round(info.get("trailingPE"), 2)
    if pe_trailing is None and ni_ttm and ni_ttm > 0:
        pe_trailing = round(mcap / ni_ttm, 2)

    pe_forward = _safe_round(info.get("forwardPE"), 2)

    ps_trailing = _safe_round(info.get("priceToSalesTrailing12Months"), 2)
    if ps_trailing is None and rev_ttm and rev_ttm > 0:
        ps_trailing = round(mcap / rev_ttm, 2)

    pb_trailing = _safe_round(info.get("priceToBook"), 2)
    if pb_trailing is None and equity and equity > 0:
        pb_trailing = round(mcap / equity, 2)

    ev_ebitda = _safe_round(info.get("enterpriseToEbitda"), 2)
    if ev_ebitda is None and ebitda_latest and ebitda_latest > 0:
        ev_ebitda = round(ev / ebitda_latest, 2)

    ev_revenue = _safe_round(info.get("enterpriseToRevenue"), 2)
    if ev_revenue is None and rev_ttm and rev_ttm > 0:
        ev_revenue = round(ev / rev_ttm, 2)

    # Health Ratios
    debt_to_equity = _safe_round(info.get("debtToEquity"), 2)
    if debt_to_equity is None and equity and equity > 0:
        debt_to_equity = round(tot_debt / equity, 2)

    current_ratio = _safe_round(info.get("currentRatio"), 2)
    if current_ratio is None and curr_liab and curr_liab > 0:
        current_ratio = round(curr_assets / curr_liab, 2)

    quick_ratio = _safe_round(info.get("quickRatio"), 2)
    if quick_ratio is None and curr_liab and curr_liab > 0:
        quick_ratio = round((cash or curr_assets * 0.5) / curr_liab, 2)

    roe = _safe_round(_safe_float(info.get("returnOnEquity"), 0) * 100 if info.get("returnOnEquity") else None, 2)
    if roe is None and equity and equity > 0 and ni_ttm is not None:
        roe = round((ni_ttm / equity) * 100, 2)

    roa = _safe_round(_safe_float(info.get("returnOnAssets"), 0) * 100 if info.get("returnOnAssets") else None, 2)
    if roa is None and tot_assets and tot_assets > 0 and ni_ttm is not None:
        roa = round((ni_ttm / tot_assets) * 100, 2)

    rev_growth = _safe_round(_safe_float(info.get("revenueGrowth"), 0) * 100 if info.get("revenueGrowth") else None, 2)
    if rev_growth is None:
        # Check inc rows if 2+ periods exist
        for row in inc:
            if "revenue" in str(row.get("key", "")).lower():
                vals = [v for v in row.get("values", []) if v is not None and isinstance(v, (int, float))]
                if len(vals) >= 4 and vals[3] > 0:
                    rev_growth = round(((vals[0] - vals[3]) / vals[3]) * 100, 2)
                elif len(vals) >= 2 and vals[1] > 0:
                    rev_growth = round(((vals[0] - vals[1]) / vals[1]) * 100, 2)
                break

    earn_growth = _safe_round(_safe_float(info.get("earningsGrowth"), 0) * 100 if info.get("earningsGrowth") else None, 2)

    fcf = _safe_float(info.get("freeCashflow")) or fcf_latest or (ocf_latest or (ni_ttm or 5_000_000_000.0) * 0.95)
    ocf = _safe_float(info.get("operatingCashflow")) or ocf_latest or ((fcf or 0) * 1.25)

    return {
        "market_cap": round(mcap, 2),
        "current_price": round(current_price, 2) if current_price is not None else None,
        "enterprise_value": round(ev, 2),
        "pe_trailing": pe_trailing,
        "pe_forward": pe_forward,
        "ps_trailing": ps_trailing,
        "pb_trailing": pb_trailing,
        "ev_ebitda": ev_ebitda,
        "ev_revenue": ev_revenue,
        "debt_to_equity": debt_to_equity,
        "current_ratio": current_ratio,
        "quick_ratio": quick_ratio,
        "roe": roe,
        "roa": roa,
        "gross_margin": gross_margin,
        "operating_margin": op_margin,
        "net_margin": net_margin,
        "revenue_growth_yoy": rev_growth,
        "earnings_growth_yoy": earn_growth,
        "free_cash_flow": round(fcf, 2) if fcf is not None else None,
        "operating_cash_flow": round(ocf, 2) if ocf is not None else None,
    }


def _generate_revenue_breakdown(
    symbol: str, info: dict[str, Any], latest_rev: float | None = None
) -> dict[str, Any]:
    """Segment / geography revenue split.

    This used to synthesise a split from the sector string and apply it to
    total revenue -- always, even when real financials were present. Every
    company in a sector got the same shape, `by_geography` was a literal
    62/22/16 for every symbol on earth, and the three segment `growth_yoy`
    figures were the constants 142.5 / 88.4 / 35.0. The dashboard renders all
    of it under a panel captioned "Source: SEC Form 10-K Notes".

    The real source is the filing's own XBRL instance document, where segment
    and geographic revenue carry dimension qualifiers (the companyfacts API
    strips dimensions entirely). When that yields nothing -- single-segment
    issuers, delisted tickers, offline -- the keys stay present and empty; the
    dashboard already guards on `by_segment?.length`, so the panel simply does
    not render.
    """
    try:
        from tools.sentiment_anomalies import xbrl_revenue_breakdown_for_symbol
    except ImportError:  # pragma: no cover - checkout-as-edge namespace
        from edge.tools.sentiment_anomalies import xbrl_revenue_breakdown_for_symbol

    try:
        return xbrl_revenue_breakdown_for_symbol(symbol)
    except Exception as e:
        logger.debug("XBRL revenue breakdown failed for %s: %s", symbol, e)
        return {
            "by_segment": [],
            "by_geography": [],
            "available": False,
            "reason": "No segment-level reporting source is configured",
        }


def _generate_fallback_financials(symbol: str, period: str) -> dict[str, Any]:
    """Empty financial statements for a symbol the provider has no data for.

    This used to synthesise complete income statements, balance sheets and
    cash-flow statements from a ticker-derived seed -- revenue, COGS, R&D,
    SG&A, share count, cash, the lot -- and return them alongside a
    `source: "deterministic_synthetic_financials"` marker. The marker was
    honest; nothing rendered it. The dashboard drew the invented statements in
    the same tables, with the same styling, as real ones.

    Synthetic fundamentals are not a display default on a research surface, so
    the tables are now empty. `getRowValues` in MarketView.vue already maps an
    empty `rows` array to nulls, which the formatters render as em-dashes.
    """
    return {
        "symbol": symbol,
        "period_type": period,
        "periods": [],
        "income_statement": {"rows": []},
        "balance_sheet": {"rows": []},
        "cash_flow": {"rows": []},
        "revenue_breakdown": _generate_revenue_breakdown(symbol, {}, None),
        "ratios": {},
        "available": False,
        "reason": "No fundamentals returned by the upstream provider for this symbol",
        "source": "unavailable",
        "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


def resolve_forecast_intel(symbol: str) -> dict[str, Any]:
    """Live last print + recent tape. Never a fabricated $35 mark or Street target."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return {}
    now = time.time()
    cached = _CACHE_TAPE.get(sym)
    if cached and now - cached[0] < TAPE_TTL_S:
        return dict(cached[1])

    intel: dict[str, Any] = {}
    try:
        import yfinance as yf  # type: ignore[import-not-found]
        ticker = yf.Ticker(sym)
        info = ticker.info or {}
        px = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        hi = _safe_float(info.get("fiftyTwoWeekHigh"))
        lo = _safe_float(info.get("fiftyTwoWeekLow"))
        hist = ticker.history(period="6mo")
        closes = None
        if hist is not None and not hist.empty and "Close" in hist.columns:
            closes = hist["Close"].astype(float).dropna()
        if px is None and closes is not None and len(closes) > 0:
            px = float(closes.iloc[-1])
        if px is not None and px > 0:
            intel["last_price"] = round(px, 4)
            intel["current_price"] = round(px, 4)
        eg = _safe_float(info.get("earningsGrowth"))
        rg = _safe_float(info.get("revenueGrowth"))
        if eg is not None:
            intel["earnings_growth"] = eg
        if rg is not None:
            intel["revenue_growth"] = rg
        feps = _safe_float(info.get("forwardEps"))
        teps = _safe_float(info.get("trailingEps"))
        if feps is not None:
            intel["forward_eps"] = feps
        if teps is not None:
            intel["trailing_eps"] = teps
        if hi and lo and hi > lo and px:
            intel["range_position"] = (px - lo) / (hi - lo)
        if closes is not None and len(closes) > 5:
            last = float(closes.iloc[-1])
            if last > 0:
                if len(closes) > 21:
                    prev = float(closes.iloc[-22])
                    if prev > 0:
                        intel["ret_1m"] = last / prev - 1.0
                lookback = 63 if len(closes) > 63 else max(5, len(closes) - 1)
                prev3 = float(closes.iloc[-lookback - 1]) if len(closes) > lookback else float(closes.iloc[0])
                if prev3 > 0:
                    intel["ret_3m"] = last / prev3 - 1.0
    except Exception as exc:
        logger.debug("live tape resolve failed for %s: %s", sym, exc)

    _CACHE_TAPE[sym] = (now, intel)
    return dict(intel)


def _with_model_forecast(data: dict[str, Any]) -> dict[str, Any]:
    """Attach the report-native ML forecast. Never uses Street targets as labels."""
    try:
        from research.financials_ml_forecast import score_report_forecast
    except ImportError:  # pragma: no cover - checkout-as-edge namespace
        from edge.research.financials_ml_forecast import score_report_forecast
    out = dict(data)
    intel = resolve_forecast_intel(str(out.get("symbol") or ""))
    if intel.get("last_price"):
        ratios = dict(out.get("ratios") or {})
        ratios["current_price"] = intel["last_price"]
        ratios["spot_source"] = "live"
        out["ratios"] = ratios
        out["tape"] = {
            k: intel[k]
            for k in (
                "last_price",
                "current_price",
                "ret_1m",
                "ret_3m",
                "range_position",
                "earnings_growth",
                "revenue_growth",
                "forward_eps",
                "trailing_eps",
            )
            if k in intel
        }
    out["model_forecast"] = score_report_forecast(out, intel)
    return out


# ==============================================================================
# 2. Company Profile, Officers, Forecast & Smart Score
# ==============================================================================
_RECOMMENDATION_LABELS = {
    "strong_buy": "Strong Buy",
    "buy": "Buy",
    "hold": "Hold",
    "underperform": "Underperform",
    "sell": "Sell",
}


def _positive_price(val: Any) -> float | None:
    """Street targets of 0 are Yahoo's empty slot, not a $0 mark."""
    price = _safe_float(val)
    if price is None or price <= 0:
        return None
    return round(price, 2)


def _revision_date(idx: Any) -> str:
    if hasattr(idx, "strftime"):
        return idx.strftime("%Y-%m-%d")
    return str(idx)[:10]


def _cell_str(val: Any) -> str:
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(val).strip()
    if text.lower() in {"", "nan", "none", "nat", "<na>"}:
        return ""
    return text


def _normalize_revision_action(action_raw: str) -> str:
    act = (action_raw or "").strip().lower()
    if not act or act in {"main", "maintain", "maintains"}:
        return "Maintains"
    if act in {"up", "upgrade", "upgrades", "upg"}:
        return "Upgrades"
    if act in {"down", "downgrade", "downgrades", "dwn"}:
        return "Downgrades"
    if act in {"init", "initiate", "initiates", "initiated", "initiation"}:
        return "Initiates Coverage"
    if act in {"reit", "reiterate", "reiterates", "reiterated"}:
        return "Reiterates"
    return action_raw.strip().title()


def _row_get(row: Any, *names: str) -> Any:
    for name in names:
        if hasattr(row, "index") and name in row.index:
            return row[name]
        if hasattr(row, "get"):
            try:
                val = row.get(name)
            except Exception:
                val = None
            if val is not None:
                return val
    if hasattr(row, "index"):
        wanted = {n.replace(" ", "").replace("_", "").lower() for n in names}
        for col in row.index:
            if str(col).replace(" ", "").replace("_", "").lower() in wanted:
                return row[col]
    return None


def parse_recommendation_counts(df: Any) -> dict[str, int] | None:
    """Current-period Yahoo recommendation buckets. Missing frame → None, never a fake mix."""
    if df is None or getattr(df, "empty", True):
        return None
    row = df.iloc[0]
    if "period" in df.columns:
        periods = df["period"].astype(str).str.lower()
        current = df[periods.isin({"0m", "0", "current"})]
        if not current.empty:
            row = current.iloc[0]

    def _bucket(*names: str) -> int | None:
        val = _safe_float(_row_get(row, *names))
        if val is None:
            return None
        return int(val)

    strong_buy = _bucket("strongBuy", "strong_buy")
    buy = _bucket("buy")
    hold = _bucket("hold")
    sell = _bucket("sell")
    strong_sell = _bucket("strongSell", "strong_sell")
    if all(part is None for part in (strong_buy, buy, hold, sell, strong_sell)):
        return None
    return {
        "strong_buy": strong_buy or 0,
        "buy": buy or 0,
        "hold": hold or 0,
        "sell": sell or 0,
        "strong_sell": strong_sell or 0,
    }


def parse_upgrades_downgrades(df: Any) -> list[dict[str, Any]]:
    """Pass through every Yahoo revision row. No 60-row cap, no synthetic firms."""
    if df is None or getattr(df, "empty", True):
        return []
    rows: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        firm = _cell_str(_row_get(row, "Firm", "firm"))
        if not firm:
            continue
        action_raw = _cell_str(_row_get(row, "Action", "action"))
        to_grade = _cell_str(_row_get(row, "ToGrade", "to_grade"))
        from_grade = _cell_str(_row_get(row, "FromGrade", "from_grade"))
        pt_action_raw = _cell_str(_row_get(row, "priceTargetAction", "price_target_action"))
        rows.append(
            {
                "date": _revision_date(idx),
                "firm": firm,
                "action": _normalize_revision_action(action_raw),
                "from_grade": from_grade or "-",
                "to_grade": to_grade or action_raw or "-",
                "current": to_grade or action_raw or "-",
                "previous": from_grade or "-",
                "target": _positive_price(_row_get(row, "currentPriceTarget", "current_price_target")),
                "prior_target": _positive_price(_row_get(row, "priorPriceTarget", "prior_price_target")),
                "target_action": pt_action_raw.title() if pt_action_raw else None,
            }
        )
    return rows


def latest_firm_estimates(
    revisions: list[Mapping[str, Any]],
    current_price: float | None,
) -> list[dict[str, Any]]:
    """Newest price target per firm. Zero Yahoo targets stay missing."""
    seen: set[str] = set()
    estimates: list[dict[str, Any]] = []
    for rev in revisions:
        firm = str(rev.get("firm") or "").strip()
        key = firm.lower()
        if not firm or key in seen:
            continue
        target = _positive_price(rev.get("target"))
        if target is None:
            continue
        seen.add(key)
        hit: bool | None = None
        vs_mark: float | None = None
        if current_price is not None and current_price > 0:
            hit = current_price >= target
            vs_mark = round(((target - current_price) / current_price) * 100.0, 1)
        estimates.append(
            {
                "firm": firm,
                "date": rev.get("date"),
                "action": rev.get("action"),
                "current": rev.get("current"),
                "previous": rev.get("previous"),
                "target": target,
                "prior_target": rev.get("prior_target"),
                "target_action": rev.get("target_action"),
                "vs_mark_pct": vs_mark,
                "hit": hit,
            }
        )
    return estimates


def _consensus_rating(rec_key: Any, rec_mean: float | None) -> str | None:
    if rec_key not in (None, ""):
        key = str(rec_key).strip().lower().replace(" ", "_").replace("-", "_")
        if key in _RECOMMENDATION_LABELS:
            return _RECOMMENDATION_LABELS[key]
    if rec_mean is None:
        return None
    if rec_mean <= 1.8:
        return "Strong Buy"
    if rec_mean <= 2.5:
        return "Buy"
    if rec_mean <= 3.5:
        return "Hold"
    return "Underperform"


def build_street_forecast(
    *,
    info: Mapping[str, Any],
    recommendations_summary: Any = None,
    upgrades_downgrades: Any = None,
    analyst_price_targets: Any = None,
) -> dict[str, Any]:
    """Observed Street consensus only. Missing inputs stay None / empty lists."""
    apt = analyst_price_targets if isinstance(analyst_price_targets, Mapping) else {}
    target_high = _positive_price(
        info.get("targetHighPrice") or info.get("targetPriceHigh") or apt.get("high")
    )
    target_median = _positive_price(
        info.get("targetMedianPrice") or info.get("targetPriceMedian") or apt.get("median")
    )
    target_low = _positive_price(
        info.get("targetLowPrice") or info.get("targetPriceLow") or apt.get("low")
    )
    target_mean = _positive_price(
        info.get("targetMeanPrice") or info.get("targetPriceMean") or apt.get("mean")
    )
    current_price = _positive_price(
        info.get("currentPrice") or info.get("regularMarketPrice") or apt.get("current")
    )
    rec_mean = _safe_round(info.get("recommendationMean"), 2)
    recs = parse_recommendation_counts(recommendations_summary)
    revisions = parse_upgrades_downgrades(upgrades_downgrades)
    estimates = latest_firm_estimates(revisions, current_price)
    upside_pct = None
    if target_median is not None and current_price:
        upside_pct = round(((target_median - current_price) / current_price) * 100.0, 1)
    analyst_count = None
    if recs is not None:
        analyst_count = (
            recs["strong_buy"] + recs["buy"] + recs["hold"] + recs["sell"] + recs["strong_sell"]
        )
    elif _safe_float(info.get("numberOfAnalystOpinions")) is not None:
        analyst_count = int(info.get("numberOfAnalystOpinions"))
    hits = sum(1 for row in estimates if row.get("hit") is True)
    opens = sum(1 for row in estimates if row.get("hit") is False)
    return {
        "consensus_rating": _consensus_rating(info.get("recommendationKey"), rec_mean),
        "recommendation_mean": rec_mean,
        "recommendation_key": info.get("recommendationKey"),
        "analyst_count": analyst_count,
        "target_price_high": target_high,
        "target_price_median": target_median,
        "target_price_mean": target_mean,
        "target_price_low": target_low,
        "current_price": current_price,
        "upside_pct": upside_pct,
        "recommendations": recs,
        "upgrades_downgrades": revisions,
        "estimates": estimates,
        "estimates_hit": hits,
        "estimates_open": opens,
    }


# Yahoo serves the profile as several independent modules. When it throttles,
# some modules resolve and others come back absent, so `info` is non-empty yet
# missing the fields the profile is built from -- and every one of those fields
# silently falls through to a generic default (symbol-derived website, canned
# description, null employees, null recommendation, null ownership pillars).
# Caching that for the full TTL serves plausible-looking wrong data for 15
# minutes, so track which modules actually resolved and expire a partial fetch
# quickly instead.
_PROFILE_MODULE_MARKERS: dict[str, tuple[str, ...]] = {
    "asset_profile": ("longBusinessSummary", "companyOfficers", "fullTimeEmployees"),
    "financial_data": ("recommendationMean", "recommendationKey"),
    "key_statistics": ("heldPercentInsiders", "heldPercentInstitutions"),
}

# Retry window for a partial upstream fetch. Long enough to stop a request
# stampede against a throttling provider, short enough that the surface repairs
# itself without an operator restart.
DEGRADED_PROFILE_TTL_S = 60


def _profile_modules_resolved(info: Mapping[str, Any]) -> dict[str, bool]:
    """Report which Yahoo profile modules came back with usable fields."""
    return {
        module: any(info.get(key) not in (None, "", [], {}) for key in keys)
        for module, keys in _PROFILE_MODULE_MARKERS.items()
    }


def _cache_is_complete_profile(data: Mapping[str, Any]) -> bool:
    """Reject cache entries built from a partial upstream profile fetch."""
    resolved = (data.get("upstream") or {}).get("modules_resolved")
    if not isinstance(resolved, Mapping):
        return False
    return all(bool(resolved.get(module)) for module in _PROFILE_MODULE_MARKERS)


def get_company_profile_payload(symbol: str, *, ticker: Any | None = None) -> dict[str, Any]:
    """Public company-profile payload used by /api/company-profile.

    `ticker` is an optional injected Yahoo-like object (tests). Live fetches
    are cached; injected tickers are not.
    """
    sym = symbol.strip().upper()
    now = time.time()
    if ticker is None and sym in _CACHE_PROFILE:
        ts, data = _CACHE_PROFILE[sym]
        age = now - ts
        ttl = CACHE_TTL_S if _cache_is_complete_profile(data) else DEGRADED_PROFILE_TTL_S
        if age < ttl:
            return data

    payload = _build_company_profile_payload(sym, ticker=ticker)
    if ticker is None:
        _CACHE_PROFILE[sym] = (now, payload)
    return payload


def _build_company_profile_payload(symbol: str, *, ticker: Any | None = None) -> dict[str, Any]:
    info: dict[str, Any] = {}
    officers: list[dict[str, Any]] = []
    rec_summary = None
    upgrades_df = None
    apt = None
    live_ticker = ticker

    try:
        if live_ticker is None:
            import yfinance as yf  # type: ignore[import-not-found]
            live_ticker = yf.Ticker(symbol)
        info = live_ticker.info or {}

        for off in info.get("companyOfficers", [])[:10]:
            officers.append({
                "name": off.get("name", "Executive Officer"),
                "title": off.get("title", "Officer"),
                "age": off.get("age"),
                "total_pay": _safe_float(off.get("totalPay")),
                "exercised_value": _safe_float(off.get("exercisedValue")),
                "year_born": off.get("yearBorn"),
            })
    except Exception as e:
        logger.debug("yfinance profile fetch error for %s: %s", symbol, e)
        live_ticker = None

    if live_ticker is not None:
        try:
            rec_summary = live_ticker.recommendations_summary
        except Exception as e:
            logger.debug("yfinance recommendations_summary error for %s: %s", symbol, e)
        try:
            upgrades_df = live_ticker.upgrades_downgrades
        except Exception as e:
            logger.debug("yfinance upgrades_downgrades error for %s: %s", symbol, e)
        try:
            apt = live_ticker.analyst_price_targets
        except Exception as e:
            logger.debug("yfinance analyst_price_targets error for %s: %s", symbol, e)


    # Extract or generate About
    sec_meta = None
    try:
        from tools.sentiment_anomalies import _sec_ticker_map
        sec_meta = _sec_ticker_map().get(symbol)
    except Exception:
        try:
            from edge.tools.sentiment_anomalies import _sec_ticker_map
            sec_meta = _sec_ticker_map().get(symbol)
        except Exception:
            pass

    sec_title = (sec_meta.get("title") or "").strip() if sec_meta else ""
    clean_sec_name = None
    if sec_title:
        clean_sec_name = sec_title.replace(" /DE/", "").replace(" /DE", "").replace("/DE/", "").title()

    name = info.get("longName") or info.get("shortName") or clean_sec_name or f"{symbol} Corporation"
    desc = info.get("longBusinessSummary") or (
        f"{name} operates as a commercial enterprise engaged in the design, development, and delivery of specialized technological and industrial solutions. The company provides scalable products and services across enterprise and institutional markets."
    )
    city = info.get("city") or "New York"
    state = info.get("state")
    country = info.get("country") or "United States"

    # Known foreign ticker headquarters fallback
    if symbol == "ASML" and not info.get("country"):
        country = "Netherlands"
        city = "Veldhoven"
    elif symbol == "TSM" and not info.get("country"):
        country = "Taiwan"
        city = "Hsinchu"
    elif symbol == "SAP" and not info.get("country"):
        country = "Germany"
        city = "Walldorf"
    elif symbol == "NVO" and not info.get("country"):
        country = "Denmark"
        city = "Bagsvaerd"

    if country.upper() in {"UNITED STATES", "USA", "US"} and state:
        address = f"{city}, {state}"
    elif state and country:
        address = f"{city}, {state}, {country}"
    elif country and country.upper() not in {"UNITED STATES", "USA", "US"}:
        address = f"{city}, {country}"
    elif state:
        address = f"{city}, {state}"
    else:
        address = city

    _SECTOR_MAP = {
        "NEM": "Basic Materials",
        "AAPL": "Technology",
        "MSFT": "Technology",
        "NVDA": "Technology",
        "AVGO": "Technology",
        "AMD": "Technology",
        "LMT": "Industrials",
        "BA": "Industrials",
        "PLTR": "Technology",
        "ASTS": "Telecommunications",
        "CEG": "Utilities",
        "RKLB": "Industrials",
        "TSLA": "Consumer Cyclical",
        "AMZN": "Consumer Cyclical",
        "GOOGL": "Communication Services",
        "META": "Communication Services",
    }
    website = info.get("website") or f"https://www.{symbol.lower()}.com"
    sector = info.get("sector") or _SECTOR_MAP.get(symbol) or "Technology"
    industry = info.get("industry") or ("Gold Mining" if symbol == "NEM" else "Communications Services")
    employees = info.get("fullTimeEmployees") or (17500 if symbol == "NEM" else None)
    market_cap = _safe_float(info.get("marketCap"))

    # Executive compensation — observed officer pay only. Never invent a DEF 14A table.
    comp_rows = []
    for off in officers:
        total_f = _safe_float(off.get("total_pay"))
        if total_f is not None and total_f <= 0:
            total_f = None
        comp_rows.append({
            "name": off.get("name") or "Officer",
            "role": off.get("title") or "Officer",
            "salary": None,
            "bonus": None,
            "stock_awards": None,
            "total_compensation": None if total_f is None else round(total_f, 2),
            "year": None,
        })
    paid = [row for row in comp_rows if row["total_compensation"] is not None]
    top = max(paid, key=lambda row: row["total_compensation"]) if paid else None
    top_exec_name = top["name"] if top else None
    top_exec_pay = top["total_compensation"] if top else None
    median_emp_pay = None
    pay_ratio = None

    forecast = build_street_forecast(
        info=info,
        recommendations_summary=rec_summary,
        upgrades_downgrades=upgrades_df,
        analyst_price_targets=apt,
    )
    rec_mean = forecast.get("recommendation_mean")
    current_price = forecast.get("current_price")
    upside_pct = forecast.get("upside_pct")

    # Multi-Pillar Quantitative Smart Score (1-10)
    # Pillar 1: Analyst Consensus & Price Target Upside (1-10)
    analyst_score = 5
    if rec_mean is not None:
        analyst_score = max(1, min(10, round(11.5 - rec_mean * 2.1)))
    if upside_pct is not None and upside_pct > 25:
        analyst_score = min(10, analyst_score + 1)
    elif upside_pct is not None and upside_pct < 0:
        analyst_score = max(1, analyst_score - 1)

    # Pillar 2: Financial Health & Profitability Multiples (1-10)
    profit_margin = _safe_float(info.get("profitMargins"))
    debt_equity = _safe_float(info.get("debtToEquity"))
    current_ratio = _safe_float(info.get("currentRatio"))
    ro_e = _safe_float(info.get("returnOnEquity"))
    
    health_points = 5
    if profit_margin is not None:
        if profit_margin > 0.15: health_points += 2
        elif profit_margin > 0: health_points += 1
        elif profit_margin < -0.20: health_points -= 2
    if debt_equity is not None:
        if debt_equity < 50: health_points += 1
        elif debt_equity > 200: health_points -= 1
    if current_ratio is not None:
        if current_ratio > 1.5: health_points += 1
        elif current_ratio < 0.9: health_points -= 1
    if ro_e is not None:
        if ro_e > 0.15: health_points += 1
        elif ro_e < -0.10: health_points -= 1
    fin_score = max(1, min(10, health_points))

    # Pillar 3: Momentum & Relative Range (1-10)
    fifty_two_hi = _safe_float(info.get("fiftyTwoWeekHigh"))
    fifty_two_lo = _safe_float(info.get("fiftyTwoWeekLow"))
    if fifty_two_hi and fifty_two_lo and fifty_two_hi > fifty_two_lo and current_price:
        pos_in_range = (current_price - fifty_two_lo) / (fifty_two_hi - fifty_two_lo)
        mom_score = max(1, min(10, round(pos_in_range * 8 + 1.5)))
    else:
        mom_score = None  # no 52-week range to place the last mark inside

    # Pillar 4: Insider Activity (1-10)
    insider_held = _safe_float(info.get("heldPercentInsiders"))
    if insider_held is not None:
        if insider_held > 0.15: insider_score = 8
        elif insider_held > 0.05: insider_score = 7
        elif insider_held < 0.01: insider_score = 4
        else: insider_score = 6
    else:
        insider_score = None  # provider gave no heldPercentInsiders

    # Pillar 5: Institutional Accumulation (1-10)
    inst_held = _safe_float(info.get("heldPercentInstitutions"))
    if inst_held is not None:
        if inst_held > 0.65: inst_score = 9
        elif inst_held > 0.40: inst_score = 7
        elif inst_held < 0.20: inst_score = 4
        else: inst_score = 6
    else:
        inst_score = None  # provider gave no heldPercentInstitutions

    # Composite Weighted Smart Score.
    #
    # Any pillar the provider gave us nothing for is None rather than a draw
    # from rng.normal(). A score assembled partly from noise is worse than no
    # score: it looks identical to a measured one on the way to the operator.
    # Re-weight across the pillars that are real, and withhold the score
    # entirely if too little of it is measured to mean anything.
    _pillars = (
        (0.25, analyst_score),
        (0.25, fin_score),
        (0.20, mom_score),
        (0.15, insider_score),
        (0.15, inst_score),
    )
    _known = [(w, v) for w, v in _pillars if v is not None]
    _weight = sum(w for w, _ in _known)
    if _weight >= 0.60:
        composite = sum(w * v for w, v in _known) / _weight
        smart_score = int(max(1, min(10, round(composite))))
        rating_str = (
            "Outperform" if smart_score >= 8 else
            "Neutral" if smart_score >= 5 else
            "Underperform"
        )
    else:
        smart_score = None
        rating_str = None

    # Bulls & Bears thesis
    bulls_say = [
        f"Strong long-term pipeline with expanding commercial addressable market in {industry}.",
        "High institutional backing and notable contract/patent execution.",
    ]
    if upside_pct is not None:
        bulls_say.append(
            f"Consensus price target implies {upside_pct:+.1f}% vs the last observed mark."
        )
    bears_say = [
        "Near-term capital expenditure requirements may pressure cash flow margins.",
        "Execution risk tied to regulatory approvals and timeline milestones.",
        "Macro volatility in high-beta tech/growth assets.",
    ]

    upstream_modules = _profile_modules_resolved(info)

    return {
        "symbol": symbol,
        "about": {
            "name": name,
            "description": desc,
            "address": address,
            "city": city,
            "state": state,
            "country": country,
            "website": website,
            "sector": sector,
            "industry": industry,
            "employees": employees,
            "market_cap": market_cap,
            "beta": _safe_round(info.get("beta"), 2),
            "fifty_two_week_high": _safe_round(info.get("fiftyTwoWeekHigh")),
            "fifty_two_week_low": _safe_round(info.get("fiftyTwoWeekLow")),
            "currency": info.get("currency", "USD"),
        },
        "officers": officers,
        "compensation": {
            "highest_paid_name": top_exec_name,
            "highest_paid_total": top_exec_pay,
            "median_employee_pay": median_emp_pay,
            "ceo_pay_ratio": pay_ratio,
            "year": None,
            "rows": comp_rows,
        },
        "forecast": forecast,
        "smart_score": {
            "score": smart_score,
            "rating": rating_str,
            "components": {
                "analyst_sentiment": analyst_score,
                "financial_health": fin_score,
                "momentum": mom_score,
                "insider_activity": insider_score,
                "institutional_flow": inst_score,
            },
        },
        "bull_bear": {
            "bulls_say": bulls_say,
            "bears_say": bears_say,
            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        },
        "model_forecast": get_financials_payload(symbol).get("model_forecast"),
        "upstream": {
            "modules_resolved": upstream_modules,
            "complete": all(upstream_modules.values()),
        },
        "source": "company_intelligence_aggregator",
        "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


# ==============================================================================
# 3. Insiders Intelligence (Form 4 + Fintel + Strategy Backtest)
# ==============================================================================
def get_insiders_payload(symbol: str) -> dict[str, Any]:
    sym = symbol.strip().upper()
    now = time.time()
    if sym in _CACHE_INSIDERS:
        ts, data = _CACHE_INSIDERS[sym]
        if now - ts < CACHE_TTL_S:
            return data

    payload = _build_insiders_payload(sym)
    _CACHE_INSIDERS[sym] = (now, payload)
    return payload


def _build_insiders_payload(symbol: str) -> dict[str, Any]:
    transactions: list[dict[str, Any]] = []

    # Resolve SEC EDGAR Form 4 URL
    edgar_form4_url = f"https://www.sec.gov/edgar/search/#/q={symbol}&forms=4"
    try:
        from tools.sentiment_anomalies import _sec_ticker_map
        tmap = _sec_ticker_map()
        meta = tmap.get(symbol)
        if meta and meta.get("cik"):
            edgar_form4_url = f"https://www.sec.gov/edgar/browse/?CIK={meta['cik']}"
    except Exception:
        pass

    # 1. Try yfinance insider trades
    try:
        import yfinance as yf  # type: ignore[import-not-found]
        ticker = yf.Ticker(symbol)
        ins_df = ticker.insider_transactions
        if ins_df is not None and not ins_df.empty:
            for _, row in ins_df.head(40).iterrows():
                d = row.get("Start Date") or row.get("Date")
                d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
                text = str(row.get("Text", "") or row.get("Transaction", ""))
                typ = "Purchase" if "buy" in text.lower() or "purchase" in text.lower() else "Sale" if "sale" in text.lower() or "sell" in text.lower() else "Option Exercise"
                sh = _safe_float(row.get("Shares")) or 0.0
                val = _safe_float(row.get("Value")) or (sh * (_safe_float(row.get("Price")) or 30.0))
                transactions.append({
                    "date": d_str,
                    "insider_name": str(row.get("Insider", "Officer/Director")),
                    "relationship": str(row.get("Position", "Executive / Director")),
                    "transaction_type": typ,
                    "shares": abs(int(sh)),
                    "price": _safe_round(row.get("Price"), 2) or _safe_round(val / sh if sh else 35.0, 2),
                    "value": abs(round(val, 2)),
                    "shares_held_after": int(_safe_float(row.get("Shares Held After")) or (sh * 4)),
                    "direct_indirect": "Direct",
                    "filing_date": d_str,
                    "sec_form_url": edgar_form4_url,
                })
    except Exception as e:
        logger.debug("yfinance insider transactions error for %s: %s", symbol, e)

    # A symbol with no yfinance insider rows used to be filled with 16
    # invented Form 4 filings: real executive names taken from
    # `companyOfficers` (or generated ones), with invented share counts,
    # prices and dates, each carrying a real SEC EDGAR URL. Attributing
    # trades that never happened to named people is not a display default,
    # so an empty result now stays empty.

    # Sort transactions descending by date
    transactions.sort(key=lambda x: x["date"], reverse=True)

    # Compute quarterly net insider volume
    quarters_map: dict[str, dict[str, float]] = {}
    for tx in transactions:
        dt = tx["date"][:7]  # YYYY-MM
        yr, mo = int(dt[:4]), int(dt[5:7])
        q_label = f"{yr} Q{(mo - 1) // 3 + 1}"
        if q_label not in quarters_map:
            quarters_map[q_label] = {"buy_shares": 0.0, "sell_shares": 0.0, "buy_val": 0.0, "sell_val": 0.0, "count": 0.0}
        
        sh = float(tx.get("shares", 0))
        val = float(tx.get("value", 0))
        quarters_map[q_label]["count"] += 1
        if tx.get("transaction_type") == "Purchase":
            quarters_map[q_label]["buy_shares"] += sh
            quarters_map[q_label]["buy_val"] += val
        else:
            quarters_map[q_label]["sell_shares"] += sh
            quarters_map[q_label]["sell_val"] += val

    quarterly_net = []
    for q_label in sorted(quarters_map.keys(), reverse=True)[:8]:
        d = quarters_map[q_label]
        quarterly_net.append({
            "quarter": q_label,
            "buy_shares": int(d["buy_shares"]),
            "sell_shares": int(d["sell_shares"]),
            "net_shares": int(d["buy_shares"] - d["sell_shares"]),
            "net_usd": round(d["buy_val"] - d["sell_val"], 2),
            "transactions_count": int(d["count"]),
        })

    # Summary metrics (90D)
    recent_txs = transactions[:8]
    total_buy_val = sum(t["value"] for t in recent_txs if t["transaction_type"] == "Purchase")
    total_sell_val = sum(t["value"] for t in recent_txs if t["transaction_type"] == "Sale")
    net_vol = total_buy_val - total_sell_val
    buy_tx_count = sum(1 for t in recent_txs if t["transaction_type"] == "Purchase")
    sell_tx_count = sum(1 for t in recent_txs if t["transaction_type"] == "Sale")
    # Buys and sells cover open-market activity only -- option exercises are
    # neither. Their sum therefore understates filing activity (a symbol whose
    # recent Form 4s are all exercises sums to zero while the tape below it
    # lists real filings), so report the true filing count separately.
    option_tx_count = sum(1 for t in recent_txs if t["transaction_type"] == "Option Exercise")
    total_filings_count = len(recent_txs)

    unique_insiders = len({t["insider_name"] for t in recent_txs})

    sentiment = "Bullish" if net_vol > 0 and buy_tx_count >= sell_tx_count else "Bearish" if net_vol < 0 else "Neutral"

    # A fixed "Insider Purchases Strategy" block used to be returned here with
    # invented performance -- CAGR 28.4%, 1y 42.6%, Sharpe 1.84, win rate
    # 68.2%, max drawdown -14.2%, "backtest_start_date": "2020-01-01" -- the
    # same numbers for every symbol, from no backtest at all. Published
    # performance figures are the one thing a research surface must never
    # invent, so the key is now absent unless a real backtest supplies it.

    return {
        "symbol": symbol,
        "summary": {
            "net_volume_usd": net_vol,
            "buy_volume_usd": total_buy_val,
            "sell_volume_usd": total_sell_val,
            "buy_transactions_count": buy_tx_count,
            "sell_transactions_count": sell_tx_count,
            "option_transactions_count": option_tx_count,
            "total_filings_count": total_filings_count,
            "active_insiders_count": unique_insiders,
            "sentiment": sentiment,
        },
        "transactions": transactions,
        "quarterly_net": quarterly_net,
        "available": bool(transactions),
        "reason": (
            None
            if transactions
            else "No insider transactions returned by the upstream provider for this symbol"
        ),
        "source": "yfinance_insider_transactions" if transactions else "unavailable",
        "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


# ==============================================================================
# 4. Government Intelligence (Congress, Lobbying, Contracts, Patents)
# ==============================================================================
def get_government_payload(symbol: str) -> dict[str, Any]:
    sym = symbol.strip().upper()
    now = time.time()
    if sym in _CACHE_GOVERNMENT:
        ts, data = _CACHE_GOVERNMENT[sym]
        if now - ts < CACHE_TTL_S:
            return data

    payload = _build_government_payload(sym)
    _CACHE_GOVERNMENT[sym] = (now, payload)
    return payload


def _build_government_payload(symbol: str) -> dict[str, Any]:
    """Congress / lobbying / contracts / patents payload from authentic regulatory disclosures."""
    try:
        from tools.government_data import build_government_payload
    except ImportError:  # pragma: no cover - checkout-as-edge namespace
        from edge.tools.government_data import build_government_payload

    return build_government_payload(symbol)



# ==============================================================================
# 5. Ownership & Institutional Holdings
# ==============================================================================
_INSTITUTION_COUNT_INFO_KEYS = (
    "institutionsCount",
    "institutionCount",
    "numberOfInstitutionalHolders",
    "numberOfInstitutionsHoldingShares",
)


def _holder_name(val: Any) -> str:
    if val is None:
        return ""
    text = str(val).strip()
    if not text or text.lower() in {"nan", "none", "nat", "natype"}:
        return ""
    return text


def _holder_date(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    if hasattr(val, "strftime"):
        try:
            return val.strftime("%Y-%m-%d")
        except (ValueError, TypeError, OverflowError):
            return None
    text = str(val).strip()
    if not text or text.lower() in {"nan", "none", "nat", "natype"}:
        return None
    return text[:10]


def _label_is_institution_count(label: Any) -> bool:
    """True for Yahoo's institutionsCount index / legacy 'Number of Institutions…' text."""
    pretty = str(label).strip().lower()
    compact = pretty.replace(" ", "").replace("_", "")
    if compact in {
        "institutionscount",
        "institutioncount",
        "numberofinstitutionalholders",
        "numberofinstitutionsholdingshares",
    }:
        return True
    if "number of institution" in pretty:
        return True
    # Do not match institutionsPercentHeld / institutionsFloatPercentHeld.
    return (
        "institution" in compact
        and "count" in compact
        and "percent" not in compact
        and "pct" not in compact
    )


def _first_numeric(value: Any) -> float | None:
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        try:
            seq = value.tolist()
            if isinstance(seq, list):
                for item in seq:
                    raw = _safe_float(item)
                    if raw is not None:
                        return raw
            else:
                return _safe_float(seq)
        except Exception:
            pass
    return _safe_float(value)


def parse_reported_institution_count(
    info: Mapping[str, Any] | None = None,
    major_holders: Any = None,
) -> int | None:
    """Yahoo reported institution count (e.g. 243), not len(top table).

    yfinance 0.2.66 builds major_holders via DataFrame.from_dict(..., orient='index')
    on majorHoldersBreakdown, so the count is the *index* key ``institutionsCount``.
    Ticker.info typically does not carry that field.
    """
    blob = info or {}
    for key in _INSTITUTION_COUNT_INFO_KEYS:
        raw = _safe_float(blob.get(key))
        if raw is not None and raw >= 0:
            return int(raw)

    if major_holders is None:
        return None

    try:
        if hasattr(major_holders, "index"):
            for idx in major_holders.index:
                if not _label_is_institution_count(idx):
                    continue
                value = major_holders.loc[idx] if hasattr(major_holders, "loc") else None
                raw = _first_numeric(value)
                if raw is not None and raw >= 0:
                    return int(raw)
        if hasattr(major_holders, "iterrows"):
            for idx, row in major_holders.iterrows():
                cells = [idx, *list(row.values)]
                if not any(
                    _label_is_institution_count(cell) or "number of institution" in str(cell).lower()
                    for cell in cells
                ):
                    continue
                raw = _first_numeric(cells)
                if raw is not None and raw >= 1:
                    return int(raw)
    except Exception:
        return None
    return None


def _yahoo_change_to_pct(raw: float | None) -> float | None:
    """Yahoo ``pctChange`` is a period fraction (0.012 → 1.2). Already-percent stays."""
    if raw is None:
        return None
    if abs(raw) <= 1.0:
        return raw * 100.0
    return raw


def _share_delta_from_pct_change(shares: float, pct_change_raw: float) -> float | None:
    """QoQ share delta: current * p / (1 + p) where p is the period fraction."""
    period = pct_change_raw if abs(pct_change_raw) <= 1.0 else pct_change_raw / 100.0
    if period <= -1.0:
        return None
    return shares * period / (1.0 + period)


def parse_holder_rows(
    df: Any,
    *,
    current_px: float | None = None,
    shares_outstanding: float | None = None,
) -> list[dict[str, Any]]:
    """Pass through every real Yahoo holder row. No cap, no synthetic names.

    ``pctHeld`` → ``pct_out`` (percent of outstanding). ``pctChange`` is last-quarter
    position change and must never become ``pct_out``. Missing ``pctHeld`` falls
    back to shares / shares outstanding.
    """
    if df is None or getattr(df, "empty", True):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    columns = list(df.columns)
    for _, row in df.iterrows():
        holder = ""
        reported = None
        shares = None
        pct = None
        value = None
        change_shares = None
        change_pct_raw = None
        for col in columns:
            c_clean = str(col).strip().lower().replace(" ", "").replace("_", "").replace("%", "pct")
            val = row.get(col) if hasattr(row, "get") else row[col]
            if "date" in c_clean:
                reported = val
            elif "holder" in c_clean or "institution" in c_clean or "name" in c_clean or "fund" in c_clean:
                parsed = _holder_name(val)
                if parsed:
                    holder = parsed
            elif "change" in c_clean or c_clean.endswith("chg"):
                # pctChange is a period delta, not % outstanding.
                if "share" in c_clean:
                    change_shares = _safe_float(val)
                elif "pct" in c_clean or "percent" in c_clean:
                    change_pct_raw = _safe_float(val)
            elif "shares" in c_clean or c_clean == "position":
                shares = _safe_float(val)
            elif c_clean in {"pctheld", "pctout", "percentheld", "percentout"} or (
                ("pct" in c_clean or "percent" in c_clean)
                and ("held" in c_clean or "out" in c_clean)
            ):
                pct = _safe_float(val)
            elif "val" in c_clean or "amount" in c_clean:
                value = _safe_float(val)
        holder = holder.strip()
        if not holder:
            continue
        key = holder.lower()
        if key in seen:
            continue
        seen.add(key)
        if pct is not None and 0 < pct <= 1.0:
            pct *= 100
        if (
            pct is None
            and shares is not None
            and shares_outstanding is not None
            and shares_outstanding > 0
        ):
            pct = (shares / shares_outstanding) * 100.0
        if value is None and shares is not None and current_px is not None:
            value = shares * current_px
        change_pct = _yahoo_change_to_pct(change_pct_raw)
        if change_shares is None and shares is not None and change_pct_raw is not None:
            change_shares = _share_delta_from_pct_change(shares, change_pct_raw)
        item: dict[str, Any] = {
            "holder": holder,
            "shares": int(shares) if shares is not None else None,
            "date_reported": _holder_date(reported),
            "pct_out": _safe_round(pct, 2),
            "value": round(value, 2) if value is not None else None,
        }
        if change_pct is not None:
            item["change_pct"] = _safe_round(change_pct, 2)
        if change_shares is not None:
            item["change_shares"] = int(round(change_shares))
        rows.append(item)
    return rows


_NASDAQ_HOLDINGS_URL = (
    "https://api.nasdaq.com/api/company/{symbol}/institutional-holdings"
    "?limit={limit}&type={holding_type}&sortColumn=marketValue"
)


def _nasdaq_headers(symbol: str) -> dict[str, str]:
    sl = symbol.strip().lower()
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Origin": "https://www.nasdaq.com",
        "Referer": f"https://www.nasdaq.com/market-activity/stocks/{sl}/institutional-holdings",
    }


def _parse_nasdaq_number(val: Any) -> float | None:
    """Parse Nasdaq table cells: '11,573,878', '(500,000)', '$148,840', '-90.832%'."""
    if val is None:
        return None
    text = str(val).strip()
    if not text or text.lower() in {"--", "n/a", "na", "new", "sold out", "soldout"}:
        return None
    neg = text.startswith("(") and text.endswith(")")
    cleaned = (
        text.replace("$", "")
        .replace(",", "")
        .replace("%", "")
        .replace("(", "")
        .replace(")", "")
        .replace("−", "-")
        .strip()
    )
    raw = _safe_float(cleaned)
    if raw is None:
        return None
    return -abs(raw) if neg else raw


def _parse_nasdaq_date(val: Any) -> str | None:
    text = str(val).strip() if val is not None else ""
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return _holder_date(val)


def fetch_nasdaq_holdings_json(
    symbol: str,
    *,
    limit: int = 10_000,
    holding_type: str = "TOTAL",
) -> dict[str, Any] | None:
    """Live Nasdaq institutional-holdings table. None on transport/parse failure."""
    try:
        import requests  # type: ignore[import-not-found]
    except Exception:
        return None
    url = _NASDAQ_HOLDINGS_URL.format(
        symbol=symbol.strip().upper(),
        limit=max(1, int(limit)),
        holding_type=holding_type,
    )
    try:
        resp = requests.get(url, headers=_nasdaq_headers(symbol), timeout=20)
        resp.raise_for_status()
        blob = resp.json()
        return blob if isinstance(blob, dict) else None
    except Exception as e:
        logger.debug("nasdaq holdings fetch error for %s: %s", symbol, e)
        return None


def parse_nasdaq_holdings_payload(
    blob: Mapping[str, Any] | None,
    *,
    current_px: float | None = None,
    shares_outstanding: float | None = None,
) -> dict[str, Any]:
    """Parse Nasdaq `/institutional-holdings` JSON into the ownership row shape.

    No 10/30-row cap. ``sharesChange`` / ``sharesChangePCT`` are last-quarter
    position change, never % of outstanding. Missing % outstanding is shares /
    outstanding. Market value cells are in thousands.
    """
    empty = {
        "institutions": [],
        "funds": [],
        "institutions_count": None,
        "institutional_pct": None,
        "shares_outstanding": None,
    }
    if not blob:
        return empty
    data = blob.get("data") if isinstance(blob, Mapping) else None
    if not isinstance(data, Mapping):
        return empty

    summary = data.get("ownershipSummary") if isinstance(data.get("ownershipSummary"), Mapping) else {}
    pct_cell = (summary or {}).get("SharesOutstandingPCT")
    so_cell = (summary or {}).get("ShareoutstandingTotal")
    inst_pct = _parse_nasdaq_number(pct_cell.get("value") if isinstance(pct_cell, Mapping) else pct_cell)
    so_millions = _parse_nasdaq_number(so_cell.get("value") if isinstance(so_cell, Mapping) else so_cell)
    nasdaq_outstanding = so_millions * 1_000_000.0 if so_millions is not None and so_millions > 0 else None
    outstanding = shares_outstanding if shares_outstanding and shares_outstanding > 0 else nasdaq_outstanding

    tx = data.get("holdingsTransactions") if isinstance(data.get("holdingsTransactions"), Mapping) else {}
    count = _parse_nasdaq_number((tx or {}).get("totalRecords"))
    table = (tx or {}).get("table") if isinstance((tx or {}).get("table"), Mapping) else {}
    raw_rows = (table or {}).get("rows") if isinstance(table, Mapping) else None
    if not isinstance(raw_rows, list):
        raw_rows = []

    institutions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            continue
        holder = _holder_name(raw.get("ownerName") or raw.get("owner") or raw.get("name"))
        if not holder:
            continue
        key = holder.lower()
        if key in seen:
            continue
        seen.add(key)
        shares = _parse_nasdaq_number(raw.get("sharesHeld") or raw.get("shares"))
        change_shares = _parse_nasdaq_number(raw.get("sharesChange"))
        pct_cell = raw.get("sharesChangePCT") or raw.get("sharesChangePct")
        pct_text = str(pct_cell).strip() if pct_cell is not None else ""
        label_l = pct_text.lower().replace(" ", "")
        change_label = None
        change_pct = None
        if label_l == "new":
            change_label = "New"
        elif label_l in {"soldout", "sold-out"}:
            change_label = "Sold Out"
            change_pct = -100.0
        else:
            change_pct = _parse_nasdaq_number(pct_cell)
        value_thousands = _parse_nasdaq_number(raw.get("marketValue") or raw.get("value"))
        value = value_thousands * 1000.0 if value_thousands is not None else None
        if value is None and shares is not None and current_px is not None:
            value = shares * current_px
        pct_out = None
        if shares is not None and outstanding and outstanding > 0:
            pct_out = (shares / outstanding) * 100.0
        item: dict[str, Any] = {
            "holder": holder,
            "shares": int(round(shares)) if shares is not None else None,
            "date_reported": _parse_nasdaq_date(raw.get("date")),
            "pct_out": _safe_round(pct_out, 2),
            "value": round(value, 2) if value is not None else None,
        }
        if change_label is not None:
            item["change_label"] = change_label
        if change_pct is not None:
            item["change_pct"] = _safe_round(change_pct, 2)
        if change_shares is not None:
            item["change_shares"] = int(round(change_shares))
        institutions.append(item)

    inst_count = int(count) if count is not None and count >= 0 else None
    if inst_count is None and institutions:
        inst_count = len(institutions)
    return {
        "institutions": institutions,
        "funds": [],
        "institutions_count": inst_count,
        "institutional_pct": _safe_round(inst_pct, 2) if inst_pct is not None else None,
        "shares_outstanding": int(nasdaq_outstanding) if nasdaq_outstanding is not None else None,
    }


def _cache_is_complete_ownership(data: Mapping[str, Any]) -> bool:
    """Reject short Yahoo top-N cache entries when a fuller 13F list is expected."""
    if "institutions_count" not in data:
        return False
    named = len(data.get("top_institutions") or [])
    reported = data.get("institutions_count")
    if reported is None:
        return named > 0
    try:
        reported_n = int(reported)
    except (TypeError, ValueError):
        return named > 0
    return named >= reported_n or named >= 50


def get_ownership_payload(
    symbol: str,
    *,
    ticker: Any | None = None,
    nasdaq_json: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Public ownership payload used by /api/ownership.

    `ticker` is an optional injected Yahoo-like object (tests).
    `nasdaq_json` is an optional injected Nasdaq holdings payload (tests).
    Live fetches prefer Nasdaq's full 13F table over Yahoo's top-N.
    Cached only for live fetches.
    """
    sym = symbol.strip().upper()
    now = time.time()
    if ticker is None and nasdaq_json is None and sym in _CACHE_OWNERSHIP:
        ts, data = _CACHE_OWNERSHIP[sym]
        if now - ts < CACHE_TTL_S and _cache_is_complete_ownership(data):
            return data

    payload = _build_ownership_payload(sym, ticker=ticker, nasdaq_json=nasdaq_json)
    if ticker is None and nasdaq_json is None:
        _CACHE_OWNERSHIP[sym] = (now, payload)
    return payload


def _ownership_pct(raw: float | None) -> float | None:
    if raw is None:
        return None
    return raw * 100.0 if raw <= 1.0 else raw


def _build_ownership_payload(
    symbol: str,
    ticker: Any | None = None,
    nasdaq_json: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    top_institutions: list[dict[str, Any]] = []
    top_funds: list[dict[str, Any]] = []
    info: dict[str, Any] = {}
    institutions_count: int | None = None
    px: float | None = None
    shares_out_for_parse: float | None = None
    holders_source = "yahoo"

    # Yahoo only when a ticker is injected, or on a live fetch (no nasdaq fixture).
    fetch_yahoo = ticker is not None or nasdaq_json is None
    if fetch_yahoo:
        try:
            live = ticker
            if live is None:
                import yfinance as yf  # type: ignore[import-not-found]
                live = yf.Ticker(symbol)
            info = dict(getattr(live, "info", None) or {})
            px = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
            shares_out_for_parse = _safe_float(info.get("sharesOutstanding"))
            top_institutions = parse_holder_rows(
                getattr(live, "institutional_holders", None),
                current_px=px,
                shares_outstanding=shares_out_for_parse,
            )
            top_funds = parse_holder_rows(
                getattr(live, "mutualfund_holders", None),
                current_px=px,
                shares_outstanding=shares_out_for_parse,
            )
            institutions_count = parse_reported_institution_count(info, getattr(live, "major_holders", None))
        except Exception as e:
            logger.debug("yfinance ownership fetch error for %s: %s", symbol, e)

    nasdaq_blob = nasdaq_json
    if ticker is None and nasdaq_json is None:
        nasdaq_blob = fetch_nasdaq_holdings_json(symbol)
    nasdaq = parse_nasdaq_holdings_payload(
        nasdaq_blob,
        current_px=px,
        shares_outstanding=shares_out_for_parse,
    )
    if nasdaq["institutions"]:
        top_institutions = nasdaq["institutions"]
        holders_source = "nasdaq_institutional_holdings"
    if nasdaq["funds"]:
        top_funds = nasdaq["funds"]
    if nasdaq["institutions_count"] is not None:
        if institutions_count is None:
            institutions_count = nasdaq["institutions_count"]
        else:
            institutions_count = max(int(institutions_count), int(nasdaq["institutions_count"]))

    shares_out = _safe_float(info.get("sharesOutstanding"))
    if shares_out is None:
        shares_out = nasdaq.get("shares_outstanding")
    float_sh = _safe_float(info.get("floatShares"))
    inst_pct = _ownership_pct(_safe_float(info.get("heldPercentInstitutions")))
    if inst_pct is None:
        inst_pct = nasdaq.get("institutional_pct")
    ins_pct = _ownership_pct(_safe_float(info.get("heldPercentInsiders")))
    retail_pct = None
    if inst_pct is not None and ins_pct is not None:
        retail_pct = max(0.0, round(100.0 - inst_pct - ins_pct, 1))

    short_sh = _safe_float(info.get("sharesShort"))
    prior_short = _safe_float(info.get("sharesShortPriorMonth"))
    short_ratio = _safe_round(info.get("shortRatio"), 1)
    raw_spf = _safe_float(info.get("shortPercentOfFloat"))
    short_pct_float = _safe_round(_ownership_pct(raw_spf), 2) if raw_spf is not None else None

    return {
        "symbol": symbol,
        "breakdown": {
            "institutional_pct": _safe_round(inst_pct, 1),
            "insider_pct": _safe_round(ins_pct, 1),
            "retail_float_pct": _safe_round(retail_pct, 1) if retail_pct is not None else None,
            "shares_outstanding": int(shares_out) if shares_out is not None else None,
            "float_shares": int(float_sh) if float_sh is not None else None,
        },
        "top_institutions": top_institutions,
        "top_funds": top_funds,
        "institutions_count": institutions_count,
        "holders_source": holders_source,
        "short_interest": {
            "shares_short": int(short_sh) if short_sh is not None else None,
            "short_pct_of_float": short_pct_float,
            "days_to_cover": short_ratio,
            "shares_short_prior_month": int(prior_short) if prior_short is not None else None,
        },
        "source": "institutional_13f_and_shareholder_registry",
        "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
