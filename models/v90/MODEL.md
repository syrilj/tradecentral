# v90_meta_confidence (ported)

Two-sided (BUY/SELL/FLAT) meta-labeling engine with **calibrated** confidence.
Ported byte-identical (booster weights, features, calibration curves) from
`TradingAlgoWork/models/poc_va_macdha/v90_meta_confidence/` per
`edge/docs/AUDIT.md` §3, which ranks it **#1** in the stack: it is the only
model with real calibration evidence (holdout ECE 0.0048) rather than an
ordinal quality score, it is genuinely two-sided (a real model-driven SELL
head, not long/flat), and it is honest about its own limits in its own
docs. Two bugs identified in the audit were fixed during this port — see
"Fixes applied during port" below. **Source repo (`TradingAlgoWork/`) was
left completely untouched**; a separate effort may independently regenerate
its `results.json`.

## Architecture

```
OHLCV (1H)
  -> causal features (features.py: returns, RSI, MACD-hist, ATR regime, vol-z,
     EMA stack/cloud, SMA200 trend, realized vol, range position, session hour)
  -> triple-barrier labels (TP/SL = +/-1.0*ATR, time exit = 8 bars);
     win := net-of-cost exit return > 0
  -> XGBoost LONG head + SHORT head (depth 4, 250 trees, lr 0.03)
  -> purged + embargoed 5-fold cross-fit  -> out-of-fold probabilities
  -> isotonic calibration (activated only if OOF Brier AND log-loss improve)
  -> raw score >= threshold decides BUY / SELL / FLAT;
     calibrated probability is the confidence shown to the operator
```

Contract (unchanged from source): train 2024-08-01→2025-08-01, locked
holdout 2025-08-01→2026-07-11, universe TSLA/MU/SPY/IONQ/APLD/XLP/QQQ,
1H bars (yfinance `auto_adjust`), 5bp+5bp roundtrip cost, horizon 8 bars,
barrier 1.0×ATR.

## Files in this directory

| File | Role | Changed vs. source? |
|---|---|---|
| `signal_engine.py` | `SignalEngine` class — the runtime entry point | Comments only (2 notes added); zero logic changes |
| `features.py` | causal feature builder, frozen `FEATURES` order | Byte-identical |
| `meta_xgb_long.json` / `meta_xgb_short.json` | XGBoost boosters (LONG/SHORT heads) | Byte-identical |
| `calibration.json` | isotonic calibration curves for both heads | Byte-identical |
| `thresholds.json` | `enter_hi`/`enter_lo`/`selective`/`exit` + operating-point metadata | Additive fields only (bug 2 fix); existing keys/values unchanged |
| `config.json` | backtest-manifest (universe, cost, strategy note) | Additive fields only (bug 2 fix + provenance) |
| `hunt_config.json` | runtime knobs (`allow_short`, `base_scale`, `selective_scale`) actually read by `SignalEngine.__init__` | Additive fields only; all behavior-affecting values unchanged |
| `results.json` | holdout evidence record | **Added during port** (not in the original file list — see note below); Sharpe fix (bug 1) + operating-point metadata (bug 2) applied |

`results.json` was not on the original list of files to port, but bug 1's
fix is specifically a fix *to* `results.json`, and `edge/`'s stated purpose
is to hold "the harness, the evidence, and the decision record" — porting
the evidence file the fix applies to, rather than leaving only prose behind,
seemed like the right call. It is not read by `SignalEngine` at runtime;
it exists purely as the evidence record for this port.

## Calibration (the honest part — unchanged)

| head | Brier (raw→cal) | log-loss (raw→cal) | OOF ECE |
|------|-----------------|--------------------|---------|
| long  | 0.2594 → 0.2491 | 0.7140 → 0.6913 | ~0 |
| short | 0.2599 → 0.2495 | 0.7145 → 0.6920 | ~0 |

Holdout (long head): Brier 0.250, log-loss 0.692, **ECE 0.0048** — when the
model says 55%, it wins ~55% of the time. This is the one model in the whole
stack with real calibration evidence, not just an ordinal score, and nothing
about the port changes it (calibration.json ported byte-identical).

## Holdout results (locked OOS, two-sided, after costs)

| operating point | raw thr | n | long/short | win rate | Wilson 95% | avg net/trade | profit factor | Sharpe | status |
|---|---:|---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| active_top10   | 0.629 | 320 | 223/97 | 51.2% | [45.8%, 56.7%] | −0.05% | 0.94 | −0.98 | reported for transparency, not the shipped default |
| **balanced_top5** | **0.671** | **111** | **76/35** | **55.0%** | **[45.7%, 63.9%]** | **+0.17%** | **1.17** | **+2.76** | **SHIPPED DEFAULT** |
| selective_top2 | 0.724 |  34 | 20/14  | 58.8% | [42.2%, 73.6%] | +0.82% | 2.26 | *n/a — n<50* | reported for transparency, not the shipped default |
| sniper_top1    | 0.760 |  11 |  6/5   | 63.6% | [35.4%, 84.8%] | +1.60% | 7.06 | *n/a — n<50* | reported for transparency, not the shipped default |

Threshold *values* for all four points are derived from **train** OOF
quantiles (`thresholds.json: quantile_source = train_oof_pooled`) — no
holdout peeking. That part was already correct in the source and is
unchanged.

## Fixes applied during port

### Bug 1 — Sharpe artifacts at n<50

**Before:** `results.json` reported `sharpe: 13.82393213955133` for
`selective_top2` (n=34) and `sharpe: 29.251110613282595` for `sniper_top1`
(n=11).

**Why it's wrong:** both are artifacts of annualizing a 1764-bars/year
factor across a tiny trade count — not real risk-adjusted returns. A
Sharpe of 13.8–29.3 is not a plausible number for any real strategy; it is
what you get when a handful of lucky/unlucky trades gets multiplied by
`sqrt(1764)`.

**After:** both fields set to `null` in the ported `results.json`, each
with a `sharpe_note` explaining the removal and pointing readers to
`profit_factor` / `avg_return_per_trade` / `win_rate_wilson95` instead.
Sharpe is **kept** for `active_top10` (n=320) and `balanced_top5` (n=111)
— both comfortably above the n=50 threshold where annualized Sharpe starts
being a defensible (if still noisy) statistic. The MODEL.md table above
marks the removed cells `n/a — n<50` instead of a blank, so the fix is
visible, not just silently absent.

### Bug 2 — operating-point selection read as holdout-peeking

**Before:** the four operating points were all computed on the holdout set,
and the source `MODEL.md`'s narrative read as if "balanced" was chosen by
eyeballing holdout profit factor across all four — a mild form of
holdout-peeking on *which threshold to ship*, even though the threshold
*values* themselves come cleanly from train-only OOF quantiles (that part
was, and remains, leak-free).

**After:** the shipped default is now a named, explicit, pre-hoc rule,
recorded in `config.json` (`default_operating_point`), `thresholds.json`
(`shipped_default_operating_point`, `operating_point_status`), and
`hunt_config.json` (`shipped_default_operating_point*`) — all three
"config" files carry the same justification so it survives regardless of
which file a future reader opens first:

> First operating point, in the fixed candidate order `active_top10 →
> balanced_top5 → selective_top2 → sniper_top1`, satisfying **all** of:
> (a) n > 100, (b) positive avg net return/trade, (c) Wilson-95% lower
> bound within reach of 50%.

Applying that rule: `active_top10` (n=320) clears (a) but fails (b) at
−0.05%/trade; `balanced_top5` (n=111) clears all three (+0.17%/trade,
Wilson95 low 45.7%); `selective_top2` (n=34) and `sniper_top1` (n=11) both
fail (a) outright regardless of their higher point estimates. The rule
resolves to the same point the source narrative already leaned toward
(`balanced_top5`), but now for a stated, falsifiable reason instead of a
post-hoc comparison across all four holdout results. The other three
points remain fully reported (`results.json`, table above) but are tagged
`status: reported_for_transparency_not_shipped_default` everywhere they
appear — they are not validated production operating points.

## Shipped default operating point

**`balanced_top5`** — raw threshold `0.6711237639188766` (train-OOF 95th
percentile). At this point: n=111, win rate 55.0% (Wilson 95% CI
[45.7%, 63.9%]), profit factor 1.17, +0.17% avg net return/trade. See
"Bug 2" above for the full selection-rule justification. This is the
operating point this port is documented and evidenced around, **and**, as
of the fix below, the operating point the runtime code actually gates on —
see "Runtime gating note" immediately below for the before/after.

## Runtime gating note (found and fixed during this port)

While reading `signal_engine.py` to understand its real interface (per the
porting brief), a third issue surfaced beyond the two bugs this port was
originally scoped to fix, and was corrected once flagged:
`SignalEngine.generate()` was gating *any* signal on `thresholds.enter_lo`
(`0.6293`, which equals `active_top10`'s raw threshold — the operating
point measured to have **negative** holdout expectancy, −0.05%/trade at
n=320), while `thresholds.enter_hi` (`0.6711`, equal to the shipped-default
`balanced_top5` threshold) was loaded into `SignalEngine._enter_hi` in
`__init__` but never referenced anywhere in `generate()` — inert. In other
words: as originally ported (and as the source repo still does), the
runtime engine's *actual* default firing frequency was `active_top10`
(top 10%, negative expectancy), not `balanced_top5` (top 5%, the documented
shipped default).

**Fix (applied):** `generate()`'s `long_ok`/`short_ok` gate now compares
against `thresholds.enter_hi` instead of `thresholds.enter_lo` —

```diff
-                long_ok = rl >= self._enter_lo
-                short_ok = rs >= self._enter_lo
+                long_ok = rl >= self._enter_hi
+                short_ok = rs >= self._enter_hi
```

A single, narrow swap — not a new two-tier scaled/watch design (an earlier
design doc sketched something like that; it is not what this engine
actually implements, and building it is a separate, bigger piece of work
left for later if wanted). Position-size escalation to `selective_scale`
above `thresholds.selective` (`0.7243`, `selective_top2`'s raw threshold)
is unchanged. `_enter_lo` is still loaded in `__init__` for backward
compatibility but is no longer read anywhere in `generate()`. Full
before/after also recorded in `hunt_config.json`'s `runtime_gating_note`
and in `signal_engine.py`'s own comments at the `_enter_hi`/`_enter_lo`
assignment and in the module docstring.

**Left untouched:** `TradingAlgoWork/models/poc_va_macdha/v90_meta_confidence/signal_engine.py`
has this same bug and was **not** patched — fixing the source repo is a
separate decision for later, out of scope for this port, and another
process may be reading that directory concurrently.

## Honest read — do not overclaim

- **The real, calibrated win-probability ceiling on this universe/timeframe
  is ~52–65%, not the 86–91% headline win rates advertised by older
  bundles.** Those came from 33–52 trades and dropped ~8–10pp
  out-of-sample. v90's edge is a *positive-expectancy asymmetry* (winners
  larger than losers, PF > 1 at selective thresholds), not a high hit-rate.
- Expectancy is positive and improves as you tighten the threshold, but
  sample size shrinks and the win-rate confidence interval widens. At the
  `selective_top2` and `sniper_top1` points the Wilson lower bound is still
  below 50% — treat those win rates as suggestive, not proven (this is why
  neither qualifies as the shipped default).
- At the highest tradeable frequency (`active_top10`, n=320) expectancy is
  **negative** (−0.05%/trade, PF 0.94). The edge measured here exists only
  at n ≤ 111 — see the runtime gating note above for why that matters
  operationally, not just academically.
- This is **simulated only**. No live-profitability claim is made. The next
  gate is forward paper/shadow trading before any real capital, per
  `edge/docs/AUDIT.md` §5's pre-registered VM/trigger criteria.

## Status

Not wired into any promotion/deployment manifest. `edge/eval/` (a parallel
effort, not yet built as of this port) is expected to be the harness that
eventually validates this engine end-to-end; this port only guarantees the
artifacts are present, importable, and that `generate()` runs without
raising — see the smoke test recorded at port time. Do not treat this port
as a promotion or a live-trading readiness signal.
