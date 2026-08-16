# GATE_DESK_RANKER result — 2026-08-16

Pre-registered in [`GATE_DESK_RANKER.md`](GATE_DESK_RANKER.md) before the run.
Artifact: `runs/desk_ranker/results.json`. Catalog: 576 names, skip-day 5-session
label, Friday rebalance, hysteresis 80/65, 10 bp round-trip.

## Development window (2022-01-18 → 2023-12-29)

| Arm | Rank IC | ICIR | NW t | Net / week | Ann. turnover | Net compound |
|---|---:|---:|---:|---:|---:|---:|
| **desk_ranker_v1** | **+0.0205** | 0.122 | 1.19 | **+0.295%** | 24.3× | **+28.9%** |
| shipped factor blend | +0.0092 | 0.054 | 0.54 | +0.276% | 31.0× | +26.4% |
| shipped LGB linear | +0.0165 | 0.096 | 1.14 | +0.249% | **11.5×** | +22.8% |

## Confirmation report — not a gate (2025-01-02 → 2026-06-30)

Overlaps the factor-probe recent window. Do not read as a clean confirmation.

| Arm | Rank IC | Net / week | Ann. turnover | Net compound |
|---|---:|---:|---:|---:|
| desk_ranker_v1 | +0.0206 | +0.273% | 20.1× | +19.2% |
| shipped factor blend | +0.0087 | +0.255% | 30.8× | +18.2% |
| shipped LGB linear | **+0.0293** | **+0.368%** | **11.4×** | **+27.7%** |

## Checks

| Criterion | Result |
|---|---|
| Skip-day IC > shipped blend | **PASS** (0.0205 > 0.0092) |
| Net @ 10 bp > shipped blend | **PASS** (0.295% > 0.276%/week) |
| IC > shipped LGB | **PASS** on development (0.0205 > 0.0165) |
| Turnover < 20× | **FAIL** (24.3×) |
| Full pre-registered gate | **FAIL** |

## Verdict

**PARTIAL.** The recipe is a better *implementation* of the two factors that
already worked. It is not a new edge, it does not clear the project's own
deployment bar (ICIR 0.12 << 0.20, NW t 1.19 << 2.0), and it missed the
pre-registered turnover cap.

What this authorizes:

- Attach `desk_ranker_v1` on the **quick scan** path only. That panel is a
  slice rank (`desk_ranker_slice_not_full_catalog`) and is **not** written
  into the shared Market cache.
- Keep LightGBM + the original `FACTOR_WEIGHTS` blend on the **deep scan**
  ensemble. The LGB bakeoff arm is the linear twin + 0.85 ensemble, not
  `model.txt`.

What this does **not** authorize: ENTER, calibrated probability, live capital,
or claiming the coin-flip directional board is fixed.

Trial count remains **1**.
