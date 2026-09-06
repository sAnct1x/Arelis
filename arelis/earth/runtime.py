"""Process-wide Earth zone. The plate and the earth tool share it."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

from arelis.earth.catalog import LAYERS
from arelis.earth.entity import Entity
from arelis.earth.lod import (
    EarthView,
    adapters_due,
    ground_buildings_on,
    ground_streets_on,
    look_shifted,
    organize,
    paint_layers,
)
from arelis.earth.simulate import populate, refresh_moving
from arelis.earth.store import EntityStore
from arelis.spatial.grant import world_stage_allowed

_EARTH: EarthRuntime | None = None
_COAST_LAYERS = frozenset({"flights", "drones", "military", "vessels"})


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
        self._lock_wall_clock()
        if self.active:
            refresh_moving(self.store, now)
            self.last_tick_unix = now
            self._kick_snapshot(refetch=True)
            if unix is None and not _in_pytest():
                self.live = True
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
        else:
            self._kick_snapshot()
        if unix is None and not _in_pytest():
            self.live = True
        self.last_tick_unix = now
        n = len(self.store)
        from arelis.earth.copy import enter_note

        self.note = enter_note(
            live=self.live,
            n=n,
            snapshot=not self.live and not _in_pytest(),
        )
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
        self.live = False
        self.track_id = ""
        self.ride_id = ""
        self.pending_goto = None
        self.tiles = False
        self.buildings = False
        self.last_view = None
        self.last_live_view = None
        self.last_fetch_unix.clear()
        self.store.clear()
        try:
            from arelis.earth.look import forget

            forget()
        except Exception:
            pass
        try:
            from arelis.earth.trails import forget as forget_trails

            forget_trails()
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
        self._note_trails()
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
        if val:
            from arelis.earth.lod import ADAPTER_LAYERS

            for adapter, needed in ADAPTER_LAYERS.items():
                if key in needed:
                    self.last_fetch_unix.pop(adapter, None)
        return val

    def _reveal_band(self, band: str) -> None:
        """Closer bands turn more on. Chips can still hide a layer after that."""
        wanted = paint_layers(band)
        for layer in wanted:
            self.layers[layer] = True

    def _sync_ground_detail(self, prev: EarthView | None) -> None:
        """Streets and footprints follow altitude. Zooming out drops them."""
        view = self.last_view
        now_s = view is not None and ground_streets_on(
            band=view.band, alt_m=view.alt_m
        )
        was_s = prev is not None and ground_streets_on(
            band=prev.band, alt_m=prev.alt_m
        )
        now_b = view is not None and ground_buildings_on(
            band=view.band, alt_m=view.alt_m
        )
        was_b = prev is not None and ground_buildings_on(
            band=prev.band, alt_m=prev.alt_m
        )
        if now_s and not was_s:
            self.tiles = True
        elif not now_s:
            self.tiles = False
        if now_b and not was_b:
            self.buildings = True
        elif not now_b:
            self.buildings = False
        if view is None:
            return
        if self.tiles:
            try:
                from arelis.earth.roads import roads_for_view

                roads_for_view(view.lat, view.lon, view.band, alt_m=view.alt_m)
            except Exception:
                pass
        if self.buildings:
            try:
                from arelis.earth.buildings import footprints_for_view
                from arelis.earth.tiles import tiles_for_view, zoom_for_ground

                tiles_for_view(
                    view.lat,
                    view.lon,
                    zoom_for_ground(view.px_r, view.band),
                    source="osm",
                )
                footprints_for_view(view.lat, view.lon, view.band)
            except Exception:
                pass

    def note_view(self, view: EarthView) -> None:
        prev = self.last_view
        self.last_view = view
        if prev is None or prev.band != view.band:
            self._reveal_band(view.band)
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
            if view.band in {"approach", "near", "city"}:
                try:
                    from arelis.earth.tiles import tiles_for_view, zoom_for_ground

                    tiles_for_view(
                        view.lat,
                        view.lon,
                        zoom_for_ground(view.px_r, view.band),
                        source="gibs",
                    )
                except Exception:
                    pass
        self._sync_ground_detail(prev)

    def visible(self) -> tuple[Entity, ...]:
        if not self.active:
            return ()
        band = self.last_view.band if self.last_view is not None else "space"
        wanted = paint_layers(band)
        hits = [
            e
            for e in self.store.all()
            if self.layers.get(e.layer, False)
            and e.layer in wanted
            and self._paint_contact(e)
        ]
        return tuple(organize(hits, self.last_view))

    def _paint_contact(self, entity: Entity) -> bool:
        """Drawn air/sea wait for a published fix. Pytest keeps the sim sky."""
        if entity.freshness != "simulated":
            return True
        if entity.layer not in _COAST_LAYERS:
            return True
        return _in_pytest()

    def get(self, entity_id: str) -> Entity | None:
        return self.store.get(entity_id)

    def unlock(self) -> None:
        """Drop track, ride, and the Earth trail for that id."""
        was = self.ride_id or self.track_id
        self.stop_ride()
        self.track_id = ""
        if was:
            try:
                from arelis.earth.trails import forget

                forget(was)
            except Exception:
                pass

    def _note_trails(self) -> None:
        hot = self.ride_id or self.track_id
        if not hot:
            return
        try:
            from arelis.earth.trails import forget, note
        except Exception:
            return
        ent = self.store.get(hot)
        if ent is None:
            forget(hot)
            return
        note(hot, (ent.x, ent.y, ent.z))

    def track(self, entity_id: str) -> Entity | None:
        key = (entity_id or "").strip()
        if not key:
            self.unlock()
            return None
        hit = self.store.get(key)
        prev = self.track_id
        if hit is None:
            self.unlock()
            return None
        if prev and prev != hit.id:
            try:
                from arelis.earth.trails import forget

                forget(prev)
            except Exception:
                pass
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

    def _lock_wall_clock(self) -> None:
        """Earth is now. Counterfactual / placeholder ICs cannot lock — leave them."""
        if _in_pytest():
            return
        try:
            from arelis.physics.runtime import get_system

            system = get_system()
        except Exception:
            return
        if system is None:
            return
        try:
            system.go_realtime()
        except Exception:
            pass

    def _kick_snapshot(self, *, refetch: bool = False) -> None:
        """One published pull. Coast until leave or a new band. Live keeps polling."""
        if _in_pytest() or self._live_busy:
            return
        if refetch:
            self.last_fetch_unix.clear()
        self._start_live_merge(moved=False)

    def _coast_due(self, view: EarthView) -> tuple[str, ...]:
        """Adapters this band has never fetched. TTL does not pull again."""
        from arelis.earth.lod import ADAPTER_BANDS, adapter_allowed

        return tuple(
            key
            for key in ADAPTER_BANDS
            if adapter_allowed(key, view.band, self.layers)
            and key not in self.last_fetch_unix
        )

    def _maybe_refresh_live(self, now: float) -> None:
        """Live polls on TTL / look walk. Coast mode fetches a band once."""
        if not self.active or self._live_busy:
            return
        if _in_pytest():
            return
        view = self.last_view
        if view is None:
            return
        moved = False
        if self.live:
            moved = look_shifted(self.last_live_view, view)
            if moved and view.band != "space":
                for key in ("opensky", "adsb", "ais"):
                    self.last_fetch_unix.pop(key, None)
            due = adapters_due(view.band, self.last_fetch_unix, now, self.layers)
        else:
            due = self._coast_due(view)
        if not due:
            return
        self._start_live_merge(moved=moved, due=due)

    def _start_live_merge(
        self, *, moved: bool, due: tuple[str, ...] | None = None
    ) -> None:
        view = self.last_view or EarthView(band="space")
        self._live_busy = True
        try:
            from arelis.physics.telemetry import emit

            emit(
                "earth_refresh",
                band=view.band,
                moved=moved,
                n=len(due or ()),
                adapters=list(due or ()),
                live=self.live,
            )
        except Exception:
            pass

        def work() -> None:
            try:
                self._merge_live()
            finally:
                self._live_busy = False

        threading.Thread(target=work, daemon=True, name="earth-live").start()


def _in_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


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
