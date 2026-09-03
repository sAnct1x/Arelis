"""Earth-zone camera, Cesium globe mount, and look-from on SolarPanel.

Cesium / enter-Earth lives here. Arelis paints stars + sodium HUD; the
planet is Cesium. Photoreal only when close. A photoreal miss must not
set host.failed. stars_only + park keep Chromium off the shared GL
context. Do not delete this as dead code.
"""
from __future__ import annotations

import json
import os
import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage

from arelis.physics.camera import CameraWarp
from arelis.physics.runtime import get_system
from arelis.physics.scene import SolarSystem
from arelis.ui.earth_overlay import look_from_pose, ride_pose


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
        self._open_earth_look(hit)
        self.update()

    def _select_earth_place(self, geo: dict) -> None:
        from arelis.earth.frames import EarthCam, nadir_cam
        from arelis.earth.runtime import get_earth

        self._earth_id = None
        self._close_earth_look()
        self._place = geo
        zone = get_earth()
        if zone is not None:
            zone.stop_ride()
            zone.track_id = ""
        if self._earth_cam is None:
            self._remember_earth_eye()
        kind = str(geo.get("kind") or "earth")
        alt = {
            "city": 80_000.0,
            "home": 80_000.0,
            "contact": 80_000.0,
            "state": 350_000.0,
            "province": 350_000.0,
            "country": 1_100_000.0,
            "continent": 5_000_000.0,
        }.get(kind, 2_400_000.0)
        dest = nadir_cam(float(geo["lat"]), float(geo["lon"]), alt)
        start = self._earth_cam if isinstance(self._earth_cam, EarthCam) else dest
        self._earth_fly = {"start": start, "end": dest, "t": 0.0, "dur": 1.05}
        self._earth_cam = start
        self.update()

    def _step_earth_fly(self, dt: float) -> None:
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
        if self._earth_globe_live():
            self._push_globe_camera()

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
        self._close_earth_look()
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

    def _enter_earth_globe(self) -> None:
        system = get_system()
        if system is not None:
            try:
                system.go_realtime()
            except Exception:
                pass
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        self._park_space_for_earth()
        if self._globe_host is None:
            if getattr(self, "_globe_mounting", False):
                return
            self._globe_mounting = True
            QTimer.singleShot(0, self._mount_earth_globe)
            return
        self._show_earth_globe()

    def _mount_earth_globe(self) -> None:
        self._globe_mounting = False
        if os.environ.get("PYTEST_CURRENT_TEST"):
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
            host = EarthGlobeHost(self)
            host.bridge.hostPicked.connect(self._on_globe_pick)
            host.bridge.hostCamera.connect(self._on_globe_camera)
            host.bridge.hostReady.connect(lambda _k: self._on_globe_ready())
            host.bridge.hostTiles.connect(lambda _k: self._on_globe_ready())
            host.bridge.hostFailed.connect(lambda _w: self._on_globe_failed())
            self._globe_host = host
        if self._earth_hud is None and self._globe_host is not None:
            self._earth_hud = EarthHudGlass(self)
        self._show_earth_globe()

    def _show_earth_globe(self) -> None:
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
            view = getattr(self, "_earth_cam", None)
            zone = None
            try:
                from arelis.earth.frames import ecef_to_geodetic
                from arelis.earth.runtime import get_earth

                zone = get_earth()
                if view is not None:
                    lat, lon, alt = ecef_to_geodetic(*view.eye)
                    host.push_camera(lat, lon, max(alt, 80_000.0))
            except Exception:
                pass
            host.push_entities(entity_rows())
            if zone is not None and zone.last_view is not None:
                host.push_places(
                    place_rows(zone.last_view.band, zone.last_view.lat, zone.last_view.lon)
                )
                host.push_streets(bool(zone.tiles))
                host.push_buildings()
        self.update()

    def _park_space_for_earth(self) -> None:
        """Last starfield, then stay off the shared GL context.

        Chromium aborts if the offscreen solar context is current — or
        becomes current again — while QWebEngineView is alive.
        """
        gl = getattr(self, "_gl", None)
        if gl is None:
            return
        if not getattr(gl, "_parked", False):
            try:
                frame = gl.render(
                    max(self.width(), 1), max(self.height(), 1), stars_only=True
                )
                if frame is not None and not frame.isNull():
                    self._stars_hold = QImage(frame)
            except Exception:
                pass
        if hasattr(gl, "park"):
            gl.park()
        else:
            gl.release_current()

    def _leave_earth_globe(self) -> None:
        self._globe_mounting = False
        self._stars_hold = None
        gl = getattr(self, "_gl", None)
        if gl is not None and hasattr(gl, "unpark"):
            gl.unpark()
        if self._globe_host is not None:
            self._globe_host.hide()
        if self._earth_hud is not None:
            self._earth_hud.hide()
        self._globe_hpr = None

    def _layout_earth_globe(self) -> None:
        if self._globe_host is not None:
            self._globe_host.setGeometry(self.rect())
        if self._earth_hud is not None:
            self._earth_hud.setGeometry(self.rect())
            host = self._globe_host
            if host is not None and not host.failed and host.isVisible():
                self._earth_hud.show()
                self._earth_hud.raise_()
            else:
                self._earth_hud.hide()

    def _on_globe_ready(self) -> None:
        self._layout_earth_globe()
        self._sync_earth_globe(force=True)
        self.update()

    def _on_globe_failed(self) -> None:
        self._leave_earth_globe()
        self.update()

    def _on_globe_pick(self, entity_id: str) -> None:
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None:
            return
        hit = zone.get(entity_id)
        if hit is None:
            return
        self._earth_id = hit.id
        zone.track(hit.id)
        self._open_earth_look(hit)
        self.update()

    def _on_globe_camera(self, raw: str) -> None:
        if self._keys or self._earth_fly is not None:
            return
        try:
            payload = json.loads(raw)
            lat = float(payload["lat"])
            lon = float(payload["lon"])
            alt = float(payload["alt_m"])
            heading = float(payload.get("heading") or 0.0)
            pitch = float(payload.get("pitch") or -90.0)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return
        from arelis.earth.frames import nadir_cam

        self._globe_hpr = (heading, pitch)
        self._earth_cam = nadir_cam(lat, lon, alt)
        self._remember_earth_eye()
        try:
            from arelis.physics.runtime import get_system
            from arelis.ui.earth_overlay import sync_earth_view

            system = get_system()
            if system is not None:
                sync_earth_view(self, system)
        except Exception:
            pass
        self.update()

    def _push_globe_camera(self) -> None:
        host = self._globe_host
        pose = self._earth_cam
        if host is None or host.failed or not host.isVisible() or pose is None:
            return
        from arelis.earth.frames import ecef_to_geodetic

        lat, lon, alt = ecef_to_geodetic(*pose.eye)
        heading, pitch = self._globe_hpr if self._globe_hpr is not None else (None, None)
        host.push_camera(lat, lon, max(alt, 200.0), heading, pitch)
        self._globe_cam_push = time.perf_counter()

    def _sync_earth_globe(self, *, force: bool = False, camera: bool = False) -> None:
        host = self._globe_host
        if host is None or host.failed or not host.isVisible():
            return
        now = time.perf_counter()
        if camera or force:
            self._push_globe_camera()
        if not force and now - self._globe_data_push < 1.0:
            return
        self._globe_data_push = now
        from arelis.earth.runtime import get_earth
        from arelis.ui.earth_globe_host import entity_rows, place_rows

        host.push_entities(entity_rows())
        zone = get_earth()
        if zone is not None and zone.last_view is not None:
            host.push_places(
                place_rows(zone.last_view.band, zone.last_view.lat, zone.last_view.lon)
            )
            host.push_streets(bool(zone.tiles))
            host.push_buildings()

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
        self.update()

    def _on_look_status(self, text: str) -> None:
        self._look_status = str(text or "")
        self.update()

    def _fov_y(self) -> float:
        punch = 0.0 if self._warp is None else 0.18 * self._warp.speed01
        return 0.70 + punch

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

    def _after_travel(self, name: str) -> None:
        from arelis.earth.runtime import get_earth, require_earth

        if name == "Earth":
            require_earth().enter()
            self._remember_earth_eye()
            self._enter_earth_globe()
            self._apply_pending_earth_goto()
            return
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
        """Keep the inspect eye on ECEF so the globe does not slide under you."""
        from arelis.earth.frames import apply_earth_cam, earth_spin_jd
        from arelis.earth.runtime import get_earth

        if self._earth_cam is None:
            return
        zone = get_earth()
        if zone is None or not zone.active or zone.ride_id:
            return
        earth = system.nbody.find("Earth")
        if earth is None:
            return
        apply_earth_cam(
            self.cam,
            (earth.x, earth.y, earth.z),
            earth_spin_jd(system.epoch_jd, system.t),
            self._earth_cam,
        )

    def _remember_earth_eye(self, system: SolarSystem | None = None) -> None:
        from arelis.earth.frames import capture_earth_cam, earth_spin_jd
        from arelis.earth.runtime import get_earth
        from arelis.physics.runtime import get_system as _live

        live = system if system is not None else _live()
        zone = get_earth()
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

    def _follow_earth_ride(self, system: SolarSystem) -> None:
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None or not zone.ride_id:
            return
        ent = zone.get(zone.ride_id)
        if ent is None:
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

