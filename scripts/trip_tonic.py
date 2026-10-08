#!/usr/bin/env python3
"""Thin launcher kept for `python scripts/trip_tonic.py`; the implementation
lives in the trip_tonic package next to this file."""

import sys

from trip_tonic.cli import main

if __name__ == "__main__":
    sys.exit(main())
