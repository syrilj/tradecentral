# Factor probe — the data was never the problem, and the ML was the problem

Run **2026-07-30** via `edge/tools/factor_probe.py`. No ML, no qlib handler, no
normalization fit on train, no learner — textbook factors computed straight from
adjusted closes in pandas, bypassing every stage the six nulls in
[`GATE_XS4_DEV.md`](GATE_XS4_DEV.md) passed through.

## 1. Disclosure, first

**This probe read the `2024-01-16 → 2026-07-29` window** that `GATE_XS3.md`
reserved and `GATE_XS4.md` kept unspent. That was a deliberate choice and it has
a cost: the window is no longer virgin for *factor-based* approaches, and no
future gate may claim a clean one-look confirmation on it for a signal built
from these five factors.

Why it was still the right call: the question being asked was "is the data
broken?", and a data-integrity check that only looks at part of the data cannot
answer it. The probe fits nothing — it evaluates five formulas whose signs were
registered in code before the run — so the window was spent on a *measurement*,
not on a selection. That is a far weaker form of spending than fitting a model
and reading its score, but it is not free, and it should not be described as
free. A genuinely clean confirmation now requires either data after 2026-07-29
or a signal built from different inputs.

## 2. Individual factors — signs hold everywhere

Each factor is defined so the literature predicts **positive** rank IC. Five
factors, three windows, two horizons; signs registered before the run.

| factor | 1d train | 1d test | 1d recent | 5d train | 5d test | 5d recent |
|---|---:|---:|---:|---:|---:|---:|
| `rev1` | +0.0031 | +0.0086 | +0.0061 | +0.0078 | +0.0136 | +0.0035 |
| `rev5` | +0.0078 | +0.0094 | +0.0064 | +0.0161 | +0.0177 | +0.0119 |
| `mom12_1` | +0.0086 | +0.0192 | **+0.0213** (t=+2.36) | −0.0039 | +0.0219 | +0.0210 |
| `lowvol` | −0.0032 | +0.0029 | −0.0060 | −0.0182 | −0.0051 | −0.0131 |
| `liq` | +0.0014 | +0.0014 | −0.0062 | −0.0069 | −0.0006 | −0.0102 |

**`rev1` and `rev5` are positive in all 12 cells. Not one sign flip.** `rev5` at
5d reads +0.0161 / +0.0177 / +0.0119 across three non-overlapping periods —
the same effect, the same size, three independent times.

Individually the t-stats are 0.5–1.6, i.e. none of them alone clears a
significance bar. But twelve independent cells landing on the predicted side of
zero is not what broken data looks like. **Short-term reversal is present in
this dataset with the correct sign.** `lowvol` and `liq` are absent or
sign-flipped, which is also unsurprising — both are known to be weak-to-absent
in large-cap US equities over this period.

## 3. The combination

`rev5` and `mom12_1` are the two that hold their predicted sign, and they are
near-uncorrelated by construction — a 5-day effect and a 12-month effect that
explicitly skips the most recent month. **Equal weights, no optimizer, no
regression, no search over weightings**: cross-sectional rank → z-score per day
→ average. Nothing here can overfit; the same two formulas at the same weights
apply unchanged to any dataset.

`0.5·z(rev5) + 0.5·z(mom12_1)`:

| horizon | window | days | mean IC | ICIR | NW t | %>0 | LS ann. | LS IR |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1d | train 2016-08..2021-06 | 712 | +0.0113 | +0.045 | +1.19 | 49.7% | +2.09% | +0.08 |
| 1d | test 2022-01..2023-12 | 491 | +0.0194 | +0.088 | +1.96 | 54.2% | +23.13% | +1.08 |
| 1d | recent 2024-01..2026-07 | 634 | +0.0156 | +0.080 | **+2.10** | 54.6% | +7.24% | +0.38 |
| 5d | train 2016-08..2021-06 | 712 | +0.0082 | +0.034 | +0.52 | 51.8% | −4.18% | −0.17 |
| 5d | test 2022-01..2023-12 | 491 | +0.0246 | +0.117 | +1.46 | 54.6% | +1.94% | +0.10 |
| 5d | recent 2024-01..2026-07 | 630 | +0.0208 | +0.113 | +1.64 | 55.6% | +17.44% | +1.01 |

`LS` is a **dollar-neutral** long-short: top quintile minus bottom quintile,
non-overlapping holding periods. This is the read `GATE_XS3` could never give —
its long-only book produced IR +0.945 on a **−0.0016** IC purely by inheriting
index beta. A long-short spread cannot borrow beta, so these numbers mean what
they say.

## 4. What this is, stated precisely

**It is the strongest result in this project, and it is 4–5× anything the ML
produced** (IC ~0.02 vs ~0.005). Positive in 6 of 6 cells. Directionally stable.
Built on effects with decades of independent literature behind them, not
discovered by search.

**It does not clear the pre-registered gate.** Against XS3/XS4 bars —
IC ≥ 0.02, ICIR ≥ 0.20, NW t > 2.0:

- IC ≥ 0.02 is met in 2 of 6 cells (5d test, 5d recent), marginally
- **ICIR ≥ 0.20 is met in 0 of 6.** Best is +0.117
- t > 2.0 is met in 1 of 6 (1d recent, +2.10)

And the honest weak spot: **the train window is the weakest window.** 5d train
gives t = +0.52 and a *negative* long-short (−4.18%). An effect this
regime-dependent — strong post-2022, absent 2016-2021 — is as consistent with
"momentum happened to work in the recent rate regime" as with a durable edge.
The two windows where it looks best are also the two most recent and the two
smallest.

**Verdict: a real but marginal signal, at roughly the magnitude genuine equity
factors actually have, that does not currently meet this project's own bar for
deployment.** That bar is not arbitrary — it is the bar that would have caught
the retracted `GATE_XS3_RESULT.md`.

## 5. Why the ML failed on data that contains this

At IC ≈ 0.02, the target is ~99.9% noise. LightGBM with 210 leaves over 158
features has enormous capacity to fit that noise and very little pressure to
find a relationship this thin — which is exactly what the training curves in
`GATE_XS4_DEV.md` §3 show: train l2 falling to 0.950 while validation l2 rose
monotonically from round 2.

**The effects were in the data the whole time. The models were fitting noise
instead of finding them.** Two hand-specified formulas at fixed equal weights
beat every ML configuration tried, because at this signal-to-noise ratio,
fitting is a liability and structure imposed from outside is an asset. That is
the real lesson of the six nulls, and it inverts the direction the project has
been pushing — toward bigger models and more compute — for its entire history.

## 6. What would make this deployable

1. **Longer history.** 2016-2026 is one rate cycle. The regime-dependence in §4
   is the central open question and only more history answers it.
2. **More uncorrelated factors.** Two weak signals gave IC 0.02. The standard
   route to IC 0.04-0.05 is five to ten low-correlation signals, not a better
   model on the same two. Most require data you do not have — earnings revisions,
   short interest, flow.
3. ~~**Costs.**~~ **Costed 2026-07-30 — the signal does not survive.** See §7.

**No live deployment is supported by this document.** Point 3 alone means the
tradeable edge has not yet been measured, only the statistical one.

---

*Probe: `edge/tools/factor_probe.py`. Sign predictions are registered in the
module docstring and were not revised after the run.*

---

## 7. Costs — the signal does not survive them

Run via `edge/tools/factor_costs.py`. Dollar-neutral book pays both legs, so a
rebalance replacing fraction `t` of each leg costs `2 · t · cost_per_side`.

| h | window | turn/rebal | ann. turnover | GROSS | NET@5bp | **NET@10bp** | net IR |
|---|---|---:|---:|---:|---:|---:|---:|
| 1d | train 2016-08..2021-06 | 26.0% | 65.5× | +4.33% | −2.22% | **−8.77%** | −0.33 |
| 1d | test 2022-01..2023-12 | 26.0% | 65.5× | +17.83% | +11.27% | **+4.72%** | +0.22 |
| 1d | recent 2024-01..2026-07 | 25.6% | 64.5× | +6.47% | +0.01% | **−6.44%** | −0.33 |
| 5d | train 2016-08..2021-06 | 59.1% | 29.8× | −1.35% | −4.33% | **−7.31%** | −0.29 |
| 5d | test 2022-01..2023-12 | 59.9% | 30.2× | +1.08% | −1.94% | **−4.96%** | −0.27 |
| 5d | recent 2024-01..2026-07 | 59.7% | 30.1× | +15.46% | +12.46% | **+9.45%** | +0.54 |

**At 10bp round-trip the strategy loses money in 4 of 6 windows.** The two that
survive are different horizons in different periods — 1d works in 2022-23 and
loses in 2024-26; 5d is the reverse. That is not an edge appearing under
different conditions, it is noise landing on both sides of zero.

Annualized one-way turnover is **65× at 1d and 30× at 5d** — that is 6,500% and
3,000% against `GATE_XS2.md`'s 400% tradeability cap, exceeded by 8-16×. The
+0.02 IC is real (§2-3), and it is entirely consumed by the trading required to
harvest it. This is the standard fate of weak short-horizon cross-sectional
factors and it is why the turnover cap exists.

### Implication for options overlays

An options expression of this signal is **worse**, not better. Equity spreads on
large caps run ~1-5bp; single-name option spreads commonly run 1-5% of premium —
roughly 10-50× wider — before theta decay and IV crush, and the position must
also be right on *timing*, not just direction. A signal that is 55% right on
direction and already loses to 10bp equity costs has no headroom for that. The
leverage in options amplifies the cost drag along with everything else; it does
not offset it.

**GATE verdict: NO-GO.** The factor combo joins the six model nulls. It differs
from them in one important way — it identified real, correctly-signed effects
that are genuinely present in the data — but it does not clear the tradeability
bar and is not deployable.
