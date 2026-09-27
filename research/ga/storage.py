"""Persist and load GA evolution runs for the API / dashboard."""
from __future__ import annotations

from dataclasses import is_dataclass
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .evolve import EvolutionResult

EDGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GA_RUNS_DIR = EDGE_ROOT / "runs" / "ga"


def _to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return _to_jsonable(obj.as_dict() if hasattr(obj, "as_dict") else obj.__dict__)
    if hasattr(obj, "as_dict"):
        return obj.as_dict()
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def write_run(result: "EvolutionResult", output_dir: Path) -> Path:
    """Write summary + elites + history under ``output_dir / run_id``."""
    run_dir = Path(output_dir) / result.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = _to_jsonable(result.as_dict())
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (run_dir / "elites.json").write_text(
        json.dumps(payload.get("elites", []), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "history.json").write_text(
        json.dumps(payload.get("history", []), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "confirmation.json").write_text(
        json.dumps(payload.get("confirmation", []), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    # Pointer for "latest" convenience
    latest = Path(output_dir) / "LATEST.json"
    latest.write_text(
        json.dumps({"run_id": result.run_id, "path": str(summary_path)}, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary_path


def list_runs(runs_dir: str | Path = DEFAULT_GA_RUNS_DIR) -> list[dict[str, Any]]:
    root = Path(runs_dir)
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/summary.json"), reverse=True):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        history = raw.get("history") or []
        best = history[-1] if history else {}
        conf = raw.get("confirmation") or []
        passes = sum(1 for c in conf if c.get("passes_confirmation"))
        rows.append(
            {
                "run_id": raw.get("run_id") or path.parent.name,
                "created_at": raw.get("created_at"),
                "n_generations": len(history),
                "population_size": (raw.get("config") or {}).get("population_size"),
                "best_fitness": best.get("best_fitness"),
                "alive_final": best.get("alive_count"),
                "n_elites": len(raw.get("elites") or []),
                "confirmation_passes": passes,
                "confirmation_total": len(conf),
                "n_symbols": len(raw.get("symbols") or []),
                "decision_authorized": bool(raw.get("decision_authorized", False)),
                "path": str(path),
            }
        )
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def load_run_summary(run_id: str, runs_dir: str | Path = DEFAULT_GA_RUNS_DIR) -> dict[str, Any]:
    path = Path(runs_dir) / run_id / "summary.json"
    if not path.is_file():
        # also allow bare path-like id that is already a full summary path parent
        alt = Path(runs_dir) / run_id
        if alt.is_file() and alt.name == "summary.json":
            path = alt
        else:
            raise FileNotFoundError(f"GA run not found: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def run_payload(run_id: str | None = None, runs_dir: str | Path = DEFAULT_GA_RUNS_DIR) -> dict[str, Any]:
    """Dashboard-facing aggregate: list + optional detail + latest pointer."""
    runs = list_runs(runs_dir)
    latest_id: str | None = None
    latest_ptr = Path(runs_dir) / "LATEST.json"
    if latest_ptr.is_file():
        try:
            latest_id = json.loads(latest_ptr.read_text(encoding="utf-8")).get("run_id")
        except (OSError, json.JSONDecodeError):
            latest_id = None
    if run_id is None and latest_id:
        run_id = latest_id
    if run_id is None and runs:
        run_id = str(runs[0]["run_id"])

    detail: dict[str, Any] | None = None
    error: str | None = None
    if run_id:
        try:
            detail = load_run_summary(run_id, runs_dir)
        except FileNotFoundError as exc:
            error = str(exc)

    return {
        "schema_version": "ga_api_v1",
        "runs_dir": str(Path(runs_dir)),
        "latest_run_id": latest_id,
        "selected_run_id": run_id,
        "runs": runs,
        "detail": detail,
        "error": error,
        "decision_authorized": False,
        "notes": [
            "Genetic evolution artifacts are research-only.",
            "Terminal holdout is sealed and never used for fitness.",
            "Promote survivors only through the existing gate/shadow process.",
        ],
    }
