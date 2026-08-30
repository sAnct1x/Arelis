"""Drive the Earth zone from Reality. Not a second product.

Enter/leave reparents knowledge, not the whole UI. Entities are ECEF.
The plate still paints ECLIPJ2000. dump writes a cited JSONL under
outputs/physics/earth. Simulated layers stay labeled simulated. Live
public and keyed feeds are opt-in (action=live). Logging into a camera
you do not own is not a layer.
"""

from __future__ import annotations

from typing import Any

from arelis.earth.dump import dump_state
from arelis.earth.runtime import require_earth, stage_ok
from arelis.tools.base import ToolResult

WRITE_ACTIONS: frozenset[str] = frozenset()


class EarthTool:
    name = "earth"
    description = (
        "Earth zone inside Reality. "
        "enter opens an observer plate on Earth (every squawking plane, "
        "coastal ships when keyed, sats, UAV ADS-B, ISS, quakes, fires, radio, "
        "published camera pins). Individual cars are not a public feed. "
        "leave returns to solar. "
        "status reads the HUD. track/ride lock a contact id from status. "
        "layer toggles a named layer. search finds a label. dump writes a "
        "cited JSONL under outputs/physics/earth. live=on is distance-gated "
        "(space=sats, approach=local planes, near=boats+planes, city=toggled "
        "layers in the look box). City-scale pulls USGS, OpenSky "
        "(every squawk + UAV), adsb.lol military, AISStream, Digitraffic AIS, "
        "BarentsWatch if keyed, CelesTrak TLE samples, Radio Browser, published "
        "camera catalogs worldwide (TfL, Caltrans, NYC, Singapore, Finland, "
        "Hong Kong, OSM), OSM tiles when Tiles is on, Open-Meteo, FIRMS, "
        "launches, EONET, OurAirports, NWS alerts, APRS, Shodan banners, "
        "Sentinel-1 footprints, GFW SAR if keyed, national 511 catalogs, "
        "EMSC, METAR, SWPC aurora, SatNOGS, Space-Track if keyed, WAQI/OpenAQ if keyed. "
        "Owned RTSP/webcam look-from is live footage. Official publisher "
        "stills refresh on click. Stream URLs never stored. "
        "Owned face boxes stay local. Failures keep sim. "
        "VHF-deaf mid-ocean; a packet a keyed feed sent is still painted. "
        "We do not buy sat-AIS. Radar is not a hull name. Not a face index. "
        "Not logging into cameras you do not own. Closed verbs: enter Earth, "
        "leave Earth. Do not invent an ADS-B fix."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "status",
                    "enter",
                    "leave",
                    "layer",
                    "track",
                    "ride",
                    "search",
                    "dump",
                    "live",
                    "coverage",
                ],
                "description": "What to do",
            },
            "id": {"type": "string", "description": "Entity id for track/ride"},
            "layer": {"type": "string", "description": "Layer id for action=layer"},
            "on": {"type": "boolean", "description": "layer/live on or off"},
            "query": {"type": "string", "description": "search text"},
        },
        "required": ["action"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        if action == "status":
            return self._status()
        if not stage_ok() and action not in {"status"}:
            return ToolResult(
                ok=False,
                output=(
                    "The Earth zone is source-checkout only, same as the solar stage."
                ),
                data={"fail_class": "fail:stage"},
            )
        earth = require_earth()
        try:
            from arelis.physics.telemetry import emit

            emit("earth_tool", action=action)
        except Exception:
            pass
        if action == "enter":
            note = earth.enter()
            return ToolResult(
                ok=True,
                output=note + ". " + earth.status_line(),
                data={
                    "active": True,
                    "n": len(earth.store),
                    "counts": earth.store.counts(),
                    "live": earth.live,
                },
            )
        if action == "leave":
            path = None
            if earth.active:
                try:
                    path = dump_state(earth, trigger="leave")
                except OSError:
                    path = None
            note = earth.leave()
            extra = f" Dumped {path}." if path is not None else ""
            return ToolResult(
                ok=True,
                output=note + extra,
                data={"active": False, "path": str(path) if path else None},
            )
        if action == "dump":
            if not earth.active:
                return ToolResult(
                    ok=False,
                    output="Not in Earth. enter first.",
                    data={"fail_class": "fail:empty"},
                )
            try:
                folder = dump_state(earth, trigger="dump")
            except OSError as exc:
                return ToolResult(
                    ok=False, output=str(exc), data={"fail_class": "fail:io"}
                )
            return ToolResult(
                ok=True,
                output=(
                    f"Dumped {len(earth.store)} entities to {folder}. "
                    "ECEF. Simulated layers labeled simulated. No GL still."
                ),
                data={"path": str(folder), "n": len(earth.store)},
            )
        if action == "layer":
            key = str(kwargs.get("layer") or "").strip().lower()
            on = kwargs.get("on")
            val = earth.set_layer(key, on if isinstance(on, bool) else None)
            if val is None:
                return ToolResult(
                    ok=False,
                    output=f"Unknown layer {key!r}.",
                    data={"fail_class": "fail:name", "layers": list(earth.layers)},
                )
            return ToolResult(
                ok=True,
                output=f"{key}={'on' if val else 'off'}",
                data={"layer": key, "on": val},
            )
        if action == "live":
            on = kwargs.get("on")
            earth.live = bool(on) if isinstance(on, bool) else (not earth.live)
            if earth.active and earth.live:
                earth._merge_live()
            mode = "live" if earth.live else "simulated"
            return ToolResult(
                ok=True,
                output=f"Earth feeds {mode}.",
                data={"live": earth.live},
            )
        if action == "track":
            eid = str(kwargs.get("id") or "").strip()
            hit = earth.track(eid)
            if hit is None:
                return ToolResult(
                    ok=False,
                    output=f"No entity {eid!r}.",
                    data={"fail_class": "fail:empty"},
                )
            return ToolResult(
                ok=True,
                output=f"Tracking {hit.label} ({hit.id}) {hit.freshness}.",
                data={"id": hit.id, "label": hit.label, "freshness": hit.freshness},
            )
        if action == "ride":
            eid = str(kwargs.get("id") or earth.track_id or "").strip()
            hit = earth.ride(eid)
            if hit is None:
                return ToolResult(
                    ok=False,
                    output="Name a contact id from status/search.",
                    data={"fail_class": "fail:empty"},
                )
            return ToolResult(
                ok=True,
                output=f"Riding {hit.label} ({hit.id}). Solar probes stay inspect-only.",
                data={"id": hit.id, "label": hit.label},
            )
        if action == "search":
            if not earth.active:
                return ToolResult(
                    ok=False,
                    output="Not in Earth. enter first.",
                    data={"fail_class": "fail:empty"},
                )
            q = str(kwargs.get("query") or kwargs.get("id") or "").strip()
            hits = earth.search(q)
            lines = [f"{e.label}  {e.id}  {e.layer}  {e.freshness}" for e in hits]
            return ToolResult(
                ok=True,
                output="\n".join(lines) if lines else f"No match for {q!r}.",
                data={"n": len(hits), "ids": [e.id for e in hits]},
            )
        if action == "coverage":
            notes = earth.coverage_notes() if earth.active else ["Not in Earth."]
            return ToolResult(
                ok=True,
                output="\n".join(notes),
                data={"notes": notes, "active": earth.active},
            )
        return ToolResult(
            ok=False,
            output=f"Unknown action {action!r}.",
            data={"fail_class": "fail:name"},
        )

    def _status(self) -> ToolResult:
        if not stage_ok():
            return ToolResult(
                ok=True,
                output="Earth zone is source-checkout only.",
                data={"stage": False, "active": False},
            )
        earth = require_earth()
        if not earth.active:
            return ToolResult(
                ok=True,
                output="Solar. Say enter Earth, or travel to Earth.",
                data={"active": False, "stage": True},
            )
        counts = earth.store.counts()
        bits = [earth.status_line()]
        bits.append(" ".join(f"{k}={v}" for k, v in counts.items() if v))
        if earth.track_id:
            hit = earth.get(earth.track_id)
            if hit is not None:
                bits.append(f"{hit.label} {hit.cite}")
        return ToolResult(
            ok=True,
            output="\n".join(bits),
            data={
                "active": True,
                "live": earth.live,
                "counts": counts,
                "track_id": earth.track_id,
                "ride_id": earth.ride_id,
                "n": len(earth.store),
            },
        )
