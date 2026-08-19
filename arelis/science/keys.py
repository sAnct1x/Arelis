"""Optional NASA / ADS keys from data/secrets.yaml.

arXiv and Horizons need no key. APOD and ADS stay honest when these are blank:
the tool says so instead of shipping NASA's shared DEMO_KEY, which is not ours
to use. Environment variables override the file, the same way mail does, if
you would rather the secret not sit on disk.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from arelis.paths import state_dir

log = logging.getLogger(__name__)

SECRETS_PATH = state_dir() / "secrets.yaml"
NASA_KEY_ENV = "ARELIS_NASA_API_KEY"
ADS_TOKEN_ENV = "ARELIS_ADS_TOKEN"
_DEMO = "DEMO_KEY"


@dataclass(frozen=True)
class ScienceKeys:
    nasa_api_key: str = ""
    ads_token: str = ""

    @property
    def nasa_ready(self) -> bool:
        key = self.nasa_api_key.strip()
        return bool(key) and key.upper() != _DEMO

    @property
    def ads_ready(self) -> bool:
        return bool(self.ads_token.strip())

    @property
    def nasa_is_demo(self) -> bool:
        return self.nasa_api_key.strip().upper() == _DEMO


def load_science_keys(path: Path | None = None) -> ScienceKeys:
    path = path or SECRETS_PATH
    nasa = (os.environ.get(NASA_KEY_ENV) or "").strip()
    ads = (os.environ.get(ADS_TOKEN_ENV) or "").strip()
    data = _load(path)
    if not nasa:
        nasa_block = data.get("nasa")
        if isinstance(nasa_block, dict):
            nasa = str(nasa_block.get("api_key") or "").strip()
    if not ads:
        ads_block = data.get("ads")
        if isinstance(ads_block, dict):
            ads = str(ads_block.get("token") or "").strip()
    return ScienceKeys(nasa_api_key=nasa, ads_token=ads)


def _load(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Could not read %s: %s", path, exc)
        return {}
    return raw if isinstance(raw, dict) else {}
