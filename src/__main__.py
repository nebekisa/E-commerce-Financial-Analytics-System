"""Enables `python -m src ...` as an alias for `python -m src.cli ...`."""

from __future__ import annotations

import sys

from src.cli import main

if __name__ == "__main__":
    sys.exit(main())
