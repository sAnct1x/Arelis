"""Keep a source checkout's virtualenv in step with pyproject.toml (#261)."""

from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
from pathlib import Path

from arelis.paths import INSTALL_PARENT, is_source_checkout

log = logging.getLogger(__name__)


def sync_checkout_deps(run=subprocess.run) -> bool:
    """Reinstall a checkout's dependencies when pyproject.toml changed. True if synced.

    The stamp lives in the virtualenv, because that is what the install changed.
    A failed install leaves no stamp, so the next launch tries again.
    """
    if not is_source_checkout():
        return False
    digest = hashlib.sha256((INSTALL_PARENT / "pyproject.toml").read_bytes()).hexdigest()
    stamp = Path(sys.prefix) / ".arelis-deps-sha256"
    if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == digest:
        return False
    cmd = [sys.executable, "-m", "pip", "install", "-q", "-e", str(INSTALL_PARENT)]
    try:
        done = run(cmd, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as err:
        log.warning("dev dependency sync did not run: %s", err)
        return False
    if done.returncode != 0:
        log.warning("dev dependency sync failed: %s", (done.stderr or "")[-2000:])
        return False
    stamp.write_text(digest, encoding="utf-8")
    log.info("dev dependency sync done")
    return True
