"""Sentinel Narrow-Caste Registry and Built-In Castes."""

from __future__ import annotations

from typing import Any

from sentinel.castes.base import (
    CasteDescriptor,
    CasteHandler,
    CasteRegistry,
    PermissionViolationError,
)
from sentinel.castes.cryptarch import CryptarchCaste, CryptoVerifierCaste
from sentinel.castes.dynamic import DynamicCasteHandler
from sentinel.castes.harvester import HarvesterCaste
from sentinel.castes.interceptor import ASTValidatorCaste, InterceptorCaste
from sentinel.castes.sanitizer import SanitizerCaste
from sentinel.castes.stalker import ProcessAuditorCaste, StalkerCaste
from sentinel.castes.tripwire import TripwireCaste
from sentinel.castes.warden import WardenCaste


def build_default_caste_registry(config: dict[str, Any] | None = None) -> CasteRegistry:
    """Instantiate and register all built-in Sentinel castes."""
    registry = CasteRegistry()
    sanitizer = SanitizerCaste(config)
    harvester = HarvesterCaste(config, sanitizer=sanitizer)
    warden = WardenCaste(config)
    tripwire = TripwireCaste(config)
    interceptor = InterceptorCaste(config)
    cryptarch = CryptarchCaste(config)
    stalker = StalkerCaste(config)

    registry.register(harvester)
    registry.register(warden)
    registry.register(sanitizer)
    registry.register(tripwire)
    registry.register(interceptor)
    registry.register(cryptarch)
    registry.register(stalker)
    return registry


__all__ = [
    "ASTValidatorCaste",
    "CasteDescriptor",
    "CasteHandler",
    "CasteRegistry",
    "CryptarchCaste",
    "CryptoVerifierCaste",
    "DynamicCasteHandler",
    "HarvesterCaste",
    "InterceptorCaste",
    "PermissionViolationError",
    "ProcessAuditorCaste",
    "SanitizerCaste",
    "StalkerCaste",
    "TripwireCaste",
    "WardenCaste",
    "build_default_caste_registry",
]

