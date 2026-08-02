-- ============================================================================
-- BigQuery AI/ML Out-of-Sample Walk-Forward Stability & Decile Analysis
-- Dataset: gen-lang-client-0699310395.trading_research
-- ============================================================================

-- Query 1: Out-of-Sample Decile Spread & Rank IC Analysis by Walk-Forward Fold
WITH ranked_inferences AS (
  SELECT
    DATE(timestamp) AS eval_date,
    symbol,
    trial,
    fold,
    probability,
    forward_return,
    net_return,
    NTILE(10) OVER (PARTITION BY DATE(timestamp) ORDER BY probability ASC) AS decile
  FROM
    `gen-lang-client-0699310395.trading_research.oof_inferences`
  WHERE
    probability IS NOT NULL
    AND forward_return IS NOT NULL
)
SELECT
  decile,
  COUNT(1) AS total_events,
  AVG(probability) AS avg_model_probability,
  AVG(forward_return) * 100 AS avg_forward_return_pct,
  AVG(net_return) * 100 AS avg_net_return_pct,
  SUM(CASE WHEN net_return > 0 THEN 1 ELSE 0 END) / COUNT(1) * 100 AS win_rate_pct
FROM
  ranked_inferences
GROUP BY
  decile
ORDER BY
  decile ASC;

-- Query 2: Multi-Year Temporal Stability (Yearly Out-of-Sample Performance)
SELECT
  EXTRACT(YEAR FROM timestamp) AS eval_year,
  COUNT(1) AS total_inferences,
  COUNTIF(direction != 0) AS total_active_trades,
  AVG(CASE WHEN direction != 0 THEN net_return END) * 100 AS avg_trade_net_pct,
  COUNTIF(direction != 0 AND net_return > 0) / NULLIF(COUNTIF(direction != 0), 0) * 100 AS win_rate_pct,
  CORR(probability, forward_return) AS rank_ic
FROM
  `gen-lang-client-0699310395.trading_research.oof_inferences`
GROUP BY
  eval_year
ORDER BY
  eval_year ASC;
