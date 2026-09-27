# Genetic Evolution Lab

Research-only “survival of the fittest” search over rule-based daily strategies.

## What shipped

| Layer | Location |
|---|---|
| Genome / mutate / crossover | `edge/research/ga/genome.py` |
| Market panel matrices | `edge/research/ga/panel.py` |
| Fitness (Sharpe, DD, cost, hard kills) | `edge/research/ga/fitness.py` |
| Evolution loop + confirmation | `edge/research/ga/evolve.py` |
| Artifact I/O + API payload | `edge/research/ga/storage.py` |
| Local CLI | `edge/tools/run_ga_evolve.py` |
| Vertex AI (GCP SPOT) | `edge/tools/gcp_ga_evolve.py` |
| HTTP | `GET /api/ga?run_id=` |
| Dashboard tab | `/evolution` (`EvolutionView.vue`) |

## Protocol (anti-overfit)

- **Fitness window:** 2018-01-02 → 2024-12-31
- **Confirmation:** 2025-01-02 → 2026-07-10 (elites re-scored OOS)
- **Terminal holdout:** 2026-07-13+ — **never loaded for fitness**
- `decision_authorized` is always `false` on GA artifacts

## Gene schema

`signal_family` ∈ momentum | mean_reversion | vol_scaled_momentum | breakout  
+ lookback, entry_z, exit_z, horizon_days (5/10/20), top_k, long_short, vol_window, dollar_volume_min_rank

## Run

```bash
# Local smoke
python edge/tools/run_ga_evolve.py --smoke

# Local full
python edge/tools/run_ga_evolve.py --pop 200 --gens 15

# GCP Vertex SPOT
python edge/tools/gcp_ga_evolve.py submit --dry-run
python edge/tools/gcp_ga_evolve.py submit --pop 300 --gens 20
python edge/tools/gcp_ga_evolve.py fetch
```

Artifacts land in `edge/runs/ga/<run_id>/` and are listed on the Evolution tab.
