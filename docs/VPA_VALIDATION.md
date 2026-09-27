# VPA Validation — walk-forward, in- and out-of-sample

Companion to the VPA engine and
[VPA_REBUILD_CONTRACT.md](VPA_REBUILD_CONTRACT.md) (engineering contract).
This document answers a different question: **does the engine's directional read
actually predict anything?**

Harness: `research/vpa_backtest.py`. Reproduce with

```bash
python3 -m research.vpa_backtest --universe 60 --timeframe 1D --horizon 10 --stride 4
```

## Headline result

**No measurable edge.** Over 60 symbols and ~15,600 walk-forward observations, the
engine's directional call performs indistinguishably from a skill-free caller once
market drift is accounted for: 50.2% out-of-sample against 50.9% expected with no
skill, an edge of −0.7% with a 95% clustered interval of [−2.4%, +1.1%]. The
in-sample / out-of-sample gap is +0.3%, so this is *not* an overfitting problem —
the signal simply is not predictive. Doubling the horizon to 20 bars reproduces the
result (50.9% OOS, gap +0.1%).

This is stated in the UI next to the percentage rather than buried here.

## Method

> **Updated 2026-09-03.** The harness passed the truncated history to the engine
> *alongside* the symbol, but the engine prefers its own on-disk bars whenever a
> symbol is supplied (the UI contract), so every historical read had silently
> scored the present end-of-disk window — the walk-forward tested a per-symbol
> constant, not the strategy. `_observations` now calls the engine with
> `symbol=None`, and a regression test pins that. The runs below are the first
> that actually measure the engine; the verdict is unchanged.
>
> **Updated 2026-09-01.** The method below was corrected after the audit in
> `docs/audits/2026-09-01-vwap-orderflow-evaluation.md` §8.1 found the harness's
> uncertainty understated and its purge ineffective. On the 60-symbol
> configuration **all four rolling origins report no edge**.

| Property | Choice | Why it matters |
|---|---|---|
| Lookahead | At as-of index `t` the engine sees `bars[:t]` only | The forward return is never visible to the scorer. |
| Split | Chronological date cut, plus **4 rolling origins** | Shuffling rows of a time series leaks the future into the training window. One split is also one draw: a result that appears at one origin and vanishes at the others is noise, and a "signal" verdict now requires every origin to agree. |
| Purge | **Date-based**, with a `horizon`-bar embargo | An in-sample read must have its whole forward window resolve before the cut. The previous version dropped `horizon` *pooled rows*, which with 60 symbols per date was a fraction of one trading day — an embargo of effectively zero. |
| Uncertainty | **Bootstrap resampling whole `as_of` dates** | Rows are not independent: consecutive reads on one symbol share most of their forward window, and every symbol on a date shares that day's market move. The old `sqrt(0.25/n)` binomial standard error treated all of that as independent and was far too narrow. The naive figure is still reported, labelled as understated. |
| Warmup | 120 bars | The 20-bar volume baseline and pivot detection need history before any read is meaningful. |
| Scoring | Close-to-close forward return over `horizon` bars | `SIDEWAYS` calls are not scored. |
| Primary metric | **Direction-signed excess return** | Forward returns are left-skewed, so raw hit rates sit well below 50% for every bucket regardless of skill and invite misreading. Hit rate is retained as a secondary figure. |
| Costs | `--cost-bp`, net columns alongside every gross figure | So "does this survive costs" is answerable from the table instead of left to the reader. |
| Benchmark | **Base rate, not 50%** | See below. This is the single most important choice in the harness. |

### A finding the corrected harness surfaced

On a **12-symbol large-cap** universe, three of four origins report signal and
one does not, so the harness reports "inconsistent across origins" and declines
to call it an edge. The old single-split, naive-interval view would have called
it signal outright. Whether that reflects real structure in a small, biased
universe or a false positive at three origins is untested; it is not an
authorization to trade, and the 60-symbol result remains the primary one.

### Why the benchmark is not 50%

Equities drift upward, so a bullish call is right more than half the time for free.
The first version of this harness compared against 50% and reported:

```
Verdict: signal
  Out-of-sample hit rate 54.4% is more than 2 standard errors above the 50% coin flip.
```

That was wrong, and flattering. In the same period **54.5% of all forward windows were
positive**. The engine was not beating anything — it was reporting the market's drift
back to us. Broken out by direction the tell was obvious:

| Direction | n | Hit rate | Mean forward return |
|---|---|---|---|
| BULLISH | 3,075 | 54.7% | +1.93% |
| BEARISH | 2,860 | 45.1% | +0.91% |

Bearish calls "lost" at exactly the rate bullish calls "won", and the mean forward
return was positive under *both* — the signature of drift, not skill.

The harness now computes `expected_hit_rate_no_skill`: given the same mix of bullish
and bearish calls and this period's drift, what would a caller with no skill have
scored? Edge is measured against that.

## Results

### Daily, 10-bar horizon, 60 symbols — primary result

| | n (directional) | Hit rate | Expected (no skill) | Edge |
|---|---|---|---|---|
| In-sample | 7,926 | 50.4% | 50.5% | — |
| Out-of-sample | 5,027 | 50.2% | 50.9% | **−0.7% [−2.4%, +1.1%]** |

IS–OOS gap **+0.3%**. Base rate 54.3% of forward windows positive. Primary
metric (direction-signed excess return): **−0.11% [−0.45%, +0.25%]**. All four
rolling origins agree: **no edge.**

### Daily, 20-bar horizon, 60 symbols — robustness check

| | n (directional) | Hit rate | Expected (no skill) | Edge |
|---|---|---|---|---|
| In-sample | 7,660 | 51.0% | 50.5% | — |
| Out-of-sample | 4,774 | 50.9% | 51.1% | **−0.2% [−0.7%, +0.4%]** |

IS–OOS gap **+0.1%**. Doubling the horizon changes nothing, so the result is
not an artefact of one horizon choice.

### Daily, 10-bar horizon, 12 large caps

> **Predates the 2026-09-03 harness fix** — kept only as the original
> illustration of origin inconsistency; the numbers are not comparable with
> the tables above.

| | n | Hit rate | Expected (no skill) | Edge |
|---|---|---|---|---|
| In-sample | 1,759 | 54.8% | — | — |
| Out-of-sample | 1,171 | 54.4% | 53.7% | **+0.7% ± 1.5%** |

Within noise. Note how much higher the raw hit rate looks on a large-cap-only
universe purely because those names drifted up harder — which is exactly why
the benchmark is the base rate and not 50%.

### Calibration (out-of-sample)

A stated probability should mean something: 68–73% ought to hit more often than 50–55%.
It does not, monotonically.

| Bucket | n | Hit rate |
|---|---|---|
| 50–55% | 1,480 | 50.9% |
| 56–61% | 2,272 | 49.5% |
| 62–67% | 1,116 | 50.5% |
| 68–73% | 159 | 51.6% |

The top bucket is the best, but 56–61% underperforms 50–55%, so the ordering is not
reliable. **The percentage ranks evidence weight. It is not a hit-rate estimate.**

## What this does and does not mean

**Does not mean the tool is useless.** The engine's value is forensic: it identifies
pivot-clustered support and resistance with touch counts, a correctly constructed
volume profile, effort-versus-result anomalies, stopping and topping volume, and
congestion patterns — each traceable to specific bars. That reading describes what
price and volume are showing. It is not a forecasting model.

**Does mean the percentage must not be presented as predictive.** The percentage is
this workstation's ranking of its own evidence ledger, and this validation is why
the UI says so.

**Does not rule out an edge elsewhere.** Untested: intraday timeframes, longer horizons,
conditioning on confidence or evidence count, event-driven entries rather than a fixed
stride, and any form of position sizing or risk management. A fixed-horizon
close-to-close test is the bluntest possible instrument.

## Honest limitations

- No transaction costs, slippage, borrow, or spread. Signal quality only, never P&L.
- Survivorship: the universe is symbols with data on disk today.
- One split point. A rolling-origin evaluation across several cuts would be stronger.
- `horizon` and `stride` were not swept; results are reported at the values shown.
- The thresholds were never fitted to this data, so IS/OOS here measures regime
  robustness rather than curve-fitting. A large gap would still be a warning.

## Reproducing

```bash
python3 -m research.vpa_backtest --universe 60 --timeframe 1D --horizon 10 --stride 4 --json runs/vpa_walkforward_1D.json
```

Artifacts are written to `runs/`.
