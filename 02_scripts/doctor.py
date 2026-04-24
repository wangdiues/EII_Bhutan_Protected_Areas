#!/usr/bin/env python3
"""Compatibility wrapper for the research doctor workflow."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import research_ops


if __name__ == "__main__":
    sys.argv.insert(1, "doctor")
    raise SystemExit(research_ops.main())
