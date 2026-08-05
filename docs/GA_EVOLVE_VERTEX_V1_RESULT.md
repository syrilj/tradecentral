# GA evolve Vertex v1 — result summary

**Job:** Vertex AI custom training `7628007886454521856`  
**Finished:** 2026-08-03 ~21:04 local (UTC create `2026-08-04T03:04:19Z` in artifact)  
**Command:** `python3 edge/tools/run_ga_evolve.py --pop 300 --gens 20 --seed 20260803`  
**Runtime:** ~12 min on Spot `n1-standard-8`  
**Artifacts (GCS):** `gs://edge-artifacts-gen-lang-client-0699310395/results/ga_evolve_v1/`  
**Local mirror:** `edge/runs/ga/vertex_ga_evolve_v1/ga_20260804T025349Z_7d7ce636/`

`decision_authorized` is **always false** on GA outputs. Survivors are research-only.

---

## 1. Config

| Field | Value |
|--------|--------|
| Population | 300 |
| Generations | 20 |
| Elite fraction | 0.10 → 30 elites confirmed |
| Mutation rate | 0.28 |
| Seed | 20260803 |
| Universe size | **60** symbols (directional v2) |
| Round-trip cost | 10 bps |
| Min trades | 40 |
| Fitness window | 2018-01-02 → 2024-12-31 |
| Confirmation window | 2025-01-02 → 2026-07-10 |
| Terminal holdout | 2026-07-13 → 2027-01-29 (**unused** by fitness) |

---

## 2. Outcome (binding)

| Metric | Result |
|--------|--------|
| Confirmation evaluated | 30 elites |
| **`passes_confirmation`** | **0 / 30** |
| Last-gen best fitness (in-sample) | ~1793 (pathological; see notes) |
| Last-gen mean fitness | still **negative** (~−236) |
| Elite gene consensus | **100%** `mean_reversion` + **100%** `long_only` + **100%** `horizon_days=20` |

### Elite gene medians (all 30)

| Gene | Median |
|------|--------|
| `signal_family` | mean_reversion |
| `long_short` | long_only |
| `horizon_days` | 20 |
| `lookback` | 8 |
| `entry_z` | 2.5 (upper bound) |
| `top_k` | 7 |
| `vol_window` | 35.5 |
| `dollar_volume_min_rank` | 0.18 |

**Read:** Search collapsed onto short-lookback, high-threshold, long-only mean reversion with a 20d hold. That is a single niche, not a diverse strategy set. **No elite survived the 2025–mid-2026 confirmation arm** under the protocol costs and hard gates.

---

## 3. What this means

1. **Larger pop/gens on the same panel did not create a promotable edge.** Local smaller runs sometimes showed confirmation passes; this Vertex run with 60 names + 300×20 found **zero** confirmation survivors. Prefer the **stricter** (zero-pass) read when promoting.
2. **In-sample fitness exploded while mean fitness stayed negative** → a thin tail of overfit genomes, not population-wide skill. Treat max fitness as a **search diagnostic**, never as alpha.
3. **Consensus is homogeneous** (MR / long-only / h=20). Next search should either:
   - diversify fitness (penalize family monopoly, force long–short arms), or
   - add an external ranking signal (Qlib / factor scores) so genomes are not pure price-z only.
4. **Infrastructure:** Spot + 12 min is the right cost shape. Drop the TF training image for a slim Python image next time.

---

## 4. Follow-on implemented in-repo

Hybrid gene hooks (research-only):

- `cs_mode`: `off` | `filter` | `blend`
- `cs_min_rank`: require cross-sectional aux score rank ≥ threshold  
- `cs_blend`: mix rule score with aux (Qlib-style) ranks  

Panel can attach `cs_score` (T×S). Default builder uses the same **factor-probe blend** as desk routing (`rev5/rev1/mom12_1/…`) without requiring a full Qlib Alpha158 rebuild. Real LGB scan scores can be injected the same way later.

CLI:

```bash
python edge/tools/run_ga_evolve.py --smoke --cs-score
python edge/tools/run_ga_evolve.py --pop 80 --gens 10 --cs-score --seed 20260803
```

Still **`decision_authorized: false`**. No live path reads GA genomes.

---

## 5. Hybrid follow-up (local, 2026-08-03)

**Command:** `python edge/tools/run_ga_evolve.py --pop 80 --gens 10 --cs-score --seed 20260803`  
**Run id:** `ga_20260804T040635Z_3daed3d2` (~57s local)  
**Artifacts:** `edge/runs/ga/ga_20260804T040635Z_3daed3d2/`

| Metric | Result |
|--------|--------|
| CS hybrid | enabled (factor-probe ranks on panel) |
| Confirmation | **0 / 8** pass |
| Alive on confirmation | 1 / 8 (still fails fitness bar) |
| Dominant death | **`max_drawdown`** (7/8; hard cap 0.45; OOS DD ~0.48–0.57) |
| Elite consensus | 8/8 **mean_reversion** + **long_only** + **`cs_mode=off`** |

Search was *allowed* to use CS filter/blend genes, but **elites discarded them** — pure price MR still won in-sample fitness. CS hybrid did **not** rescue confirmation on this 60-name panel.

### Recommended next (only if continuing research)

1. **Force CS use** for a diagnostic arm (`cs_mode` fixed to `filter`/`blend` in init, no mutate to `off`) — measures whether ranks help when not optional.  
2. **Widen universe / true Qlib scores** — factor-probe on 60 names is not the 500–1000 name IC design.  
3. **Do not promote** any elite from Vertex v1 or this hybrid run.

---

*Vertex section from GCS mirror `ga_20260804T025349Z_7d7ce636`; hybrid section from local run `ga_20260804T040635Z_3daed3d2`.*
