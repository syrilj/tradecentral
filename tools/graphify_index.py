#!/usr/bin/env python3
"""Incremental, cached knowledge-graph indexer wrapping the `graphify` CLI.

The point of this wrapper is that repeated invocations should be cheap: it
walks the source tree, fingerprints every file, and compares that fingerprint
against a manifest written by the previous run. If nothing changed, `graphify`
is never invoked. If something changed, `graphify update` (its own
no-LLM-needed incremental re-extraction) is used instead of a full rebuild.
A full rebuild (`graphify extract`) only happens when the manifest is
missing/corrupt or `--force` is passed.

Examples:
  python3 edge/tools/graphify_index.py            # incremental: index only changed files
  python3 edge/tools/graphify_index.py --force    # full rebuild
  python3 edge/tools/graphify_index.py --status   # print staleness without indexing
  python3 edge/tools/graphify_index.py --json     # machine-readable status to stdout

This module is pure standard library (subprocess, hashlib, json, pathlib,
argparse) and runs unmodified under both the repo's .venv-qlib interpreter
and a bare system python3 — the `graphify` binary itself is invoked as a
subprocess, never imported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
MANIFEST_NAME = "index_manifest.json"
DEFAULT_TIMEOUT_S = 900

EDGE_ROOT = Path(__file__).resolve().parents[1]
GRAPH_DIR = EDGE_ROOT / "runs" / "graph"

GRAPHIFY_BIN = os.environ.get(
    "GRAPHIFY_BIN", str(Path.home() / "Library/Python/3.10/bin/graphify")
)

INCLUDE_EXTENSIONS = {".py", ".md", ".vue", ".ts", ".json"}

# Directory *names* excluded no matter where they appear in the tree.
EXCLUDE_DIR_NAMES = {
    ".git",
    ".venv-qlib",
    ".qlib-src",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "runs",
    "data",
    "models",
    "mlruns",
}

# Two-component relative path exclusions (parent, child) — matched wherever
# that consecutive pair occurs in the walked path.
EXCLUDE_PATH_PAIRS = {("dashboard", "dist")}

# LLM backend API keys graphify's `extract` command knows how to use. If none
# of these are present we pass --code-only so a full rebuild never fails for
# lack of credentials (AST-only extraction needs no key).
_LLM_BACKEND_ENV_KEYS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "MOONSHOT_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)


def _is_excluded_dir_name(name: str) -> bool:
    if name in EXCLUDE_DIR_NAMES:
        return True
    if name.startswith("qlib_xs"):
        return True
    return False


def _is_excluded_file(path: Path) -> bool:
    """True for anything that must never enter a graph artifact."""
    name = path.name
    lower = name.lower()
    if name == ".env":
        return True
    if lower.endswith(".key") or lower.endswith(".pem"):
        return True
    if "secret" in lower or "credential" in lower:
        return True
    return False


def _sha256_short(path: Path, length: int = 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:length]


def scan_source_files(source_root: Path) -> dict[str, dict]:
    """Walk source_root and fingerprint every included, non-excluded file.

    Returns {relpath (posix, relative to source_root): {mtime, size, sha256_short}}.
    """
    source_root = source_root.resolve()
    out: dict[str, dict] = {}
    for dirpath, dirnames, filenames in os.walk(source_root):
        dirnames[:] = sorted(d for d in dirnames if not _is_excluded_dir_name(d))
        dir_rel = Path(dirpath).resolve().relative_to(source_root)
        parts = dir_rel.parts
        if any(
            len(parts) >= idx + 2 and (parts[idx], parts[idx + 1]) in EXCLUDE_PATH_PAIRS
            for idx in range(len(parts))
        ):
            dirnames[:] = []
            continue
        for filename in filenames:
            file_path = Path(dirpath) / filename
            if file_path.suffix not in INCLUDE_EXTENSIONS:
                continue
            if _is_excluded_file(file_path):
                continue
            try:
                stat = file_path.stat()
            except OSError:
                continue
            relpath = file_path.resolve().relative_to(source_root).as_posix()
            out[relpath] = {
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "sha256_short": _sha256_short(file_path),
            }
    return out


def compute_content_fingerprint(files: dict[str, dict]) -> str:
    h = hashlib.sha256()
    for relpath in sorted(files):
        h.update(relpath.encode("utf-8"))
        h.update(b"\0")
        h.update(files[relpath]["sha256_short"].encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def load_manifest(manifest_path: Path) -> dict | None:
    """Return the parsed manifest, or None if missing/corrupt/malformed."""
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "files" not in data or not isinstance(data["files"], dict):
        return None
    return data


def diff_files(
    old_files: dict[str, dict], new_files: dict[str, dict]
) -> tuple[list[str], list[str], list[str]]:
    old_keys = set(old_files)
    new_keys = set(new_files)
    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    changed = sorted(
        k
        for k in old_keys & new_keys
        if old_files[k].get("sha256_short") != new_files[k].get("sha256_short")
    )
    return added, removed, changed


def _has_llm_backend_key(env: dict[str, str]) -> bool:
    return any(env.get(key) for key in _LLM_BACKEND_ENV_KEYS)


def get_graphify_version(timeout: int = 15) -> str | None:
    try:
        proc = subprocess.run(
            [GRAPHIFY_BIN, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (proc.stdout or "").strip()
    if not out:
        return None
    parts = out.split()
    return parts[-1] if len(parts) >= 2 else out


def run_graphify(
    mode: str, source_root: Path, graph_dir: Path, timeout: int
) -> subprocess.CompletedProcess:
    """Invoke the real graphify binary. mode is 'full' or 'incremental'."""
    env = dict(os.environ)
    env["GRAPHIFY_OUT"] = str(graph_dir.resolve())

    if mode == "full":
        cmd = [GRAPHIFY_BIN, "extract", str(source_root)]
        if not _has_llm_backend_key(env):
            # AST-only extraction needs no API key; avoids a hard failure
            # when no LLM backend is configured on this machine.
            cmd.append("--code-only")
    elif mode == "incremental":
        cmd = [GRAPHIFY_BIN, "update", str(source_root)]
    else:
        raise ValueError(f"unknown mode: {mode!r}")

    return subprocess.run(
        cmd,
        cwd=str(source_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _stderr_tail(stderr: str, max_lines: int = 40) -> str:
    lines = (stderr or "").strip().splitlines()
    return "\n".join(lines[-max_lines:])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit_status(payload: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, sort_keys=True))
        return
    if payload["stale"]:
        reasons = []
        if payload["manifest_corrupt"]:
            reasons.append("manifest corrupt")
        elif not payload["manifest_present"]:
            reasons.append("no manifest")
        if payload["added"]:
            reasons.append(f"{len(payload['added'])} added")
        if payload["removed"]:
            reasons.append(f"{len(payload['removed'])} removed")
        if payload["changed"]:
            reasons.append(f"{len(payload['changed'])} changed")
        print(f"graph is STALE ({', '.join(reasons) or 'unknown reason'})")
    else:
        when = payload["last_indexed_utc"] or "unknown time"
        print(f"graph is current ({payload['file_count']} files, last indexed {when})")


def run(
    *,
    source_root: Path,
    graph_dir: Path,
    force: bool = False,
    status_only: bool = False,
    as_json: bool = False,
    timeout: int = DEFAULT_TIMEOUT_S,
) -> int:
    source_root = source_root.resolve()
    manifest_path = graph_dir / MANIFEST_NAME

    current_files = scan_source_files(source_root)
    manifest_existed = manifest_path.exists()
    manifest = load_manifest(manifest_path)
    manifest_corrupt = manifest_existed and manifest is None

    if manifest is None:
        added = sorted(current_files)
        removed: list[str] = []
        changed: list[str] = []
        stale = True
    else:
        added, removed, changed = diff_files(manifest.get("files", {}), current_files)
        stale = bool(added or removed or changed)

    status_payload = {
        "stale": stale,
        "manifest_present": manifest is not None,
        "manifest_corrupt": manifest_corrupt,
        "file_count": len(current_files),
        "added": added,
        "removed": removed,
        "changed": changed,
        "last_indexed_utc": manifest.get("last_indexed_utc") if manifest else None,
        "graph_dir": str(graph_dir),
    }

    if status_only:
        _emit_status(status_payload, as_json=as_json)
        return 0

    # Staleness check happens BEFORE invoking graphify — this is the whole
    # point: an up-to-date graph with no --force short-circuits without ever
    # touching the graphify subprocess.
    if manifest is not None and not stale and not force:
        _emit_status({**status_payload, "ran": False}, as_json=as_json)
        return 0

    graph_dir.mkdir(parents=True, exist_ok=True)
    mode = "full" if (manifest is None or force) else "incremental"

    start = time.monotonic()
    try:
        proc = run_graphify(mode, source_root, graph_dir, timeout)
    except subprocess.TimeoutExpired:
        print(
            f"error: graphify {mode} run exceeded timeout of {timeout}s",
            file=sys.stderr,
        )
        return 1
    duration = time.monotonic() - start

    if proc.returncode != 0:
        print(
            f"error: graphify {mode} run failed with exit code {proc.returncode}",
            file=sys.stderr,
        )
        tail = _stderr_tail(proc.stderr)
        if tail:
            print(tail, file=sys.stderr)
        # Never write a manifest for a failed run — a stale manifest
        # claiming freshness is worse than no manifest.
        return proc.returncode or 1

    manifest_out = {
        "schema_version": SCHEMA_VERSION,
        "last_indexed_utc": _now_iso(),
        "graphify_version": get_graphify_version(),
        "source_root": str(source_root),
        "file_count": len(current_files),
        "content_fingerprint": compute_content_fingerprint(current_files),
        "files": current_files,
        "last_run": {
            "duration_s": round(duration, 3),
            "exit_code": proc.returncode,
            "mode": mode,
        },
    }
    manifest_path.write_text(
        json.dumps(manifest_out, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    result = {
        "ran": True,
        "mode": mode,
        "file_count": len(current_files),
        "duration_s": round(duration, 3),
    }
    if as_json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"graph indexed ({mode} run): {len(current_files)} files in {duration:.1f}s")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="Full rebuild even if the graph is current")
    parser.add_argument("--status", action="store_true", help="Print staleness without indexing")
    parser.add_argument("--json", action="store_true", help="Machine-readable output to stdout")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_S,
        help=f"Subprocess timeout in seconds (default {DEFAULT_TIMEOUT_S})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(
        source_root=EDGE_ROOT,
        graph_dir=GRAPH_DIR,
        force=args.force,
        status_only=args.status,
        as_json=args.json,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
