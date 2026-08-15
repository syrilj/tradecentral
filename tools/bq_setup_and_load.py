#!/usr/bin/env python3
"""bq_setup_and_load.py — Create BigQuery dataset + tables, batch-load all research data.

Completely free at this scale:
  - Storage:  10 GB/month free tier (we use ~200 MB)
  - Queries:  1 TB/month free tier (we process ~50 MB per query)
  - Loads:    Always free (batch, not streaming)

Tables created in dataset `trading_research` (project: gen-lang-client-0699310395):
  1. oof_inferences    — all OOF parquet rows (score, probability, return, regime)
  2. model_gate_results — one row per gate/model run (IC, Sharpe, verdict)
  3. v90_trades        — v90 holdout operating point trade log
  4. price_ohlcv_1d    — daily OHLCV for all symbols (for volume normalization)

Usage:
  python3 edge/tools/bq_setup_and_load.py           # full load
  python3 edge/tools/bq_setup_and_load.py --dry-run # show what would be loaded
  python3 edge/tools/bq_setup_and_load.py --tables oof_inferences model_gate_results
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EDGE = ROOT / "edge"
PROJECT = "gen-lang-client-0699310395"
DATASET = "trading_research"
LOCATION = "US"

# ── Schema definitions ──────────────────────────────────────────────────────

OOF_SCHEMA = [
    {"name": "timestamp",          "type": "TIMESTAMP"},
    {"name": "symbol",             "type": "STRING"},
    {"name": "trial",              "type": "STRING"},
    {"name": "fold",               "type": "INTEGER"},
    {"name": "holding_days",       "type": "INTEGER"},
    {"name": "raw_score",          "type": "FLOAT"},
    {"name": "probability",        "type": "FLOAT"},
    {"name": "direction",          "type": "INTEGER"},
    {"name": "forward_return",     "type": "FLOAT"},
    {"name": "gross_return",       "type": "FLOAT"},
    {"name": "net_return",         "type": "FLOAT"},
    {"name": "threshold",          "type": "FLOAT"},
    {"name": "sector",             "type": "STRING"},
    {"name": "volatility_regime",  "type": "STRING"},
    {"name": "trend_regime",       "type": "STRING"},
    {"name": "bear_market",        "type": "BOOL"},
    {"name": "run_id",             "type": "STRING"},
    {"name": "loaded_utc",         "type": "TIMESTAMP"},
]

GATE_RESULTS_SCHEMA = [
    {"name": "loaded_utc",         "type": "TIMESTAMP"},
    {"name": "model_name",         "type": "STRING"},
    {"name": "gate_file",          "type": "STRING"},
    {"name": "verdict",            "type": "STRING"},
    {"name": "gcp_validated",      "type": "BOOL"},
    {"name": "mean_rank_ic",       "type": "FLOAT"},
    {"name": "rank_icir",          "type": "FLOAT"},
    {"name": "sharpe_ratio",       "type": "FLOAT"},
    {"name": "net_annual_return_pct", "type": "FLOAT"},
    {"name": "annual_turnover",    "type": "FLOAT"},
    {"name": "cost_drag_pct",      "type": "FLOAT"},
    {"name": "n_trades",           "type": "INTEGER"},
    {"name": "source_file",        "type": "STRING"},
]

V90_TRADES_SCHEMA = [
    {"name": "loaded_utc",         "type": "TIMESTAMP"},
    {"name": "operating_point",    "type": "STRING"},
    {"name": "side",               "type": "STRING"},
    {"name": "symbol",             "type": "STRING"},
    {"name": "raw_score_long",     "type": "FLOAT"},
    {"name": "raw_score_short",    "type": "FLOAT"},
    {"name": "cal_prob_long",      "type": "FLOAT"},
    {"name": "cal_prob_short",     "type": "FLOAT"},
    {"name": "threshold",          "type": "FLOAT"},
    {"name": "net_return",         "type": "FLOAT"},
    {"name": "win",                "type": "BOOL"},
]

OHLCV_SCHEMA = [
    {"name": "date",               "type": "DATE"},
    {"name": "symbol",             "type": "STRING"},
    {"name": "open",               "type": "FLOAT"},
    {"name": "high",               "type": "FLOAT"},
    {"name": "low",                "type": "FLOAT"},
    {"name": "close",              "type": "FLOAT"},
    {"name": "volume",             "type": "FLOAT"},
    {"name": "hour_of_day",        "type": "INTEGER"},  # for 1H data
    {"name": "vol_norm_by_hour",   "type": "FLOAT"},    # volume / same-hour 20d SMA
]

SIGNAL_JOURNAL_SIGNALS_SCHEMA = [
    {"name": "id",                 "type": "STRING"},
    {"name": "signal_type",        "type": "STRING"},
    {"name": "source",             "type": "STRING"},
    {"name": "ticker",             "type": "STRING"},
    {"name": "contract_key",       "type": "STRING"},
    {"name": "ts_utc",             "type": "STRING"},
    {"name": "trading_date",       "type": "STRING"},
    {"name": "score",              "type": "FLOAT"},
    {"name": "grade",              "type": "STRING"},
    {"name": "direction",          "type": "STRING"},
    {"name": "entry_ref_price",    "type": "FLOAT"},
    {"name": "spy_ref_price",      "type": "FLOAT"},
    {"name": "features",           "type": "STRING"},
    {"name": "regime_risk",        "type": "STRING"},
    {"name": "gex_regime",         "type": "STRING"},
    {"name": "dist_to_flip_pct",   "type": "FLOAT"},
    {"name": "trend",              "type": "STRING"},
    {"name": "structure",          "type": "STRING"},
    {"name": "first_seen",         "type": "STRING"},
    {"name": "last_seen",          "type": "STRING"},
    {"name": "seen_count",         "type": "INTEGER"},
    {"name": "replayed",           "type": "BOOL"},
    {"name": "loaded_utc",         "type": "TIMESTAMP"},
]

SIGNAL_JOURNAL_OUTCOMES_SCHEMA = [
    {"name": "signal_id",          "type": "STRING"},
    {"name": "horizon",            "type": "STRING"},
    {"name": "fwd_return",         "type": "FLOAT"},
    {"name": "fwd_return_excess",  "type": "FLOAT"},
    {"name": "exit_price",         "type": "FLOAT"},
    {"name": "filled_at",          "type": "STRING"},
    {"name": "loaded_utc",         "type": "TIMESTAMP"},
]


# ── Data builders ───────────────────────────────────────────────────────────

def build_signal_journal_signals_df() -> pd.DataFrame:
    import sqlite3
    db_paths = [
        ROOT / "TradingWork" / "data" / "signal_journal.db",
        EDGE / "data" / "signal_journal.db",
    ]
    for db_path in db_paths:
        try:
            if db_path.exists() and db_path.is_file():
                conn = sqlite3.connect(str(db_path))
                df = pd.read_sql_query("SELECT * FROM signals", conn)
                conn.close()
                df["loaded_utc"] = pd.Timestamp.now(tz="UTC")
                print(f"  Signal Journal Signals: {len(df):,} rows")
                return df
        except Exception:
            pass
    print("  signal_journal.db not found — skipping signals table")
    return pd.DataFrame()

def build_signal_journal_outcomes_df() -> pd.DataFrame:
    import sqlite3
    db_paths = [
        ROOT / "TradingWork" / "data" / "signal_journal.db",
        EDGE / "data" / "signal_journal.db",
    ]
    for db_path in db_paths:
        try:
            if db_path.exists() and db_path.is_file():
                conn = sqlite3.connect(str(db_path))
                df = pd.read_sql_query("SELECT * FROM outcomes", conn)
                conn.close()
                df["loaded_utc"] = pd.Timestamp.now(tz="UTC")
                print(f"  Signal Journal Outcomes: {len(df):,} rows")
                return df
        except Exception:
            pass
    print("  signal_journal.db not found — skipping outcomes table")
    return pd.DataFrame()

def load_oof_inferences(client, table_id: str, dry_run: bool = False) -> None:
    """Load all OOF parquet files from directional_daily_v1 directly into BigQuery."""
    now_ts = pd.Timestamp.now(tz="UTC")
    files = list((EDGE / "runs" / "research" / "directional_daily_v1").glob("**/*.parquet"))
    files += list((EDGE / "runs" / "walkforward").glob("**/*.parquet"))
    print(f"  Found {len(files)} OOF parquet files to process.")
    
    total_rows = 0
    batch = []
    
    for i, pq in enumerate(files):
        parts = pq.stem.split("_")
        holding_days = int(parts[1].replace("d", "")) if len(parts) > 1 and parts[1].endswith("d") and parts[1][:-1].isdigit() else 0
        try:
            df = pd.read_parquet(pq)
            df = df.reset_index()
            fwd_col = next((c for c in df.columns if "forward_return" in c), None)
            dir_col = next((c for c in df.columns if "direction" in c), None)
            
            clean_df = pd.DataFrame()
            if "timestamp" in df.columns:
                clean_df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize("UTC")
            elif "date" in df.columns:
                clean_df["timestamp"] = pd.to_datetime(df["date"]).dt.tz_localize("UTC")
            else:
                continue
            
            clean_df["symbol"] = df["symbol"].astype(str) if "symbol" in df.columns else ""
            clean_df["trial"] = df["trial"].astype(str) if "trial" in df.columns else pq.stem
            clean_df["fold"] = df["fold"].fillna(0).astype(int) if "fold" in df.columns else 0
            clean_df["holding_days"] = holding_days
            clean_df["raw_score"] = df["raw_score"].astype(float) if "raw_score" in df.columns else np.nan
            clean_df["probability"] = df["probability"].astype(float) if "probability" in df.columns else np.nan
            clean_df["direction"] = df[dir_col].fillna(0).astype(int) if dir_col else 0
            clean_df["forward_return"] = df[fwd_col].astype(float) if fwd_col else np.nan
            clean_df["gross_return"] = df["gross_return"].astype(float) if "gross_return" in df.columns else np.nan
            clean_df["net_return"] = df["net_return"].astype(float) if "net_return" in df.columns else np.nan
            clean_df["threshold"] = df["threshold"].astype(float) if "threshold" in df.columns else 0.5
            clean_df["sector"] = df["sector"].astype(str) if "sector" in df.columns else ""
            clean_df["volatility_regime"] = df["volatility_regime"].astype(str) if "volatility_regime" in df.columns else ""
            clean_df["trend_regime"] = df["trend_regime"].astype(str) if "trend_regime" in df.columns else ""
            clean_df["bear_market"] = df["bear_market"].fillna(False).astype(bool) if "bear_market" in df.columns else False
            clean_df["run_id"] = pq.parent.name
            clean_df["loaded_utc"] = now_ts
            
            batch.append(clean_df)
            total_rows += len(clean_df)
            
            # Load in chunks of 5 files to keep RAM tiny
            if len(batch) >= 5 or i == len(files) - 1:
                chunk_df = pd.concat(batch, ignore_index=True)
                if not dry_run:
                    batch_load(client, table_id, chunk_df, dry_run=False)
                else:
                    print(f"  [DRY-RUN] Chunk {i+1}/{len(files)}: {len(chunk_df):,} rows")
                batch = []
                
        except Exception as e:
            print(f"  Warning: could not process {pq.name}: {e}")

    print(f"  OOF data total: {total_rows:,} rows across {len(files)} files processed.")


def build_gate_results_df() -> pd.DataFrame:
    """Load all results.json files and produce one row per model."""
    model_dirs = {
        "PEAD Catalyst":          EDGE / "runs" / "pead_catalyst" / "results.json",
        "FINRA Short Vol":         EDGE / "runs" / "finra_factor" / "results.json",
        "V90 Meta-Confidence":     EDGE / "models" / "v90" / "results.json",
        "V90 Wide (control)":      EDGE / "models" / "v90_wide" / "results.json",
        "Volatility Timing":       EDGE / "runs" / "vol_timing" / "results.json",
        "XS3 LightGBM 557":        EDGE / "runs" / "qlib_xs3" / "results.json",
        "XS2 Cross-Sect 40":       EDGE / "runs" / "qlib_xs2" / "results.json",
        "PEAD v2 (VWAP)":          EDGE / "runs" / "pead_v2" / "results.json",
        "PEAD XGBoost":            EDGE / "runs" / "pead_xgb" / "results.json",
        "LightGBM Hybrid":         EDGE / "runs" / "lgbm_hybrid" / "results.json",
    }
    now_ts = pd.Timestamp.now(tz="UTC")
    rows = []
    for model_name, path in model_dirs.items():
        if not path.exists():
            continue
        try:
            r = json.loads(path.read_text())
        except Exception:
            continue
        # Net return: handle both fraction and percentage representations
        net = r.get("net_annual_return_pct", r.get("net_annual_return", 0.0))
        if net is not None and abs(float(net)) < 5 and "pct" not in str(list(r.keys())):
            net = float(net) * 100  # convert fraction to %
        rows.append({
            "loaded_utc": now_ts,
            "model_name": model_name,
            "gate_file": r.get("gate", path.parent.name),
            "verdict": r.get("verdict", "UNKNOWN"),
            "gcp_validated": bool(r.get("gcp_validated", False)),
            "mean_rank_ic": float(r.get("mean_rank_ic", 0.0) or 0.0),
            "rank_icir": float(r.get("rank_icir", 0.0) or 0.0),
            "sharpe_ratio": float(r.get("sharpe_ratio", 0.0) or 0.0),
            "net_annual_return_pct": float(net or 0.0),
            "annual_turnover": float(r.get("annual_turnover", 0.0) or 0.0),
            "cost_drag_pct": float(r.get("cost_drag_pct", 0.0) or 0.0),
            "n_trades": int(r.get("n_trades", r.get("n_ic_observations", 0)) or 0),
            "source_file": str(path),
        })
    df = pd.DataFrame(rows)
    print(f"  Gate results: {len(df)} model records")
    return df


def build_v90_trades_df() -> pd.DataFrame:
    """Extract v90 holdout operating point trade records from results.json."""
    path = EDGE / "models" / "v90" / "results.json"
    if not path.exists():
        print("  v90 results.json not found — skipping trade table")
        return pd.DataFrame()
    r = json.loads(path.read_text())
    now_ts = pd.Timestamp.now(tz="UTC")
    rows = []
    ops = r.get("holdout_operating_points", {})
    for op_name, op_data in ops.items():
        trades = op_data.get("trades", [])
        if not trades:
            # Try to build synthetic rows from aggregate stats
            n = op_data.get("n", 0)
            if n == 0:
                continue
            win_rate = op_data.get("win_rate", 0.5)
            avg_ret = op_data.get("avg_net_return", 0.0)
            for i in range(n):
                rows.append({
                    "loaded_utc": now_ts,
                    "operating_point": op_name,
                    "side": "LONG",
                    "symbol": "AGGREGATE",
                    "raw_score_long": float(op_data.get("threshold", 0.67)),
                    "raw_score_short": 0.0,
                    "cal_prob_long": float(win_rate),
                    "cal_prob_short": 0.0,
                    "threshold": float(op_data.get("threshold", 0.67)),
                    "net_return": float(avg_ret),
                    "win": (i / n) < win_rate,
                })
        else:
            for t in trades:
                rows.append({
                    "loaded_utc": now_ts,
                    "operating_point": op_name,
                    "side": t.get("side", "LONG"),
                    "symbol": t.get("symbol", "UNKNOWN"),
                    "raw_score_long": float(t.get("raw_long", 0.0)),
                    "raw_score_short": float(t.get("raw_short", 0.0)),
                    "cal_prob_long": float(t.get("cal_long", 0.0)),
                    "cal_prob_short": float(t.get("cal_short", 0.0)),
                    "threshold": float(t.get("threshold", 0.67)),
                    "net_return": float(t.get("net_return", 0.0)),
                    "win": bool(t.get("net_return", 0.0) > 0),
                })
    df = pd.DataFrame(rows)
    print(f"  V90 trades: {len(df)} records across {len(ops)} operating points")
    return df


def build_ohlcv_df() -> pd.DataFrame:
    """Load 1D OHLCV parquet files and add hour-normalized volume column."""
    data_1d = EDGE / "data" / "1d"
    if not data_1d.exists():
        print("  1D data dir not found — skipping OHLCV table")
        return pd.DataFrame()
    rows = []
    for pq in list(data_1d.glob("*.parquet"))[:50]:  # cap at 50 symbols to stay well inside free tier
        sym = pq.stem
        try:
            df = pd.read_parquet(pq)
            df.columns = [c.lower() for c in df.columns]
            needed = {"open", "high", "low", "close", "volume"}
            if not needed.issubset(df.columns):
                continue
            df = df[list(needed)].copy()
            df["symbol"] = sym
            df["date"] = pd.to_datetime(df.index.date)
            df["hour_of_day"] = df.index.hour if hasattr(df.index, "hour") else 0
            # Volume normalized by same hour-of-day, rolling 20 sessions
            if df["hour_of_day"].nunique() > 1:
                df["vol_norm_by_hour"] = (
                    df.groupby("hour_of_day")["volume"]
                    .transform(lambda s: s / s.rolling(20, min_periods=5).mean().shift(1))
                )
            else:
                df["vol_norm_by_hour"] = df["volume"] / df["volume"].rolling(20, min_periods=5).mean().shift(1)
            rows.append(df.reset_index(drop=True))
        except Exception as e:
            print(f"  Warning: {sym}: {e}")
    if not rows:
        return pd.DataFrame()
    result = pd.concat(rows, ignore_index=True)
    # Rename index col if present
    if "index" in result.columns:
        result = result.drop(columns=["index"])
    print(f"  OHLCV: {len(result):,} rows, {result['symbol'].nunique()} symbols")
    return result


# ── BigQuery helpers ────────────────────────────────────────────────────────

def ensure_dataset(client) -> None:
    from google.cloud import bigquery
    ds_ref = f"{PROJECT}.{DATASET}"
    try:
        client.get_dataset(ds_ref)
        print(f"  Dataset {ds_ref} already exists.")
    except Exception:
        ds = bigquery.Dataset(ds_ref)
        ds.location = LOCATION
        ds.description = "Trading research: OOF inferences, model gate results, price data"
        client.create_dataset(ds, timeout=30)
        print(f"  Created dataset {ds_ref}")


def ensure_table(client, table_name: str, schema_dicts: list, dry_run: bool = False) -> str:
    from google.cloud import bigquery
    table_id = f"{PROJECT}.{DATASET}.{table_name}"
    schema = [bigquery.SchemaField(s["name"], s["type"]) for s in schema_dicts]
    if dry_run:
        print(f"  [DRY-RUN] Would create/confirm table {table_id} (Partitioned + Clustered)")
        return table_id
    try:
        client.get_table(table_id)
        print(f"  Table {table_id} already exists.")
    except Exception:
        table = bigquery.Table(table_id, schema=schema)
        # Partition by date on timestamp/loaded_utc column with 180-day partition expiration
        if any(s["name"] in ("timestamp", "loaded_utc") for s in schema_dicts):
            partition_field = "loaded_utc" if any(s["name"] == "loaded_utc" for s in schema_dicts) else "timestamp"
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field=partition_field,
                expiration_ms=180 * 24 * 60 * 60 * 1000,  # 180 days auto-prune
            )
        # Apply cost-optimizing clustering on high-cardinality query keys
        clustering_map = {
            "oof_inferences": ["symbol", "trial"],
            "model_gate_results": ["model_name", "verdict"],
            "v90_trades": ["operating_point", "symbol"],
            "price_ohlcv_1d": ["symbol"],
            "signal_journal_signals": ["ticker", "signal_type"],
            "signal_journal_outcomes": ["signal_id", "horizon"],
        }
        if table_name in clustering_map:
            table.clustering_fields = clustering_map[table_name]
            print(f"  [Cost Opt] Configured BigQuery clustering: {table.clustering_fields}")

        client.create_table(table, timeout=30)
        print(f"  Created table {table_id} (Partitioned + Clustered)")
    return table_id


def batch_load(client, table_id: str, df: pd.DataFrame, dry_run: bool = False) -> None:
    from google.cloud import bigquery
    if df.empty:
        print(f"  Skipping empty DataFrame for {table_id}")
        return
    # Convert date columns to string for BQ compatibility
    for col in df.columns:
        if col in ("timestamp", "loaded_utc"):
            df[col] = pd.to_datetime(df[col], utc=True)
        elif df[col].dtype == object:
            df[col] = df[col].astype(str)
    size_mb = df.memory_usage(deep=True).sum() / 1e6
    print(f"  Loading {len(df):,} rows ({size_mb:.1f} MB) into {table_id} ...")
    if dry_run:
        print(f"  [DRY-RUN] Would load {len(df):,} rows — $0.00 (batch load)")
        return
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_APPEND",
        source_format=bigquery.SourceFormat.PARQUET,
    )
    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result(timeout=300)
    print(f"  ✅ Loaded {job.output_rows:,} rows → {table_id}  ($0.00 — batch load, free tier)")


# ── Main ────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Show what would be loaded without touching BQ")
    ap.add_argument("--tables", nargs="+",
                    choices=["oof_inferences", "model_gate_results", "v90_trades", "price_ohlcv_1d", "signal_journal_signals", "signal_journal_outcomes"],
                    help="Load only specific tables (default: all)")
    args = ap.parse_args(argv)

    tables_to_load = args.tables or ["oof_inferences", "model_gate_results", "v90_trades", "price_ohlcv_1d", "signal_journal_signals", "signal_journal_outcomes"]

    print("=" * 70)
    print("  BIGQUERY BATCH LOAD — trading_research dataset")
    print("=" * 70)
    print(f"  Project:   {PROJECT}")
    print(f"  Dataset:   {DATASET}")
    print(f"  Tables:    {', '.join(tables_to_load)}")
    print(f"  Dry-run:   {args.dry_run}")
    print(f"  Cost:      $0.00  (batch load + free tier queries)")
    print("=" * 70)

    if not args.dry_run:
        try:
            from google.cloud import bigquery
        except ImportError:
            print("ERROR: google-cloud-bigquery not installed.")
            print("Run: pip3 install google-cloud-bigquery google-cloud-bigquery-storage pyarrow")
            return 1
        client = bigquery.Client(project=PROJECT)
        ensure_dataset(client)
    else:
        client = None

    table_map = {
        "model_gate_results":     (GATE_RESULTS_SCHEMA,            build_gate_results_df),
        "v90_trades":             (V90_TRADES_SCHEMA,               build_v90_trades_df),
        "price_ohlcv_1d":         (OHLCV_SCHEMA,                    build_ohlcv_df),
        "signal_journal_signals": (SIGNAL_JOURNAL_SIGNALS_SCHEMA,  build_signal_journal_signals_df),
        "signal_journal_outcomes":(SIGNAL_JOURNAL_OUTCOMES_SCHEMA, build_signal_journal_outcomes_df),
    }

    for table_name in tables_to_load:
        print(f"\n[{table_name}]")
        if table_name == "oof_inferences":
            table_id = ensure_table(client, table_name, OOF_SCHEMA, dry_run=args.dry_run)
            load_oof_inferences(client, table_id, dry_run=args.dry_run)
        else:
            schema, builder = table_map[table_name]
            table_id = ensure_table(client, table_name, schema, dry_run=args.dry_run)
            df = builder()
            if not df.empty:
                batch_load(client, table_id, df, dry_run=args.dry_run)

    print("\n" + "=" * 70)
    print("  LOAD COMPLETE")
    print("  Now run the score-decile analysis query:")
    print("  python3 edge/tools/bq_score_decile_analysis.py")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
