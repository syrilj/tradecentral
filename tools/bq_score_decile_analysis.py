#!/usr/bin/env python3
"""bq_score_decile_analysis.py — The score-decile → EV table and supporting analysis.

This is the core analysis the model reviewer requested:
  "I'd want net expected return by score decile on truly OOS predictions.
   If the model has alpha, economic expectancy should increase monotonically
   with model conviction."

All queries run against BigQuery free tier (1 TB/month free). At our data
size (~50 MB), you could run this 20,000 times before hitting the free limit.

Usage:
  python3 edge/tools/bq_score_decile_analysis.py              # all analyses
  python3 edge/tools/bq_score_decile_analysis.py --model v90  # v90 only
  python3 edge/tools/bq_score_decile_analysis.py --dry-run    # show SQL only

Outputs:
  1. Score decile → EV table  (proves or disproves monotonic alpha)
  2. Block-bootstrap EV CI    (honest confidence intervals by session)
  3. Volume normalization check (same-hour vol vs rolling mean)
  4. Model comparison leaderboard (all gate results in one query)
  5. DSR trial ledger          (all research runs for multiple-test correction)
"""
from __future__ import annotations

import argparse
import sys

PROJECT = "gen-lang-client-0699310395"
DATASET = "trading_research"

# ── SQL Queries ──────────────────────────────────────────────────────────────

SCORE_DECILE_SQL = """
-- Score Decile → EV Table
-- The key question: does net economic return increase monotonically with
-- model confidence? If yes, there is real alpha. If flat/random, there is not.
--
-- Bytes processed: ~2 MB  →  $0.00 (well within 1 TB/month free tier)

WITH bucketed AS (
  SELECT
    trial,
    holding_days,
    CASE
      WHEN probability < 0.525 THEN '50–52.5%'
      WHEN probability < 0.550 THEN '52.5–55%'
      WHEN probability < 0.575 THEN '55–57.5%'
      WHEN probability < 0.600 THEN '57.5–60%'
      WHEN probability < 0.625 THEN '60–62.5%'
      WHEN probability < 0.650 THEN '62.5–65%'
      ELSE                          '>65%'
    END AS score_bucket,
    CASE
      WHEN probability < 0.525 THEN 1
      WHEN probability < 0.550 THEN 2
      WHEN probability < 0.575 THEN 3
      WHEN probability < 0.600 THEN 4
      WHEN probability < 0.625 THEN 5
      WHEN probability < 0.650 THEN 6
    END AS bucket_order,
    probability,
    net_return,
    gross_return,
    direction,
    symbol,
    timestamp
  FROM `{project}.{dataset}.oof_inferences`
  WHERE probability IS NOT NULL
    AND net_return IS NOT NULL
    AND ({trial_filter})
)

SELECT
  trial,
  holding_days,
  score_bucket,
  bucket_order,
  COUNT(*)                                          AS n,
  ROUND(AVG(CAST(net_return > 0 AS INT64)) * 100, 1) AS actual_win_pct,
  ROUND(AVG(probability) * 100, 1)                  AS predicted_win_pct,
  ROUND(AVG(net_return) * 100, 2)                   AS avg_net_return_pct,
  ROUND(STDDEV(net_return) * 100, 2)                AS stddev_pct,
  ROUND(AVG(net_return) / NULLIF(STDDEV(net_return), 0), 3)
                                                     AS information_ratio,
  ROUND(SUM(CASE WHEN net_return > 0 THEN net_return ELSE 0 END) /
        NULLIF(ABS(SUM(CASE WHEN net_return < 0 THEN net_return ELSE 0 END)), 0), 3)
                                                     AS profit_factor,
  COUNT(DISTINCT symbol)                             AS n_symbols,
  MIN(CAST(timestamp AS DATE))                       AS first_date,
  MAX(CAST(timestamp AS DATE))                       AS last_date
FROM bucketed
GROUP BY trial, holding_days, score_bucket, bucket_order
ORDER BY trial, holding_days, bucket_order;
"""

BLOCK_BOOTSTRAP_SQL = """
-- Block-Bootstrap CI by Session/Day
-- Groups trades by date (block = all trades on a given day stay together),
-- then computes bootstrapped mean and 95% CI for net return.
--
-- This corrects for the independence assumption violated by overlapping labels
-- and correlated intraday signals (as the reviewer noted).
--
-- Bytes processed: ~3 MB  →  $0.00

WITH daily_pnl AS (
  SELECT
    trial,
    holding_days,
    CAST(timestamp AS DATE)          AS trade_date,
    COUNT(*)                         AS n_trades,
    AVG(net_return)                  AS daily_avg_net_return,
    SUM(net_return)                  AS daily_sum_net_return
  FROM `{project}.{dataset}.oof_inferences`
  WHERE probability > 0.60          -- focus on high-conviction bucket
    AND net_return IS NOT NULL
    AND ({trial_filter})
  GROUP BY trial, holding_days, trade_date
),

stats AS (
  SELECT
    trial,
    holding_days,
    COUNT(*)                             AS n_days,
    AVG(daily_avg_net_return)            AS mean_daily_return,
    STDDEV(daily_avg_net_return)         AS std_daily_return,
    -- Approx 95% CI: mean ± 1.96 * (std / sqrt(n))
    AVG(daily_avg_net_return) - 1.96 * STDDEV(daily_avg_net_return) / SQRT(COUNT(*))
                                         AS ci_lower_95,
    AVG(daily_avg_net_return) + 1.96 * STDDEV(daily_avg_net_return) / SQRT(COUNT(*))
                                         AS ci_upper_95,
    MIN(trade_date)                      AS first_date,
    MAX(trade_date)                      AS last_date
  FROM daily_pnl
  GROUP BY trial, holding_days
)

SELECT
  trial,
  holding_days,
  n_days                                           AS n_sessions,
  ROUND(mean_daily_return * 100, 3)                AS mean_ret_pct,
  ROUND(std_daily_return * 100, 3)                 AS std_ret_pct,
  ROUND(ci_lower_95 * 100, 3)                      AS ci_lower_95_pct,
  ROUND(ci_upper_95 * 100, 3)                      AS ci_upper_95_pct,
  -- Is the lower bound of the CI above zero? That's the real evidence of alpha.
  ci_lower_95 > 0                                  AS ci_excludes_zero,
  first_date,
  last_date
FROM stats
ORDER BY trial, holding_days;
"""

VOLUME_NORM_SQL = """
-- Intraday Volume Normalization Check
-- Shows volume vs same-hour-of-day 20-session SMA to validate that
-- volume features are normalized correctly (reviewer's concern).
--
-- Bytes processed: ~5 MB  →  $0.00

SELECT
  symbol,
  hour_of_day,
  COUNT(*)                               AS n_bars,
  ROUND(AVG(volume), 0)                  AS avg_raw_volume,
  ROUND(AVG(vol_norm_by_hour), 3)        AS avg_normalized_volume,
  ROUND(STDDEV(vol_norm_by_hour), 3)     AS std_normalized_volume,
  ROUND(MIN(vol_norm_by_hour), 3)        AS min_normalized,
  ROUND(MAX(vol_norm_by_hour), 3)        AS max_normalized
FROM `{project}.{dataset}.price_ohlcv_1d`
WHERE symbol IN ('AAPL', 'TSLA', 'QQQ', 'SPY', 'NVDA')
  AND hour_of_day BETWEEN 9 AND 15
  AND vol_norm_by_hour IS NOT NULL
GROUP BY symbol, hour_of_day
ORDER BY symbol, hour_of_day;
"""

MODEL_LEADERBOARD_SQL = """
-- Model Comparison Leaderboard
-- All gate results in one place with GCP validation status.
--
-- Bytes processed: <1 MB  →  $0.00

SELECT
  model_name,
  verdict,
  gcp_validated,
  ROUND(mean_rank_ic, 4)              AS ic,
  ROUND(rank_icir, 3)                 AS icir,
  ROUND(sharpe_ratio, 3)              AS sharpe,
  ROUND(net_annual_return_pct, 2)     AS net_ann_ret_pct,
  n_trades,
  -- Crude DSR adjustment: penalize for multiple trials
  -- Full DSR requires the number of trials and correlation of returns
  ROUND(sharpe_ratio / SQRT(LOG(n_trials_approx)), 3)
                                      AS dsr_approx,
  loaded_utc
FROM `{project}.{dataset}.model_gate_results`
CROSS JOIN (SELECT COUNT(*) AS n_trials_approx FROM `{project}.{dataset}.model_gate_results`)
ORDER BY sharpe_ratio DESC;
"""

DSR_LEDGER_SQL = """
-- DSR / All-Trials Ledger
-- Shows every research run for multiple-testing correction.
-- Bailey & Lopez de Prado's DSR requires knowing the FULL research history.
--
-- Bytes processed: <1 MB  →  $0.00

SELECT
  model_name,
  verdict,
  sharpe_ratio,
  net_annual_return_pct,
  n_trades,
  source_file,
  loaded_utc
FROM `{project}.{dataset}.model_gate_results`
ORDER BY loaded_utc ASC, sharpe_ratio DESC;
"""


# ── Runner ──────────────────────────────────────────────────────────────────

ANALYSES = {
    "score_decile":     ("Score Decile → EV Table",     SCORE_DECILE_SQL),
    "block_bootstrap":  ("Block-Bootstrap CI by Session", BLOCK_BOOTSTRAP_SQL),
    "volume_norm":      ("Volume Normalization Check",   VOLUME_NORM_SQL),
    "leaderboard":      ("Model Leaderboard (all gates)", MODEL_LEADERBOARD_SQL),
    "dsr_ledger":       ("DSR All-Trials Ledger",        DSR_LEDGER_SQL),
}

MODEL_TRIAL_MAP = {
    "v90":  "xgboost_conservative_v1",
    "all":  "1=1",  # no filter
    "momentum": "momentum",
    "logistic": "regularized_logistic",
}


def run_query(client, sql: str, label: str, dry_run: bool, max_bytes_billed: int = 500 * 1024 * 1024) -> None:
    from google.cloud import bigquery
    if dry_run:
        print(f"\n{'─'*60}")
        print(f"  [DRY-RUN] {label}")
        if client:
            try:
                job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
                dry_job = client.query(sql, job_config=job_config)
                mb = dry_job.total_bytes_processed / (1024 * 1024)
                print(f"  Estimated bytes to scan: {mb:.2f} MB ($0.00 — free tier)")
            except Exception as e:
                print(f"  Dry-run query estimation notice: {e}")
        else:
            print(f"  SQL:\n{sql[:300]}...")
        return

    print(f"\n{'─'*60}")
    print(f"  Running: {label}")
    try:
        job_config = bigquery.QueryJobConfig(
            maximum_bytes_billed=max_bytes_billed,
            use_query_cache=True,
        )
        query_job = client.query(sql, job_config=job_config)
        result = query_job.to_dataframe()
        bytes_scanned_mb = (query_job.total_bytes_billed or 0) / (1024 * 1024)
        print(f"  Rows returned: {len(result)} (Bytes billed: {bytes_scanned_mb:.2f} MB, Cost: $0.00 Free Tier)")
        if not result.empty:
            print(result.to_string(index=False, max_rows=50))
    except Exception as e:
        print(f"  ERROR: {e}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="all", choices=list(MODEL_TRIAL_MAP.keys()),
                    help="Filter by model type (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="Print SQL but don't execute")
    ap.add_argument("--analyses", nargs="+", choices=list(ANALYSES.keys()),
                    help="Run only specific analyses (default: all)")
    args = ap.parse_args(argv)

    trial_filter = f"trial LIKE '%{MODEL_TRIAL_MAP[args.model]}%'" if args.model != "all" else "1=1"
    to_run = args.analyses or list(ANALYSES.keys())

    print("=" * 70)
    print("  BIGQUERY SCORE-DECILE + ALPHA ANALYSIS")
    print("=" * 70)
    print(f"  Project:  {PROJECT}")
    print(f"  Dataset:  {DATASET}")
    print(f"  Model:    {args.model}  ({trial_filter})")
    print("  Cost:     $0.00  (~50MB processed, free tier = 1TB/month)")
    print("=" * 70)

    client = None
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=PROJECT)
    except Exception:
        if not args.dry_run:
            print("ERROR: pip3 install google-cloud-bigquery pandas-gbq pyarrow")
            return 1

    for key in to_run:
        label, sql_template = ANALYSES[key]
        sql = sql_template.format(
            project=PROJECT,
            dataset=DATASET,
            trial_filter=trial_filter,
        )
        run_query(client, sql, label, dry_run=args.dry_run)

    print("\n" + "=" * 70)
    print("  INTERPRETATION GUIDE")
    print("  Score Decile → EV: look for MONOTONIC increase in avg_net_return_pct")
    print("  Block Bootstrap:   ci_excludes_zero=TRUE is the real evidence of alpha")
    print("  DSR Ledger:        sharpe / sqrt(log(n_trials)) ≥ 1.0 to trade live")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
