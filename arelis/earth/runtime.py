"""Process-wide Earth zone. The plate and the earth tool share it."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from arelis.earth.catalog import LAYER_BY_ID, LAYERS
from arelis.earth.entity import LAYER_IDS, Entity
from arelis.earth.simulate import populate, refresh_moving
from arelis.earth.store import EntityStore
from arelis.spatial.grant import world_stage_allowed

_EARTH: EarthRuntime | None = None


def default_layers() -> dict[str, bool]:
    return {spec.id: spec.default_on for spec in LAYERS}


@dataclass
class EarthRuntime:
    active: bool = False
    live: bool = False
    tiles: bool = False
    layers: dict[str, bool] = field(default_factory=default_layers)
    store: EntityStore = field(default_factory=EntityStore)
    track_id: str = ""
    ride_id: str = ""
    entered_unix: float = 0.0
    last_tick_unix: float = 0.0
    last_local_unix: float = 0.0
    note: str = ""

    def enter(self, *, unix: float | None = None) -> str:
        now = float(unix if unix is not None else time.time())
        if self.active:
            refresh_moving(self.store, now)
            self.last_tick_unix = now
            self.note = "already in Earth"
            return self.note
        self.active = True
        self.entered_unix = now
        self.track_id = ""
        self.ride_id = ""
        populate(self.store, now)
        self._merge_local()
        self.last_local_unix = now
        if self.live:
            self._merge_live()
        self.last_tick_unix = now
        n = len(self.store)
        mode = "live" if self.live else "simulated"
        self.note = f"observing Earth  ECEF  {n} entities  {mode}"
        return self.note

    def leave(self) -> str:
        if not self.active:
            self.note = "already solar"
            return self.note
        self.active = False
        self.track_id = ""
        self.ride_id = ""
        self.store.clear()
        self.note = "left Earth"
        return self.note

    def tick(self, *, unix: float | None = None) -> None:
        if not self.active:
            return
        now = float(unix if unix is not None else time.time())
        if now - self.last_tick_unix < 0.2:
            return
        dt = now - self.last_tick_unix if self.last_tick_unix else 0.0
        refresh_moving(self.store, now, dt=dt)
        if now - self.last_local_unix >= 8.0:
            self._merge_local()
            self.last_local_unix = now
        self.last_tick_unix = now

    def set_layer(self, layer: str, on: bool | None = None) -> bool | None:
        key = (layer or "").strip().lower()
        if key not in self.layers:
            return None
        val = bool(on) if on is not None else (not self.layers[key])
        self.layers[key] = val
        return val

    def visible(self) -> tuple[Entity, ...]:
        if not self.active:
            return ()
        return tuple(
            e for e in self.store.all() if self.layers.get(e.layer, False)
        )

    def get(self, entity_id: str) -> Entity | None:
        return self.store.get(entity_id)

    def track(self, entity_id: str) -> Entity | None:
        hit = self.store.get(entity_id)
        if hit is None:
            self.track_id = ""
            return None
        self.track_id = hit.id
        return hit

    def ride(self, entity_id: str) -> Entity | None:
        hit = self.track(entity_id)
        if hit is None:
            self.ride_id = ""
            return None
        self.ride_id = hit.id
        return hit

    def stop_ride(self) -> None:
        self.ride_id = ""

    def search(self, text: str) -> tuple[Entity, ...]:
        q = (text or "").strip().casefold()
        if not q:
            return ()
        hits = [
            e
            for e in self.visible()
            if q in e.label.casefold() or q in e.id.casefold() or q in e.cls
        ]
        return tuple(hits[:24])

    def status_line(self) -> str:
        if not self.active:
            return "solar"
        n = len(self.visible())
        mode = "live" if self.live else "simulated"
        extra = ""
        if self.ride_id:
            extra = f"  ride {self.ride_id}"
        elif self.track_id:
            extra = f"  track {self.track_id}"
        return f"observing Earth  ECEF  {n}  {mode}{extra}"

    def coverage_notes(self) -> list[str]:
        notes: list[str] = []
        for spec in LAYERS:
            if not self.layers.get(spec.id, False):
                continue
            notes.append(f"{spec.title}: {spec.hole}")
        return notes

    def _merge_local(self) -> None:
        """Owned book and owned camera pins. No network."""
        try:
            from arelis.earth.cameras import load_owned
            from arelis.earth.owned import load_owned_faces
            from arelis.earth.people import load_people
        except Exception:
            return
        try:
            for e in load_people():
                self.store.upsert(e)
            for e in load_owned():
                self.store.upsert(e)
            for e in load_owned_faces():
                self.store.upsert(e)
        except Exception:
            return

    def _merge_live(self) -> None:
        """Best-effort public feeds. Failures stay simulated."""
        try:
            from arelis.earth.live import merge_live
        except Exception:
            return
        try:
            merge_live(self.store)
        except Exception:
            return


def get_earth() -> EarthRuntime | None:
    return _EARTH


def set_earth(runtime: EarthRuntime | None) -> None:
    global _EARTH
    _EARTH = runtime


def require_earth() -> EarthRuntime:
    current = get_earth()
    if current is None:
        current = EarthRuntime()
        set_earth(current)
    return current


def stage_ok() -> bool:
    return world_stage_allowed()


def layer_title(layer: str) -> str:
    spec = LAYER_BY_ID.get(layer)
    return spec.title if spec is not None else layer


def known_layers() -> tuple[str, ...]:
    return LAYER_IDS
