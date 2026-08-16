import json
import time
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

from daily_plays.adapters.internal_models import ChainFreeInternalModelsAdapter
from daily_plays.clock import RunContext


def setup_benchmark_data(tmp_dir: Path, num_symbols: int = 100) -> tuple[Path, Path]:
    data_dir = tmp_dir / "1d"
    data_dir.mkdir(parents=True, exist_ok=True)

    symbols = [f"SYM{i:03d}" for i in range(num_symbols)]
    universe_path = tmp_dir / "universe.json"
    universe_path.write_text(json.dumps({"symbols": symbols}))

    dates = pd.date_range("2026-02-20", periods=160, freq="D")
    for symbol in symbols:
        close = [100.0 + i * 0.1 for i in range(len(dates))]
        df = pd.DataFrame(
            {
                "open": close,
                "high": [x + 1.0 for x in close],
                "low": [x - 1.0 for x in close],
                "close": close,
                "volume": [10000] * len(dates),
            },
            index=dates,
        )
        df.to_parquet(data_dir / f"{symbol}.parquet")

    return universe_path, data_dir


def run_benchmark(num_symbols: int = 100, iterations: int = 10) -> float:
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)
        universe_path, data_dir = setup_benchmark_data(tmp_dir, num_symbols=num_symbols)

        adapter = ChainFreeInternalModelsAdapter(
            universe_path=universe_path, data_path=data_dir, candidate_limit=num_symbols
        )
        asof_dt = datetime(2026, 7, 29, tzinfo=timezone.utc)
        context = RunContext.create(asof_utc=asof_dt)

        # Warmup
        warmup_results = list(adapter(context=context))

        start_time = time.perf_counter()
        for _ in range(iterations):
            results = list(adapter(context=context))
        end_time = time.perf_counter()

        avg_time_ms = ((end_time - start_time) / iterations) * 1000.0
        print(f"Benchmark: {num_symbols} symbols, {iterations} iterations.")
        print(f"Candidates returned per run: {len(results)}")
        print(f"Average execution time per run: {avg_time_ms:.2f} ms")
        return avg_time_ms


if __name__ == "__main__":
    run_benchmark(num_symbols=100, iterations=10)
