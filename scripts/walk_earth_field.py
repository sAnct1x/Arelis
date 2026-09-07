"""Live Reality field walk. Every beat waits for Cesium, then holds.

Pytest owns the contract (tests/test_earth_field.py). This script is
the eyes. A beat is not proven from Python logs. Cesium must land,
the walk window must stay on screen, and the PNG + PROOF.jsonl must
agree. A miss is written as a miss.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.pop("PYTEST_CURRENT_TEST", None)
os.environ["ARELIS_SOLAR_GL"] = "1"
if sys.platform == "win32":
    os.environ["QT_QPA_PLATFORM"] = "windows"

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication

DEST = ROOT / ".tmp-earth-field"
PROOF = DEST / "PROOF.jsonl"
HOLD_S = 7.0
WIN_W, WIN_H = 1600, 1000


def _banner(msg: str) -> None:
    bar = "=" * 72
    print(f"\n{bar}\n  {msg}\n{bar}", flush=True)


def _pump(app: QApplication, ms: int) -> None:
    app.processEvents()
    t0 = time.perf_counter()
    while (time.perf_counter() - t0) * 1000 < ms:
        app.processEvents()


def _luma_ok(img: QImage) -> bool:
    """Empty HWND is ~0. Dark ocean is still Earth."""
    if img.isNull() or img.width() < 16 or img.height() < 16:
        return False
    w, h = img.width(), img.height()
    samples: list[float] = []
    for xf in (0.35, 0.50, 0.65):
        for yf in (0.40, 0.55, 0.70):
            c = img.pixelColor(int(w * xf), int(h * yf))
            samples.append((c.red() + c.green() + c.blue()) / 3.0)
    return max(samples) > 6.0


def _screen_size(screen) -> tuple[int, int]:
    geo = screen.geometry()
    return geo.width(), geo.height()


def _window_rect(top, hud=None) -> QRect:
    frame = top.frameGeometry()
    client = QRect(top.mapToGlobal(QPoint(0, 0)), top.size())
    geo = frame if frame.width() >= 400 else client
    if hud is not None and hud.isVisible():
        hg = hud.frameGeometry()
        if hg.width() <= geo.width() + 80 and hg.height() <= geo.height() + 80:
            geo = geo.united(hg)
    return geo


def _seat_left(panel) -> None:
    """Put the walk on the leftmost screen. That's the chair, not primary."""
    screens = list(QGuiApplication.screens() or [])
    if not screens:
        return
    left = min(screens, key=lambda s: s.geometry().x())
    geo = left.availableGeometry()
    top = panel.window()
    x = geo.x() + 80
    y = geo.y() + 80
    top.setGeometry(x, y, WIN_W, WIN_H)
    print(
        f"seat {left.name()} geo={x},{y} {WIN_W}x{WIN_H} "
        f"screen={geo.x()},{geo.y()} {geo.width()}x{geo.height()}",
        flush=True,
    )


def _front(panel) -> None:
    """Stay on whichever monitor the operator dragged it to."""
    top = panel.window()
    hud = getattr(panel, "_earth_hud", None)
    top.show()
    top.raise_()
    host = getattr(panel, "_globe_host", None)
    pin = getattr(host, "pin_child", None)
    if callable(pin):
        pin()
    if hud is not None:
        hud.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        hud.show()
        from arelis.ui.earth_globe_host import stack_chrome_over_globe

        stack_chrome_over_globe(hud, host)
        hud.raise_()
    top.activateWindow()


def _grab(app: QApplication, panel, name: str) -> tuple[Path, dict[str, object]]:
    """Desktop crop of the walk window. Child Cesium HWND grabs are black."""
    DEST.mkdir(parents=True, exist_ok=True)
    top = panel.window()
    _front(panel)
    app.processEvents()
    dest = DEST / name
    screen = QGuiApplication.screenAt(top.frameGeometry().center())
    if screen is None:
        screen = top.screen() or QGuiApplication.primaryScreen()
    meta: dict[str, object] = {"png": name, "bytes": 0, "luma_ok": False}
    if screen is None:
        print(f"no screen for {name}", flush=True)
        return dest, meta
    sw, sh = _screen_size(screen)
    hud = getattr(panel, "_earth_hud", None)
    geo = _window_rect(top, hud)
    origin = screen.geometry().topLeft()
    local = QRect(
        geo.x() - origin.x(),
        geo.y() - origin.y(),
        geo.width(),
        geo.height(),
    )
    print(
        f"grab geo={geo.x()},{geo.y()} {geo.width()}x{geo.height()} "
        f"local={local.x()},{local.y()} screen={sw}x{sh} "
        f"name={screen.name()}",
        flush=True,
    )
    full = screen.grabWindow(0)
    out = full.copy(local).toImage()
    source = "screen_local"
    if out.isNull() or out.width() < 200:
        print(
            f"grab miss local={local.x()},{local.y()} {local.width()}x{local.height()}",
            flush=True,
        )
    desktop = out.width() >= sw - 8 and out.height() >= sh - 8
    if desktop:
        print(f"grab still looks like the desktop for {name}", flush=True)
        source = f"{source}+desktop_suspect"
    out.save(str(dest), "PNG")
    meta.update(
        {
            "w": out.width(),
            "h": out.height(),
            "bytes": dest.stat().st_size if dest.exists() else 0,
            "luma_ok": _luma_ok(out),
            "source": source,
            "desktop_suspect": desktop,
            "geo": f"{geo.x()},{geo.y()},{geo.width()}x{geo.height()}",
        }
    )
    print(
        f"wrote {dest}  {out.width()}x{out.height()}  "
        f"luma_ok={meta['luma_ok']}  src={source}",
        flush=True,
    )
    return dest, meta


def _pose(panel) -> tuple[float | None, float | None, float | None]:
    """Cesium's last emit only. Python's intended eye is not proof."""
    lla = getattr(panel, "_cesium_lla", None)
    if isinstance(lla, tuple) and len(lla) >= 3:
        try:
            return float(lla[0]), float(lla[1]), float(lla[2])
        except (TypeError, ValueError):
            return None, None, None
    return None, None, None


def _landed(
    panel, lat: float, lon: float, alt_m: float
) -> tuple[bool, float | None, float | None, float | None]:
    got_lat, got_lon, got_alt = _pose(panel)
    if got_alt is None or got_lat is None or got_lon is None:
        return False, got_lat, got_lon, got_alt
    if abs(got_alt - alt_m) / max(alt_m, 1.0) > 0.08:
        return False, got_lat, got_lon, got_alt
    if abs(got_lat - lat) > 0.85 or abs(got_lon - lon) > 0.85:
        return False, got_lat, got_lon, got_alt
    if alt_m < 400_000.0:
        look = getattr(panel, "_cesium_look", None)
        if not (isinstance(look, tuple) and len(look) >= 2):
            return False, got_lat, got_lon, got_alt
        try:
            if abs(float(look[0]) - lat) > 0.85 or abs(float(look[1]) - lon) > 0.85:
                return False, got_lat, got_lon, got_alt
        except (TypeError, ValueError):
            return False, got_lat, got_lon, got_alt
    return True, got_lat, got_lon, got_alt


def _unlock(panel) -> None:
    clear = getattr(panel, "_clear_earth_pick", None)
    if callable(clear):
        clear()
        return
    from arelis.earth.runtime import get_earth

    zone = get_earth()
    if zone is not None:
        zone.unlock()
    panel._earth_id = None


def _place(
    app: QApplication, panel, lat: float, lon: float, alt_m: float, seconds: float = 28.0
) -> dict[str, object]:
    """Same door as /find. Wait until Cesium emits this pose."""
    from arelis.earth.runtime import get_earth

    panel._cesium_lla = None
    panel._globe_hpr = (0.0, -90.0)
    panel._select_earth_place(
        {"lat": lat, "lon": lon, "kind": "city", "alt_m": alt_m}
    )
    deadline = time.perf_counter() + seconds
    ok = False
    got_lat = got_lon = got_alt = None
    while time.perf_counter() < deadline:
        _pump(app, 200)
        _front(panel)
        ok, got_lat, got_lon, got_alt = _landed(panel, lat, lon, alt_m)
        if ok:
            break
    host = getattr(panel, "_globe_host", None)
    zone = get_earth()
    if zone is not None:
        zone.tick(unix=time.time())
        if host is not None and panel._earth_globe_live():
            from arelis.ui.earth_globe_host import entity_rows

            host.push_entities(entity_rows())
    print(
        f"place want={lat:.3f},{lon:.3f} @{alt_m:.0f}m  "
        f"got={got_lat},{got_lon} @{got_alt}  landed={ok}",
        flush=True,
    )
    return {
        "want_lat": lat,
        "want_lon": lon,
        "want_alt_m": alt_m,
        "got_lat": got_lat,
        "got_lon": got_lon,
        "got_alt_m": got_alt,
        "landed": ok,
    }


def _only(zone, on: set[str]) -> None:
    from arelis.earth.entity import LAYER_IDS

    for key in LAYER_IDS:
        zone.set_layer(key, key in on)


def _counts(zone) -> dict[str, int]:
    vis = list(zone.visible()) if zone is not None else []
    return dict(Counter(e.layer for e in vis))


def _note(tag: str) -> dict[str, object]:
    from arelis.earth.runtime import get_earth

    zone = get_earth()
    view = getattr(zone, "last_view", None) if zone is not None else None
    counts = _counts(zone)
    row = {
        "tag": tag,
        "band": getattr(view, "band", None),
        "alt_m": getattr(view, "alt_m", None),
        "lat": getattr(view, "lat", None),
        "lon": getattr(view, "lon", None),
        "live": getattr(zone, "live", None),
        "busy": getattr(zone, "_live_busy", None),
        "inflight": sorted(getattr(zone, "_live_inflight", set()) or ()),
        "fetch": sorted((getattr(zone, "last_fetch_unix", {}) or {}).keys()),
        "visible": counts,
        "visible_n": sum(counts.values()),
        "fresh": dict(
            Counter(e.freshness for e in (zone.visible() if zone is not None else []))
        ),
    }
    print(
        f"{tag} band={row['band']} cesium_alt={row['alt_m']} "
        f"look={row['lat']},{row['lon']} live={row['live']} "
        f"busy={row['busy']} inflight={row['inflight']} "
        f"fetch={row['fetch']} visible={row['visible_n']} {counts} "
        f"fresh={row['fresh']}",
        flush=True,
    )
    return row


def _wait_fetch(app: QApplication, *keys: str, seconds: float = 20.0) -> bool:
    from arelis.earth.runtime import get_earth

    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        _pump(app, 400)
        zone = get_earth()
        if zone is None:
            continue
        zone.tick(unix=time.time())
        got = zone.last_fetch_unix or {}
        if all(key in got for key in keys):
            return True
    return False


def _wait_visible(
    app: QApplication, layer: str, n: int = 1, seconds: float = 24.0
) -> int:
    from arelis.earth.runtime import get_earth

    deadline = time.perf_counter() + seconds
    count = 0
    while time.perf_counter() < deadline:
        _pump(app, 400)
        zone = get_earth()
        if zone is None:
            continue
        zone.tick(unix=time.time())
        count = sum(1 for e in zone.visible() if e.layer == layer)
        if count >= n:
            return count
    return count


def _title(panel, step: str) -> None:
    panel.setWindowTitle(f"REALITY WALK — {step} — WATCH THIS WINDOW")


def _announce(panel, title: str, line: str) -> None:
    """Put the beat on the glass. A stranger cannot read the terminal."""
    from arelis.ui.earth_chrome import set_earth_say

    panel.setWindowTitle(f"REALITY WALK — {title} — WATCH THIS WINDOW")
    set_earth_say(panel, title, line)
    _paint(panel)


def _hold(app: QApplication, seconds: float = HOLD_S) -> None:
    print(f"holding {seconds:.1f}s so you can see it", flush=True)
    _pump(app, int(seconds * 1000))


def _proof(step: str, **fields: object) -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    row = {"step": step, "t": time.time(), **fields}
    with PROOF.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
    print(f"PROOF {step} ok={row.get('ok')} {row.get('why', '')}", flush=True)


def _write_proof_md(rows: list[dict[str, object]]) -> None:
    dest = DEST / "PROOF.md"
    lines = [
        "# Reality field walk proof",
        "",
        "A beat is proven only when Cesium landed, the grab is the walk",
        "window (not the desktop), and the required marks were visible",
        "or the miss is named.",
        "",
        "| Step | Landed | Luma | Visible | OK | Why |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        vis = row.get("visible") or {}
        lines.append(
            f"| {row.get('step')} | {row.get('landed')} | {row.get('luma_ok')} "
            f"| {vis} | {row.get('ok')} | {row.get('why', '')} |"
        )
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {dest}", flush=True)


def _paint(panel) -> None:
    hud = getattr(panel, "_earth_hud", None)
    panel.update()
    if hud is not None:
        hud.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        hud.show()
        hud.raise_()
        hud.update()


def _wait_hud(app: QApplication, panel, *, card: bool = False, seconds: float = 6.0) -> bool:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        _paint(panel)
        _front(panel)
        _pump(app, 200)
        chips = getattr(panel, "_earth_chip_box", None)
        have_chips = chips is not None and not chips.isEmpty()
        if not card:
            if have_chips:
                return True
            continue
        box = getattr(panel, "_earth_card_box", None)
        if have_chips and box is not None and not box.isEmpty():
            return True
    return False


def main() -> int:
    from arelis.earth.firms import firms_key
    from arelis.earth.lod import entity_lla
    from arelis.earth.look import resolve
    from arelis.earth.runtime import get_earth, set_earth
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import set_system
    from arelis.ui.earth_globe_host import webengine_available
    from arelis.ui.glass import seal_tool_window
    from arelis.ui.panels.solar import SolarPanel
    from arelis.ui.solar_gl import prepare_desktop_gl
    from arelis.ui.theme import app_font, load_fonts
    from arelis.ui.window_resize import configure_native_windows

    if not rebound_available():
        print("rebound missing", file=sys.stderr)
        return 2

    if PROOF.exists():
        PROOF.unlink()

    prepare_desktop_gl(os.environ)
    configure_native_windows()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL, True)
    app = QApplication.instance() or QApplication([])
    app.setFont(app_font(load_fonts()))
    print(f"webengine={webengine_available()}", flush=True)

    set_system(None)
    set_earth(None)
    solar = SolarPanel()
    solar._ensure_ic()
    solar.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    solar.resize(WIN_W, WIN_H)
    _announce(solar, "Solar lab", "The desk before Earth. Then we enter the planet.")
    seal_tool_window(solar)
    solar.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    solar.show()
    solar.raise_()
    solar.activateWindow()
    _pump(app, 200)
    _seat_left(solar)
    solar.raise_()
    solar.activateWindow()
    _pump(app, 500)
    rows: list[dict[str, object]] = []
    code = 0

    def beat(step: str, *, ok: bool, why: str, place: dict | None = None, **extra):
        _paint(solar)
        _front(solar)
        _hold(app)
        _path, grab = _grab(app, solar, f"{step}.png")
        landed = True if place is None else bool(place.get("landed"))
        note = _note(step)
        dark_ok = step.startswith("00-")
        proven = (
            ok
            and landed
            and (dark_ok or bool(grab.get("luma_ok")))
            and not grab.get("desktop_suspect")
        )
        if not landed:
            why = f"cesium did not land — {why}"
        elif not dark_ok and not grab.get("luma_ok"):
            why = f"grab is black or empty — {why}"
        elif grab.get("desktop_suspect"):
            why = f"grab looks like the desktop — {why}"
        row = {
            "step": step,
            "ok": proven,
            "why": why,
            "landed": landed,
            **(place or {}),
            **note,
            **grab,
            **extra,
        }
        rows.append(row)
        _proof(**row)

    _banner("00 SOLAR LAB — starting window. You should see the lab.")
    beat("00-solar", ok=True, why="solar lab before Enter")

    _banner("01 ENTER EARTH — waiting for Cesium. Do not look away.")
    _announce(
        solar,
        "Earth from 20,000 km",
        "The whole planet. Night cities should glow. This is the finished mosaic, not a loading hole.",
    )
    solar._enter_earth_zone()
    _pump(app, 200)
    host = solar._globe_host
    deadline = time.perf_counter() + 70.0
    while time.perf_counter() < deadline:
        _pump(app, 250)
        host = solar._globe_host
        if host is not None and (host.ready or host.failed):
            break
    print(
        f"host={host is not None} ready={getattr(host, 'ready', None)} "
        f"failed={getattr(host, 'failed', None)} kind={getattr(host, 'kind', None)} "
        f"hwnd={getattr(host, '_hwnd', None)}",
        flush=True,
    )
    if host is None or not host.ready:
        beat("01-enter-space", ok=False, why="cesium did not come up")
        _write_proof_md(rows)
        solar.close()
        QTimer.singleShot(0, app.quit)
        app.processEvents()
        return 3

    space_ready = False
    deadline = time.perf_counter() + 16.0
    while time.perf_counter() < deadline:
        _pump(app, 250)
        _front(solar)
        pose = _pose(solar)
        if pose[2] is not None and pose[2] > 1.0e6:
            space_ready = True
            break
    hud_chips = _wait_hud(app, solar, card=False, seconds=6.0)
    celestrak = _wait_fetch(app, "celestrak", seconds=22.0)
    vis_sats = _wait_visible(app, "satellites", n=1, seconds=8.0)
    beat(
        "01-enter-space",
        ok=space_ready and vis_sats >= 1 and hud_chips,
        why=(
            f"cesium={_pose(solar)} celestrak={celestrak} "
            f"sats={vis_sats} hud_chips={hud_chips}"
        ),
        place={
            "landed": space_ready,
            "got_alt_m": _pose(solar)[2],
        },
        celestrak=celestrak,
        hud_chips=hud_chips,
    )

    zone = get_earth()
    iss = zone.get("norad:25544") if zone is not None else None
    _banner("02 ISS CARD — click the station. Ride it. Do not park at 1.2 Mm.")
    _announce(
        solar,
        "Click the ISS — ride it",
        "You should sit ~500 km above the station and move with it. A still Himalaya means the ride failed.",
    )
    iss_place = None
    rode = False
    if iss is not None:
        pair = entity_lla(iss)
        if pair is not None:
            hop = _place(app, solar, pair[0], pair[1], 500_000.0)
            rode = bool(hop.get("landed"))
            iss_place = {**hop, "ride": rode}
            if rode:
                print(f"iss-ride sit cesium={_pose(solar)}", flush=True)
        solar._select_earth_entity(iss, ride=True)
        _paint(solar)
        ride_until = time.perf_counter() + (4.0 if rode else 12.0)
        while time.perf_counter() < ride_until:
            if zone is not None:
                zone.tick(unix=time.time())
            solar._tick()
            _pump(app, 200)
            _front(solar)
            pose = _pose(solar)
            alt = pose[2]
            if alt is not None and 80_000.0 <= alt <= 900_000.0:
                rode = True
                iss_place = {
                    "want_alt_m": 500_000.0,
                    "got_lat": pose[0],
                    "got_lon": pose[1],
                    "got_alt_m": alt,
                    "landed": True,
                    "ride": True,
                }
                print(f"iss-ride sit cesium={pose}", flush=True)
                break
        if not rode:
            pose = _pose(solar)
            iss_place = {
                "got_lat": pose[0],
                "got_lon": pose[1],
                "got_alt_m": pose[2],
                "landed": False,
                "ride": False,
            }
            print(f"iss-ride miss cesium={pose}", flush=True)
        if rode:
            _announce(
                solar,
                "You are on the ISS",
                "Sit is ~500 km above the station. The ground should drift.",
            )
        else:
            _announce(
                solar,
                "ISS ride missed",
                "Still parked at 20,000 km. That is a miss, not a ride.",
            )
    card_on = _wait_hud(app, solar, card=True, seconds=6.0)
    card = ""
    try:
        from arelis.ui.earth_overlay import inspect_card_text

        if iss is not None:
            card = inspect_card_text(iss)
    except Exception:
        card = ""
    beat(
        "02-iss-card",
        ok=iss is not None and "ISS" in card and card_on and rode,
        why=(
            f"iss={iss is not None} card_has_ISS={'ISS' in card} "
            f"hud_card={card_on} rode={rode}"
        ),
        place=iss_place,
        card_excerpt=card[:160],
        hud_card=card_on,
        rode=rode,
    )

    _banner("03 ISS COAST — five seconds of motion. Station must move.")
    _announce(
        solar,
        "ISS coast",
        "Five seconds. The ground under the station must drift. If this frame matches the last, we are parked.",
    )
    drift = 0.0
    look0 = getattr(solar, "_cesium_look", None)
    cam0 = _pose(solar)
    if iss is not None and zone is not None:
        x0, y0, z0 = iss.x, iss.y, iss.z
        for _ in range(8):
            zone.tick(unix=time.time())
            solar._tick()
            follow = getattr(solar, "_globe_follow_ride", None)
            if callable(follow):
                follow(iss)
            if solar._earth_globe_live() and host is not None:
                from arelis.ui.earth_globe_host import entity_rows

                host.push_entities(entity_rows())
            print(
                f"iss-coast tick ride={zone.ride_id} "
                f"globe={solar._earth_globe_live()} cesium={_pose(solar)}",
                flush=True,
            )
            _paint(solar)
            _pump(app, 700)
        later = zone.get("norad:25544")
        if later is not None:
            drift = (
                (later.x - x0) ** 2 + (later.y - y0) ** 2 + (later.z - z0) ** 2
            ) ** 0.5
            print(f"iss-coast drift_m={drift:.0f}", flush=True)
    look1 = getattr(solar, "_cesium_look", None)
    look_deg = 0.0
    if (
        isinstance(look0, tuple)
        and isinstance(look1, tuple)
        and look0[0] is not None
        and look1[0] is not None
    ):
        look_deg = (
            (float(look1[0]) - float(look0[0])) ** 2
            + (float(look1[1]) - float(look0[1])) ** 2
        ) ** 0.5
        print(f"iss-coast look_deg={look_deg:.4f}", flush=True)
    cam1 = _pose(solar)
    cam_deg = 0.0
    if cam0[0] is not None and cam1[0] is not None:
        cam_deg = (
            (float(cam1[0]) - float(cam0[0])) ** 2
            + (float(cam1[1]) - float(cam0[1])) ** 2
        ) ** 0.5
        print(f"iss-coast cam_deg={cam_deg:.4f} {cam0} -> {cam1}", flush=True)
    beat(
        "03-iss-coast",
        ok=drift > 100.0 and (look_deg > 0.02 or cam_deg > 0.02),
        why=f"drift_m={drift:.0f} look_deg={look_deg:.4f} cam_deg={cam_deg:.4f}",
        place=iss_place,
        drift_m=drift,
        look_deg=look_deg,
    )

    hop = getattr(solar, "_hop_off_earth_contact", None)
    if callable(hop):
        hop()
        _pump(app, 400)

    _banner("04 SINGAPORE 50 km — boats and planes. Camera must leave space.")
    if zone is not None:
        _only(zone, {"vessels", "flights"})
    sg = _place(app, solar, 1.26, 103.85, 50_000.0)
    _announce(
        solar,
        "Singapore · 50 km",
        "Ships and planes in this box. You should see the strait, not leftover ISS.",
    )
    _wait_fetch(app, "ais", seconds=22.0)
    boats = _wait_visible(app, "vessels", n=1, seconds=16.0)
    planes = _wait_visible(app, "flights", n=1, seconds=8.0)
    beat(
        "04-ocean-singapore",
        ok=bool(sg.get("landed")) and boats >= 1,
        why=f"boats={boats} planes={planes}",
        place=sg,
        boats=boats,
        planes=planes,
    )

    _banner("05 LONDON 2.4 km — cameras first, then radio/weather. Wait for pins.")
    if zone is not None:
        _only(zone, {"cameras"})
        zone.set_layer("cameras", True)
    lon = _place(app, solar, 51.508, -0.128, 2_400.0)
    _announce(
        solar,
        "London · 2.4 km",
        "This should read as a city. Photoreal refines after we land — the mosaic stays until then.",
    )
    cams_fetched = _wait_fetch(app, "cameras", seconds=40.0)
    cams = _wait_visible(app, "cameras", n=1, seconds=20.0)
    if zone is not None:
        zone.set_layer("radio", True)
        zone.set_layer("weather", True)
    _wait_fetch(app, "radio", seconds=12.0)
    radios = _wait_visible(app, "radio", n=1, seconds=8.0)
    beat(
        "05-london-city",
        ok=bool(lon.get("landed")) and cams >= 1,
        why=f"cameras_fetch={cams_fetched} cameras={cams} radio={radios}",
        place=lon,
        cameras=cams,
        radios=radios,
    )

    _banner("06 CAMERA LOOK — only a real publisher handle. No fake still.")
    _announce(
        solar,
        "Trafalgar Square camera",
        "The tile on the right is a publisher still. View / More. No fake picture.",
    )
    cam = None
    handle = None
    look_deadline = time.perf_counter() + 20.0
    while time.perf_counter() < look_deadline:
        _pump(app, 400)
        if zone is not None:
            zone.tick(unix=time.time())
            for ent in zone.visible():
                if ent.layer != "cameras":
                    continue
                handle = resolve(ent.id)
                if handle is not None:
                    cam = ent
                    break
        if handle is not None:
            break
    if cam is None and zone is not None:
        cams_list = [e for e in zone.visible() if e.layer == "cameras"]
        cam = cams_list[0] if cams_list else None
    frame = False
    status = ""
    if cam is not None:
        solar._select_earth_entity(cam, ride=False)
        _paint(solar)
        deadline = time.perf_counter() + 12.0
        while time.perf_counter() < deadline:
            _pump(app, 400)
            if getattr(solar, "_look_frame", None) is not None:
                frame = True
                from arelis.ui.earth_dock import expand_earth_look

                expand_earth_look(solar)
                _announce(
                    solar,
                    "Trafalgar Square still",
                    "This is the publisher JPEG, enlarged. This walk does not play a live stream.",
                )
                break
        status = str(getattr(solar, "_look_status", "") or "")
        print(
            f"look id={cam.id} handle={handle is not None} "
            f"status={status!r} frame={frame}",
            flush=True,
        )
    beat(
        "06-camera-look",
        ok=handle is not None and frame,
        why=(
            f"id={getattr(cam, 'id', None)} handle={handle is not None} "
            f"frame={frame} status={status!r}"
        ),
        place=lon,
        look_id=getattr(cam, "id", None),
        look_handle=handle is not None,
        look_frame=frame,
        look_status=status,
    )

    _banner("07 CALIFORNIA FIRES — park on a real pin, not an empty box.")
    _unlock(solar)
    keyed = bool(firms_key())
    fire_lat, fire_lon = 38.5, -122.5
    fire_id = ""
    if zone is not None:
        _only(zone, {"fires", "weather"})
        zone.set_layer("fires", True)
        zone.set_layer("weather", True)
    fire_place = _place(app, solar, fire_lat, fire_lon, 18_000.0)
    _wait_fetch(app, "firms", seconds=18.0)
    if zone is not None:
        zone.tick(unix=time.time())
        for ent in zone.store.all():
            if ent.layer != "fires":
                continue
            pair = entity_lla(ent)
            if pair is None:
                continue
            lat, lon_f = pair
            if 32.0 <= lat <= 42.5 and -124.5 <= lon_f <= -114.0:
                fire_lat, fire_lon = lat, lon_f
                fire_id = ent.id
                break
        if not fire_id:
            fire_id = "hole:no-california-firms"
    if fire_id.startswith("firms:") or fire_id.startswith("sim-fire:"):
        fire_place = _place(app, solar, fire_lat, fire_lon, 18_000.0)
    _announce(
        solar,
        "California fires",
        "Only a real FIRMS pin. An empty box is a named hole — we do not hop to Sweden.",
    )
    fires = _wait_visible(app, "fires", n=1, seconds=10.0)
    beat(
        "07-california-fires",
        ok=(
            bool(fire_place.get("landed"))
            and fires >= 1
            and not str(fire_id).startswith("hole:")
        ),
        why=f"firms_keyed={keyed} pin={fire_id} fires={fires}",
        place=fire_place,
        firms_keyed=keyed,
        fire_id=fire_id,
        fires=fires,
    )

    _banner("08 DC 50 km — flights, military if the feed has them, drones if any.")
    if zone is not None:
        _only(zone, {"flights", "military", "drones"})
    dc = _place(app, solar, 38.87, -77.04, 50_000.0)
    _announce(
        solar,
        "Washington · 50 km",
        "Night city lights plus live flights. Military only if the public feed has one.",
    )
    _wait_fetch(app, "opensky", seconds=24.0)
    flights = _wait_visible(app, "flights", n=1, seconds=16.0)
    military = _wait_visible(app, "military", n=1, seconds=8.0)
    drones = sum(1 for e in (zone.visible() if zone is not None else []) if e.layer == "drones")
    beat(
        "08-dc-air",
        ok=bool(dc.get("landed")) and flights >= 1,
        why=f"flights={flights} military={military} drones={drones}",
        place=dc,
        flights=flights,
        military=military,
        drones=drones,
    )

    _banner("09 NYC 4 km — city chips, refetch, do not claim cameras if empty.")
    if zone is not None:
        _only(zone, {"cameras", "radio", "weather", "traffic", "sites", "flights"})
        zone.set_layer("cameras", True)
    nyc = _place(app, solar, 40.76, -73.98, 4_000.0)
    _announce(
        solar,
        "New York · 4 km",
        "Streets are the photoreal city. Brown void plus yellow wires means it failed.",
    )
    _wait_fetch(app, "cameras", seconds=40.0)
    nyc_cams = _wait_visible(app, "cameras", n=1, seconds=24.0)
    beat(
        "09-nyc-city",
        ok=bool(nyc.get("landed")),
        why=f"cameras={nyc_cams} (zero is a hole, not a skip)",
        place=nyc,
        cameras=nyc_cams,
    )

    try:
        _write_proof_md(rows)
        proven = sum(1 for r in rows if r.get("ok"))
        print(f"\nWALK DONE  proven={proven}/{len(rows)}  see {PROOF}", flush=True)
        code = 0 if proven == len(rows) and rows else 4
    finally:
        solar.close()
        QTimer.singleShot(0, app.quit)
        app.processEvents()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
