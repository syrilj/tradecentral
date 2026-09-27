# GATE result — single evaluation, 2026-07-30

Pre-registered criteria: [`GATE.md`](GATE.md) (written **before** this run).  
Spec evaluated: **v90 hyperparams frozen**, re-fit once on Step 5 widened 1h
universe (`edge/models/v90_wide/`, 59 symbols, train 2024-08-01→2025-08-01,
holdout 2025-08-01→2026-07-11). Artifacts: `edge/models/v90_wide/results.json`.

## Trial count (for deflated Sharpe honesty)

| Item | Count |
|---|---:|
| Configurations searched **for this evaluation** | **1** (single frozen v90 recipe) |
| Hyperparameter grid tried against this holdout | 0 |
| Operating points *reported* (not re-selected on holdout) | 4 (train-OOF quantiles only) |

Deflation factor uses **1** modeling trial for this gate. Historical research
elsewhere in the stack (152 versions) is **not** re-opened here; this gate is
specifically "does the frozen v90 recipe clear on a wider cross-section?"

## Holdout metrics vs gate

| Criterion | Threshold | balanced_top5 (shipped OP) | active_top10 | selective_top2 | sniper_top1 | Pass? |
|---|---|---:|---:|---:|---:|---|
| n trades | ≥ 200 | **2049** | 4632 | 444 | 161 | balanced **YES** |
| Expectancy after 10bp | ≥ +0.15R | **−0.03%/trade** | −0.00% | −0.03% | +0.02% | **NO** |
| Wilson 95% low on WR | > 50% | **50.4%** (CI [50%, 55%]) | 53% | 48% | 43% | balanced **marginal YES*** |
| ECE (long head) | ≤ 0.05 | **0.0088** | same cal | same | same | **YES** |
| Deflated Sharpe | > 0 | **−0.73** | −0.12 | −0.50 | +0.28 (n&lt;200) | **NO** |

\*Printed Wilson interval for balanced is `[0.50, 0.55]`; treat as **does not
comfortably clear** a strict >50% lower bound. Even if counted as pass, the
expectancy and Sharpe criteria fail hard.

### Calibration (survives)

| Metric | Value |
|---|---:|
| long holdout Brier | 0.2474 |
| long holdout log-loss | 0.6863 |
| long holdout ECE | 0.0088 |

The model remains **well calibrated** on the wide set. Calibration is not edge.

## Verdict

# **NO-GO**

The frozen v90 recipe, evaluated once on ≥40 symbols (59 landed), **does not**
clear the pre-registered gate. Expectancy is non-positive at every operating
point with n≥200. Widening the cross-section **did not** produce a tradeable
high-confidence edge; it produced a larger sample of roughly coin-flip
selective trading with good probability calibration.

### What this authorizes / blocks

| Action | Status |
|---|---|
| Step 8 Kronos fine-tune / GPU VM | **Blocked** (gate failed) |
| Re-tune thresholds on this holdout | **Forbidden** by GATE.md rule 1 |
| Fresh research on a **new** holdout window / label / feature set | Allowed as a new Step 5 cycle (new gate write first) |
| Keep `edge/models/v90` baseline as documentation champion | Yes — small-universe historical result only |
| Keep shadow logging (`edge/tools/shadow_v90.py`) | Yes — forward evidence still valuable |
| Live capital on v90_wide | **No** |

## Interpretation (honest)

On 7 names in a 2024–26 melt-up, v90's rare "balanced" pocket looked like a
thin positive edge (n=111, +0.17%/trade). On 59 liquid names the same recipe
yields thousands of trades with **~52–54% WR and ≤0 expectancy after costs**.
That is the pattern of an overfit niche, not a portable edge. The binding
constraint remains **evidence and regime**, not model capacity or GPUs.

## Paths forward (none require a VM yet)

1. **New hypothesis, new holdout** — e.g. regime filter + lower frequency, or
   daily bars with multi-year span — with a **new** gate file dated before the
   run.
2. **Continue shadow** on the baseline bundle for calibration drift only.
3. **Use Kronos only for intervals** (split-conformal), not direction.
4. **Do not** chase win rate; LEADERBOARD already showed high-WR low-return
   models (v70) underperform.

---

*Simulated holdout only. Not financial advice. Gate criteria were not edited
after seeing these numbers.*
