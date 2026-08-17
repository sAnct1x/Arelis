#!/usr/bin/env python3
"""Helpers for the offline Hey Arelis openWakeWord model.

This script does NOT train. It checks the expected artifact path and prints the
recommended training workflow (easy-oww / Piper synthetic data).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "models" / "wake" / "hey_arelis.onnx"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 0 if hey_arelis.onnx exists, else 1.",
    )
    args = parser.parse_args()
    print(f"Expected model: {TARGET}")
    if TARGET.is_file():
        print(f"Found ({TARGET.stat().st_size} bytes).")
        print("voice.wake.engine: auto will use openWakeWord.")
        return 0
    print("Missing. Train offline, then copy the ONNX here.")
    print()
    print("Recommended:")
    print("  1. Install easy-oww (https://github.com/pjdoland/easy-oww)")
    print("  2. Generate Piper synthetic clips for 'Hey Arelis' only (not bare 'Arelis')")
    print("  3. Train + export ONNX")
    print(f"  4. Copy to {TARGET}")
    print()
    print("Until then, keep voice.wake.engine: whisper (or auto -> whisper).")
    return 1 if args.check else 0


if __name__ == "__main__":
    sys.exit(main())
