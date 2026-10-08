"""Pip constraints for the Qt build the Windows installer ships.

The test job installs with these constraints so CI cannot float to a newer
PySide6 than win-installer/requirements-win-amd64-cp314.txt. Hashes are
stripped: a constraints file that carries any hash forces hashes on every
other requirement, which this install does not have.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_RELATIVE = Path("win-installer/requirements-win-amd64-cp314.txt")

# Names match the lock file. PySide6 6.12 split Pdf and WebEngine into extra
# wheels; those names are not in the 6.11.2 lock, so they are not pinned here.
QT_NAMES = (
    "PySide6",
    "PySide6_Addons",
    "PySide6_Essentials",
    "shiboken6",
)


def pins_from_lock(text: str) -> list[str]:
    found: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pin = line.split("--hash", 1)[0].strip()
        if "==" not in pin:
            continue
        name, version = pin.split("==", 1)
        name = name.strip()
        version = version.strip()
        if name not in QT_NAMES:
            continue
        if not version or any(ch.isspace() for ch in version):
            raise ValueError(f"installer lock has an unreadable pin for {name}")
        found[name] = f"{name}=={version}"
    missing = [name for name in QT_NAMES if name not in found]
    if missing:
        raise ValueError(f"installer lock is missing {', '.join(missing)}")
    return [found[name] for name in QT_NAMES]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        help="write constraints here as UTF-8. Default is stdout.",
    )
    args = parser.parse_args(argv)
    text = (ROOT / LOCK_RELATIVE).read_text(encoding="utf-8")
    body = "\n".join(pins_from_lock(text)) + "\n"
    if args.out is None:
        sys.stdout.write(body)
    else:
        args.out.write_text(body, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
