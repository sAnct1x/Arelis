"""Earth-zone camera, Cesium globe mount, and look-from on SolarPanel.

Earth zone is one Cesium globe. Solar lab is native GL. Never both live:
park/destroy the offscreen context, then mount WebEngine. A photoreal
miss must not set host.failed. Native disc is fallback only.
"""
from __future__ import annotations

import json
import math
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from arelis.earth.copy import RIDE_LAYERS, can_ride
from arelis.physics.camera import CameraWarp
from arelis.physics.collision import inspect_stop_m
from arelis.physics.runtime import get_system
from arelis.physics.scene import SolarSystem
from arelis.ui.earth_overlay import look_from_pose, ride_pose


def earth_zoom_factor(delta: float) -> float:
    """One wheel notch is a fraction of altitude, not a solar-cruise hop."""
    step = abs(float(delta))
    if step <= 0.0:
        return 1.0
    notches = step / 120.0 if step >= 40.0 else step / 40.0
    notches = min(3.0, max(0.12, notches))
    inward = 0.78 ** notches
    return inward if delta > 0.0 else 1.0 / inward


# Find / take-me-to. City must open the city band (< 40 km AGL). 80 km
# was near-band and sat on the old photoreal switch — ocean tiles went black.
CITY_LOOK_ALT_M = 8_000.0
# Street address: a few blocks, names readable. Above the 200 m camera floor.
STREET_LOOK_ALT_M = 350.0
# First Enter: whole Earth, nadir, north-up. Not the leftover solar glance.
SPACE_ENTER_ALT_M = 20_000_000.0
# Ride sits on cameras and moving contacts. Ground pins fly-to instead.
GLOBE_RIDE_LAYERS = RIDE_LAYERS


def globe_ride_layer(layer: str) -> bool:
    return can_ride(layer)


def earth_enter_lla(zone=None) -> tuple[float, float, float]:
    """Space-band nadir for the first Cesium pose. Earth fills the frame."""
    view = getattr(zone, "last_view", None) if zone is not None else None
    if view is not None:
        try:
            lat = float(view.lat)
            lon = float(view.lon)
            if abs(lat) <= 90.0:
                return lat, lon, SPACE_ENTER_ALT_M
        except (TypeError, ValueError):
            pass
    return 20.0, 0.0, SPACE_ENTER_ALT_M


def earth_entity_look_alt_m(layer: str) -> float:
    """Nadir height after a ground-mark click. Stay out of the ellipsoid."""
    if layer in {"cameras", "traffic", "people"}:
        return 1_200.0
    if layer in {"flights", "drones", "military"}:
        return 12_000.0
    if layer in {"iss", "satellites"}:
        return 80_000.0
    return CITY_LOOK_ALT_M


def earth_goto_alt_m(kind: str) -> float:
    """Nadir height for a gazetteer or address hit."""
    return {
        "address": STREET_LOOK_ALT_M,
        "city": CITY_LOOK_ALT_M,
        "home": CITY_LOOK_ALT_M,
        "contact": CITY_LOOK_ALT_M,
        "state": 350_000.0,
        "province": 350_000.0,
        "country": 1_100_000.0,
        "continent": 5_000_000.0,
    }.get(str(kind or "earth"), 2_400_000.0)


def clamp_radial(
    eye: tuple[float, float, float],
    center: tuple[float, float, float],
    r_min: float,
    r_max: float | None = None,
) -> tuple[float, float, float]:
    """Keep the inspect eye outside the stop sphere. No mesh, no landing."""
    dx = eye[0] - center[0]
    dy = eye[1] - center[1]
    dz = eye[2] - center[2]
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist < 1.0:
        return (center[0] + r_min, center[1], center[2])
    limit = dist
    if dist < r_min:
        limit = r_min
    elif r_max is not None and dist > r_max:
        limit = r_max
    if limit == dist:
        return eye
    s = limit / dist
    return (center[0] + dx * s, center[1] + dy * s, center[2] + dz * s)


def earth_zone_speed(dist_m: float, radius_m: float, slider: float) -> float:
    """WASD speed follows height above the inspect floor, not leftover AU/s."""
    height = max(80.0, dist_m - float(radius_m))
    scaled = 40.0 + height * 0.02
    return max(8.0, min(float(slider), scaled))


def _emit_earth_lock(on: bool) -> None:
    try:
        from arelis.physics.telemetry import emit

        emit("earth_lock", on=on)
    except Exception:
        pass


class SolarEarthMixin:
    def _select_earth_entity(self, hit, *, ride: bool) -> None:
        from arelis.earth.runtime import get_earth

        self._earth_id = hit.id
        zone = get_earth()
        if zone is not None:
            if ride:
                zone.ride(hit.id)
            else:
                zone.stop_ride()
                zone.track(hit.id)
        if ride:
            self._globe_rode = None
        if hit.layer == "cameras":
            from arelis.ui.earth_dock import open_camera_dock

            open_camera_dock(self, hit.id, mode="peek")
            self._open_earth_look(hit)
        elif hit.layer == "radio":
            from arelis.ui.earth_dock import open_radio_dock

            open_radio_dock(self, tune_id=hit.id)
        else:
            from arelis.ui.earth_dock import close_earth_dock

            close_earth_dock(self)
        if self._earth_globe_live():
            host = self._globe_host
            if host is not None and not getattr(host, "failed", False):
                from arelis.ui.earth_globe_host import entity_rows

                if ride:
                    here = getattr(self, "_cesium_lla", None)
                    sat = False
                    if isinstance(here, tuple) and len(here) >= 3:
                        try:
                            sat = 80_000.0 <= float(here[2]) <= 900_000.0
                        except (TypeError, ValueError):
                            sat = False
                    if not sat:
                        self._fly_ride_sit(hit)
                    if hasattr(host, "arm_ride"):
                        host.arm_ride(hit.id)
                elif hasattr(host, "arm_ride"):
                    host.arm_ride("")
                host.push_entities(entity_rows())
        from arelis.ui.earth_chrome import set_earth_say

        label = str(hit.label or hit.id)
        if ride:
            set_earth_say(
                self,
                f"Riding {label}",
                "You should be moving with it. The ground streams. Esc hops off.",
            )
        elif hit.layer == "cameras":
            set_earth_say(
                self,
                label,
                "Publisher still on the right. View enlarges it.",
            )
        else:
            set_earth_say(self, label, "This mark. Double-click rides it.")
        self.update()

    def _fly_to_earth_entity(self, ent) -> None:
        """Nadir fly to a pin. Do not sit 200 m on a quake."""
        from arelis.earth.lod import entity_lla

        pair = entity_lla(ent)
        if pair is None:
            return
        alt = earth_entity_look_alt_m(getattr(ent, "layer", ""))
        self._go_earth_lla(pair[0], pair[1], alt, leave=False)

    def _go_earth_lla(
        self, lat: float, lon: float, alt_m: float, *, leave: bool = True
    ) -> bool:
        """Fly here. A place hop drops the old contact. Dest is not the eye."""
        if leave:
            from arelis.earth.runtime import get_earth

            zone = get_earth()
            if zone is not None:
                zone.unlock()
            self._earth_id = None
            self._earth_card_xy = None
            self._close_earth_look()
            from arelis.ui.earth_dock import close_earth_dock

            close_earth_dock(self)
        self._earth_fly = None
        host = self._globe_host
        if host is not None and hasattr(host, "arm_ride"):
            host.arm_ride("")
        if host is not None and hasattr(host, "release_camera"):
            host.release_camera()
        if self._fly_globe_to(lat, lon, alt_m):
            self.update()
            return True
        return False

    def _select_earth_place(self, geo: dict) -> None:
        from arelis.earth.frames import EarthCam, nadir_cam
        from arelis.earth.runtime import get_earth

        self._close_earth_look()
        self._place = geo
        self._globe_hpr = None
        zone = get_earth()
        if zone is not None:
            zone.unlock()
        self._earth_id = None
        self._earth_card_xy = None
        self._globe_aimed = None
        self._earth_pin = None
        kind = str(geo.get("kind") or "earth")
        try:
            alt = float(geo["alt_m"])
        except (KeyError, TypeError, ValueError):
            alt = earth_goto_alt_m(kind)
        lat, lon = float(geo["lat"]), float(geo["lon"])
        from arelis.ui.earth_chrome import set_earth_say

        name = str(geo.get("name") or geo.get("kind") or "Earth")
        km = alt / 1000.0
        how = f"{km:,.0f} km up" if km >= 100 else f"{km:.1f} km up"
        set_earth_say(self, name, f"Flying here · {how}. Watch the planet.")
        if self._go_earth_lla(lat, lon, alt):
            return
        zone = get_earth()
        if zone is not None:
            zone.unlock()
        if self._earth_cam is None:
            self._remember_earth_eye()
        dest = nadir_cam(lat, lon, alt)
        start = self._earth_cam if isinstance(self._earth_cam, EarthCam) else dest
        self._earth_fly = {"start": start, "end": dest, "t": 0.0, "dur": 1.2}
        self._earth_cam = start
        self.update()

    def _step_earth_fly(self, dt: float) -> None:
        if self._earth_globe_live():
            self._earth_fly = None
            return
        flight = self._earth_fly
        if not isinstance(flight, dict):
            return
        start = flight.get("start")
        end = flight.get("end")
        if start is None or end is None:
            self._earth_fly = None
            return
        dur = max(0.2, float(flight.get("dur") or 1.0))
        t = min(1.0, float(flight.get("t") or 0.0) + dt / dur)
        flight["t"] = t
        u = t * t * (3.0 - 2.0 * t)

        def mix(
            a: tuple[float, float, float], b: tuple[float, float, float]
        ) -> tuple[float, float, float]:
            return (
                a[0] + (b[0] - a[0]) * u,
                a[1] + (b[1] - a[1]) * u,
                a[2] + (b[2] - a[2]) * u,
            )

        from arelis.earth.frames import EarthCam

        self._earth_cam = EarthCam(
            eye=mix(start.eye, end.eye),
            look=mix(start.look, end.look),
            up=mix(start.up, end.up),
        )
        if t >= 1.0:
            self._earth_cam = end
            self._earth_fly = None

    def _leave_earth_zone(self) -> None:
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is not None:
            zone.stop_ride()
            zone.leave()
        self._earth_cam = None
        self._earth_fly = None
        self._earth_id = None
        self._place = None
        self._globe_aimed = None
        self._globe_rode = None
        self._earth_agl_m = None
        self._earth_mpp = None
        self._earth_nadir_m = None
        self._earth_pin = None
        self._streets_on = None
        self._roads_gen = None
        self._globe_did_ready = False
        self._globe_ride_push = 0.0
        self._globe_data_push = 0.0
        self._globe_bldg_gen = None
        self._globe_cam_push = 0.0
        self._earth_live_busy = False
        self._cesium_off = False
        self._close_earth_look()
        from arelis.ui.earth_dock import close_earth_dock

        close_earth_dock(self)
        self._leave_earth_globe()
        self._globe_hpr = None
        self.update()

    def _earth_zone_on(self) -> bool:
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        return zone is not None and zone.active

    def _earth_globe_live(self) -> bool:
        host = self._globe_host
        return host is not None and not host.failed and host.isVisible()

    def _cesium_forbidden(self) -> bool:
        """Cannot construct WebEngine. Pytest is not a reason."""
        try:
            from arelis.ui.earth_globe_host import webengine_available

            return not webengine_available()
        except Exception:
            return True

    def _skip_cesium(self) -> bool:
        """Native fallback only. GPU space and pytest no longer forbid the globe."""
        if self._cesium_forbidden():
            return True
        return bool(getattr(self, "_cesium_off", False))

    def _fallback_native_globe(self, why: str) -> None:
        from arelis.ui.solar_gl import trace

        self._cesium_off = True
        self._drop_earth_webengine()
        gl = getattr(self, "_gl", None)
        if gl is not None and getattr(gl, "_parked", False) and hasattr(gl, "unpark"):
            gl.unpark()
        trace(f"earth globe: native fallback ({why})")

    def _enter_earth_globe(self) -> None:
        system = get_system()
        if system is not None:
            try:
                system.go_realtime()
            except Exception:
                pass
        if getattr(self, "_cesium_off", False) or self._cesium_forbidden():
            self._fallback_native_globe("webengine missing or already off")
            return
        self._park_space_for_earth()
        if self._globe_host is None:
            if getattr(self, "_globe_mounting", False):
                return
            self._globe_mounting = True
            QTimer.singleShot(0, self, self._mount_earth_globe)
            return
        self._show_earth_globe()

    def _mount_earth_globe(self) -> None:
        self._globe_mounting = False
        if not self._earth_zone_on():
            return
        if getattr(self, "_cesium_off", False) or self._cesium_forbidden():
            self._fallback_native_globe("webengine missing or already off")
            return
        from arelis.ui.earth_globe_host import (
            EarthGlobeHost,
            EarthHudGlass,
            webengine_available,
        )

        gl = getattr(self, "_gl", None)
        if gl is not None:
            if hasattr(gl, "park"):
                gl.park()
            else:
                gl.release_current()
        if self._globe_host is None and webengine_available():
            from arelis.ui.solar_gl import trace

            trace("earth globe: mount host")
            host = EarthGlobeHost(self)
            if host.failed:
                self._drop_earth_webengine()
                if gl is not None and hasattr(gl, "unpark"):
                    gl.unpark()
                return
            host.bridge.hostPicked.connect(self._on_globe_pick)
            if hasattr(host.bridge, "hostRidden"):
                host.bridge.hostRidden.connect(self._on_globe_ridden)
            host.bridge.hostCamera.connect(self._on_globe_camera)
            host.bridge.hostGround.connect(self._on_globe_ground)
            host.bridge.hostReady.connect(lambda _k: self._on_globe_ready())
            host.bridge.hostTiles.connect(self._on_globe_tiles)
            host.bridge.hostFailed.connect(lambda _w: self._on_globe_failed())
            self._globe_host = host
        if self._earth_hud is None and self._globe_host is not None:
            self._earth_hud = EarthHudGlass(self)
        self._show_earth_globe()

    def _show_earth_globe(self) -> None:
        if self._skip_cesium():
            return
        from arelis.ui.earth_globe_host import entity_rows, place_rows

        host = self._globe_host
        if host is not None and not host.failed:
            host.show()
            host.lower()
        if self._earth_hud is not None:
            self._earth_hud.show()
            self._earth_hud.raise_()
        self._layout_earth_globe()
        if host is not None and not host.failed:
            zone = None
            try:
                from arelis.earth.runtime import get_earth

                zone = get_earth()
            except Exception:
                zone = None
            if getattr(self, "_globe_did_ready", False) and not self._globe_flight_live():
                self._push_globe_camera()
            host.push_entities(entity_rows())
            if zone is not None and zone.last_view is not None:
                host.push_places(
                    place_rows(zone.last_view.band, zone.last_view.lat, zone.last_view.lon)
                )
                self._push_streets_if_changed(zone)
        self.update()

    def _park_space_for_earth(self) -> None:
        """Destroy the offscreen solar context. Do not keep a leftover frame.

        A frozen FBO under a translucent Cesium plate is the night-side
        ghost. park() deletes the offscreen context; the share group
        still lives, so the daily driver mounts Cesium in a child
        process. The plate itself is opaque (``seal_globe_plate``).
        """
        if getattr(self, "_cesium_off", False):
            return
        gl = getattr(self, "_gl", None)
        if gl is None:
            return
        if hasattr(gl, "park"):
            gl.park()
        else:
            gl.release_current()

    def _drop_earth_webengine(self) -> None:
        """Kill Chromium before solar GL is allowed to exist again."""
        host = self._globe_host
        hud = self._earth_hud
        self._globe_host = None
        self._earth_hud = None

        def _retire(widget) -> None:
            if widget is None:
                return
            hide = getattr(widget, "hide", None)
            if callable(hide):
                hide()
            late = getattr(widget, "deleteLater", None)
            if callable(late):
                late()

        _retire(hud)
        if host is None:
            return
        shut = getattr(host, "shutdown", None)
        if callable(shut):
            try:
                shut()
            except Exception:
                pass
        view = getattr(host, "_view", None)
        if view is not None:
            _retire(view)
            host._view = None
        _retire(host)

    def _leave_earth_globe(self) -> None:
        from arelis.ui.earth_find import close_find, hold_globe_keys

        close_find(self)
        hold_globe_keys(self, False)
        self._globe_mounting = False
        self._globe_hpr = None
        self._globe_fly_until = 0.0
        self._globe_did_ready = False
        self._streets_on = None
        self._roads_gen = None
        self._roads_view_key = None
        self._drop_earth_webengine()
        gl = getattr(self, "_gl", None)
        if gl is not None and hasattr(gl, "unpark"):
            gl.unpark()

    def _layout_earth_globe(self) -> None:
        if self._globe_host is not None:
            self._globe_host.setGeometry(self.rect())
            pin = getattr(self._globe_host, "pin_child", None)
            if callable(pin):
                pin()
        if self._earth_hud is not None:
            host = self._globe_host
            if host is not None and not host.failed and host.isVisible():
                self._earth_hud.show()
                from arelis.ui.earth_globe_host import stack_chrome_over_globe

                stack_chrome_over_globe(self._earth_hud, host)
            else:
                self._earth_hud.hide()

    def _frame_earth_enter(self) -> None:
        """Nadir, north-up, whole Earth. Do not inherit the solar glance."""
        from arelis.earth.frames import nadir_cam
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is not None and getattr(zone, "ride_id", ""):
            return
        lat, lon, alt = earth_enter_lla(zone)
        self._globe_hpr = (0.0, -90.0)
        host = self._globe_host
        if host is not None and not host.failed and host.isVisible():
            host.push_camera(lat, lon, alt, 0.0, -90.0)
            return
        self._earth_cam = nadir_cam(lat, lon, alt)
        self._earth_agl_m = float(alt)
        self._earth_nadir_m = None

    def _on_globe_ready(self) -> None:
        self._layout_earth_globe()
        if getattr(self, "_globe_did_ready", False):
            return
        self._globe_did_ready = True
        flight = self._earth_fly
        end = flight.get("end") if isinstance(flight, dict) else None
        if end is not None:
            from arelis.earth.frames import ecef_to_geodetic

            lat, lon, alt = ecef_to_geodetic(*end.eye)
            self._earth_cam = end
            self._earth_fly = None
            if self._fly_globe_to(lat, lon, alt):
                self._sync_earth_globe(force=True, camera=False)
                self.update()
                return
        self._frame_earth_enter()
        self._sync_earth_globe(force=True, camera=True)
        self.update()

    def _on_globe_tiles(self, kind: str) -> None:
        try:
            from arelis.physics.telemetry import emit

            emit("earth_tiles", kind=str(kind or ""))
        except Exception:
            pass

    def _on_globe_failed(self) -> None:
        self._cesium_off = True
        self._leave_earth_globe()
        self.update()

    def _clear_earth_pick(self) -> None:
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is not None:
            zone.unlock()
        self._earth_id = None
        self._place = None
        self._earth_card_xy = None
        self._globe_aimed = None
        self._close_earth_look()
        from arelis.ui.earth_dock import close_earth_dock

        close_earth_dock(self)
        host = self._globe_host
        if host is not None and hasattr(host, "release_camera"):
            host.release_camera()
        if self._earth_globe_live():
            self._sync_earth_globe(force=True)

    def _hop_off_earth_contact(self) -> bool:
        """Esc or empty sky. Drop track and ride. Eye stays put."""
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        held = bool(getattr(self, "_earth_id", None) or getattr(self, "_place", None))
        if zone is not None:
            held = held or bool(zone.track_id or zone.ride_id)
        if not held:
            return False
        self._clear_earth_pick()
        self.update()
        return True

    def _on_globe_pick(self, entity_id: str) -> None:
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None:
            return
        hit = zone.get(entity_id)
        if hit is None:
            return
        self._select_earth_entity(hit, ride=hit.layer == "iss")

    def _on_globe_ridden(self, entity_id: str) -> None:
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None:
            return
        hit = zone.get(entity_id)
        if hit is None:
            return
        if globe_ride_layer(hit.layer):
            self._select_earth_entity(hit, ride=True)
            return
        self._select_earth_entity(hit, ride=False)
        self._fly_to_earth_entity(hit)

    def _on_globe_camera(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
            lat = float(payload["lat"])
            lon = float(payload["lon"])
            alt = float(payload["alt_m"])
            heading = float(payload.get("heading") or 0.0)
            pitch = float(payload.get("pitch") or -90.0)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return
        self._earth_agl_m = alt
        self._cesium_lla = (lat, lon, alt)
        self._cesium_lla_at = time.perf_counter()
        try:
            look_lat = float(payload["look_lat"])
            look_lon = float(payload["look_lon"])
        except (KeyError, TypeError, ValueError):
            look_lat = look_lon = None
        self._cesium_look = (
            (look_lat, look_lon) if look_lat is not None else None
        )
        try:
            mpp = float(payload.get("mpp") or 0.0)
        except (TypeError, ValueError):
            mpp = 0.0
        self._earth_mpp = mpp if mpp > 0.0 else None
        try:
            nadir = float(payload.get("nadir_m") or 0.0)
        except (TypeError, ValueError):
            nadir = 0.0
        self._earth_nadir_m = nadir if nadir > 0.0 else None
        self._globe_hpr = (heading, pitch)
        try:
            hx = float(payload.get("hot_x"))
            hy = float(payload.get("hot_y"))
            hid = str(payload.get("hot_id") or "")
        except (TypeError, ValueError):
            hx = hy = None
            hid = ""
        if hid and hid == (self._earth_id or "") and hx is not None:
            self._earth_card_xy = (hx, hy)
        else:
            self._earth_card_xy = None
        if self._earth_globe_live():
            self._earth_fly = None
        elif self._earth_fly is not None:
            if self._globe_flight_live():
                self.update()
                return
            self._earth_fly = None
        from arelis.earth.frames import nadir_cam

        self._earth_cam = nadir_cam(lat, lon, alt)
        try:
            from arelis.earth.runtime import get_earth
            from arelis.physics.runtime import get_system
            from arelis.physics.telemetry import sample
            from arelis.ui.earth_overlay import sync_earth_view

            system = get_system()
            if system is not None:
                sync_earth_view(self, system)
            zone = get_earth()
            if zone is not None:
                self._push_streets_if_changed(zone)
            sample(
                "earth_pose",
                lat=lat,
                lon=lon,
                agl_m=alt,
                nadir_m=nadir,
                mpp=mpp,
                band=zone.last_view.band if zone is not None and zone.last_view else "",
                tiles=bool(zone.tiles) if zone is not None else False,
            )
        except Exception:
            pass
        self.update()

    def _on_globe_ground(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        if payload.get("sky"):
            self._hop_off_earth_contact()
            return
        try:
            lat = float(payload["lat"])
            lon = float(payload["lon"])
            slant = float(payload.get("slant_m") or 0.0)
            agl = float(payload.get("agl_m") or 0.0)
        except (KeyError, TypeError, ValueError):
            return
        self._earth_pin = {"lat": lat, "lon": lon, "slant_m": slant}
        if agl > 0.0:
            self._earth_agl_m = agl
        self._clear_earth_pick()
        try:
            from arelis.physics.telemetry import emit

            emit(
                "earth_ground",
                pin_lat=lat,
                pin_lon=lon,
                slant_m=slant,
                agl_m=agl,
            )
        except Exception:
            pass
        self.update()

    def _globe_flight_live(self) -> bool:
        return time.perf_counter() < float(getattr(self, "_globe_fly_until", 0.0) or 0.0)

    def _fly_globe_to(self, lat: float, lon: float, alt_m: float) -> bool:
        """One Cesium fly. Do not also setView every Python tick."""
        host = self._globe_host
        if host is None or host.failed or not host.isVisible():
            return False
        if not self._earth_globe_live():
            return False
        host.fly_to(lat, lon, alt_m)
        self._globe_fly_until = time.perf_counter() + 12.0
        return True

    def _face_earth_north(self) -> None:
        """Click the compass — heading 0, keep the current look."""
        pitch = -90.0
        if self._globe_hpr is not None:
            pitch = float(self._globe_hpr[1])
        self._globe_hpr = (0.0, pitch)
        host = self._globe_host
        if host is None or host.failed or not host.isVisible():
            self.update()
            return
        lla = getattr(self, "_cesium_lla", None)
        if isinstance(lla, tuple) and len(lla) >= 3:
            lat, lon, alt = float(lla[0]), float(lla[1]), float(lla[2])
        else:
            pose = self._earth_cam
            if pose is None:
                self.update()
                return
            from arelis.earth.frames import ecef_to_geodetic

            lat, lon, alt = ecef_to_geodetic(*pose.eye)
        host.push_camera(lat, lon, max(alt, 200.0), 0.0, pitch)
        self.update()

    def _push_globe_camera(self) -> None:
        if self._earth_globe_live():
            return
        host = self._globe_host
        pose = self._earth_cam
        if host is None or host.failed or not host.isVisible() or pose is None:
            return
        if self._globe_flight_live():
            return
        from arelis.earth.frames import ecef_to_geodetic

        lat, lon, alt = ecef_to_geodetic(*pose.eye)
        heading, pitch = (None, None)
        if self._earth_fly is None and self._globe_hpr is not None:
            heading, pitch = self._globe_hpr
        host.push_camera(lat, lon, max(alt, 200.0), heading, pitch)
        self._globe_cam_push = time.perf_counter()

    def _push_streets_if_changed(self, zone) -> None:
        """Push the overlay once per on/off or Overpass generation. Not every camera tick."""
        host = self._globe_host
        if host is None or host.failed:
            return
        from arelis.earth.roads import cache_key, road_generation

        want = bool(zone.tiles)
        gen = road_generation()
        view = zone.last_view
        look = (
            cache_key(view.lat, view.lon, view.band, alt_m=view.alt_m)
            if view is not None
            else None
        )
        if (
            want == getattr(self, "_streets_on", None)
            and gen == getattr(self, "_roads_gen", None)
            and look == getattr(self, "_roads_view_key", None)
        ):
            return
        self._streets_on = want
        self._roads_gen = gen
        self._roads_view_key = look
        host.push_streets(want)
        try:
            from arelis.physics.telemetry import emit
            from arelis.ui.earth_globe_host import road_rows

            emit(
                "earth_roads",
                on=want,
                gen=gen,
                n=len(road_rows()) if want else 0,
                agl_m=getattr(self, "_earth_agl_m", None) or 0.0,
            )
        except Exception:
            pass

    def _sync_earth_globe(self, *, force: bool = False, camera: bool = False) -> None:
        host = self._globe_host
        if host is None or host.failed or not host.isVisible():
            return
        now = time.perf_counter()
        if (
            (camera or force)
            and not self._globe_flight_live()
            and not self._earth_globe_live()
        ):
            self._push_globe_camera()
        from arelis.earth.runtime import get_earth
        from arelis.ui.earth_globe_host import entity_rows, place_rows

        zone = get_earth()
        if zone is not None:
            self._push_streets_if_changed(zone)
        if not force and now - self._globe_data_push < 0.35:
            return
        self._globe_data_push = now
        host.push_entities(entity_rows())
        if zone is not None and zone.last_view is not None:
            host.push_places(
                place_rows(zone.last_view.band, zone.last_view.lat, zone.last_view.lon)
            )

    def _open_earth_look(self, hit) -> None:
        from arelis.earth.look import resolve

        handle = resolve(hit.id)
        if handle is None:
            self._close_earth_look()
            return
        if self._look_session is None:
            from arelis.ui.look_session import LookSession

            session = LookSession(self)
            session.frame.connect(self._on_look_frame)
            session.status.connect(self._on_look_status)
            self._look_session = session
        self._look_session.start(handle)

    def _close_earth_look(self) -> None:
        session = self._look_session
        if session is not None:
            session.stop()
        self._look_frame = None
        self._look_status = ""

    def _on_look_frame(self, image) -> None:
        self._look_frame = image
        self._chrome_key = None
        self._chrome_cache = None
        self.update()
        hud = getattr(self, "_earth_hud", None)
        if hud is not None:
            hud.update()

    def _on_look_status(self, text: str) -> None:
        self._look_status = str(text or "")
        self.update()

    def _fov_y(self) -> float:
        from arelis.earth.scale import EARTH_FOV_Y

        punch = 0.0 if self._warp is None else 0.18 * self._warp.speed01
        return EARTH_FOV_Y + punch

    def _travel_to(self, name: str) -> None:
        """Fly the inspect eye to ~8× IAU radius. Accel, cruise, slow. Not a burn."""
        system = get_system()
        if system is None:
            return
        body = system.nbody.find(name)
        if body is None:
            return
        sun = system.nbody.find("Sun")
        sun_p = (sun.x, sun.y, sun.z) if sun is not None else None
        self._warp = CameraWarp.start(
            self.cam,
            name,
            body.x,
            body.y,
            body.z,
            body.radius,
            sun_p,
        )
        try:
            from arelis.physics.telemetry import emit

            emit("travel", body=name, radius=body.radius)
        except Exception:
            pass
        self._fly_v = [0.0, 0.0, 0.0]
        self._set_inspect(name)
        self.update()

    def _step_warp(self, system: SolarSystem, dt: float) -> None:
        flight = self._warp
        if flight is None:
            return
        body = system.nbody.find(flight.name)
        if body is None:
            self._warp = None
            return
        sun = system.nbody.find("Sun")
        sun_p = (sun.x, sun.y, sun.z) if sun is not None else None
        flying = flight.step(
            self.cam, body.x, body.y, body.z, body.radius, sun_p, dt
        )
        if not flying:
            name = flight.name
            self._warp = None
            self._after_travel(name)

    def _finish_travel(self) -> None:
        """Snap to the standoff. Tests, not a shortcut in the plate."""
        flight = self._warp
        system = get_system()
        if flight is None or system is None:
            return
        body = system.nbody.find(flight.name)
        if body is None:
            self._warp = None
            return
        sun = system.nbody.find("Sun")
        sun_p = (sun.x, sun.y, sun.z) if sun is not None else None
        flight.snap(self.cam, body.x, body.y, body.z, body.radius, sun_p)
        name = flight.name
        self._warp = None
        self._after_travel(name)

    def _enter_earth_zone(self) -> None:
        """Earth-only zone door. Travel to is a solar-lab warp; this is Enter."""
        from arelis.earth.runtime import require_earth

        require_earth().enter()
        if self._inspect != "Earth":
            self._inspect = "Earth"
        self._remember_earth_eye()
        self._frame_earth_enter()
        self._enter_earth_globe()
        self._apply_pending_earth_goto()
        self.update()

    def _after_travel(self, name: str) -> None:
        from arelis.earth.runtime import get_earth

        if name == "Earth":
            self._earth_at_door = True
            self._set_inspect("Earth")
            self.update()
            return
        self._earth_at_door = False
        zone = get_earth()
        if zone is not None and zone.active:
            zone.stop_ride()
            zone.leave()
        self._earth_cam = None
        self._earth_id = None
        self._close_earth_look()
        self._leave_earth_globe()

    def _apply_pending_earth_goto(self) -> None:
        """Fly to a spoken or tool destination once Earth is the inspect body."""
        if self._warp is not None:
            return
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None or not zone.active:
            return
        dest = zone.take_goto()
        if dest is None:
            return
        self._select_earth_place(dest)

    def _earth_lock_ready(self, system: SolarSystem) -> bool:
        from arelis.earth.frames import earth_eye_locked
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None or not zone.active:
            return False
        earth = system.nbody.find("Earth")
        if earth is None:
            return False
        return earth_eye_locked(
            (earth.x, earth.y, earth.z),
            earth.radius,
            (self.cam.x, self.cam.y, self.cam.z),
        )

    def _hold_earth_eye(self, system: SolarSystem) -> None:
        """Keep the inspect eye on ECEF so the globe does not slide under you.

        Sleep follows accumulated sim time (`lock_due`). Physics still
        turns. At Travel standoff, spin is not visible until enough time
        or a closer eye makes it so. City slip is every tick.
        """
        from arelis.earth.frames import apply_earth_cam, earth_spin_jd
        from arelis.earth.lod import lock_due
        from arelis.earth.runtime import get_earth

        if self._earth_cam is None:
            return
        if self._earth_globe_live():
            return
        zone = get_earth()
        if zone is None or not zone.active or zone.ride_id:
            return
        earth = system.nbody.find("Earth")
        if earth is None:
            return
        view = zone.last_view
        alt_m = view.alt_m if view is not None else 44_600_000.0
        px_r = view.px_r if view is not None else 200.0
        last = float(getattr(self, "_earth_hold_t", 0.0) or 0.0)
        dt_s = float(system.t) - last
        if last > 0.0 and not lock_due(alt_m=alt_m, px_r=px_r, dt_s=dt_s):
            return
        self._earth_hold_t = float(system.t)
        apply_earth_cam(
            self.cam,
            (earth.x, earth.y, earth.z),
            earth_spin_jd(system.epoch_jd, system.t),
            self._earth_cam,
        )
        self._clamp_earth_eye(system)

    def _clamp_earth_eye(self, system: SolarSystem | None = None) -> None:
        """Inspect floor. Wheel/WASD must not put the eye inside the planet."""
        live = system if system is not None else get_system()
        if live is None or not self._earth_zone_on():
            return
        earth = live.nbody.find("Earth")
        if earth is None:
            return
        r_stop, _ = inspect_stop_m("Earth")
        r_max = max(float(earth.radius) * 20.0, r_stop * 4.0)
        eye = clamp_radial(
            (self.cam.x, self.cam.y, self.cam.z),
            (earth.x, earth.y, earth.z),
            r_stop,
            r_max,
        )
        if eye == (self.cam.x, self.cam.y, self.cam.z):
            return
        self.cam.x, self.cam.y, self.cam.z = eye
        self._remember_earth_eye(live)

    def _earth_wheel_zoom(self, delta: float) -> None:
        """Radial zoom toward the surface. Smooth, altitude-scaled, clamped."""
        system = get_system()
        if system is None:
            return
        earth = system.nbody.find("Earth")
        if earth is None:
            return
        factor = earth_zoom_factor(delta)
        if factor == 1.0:
            return
        r_stop, _ = inspect_stop_m("Earth")
        r_max = max(float(earth.radius) * 20.0, r_stop * 4.0)
        cx, cy, cz = earth.x, earth.y, earth.z
        dx, dy, dz = self.cam.x - cx, self.cam.y - cy, self.cam.z - cz
        dist = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        new = min(r_max, max(r_stop, dist * factor))
        s = new / dist
        self.cam.x = cx + dx * s
        self.cam.y = cy + dy * s
        self.cam.z = cz + dz * s
        self._remember_earth_eye(system)

    def _earth_fly_speed(self) -> float:
        system = get_system()
        if system is None:
            return max(80.0, float(self.cam.speed))
        earth = system.nbody.find("Earth")
        if earth is None:
            return max(80.0, float(self.cam.speed))
        if self._earth_globe_live():
            from arelis.earth.runtime import get_earth

            zone = get_earth()
            view = zone.last_view if zone is not None else None
            if view is not None:
                return earth_zone_speed(
                    float(earth.radius) + float(view.alt_m),
                    earth.radius,
                    self.cam.speed,
                )
        dist = math.hypot(
            self.cam.x - earth.x, self.cam.y - earth.y, self.cam.z - earth.z
        )
        return earth_zone_speed(dist, earth.radius, self.cam.speed)

    def _remember_earth_eye(self, system: SolarSystem | None = None) -> None:
        from arelis.earth.frames import capture_earth_cam, earth_spin_jd
        from arelis.earth.runtime import get_earth
        from arelis.physics.runtime import get_system as _live

        live = system if system is not None else _live()
        zone = get_earth()
        if self._earth_globe_live():
            return
        had = self._earth_cam is not None
        if live is None or zone is None or not zone.active:
            self._earth_cam = None
            if had:
                _emit_earth_lock(False)
            return
        if not self._earth_lock_ready(live):
            self._earth_cam = None
            if had:
                _emit_earth_lock(False)
            return
        earth = live.nbody.find("Earth")
        if earth is None:
            return
        self._earth_cam = capture_earth_cam(
            self.cam,
            (earth.x, earth.y, earth.z),
            earth_spin_jd(live.epoch_jd, live.t),
        )
        if not had:
            _emit_earth_lock(True)

    def _follow_earth_ride(self, system: SolarSystem | None) -> None:
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None or not zone.ride_id:
            return
        ent = zone.get(zone.ride_id)
        if ent is None:
            return
        if self._earth_globe_live():
            if not globe_ride_layer(getattr(ent, "layer", "")):
                if getattr(self, "_globe_rode", None) != ent.id:
                    self._fly_to_earth_entity(ent)
                    self._globe_rode = ent.id
                    zone.stop_ride()
                    zone.track(ent.id)
                return
            self._globe_follow_ride(ent)
            return
        if system is None:
            return
        pose = None
        if ent.layer == "cameras":
            pose = look_from_pose(system, ent)
        if pose is None:
            pose = ride_pose(system, ent)
        if pose is None:
            return
        eye, look, up = pose
        self.cam.x, self.cam.y, self.cam.z = eye
        self.cam.aim(look[0], look[1], look[2], up=up)
        self._clamp_earth_eye(system)

    def _aim_earth_track(self, system: SolarSystem) -> None:
        """Keep the look pin on the tracked contact. Softer than ride.

        Runs after `_remember_earth_eye` so the recapture cannot undo the
        aim. Applies the pose onto the fly camera the same tick.
        """
        from arelis.earth.frames import EarthCam, apply_earth_cam, earth_spin_jd
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None or not zone.track_id or zone.ride_id:
            return
        ent = zone.get(zone.track_id)
        if ent is None:
            return
        if self._earth_globe_live():
            return
        pose = self._earth_cam
        if pose is None:
            return
        earth = system.nbody.find("Earth")
        if earth is None:
            return
        self._earth_cam = EarthCam(
            eye=pose.eye,
            look=(ent.x, ent.y, ent.z),
            up=pose.up,
        )
        apply_earth_cam(
            self.cam,
            (earth.x, earth.y, earth.z),
            earth_spin_jd(system.epoch_jd, system.t),
            self._earth_cam,
        )

    def _fly_ride_sit(self, ent) -> None:
        """Leave 20 Mm the same way a place hop does — a fly, not a snap."""
        from arelis.earth.frames import MEAN_R, ecef_to_geodetic

        host = self._globe_host
        if host is None:
            return
        try:
            lat, lon, alt = ecef_to_geodetic(ent.x, ent.y, ent.z)
        except Exception:
            self._globe_follow_ride(ent)
            return
        if getattr(ent, "layer", "") == "iss":
            sit = 80_000.0
        else:
            sit = max(40.0, min(250.0, 0.00002 * (abs(alt) + MEAN_R)))
        if not self._go_earth_lla(lat, lon, max(200.0, alt + sit), leave=False):
            self._globe_follow_ride(ent)
            return
        self._globe_rode = ent.id

    def _globe_follow_ride(self, ent) -> None:
        """Sit on the contact in Cesium. Do not spin the parked solar cam."""
        from arelis.earth.frames import MEAN_R, ecef_to_geodetic
        from arelis.ui.earth_marks import heading_of

        host = self._globe_host
        if host is None:
            return
        now = time.perf_counter()
        last = float(getattr(self, "_globe_ride_push", 0.0) or 0.0)
        gap = 0.7 if getattr(ent, "layer", "") == "iss" else 0.35
        if now - last < gap:
            return
        self._globe_ride_push = now
        try:
            lat, lon, alt = ecef_to_geodetic(ent.x, ent.y, ent.z)
        except Exception:
            return
        heading = heading_of(ent)
        speed = math.hypot(float(ent.vx), float(ent.vy), float(ent.vz))
        if getattr(ent, "layer", "") == "iss":
            sit = 80_000.0
            pitch = -28.0
        else:
            sit = max(40.0, min(250.0, 0.00002 * (abs(alt) + MEAN_R)))
            pitch = -12.0 if speed >= 0.5 else -90.0
        first = getattr(self, "_globe_rode", None) != ent.id
        if first:
            self._globe_rode = ent.id
        dest_alt = max(200.0, alt + sit)
        yaw = heading if heading is not None else 0.0
        if hasattr(host, "follow_lla"):
            host.follow_lla(lat, lon, dest_alt, yaw, pitch)
            return
        host.push_camera(
            lat,
            lon,
            dest_alt,
            yaw,
            pitch,
            soft=not first,
            keep_ride=True,
        )

    def _globe_aim_track(self, ent) -> None:
        """Point Cesium at the tracked contact. Eye stays put."""
        from arelis.earth.frames import ecef_to_geodetic

        host = self._globe_host
        if host is None:
            return
        try:
            lat, lon, alt = ecef_to_geodetic(ent.x, ent.y, ent.z)
        except Exception:
            return
        host.push_aim(lat, lon, alt)

    def _copy_earth_view(self) -> None:
        """Clipboard receipt: eye, band, chips, one target. No stream URLs."""
        from arelis.earth.dump import view_receipt
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None:
            return
        text = json.dumps(
            view_receipt(zone, camera=getattr(self, "_earth_cam", None)),
            indent=2,
            sort_keys=True,
        )
        clip = QApplication.clipboard()
        if clip is not None:
            clip.setText(text)

    def _sync_earth_look(self) -> None:
        """Tool/voice ride or track should open the same live look as a click."""
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None or not zone.active or not zone.ride_id:
            return
        eid = zone.ride_id
        session = self._look_session
        if session is not None and session.active_id() == eid:
            return
        hit = zone.get(eid)
        if hit is None:
            return
        self._earth_id = hit.id
        self._open_earth_look(hit)

