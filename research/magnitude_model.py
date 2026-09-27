"""Conditional magnitude model: how big is the rest of this session likely to be?

Why a magnitude model and not a direction model
-----------------------------------------------
The 2026-09-01 audit (``docs/audits/2026-09-01-vwap-orderflow-evaluation.md``)
tested direction hard and found nothing: session-VWAP distance, crosses and
acceptance carry no measurable directional information at 1h resolution across
512k observations, in or out of sample, in any volatility or trend regime.

The same study found one robust, monotonic relationship -- time-of-day
normalised volume forecasts the *size* of the remaining session move (~44bp at
normal slot volume rising to ~96bp above 3x) with no directional content.

This module models that quantity, and only that quantity. It deliberately
emits no directional opinion, because the evidence does not support one. Its
job in the wider system is to answer:

* how wide should a barrier / stop / target be right now?
* is the expected move large enough to clear costs -- or is this a NO TRADE?

A NO TRADE answer is a successful output, not a failure.

Validation discipline
---------------------
Same rules the audit demanded of the VPA harness, because the failure mode is
identical:

* **Grouped by session.** Every symbol on one date shares that date's market
  move, so rows are nowhere near independent. Folds split on whole dates and
  confidence intervals bootstrap whole dates, never rows. Pooled row-count
  intervals would be several times too narrow.
* **Purged and embargoed.** A training fold may not contain any observation
  whose forward window overlaps the test fold.
* **Rolling origins.** One split is one draw. A result that survives one origin
  and vanishes at the others is noise, and is reported as such.
* **Skill is measured against a real baseline** -- the trailing unconditional
  quantile, not zero. Beating "no model at all" is the bar.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from research.session_features import (
    SessionFeatureConfig,
    build_features,
    forward_targets,
)

EDGE_ROOT = Path(__file__).resolve().parents[1]
HOURLY_DIR = EDGE_ROOT / "data" / "1h"

#: Inputs to the magnitude model. Every one is causal (see session_features)
#: and none of them encodes direction -- sign-carrying columns are excluded on
#: purpose so the model cannot smuggle in a directional bet.
MAGNITUDE_FEATURES = (
    "log_rvol_slot",
    "cum_rvol_session",
    "range_ratio",
    "realized_vol",
    "abs_vwap_z",
    "abs_vwap_dist_bp",
    "slot",
    "bars_left",
)

DEFAULT_QUANTILES = (0.25, 0.5, 0.75, 0.9)


@dataclass(frozen=True)
class MagnitudeConfig:
    """Model and validation geometry."""

    quantiles: tuple[float, ...] = DEFAULT_QUANTILES
    #: Rolling evaluation origins. One split is one draw.
    n_origins: int = 4
    #: Fraction of dates in the first training window.
    initial_train: float = 0.5
    #: Sessions purged between train and test on each side of the boundary.
    embargo_sessions: int = 2
    #: Bootstrap replicates for session-clustered intervals.
    bootstrap_reps: int = 400
    seed: int = 7
    #: Gradient-boosting geometry: deliberately small. This is a
    #: low-signal-to-noise financial problem and a deep forest would memorise
    #: sessions rather than learn the volume-to-magnitude relationship.
    n_estimators: int = 200
    max_depth: int = 3
    learning_rate: float = 0.05
    min_samples_leaf: int = 200
    subsample: float = 0.8
    #: Round-trip cost in bp used by the no-trade rule.
    cost_bp: float = 8.0
    #: Expected move must clear this multiple of round-trip cost to trade.
    cost_multiple: float = 2.0

    def __post_init__(self) -> None:
        if not self.quantiles:
            raise ValueError("at least one quantile is required")
        if not all(0.0 < q < 1.0 for q in self.quantiles):
            raise ValueError("quantiles must lie strictly inside (0, 1)")
        if self.n_origins < 1:
            raise ValueError("n_origins must be >= 1")
        if not 0.0 < self.initial_train < 1.0:
            raise ValueError("initial_train must lie in (0, 1)")
        if self.embargo_sessions < 0:
            raise ValueError("embargo_sessions must be >= 0")
        if self.cost_bp < 0 or self.cost_multiple <= 0:
            raise ValueError("cost settings must be non-negative / positive")


# ------------------------------------------------------------------ panel --

def build_panel(
    bars_by_symbol: dict[str, pd.DataFrame],
    cfg: SessionFeatureConfig | None = None,
) -> pd.DataFrame:
    """Feature + target panel across symbols. Pure: callers do the I/O.

    The returned frame carries one row per (symbol, bar) with a ``session``
    column that every fold and every bootstrap groups on.
    """
    cfg = cfg or SessionFeatureConfig()
    frames = []
    for sym, bars in bars_by_symbol.items():
        if bars is None or bars.empty:
            continue
        feats = build_features(bars, cfg, symbol=sym)
        if feats.empty:
            continue
        tgts = forward_targets(bars, cfg)
        joined = feats.join(tgts, how="inner")
        frames.append(joined)
    if not frames:
        return pd.DataFrame()

    panel = pd.concat(frames).sort_index()
    # Magnitude features: strip the sign so the model cannot learn direction
    # through a back door, and give it the one bit of session geometry that
    # obviously matters -- how much session is left to move in.
    panel["abs_vwap_z"] = panel["vwap_z"].abs()
    panel["abs_vwap_dist_bp"] = panel["vwap_dist_bp"].abs()
    bars_per_session = int(panel["slot"].max()) + 1
    panel["bars_left"] = bars_per_session - 1 - panel["slot"]
    return panel


def load_hourly_panel(
    symbols: Sequence[str],
    hourly_dir: Path | None = None,
    cfg: SessionFeatureConfig | None = None,
    max_bars: int | None = None,
) -> pd.DataFrame:
    """Read local 1h parquet for ``symbols`` and build the panel."""
    hourly_dir = Path(hourly_dir or HOURLY_DIR)
    bars: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        p = hourly_dir / f"{sym}.parquet"
        if not p.is_file():
            continue
        df = pd.read_parquet(p)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        if max_bars:
            df = df.tail(max_bars)
        bars[sym] = df
    return build_panel(bars, cfg)


# ------------------------------------------------------------- estimators --

class UnconditionalQuantile:
    """Baseline: the trailing unconditional quantile, no features at all.

    This is the number a model has to beat. Reporting skill against zero, or
    against a coin flip, would flatter any model at all.
    """

    def __init__(self, quantiles: Sequence[float]):
        self.quantiles = tuple(quantiles)
        self._q: dict[float, float] = {}

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "UnconditionalQuantile":
        for q in self.quantiles:
            self._q[q] = float(np.quantile(y.to_numpy(dtype=float), q))
        return self

    def predict(self, X: pd.DataFrame) -> dict[float, np.ndarray]:
        return {q: np.full(len(X), v) for q, v in self._q.items()}


class GradientQuantile:
    """Small gradient-boosted quantile regressors, one per quantile."""

    def __init__(self, cfg: MagnitudeConfig):
        self.cfg = cfg
        self._models: dict[float, object] = {}

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "GradientQuantile":
        from sklearn.ensemble import GradientBoostingRegressor

        for q in self.cfg.quantiles:
            m = GradientBoostingRegressor(
                loss="quantile",
                alpha=q,
                n_estimators=self.cfg.n_estimators,
                max_depth=self.cfg.max_depth,
                learning_rate=self.cfg.learning_rate,
                min_samples_leaf=self.cfg.min_samples_leaf,
                subsample=self.cfg.subsample,
                random_state=self.cfg.seed,
            )
            m.fit(X.to_numpy(dtype=float), y.to_numpy(dtype=float))
            self._models[q] = m
        return self

    def predict(self, X: pd.DataFrame) -> dict[float, np.ndarray]:
        arr = X.to_numpy(dtype=float)
        return {q: m.predict(arr) for q, m in self._models.items()}

    def feature_importance(self, columns: Sequence[str], q: float = 0.5) -> dict[str, float]:
        m = self._models.get(q)
        if m is None:
            return {}
        return {c: float(v) for c, v in zip(columns, m.feature_importances_)}


# ---------------------------------------------------------------- metrics --

def pinball_loss(y: np.ndarray, pred: np.ndarray, q: float) -> float:
    """Mean pinball (quantile) loss. Lower is better."""
    d = y - pred
    return float(np.mean(np.maximum(q * d, (q - 1.0) * d)))


def cluster_bootstrap_mean(
    values: np.ndarray,
    groups: np.ndarray,
    reps: int = 400,
    seed: int = 7,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """Mean of ``values`` with a CI that resamples whole ``groups``.

    Rows within a session are not independent observations of the market, so a
    row-level interval understates uncertainty badly. This resamples sessions.
    """
    v = np.asarray(values, dtype=float)
    g = np.asarray(groups)
    ok = np.isfinite(v)
    v, g = v[ok], g[ok]
    if v.size == 0:
        return (float("nan"),) * 3

    uniq, inverse = np.unique(g, return_inverse=True)
    order = np.argsort(inverse, kind="stable")
    sorted_inv = inverse[order]
    sorted_v = v[order]
    bounds = np.searchsorted(sorted_inv, np.arange(len(uniq) + 1))
    sums = np.add.reduceat(sorted_v, bounds[:-1]) if len(uniq) else np.array([])
    counts = np.diff(bounds).astype(float)

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uniq), size=(reps, len(uniq)))
    means = sums[idx].sum(axis=1) / np.maximum(counts[idx].sum(axis=1), 1.0)
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(v.mean()), float(lo), float(hi)


# ------------------------------------------------------------ validation ---

def rolling_origins(
    sessions: np.ndarray,
    cfg: MagnitudeConfig,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding-window (train_sessions, test_sessions) splits with an embargo.

    Splitting on sessions rather than rows is what makes the purge real: an
    embargo measured in pooled rows would, with dozens of symbols per date,
    amount to a fraction of a single trading day.
    """
    uniq = np.array(sorted(pd.unique(sessions)))
    n = len(uniq)
    if n < 10:
        return []
    start = int(n * cfg.initial_train)
    if start < 2 or start >= n:
        return []

    out = []
    remaining = n - start
    step = max(1, remaining // cfg.n_origins)
    for i in range(cfg.n_origins):
        train_end = start + i * step
        test_start = train_end + cfg.embargo_sessions
        test_end = min(n, test_start + step)
        if test_start >= n or test_end <= test_start or train_end < 2:
            break
        out.append((uniq[:train_end], uniq[test_start:test_end]))
    return out


def evaluate(
    panel: pd.DataFrame,
    cfg: MagnitudeConfig | None = None,
    target: str = "abs_eod_bp",
    features: Sequence[str] = MAGNITUDE_FEATURES,
) -> dict:
    """Rolling-origin, session-purged evaluation of the magnitude model.

    Returns per-origin and pooled results. Every headline figure carries a
    session-clustered interval; a skill number without one is not evidence.
    """
    cfg = cfg or MagnitudeConfig()
    cols = [c for c in features if c in panel.columns]
    needed = cols + [target, "session"]
    data = panel.dropna(subset=needed).copy()
    if data.empty:
        return {"status": "empty_panel", "reason": "no complete rows after dropna"}

    splits = rolling_origins(data["session"].to_numpy(), cfg)
    if not splits:
        return {"status": "insufficient_sessions", "sessions": int(data["session"].nunique())}

    origins = []
    pooled_rows = []
    for i, (train_sessions, test_sessions) in enumerate(splits):
        tr = data[data["session"].isin(train_sessions)]
        te = data[data["session"].isin(test_sessions)]
        if len(tr) < 500 or len(te) < 100:
            continue

        Xtr, ytr = tr[cols], tr[target]
        Xte, yte = te[cols], te[target]

        base = UnconditionalQuantile(cfg.quantiles).fit(Xtr, ytr)
        model = GradientQuantile(cfg).fit(Xtr, ytr)
        p_base = base.predict(Xte)
        p_model = model.predict(Xte)

        y = yte.to_numpy(dtype=float)
        per_q = {}
        for q in cfg.quantiles:
            lb = pinball_loss(y, p_base[q], q)
            lm = pinball_loss(y, p_model[q], q)
            per_q[str(q)] = {
                "pinball_baseline": round(lb, 4),
                "pinball_model": round(lm, 4),
                # Skill score: fraction of the baseline's loss removed.
                "skill_vs_baseline": round((lb - lm) / lb, 4) if lb > 0 else None,
                "coverage": round(float(np.mean(y <= p_model[q])), 4),
                "coverage_target": q,
            }

        med = p_model[0.5] if 0.5 in p_model else p_model[cfg.quantiles[0]]
        rank = float(pd.Series(med).corr(pd.Series(y), method="spearman"))
        pooled_rows.append(
            pd.DataFrame(
                {
                    "session": te["session"].to_numpy(),
                    "y": y,
                    "pred": med,
                    "base": p_base[0.5] if 0.5 in p_base else p_base[cfg.quantiles[0]],
                    "origin": i,
                }
            )
        )
        origins.append(
            {
                "origin": i,
                "train_sessions": int(len(train_sessions)),
                "test_sessions": int(len(test_sessions)),
                "n_train": int(len(tr)),
                "n_test": int(len(te)),
                "train_end": str(pd.Timestamp(train_sessions[-1]).date()),
                "test_start": str(pd.Timestamp(test_sessions[0]).date()),
                "test_end": str(pd.Timestamp(test_sessions[-1]).date()),
                "spearman_pred_vs_realised": round(rank, 4),
                "by_quantile": per_q,
                "feature_importance": {
                    k: round(v, 4)
                    for k, v in sorted(
                        model.feature_importance(cols).items(), key=lambda kv: -kv[1]
                    )
                },
            }
        )

    if not origins:
        return {"status": "no_usable_origins", "splits": len(splits)}

    allrows = pd.concat(pooled_rows)
    skills = [
        o["by_quantile"][str(q)]["skill_vs_baseline"]
        for o in origins
        for q in cfg.quantiles
        if o["by_quantile"][str(q)]["skill_vs_baseline"] is not None
    ]
    med_skills = [
        o["by_quantile"]["0.5"]["skill_vs_baseline"]
        for o in origins
        if "0.5" in o["by_quantile"] and o["by_quantile"]["0.5"]["skill_vs_baseline"] is not None
    ]
    ranks = [o["spearman_pred_vs_realised"] for o in origins]

    err_model = np.abs(allrows["y"] - allrows["pred"]).to_numpy()
    err_base = np.abs(allrows["y"] - allrows["base"]).to_numpy()
    diff = err_base - err_model  # positive => model closer than baseline
    d_mean, d_lo, d_hi = cluster_bootstrap_mean(
        diff, allrows["session"].to_numpy(), cfg.bootstrap_reps, cfg.seed
    )

    return {
        "status": "evaluated",
        "target": target,
        "features": cols,
        "n_origins": len(origins),
        "n_test_rows": int(len(allrows)),
        "n_test_sessions": int(allrows["session"].nunique()),
        "origins": origins,
        "pooled": {
            "median_quantile_skill_by_origin": med_skills,
            "median_quantile_skill_min": round(min(med_skills), 4) if med_skills else None,
            "all_quantile_skill_min": round(min(skills), 4) if skills else None,
            "spearman_by_origin": ranks,
            "spearman_min": round(min(ranks), 4) if ranks else None,
            "abs_error_improvement_bp": round(d_mean, 3),
            "abs_error_improvement_ci": [round(d_lo, 3), round(d_hi, 3)],
            "improvement_ci_excludes_zero": bool(d_lo > 0),
        },
        "verdict": _verdict(med_skills, ranks, d_lo),
    }


def _verdict(med_skills: list[float], ranks: list[float], d_lo: float) -> dict:
    """Consistency across origins, not a single flattering number."""
    notes: list[str] = []
    if not med_skills:
        return {"call": "inconclusive", "notes": ["no origin produced a median-quantile skill score"]}

    positive_everywhere = all(s > 0 for s in med_skills)
    rank_everywhere = all(r > 0 for r in ranks)
    ci_clear = bool(d_lo > 0)

    if positive_everywhere and rank_everywhere and ci_clear:
        call = "useful"
        notes.append(
            "The model beats the trailing unconditional quantile at every origin, its "
            "ranking of magnitude is positive at every origin, and the session-clustered "
            "interval on the absolute-error improvement excludes zero."
        )
    elif positive_everywhere and ci_clear:
        call = "useful_but_check"
        notes.append("Skill is positive at every origin but the rank correlation is not.")
    elif not positive_everywhere:
        call = "unstable"
        notes.append(
            f"Skill is not positive at every origin ({med_skills}); a result that appears at "
            "one origin and vanishes at another is noise."
        )
    else:
        call = "inconclusive"
        notes.append("The session-clustered interval on the improvement includes zero.")

    notes.append(
        "This model forecasts move SIZE only. It carries no directional information and "
        "must never be read as one."
    )
    return {"call": call, "notes": notes}


# ----------------------------------------------------------- decision use --

def no_trade_filter(
    predicted_move_bp: Iterable[float],
    cfg: MagnitudeConfig | None = None,
) -> np.ndarray:
    """True where the expected move does not clear the cost hurdle.

    The decision rule the audit asks for: a NO TRADE is a valid and desirable
    output. Expected move must exceed ``cost_multiple`` x round-trip cost
    before a directional decision is even worth considering -- and since this
    repo has no validated directional edge, this filter is currently the only
    part of the decision chain resting on evidence.
    """
    cfg = cfg or MagnitudeConfig()
    hurdle = cfg.cost_bp * cfg.cost_multiple
    pred = np.asarray(list(predicted_move_bp), dtype=float)
    return ~(pred > hurdle)


def evaluate_no_trade_filter(
    panel: pd.DataFrame,
    cfg: MagnitudeConfig | None = None,
    target: str = "abs_eod_bp",
    features: Sequence[str] = MAGNITUDE_FEATURES,
) -> dict:
    """Does the filter actually separate small moves from large ones OOS?

    Fits on the first training window and reports, on held-out sessions, the
    realised magnitude of the bars it would have vetoed versus those it would
    have let through. If the vetoed bars are not meaningfully quieter, the
    filter is decoration.
    """
    cfg = cfg or MagnitudeConfig()
    cols = [c for c in features if c in panel.columns]
    data = panel.dropna(subset=cols + [target, "session"]).copy()
    splits = rolling_origins(data["session"].to_numpy(), cfg)
    if not splits:
        return {"status": "insufficient_sessions"}

    train_sessions, test_sessions = splits[0]
    tr = data[data["session"].isin(train_sessions)]
    te = data[data["session"].isin(test_sessions)]
    if len(tr) < 500 or len(te) < 100:
        return {"status": "insufficient_rows"}

    model = GradientQuantile(cfg).fit(tr[cols], tr[target])
    pred = model.predict(te[cols])
    med = pred[0.5] if 0.5 in pred else pred[cfg.quantiles[0]]
    vetoed = no_trade_filter(med, cfg)

    y = te[target].to_numpy(dtype=float)
    sess = te["session"].to_numpy()
    v_mean, v_lo, v_hi = cluster_bootstrap_mean(y[vetoed], sess[vetoed], cfg.bootstrap_reps, cfg.seed)
    t_mean, t_lo, t_hi = cluster_bootstrap_mean(y[~vetoed], sess[~vetoed], cfg.bootstrap_reps, cfg.seed)

    return {
        "status": "evaluated",
        "hurdle_bp": cfg.cost_bp * cfg.cost_multiple,
        "n_test": int(len(te)),
        "vetoed_share": round(float(vetoed.mean()), 4),
        "vetoed_realised_abs_move_bp": round(v_mean, 2),
        "vetoed_ci": [round(v_lo, 2), round(v_hi, 2)],
        "allowed_realised_abs_move_bp": round(t_mean, 2),
        "allowed_ci": [round(t_lo, 2), round(t_hi, 2)],
        "separation_bp": round(t_mean - v_mean, 2),
        "separation_is_real": bool(v_hi < t_lo),
    }


# --------------------------------------------------------------------- cli --

def _universe(limit: int, hourly_dir: Path) -> list[str]:
    forced = ["SPY", "QQQ", "IWM"]
    out = [s for s in forced if (hourly_dir / f"{s}.parquet").is_file()]
    for p in sorted(hourly_dir.glob("*.parquet")):
        if len(out) >= limit:
            break
        if p.stem not in out:
            out.append(p.stem)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", type=int, default=60)
    ap.add_argument("--max-bars", type=int, default=None)
    ap.add_argument("--cost-bp", type=float, default=8.0)
    ap.add_argument("--origins", type=int, default=4)
    ap.add_argument("--json", type=str, default=None)
    args = ap.parse_args()

    cfg = MagnitudeConfig(n_origins=args.origins, cost_bp=args.cost_bp)
    syms = _universe(args.symbols, HOURLY_DIR)
    print(f"loading {len(syms)} symbols from {HOURLY_DIR} ...")
    panel = load_hourly_panel(syms, max_bars=args.max_bars)
    if panel.empty:
        print("no panel could be built")
        return
    print(f"panel: {len(panel):,} rows, {panel['session'].nunique():,} sessions, "
          f"{panel['symbol'].nunique()} symbols")

    res = evaluate(panel, cfg)
    print(f"\nstatus: {res.get('status')}")
    if res.get("status") == "evaluated":
        for o in res["origins"]:
            q50 = o["by_quantile"].get("0.5", {})
            print(f"  origin {o['origin']}: test {o['test_start']}..{o['test_end']} "
                  f"n={o['n_test']:,}  q50 skill {q50.get('skill_vs_baseline')}  "
                  f"spearman {o['spearman_pred_vs_realised']}")
        p = res["pooled"]
        print(f"\n  abs-error improvement {p['abs_error_improvement_bp']}bp "
              f"CI{p['abs_error_improvement_ci']}  excludes zero: {p['improvement_ci_excludes_zero']}")
        print(f"  verdict: {res['verdict']['call']}")
        for n in res["verdict"]["notes"]:
            print(f"    - {n}")
        top = res["origins"][-1]["feature_importance"]
        print("  top features:", list(top.items())[:5])

    flt = evaluate_no_trade_filter(panel, cfg)
    print(f"\nno-trade filter: {flt.get('status')}")
    if flt.get("status") == "evaluated":
        print(f"  hurdle {flt['hurdle_bp']}bp; vetoes {flt['vetoed_share']:.1%} of bars")
        print(f"  vetoed bars realised {flt['vetoed_realised_abs_move_bp']}bp CI{flt['vetoed_ci']}")
        print(f"  allowed bars realised {flt['allowed_realised_abs_move_bp']}bp CI{flt['allowed_ci']}")
        print(f"  separation {flt['separation_bp']}bp; real: {flt['separation_is_real']}")

    if args.json:
        Path(args.json).write_text(json.dumps({"evaluation": res, "no_trade_filter": flt},
                                              default=str, indent=1))
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
