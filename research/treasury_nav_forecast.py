"""Digital-asset treasury forecast: NAV bridge, own-history mNAV, coin-per-share.

Decision support only. Research, not an ENTER authorization.

Why this exists
---------------
:mod:`research.financials_ml_forecast` prices an operating business: it
capitalises earnings growth and re-rates a P/E. Pointed at a digital-asset
treasury company that engine reads a coin fair-value remeasurement as
*earnings*. For a name holding ~$50B of coin against ~$0.5B of software
revenue, ASU 2023-08 puts a ±$10B non-cash mark through net income every
quarter. The earnings leg then capitalises a crypto tick, the multiple leg
computes a P/E whose E is that same tick, and coin purchases show up as capex
intensity in the thousands of percent. Every number is arithmetically correct
and economically meaningless.

Method
------
The stack is valued, not the income statement.

1. **Implied holdings** — the coin carrying value on the balance sheet divided
   by the coin price *at that period end*. Fair-value accounting makes the
   carrying value a mark, so dividing it back out recovers the unit count the
   filing implies. Holdings are a count, not a price, so they survive a
   re-mark; that is the whole point.
2. **NAV bridge** — holdings re-marked to the live coin price, plus cash, plus
   a revenue multiple on the operating stub, less total debt, less preferred at
   carrying value. Preferred sits ahead of common and is not netted silently.
3. **mNAV** — the premium the market pays over that NAV. The anchor is the
   name's *own* history: one mNAV observation per reported period, from its own
   price and its own NAV on that date. No cross-sectional prior is imposed on a
   structure the cross-section does not contain.
4. **Coin per share** — holdings ÷ diluted shares, period over period. This is
   the flywheel measured rather than assumed: issuing above NAV and buying coin
   raises coin-per-share, issuing below NAV destroys it. The sign falls out of
   the filings.

The coin price is **not** forecast. Expected coin price at the horizon is the
live spot — a martingale. Every published number is therefore conditional on
the coin, and the scenario band is where the coin's own volatility is expressed
(levered by NAV gearing, widened by mNAV dispersion). A model that quietly
assumed coin drift would be publishing a crypto call dressed as equity
research.

Classification is evidence-based, never a ticker list: the coin stack has to
dominate assets, the operating business has to be immaterial against those
assets, and the bottom line has to be dominated by remeasurement rather than
operations. All three, or the name routes back to the earnings engine.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

TREASURY_STATUS = "ok"
TREASURY_LABEL = "what it should be"
TREASURY_METHOD = "digital_asset_treasury_nav"

# ── Classification thresholds ──────────────────────────────────────────────
# All three must hold. Each alone has a plausible false positive: an acquisitive
# rollup carries large intangibles, a pre-revenue biotech carries little revenue,
# and a one-off impairment distorts any single bottom line. Together they
# describe a balance sheet that *is* the business.
MIN_COIN_ASSET_SHARE = 0.50   # coin carrying value / total assets
MAX_REVENUE_ASSET_RATIO = 0.10  # TTM revenue / total assets
MIN_REMEASUREMENT_RATIO = 2.0   # |net income| / revenue

# ── Valuation ──────────────────────────────────────────────────────────────
# The operating stub is a real business, but a small one against the stack.
# A revenue multiple keeps it bounded; capitalising its (negative) earnings is
# what the earnings engine already got wrong.
OPERATING_REVENUE_MULTIPLE = 2.5
# How far the current premium reverts toward the name's own historical median
# over the horizon. Partial: today's regime is evidence, not noise.
MNAV_REVERSION = 0.45
# Rails on the mNAV anchor. A treasury trading at a huge premium is a real
# market state, but it is not a target the model will extrapolate.
MIN_MNAV_ANCHOR = 0.55
MAX_MNAV_ANCHOR = 2.50
# Coin-per-share accretion is derived, then railed. The flywheel is real but it
# is funded by issuance, and issuance windows close.
MAX_COIN_PER_SHARE_GROWTH = 0.60
MIN_COIN_PER_SHARE_GROWTH = -0.25
# Accretion fades like any supernormal rate — it depends on a premium that the
# reversion term is simultaneously closing.
ACCRETION_FADE_TAU_YEARS = 2.0

# Horizon. Treasury names are coin-clocked, not filing-clocked; a shorter book
# than the earnings engine's, because the premium regime turns over fast.
HORIZON_YEARS = 1.0

# Hurdle. A levered coin holding is not a 9% cost-of-equity asset.
BASE_COST_OF_EQUITY = 0.09
NAV_LEVERAGE_PREMIUM = 0.045  # per 1.0x of coin NAV / equity NAV above 1.0
MAX_COST_OF_EQUITY = 0.30

# Rails on the published mark, annualised, matching the earnings engine's
# contract. Wider, because NAV gearing is a real mechanism, not an input error.
MAX_ANNUALISED_RETURN = 0.55
MIN_ANNUALISED_RETURN = -0.50
SCENARIO_Z = 1.2816  # 10th / 90th percentile
MAX_SCENARIO_ANNUALISED = 1.20
MIN_SCENARIO_ANNUALISED = -0.70

# Fallback coin volatility when no history is supplied. Deliberately high.
DEFAULT_COIN_VOL = 0.55
# Dispersion floor on the mNAV band — two observations do not make a regime.
MIN_MNAV_LOG_SD = 0.18

GEARING_ACCRETION = "coin-per-share accretion"
GEARING_DILUTION = "issuance below NAV — coin per share falling"
GEARING_DELEVER = "premium compression and de-levering"
GEARING_HOLD = "holding the stack"


def _finite(val: Any) -> float | None:
    try:
        out = float(val)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _norm(text: Any) -> str:
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def _rows(payload: Mapping[str, Any], table: str) -> list[Mapping[str, Any]]:
    block = payload.get(table) or {}
    if not isinstance(block, Mapping):
        return []
    rows = block.get("rows")
    return [r for r in rows if isinstance(r, Mapping)] if isinstance(rows, list) else []


def _series(
    rows: Sequence[Mapping[str, Any]],
    aliases: tuple[str, ...],
    *,
    strict: bool = False,
) -> list[float | None]:
    """Newest-first value series for the first row matching any alias.

    ``strict`` disables substring matching. Goodwill needs it: a payload that
    only carries the combined "Goodwill & Intangible Assets" line would
    otherwise fuzzy-match ``goodwill`` and net the entire coin stack out of the
    NAV bridge. A row that is not reported must read as absent, not as the
    superset row that happens to contain its name.
    """
    fuzzy: list[float | None] | None = None
    for row in rows:
        key = _norm(row.get("key", ""))
        label = _norm(row.get("label", ""))
        vals = [_finite(v) for v in (row.get("values") or [])]
        for alias in aliases:
            if key == alias or label == alias:
                return vals
            if not strict and fuzzy is None and alias and (alias in key or alias in label):
                fuzzy = vals
    return fuzzy or []


def _at(series: Sequence[float | None], idx: int) -> float | None:
    return series[idx] if 0 <= idx < len(series) else None


def _first(series: Sequence[float | None]) -> float | None:
    for val in series:
        if val is not None:
            return val
    return None


# Exact rows only. "Goodwill & Intangible Assets" is a superset line and
# matching it here would mark acquisition goodwill as coin.
_COIN_CARRY = ("digitalassets", "otherintangibleassets", "bitcoin", "cryptoassets")
_GOODWILL = ("goodwill",)
_TOTAL_ASSETS = ("totalassets",)
_REVENUE = ("totalrevenue", "operatingrevenue", "revenue")
_NET_INCOME = ("netincome", "netincomecommonstockholders")
_DILUTED_EPS = ("dilutedeps", "dilutedearningspershare")
_CASH_COMBINED = ("cashshortterminvestments",
                  "cashcashequivalentsandshortterminvestments")
_CASH = ("cashandcashequivalents", "cashcashequivalents")
_STI = ("othershortterminvestments", "shortterminvestments")
_TOTAL_DEBT = ("totaldebt",)
_LT_DEBT = ("longtermdebtandcapitalleaseobligation", "longtermdebt")
_CUR_DEBT = ("currentdebtandcapitalleaseobligation", "currentdebt")
_PREFERRED = ("preferredstockequity", "preferredstock")


def _ttm(series: Sequence[float | None], periods_per_year: int) -> float | None:
    """Trailing-twelve-month sum. Requires a full year of observed periods."""
    take = series[:periods_per_year]
    if len(take) < periods_per_year or any(v is None for v in take):
        return None
    return float(sum(v for v in take if v is not None))


def classify_digital_asset_treasury(
    payload: Mapping[str, Any] | None,
    periods_per_year: int = 4,
) -> dict[str, Any] | None:
    """Evidence for routing to the NAV engine, or ``None``.

    Three independent signals, all required. Returns the evidence itself so the
    caller can publish *why* a name was reclassified rather than asserting it.
    """
    if not isinstance(payload, Mapping):
        return None
    bal = _rows(payload, "balance_sheet")
    inc = _rows(payload, "income_statement")
    if not bal or not inc:
        return None

    carry_series = _series(bal, _COIN_CARRY, strict=True)
    coin_carry = _first(carry_series)
    total_assets = _first(_series(bal, _TOTAL_ASSETS))
    if not coin_carry or not total_assets or coin_carry <= 0 or total_assets <= 0:
        return None

    # Acquisition goodwill is not a coin stack. Net it out before testing share.
    goodwill = _first(_series(bal, _GOODWILL, strict=True)) or 0.0
    if goodwill > 0 and goodwill < coin_carry:
        coin_carry = max(coin_carry - goodwill, 0.0)
    if coin_carry <= 0:
        return None

    asset_share = coin_carry / total_assets
    if asset_share < MIN_COIN_ASSET_SHARE:
        return None

    rev_series = _series(inc, _REVENUE)
    revenue_ttm = _ttm(rev_series, periods_per_year)
    if revenue_ttm is None:
        latest_rev = _first(rev_series)
        revenue_ttm = None if latest_rev is None else latest_rev * periods_per_year
    if revenue_ttm is None or revenue_ttm <= 0:
        return None
    revenue_ratio = revenue_ttm / total_assets
    if revenue_ratio > MAX_REVENUE_ASSET_RATIO:
        return None

    ni_series = _series(inc, _NET_INCOME)
    net_income = _first(ni_series)
    latest_rev = _first(rev_series)
    if net_income is None or not latest_rev or latest_rev <= 0:
        return None
    remeasurement = abs(net_income) / latest_rev
    if remeasurement < MIN_REMEASUREMENT_RATIO:
        return None

    return {
        "coin_carrying_value": round(coin_carry, 2),
        "total_assets": round(total_assets, 2),
        "coin_asset_share": round(asset_share, 6),
        "revenue_ttm": round(revenue_ttm, 2),
        "revenue_asset_ratio": round(revenue_ratio, 6),
        "remeasurement_ratio": round(remeasurement, 4),
        "goodwill_excluded": round(goodwill, 2) if goodwill else 0.0,
    }


def implied_holdings(coin_carrying_value: float, coin_price_at_period: float) -> float | None:
    """Unit count the filing implies: a fair-value mark divided back by its price."""
    if coin_carrying_value <= 0 or coin_price_at_period <= 0:
        return None
    return coin_carrying_value / coin_price_at_period


def diluted_shares(net_income: float | None, diluted_eps: float | None) -> float | None:
    """Share count implied by the filing's own bottom line and per-share figure.

    Both legs carry the same sign, so a loss period recovers the same positive
    count a profit period does.
    """
    if net_income is None or diluted_eps is None or diluted_eps == 0:
        return None
    shares = abs(net_income) / abs(diluted_eps)
    return shares if math.isfinite(shares) and shares > 0 else None


def nav_bridge(
    *,
    holdings: float,
    coin_spot: float,
    cash: float | None,
    revenue_ttm: float | None,
    total_debt: float | None,
    preferred: float | None,
) -> dict[str, float]:
    """Coin marked live, plus cash and the operating stub, less debt and preferred."""
    coin_nav = holdings * coin_spot
    cash_v = max(cash or 0.0, 0.0)
    stub = max((revenue_ttm or 0.0) * OPERATING_REVENUE_MULTIPLE, 0.0)
    debt_v = max(total_debt or 0.0, 0.0)
    pref_v = max(preferred or 0.0, 0.0)
    nav = coin_nav + cash_v + stub - debt_v - pref_v
    return {
        "coin_nav": coin_nav,
        "cash": cash_v,
        "operating_stub": stub,
        "total_debt": debt_v,
        "preferred": pref_v,
        "nav_to_common": nav,
    }


def mnav_observations(
    *,
    carry_series: Sequence[float | None],
    cash_series: Sequence[float | None],
    debt_series: Sequence[float | None],
    preferred_series: Sequence[float | None],
    share_series: Sequence[float | None],
    coin_price_history: Sequence[float | None],
    price_history: Sequence[float | None],
    revenue_ttm: float | None,
) -> list[dict[str, float]]:
    """One mNAV point per reported period, each priced on that period's own date.

    The coin price, the equity price and the balance sheet all come from the
    same date, so the ratio is a real historical premium rather than today's
    price against a stale book.
    """
    out: list[dict[str, float]] = []
    n = min(len(carry_series), len(coin_price_history), len(price_history))
    for i in range(n):
        carry = _at(carry_series, i)
        coin_px = _at(coin_price_history, i)
        equity_px = _at(price_history, i)
        shares = _at(share_series, i)
        if not carry or not coin_px or not equity_px or not shares:
            continue
        hold = implied_holdings(carry, coin_px)
        if hold is None:
            continue
        bridge = nav_bridge(
            holdings=hold,
            coin_spot=coin_px,
            cash=_at(cash_series, i),
            revenue_ttm=revenue_ttm,
            total_debt=_at(debt_series, i),
            preferred=_at(preferred_series, i),
        )
        nav_ps = bridge["nav_to_common"] / shares
        if nav_ps <= 0:
            continue
        out.append({
            "index": float(i),
            "holdings": hold,
            "shares": shares,
            "coin_per_share": hold / shares,
            "nav_per_share": nav_ps,
            "price": equity_px,
            "mnav": equity_px / nav_ps,
        })
    return out


def _log_sd(values: Sequence[float]) -> float:
    positives = [v for v in values if v > 0]
    if len(positives) < 2:
        return MIN_MNAV_LOG_SD
    logs = [math.log(v) for v in positives]
    mean = sum(logs) / len(logs)
    var = sum((x - mean) ** 2 for x in logs) / (len(logs) - 1)
    return max(math.sqrt(var), MIN_MNAV_LOG_SD)


def _median(values: Sequence[float]) -> float | None:
    vals = sorted(v for v in values if math.isfinite(v))
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else 0.5 * (vals[mid - 1] + vals[mid])


def mnav_anchor(observations: Sequence[Mapping[str, float]]) -> tuple[float | None, float]:
    """(median own-history mNAV, log dispersion). The name's own regime, railed."""
    marks = [float(o["mnav"]) for o in observations if o.get("mnav")]
    med = _median(marks)
    sd = _log_sd(marks)
    if med is None:
        return None, sd
    return float(min(max(med, MIN_MNAV_ANCHOR), MAX_MNAV_ANCHOR)), sd


def coin_per_share_growth(observations: Sequence[Mapping[str, float]]) -> float | None:
    """Annualised coin-per-share accretion, measured newest-vs-oldest.

    Positive when issuance funded coin faster than it created shares. This is
    the flywheel as reported, not as claimed.
    """
    series = [float(o["coin_per_share"]) for o in observations if o.get("coin_per_share")]
    if len(series) < 2:
        return None
    newest, oldest = series[0], series[-1]
    if newest <= 0 or oldest <= 0:
        return None
    periods = len(series) - 1
    per_period = (newest / oldest) ** (1.0 / periods) - 1.0
    annual = (1.0 + per_period) ** 4 - 1.0
    if not math.isfinite(annual):
        return None
    return float(min(max(annual, MIN_COIN_PER_SHARE_GROWTH), MAX_COIN_PER_SHARE_GROWTH))


def _faded_accretion_log(g0: float, years: float) -> float:
    """Integral of log(1+g(t)) with accretion decaying toward zero.

    Accretion is funded by a premium the reversion term is closing, so it is not
    held flat to the horizon.
    """
    steps = 240
    dt = max(years, 0.0) / steps
    total = 0.0
    for i in range(steps):
        t = (i + 0.5) * dt
        g_t = g0 * math.exp(-t / ACCRETION_FADE_TAU_YEARS)
        total += math.log1p(max(g_t, -0.85)) * dt
    return total


def nav_cost_of_equity(coin_nav: float, nav_to_common: float) -> float:
    """Hurdle rises with NAV gearing: debt and preferred lever the coin position."""
    if nav_to_common <= 0:
        return MAX_COST_OF_EQUITY
    leverage = coin_nav / nav_to_common
    premium = NAV_LEVERAGE_PREMIUM * max(leverage - 1.0, 0.0)
    return float(min(BASE_COST_OF_EQUITY + premium, MAX_COST_OF_EQUITY))


def nav_leverage(coin_nav: float, nav_to_common: float) -> float:
    """How much a 1% coin move moves NAV per share."""
    if nav_to_common <= 0:
        return 1.0
    return max(coin_nav / nav_to_common, 0.0)


def scenario_sigma(coin_vol: float, leverage: float, mnav_sd: float, years: float) -> float:
    """Horizon dispersion: levered coin vol and premium dispersion, independent."""
    coin_leg = coin_vol * min(leverage, 4.0) * math.sqrt(max(years, 0.25))
    mnav_leg = mnav_sd * math.sqrt(max(years, 0.25))
    return float(min(math.sqrt(coin_leg ** 2 + mnav_leg ** 2), 1.6))


def classify_gearing(
    accretion: float | None,
    mnav_now: float | None,
    anchor: float | None,
) -> str:
    if accretion is not None and accretion < -0.02:
        return GEARING_DILUTION
    if mnav_now is not None and anchor is not None and mnav_now > anchor * 1.25:
        return GEARING_DELEVER
    if accretion is not None and accretion > 0.05:
        return GEARING_ACCRETION
    return GEARING_HOLD


def _pct(val: float) -> str:
    return f"{val * 100:+.0f}%"


def _factors(
    *,
    coin_symbol: str,
    holdings: float,
    coin_spot: float,
    bridge: Mapping[str, float],
    nav_per_share: float,
    mnav_now: float,
    anchor: float | None,
    accretion: float | None,
    leverage: float,
    coin_vol: float,
    revenue_ttm: float | None,
) -> list[dict[str, Any]]:
    """Observed NAV drivers only. Nothing is emitted that was not derived."""
    rows: list[dict[str, Any]] = []

    def add(key: str, label: str, val: float | None, display: str, tone: str) -> None:
        if val is None or not math.isfinite(val):
            return
        rows.append({
            "key": key,
            "label": label,
            "value": round(float(val), 6),
            "display": display,
            "tone": tone,
        })

    coin = coin_symbol.replace("-USD", "")
    add("coin_holdings", f"{coin} held", holdings, f"{holdings:,.0f} {coin}", "flat")
    add("coin_spot", f"{coin} spot", coin_spot, f"${coin_spot:,.0f}", "flat")
    add("coin_nav", "Coin NAV", bridge["coin_nav"], f"${bridge['coin_nav'] / 1e9:,.1f}B", "pos")
    if bridge["preferred"] > 0:
        add("preferred", "Preferred ahead of common", -bridge["preferred"],
            f"-${bridge['preferred'] / 1e9:,.1f}B", "neg")
    if bridge["total_debt"] > 0:
        add("total_debt", "Total debt", -bridge["total_debt"],
            f"-${bridge['total_debt'] / 1e9:,.1f}B", "neg")
    add("nav_per_share", "NAV per share", nav_per_share, f"${nav_per_share:,.2f}", "flat")
    add("mnav", "mNAV (price / NAV)", mnav_now, f"{mnav_now:.2f}x",
        "neg" if mnav_now > 1.35 else "pos" if mnav_now < 1.0 else "flat")
    if anchor is not None:
        add("mnav_anchor", "Own-history mNAV", anchor, f"{anchor:.2f}x", "flat")
    if accretion is not None:
        add("coin_per_share_growth", "Coin per share", accretion, _pct(accretion),
            "pos" if accretion > 0 else "neg")
    add("nav_leverage", "NAV gearing", leverage, f"{leverage:.2f}x",
        "neg" if leverage > 1.5 else "flat")
    add("coin_vol", f"{coin} volatility", coin_vol, _pct(coin_vol), "flat")
    if revenue_ttm:
        add("revenue_ttm", "Software revenue (TTM)", revenue_ttm,
            f"${revenue_ttm / 1e6:,.0f}M", "flat")
    return rows


def _thesis(side: str, coin: str, gearing: str) -> str:
    if side == "bull":
        return (
            f"{coin} holds or rises and the premium re-rates toward the name's own "
            "history; issuance stays accretive to coin per share."
        )
    if side == "bear":
        return (
            f"{coin} falls into levered NAV — debt and preferred sit ahead of common, "
            "so the equity moves more than the coin does — and the premium compresses."
        )
    if gearing == GEARING_DILUTION:
        return (
            f"{coin} flat at spot. Coin per share is falling, so NAV per share erodes "
            "even before the premium moves."
        )
    return (
        f"{coin} flat at spot — the coin is not forecast. What moves the mark is the "
        "premium reverting toward the name's own history, plus measured coin-per-share "
        "accretion."
    )


def empty_forecast(status: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "predicted_price": None,
        "forecast_score": None,
        "gearing_up_towards": None,
        "status": status,
        "label": TREASURY_LABEL,
        "method": TREASURY_METHOD,
        "unmodelable_reason": reason,
        "horizon": None,
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
        "spot_used": None,
        "spot_source": None,
    }


def score_treasury_forecast(
    payload: Mapping[str, Any] | None,
    intel: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """NAV-based mark for a digital-asset treasury, or ``None`` if not applicable.

    ``intel`` must carry the live equity spot and, under ``coin``, the coin spot
    plus the coin price on each reported period end. Missing coin data returns
    an explicit unmodelable state — never a number built on a guessed price.
    """
    if not isinstance(payload, Mapping):
        return None
    periods_per_year = 4 if str(payload.get("period_type") or "quarterly").lower() == "quarterly" else 1
    evidence = evidence or classify_digital_asset_treasury(payload, periods_per_year)
    if not evidence:
        return None

    intel = intel if isinstance(intel, Mapping) else {}
    coin = intel.get("coin") if isinstance(intel.get("coin"), Mapping) else {}
    coin_symbol = str(coin.get("symbol") or "BTC-USD")
    coin_spot = _finite(coin.get("spot"))
    coin_history = coin.get("period_prices")
    coin_history = list(coin_history) if isinstance(coin_history, (list, tuple)) else []
    coin_vol = _finite(coin.get("annual_vol")) or DEFAULT_COIN_VOL

    spot = _finite(intel.get("last_price")) or _finite(intel.get("current_price"))
    if spot is None or spot <= 0:
        return empty_forecast("missing", "no live equity mark")
    if coin_spot is None or coin_spot <= 0 or not coin_history:
        return empty_forecast(
            "missing",
            f"{coin_symbol} price history unavailable — NAV cannot be marked",
        )

    bal = _rows(payload, "balance_sheet")
    inc = _rows(payload, "income_statement")

    carry_series = _series(bal, _COIN_CARRY, strict=True)
    goodwill = _first(_series(bal, _GOODWILL, strict=True)) or 0.0
    if goodwill > 0:
        carry_series = [None if v is None else max(v - goodwill, 0.0) for v in carry_series]

    # The combined line already includes short-term investments; summing it with
    # the STI row would double-count. Only the narrow cash row gets STI added.
    combined = _series(bal, _CASH_COMBINED, strict=True)
    cash_series: list[float | None]
    if any(v is not None for v in combined):
        cash_series = list(combined)
    else:
        cash_core = _series(bal, _CASH, strict=True)
        sti = _series(bal, _STI, strict=True)
        cash_series = []
        for i in range(max(len(cash_core), len(sti))):
            base = _at(cash_core, i)
            extra = _at(sti, i)
            if base is None and extra is None:
                cash_series.append(None)
            else:
                cash_series.append((base or 0.0) + (extra or 0.0))

    debt_series = _series(bal, _TOTAL_DEBT, strict=True)
    if not debt_series:
        lt = _series(bal, _LT_DEBT, strict=True)
        cur = _series(bal, _CUR_DEBT, strict=True)
        debt_series = [
            None if (_at(lt, i) is None and _at(cur, i) is None)
            else (_at(lt, i) or 0.0) + (_at(cur, i) or 0.0)
            for i in range(max(len(lt), len(cur)))
        ]
    preferred_series = _series(bal, _PREFERRED, strict=True)

    ni_series = _series(inc, _NET_INCOME)
    eps_series = _series(inc, _DILUTED_EPS)
    share_series = [
        diluted_shares(_at(ni_series, i), _at(eps_series, i))
        for i in range(max(len(ni_series), len(eps_series)))
    ]
    shares = _first(share_series)
    if shares is None:
        shares = _finite(intel.get("shares_outstanding"))
    if shares is None or shares <= 0:
        return empty_forecast("missing", "diluted share count not recoverable from filings")

    carry_now = _first(carry_series)
    if not carry_now:
        return empty_forecast("missing", "no coin carrying value on the balance sheet")
    coin_px_at_report = _finite(_at(coin_history, 0))
    if coin_px_at_report is None or coin_px_at_report <= 0:
        return empty_forecast("missing", f"no {coin_symbol} price at the reporting date")

    holdings = implied_holdings(carry_now, coin_px_at_report)
    if holdings is None:
        return empty_forecast("missing", "implied holdings not recoverable")

    revenue_ttm = _finite(evidence.get("revenue_ttm"))
    bridge = nav_bridge(
        holdings=holdings,
        coin_spot=coin_spot,
        cash=_first(cash_series),
        revenue_ttm=revenue_ttm,
        total_debt=_first(debt_series),
        preferred=_first(preferred_series),
    )
    nav_to_common = bridge["nav_to_common"]
    if nav_to_common <= 0:
        return empty_forecast(
            "missing",
            "debt and preferred exceed the marked stack — no residual NAV to common",
        )
    nav_per_share = nav_to_common / shares
    mnav_now = spot / nav_per_share

    price_history = intel.get("period_prices")
    price_history = list(price_history) if isinstance(price_history, (list, tuple)) else []
    observations = mnav_observations(
        carry_series=carry_series,
        cash_series=cash_series,
        debt_series=debt_series,
        preferred_series=preferred_series,
        share_series=share_series,
        coin_price_history=coin_history,
        price_history=price_history,
        revenue_ttm=revenue_ttm,
    )
    anchor, mnav_sd = mnav_anchor(observations)
    accretion = coin_per_share_growth(observations)
    years = HORIZON_YEARS

    # Two legs. NAV per share grows only by measured accretion — the coin is held
    # at spot, so no leg here is a crypto forecast. The premium reverts partway
    # toward the name's own median.
    accretion_leg = _faded_accretion_log(accretion, years) if accretion is not None else 0.0
    if anchor is not None and mnav_now > 0:
        mnav_target = mnav_now * (anchor / mnav_now) ** MNAV_REVERSION
        rerate_leg = math.log(mnav_target / mnav_now)
    else:
        mnav_target = mnav_now
        rerate_leg = 0.0

    log_ret = accretion_leg + rerate_leg
    cap = math.log(1.0 + MAX_ANNUALISED_RETURN) * years
    floor = math.log(1.0 + MIN_ANNUALISED_RETURN) * years
    log_ret = float(min(max(log_ret, floor), cap))
    predicted_price = spot * math.exp(log_ret)

    leverage = nav_leverage(bridge["coin_nav"], nav_to_common)
    hurdle = nav_cost_of_equity(bridge["coin_nav"], nav_to_common)
    sigma = scenario_sigma(coin_vol, leverage, mnav_sd, years)
    spread = SCENARIO_Z * sigma
    bear = predicted_price * math.exp(-spread)
    bull = predicted_price * math.exp(spread)
    bear = min(bear, spot * 0.92)
    bull = max(bull, spot * 1.05, predicted_price * 1.05)
    bull = min(bull, spot * (1.0 + MAX_SCENARIO_ANNUALISED) ** years)
    bear = max(bear, spot * (1.0 + MIN_SCENARIO_ANNUALISED) ** years)
    if bear >= predicted_price:
        bear = min(predicted_price * 0.85, spot * 0.90)

    annualized = math.expm1(log_ret / years) if years > 0 else math.expm1(log_ret)
    excess = annualized - hurdle
    gearing = classify_gearing(accretion, mnav_now, anchor)

    # Score: return over the hurdle, tilted by how far the premium sits below the
    # name's own history. A discount to NAV with positive accretion scores well;
    # a large premium funded by dilution does not.
    score = 50.0 + 90.0 * float(min(max(excess, -0.5), 0.5))
    if anchor is not None and mnav_now > 0:
        score += 14.0 * float(min(max(math.log(anchor / mnav_now), -0.6), 0.6))
    if accretion is not None:
        score += 10.0 * float(min(max(accretion, -0.25), 0.35))
    score = float(min(max(score, 0.0), 100.0))

    coin_name = coin_symbol.replace("-USD", "")
    months = int(round(years * 12))
    return {
        "predicted_price": round(predicted_price, 4),
        "forecast_score": round(score, 4),
        "gearing_up_towards": gearing,
        "status": TREASURY_STATUS,
        "label": TREASURY_LABEL,
        "method": TREASURY_METHOD,
        "horizon": f"{months} months",
        "timeframe": f"{months} months",
        "timeframe_months": months,
        "factors": _factors(
            coin_symbol=coin_symbol,
            holdings=holdings,
            coin_spot=coin_spot,
            bridge=bridge,
            nav_per_share=nav_per_share,
            mnav_now=mnav_now,
            anchor=anchor,
            accretion=accretion,
            leverage=leverage,
            coin_vol=coin_vol,
            revenue_ttm=revenue_ttm,
        ),
        "cases": {
            "bear": {"price": round(bear, 4), "label": "Bear",
                     "thesis": _thesis("bear", coin_name, gearing)},
            "base": {"price": round(predicted_price, 4), "label": "Base",
                     "thesis": _thesis("base", coin_name, gearing)},
            "bull": {"price": round(bull, 4), "label": "Bull",
                     "thesis": _thesis("bull", coin_name, gearing)},
        },
        "decision_authorized": False,
        "live_capital_authorized": False,
        "treasury": {
            "coin_symbol": coin_symbol,
            "coin_spot": round(coin_spot, 4),
            "coin_holdings": round(holdings, 4),
            "coin_nav": round(bridge["coin_nav"], 2),
            "cash": round(bridge["cash"], 2),
            "operating_stub": round(bridge["operating_stub"], 2),
            "total_debt": round(bridge["total_debt"], 2),
            "preferred": round(bridge["preferred"], 2),
            "nav_to_common": round(nav_to_common, 2),
            "nav_per_share": round(nav_per_share, 4),
            "diluted_shares": round(shares, 2),
            "mnav_now": round(mnav_now, 4),
            "mnav_anchor": None if anchor is None else round(anchor, 4),
            "mnav_target": round(mnav_target, 4),
            "mnav_log_sd": round(mnav_sd, 4),
            "mnav_observations": len(observations),
            "coin_per_share": round(holdings / shares, 8),
            "coin_per_share_growth": None if accretion is None else round(accretion, 6),
            "nav_leverage": round(leverage, 4),
            "coin_annual_vol": round(coin_vol, 4),
            "coin_price_forecast": "none — coin held at spot (martingale)",
            "evidence": dict(evidence),
        },
        "implied_log_return": round(log_ret, 6),
        "accretion_log_return": round(accretion_leg, 6),
        "rerate_log_return": round(rerate_leg, 6),
        "cost_of_equity": round(hurdle, 6),
        "annualized_return": round(annualized, 6),
        "excess_annualized_return": round(excess, 6),
        "expected_return": round(math.expm1(log_ret), 6),
        "scenario_sigma": round(sigma, 6),
        "spot_used": round(spot, 4),
        "spot_source": intel.get("spot_source"),
    }
