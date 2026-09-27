#!/usr/bin/env python3
"""Launcher for the Edge Quantitative Trading Literature RAG & Model Doctor.

Usage examples:
  python3 tools/quant_rag.py ingest ~/Downloads/Research-Papers
  python3 tools/quant_rag.py stats
  python3 tools/quant_rag.py search "purged k-fold cross validation"
  python3 tools/quant_rag.py diagnose "My backtest Sharpe is 3.1 but live execution loses money due to slippage"
  python3 tools/quant_rag.py eval
"""

import os
from pathlib import Path
import sys

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load .env if present
try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from edge.rag.cli import main

if __name__ == "__main__":
    main()
