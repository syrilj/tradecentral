"""Report-native forecast: predicted price, forecast score, gearing-up readout.

Decision support only. Street consensus and median targets are never labels or
features, and missing filings stay ``None`` — zeros are not substituted for
absence.

Method
------
The published mark is a *forward* target price at the look-through horizon,
built from two bounded legs plus a small quality tilt:

1. **Earnings leg** — observed growth is shrunk toward a cross-sectional prior
   (:data:`GROWTH_SHRINK`), then faded exponentially toward
   :data:`TERMINAL_GROWTH` over the horizon. A single hot quarter is evidence,
   not a compounding rate.
2. **Multiple leg** — the log move from today's trailing multiple to the fair
   multiple implied by *faded* growth at the horizon. A rich name whose growth
   is rolling over pays for it, which is how the growth trap gets expressed.
3. **Quality tilt** — a frozen Ridge on a deterministic synthetic panel, at 28%
   weight. The panel carries an explicit value tilt, so a higher multiple
   lowers expected return rather than raising it.

Both the mark and the scenario band are railed in *annualised* terms
(:data:`MAX_ANNUALISED_RETURN` / :data:`MIN_ANNUALISED_RETURN`), so no input
combination can print an unbounded target and a bearish read is always
reachable. The target is not discounted — it is a price at the horizon, not a
present value — so :func:`cost_of_equity` is published alongside it as the
hurdle the implied return has to clear.

Units are taken from the source, never guessed from magnitude: the ``ratios``
block is percent, the live ``tape`` block is fractional, ``period_type`` decides
whether a five-row statement spans four quarters or four years, and a vendor
``debtToEquity`` of 150.0 means 1.5x.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

MISSING_STATUS = "missing"
OK_STATUS = "ok"
STALE_STATUS = "stale"

# Core statement-derived names the Ridge sees. Order is the model column order.
FEATURE_NAMES: tuple[str, ...] = (
    "log_revenue",
    "revenue_growth",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "rd_intensity",
    "fcf_margin",
    "capex_intensity",
    "current_ratio",
    "debt_to_equity",
    "roe",
    "roa",
    "log_pe",
    "log_pb",
)

# At least this many observed (non-null) model features plus a spot are required
# before the scorer will emit a price / score instead of a missing state.
MIN_OBSERVED_FEATURES = 6

# ── Valuation rails ────────────────────────────────────────────────────────
# The mark is a *forward* target price at the look-through horizon, so it is not
# discounted back. The cost of equity is carried alongside it instead, as the
# hurdle the implied return has to clear before the name is interesting.
DEFAULT_COST_OF_EQUITY = 0.09
LEVERAGE_RISK_PREMIUM = 0.015  # added per 1.0x of debt / equity
TERMINAL_GROWTH = 0.03  # long-run fade target, roughly nominal GDP
GROWTH_FADE_TAU_YEARS = 3.0  # supernormal growth half-lives into the terminal rate
GROWTH_PRIOR = 0.06  # shrinkage prior: typical sustainable growth
GROWTH_SHRINK = 0.55  # how much of the observed gap from the prior we keep
MAX_SUSTAINED_GROWTH = 0.60  # no filing justifies capitalising more than this
BASE_FAIR_PE = 15.0  # fair trailing multiple at zero sustainable growth
PE_GROWTH_SLOPE = 55.0  # fair multiple added per 1.0 of sustainable growth
MAX_FAIR_PE = 45.0
MIN_FAIR_PE = 8.0
# Annualised rails on the published view. Wide enough for a genuine top-decile
# call, tight enough that no input combination prints a fantasy target.
MAX_ANNUALISED_RETURN = 0.35
MIN_ANNUALISED_RETURN = -0.35
# Book equity at or below zero is balance-sheet distress, not zero leverage.
DISTRESS_DEBT_TO_EQUITY = 6.0
# 10th / 90th percentile band around the base case.
SCENARIO_Z = 1.2816
# Scenario rails, annualised. Wider than the base rails — a tail is allowed to
# be a tail — but still bounded so a bull case stays a forecast, not a fantasy.
MAX_SCENARIO_ANNUALISED = 0.80
MIN_SCENARIO_ANNUALISED = -0.60

# Gearing-up labels — model's view of the trajectory, not Street ratings.
GEARING_EXPANSION = "product and capacity expansion"
GEARING_MARGINS = "margin expansion via operating leverage"
GEARING_CASH = "cash generation and de-levering"
GEARING_REPAIR = "balance-sheet repair"
GEARING_QUALITY = "earnings quality rebuild"
GEARING_HARVEST = "defensive harvest"

_MODEL_CACHE: dict[str, Any] | None = None

_ROW_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("totalrevenue", "operatingrevenue", "revenue"),
    "gross_profit": ("grossprofit",),
    "operating_income": ("operatingincome", "ebit"),
    "net_income": ("netincome", "netincomecommonstockholders"),
    "rd": ("researchanddevelopment", "randd", "researchdevelopment"),
    "basic_eps": ("basiceps", "basicearningspershare"),
    "diluted_eps": ("dilutedeps", "dilutedearningspershare"),
    "gross_margin_pct": ("grossmarginpct", "grossmargin"),
    "operating_margin_pct": ("operatingmarginpct", "operatingmargin"),
    "net_margin_pct": ("netmarginpct", "netmargin"),
    "cash": ("cashandcashequivalents", "cashequivalents", "cashcashequivalentsandshortterminvestments"),
    "current_assets": ("currentassets", "totalcurrentassets"),
    "current_liabilities": ("currentliabilities", "totalcurrentliabilities"),
    "total_assets": ("totalassets",),
    "long_term_debt": ("longtermdebt", "longtermdebtandcapitalleaseobligation"),
    "equity": ("stockholdersequity", "commonstockequity", "totalstockholdersequity"),
    "working_capital": ("workingcapital",),
    "operating_cash_flow": ("operatingcashflow", "cashfromoperatingactivities", "cashflowfromcontinuingoperatingactivities"),
    "free_cash_flow": ("freecashflow",),
    "capex": ("capitalexpenditure", "capitalexpenditures", "capex"),
}


def _finite(val: Any) -> float | None:
    if val is None:
        return None
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return num


def _norm(text: Any) -> str:
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def _row_hits(key: str, label: str, alias: str) -> bool:
    if not alias:
        return False
    if key == alias or label == alias:
        return True
    if alias == "revenue" and ("cost" in key or "cost" in label):
        return False
    return alias in key or alias in label


def _row_series(rows: list[Mapping[str, Any]], aliases: tuple[str, ...]) -> list[float | None]:
    fuzzy: list[float | None] | None = None
    for row in rows:
        key = _norm(row.get("key", ""))
        label = _norm(row.get("label", ""))
        raw = [_finite(v) for v in (row.get("values") or [])]
        for alias in aliases:
            if key == alias or label == alias:
                return raw
            if fuzzy is None and _row_hits(key, label, alias):
                fuzzy = raw
    return fuzzy or []


def _latest(series: list[float | None]) -> float | None:
    for val in series:
        if val is not None:
            return val
    return None


def _growth(series: list[float | None], periods_per_year: int = 4) -> float | None:
    """Annualised growth from a newest-first series.

    The widest available span is used and then converted to a per-year rate, so
    an annual filing's four-year span is never read as if it were one year of
    growth (and a two-point quarterly span is not read as a full year either).
    """
    observed = [v for v in series if v is not None]
    if len(observed) >= 5 and observed[4] != 0:
        newest, oldest, periods = observed[0], observed[4], 4
    elif len(observed) >= 2 and observed[1] != 0:
        newest, oldest, periods = observed[0], observed[1], 1
    else:
        return None
    ppy = periods_per_year if periods_per_year and periods_per_year > 0 else 4
    years = periods / float(ppy)
    total = (newest - oldest) / abs(oldest)
    if years <= 0:
        return None
    if abs(years - 1.0) < 1e-9:
        return total
    ratio = 1.0 + total
    if ratio <= 0:
        # Sign flip (profit into loss): a root of a negative ratio is undefined,
        # so fall back to a linear per-year rate rather than inventing one.
        return max(total / years, -0.95)
    return ratio ** (1.0 / years) - 1.0


def _periods_per_year(payload: Mapping[str, Any] | None) -> int:
    """4 for quarterly reports, 1 for annual. Defaults to quarterly."""
    ptype = str((payload or {}).get("period_type") or "").strip().lower()
    if ptype.startswith(("annual", "year", "fy")):
        return 1
    if ptype.startswith(("quarter", "q")):
        return 4
    periods = (payload or {}).get("periods")
    if isinstance(periods, list) and len(periods) >= 2:
        try:
            y0 = int(str(periods[0])[:4])
            y1 = int(str(periods[1])[:4])
        except (TypeError, ValueError):
            return 4
        if abs(y0 - y1) >= 1:
            return 1
    return 4


def _normalise_debt_to_equity(val: float | None) -> float | None:
    """yfinance reports ``debtToEquity`` as a percentage — 150.0 means 1.5x.

    Left unconverted this standardises to z>600 against the fitted panel and
    pins the model to its floor for every symbol the vendor covers.
    """
    if val is None:
        return None
    if abs(val) > 5.0:
        val = val / 100.0
    if val < 0:
        return DISTRESS_DEBT_TO_EQUITY
    return val


def _ratio(numer: float | None, denom: float | None) -> float | None:
    if numer is None or denom is None or denom == 0:
        return None
    return numer / denom


def _log_pos(val: float | None) -> float | None:
    if val is None or val <= 0:
        return None
    return math.log(val)


def _tape_growth(val: Any) -> float | None:
    """Growth straight off the live tape. Already a fraction — never rescaled."""
    num = _finite(val)
    if num is None:
        return None
    return float(np.clip(num, -0.99, 10.0))


def _pct_to_frac(val: float | None) -> float | None:
    if val is None:
        return None
    # Statement margins are typically 0–100; ratios in this repo are too.
    if abs(val) > 1.5:
        return val / 100.0
    return val


def _table_rows(payload: Mapping[str, Any], table_key: str) -> list[Mapping[str, Any]]:
    table = payload.get(table_key) or {}
    if isinstance(table, Mapping):
        rows = table.get("rows") or []
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, Mapping)]
    return []


def statements_have_values(payload: Mapping[str, Any]) -> bool:
    """True when at least one income / balance / cash-flow cell is finite."""
    for key in ("income_statement", "balance_sheet", "cash_flow"):
        for row in _table_rows(payload, key):
            for val in row.get("values") or []:
                if _finite(val) is not None:
                    return True
    return False


def build_report_features(
    payload: Mapping[str, Any] | None,
    intel: Mapping[str, Any] | None = None,
) -> dict[str, float | None]:
    """Pure feature map from a financials report (+ optional adjacent intel).

    Absent fields stay None. Street consensus / target prices are ignored.
    """
    empty = {name: None for name in (
        *FEATURE_NAMES,
        "revenue",
        "net_income",
        "diluted_eps",
        "basic_eps",
        "free_cash_flow",
        "operating_cash_flow",
        "capex",
        "cash",
        "equity",
        "total_assets",
        "long_term_debt",
        "current_price",
        "market_cap",
        "insider_net_volume_usd",
        "institutional_pct",
    )}
    if not isinstance(payload, Mapping) or not statements_have_values(payload):
        return empty

    inc = _table_rows(payload, "income_statement")
    bal = _table_rows(payload, "balance_sheet")
    cf = _table_rows(payload, "cash_flow")
    ppy = _periods_per_year(payload)
    ratios = payload.get("ratios") if isinstance(payload.get("ratios"), Mapping) else {}
    extra = intel if isinstance(intel, Mapping) else {}

    def take(name: str) -> list[float | None]:
        return _row_series(inc if name in {
            "revenue", "gross_profit", "operating_income", "net_income", "rd",
            "basic_eps", "diluted_eps", "gross_margin_pct", "operating_margin_pct",
            "net_margin_pct",
        } else bal if name in {
            "cash", "current_assets", "current_liabilities", "total_assets",
            "long_term_debt", "equity", "working_capital",
        } else cf, _ROW_ALIASES[name])

    revenue = _latest(take("revenue"))
    gross_profit = _latest(take("gross_profit"))
    operating_income = _latest(take("operating_income"))
    net_income = _latest(take("net_income"))
    rd = _latest(take("rd"))
    basic_eps = _latest(take("basic_eps"))
    diluted_eps = _latest(take("diluted_eps"))
    cash = _latest(take("cash"))
    current_assets = _latest(take("current_assets"))
    current_liab = _latest(take("current_liabilities"))
    total_assets = _latest(take("total_assets"))
    lt_debt = _latest(take("long_term_debt"))
    equity = _latest(take("equity"))
    ocf = _latest(take("operating_cash_flow"))
    fcf = _latest(take("free_cash_flow"))
    capex = _latest(take("capex"))

    gross_margin = _pct_to_frac(_latest(take("gross_margin_pct"))) or _ratio(gross_profit, revenue)
    operating_margin = _pct_to_frac(_latest(take("operating_margin_pct"))) or _ratio(operating_income, revenue)
    net_margin = _pct_to_frac(_latest(take("net_margin_pct"))) or _ratio(net_income, revenue)

    # Ratios are secondary and only fill holes left by the statements.
    if gross_margin is None:
        gross_margin = _pct_to_frac(_finite(ratios.get("gross_margin")))
    if operating_margin is None:
        operating_margin = _pct_to_frac(_finite(ratios.get("operating_margin")))
    if net_margin is None:
        net_margin = _pct_to_frac(_finite(ratios.get("net_margin")))

    revenue_growth = _growth(take("revenue"), ppy)
    if revenue_growth is None:
        revenue_growth = _pct_to_frac(_finite(ratios.get("revenue_growth_yoy")))
    # Tape growth comes from yfinance as a FRACTION (0.82 == 82%); the ratios
    # block is built as a PERCENT. Running the magnitude heuristic over the tape
    # crushed a genuine 180% grower (1.8) to 1.8%, so units follow the source.
    live_rg = _tape_growth(extra.get("revenue_growth"))
    if live_rg is not None:
        revenue_growth = live_rg if revenue_growth is None else 0.45 * revenue_growth + 0.55 * live_rg

    earnings_growth = _growth(take("net_income"), ppy)
    if earnings_growth is None:
        earnings_growth = _pct_to_frac(_finite(ratios.get("earnings_growth_yoy")))
    live_eg = _tape_growth(extra.get("earnings_growth"))
    if live_eg is not None:
        earnings_growth = live_eg

    # Return on a negative book is arithmetically positive and economically
    # meaningless, so it stays undefined rather than flattering the name.
    negative_book = equity is not None and equity <= 0
    roe = None if negative_book else _ratio(net_income, equity)
    if roe is None and not negative_book:
        roe = _pct_to_frac(_finite(ratios.get("roe")))
    roa = _ratio(net_income, total_assets)
    if roa is None:
        roa = _pct_to_frac(_finite(ratios.get("roa")))

    current_ratio = _ratio(current_assets, current_liab)
    if current_ratio is None:
        current_ratio = _finite(ratios.get("current_ratio"))
    if negative_book:
        debt_to_equity = DISTRESS_DEBT_TO_EQUITY
    else:
        debt_to_equity = _ratio(lt_debt, equity)
    if debt_to_equity is None:
        debt_to_equity = _normalise_debt_to_equity(_finite(ratios.get("debt_to_equity")))
    if debt_to_equity is not None:
        debt_to_equity = float(np.clip(debt_to_equity, 0.0, DISTRESS_DEBT_TO_EQUITY))

    pe = _finite(ratios.get("pe_trailing"))
    pb = _finite(ratios.get("pb_trailing"))
    market_cap = _finite(ratios.get("market_cap"))
    pe_forward = _finite(ratios.get("pe_forward")) or _finite(extra.get("pe_forward"))
    implied_earnings_growth = None
    if pe is not None and pe_forward is not None and pe > 0 and pe_forward > 0:
        implied = pe / pe_forward - 1.0
        if -0.45 <= implied <= 1.8:
            implied_earnings_growth = implied
    forward_eps = _finite(extra.get("forward_eps"))
    trailing_eps = _finite(extra.get("trailing_eps")) or diluted_eps or basic_eps

    # Live tape wins. Synthetic fallback marks (e.g. $35) are not a last print.
    synthetic = str(payload.get("source") or "") == "deterministic_synthetic_financials"
    live_stamped = str(ratios.get("spot_source") or extra.get("spot_source") or "") == "live"
    spot = _finite(extra.get("last_price"))
    if spot is None:
        spot = _finite(extra.get("current_price"))
    if spot is None and (live_stamped or not synthetic):
        spot = _finite(ratios.get("current_price"))
    if spot is None and (live_stamped or not synthetic):
        spot = _finite(payload.get("current_price"))
    if spot is None and market_cap is not None and not synthetic:
        eps = diluted_eps if diluted_eps not in (None, 0) else basic_eps
        if net_income is not None and eps not in (None, 0):
            shares = net_income / eps
            if shares > 0:
                spot = market_cap / shares

    features: dict[str, float | None] = {
        "log_revenue": _log_pos(revenue),
        "revenue_growth": revenue_growth,
        "gross_margin": gross_margin,
        "operating_margin": operating_margin,
        "net_margin": net_margin,
        "rd_intensity": _ratio(rd, revenue),
        "fcf_margin": _ratio(fcf, revenue),
        "capex_intensity": _ratio(None if capex is None else abs(capex), revenue),
        "current_ratio": current_ratio,
        "debt_to_equity": debt_to_equity,
        "roe": roe,
        "roa": roa,
        "log_pe": _log_pos(pe),
        "log_pb": _log_pos(pb),
        "revenue": revenue,
        "net_income": net_income,
        "diluted_eps": diluted_eps,
        "basic_eps": basic_eps,
        "free_cash_flow": fcf,
        "operating_cash_flow": ocf,
        "capex": capex,
        "cash": cash,
        "equity": equity,
        "total_assets": total_assets,
        "long_term_debt": lt_debt,
        "current_price": spot,
        "market_cap": market_cap,
        "insider_net_volume_usd": _finite(extra.get("insider_net_volume_usd")),
        "institutional_pct": _finite(extra.get("institutional_pct")),
        "ret_1m": _finite(extra.get("ret_1m")),
        "ret_3m": _finite(extra.get("ret_3m")),
        "range_position": _finite(extra.get("range_position")),
        "earnings_growth": earnings_growth,
        "implied_earnings_growth": implied_earnings_growth,
        "forward_eps": forward_eps,
        "trailing_eps": trailing_eps,
        "pe_forward": pe_forward,
    }
    return features


def _observed_model_count(features: Mapping[str, float | None]) -> int:
    return sum(1 for name in FEATURE_NAMES if features.get(name) is not None)


def _vector(features: Mapping[str, float | None]) -> np.ndarray:
    return np.array([[features.get(name) if features.get(name) is not None else np.nan for name in FEATURE_NAMES]], dtype=float)


def _synthetic_panel(n: int = 480, seed: int = 42) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Latent-quality panel. Labels are fundamental residual return / quality, not Street."""
    rng = np.random.default_rng(seed)
    q = rng.normal(0.0, 1.0, size=n)
    growth = 0.08 + 0.10 * q + rng.normal(0.0, 0.04, size=n)
    gm = 0.42 + 0.08 * q + rng.normal(0.0, 0.03, size=n)
    om = gm * (0.45 + 0.08 * q) + rng.normal(0.0, 0.02, size=n)
    nm = om * (0.70 + 0.05 * q) + rng.normal(0.0, 0.015, size=n)
    rd = np.clip(0.08 + 0.06 * np.maximum(q, 0) + rng.normal(0.0, 0.02, size=n), 0.0, 0.45)
    fcf_m = nm + 0.04 - 0.03 * rd + rng.normal(0.0, 0.02, size=n)
    capex_i = np.clip(0.06 + 0.05 * np.maximum(q, 0) + rng.normal(0.0, 0.02, size=n), 0.01, 0.40)
    cr = np.clip(1.4 + 0.25 * q + rng.normal(0.0, 0.15, size=n), 0.4, 4.0)
    de = np.clip(0.55 - 0.20 * q + rng.normal(0.0, 0.12, size=n), 0.0, 3.5)
    roe = nm * (1.8 + 0.2 * q) + rng.normal(0.0, 0.03, size=n)
    roa = nm * (0.9 + 0.1 * q) + rng.normal(0.0, 0.02, size=n)
    log_rev = 18.0 + 1.2 * q + rng.normal(0.0, 0.8, size=n)
    # Richness carries its own dispersion instead of being a restatement of
    # quality. Tying the multiple to ``q`` alone taught the fit that expensive
    # names earn more (corr(log_pe, label) was +0.83), inverting the value tilt.
    richness = 0.35 * q + rng.normal(0.0, 0.95, size=n)
    log_pe = np.log(np.clip(18.0 + 7.0 * richness + rng.normal(0.0, 2.0, size=n), 4.0, 80.0))
    log_pb = np.log(np.clip(3.0 + 2.2 * richness + rng.normal(0.0, 0.6, size=n), 0.4, 25.0))

    x = np.column_stack([
        log_rev, growth, gm, om, nm, rd, fcf_m, capex_i, cr, de, roe, roa, log_pe, log_pb,
    ])
    # 12-month log residual return implied by the same latent quality — not a target price.
    log_ret = (
        0.03
        + 0.11 * q
        + 0.35 * growth
        + 0.20 * fcf_m
        + 0.12 * om
        - 0.08 * de
        - 0.055 * richness  # paying up mean-reverts: the value tilt
        + rng.normal(0.0, 0.03, size=n)
    )
    quality = 50.0 + 18.0 * np.tanh(q) + 12.0 * np.tanh(growth / 0.20) + 6.0 * np.tanh(fcf_m / 0.10)
    quality = np.clip(quality, 5.0, 95.0)
    return x, log_ret, quality


def _fit_models() -> dict[str, Any]:
    x, log_ret, quality = _synthetic_panel()
    ret_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("ridge", Ridge(alpha=2.0)),
    ])
    score_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("ridge", Ridge(alpha=2.0)),
    ])
    ret_pipe.fit(x, log_ret)
    score_pipe.fit(x, quality)
    return {"return": ret_pipe, "score": score_pipe}


def get_fitted_models() -> dict[str, Any]:
    """Module-level cached Ridge pair. Deterministic; no HTTP / Vue."""
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        _MODEL_CACHE = _fit_models()
    return _MODEL_CACHE


def classify_gearing_up(features: Mapping[str, float | None]) -> str | None:
    """Trajectory the filings imply the company is building toward."""
    if _observed_model_count(features) < MIN_OBSERVED_FEATURES:
        return None
    growth = features.get("revenue_growth")
    rd = features.get("rd_intensity")
    capex = features.get("capex_intensity")
    om = features.get("operating_margin")
    fcf_m = features.get("fcf_margin")
    de = features.get("debt_to_equity")
    nm = features.get("net_margin")

    scores = {
        GEARING_EXPANSION: 0.0,
        GEARING_MARGINS: 0.0,
        GEARING_CASH: 0.0,
        GEARING_REPAIR: 0.0,
        GEARING_QUALITY: 0.0,
        GEARING_HARVEST: 0.0,
    }
    if growth is not None and rd is not None and capex is not None:
        scores[GEARING_EXPANSION] = 1.4 * growth + 1.1 * rd + 0.9 * capex
    if om is not None and growth is not None:
        scores[GEARING_MARGINS] = 1.6 * om + 0.8 * growth
    if fcf_m is not None and de is not None:
        scores[GEARING_CASH] = 1.5 * fcf_m - 0.4 * de
    if de is not None and fcf_m is not None:
        scores[GEARING_REPAIR] = 0.9 * de - 1.2 * (fcf_m if fcf_m is not None else 0.0)
        if growth is not None and growth < 0:
            scores[GEARING_REPAIR] += 0.4
    if nm is not None and om is not None and nm < om * 0.45:
        scores[GEARING_QUALITY] = (om - nm) + 0.2
    if fcf_m is not None and growth is not None and growth < 0.04 and fcf_m > 0.08:
        scores[GEARING_HARVEST] = fcf_m - growth

    best_label = max(scores, key=scores.get)
    if scores[best_label] <= 0:
        # Still emit a directional view when we have enough filings.
        if growth is not None and growth >= 0.08:
            return GEARING_EXPANSION
        if om is not None and om >= 0.12:
            return GEARING_MARGINS
        if de is not None and de >= 1.0:
            return GEARING_REPAIR
        return GEARING_CASH
    return best_label


def blend_future_growth(features: Mapping[str, float | None]) -> float | None:
    """Blend statement / live / implied earnings growth. None if nothing observed."""
    parts: list[tuple[float, float]] = []
    eg = features.get("earnings_growth")
    rg = features.get("revenue_growth")
    ig = features.get("implied_earnings_growth")
    scaling = rg is not None and rg >= 0.15
    if eg is not None and eg < 0 and scaling:
        # Pre-profit / reinvestment: do not capitalize this year's losses.
        parts.append((float(np.clip(rg, -0.40, 0.90)), 0.70))
    elif eg is not None:
        parts.append((float(np.clip(eg, -0.40, 0.90)), 0.48))
        if rg is not None:
            parts.append((float(np.clip(rg, -0.40, 0.90)), 0.32))
    elif rg is not None:
        parts.append((float(np.clip(rg, -0.40, 0.90)), 0.55))
    if ig is not None and not (ig < 0 and scaling):
        parts.append((float(np.clip(ig, -0.40, 0.90)), 0.20))
    if not parts:
        return None
    total_w = sum(w for _, w in parts)
    g = sum(val * w for val, w in parts) / total_w
    return float(np.clip(g, -0.40, 0.95))


def lookthrough_years(
    growth: float | None,
    gearing: str | None,
    rd_intensity: float | None,
) -> float:
    """How far ahead the mark looks. Expansion / high growth = longer."""
    g = 0.0 if growth is None else growth
    years = 1.0
    if gearing == GEARING_REPAIR:
        years = 0.85
    elif gearing == GEARING_EXPANSION or g >= 0.18:
        years = 1.80
    elif g >= 0.08:
        years = 1.35
    if rd_intensity is not None and rd_intensity >= 0.12 and years >= 1.0:
        years += 0.20
    return years


def timeframe_from_years(years: float) -> tuple[str, int]:
    months = int(round(max(0.75, min(2.1, years)) * 12))
    months = min(24, max(10, months))
    return f"{months} months", months


def cost_of_equity(features: Mapping[str, float | None]) -> float:
    """Annual hurdle the implied return has to clear. Rises with leverage."""
    de = features.get("debt_to_equity")
    premium = 0.0 if de is None else LEVERAGE_RISK_PREMIUM * float(np.clip(de, 0.0, 3.0))
    return DEFAULT_COST_OF_EQUITY + premium


def sustainable_growth(growth: float | None) -> float | None:
    """Shrink an observed growth rate toward the cross-sectional prior.

    A single filing's growth is a noisy estimate of what a company can sustain,
    and the market has already paid for part of it. Capitalising the raw print
    is what turned an 82% quarter into a 3x price target.
    """
    if growth is None:
        return None
    shrunk = GROWTH_PRIOR + GROWTH_SHRINK * (growth - GROWTH_PRIOR)
    return float(np.clip(shrunk, -0.40, MAX_SUSTAINED_GROWTH))


def _faded_growth_log(g0: float, years: float) -> float:
    """Integral of log(1+g(t)) with g fading exponentially to TERMINAL_GROWTH.

    No business compounds its current rate flat out to the horizon, so the
    earnings leg decays toward the terminal rate instead of staying pinned.
    """
    steps = 240
    dt = max(years, 0.0) / steps
    total = 0.0
    for i in range(steps):
        t = (i + 0.5) * dt
        g_t = TERMINAL_GROWTH + (g0 - TERMINAL_GROWTH) * math.exp(-t / GROWTH_FADE_TAU_YEARS)
        total += math.log1p(max(g_t, -0.85)) * dt
    return total


def fair_multiple(growth_at_horizon: float) -> float:
    """Fair trailing multiple for a given sustainable growth rate."""
    fair = BASE_FAIR_PE + PE_GROWTH_SLOPE * max(growth_at_horizon, 0.0)
    return float(np.clip(fair, MIN_FAIR_PE, MAX_FAIR_PE))


def multiple_rerate_log(
    pe_now: float | None,
    g0: float,
    years: float,
    gearing: str | None,
) -> float:
    """Log change from today's multiple to the fair multiple at the horizon.

    The horizon multiple is priced off *faded* growth, so a rich name whose
    growth is rolling over pays for it — the growth trap the old unconditional
    ``+0.32 * tanh(growth)`` re-rate could never express.
    """
    if pe_now is None or pe_now <= 0:
        return 0.0
    g_h = TERMINAL_GROWTH + (g0 - TERMINAL_GROWTH) * math.exp(-max(years, 0.0) / GROWTH_FADE_TAU_YEARS)
    fair = fair_multiple(g_h)
    if gearing == GEARING_REPAIR:
        fair = min(fair, BASE_FAIR_PE)
    return float(np.clip(math.log(fair / pe_now), -0.50, 0.40))


def growth_lookthrough_log_return(
    growth: float,
    gearing: str | None,
    rd_intensity: float | None,
    pe_now: float | None = None,
    years: float | None = None,
) -> float:
    """Earnings the company is building toward, plus the multiple it should carry.

    Two legs, both bounded: faded earnings growth over the horizon, and the
    re-rating from today's multiple to the one that growth deserves by then.
    """
    if years is None:
        years = lookthrough_years(growth, gearing, rd_intensity)
    g0 = sustainable_growth(growth) or 0.0
    earnings_leg = _faded_growth_log(g0, years)
    rerate = multiple_rerate_log(pe_now, g0, years, gearing)
    return earnings_leg + rerate


def scenario_sigma(
    features: Mapping[str, float | None],
    future_g: float | None,
    years: float,
) -> float:
    """Horizon log-return dispersion. Faster growth and more debt widen it."""
    g = abs(future_g or 0.0)
    de = features.get("debt_to_equity") or 0.0
    annual = 0.28 + 0.30 * min(g, 0.60) + 0.04 * float(np.clip(de, 0.0, 3.0))
    annual = float(np.clip(annual, 0.22, 0.75))
    return annual * math.sqrt(max(years, 0.25))


def _pct_display(val: float) -> str:
    return f"{val * 100:+.0f}%"


def forecast_factors(
    features: Mapping[str, float | None],
    future_g: float | None,
) -> list[dict[str, Any]]:
    """Observed drivers only. Missing fields are omitted, never faked as 0."""
    rows: list[dict[str, Any]] = []

    def add(key: str, label: str, val: float | None, kind: str) -> None:
        if val is None or not math.isfinite(val):
            return
        if kind == "pct":
            display = _pct_display(val)
        elif kind == "x":
            display = f"{val:.2f}x"
        else:
            display = f"{val:.2f}"
        tone = "pos" if val > 0 else "neg" if val < 0 else "flat"
        if key == "debt_to_equity":
            tone = "neg" if val >= 1.0 else "pos" if val <= 0.45 else "flat"
        if key == "cost_of_equity":
            tone = "flat"
        rows.append({
            "key": key,
            "label": label,
            "value": round(float(val), 6),
            "display": display,
            "tone": tone,
        })

    add("revenue_growth", "Revenue growth", features.get("revenue_growth"), "pct")
    add("earnings_growth", "Earnings growth", features.get("earnings_growth"), "pct")
    add("lookthrough_growth", "Look-through growth", future_g, "pct")
    add("rd_intensity", "R&D intensity", features.get("rd_intensity"), "pct")
    add("capex_intensity", "Capex intensity", features.get("capex_intensity"), "pct")
    add("fcf_margin", "FCF margin", features.get("fcf_margin"), "pct")
    add("operating_margin", "Operating margin", features.get("operating_margin"), "pct")
    add("debt_to_equity", "Debt / equity", features.get("debt_to_equity"), "x")
    add("ret_3m", "3-month tape", features.get("ret_3m"), "pct")
    add("range_position", "52-week range", features.get("range_position"), "pct")
    return rows


def _case_thesis(side: str, gearing: str | None, future_g: float | None) -> str:
    g = future_g
    if side == "bull":
        if gearing == GEARING_EXPANSION:
            return "Scale converts into earnings; the growth multiple holds or expands."
        if g is not None and g >= 0.15:
            return "Growth stays intact and the multiple is allowed to re-rate."
        return "Execution beats the current run-rate and cash conversion improves."
    if side == "bear":
        if gearing == GEARING_REPAIR:
            return "De-levering stalls or cash stays tight; the multiple compresses."
        if gearing == GEARING_EXPANSION:
            return "Growth or funding slips; the multiple compresses and the mark can print below today's price."
        return "Growth misses and the multiple comes in — downside can sit below the live print."
    if gearing == GEARING_EXPANSION:
        return "Base case looks through the growth they are building toward."
    return "Base case follows the filings and live tape, not Street targets."


def scenario_case_prices(
    spot: float,
    predicted_price: float,
    sigma_h: float,
    years: float = 1.0,
    z: float = SCENARIO_Z,
) -> tuple[float, float, float]:
    """10th / base / 90th percentile of a lognormal band around the base case.

    The width is the model's own uncertainty (growth volatility and leverage
    scaled by the horizon), so it carries information. The previous version
    pinned bear and bull to fixed multiples of spot, which made the band
    decorative — the same +/-8% brackets whatever the inputs said.
    """
    spread = max(z * max(sigma_h, 0.05), 0.05)
    bear = predicted_price * math.exp(-spread)
    bull = predicted_price * math.exp(spread)
    # A bear case has to be a genuine adverse outcome against the live mark;
    # a merely cheaper bull is not a downside scenario.
    bear = min(bear, spot * 0.92)
    bull = max(bull, spot * 1.05, predicted_price * 1.05)
    # Rail the tails in annualised terms so a long horizon cannot compound the
    # band into a number nobody would underwrite.
    yrs = max(years, 0.25)
    bull = min(bull, spot * (1.0 + MAX_SCENARIO_ANNUALISED) ** yrs)
    bear = max(bear, spot * (1.0 + MIN_SCENARIO_ANNUALISED) ** yrs)
    bull = max(bull, predicted_price * 1.05)
    if bear >= predicted_price:
        bear = min(predicted_price * 0.85, spot * 0.90)
    return round(float(bear), 4), round(float(predicted_price), 4), round(float(bull), 4)


def _empty_forecast(*, status: str = MISSING_STATUS) -> dict[str, Any]:
    return {
        "predicted_price": None,
        "forecast_score": None,
        "gearing_up_towards": None,
        "status": status,
        "label": "what it should be",
        "horizon": "18m research",
        "timeframe": None,
        "timeframe_months": None,
        "factors": [],
        "cases": {
            "bear": {"price": None, "label": "Bear", "thesis": None},
            "base": {"price": None, "label": "Base", "thesis": None},
            "bull": {"price": None, "label": "Bull", "thesis": None},
        },
        "decision_authorized": False,
        "live_capital_authorized": False,
        "features_used": [],
        "observed_feature_count": 0,
        "feature_count_total": len(FEATURE_NAMES),
        "expected_return": None,
        "annualized_return": None,
        "cost_of_equity": None,
        "excess_annualized_return": None,
        "scenario_sigma": None,
        "sustainable_growth": None,
    }


def _treasury_forecast(
    payload: Mapping[str, Any] | None,
    intel: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Delegate to the NAV engine when the filings say this is a coin stack.

    Import is local: the treasury module is a sibling in ``research`` and a
    module-level import would make either file unusable without the other.
    Classification failing closed is deliberate — an exception here must fall
    back to the earnings engine, never blank the surface.
    """
    try:
        try:
            from research.treasury_nav_forecast import (
                classify_digital_asset_treasury,
                score_treasury_forecast,
            )
        except ImportError:  # pragma: no cover - checkout-as-edge namespace
            from edge.research.treasury_nav_forecast import (  # type: ignore[no-redef]
                classify_digital_asset_treasury,
                score_treasury_forecast,
            )
        periods_per_year = _periods_per_year(payload)
        evidence = classify_digital_asset_treasury(payload, periods_per_year)
        if not evidence:
            return None
        return score_treasury_forecast(payload, intel, evidence)
    except Exception:  # noqa: BLE001 - never let routing blank the forecast
        return None


def score_report_forecast(
    payload: Mapping[str, Any] | None,
    intel: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fit/predict path: predicted price, 0–100 forecast score, gearing-up readout.

    Returns explicit missing/stale fields when the report is insufficient.
    Never emits 0 / "0" / "" as a stand-in for a missing score.
    """
    merged: dict[str, Any] = {}
    if isinstance(payload, Mapping) and isinstance(payload.get("tape"), Mapping):
        merged.update(payload["tape"])
    if isinstance(intel, Mapping):
        merged.update(intel)
    intel = merged

    # A digital-asset treasury is not an operating business with a strange
    # income statement — it is a coin position with a small software company
    # attached. Capitalising a fair-value remeasurement as earnings growth and
    # computing a P/E whose E is a crypto tick produces an arithmetically
    # correct, economically meaningless mark. Route those names to the NAV
    # engine, which values the stack instead of the bottom line.
    treasury = _treasury_forecast(payload, intel)
    if treasury is not None:
        return treasury

    features = build_report_features(payload, intel)
    observed = _observed_model_count(features)
    used = [name for name in FEATURE_NAMES if features.get(name) is not None]
    spot = features.get("current_price")

    if not statements_have_values(payload or {}) or observed < MIN_OBSERVED_FEATURES:
        out = _empty_forecast(status=MISSING_STATUS)
        out["observed_feature_count"] = observed
        out["features_used"] = used
        return out

    models = get_fitted_models()
    x = _vector(features)
    log_ret = float(models["return"].predict(x)[0])
    raw_score = float(models["score"].predict(x)[0])
    if not math.isfinite(log_ret) or not math.isfinite(raw_score):
        out = _empty_forecast(status=STALE_STATUS)
        out["observed_feature_count"] = observed
        out["features_used"] = used
        return out

    ridge_ret = float(np.clip(log_ret, -0.75, 0.75))
    gearing = classify_gearing_up(features)
    future_g = blend_future_growth(features)
    years = lookthrough_years(future_g, gearing, features.get("rd_intensity"))
    hurdle = cost_of_equity(features)
    g_sustainable = sustainable_growth(future_g)
    log_pe = features.get("log_pe")
    pe_now = math.exp(log_pe) if log_pe is not None else None

    if future_g is not None:
        look_ret = growth_lookthrough_log_return(
            future_g, gearing, features.get("rd_intensity"), pe_now=pe_now, years=years,
        )
        # Growth/future earnings dominate — the Ridge residual only tempers.
        log_ret = 0.28 * ridge_ret + 0.72 * look_ret
    else:
        log_ret = ridge_ret
    ret_3m = features.get("ret_3m")
    if ret_3m is not None:
        log_ret += 0.12 * math.tanh(ret_3m)
    range_pos = features.get("range_position")
    if range_pos is not None:
        # Symmetric: extended names give some back, based names are not punished.
        log_ret += 0.06 * (2.0 * float(np.clip(range_pos, 0.0, 1.0)) - 1.0)

    # Annualised rails. Nothing in a filing justifies an unbounded target, and
    # the old expansion ratchets (a hard +28% floor) made a bearish read
    # structurally impossible however poor the fundamentals were.
    cap = years * math.log1p(MAX_ANNUALISED_RETURN)
    floor = years * math.log1p(MIN_ANNUALISED_RETURN)
    log_ret = float(np.clip(log_ret, floor, cap))

    annualized = math.expm1(log_ret / max(years, 0.25))
    excess = annualized - hurdle
    quality = float(np.clip(raw_score, 5.0, 95.0))
    # The return leg scores return *above the hurdle*, not raw return, so a
    # levered name has to work harder for the same mark.
    return_leg = 50.0 + 40.0 * math.tanh(excess / 0.22)
    forecast_score = float(np.clip(0.55 * quality + 0.45 * return_leg, 5.0, 95.0))
    predicted_price = None
    if spot is not None and spot > 0:
        predicted_price = float(spot) * math.exp(log_ret)
        fwd_eps = features.get("forward_eps")
        if fwd_eps is not None and fwd_eps > 0 and g_sustainable is not None:
            multiple = fair_multiple(g_sustainable)
            eps_px = fwd_eps * multiple
            if 0.55 * spot < eps_px < 2.5 * spot:
                predicted_price = 0.58 * predicted_price + 0.42 * eps_px
        # Re-assert the rail after the EPS cross-check so the blend cannot
        # carry the mark back outside it.
        predicted_price = float(
            np.clip(predicted_price, spot * math.exp(floor), spot * math.exp(cap))
        )
        log_ret = math.log(predicted_price / float(spot))
        annualized = math.expm1(log_ret / max(years, 0.25))
        excess = annualized - hurdle
        predicted_price = round(predicted_price, 4)

    timeframe, timeframe_months = timeframe_from_years(years)
    factors = forecast_factors(features, future_g)
    horizon = f"{timeframe_months}m research"

    # Sufficient filings without a spot still yield score + gearing, not a fake price.
    if predicted_price is None:
        status = STALE_STATUS if observed >= MIN_OBSERVED_FEATURES else MISSING_STATUS
        return {
            "predicted_price": None,
            "forecast_score": round(forecast_score, 4),
            "gearing_up_towards": gearing,
            "status": status,
            "label": "what it should be",
            "horizon": horizon,
            "timeframe": timeframe,
            "timeframe_months": timeframe_months,
            "factors": factors,
            "cases": {
                "bear": {"price": None, "label": "Bear", "thesis": None},
                "base": {"price": None, "label": "Base", "thesis": None},
                "bull": {"price": None, "label": "Bull", "thesis": None},
            },
            "decision_authorized": False,
            "live_capital_authorized": False,
            "features_used": used,
            "observed_feature_count": observed,
            "implied_log_return": round(log_ret, 6),
            "lookthrough_growth": None if future_g is None else round(future_g, 6),
            "sustainable_growth": None if g_sustainable is None else round(g_sustainable, 6),
            "cost_of_equity": round(hurdle, 6),
            "annualized_return": round(annualized, 6),
            "excess_annualized_return": round(excess, 6),
            "expected_return": round(math.expm1(log_ret), 6),
            "feature_count_total": len(FEATURE_NAMES),
            "scenario_sigma": None,
            "spot_used": None,
            "spot_source": None,
        }

    intel = intel if isinstance(intel, Mapping) else {}
    spot_source = None
    if _finite(intel.get("last_price")) or _finite(intel.get("current_price")):
        spot_source = "live"
    elif str((payload or {}).get("source") or "") == "deterministic_synthetic_financials":
        spot_source = "synthetic"
    else:
        spot_source = "report"

    sigma_h = scenario_sigma(features, future_g, years)
    bear_px, base_px, bull_px = scenario_case_prices(
        float(spot), float(predicted_price), sigma_h, years,
    )
    return {
        "predicted_price": predicted_price,
        "forecast_score": round(forecast_score, 4),
        "gearing_up_towards": gearing,
        "status": OK_STATUS,
        "label": "what it should be",
        "horizon": horizon,
        "timeframe": timeframe,
        "timeframe_months": timeframe_months,
        "factors": factors,
        "cases": {
            "bear": {
                "price": bear_px,
                "label": "Bear",
                "thesis": _case_thesis("bear", gearing, future_g),
            },
            "base": {
                "price": base_px,
                "label": "Base",
                "thesis": _case_thesis("base", gearing, future_g),
            },
            "bull": {
                "price": bull_px,
                "label": "Bull",
                "thesis": _case_thesis("bull", gearing, future_g),
            },
        },
        "decision_authorized": False,
        "live_capital_authorized": False,
        "features_used": used,
        "observed_feature_count": observed,
        "implied_log_return": round(log_ret, 6),
        "lookthrough_growth": None if future_g is None else round(future_g, 6),
        "sustainable_growth": None if g_sustainable is None else round(g_sustainable, 6),
        "cost_of_equity": round(hurdle, 6),
        "annualized_return": round(annualized, 6),
        "excess_annualized_return": round(excess, 6),
        "expected_return": round(math.expm1(log_ret), 6),
        "feature_count_total": len(FEATURE_NAMES),
        "scenario_sigma": round(sigma_h, 6),
        "spot_used": round(float(spot), 4) if spot else None,
        "spot_source": spot_source,
    }


def attach_model_forecast(
    payload: Mapping[str, Any],
    intel: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a shallow copy of the report with ``model_forecast`` attached."""
    out = dict(payload)
    out["model_forecast"] = score_report_forecast(out, intel)
    return out
