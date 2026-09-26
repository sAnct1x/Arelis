"""Mint a release keystore for the companion. Never writes into the repo.

The repository is public. A keystore that lands in git is a keystore
everybody has, and every phone that trusted it can be impersonated.

This writes to the user data directory (the same place Arelis already
keeps secrets) and prints the GitHub secret names. You add those secrets
yourself. This script will not print the private key in a form that
belongs in a commit.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def dest_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        root = Path(base) / "Arelis" if base else Path.home() / "AppData" / "Local" / "Arelis"
    else:
        xdg = os.environ.get("XDG_DATA_HOME", "").strip()
        root = Path(xdg) / "arelis" if xdg else Path.home() / ".local" / "share" / "arelis"
    return root / "android"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alias", default="arelis")
    parser.add_argument(
        "--out",
        default="",
        help="Keystore path. Default: user-data android/arelis-companion.jks",
    )
    args = parser.parse_args()
    keytool = shutil.which("keytool")
    if keytool is None:
        print("keytool is not on PATH. Install a JDK.", file=sys.stderr)
        return 2
    path = Path(args.out).expanduser() if args.out else dest_dir() / "arelis-companion.jks"
    if path.exists():
        print(f"{path} already exists. Not overwriting.", file=sys.stderr)
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    password = os.environ.get("ARELIS_ANDROID_KEYSTORE_PASSWORD", "").strip()
    if not password:
        print(
            "Set ARELIS_ANDROID_KEYSTORE_PASSWORD in the environment first "
            "(a long random string). It is not prompted so it never lands in a scrollback "
            "you later paste.",
            file=sys.stderr,
        )
        return 2
    cmd = [
        keytool,
        "-genkeypair",
        "-keystore",
        str(path),
        "-alias",
        args.alias,
        "-keyalg",
        "RSA",
        "-keysize",
        "2048",
        "-validity",
        "10000",
        "-storepass",
        password,
        "-keypass",
        password,
        "-dname",
        "CN=Arelis companion, O=Arelis, C=US",
    ]
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        return result.returncode
    raw = path.read_bytes()
    print(
        f"Wrote {path} ({len(raw)} bytes). Keep this file. If you lose it, phones cannot update in place."
    )
    print()
    print("GitHub Actions secrets (repo settings → Secrets):")
    print("  ARELIS_ANDROID_KEYSTORE_BASE64")
    print("  ARELIS_ANDROID_KEYSTORE_PASSWORD")
    print("  ARELIS_ANDROID_KEY_ALIAS          =", args.alias)
    print(
        "  ARELIS_ANDROID_KEY_PASSWORD       = same as the store password unless you set a different one"
    )
    print()
    print("Local build:")
    print(f"  set ARELIS_ANDROID_KEYSTORE={path}")
    print("  python scripts/build_companion.py")
    print()
    print("To fill ARELIS_ANDROID_KEYSTORE_BASE64, on this machine:")
    if sys.platform == "win32":
        print(f"  [Convert]::ToBase64String([IO.File]::ReadAllBytes('{path}'))")
    else:
        print(f"  base64 -w0 {path}")
    print()
    print("Do not commit the jks, the base64, or the password.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
