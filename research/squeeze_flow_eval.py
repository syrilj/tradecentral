"""Train vs out-of-sample evaluation of shipped squeeze + flow-shift scores.

Uses the repo's expanding / purged walk-forward primitives so a train origin
cannot see an OOS label. Thresholds that define a "fire" for hit-rate are
fit on the train fold only and applied once to OOS.

The directional score is the shipped theory squeeze when a chain is
available, otherwise the post-shift flow imbalance from
``current_flow_after_shift``. Historical option chains have no aggressor, so
the flow term is a causal bar signed-volume proxy — never reconstructed
tape.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from edge.daily_plays.gex_core import compute_theory_squeeze
from edge.research.flow_shift import (
    FlowShiftConfig,
    current_flow_after_shift,
    signed_observations_from_bars,
    squeeze_with_shifted_flow,
)
from edge.research.panel_splits import expanding_panel_walk_forward_splits
from edge.research.squeeze_validation import (
    _chain_to_theory_rows,
    _forward_returns,
    _hit,
    _hit_rate,
    _load_price,
    _rank_ic,
)


EDGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = EDGE_ROOT / "runs" / "squeeze_flow_eval"
DEFAULT_FIXTURE = EDGE_ROOT / "tests" / "research" / "fixtures" / "squeeze_flow_eval_panel.parquet"
FIRE_THRESHOLD_GRID = (0.0, 0.05, 0.10, 0.20, 0.35, 0.50)

# `evaluate_train_oos` below always fits/scores against the *next-session*
# forward return -- `fit_fire_threshold` and `summarize_split` both read this
# one column, never a caller-selectable one. The walk-forward purge/embargo
# geometry fed to the splitter has to protect exactly that column's forward
# window: passing a larger `cfg.label_horizon` (e.g. 5, sized for a `fwd_5d`
# label nothing here scores) doesn't make a 1-day score any safer, it just
# burns extra trailing dates the splitter never needed to protect from
# leakage -- which is exactly what starved fold formation in production (a
# panel with 8 usable dates and `label_horizon=5` cannot form a single fold;
# see `_min_dates_required`). `cfg.label_horizon` keeps its own meaning
# elsewhere in this module (e.g. the `label_end` fallback below and in
# `build_panel_from_local_bars`); it is intentionally NOT threaded into the
# splitter call in `evaluate_train_oos`. Callers who want a wider protective
# margin than a 1-day label strictly requires should raise `embargo_dates`
# instead, which exists for exactly that purpose (see splits.py docstring).
SCORE_FWD_COL = "fwd_1d"
SCORE_LABEL_HORIZON = 1


@dataclass(frozen=True)
class SqueezeFlowEvalConfig:
    panel_path: str | None = None
    out_dir: str = str(DEFAULT_OUT)
    price_dirs: tuple[str, ...] = (
        str(EDGE_ROOT / "data" / "1d"),
        str(EDGE_ROOT / "data" / "1d_wide"),
    )
    hourly_dir: str = str(EDGE_ROOT / "data" / "1h")
    chain_root: str = str(EDGE_ROOT / "data" / "option_chains")
    symbols: tuple[str, ...] = ("SPY", "QQQ", "AAPL", "NVDA", "TSLA")
    max_dates: int = 80
    label_horizon: int = 5
    initial_train_dates: int = 20
    validation_dates: int = 12
    embargo_dates: int = 1
    step_dates: int | None = 12
    include_partial_final: bool = True
    min_partial_validation_dates: int = 6
    score_threshold: float = 0.0
    min_threshold_n: int = 8
    forward_horizons: tuple[int, ...] = (1, 3, 5)
    risk_free_rate: float = 0.045
    max_dte: int = 45
    min_open_interest: int = 50
    score_scale: float = 40.0
    use_fixture: bool = True


def _fuel_fixture_chain() -> list[dict[str, Any]]:
    return [
        {"right": "call", "strike": 101, "gamma": 0.08, "open_interest": 50_000, "multiplier": 100, "dte": 2},
        {"right": "put", "strike": 99, "gamma": 0.02, "open_interest": 5_000, "multiplier": 100, "dte": 2},
    ]


def make_deterministic_panel(
    *,
    n_dates: int = 48,
    symbols: Sequence[str] = ("AAA", "BBB", "CCC", "DDD"),
    seed: int = 7,
) -> pd.DataFrame:
    """Checked-in / test fixture: real detector + shipped squeeze, no I/O."""
    dates = pd.bdate_range("2024-01-02", periods=n_dates)
    rng = np.random.default_rng(seed)
    chain = _fuel_fixture_chain()
    rows: list[dict[str, Any]] = []
    for i, asof in enumerate(dates):
        for j, symbol in enumerate(symbols):
            tilt = 0.35 + 0.05 * ((i + j) % 7)
            if j % 2 == 0:
                values = [tilt] * 10
                if i >= n_dates // 2:
                    values = [tilt] * 8 + [-tilt * (0.8 + 0.05 * (i % 5))] * (4 + min(8, i - n_dates // 2))
            else:
                values = [-tilt] * 12
                if i >= (n_dates // 2 + 4):
                    values = [-tilt] * 8 + [tilt * (0.7 + 0.04 * (j + 1))] * 8
            last_age = 0.0 if (i + j) % 9 else 8.0
            readout = current_flow_after_shift(
                values, last_age=last_age, max_fresh_age=2.0,
            )
            theory = squeeze_with_shifted_flow(
                chain_rows=chain,
                spot=100.0,
                adv_notional=50_000_000.0,
                momentum=0.02 * float(np.sign(readout.effective_imbalance) or 0.0),
                signed_flow=values,
                last_age=last_age,
                max_fresh_age=2.0,
            )
            noise = float(rng.normal(0.0, 0.012))
            fwd = 0.003 * float(readout.signed_imbalance) + noise
            rows.append({
                "symbol": symbol,
                "asof": pd.Timestamp(asof).normalize(),
                "flow_score": float(readout.effective_imbalance),
                "theory_score": float(theory["squeeze_score"]),
                "eval_score": float(theory["squeeze_score"]),
                "fwd_1d": fwd,
                "fwd_3d": fwd * 1.15,
                "fwd_5d": fwd * 1.35,
                "label_end": pd.Timestamp(asof).normalize() + pd.tseries.offsets.BDay(5),
                "confidence": float(readout.confidence),
                "confidence_band": readout.confidence_band,
                "n_post_shift": int(readout.n_post_shift),
                "shifted": bool(readout.shifted),
                "last_shift_index": readout.last_shift_index,
                "source": "deterministic_fixture",
            })
    return pd.DataFrame.from_records(rows)


def _normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        for col in ("Date", "date", "timestamp"):
            if col in df.columns:
                df = df.set_index(col)
                break
    df.index = pd.to_datetime(df.index).tz_localize(None)
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for want in ("open", "high", "low", "close", "volume"):
        if want in cols:
            rename[cols[want]] = want
    return df.rename(columns=rename).sort_index()


def _load_hourly(symbol: str, hourly_dir: Path, asof: pd.Timestamp) -> pd.DataFrame | None:
    path = hourly_dir / f"{symbol.upper()}.parquet"
    if not path.exists():
        return None
    df = _normalize_bars(pd.read_parquet(path))
    end = pd.Timestamp(asof).normalize() + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    hist = df.loc[df.index <= end]
    need = ("open", "high", "low", "close", "volume")
    if hist.empty or any(col not in hist.columns for col in need):
        return None
    return hist


def _causal_bar_flow(
    prices: pd.DataFrame,
    asof: pd.Timestamp,
    *,
    hourly: pd.DataFrame | None = None,
    cfg: FlowShiftConfig | None = None,
) -> tuple[list[float], Any]:
    hist = prices.loc[prices.index <= asof]
    bars = hourly if hourly is not None and len(hourly) >= 8 else hist
    if bars.empty or any(col not in bars.columns for col in ("open", "high", "low", "close", "volume")):
        return [], None
    try:
        obs = signed_observations_from_bars(bars)
    except (KeyError, ValueError):
        return [], None
    if not obs:
        return [], None
    last_bar = pd.Timestamp(bars.index.max())
    age_days = float((pd.Timestamp(asof).normalize() - last_bar.normalize()).days)
    readout = current_flow_after_shift(obs, cfg=cfg, last_age=age_days, max_fresh_age=2.0)
    return obs, readout


def _chain_for_symbol_date(chain_root: Path, symbol: str, asof: pd.Timestamp) -> pd.DataFrame | None:
    folder = chain_root / f"date={asof.strftime('%Y-%m-%d')}"
    path = folder / f"{symbol.upper()}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None
    return None if df.empty else df


def build_panel_from_local_bars(cfg: SqueezeFlowEvalConfig) -> pd.DataFrame:
    """Causal bar-proxy panel for symbols that have local 1d / 1h history."""
    price_dirs = [Path(p) for p in cfg.price_dirs]
    hourly_dir = Path(cfg.hourly_dir)
    chain_root = Path(cfg.chain_root)
    rows: list[dict[str, Any]] = []
    for symbol in cfg.symbols:
        prices = _load_price(symbol, price_dirs)
        if prices is None or prices.empty:
            continue
        prices = prices.sort_index()
        dates = prices.index.normalize().unique().sort_values()
        dates = dates[-int(cfg.max_dates):] if cfg.max_dates else dates
        for asof in dates:
            asof_ts = pd.Timestamp(asof).normalize()
            hourly = _load_hourly(symbol, hourly_dir, asof_ts)
            obs, readout = _causal_bar_flow(prices, asof_ts, hourly=hourly)
            if readout is None:
                continue
            hist = prices.loc[prices.index <= asof_ts]
            if len(hist) < 6:
                continue
            close = hist["close"].astype(float)
            mom_n = min(5, len(close) - 1)
            momentum = float(close.iloc[-1] / close.iloc[-(mom_n + 1)] - 1.0)
            vol = hist["volume"].astype(float) if "volume" in hist.columns else pd.Series(0.0, index=hist.index)
            dollar = (close * vol).replace([np.inf, -np.inf], np.nan).dropna()
            adv = float(dollar.tail(20).mean()) if len(dollar) else 0.0
            spot = float(close.iloc[-1])
            theory_score = None
            chain = _chain_for_symbol_date(chain_root, symbol, asof_ts)
            if chain is not None:
                theory_rows, _, _ = _chain_to_theory_rows(
                    chain,
                    spot=spot,
                    rate=cfg.risk_free_rate,
                    max_dte=cfg.max_dte,
                    min_oi=cfg.min_open_interest,
                )
                if theory_rows:
                    theory = compute_theory_squeeze(
                        chain_rows=theory_rows,
                        spot=spot,
                        adv_notional=adv,
                        call_imbalance=readout.effective_imbalance,
                        momentum=momentum,
                        score_scale=cfg.score_scale,
                    )
                    theory_score = float(theory["squeeze_score"])
            fwd = _forward_returns(prices, asof=asof_ts, horizons=cfg.forward_horizons)
            eval_score = theory_score if theory_score is not None else float(readout.effective_imbalance)
            rows.append({
                "symbol": symbol,
                "asof": asof_ts,
                "flow_score": float(readout.effective_imbalance),
                "theory_score": theory_score,
                "eval_score": float(eval_score),
                **{k: v for k, v in fwd.items() if k != "signal_session"},
                "label_end": asof_ts + pd.tseries.offsets.BDay(cfg.label_horizon),
                "confidence": float(readout.confidence),
                "confidence_band": readout.confidence_band,
                "n_post_shift": int(readout.n_post_shift),
                "shifted": bool(readout.shifted),
                "last_shift_index": readout.last_shift_index,
                "source": "hourly_bars" if hourly is not None and len(hourly) >= 8 else "daily_bars",
            })
    return pd.DataFrame.from_records(rows)


def load_panel(cfg: SqueezeFlowEvalConfig) -> pd.DataFrame:
    if cfg.panel_path:
        path = Path(cfg.panel_path)
        if not path.exists():
            raise FileNotFoundError(path)
        if path.suffix == ".json":
            return pd.read_json(path)
        return pd.read_parquet(path)
    if cfg.use_fixture:
        if DEFAULT_FIXTURE.exists():
            return pd.read_parquet(DEFAULT_FIXTURE)
        return make_deterministic_panel()
    return build_panel_from_local_bars(cfg)


def _accuracy_block(
    scores: pd.Series,
    rets: pd.Series,
    *,
    threshold: float,
) -> dict[str, Any]:
    hits = []
    for score, fwd in zip(scores.tolist(), rets.tolist()):
        hits.append(_hit(score, fwd, threshold))
    hit_stats = _hit_rate(pd.Series(hits, dtype=object))
    s = pd.to_numeric(scores, errors="coerce")
    r = pd.to_numeric(rets, errors="coerce")
    mask = s.notna() & r.notna()
    ic = None
    if int(mask.sum()) >= 8 and s[mask].nunique() >= 2 and r[mask].nunique() >= 2:
        ic = _rank_ic(s, r)
    return {
        "n": int(hit_stats["n"]),
        "hits": int(hit_stats["hits"]),
        "hit_rate": hit_stats["hit_rate"],
        "rank_ic": ic,
        "threshold": float(threshold),
    }


def fit_fire_threshold(
    scores: pd.Series,
    rets: pd.Series,
    *,
    grid: Sequence[float] = FIRE_THRESHOLD_GRID,
    min_n: int = 8,
) -> float:
    """Pick a fire threshold on train only. Never looks at OOS labels."""
    best_thr = 0.0
    best_hr = -1.0
    best_n = -1
    for thr in grid:
        block = _accuracy_block(scores, rets, threshold=float(thr))
        n = int(block["n"])
        hr = block["hit_rate"]
        if n < min_n or hr is None:
            continue
        if hr > best_hr or (hr == best_hr and n > best_n):
            best_thr, best_hr, best_n = float(thr), float(hr), n
    return best_thr


def _band_blocks(frame: pd.DataFrame, *, score_col: str, fwd_col: str, threshold: float) -> dict[str, Any]:
    # Confidence buckets are scored on the raw post-shift sign (flow_score)
    # at threshold 0 so a shrunk-to-zero stale/thin sample still has an n.
    # Headline train/OOS hit rates keep the train-fitted fire threshold.
    band_col = "flow_score" if "flow_score" in frame.columns else score_col
    out: dict[str, Any] = {}
    for band in ("high", "medium", "low"):
        subset = frame[frame["confidence_band"] == band] if "confidence_band" in frame.columns else frame.iloc[0:0]
        if subset.empty:
            out[band] = {
                "n": 0, "hits": 0, "hit_rate": None, "rank_ic": None,
                "threshold": 0.0, "n_rows": 0,
            }
        else:
            block = _accuracy_block(subset[band_col], subset[fwd_col], threshold=0.0)
            block["n_rows"] = int(len(subset))
            out[band] = block
    return out


def summarize_split(
    frame: pd.DataFrame,
    *,
    score_col: str = "eval_score",
    fwd_col: str = SCORE_FWD_COL,
    threshold: float,
    status: str = "evaluated",
) -> dict[str, Any]:
    """Summarize one train/OOS slice.

    ``status`` is caller-supplied context (``"evaluated"``,
    ``"empty_panel"``, ``"insufficient_dates"``, ...) so a block with
    ``n: 0`` can be told apart from one that was genuinely scored and simply
    found no valid observations -- both look identical on ``n``/``hit_rate``
    alone.
    """
    if frame.empty or score_col not in frame.columns or fwd_col not in frame.columns:
        return {
            "n": 0,
            "hits": 0,
            "hit_rate": None,
            "rank_ic": None,
            "threshold": float(threshold),
            "status": status,
            "by_confidence": _band_blocks(frame, score_col=score_col, fwd_col=fwd_col, threshold=threshold),
        }
    block = _accuracy_block(frame[score_col], frame[fwd_col], threshold=threshold)
    block["by_confidence"] = _band_blocks(frame, score_col=score_col, fwd_col=fwd_col, threshold=threshold)
    block["n_rows"] = int(len(frame))
    block["status"] = status
    return block


def _min_dates_required(cfg: SqueezeFlowEvalConfig) -> int:
    """Fewest usable trading dates the walk-forward geometry needs to yield
    even one fold, given the horizon the splitter actually uses
    (``SCORE_LABEL_HORIZON``, not ``cfg.label_horizon`` -- see module
    docstring comment above ``SCORE_FWD_COL``).

    Mirrors the arithmetic in ``expanding_walk_forward_splits``
    (research/splits.py): the first fold needs
    ``validation_start = initial_train_size + label_horizon + embargo``
    plus enough remaining dates for either a full validation block or, if
    partial finals are allowed, the smaller partial minimum.
    """
    tail = cfg.min_partial_validation_dates if cfg.include_partial_final else cfg.validation_dates
    return cfg.initial_train_dates + SCORE_LABEL_HORIZON + cfg.embargo_dates + tail


def _geometry_dict(cfg: SqueezeFlowEvalConfig) -> dict[str, Any]:
    return {
        "initial_train_dates": cfg.initial_train_dates,
        "validation_dates": cfg.validation_dates,
        "label_horizon": SCORE_LABEL_HORIZON,
        "embargo_dates": cfg.embargo_dates,
        "step_dates": cfg.step_dates,
        "include_partial_final": cfg.include_partial_final,
        "min_partial_validation_dates": cfg.min_partial_validation_dates,
    }


def evaluate_train_oos(
    panel: pd.DataFrame,
    *,
    cfg: SqueezeFlowEvalConfig | None = None,
) -> dict[str, Any]:
    """Walk-forward train vs OOS on unique asof dates. No lookahead.

    The result always carries a top-level ``status`` -- ``"evaluated"``,
    ``"empty_panel"``, or ``"insufficient_dates"`` -- and the same status is
    mirrored onto both the ``train`` and ``oos`` blocks, so a caller reading
    only ``result["train"]``/``result["oos"]`` (as
    ``squeeze_validation.evaluate_universe`` does) can still tell "evaluated,
    no edge found" apart from "never evaluated" without inferring it from an
    all-null block that looks identical either way.
    """
    cfg = cfg or SqueezeFlowEvalConfig()
    if panel.empty:
        train_empty = summarize_split(panel, threshold=cfg.score_threshold, status="empty_panel")
        oos_empty = summarize_split(panel, threshold=cfg.score_threshold, status="empty_panel")
        return {
            "train": train_empty,
            "oos": oos_empty,
            "n_folds": 0,
            "chosen_threshold": cfg.score_threshold,
            "split": "expanding_panel_walk_forward",
            "status": "empty_panel",
            "note": "empty_panel",
            "n_dates_available": 0,
            "n_dates_required": _min_dates_required(cfg),
            "geometry": _geometry_dict(cfg),
        }
    work = panel.copy()
    work["asof"] = pd.to_datetime(work["asof"]).dt.tz_localize(None).dt.normalize()
    if "label_end" not in work.columns:
        work["label_end"] = work["asof"] + pd.tseries.offsets.BDay(cfg.label_horizon)
    folds = list(
        expanding_panel_walk_forward_splits(
            work,
            label_horizon=SCORE_LABEL_HORIZON,
            initial_train_dates=cfg.initial_train_dates,
            validation_dates=cfg.validation_dates,
            step_dates=cfg.step_dates,
            embargo_dates=cfg.embargo_dates,
            include_partial_final=cfg.include_partial_final,
            min_partial_validation_dates=cfg.min_partial_validation_dates,
            date_level="asof",
        )
    )
    if not folds:
        # Honest fallback: still emit two blocks with n=0 rather than
        # crashing -- but tagged so this can never be mistaken for "we
        # evaluated and found no edge". The required-vs-available date
        # counts make the infeasibility diagnosable straight from a saved
        # summary.json, without re-deriving the splitter arithmetic by hand.
        n_dates_available = int(work["asof"].nunique())
        n_dates_required = _min_dates_required(cfg)
        train_empty = summarize_split(work.iloc[0:0], threshold=cfg.score_threshold, status="insufficient_dates")
        oos_empty = summarize_split(work.iloc[0:0], threshold=cfg.score_threshold, status="insufficient_dates")
        return {
            "train": train_empty,
            "oos": oos_empty,
            "n_folds": 0,
            "chosen_threshold": cfg.score_threshold,
            "split": "expanding_panel_walk_forward",
            "note": "not_enough_dates_for_walk_forward",
            "status": "insufficient_dates",
            "n_dates_available": n_dates_available,
            "n_dates_required": n_dates_required,
            "geometry": _geometry_dict(cfg),
        }
    fold = folds[-1]
    train = work.iloc[fold.train_indices].copy()
    oos = work.iloc[fold.validation_indices].copy()
    if train["asof"].max() >= oos["asof"].min():
        raise RuntimeError("walk-forward produced overlapping train/OOS dates")
    threshold = fit_fire_threshold(
        train["eval_score"],
        train[SCORE_FWD_COL],
        min_n=cfg.min_threshold_n,
    )
    train_block = summarize_split(train, threshold=threshold, status="evaluated")
    oos_block = summarize_split(oos, threshold=threshold, status="evaluated")
    train_block["n_dates"] = int(train["asof"].nunique())
    oos_block["n_dates"] = int(oos["asof"].nunique())
    train_block["max_asof"] = str(pd.Timestamp(train["asof"].max()).date()) if len(train) else None
    oos_block["min_asof"] = str(pd.Timestamp(oos["asof"].min()).date()) if len(oos) else None
    return {
        "train": train_block,
        "oos": oos_block,
        "n_folds": len(folds),
        "fold": int(fold.fold),
        "label_horizon": int(fold.label_horizon),
        "embargo": int(fold.embargo),
        "chosen_threshold": float(threshold),
        "split": "expanding_panel_walk_forward",
        "status": "evaluated",
        "train_dates": [str(d.date()) for d in fold.train_dates],
        "oos_dates": [str(d.date()) for d in fold.validation_dates],
    }


def run_and_save(cfg: SqueezeFlowEvalConfig | None = None) -> dict[str, Any]:
    cfg = cfg or SqueezeFlowEvalConfig()
    panel = load_panel(cfg)
    metrics = evaluate_train_oos(panel, cfg=cfg)
    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    panel_path = out_dir / "panel.parquet"
    summary_path = out_dir / "summary.json"
    if not panel.empty:
        panel.to_parquet(panel_path, index=False)
    payload = {
        "config": asdict(cfg),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_rows": int(len(panel)),
        "train": metrics["train"],
        "oos": metrics["oos"],
        "n_folds": metrics.get("n_folds"),
        "chosen_threshold": metrics.get("chosen_threshold"),
        "split": metrics.get("split"),
        "fold": metrics.get("fold"),
        "label_horizon": metrics.get("label_horizon"),
        "embargo": metrics.get("embargo"),
        "panel_path": str(panel_path),
    }
    if metrics.get("note"):
        payload["note"] = metrics["note"]
    summary_path.write_text(json.dumps(payload, indent=2, default=str))
    return payload


def write_fixture(path: Path | None = None) -> Path:
    dest = Path(path) if path is not None else DEFAULT_FIXTURE
    dest.parent.mkdir(parents=True, exist_ok=True)
    panel = make_deterministic_panel()
    panel.to_parquet(dest, index=False)
    return dest
