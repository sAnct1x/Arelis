"""Process-wide Earth zone. The plate and the earth tool share it."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

from arelis.earth.catalog import LAYER_BY_ID, LAYERS
from arelis.earth.entity import LAYER_IDS, Entity
from arelis.earth.lod import (
    EarthView,
    adapters_due,
    look_shifted,
    organize,
    paint_layers,
)
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
    buildings: bool = False
    grid: bool = False
    layers: dict[str, bool] = field(default_factory=default_layers)
    store: EntityStore = field(default_factory=EntityStore)
    track_id: str = ""
    ride_id: str = ""
    entered_unix: float = 0.0
    last_tick_unix: float = 0.0
    last_local_unix: float = 0.0
    last_view: EarthView | None = None
    last_live_view: EarthView | None = None
    last_fetch_unix: dict[str, float] = field(default_factory=dict)
    _live_busy: bool = False
    note: str = ""
    pending_goto: dict | None = None

    def enter(self, *, unix: float | None = None) -> str:
        now = float(unix if unix is not None else time.time())
        if self.active:
            refresh_moving(self.store, now)
            self.last_tick_unix = now
            self.note = "already in Earth"
            try:
                from arelis.physics.telemetry import emit

                emit("earth_enter", n=len(self.store), live=self.live, already=True)
            except Exception:
                pass
            return self.note
        self.active = True
        self.entered_unix = now
        self.track_id = ""
        self.ride_id = ""
        populate(self.store, now)
        self._merge_local()
        self.last_local_unix = now
        try:
            from arelis.earth.land import schedule_land_fetch

            schedule_land_fetch()
        except Exception:
            pass
        if self.live:
            self._merge_live()
        self.last_tick_unix = now
        n = len(self.store)
        from arelis.earth.copy import enter_note

        self.note = enter_note(live=self.live, n=n)
        try:
            from arelis.physics.telemetry import emit

            emit("earth_enter", n=n, live=self.live, already=False)
        except Exception:
            pass
        return self.note

    def leave(self) -> str:
        if not self.active:
            self.note = "already solar"
            return self.note
        self.active = False
        self.track_id = ""
        self.ride_id = ""
        self.pending_goto = None
        self.last_view = None
        self.last_live_view = None
        self.last_fetch_unix.clear()
        self.store.clear()
        try:
            from arelis.earth.look import forget

            forget()
        except Exception:
            pass
        from arelis.earth.copy import leave_note

        self.note = leave_note()
        try:
            from arelis.physics.telemetry import emit

            emit("earth_leave")
        except Exception:
            pass
        return self.note

    def request_goto(self, place: object) -> None:
        """Queue a plate fly. The solar tick consumes it once Earth is in view."""
        if hasattr(place, "as_place"):
            self.pending_goto = place.as_place()
            return
        if isinstance(place, dict):
            self.pending_goto = {
                "kind": str(place.get("kind") or "city"),
                "name": str(place.get("name") or ""),
                "lat": float(place["lat"]),
                "lon": float(place["lon"]),
            }

    def take_goto(self) -> dict | None:
        hit = self.pending_goto
        self.pending_goto = None
        return hit

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
        self._maybe_refresh_live(now)
        self.last_tick_unix = now

    def set_layer(self, layer: str, on: bool | None = None) -> bool | None:
        key = (layer or "").strip().lower()
        if key not in self.layers:
            return None
        val = bool(on) if on is not None else (not self.layers[key])
        self.layers[key] = val
        try:
            from arelis.physics.telemetry import emit

            emit("earth_layer", layer=key, on=val, live=self.live)
        except Exception:
            pass
        if val and self.live:
            from arelis.earth.lod import ADAPTER_LAYERS

            for adapter, needed in ADAPTER_LAYERS.items():
                if key in needed:
                    self.last_fetch_unix.pop(adapter, None)
        return val

    def note_view(self, view: EarthView) -> None:
        prev = self.last_view
        self.last_view = view
        if prev is None or prev.band != view.band:
            try:
                from arelis.physics.telemetry import emit

                emit(
                    "earth_band",
                    band=view.band,
                    prev=prev.band if prev is not None else "",
                    alt_m=view.alt_m,
                    px_r=view.px_r,
                    lat=view.lat,
                    lon=view.lon,
                    live=self.live,
                )
            except Exception:
                pass

    def visible(self) -> tuple[Entity, ...]:
        if not self.active:
            return ()
        band = self.last_view.band if self.last_view is not None else "space"
        wanted = paint_layers(band)
        hits = [
            e
            for e in self.store.all()
            if self.layers.get(e.layer, False) and e.layer in wanted
        ]
        return tuple(organize(hits, self.last_view))

    def get(self, entity_id: str) -> Entity | None:
        return self.store.get(entity_id)

    def track(self, entity_id: str) -> Entity | None:
        hit = self.store.get(entity_id)
        if hit is None:
            self.track_id = ""
            return None
        self.track_id = hit.id
        try:
            from arelis.physics.telemetry import emit

            emit("earth_track", id=hit.id, layer=hit.layer)
        except Exception:
            pass
        return hit

    def ride(self, entity_id: str) -> Entity | None:
        hit = self.track(entity_id)
        if hit is None:
            self.ride_id = ""
            return None
        self.ride_id = hit.id
        try:
            from arelis.physics.telemetry import emit

            emit("earth_ride", id=hit.id, layer=hit.layer)
        except Exception:
            pass
        return hit

    def stop_ride(self) -> None:
        was = self.ride_id
        self.ride_id = ""
        if was:
            try:
                from arelis.physics.telemetry import emit

                emit("earth_ride", id="", stop=True)
            except Exception:
                pass

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
        from arelis.earth.copy import status_sentence

        return status_sentence(self)

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
        """Best-effort public feeds for this band. Failures stay simulated."""
        try:
            from arelis.earth.live import merge_live
        except Exception:
            return
        view = self.last_view or EarthView(band="space")
        now = time.time()
        only = adapters_due(view.band, self.last_fetch_unix, now, self.layers)
        if not only:
            return
        try:
            merge_live(self.store, view=view, layers=self.layers, only=only)
        except Exception:
            return
        for key in only:
            self.last_fetch_unix[key] = now
        self.last_live_view = view

    def _maybe_refresh_live(self, now: float) -> None:
        """Re-poll when the band changes or the look pin walks. Not from pytest."""
        if not self.live or not self.active or self._live_busy:
            return
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        view = self.last_view
        if view is None:
            return
        moved = look_shifted(self.last_live_view, view)
        if moved and view.band != "space":
            for key in ("opensky", "adsb", "ais"):
                self.last_fetch_unix.pop(key, None)
        due = adapters_due(view.band, self.last_fetch_unix, now, self.layers)
        if not due:
            return
        self._live_busy = True
        try:
            from arelis.physics.telemetry import emit

            emit(
                "earth_refresh",
                band=view.band,
                moved=moved,
                n=len(due),
                adapters=list(due),
            )
        except Exception:
            pass

        def work() -> None:
            try:
                self._merge_live()
            finally:
                self._live_busy = False

        threading.Thread(target=work, daemon=True, name="earth-live").start()


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
