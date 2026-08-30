"""Process-wide live solar system. The tool and Reality's plate share it."""

from __future__ import annotations

from arelis.physics.scene import SolarSystem

_SYSTEM: SolarSystem | None = None


def get_system() -> SolarSystem | None:
    return _SYSTEM


def set_system(system: SolarSystem | None) -> None:
    global _SYSTEM
    _SYSTEM = system
