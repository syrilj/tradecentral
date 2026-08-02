# edge/

Clean workspace consolidating the best-validated pieces of `Kronos/`,
`TradingAlgoWork/` and `TradingWork/` into one auditable path to a live-tradeable
model. Nothing here duplicates the source repos — `edge/` reads from them and
holds only the harness, the evidence, and the decision record.

## Start here

| File | What it is |
|---|---|
| [`docs/STATUS.md`](docs/STATUS.md) | **Current wave status** — what's done, blocked, next |
| [`docs/AUDIT.md`](docs/AUDIT.md) | Repo map, honest model ranking, lookahead leak, GPU-VM verdict |
| [`docs/PLAN.md`](docs/PLAN.md) | 8-step plan. Steps 1–6 CPU-only; Step 8 GPU, gated on Step 6 |
| [`docs/GATE.md`](docs/GATE.md) | Pre-registered GO/NO-GO criteria (written before Step 5 results) |
| [`tools/verify_no_lookahead.py`](tools/verify_no_lookahead.py) | Runnable proof of the Kronos selective leak |
| [`models/v90/`](models/v90/) | Ported champion: calibrated two-sided meta-labeler |
| [`eval/`](eval/) | Single leak-free walk-forward harness + conformal + property tests |

```bash
# prove the Kronos leak / fix
python3 edge/tools/verify_no_lookahead.py

# harness property tests
python3 -m pytest edge/eval -q

# Step 5 — pull widened universe (1h + 1d)
python3 edge/tools/fetch_universe.py

# Step 5 — coverage check before re-fit
python3 edge/tools/train_v90_wide.py --dry-run

# Step 7 — shadow one session of v90 decisions
python3 edge/tools/shadow_v90.py
python3 edge/tools/shadow_v90.py --realize   # after horizon elapses
python3 edge/tools/shadow_reliability.py

# Step 9 — always use the venv interpreter explicitly, from alltrading/.
# Do NOT rely on bare `python3`: it means different things depending on whether
# `.venv-qlib` is activated, and the two interpreters have different packages.
edge/.venv-qlib/bin/python edge/tools/rank_ic.py                # Rank IC of a v90 bundle
edge/.venv-qlib/bin/python edge/tools/qlib_ingest.py            # build provider dir
edge/.venv-qlib/bin/python edge/tools/qlib_ingest.py --verify   # round-trip check
edge/.venv-qlib/bin/python edge/tools/qlib_run.py --market xs47
edge/.venv-qlib/bin/python edge/tools/qlib_run.py --market xs40
```

**Expected noise on every qlib run** (both appear on *successful* runs — neither
is an error):

- A full `git diff` usage dump, followed by `Fail to log the uncommitted code of
  $CWD ... when run git diff --cached`. Qlib's recorder tries to snapshot
  uncommitted code for provenance; `alltrading/` is not a git repo, so git prints
  its help text. Non-fatal and explicitly caught by qlib.
- `ModuleNotFoundError. CatBoostModel / XGBModel / PyTorch ... skipped`. Qlib
  probes optional model backends at import. Only LightGBM is needed here.

**Do not use bare `qrun` for the gate.** It fails on mlflow ≥3 (the filesystem
tracking backend now raises unless `MLFLOW_ALLOW_FILE_STORE=true`, which
`qlib_run.py` sets for you), and more importantly it does **not** emit the
Newey-West IC t-stat that `docs/GATE_XS.md` binds on, nor run both required
universes. `qlib_run.py` is the supported entry point; the YAML is the spec it
loads.

Comparable cross-model table (capital-normalized):  
`TradingAlgoWork/LEADERBOARD.json`.

## The one-line state of things

The best **calibrated** model in the stack is `v90_meta_confidence`
(holdout ECE 0.0048). At the shipped `balanced_top5` operating point: n=111,
WR 55.0% [45.7%, 63.9%], +0.17%/trade after 10bp costs. Higher frequency
(top-10%) has **negative** expectancy. The Kronos selective model that appeared
to reach 82% is a lookahead artifact (leak-free ≈ 49–52%).

Steps **1–6** are complete. Widened re-fit (`models/v90_wide/`, 59 symbols)
was evaluated once against the pre-registered gate → **NO-GO** (see
`docs/GATE_RESULT.md`). Step **7** shadow logging is live; ≥60 sessions still
needed for forward evidence. **Do not buy a GPU VM.**

Step **9** tested a different question — *cross-sectional* ranking (Qlib /
Alpha158 / `CSRankNorm`, daily 2016-2026) instead of absolute per-symbol
direction — and also returned **NO-GO** (`docs/GATE_XS_RESULT.md`). It is
nonetheless the least-dead result in the stack: Rank IC 0.033 (NW t 2.68) on the
survivorship-controlled universe, against a measured null of −0.0008. Two things
now look like the real constraints: **turnover** (10bp halves the edge) and
**universe construction** (dropping the hindsight-picked 2020-23 listing cohort
*improves* the signal and *worsens* the returns). Neither is fixed by a bigger
model.

---

*All figures are simulated backtests. Not financial advice.*
