#!/usr/bin/env python3
"""Fail fast if the training container's environment drifted from the pins.

Job qlib-xs3-wide-sweep-v2 burned ~6 minutes of provisioning and install before
dying on `from numpy.core.numeric import ComplexWarning` -- a break that was
already decidable the moment pip finished. This runs first and costs ~2s.

Exit codes:
  0  environment matches edge/requirements-vertex.txt
  1  a required package is missing or unimportable
  2  a version differs from the pin (results would not be comparable to the
     GATE_XS* runs, which were all produced under edge/.venv-qlib)

Usage:
  python3 edge/tools/preflight_env.py             # enforce pins
  python3 edge/tools/preflight_env.py --warn-only # report drift, exit 0
"""
from __future__ import annotations

import argparse
import importlib
import sys

# (import name, distribution name, expected version or None to only require import)
# Kept in sync by hand with edge/requirements-vertex.txt -- deliberately, so that
# loosening a pin is a two-file edit somebody has to think about.
EXPECTED = [
    ("numpy", "numpy", "1.26.4"),
    ("pandas", "pandas", "2.3.3"),
    ("scipy", "scipy", "1.15.3"),
    ("sklearn", "scikit-learn", "1.7.2"),
    ("lightgbm", "lightgbm", "4.7.0"),
    ("torch", "torch", "2.4.1"),
    ("qlib", "pyqlib", None),          # git ref; version string is 0.9.8.devN
    ("ruamel.yaml", "ruamel.yaml", None),
    ("mlflow", "mlflow", None),
    ("pyarrow", "pyarrow", None),
]

# Imports that must succeed for the run to be possible at all. These are the
# ones that actually blew up: qlib.contrib.model pulls in sklearn transitively
# via qlib/contrib/model/linear.py, which is where the numpy 2.x break landed.
CRITICAL_IMPORTS = [
    "qlib",
    "qlib.contrib.model",              # <-- the exact module that raised
    "qlib.contrib.model.gbdt",
    "qlib.contrib.data.handler",
    "qlib.contrib.strategy",
    "sklearn.utils.validation",        # <-- the exact file that raised
]


def _version(mod) -> str:
    return getattr(mod, "__version__", "?")


def _canonical(version: str) -> str:
    """Strip a PEP 440 local version segment, e.g. "2.4.1+cpu" -> "2.4.1".

    FIX (2026-07-31): everything after '+' is build metadata, not the
    release -- "+cpu" vs "+cu121" vs nothing at all, depending on which
    wheel index supplied the package. requirements-vertex.txt installs
    torch via `--extra-index-url https://download.pytorch.org/whl/cpu`,
    which always reports `torch.__version__` as "<release>+cpu". Comparing
    that raw string against the bare release pin ("2.4.1") flagged every
    correctly-installed job as DRIFT and made this script exit 2 before any
    training code ran. That is what killed every job submitted between
    2026-07-31T03:27Z and 2026-07-31T20:31Z with "workerpool0-0 exited with
    a non-zero status of 2" -- confirmed via Cloud Logging on
    customJobs/5475037125676105728 and customJobs/1412086574346141696,
    both showing "[  DRIFT] torch  2.4.1+cpu  (pinned 2.4.1)" immediately
    before the FAIL line. Compare on the release segment only; the local
    segment is expected to vary by install channel and is not drift.
    """
    return version.split("+", 1)[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warn-only", action="store_true",
                    help="report drift but exit 0 anyway")
    ap.add_argument("--require-torch", action="store_true",
                    help="treat a missing torch as fatal (deep-model arms need it)")
    args = ap.parse_args()

    print("=" * 68)
    print("PREFLIGHT  edge/requirements-vertex.txt")
    print("=" * 68)

    missing: list[str] = []
    drifted: list[str] = []

    for import_name, dist_name, expected in EXPECTED:
        try:
            mod = importlib.import_module(import_name)
        except Exception as exc:  # noqa: BLE001 -- want the reason, whatever it is
            optional = import_name == "torch" and not args.require_torch
            tag = "SKIP" if optional else "MISSING"
            print(f"  [{tag:>7}] {dist_name:<16} {type(exc).__name__}: {exc}")
            if not optional:
                missing.append(dist_name)
            continue

        got = _version(mod)
        if expected is None:
            print(f"  [     ok] {dist_name:<16} {got}")
        elif _canonical(got) == expected:
            print(f"  [     ok] {dist_name:<16} {got}")
        else:
            print(f"  [  DRIFT] {dist_name:<16} {got}  (pinned {expected})")
            drifted.append(f"{dist_name} {got} != {expected}")

    print("-" * 68)
    for name in CRITICAL_IMPORTS:
        try:
            importlib.import_module(name)
            print(f"  [     ok] import {name}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [MISSING] import {name} -> {type(exc).__name__}: {exc}")
            missing.append(name)

    print("=" * 68)

    if missing:
        print(f"FAIL: {len(missing)} unimportable -> {', '.join(missing)}")
        print("This is the failure mode that killed customJobs/5094447772791209984.")
        return 0 if args.warn_only else 1

    if drifted:
        print(f"FAIL: {len(drifted)} version(s) drifted from the pins:")
        for d in drifted:
            print(f"  - {d}")
        print("Results under a drifted env are not comparable to the GATE_XS* "
              "numbers, which were produced under edge/.venv-qlib.")
        return 0 if args.warn_only else 2

    print("PASS: environment matches the pins.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
