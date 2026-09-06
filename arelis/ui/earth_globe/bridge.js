/* Arelis Earth globe. Cesium draws the planet and the starfield.
   Sodium HUD stays in Qt, pinned over this plate. */
(function () {
  "use strict";

  var viewer = null;
  var tileset = null;
  var osmLayer = null;
  var streetsOn = false;
  var roads = {};
  var lastRoadsKey = "";
  var entities = {};
  var labels = {};
  var buildings = {};
  var lastBuildingsKey = "";
  var bridge = null;
  var pushing = false;
  var lastKind = "";
  var lastStack = null;
  var lastPlacesKey = "";
  var lastEntityKey = "";
  var lastEmit = 0;
  var photorealAltM = 8000;
  var atlas = {};
  var findOpen = false;

  function finite(n, fallback) {
    n = Number(n);
    return isFinite(n) ? n : fallback;
  }

  function clampAlt(alt) {
    return Math.min(8e7, Math.max(200, finite(alt, 4e6)));
  }

  // Marks may sit on the ellipsoid. Camera still floors at 200 m.
  function clampMarkAlt(alt) {
    var n = finite(alt, 0);
    if (n < 0) n = 0;
    return Math.min(8e7, n);
  }

  function saneLla(lat, lon, alt) {
    lat = finite(lat, 0);
    lon = finite(lon, 0);
    if (Math.abs(lat) > 90 || Math.abs(lon) > 1e6) return null;
    return { lat: lat, lon: lon, alt: clampAlt(alt) };
  }

  function saneMarkLla(lat, lon, alt) {
    lat = finite(lat, 0);
    lon = finite(lon, 0);
    if (Math.abs(lat) > 90 || Math.abs(lon) > 1e6) return null;
    return { lat: lat, lon: lon, alt: clampMarkAlt(alt) };
  }

  function loadScript(url) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = url;
      s.onload = resolve;
      s.onerror = function () { reject(new Error("cesium")); };
      document.head.appendChild(s);
    });
  }

  function loadCss(url) {
    var l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = url;
    document.head.appendChild(l);
  }

  function ink(layer) {
    var map = {
      flights: Cesium.Color.fromCssColorString("#ff7a22"),
      drones: Cesium.Color.fromCssColorString("#ff5e12"),
      military: Cesium.Color.fromCssColorString("#ff5e12"),
      vessels: Cesium.Color.fromCssColorString("#ffc08a"),
      satellites: Cesium.Color.fromCssColorString("#d8a482"),
      iss: Cesium.Color.fromCssColorString("#fae8dc"),
      cameras: Cesium.Color.fromCssColorString("#ff7a22"),
      quakes: Cesium.Color.fromCssColorString("#ff5e12"),
      fires: Cesium.Color.fromCssColorString("#ff5e12"),
      weather: Cesium.Color.fromCssColorString("#ffc08a"),
      radio: Cesium.Color.fromCssColorString("#fae8dc"),
      traffic: Cesium.Color.fromCssColorString("#d8a482"),
      sites: Cesium.Color.fromCssColorString("#d8a482"),
      radar: Cesium.Color.fromCssColorString("#d8a482")
    };
    return map[layer] || Cesium.Color.fromCssColorString("#ff7a22");
  }

  function sunNow() {
    viewer.clock.currentTime = Cesium.JulianDate.now();
    viewer.clock.shouldAnimate = false;
    dressLighting(currentAlt());
  }

  function dressLighting(alt) {
    if (!viewer) return;
    var globe = viewer.scene.globe;
    globe.enableLighting = true;
    if (globe.nightFadeOutDistance !== undefined) {
      globe.nightFadeOutDistance = 5.0e5;
      globe.nightFadeInDistance = 2.5e6;
    } else if (finite(alt, 1e7) <= 400000) {
      globe.enableLighting = false;
    }
  }

  function dressSpace() {
    /* Qt stars die when solar GL parks. Opaque Cesium skybox — not a hole. */
    if (viewer.scene.skyBox) viewer.scene.skyBox.show = true;
    if (viewer.scene.sun) viewer.scene.sun.show = false;
    if (viewer.scene.moon) viewer.scene.moon.show = false;
    viewer.scene.skyAtmosphere.show = true;
    viewer.scene.fog.enabled = false;
    viewer.scene.backgroundColor = Cesium.Color.fromCssColorString("#040508");
    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#0b1c2c");
    if (viewer.scene.globe.translucency) {
      viewer.scene.globe.translucency.enabled = false;
    }
    dressControls();
  }

  function dressControls() {
    if (!viewer) return;
    var c = viewer.scene.screenSpaceCameraController;
    c.enableRotate = true;
    c.enableLook = true;
    c.enableTilt = true;
    c.enableTranslate = true;
    c.enableZoom = true;
    c.inertiaSpin = 0;
    c.inertiaTranslate = 0.3;
    c.inertiaZoom = 0.3;
  }

  function applyNudge(payload) {
    if (!viewer || !payload) return;
    var fwd = finite(payload.fwd, 0);
    var right = finite(payload.right, 0);
    var up = finite(payload.up, 0);
    var mag = Math.abs(fwd) + Math.abs(right) + Math.abs(up);
    if (!mag) return;
    if (mag > 2e6) {
      var s = 2e6 / mag;
      fwd *= s;
      right *= s;
      up *= s;
    }
    var move = new Cesium.Cartesian3();
    Cesium.Cartesian3.multiplyByScalar(viewer.camera.direction, fwd, move);
    var step = new Cesium.Cartesian3();
    Cesium.Cartesian3.multiplyByScalar(viewer.camera.right, right, step);
    Cesium.Cartesian3.add(move, step, move);
    Cesium.Cartesian3.multiplyByScalar(viewer.camera.up, up, step);
    Cesium.Cartesian3.add(move, step, move);
    viewer.camera.move(move);
    viewer.scene.requestRender();
  }

  function qtKey(ev) {
    if (ev.key === "Enter") return ev.location === 3 ? 16777221 : 16777220;
    if (ev.key === "Backspace") return 16777219;
    if (ev.key === "Escape") return 16777216;
    if (ev.key === "ArrowUp") return 16777235;
    if (ev.key === "ArrowDown") return 16777237;
    if (ev.key === "ArrowLeft") return 16777234;
    if (ev.key === "ArrowRight") return 16777236;
    if (ev.key === " ") return 32;
    if (ev.key === "/") return 47;
    if (ev.key && ev.key.length === 1) {
      var code = ev.key.charCodeAt(0);
      if (code >= 97 && code <= 122) return code - 32;
      return code;
    }
    return 0;
  }

  function jsMod(ev) {
    var mod = 0;
    if (ev.shiftKey) mod |= 0x02000000;
    if (ev.ctrlKey) mod |= 0x04000000;
    if (ev.altKey) mod |= 0x08000000;
    if (ev.metaKey) mod |= 0x10000000;
    return mod;
  }

  function shouldHose(ev) {
    if (findOpen) {
      return ev.key === "Enter" || ev.key === "Backspace" || ev.key === "Escape"
        || ev.key === "ArrowUp" || ev.key === "ArrowDown"
        || ev.key === " " || (ev.key && ev.key.length === 1);
    }
    var code = ev.code || "";
    return ev.key === "/" || ev.key === "Enter"
      || ev.key === "ArrowUp" || ev.key === "ArrowDown"
      || ev.key === "ArrowLeft" || ev.key === "ArrowRight"
      || code === "KeyW" || code === "KeyA" || code === "KeyS" || code === "KeyD"
      || code === "KeyQ" || code === "KeyE";
  }

  function hoseKey(ev, down) {
    if (!bridge || !bridge.keyStruck || !shouldHose(ev)) return false;
    ev.preventDefault();
    ev.stopPropagation();
    bridge.keyStruck(JSON.stringify({
      down: !!down,
      key: qtKey(ev),
      mod: jsMod(ev),
      text: ev.key && ev.key.length === 1 ? ev.key : "",
      auto: !!ev.repeat
    }));
    return true;
  }

  function updateCredits() {
    var credit = document.getElementById("credit");
    if (!credit) return;
    var bits = ["NASA GIBS Blue Marble", "© OpenStreetMap"];
    if (tileset) bits = ["Google", "Cesium"].concat(bits);
    else if (lastKind === "ion") bits = ["Cesium ion"].concat(bits);
    credit.textContent = bits.join(" · ");
  }

  function currentAlt() {
    if (!viewer) return 1e7;
    var carto = viewer.camera.positionCartographic;
    return carto ? carto.height : 1e7;
  }

  function wantPhotoreal(alt) {
    return lastKind === "photoreal" && lastStack && lastStack.googleKey && alt < photorealAltM;
  }

  function syncPhotoreal(alt) {
    if (!viewer || !lastStack) return;
    if (!wantPhotoreal(alt)) {
      if (tileset) {
        viewer.scene.primitives.remove(tileset);
        tileset = null;
        updateCredits();
        viewer.scene.requestRender();
      }
      return;
    }
    if (tileset) return;
    var url = lastStack.google3d + "?key=" + encodeURIComponent(lastStack.googleKey);
    Cesium.Cesium3DTileset.fromUrl(url).then(function (set) {
      if (!wantPhotoreal(currentAlt())) {
        return;
      }
      if (tileset) viewer.scene.primitives.remove(tileset);
      tileset = set;
      viewer.scene.primitives.add(set);
      updateCredits();
      if (bridge) bridge.tilesReady(lastKind);
      viewer.scene.requestRender();
    }).catch(function () {
      tileset = null;
      updateCredits();
    });
  }

  function applyStack(stack) {
    lastStack = stack;
    lastKind = stack.kind || "gibs";
    photorealAltM = Number(stack.photorealAltM || 8000);
    if (stack.ionToken) {
      Cesium.Ion.defaultAccessToken = stack.ionToken;
    }
    viewer.imageryLayers.removeAll();
    osmLayer = null;
    viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
      url: stack.gibs,
      maximumLevel: 8,
      credit: "NASA GIBS"
    }));
    if (stack.kind === "ion" && stack.ionToken) {
      viewer.terrainProvider = Cesium.CesiumTerrainProvider.fromIonAssetId(1);
    } else {
      viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
    }
    updateCredits();
    sunNow();
    dressSpace();
    syncPhotoreal(currentAlt());
    viewer.scene.requestRender();
  }

  function clearBuildings() {
    Object.keys(buildings).forEach(function (id) {
      viewer.entities.remove(buildings[id]);
      delete buildings[id];
    });
  }

  function setBuildings(rings) {
    if (!viewer) return;
    var list = rings || [];
    var key = list.length + ":" + (list[0] ? list[0].length : 0) + ":" +
      (list[0] && list[0][0] ? list[0][0].join(",") : "");
    if (key === lastBuildingsKey) return;
    lastBuildingsKey = key;
    clearBuildings();
    var ink = Cesium.Color.fromCssColorString("#d8a482").withAlpha(0.85);
    list.forEach(function (ring, i) {
      if (!ring || ring.length < 3) return;
      var flat = [];
      ring.forEach(function (pt) {
        if (!pt || pt.length < 2) return;
        var lon = finite(pt[1], NaN);
        var lat = finite(pt[0], NaN);
        if (!isFinite(lon) || !isFinite(lat)) return;
        if (Math.abs(lat) > 90) return;
        flat.push(lon, lat);
      });
      if (flat.length < 6) return;
      if (flat[0] !== flat[flat.length - 2] || flat[1] !== flat[flat.length - 1]) {
        flat.push(flat[0], flat[1]);
      }
      var id = "bldg:" + i;
      buildings[id] = viewer.entities.add({
        id: id,
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArray(flat),
          width: 1.5,
          material: ink,
          clampToGround: true
        }
      });
    });
    viewer.scene.requestRender();
  }

  function setStreets(on) {
    streetsOn = !!on;
    if (!on) {
      clearRoads();
      lastRoadsKey = "";
    }
    if (osmLayer) {
      viewer.imageryLayers.remove(osmLayer);
      osmLayer = null;
    }
    syncPhotoreal(currentAlt());
    viewer.scene.requestRender();
  }

  function clearRoads() {
    Object.keys(roads).forEach(function (id) {
      viewer.entities.remove(roads[id]);
      delete roads[id];
    });
    lastRoadsKey = "";
  }

  function roadWidth(kind) {
    if (kind === "motorway" || kind === "trunk") return 3.6;
    if (kind === "primary") return 2.6;
    if (kind === "secondary") return 2.0;
    return 1.3;
  }

  function roadsKey(list) {
    var names = [];
    for (var i = 0; i < list.length; i++) {
      var row = list[i];
      if (!row) continue;
      names.push((row.name || "") + ":" + (row.kind || "") + ":" +
        (row.pts ? row.pts.length : 0));
    }
    return list.length + ":" + names.join("|");
  }

  function setRoads(rows) {
    if (!viewer) return;
    var list = rows || [];
    if (!list.length) {
      if (!streetsOn) {
        clearRoads();
        lastRoadsKey = "";
      }
      return;
    }
    var key = roadsKey(list);
    if (key === lastRoadsKey) return;
    lastRoadsKey = key;
    clearRoads();
    lastRoadsKey = key;
    var ink = Cesium.Color.fromCssColorString("#f2e2b8").withAlpha(0.92);
    list.forEach(function (row, i) {
      if (!row || !row.pts || row.pts.length < 2) return;
      var flat = [];
      row.pts.forEach(function (pt) {
        if (!pt || pt.length < 2) return;
        var lon = finite(pt[1], NaN);
        var lat = finite(pt[0], NaN);
        if (!isFinite(lon) || !isFinite(lat) || Math.abs(lat) > 90) return;
        flat.push(lon, lat);
      });
      if (flat.length < 4) return;
      var id = "road:" + i;
      var mid = Math.floor(row.pts.length / 2);
      var named = row.name && (row.kind === "motorway" || row.kind === "trunk" ||
        row.kind === "primary" || row.kind === "secondary");
      var ent = {
        id: id,
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArray(flat),
          width: roadWidth(row.kind),
          material: ink,
          clampToGround: true,
          distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 12000.0)
        }
      };
      if (named && row.pts[mid]) {
        ent.position = Cesium.Cartesian3.fromDegrees(
          finite(row.pts[mid][1], 0),
          finite(row.pts[mid][0], 0)
        );
        ent.label = {
          text: String(row.name),
          font: "13px sans-serif",
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          pixelOffset: new Cesium.Cartesian2(0, -6),
          distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 8000.0)
        };
      }
      roads[id] = viewer.entities.add(ent);
    });
    viewer.scene.requestRender();
  }

  function setCamera(payload) {
    if (!viewer || !payload) return;
    var pose = saneLla(payload.lat, payload.lon, payload.alt_m);
    if (!pose) return;
    var soft = !!payload.soft;
    var carto = viewer.camera.positionCartographic;
    if (carto) {
      var dlat = Math.abs(Cesium.Math.toDegrees(carto.latitude) - pose.lat);
      var dlon = Math.abs(Cesium.Math.toDegrees(carto.longitude) - pose.lon);
      var dalt = Math.abs(carto.height - pose.alt);
      if (dlat < 1e-4 && dlon < 1e-4 && dalt < 80) return;
    }
    if (!soft) pushing = true;
    var dest = Cesium.Cartesian3.fromDegrees(pose.lon, pose.lat, pose.alt);
    var heading = finite(payload.heading, 0);
    var pitch = payload.pitch == null ? -90 : finite(payload.pitch, -90);
    viewer.camera.setView({
      destination: dest,
      orientation: {
        heading: Cesium.Math.toRadians(heading),
        pitch: Cesium.Math.toRadians(pitch),
        roll: 0
      }
    });
    viewer.scene.fog.enabled = pose.alt < 400000;
    dressLighting(pose.alt);
    syncPhotoreal(pose.alt);
    viewer.scene.requestRender();
    if (soft) {
      lastEmit = 0;
      emitCamera();
      return;
    }
    setTimeout(function () {
      pushing = false;
      lastEmit = 0;
      emitCamera();
    }, 40);
  }

  function applyLook(payload) {
    if (!viewer || !payload) return;
    var yaw = finite(payload.yaw, 0);
    var pitch = finite(payload.pitch, 0);
    if (!yaw && !pitch) return;
    viewer.camera.lookRight(yaw);
    viewer.camera.lookUp(pitch);
    viewer.scene.requestRender();
  }

  function lookTarget(payload) {
    if (!viewer || !payload) return;
    var pose = saneMarkLla(payload.lat, payload.lon, payload.alt_m || 0);
    if (!pose) return;
    var target = Cesium.Cartesian3.fromDegrees(pose.lon, pose.lat, pose.alt);
    var from = viewer.camera.positionWC;
    var dir = Cesium.Cartesian3.subtract(target, from, new Cesium.Cartesian3());
    if (Cesium.Cartesian3.magnitude(dir) < 1) return;
    Cesium.Cartesian3.normalize(dir, dir);
    var up = new Cesium.Cartesian3();
    Cesium.Cartesian3.normalize(from, up);
    var right = Cesium.Cartesian3.cross(dir, up, new Cesium.Cartesian3());
    if (Cesium.Cartesian3.magnitude(right) < 1e-6) {
      up = viewer.camera.up;
    }
    viewer.camera.setView({
      destination: from,
      orientation: { direction: dir, up: up }
    });
    viewer.scene.requestRender();
    lastEmit = 0;
    emitCamera();
  }

  function orbitalDepth(row) {
    var alt = finite(row && row.alt_m, 0);
    if ((row.layer === "satellites" || row.layer === "iss") && alt > 10000) {
      return 0;
    }
    return Number.POSITIVE_INFINITY;
  }

  function flySeconds(fromAlt, toAlt, dlat, dlon) {
    var deg = Math.hypot(finite(dlat, 0), finite(dlon, 0));
    var km = Math.abs(finite(fromAlt, 0) - finite(toAlt, 0)) / 1000 + deg * 111;
    return Math.min(9.0, Math.max(2.2, Math.log10(km + 25) * 2.15));
  }

  var HEADING = {flights: 1, military: 1, drones: 1, vessels: 1};

  function markSize(row) {
    if (row.layer === "iss") return row.band === "space" ? 56 : 40;
    if (row.layer === "satellites") return row.band === "space" ? 40 : 28;
    if (row.band === "space") return 32;
    if (row.band === "approach") return 26;
    if (row.band === "near") return 22;
    return 24;
  }

  function markImage(row) {
    var mark = row.mark || row.layer;
    var band = row.band || "city";
    return atlas[mark + ":" + band] || atlas[mark] || "";
  }

  function wantLabel(row) {
    if (!row || !row.label) return false;
    if (row.hot || row.layer === "iss") return true;
    if (row.layer === "satellites") return row.band !== "space";
    return row.band === "city";
  }

  function lookHit(pt) {
    if (!viewer) return undefined;
    var ray = viewer.camera.getPickRay(pt);
    var cart = ray ? viewer.scene.globe.pick(ray, viewer.scene) : undefined;
    if (!Cesium.defined(cart)) {
      cart = viewer.camera.pickEllipsoid(pt, viewer.scene.globe.ellipsoid);
    }
    return cart;
  }

  function canvasMid() {
    var canvas = viewer.scene.canvas;
    var w = canvas.clientWidth || canvas.width || 1;
    var h = canvas.clientHeight || canvas.height || 1;
    return new Cesium.Cartesian2(w * 0.5, h * 0.5);
  }

  function metersPerPixel() {
    if (!viewer) return 0;
    var mid = canvasMid();
    var right = new Cesium.Cartesian2(mid.x + 8, mid.y);
    var a = lookHit(mid);
    var b = lookHit(right);
    if (!Cesium.defined(a) || !Cesium.defined(b)) return 0;
    var step = Cesium.Cartesian3.distance(a, b) / 8.0;
    return isFinite(step) ? step : 0;
  }

  function lookRange() {
    if (!viewer) return 0;
    var cart = lookHit(canvasMid());
    if (!Cesium.defined(cart)) return 0;
    var step = Cesium.Cartesian3.distance(viewer.camera.positionWC, cart);
    return isFinite(step) ? step : 0;
  }

  function rangeLabel(meters) {
    var m = Number(meters) || 0;
    if (m >= 1000) {
      var km = m / 1000;
      return (km >= 10 ? Math.round(km) : Math.round(km * 10) / 10) + " km";
    }
    return Math.round(m) + " m";
  }

  var groundPin = null;

  function setGroundPin(lat, lon, slant) {
    if (!viewer) return;
    var pos = Cesium.Cartesian3.fromDegrees(lon, lat, 0);
    var text = rangeLabel(slant) + " to pin";
    if (!groundPin) {
      groundPin = viewer.entities.add({
        id: "arelis:ground-pin",
        position: pos,
        point: {
          pixelSize: 16,
          color: Cesium.Color.fromCssColorString("#fae8dc"),
          outlineColor: Cesium.Color.fromCssColorString("#160d07"),
          outlineWidth: 2,
          disableDepthTestDistance: Number.POSITIVE_INFINITY
        },
        label: {
          text: text,
          font: "15px sans-serif",
          fillColor: Cesium.Color.fromCssColorString("#fae8dc"),
          outlineColor: Cesium.Color.fromCssColorString("#160d07"),
          outlineWidth: 4,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cesium.Cartesian2(10, -14),
          disableDepthTestDistance: Number.POSITIVE_INFINITY
        }
      });
    } else {
      groundPin.position = pos;
      if (groundPin.label) groundPin.label.text = text;
    }
    viewer.scene.requestRender();
  }

  function headingRad(row) {
    var deg = row.heading_deg;
    if (deg == null || deg === "") return 0;
    return Cesium.Math.toRadians(Number(deg) || 0);
  }

  function setMarks(map) {
    atlas = map || {};
    lastEntityKey = "";
  }

  function dressBillboard(ent, row) {
    var img = markImage(row);
    var px = markSize(row);
    if (!ent.billboard) return;
    if (img) ent.billboard.image = img;
    ent.billboard.width = px;
    ent.billboard.height = px;
    ent.billboard.sizeInMeters = false;
    if (HEADING[row.layer]) {
      ent.billboard.rotation = headingRad(row);
      ent.billboard.alignedAxis = Cesium.Cartesian3.UNIT_Z;
    } else {
      ent.billboard.rotation = 0;
      ent.billboard.alignedAxis = Cesium.Cartesian3.ZERO;
    }
    ent.billboard.color = Cesium.Color.WHITE;
    if (row.freshness === "stale") {
      ent.billboard.color = Cesium.Color.WHITE.withAlpha(0.45);
    } else     if (row.freshness === "dead-reckoned") {
      ent.billboard.color = Cesium.Color.WHITE.withAlpha(0.7);
    }
    ent.billboard.disableDepthTestDistance = orbitalDepth(row);
  }

  function upsert(rows) {
    if (!viewer || !rows) return;
    var key = rows.map(function (row) {
      return row.id + ":" + Math.round(row.lat * 100) + ":" + Math.round(row.lon * 100)
        + ":" + Math.round(row.alt_m || 0)
        + ":" + (row.mark || row.layer) + ":" + (row.heading_deg || 0)
        + ":" + (row.freshness || "") + ":" + (row.band || "");
    }).join("|");
    if (key === lastEntityKey) return;
    lastEntityKey = key;
    var keep = {};
    rows.forEach(function (row) {
      if (!row || !row.id) return;
      var pose = saneMarkLla(row.lat, row.lon, row.alt_m || 0);
      if (!pose) return;
      keep[row.id] = true;
      var pos = Cesium.Cartesian3.fromDegrees(pose.lon, pose.lat, pose.alt);
      var ent = entities[row.id];
      if (!ent) {
        ent = viewer.entities.add({
          id: row.id,
          position: pos,
          billboard: {
            image: markImage(row),
            width: markSize(row),
            height: markSize(row),
            sizeInMeters: false,
            rotation: HEADING[row.layer] ? headingRad(row) : 0,
            alignedAxis: HEADING[row.layer]
              ? Cesium.Cartesian3.UNIT_Z
              : Cesium.Cartesian3.ZERO,
            color: Cesium.Color.WHITE,
            disableDepthTestDistance: orbitalDepth(row)
          },
          label: {
            text: row.label || "",
            font: row.layer === "iss" ? "16px sans-serif" : "13px sans-serif",
            fillColor: Cesium.Color.fromCssColorString("#fae8dc"),
            outlineColor: Cesium.Color.fromCssColorString("#160d07"),
            outlineWidth: 4,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            pixelOffset: new Cesium.Cartesian2(12, -12),
            show: wantLabel(row),
            disableDepthTestDistance: Number.POSITIVE_INFINITY
          }
        });
        entities[row.id] = ent;
      } else {
        ent.position = pos;
        dressBillboard(ent, row);
        if (ent.label) {
          ent.label.text = row.label || "";
          ent.label.show = wantLabel(row);
        }
      }
      var oid = row.id + ":mark-overlay";
      var oimg = "";
      if (row.freshness === "stale") oimg = atlas.stale || "";
      if (row.freshness === "dead-reckoned") oimg = atlas["dead-reckon"] || "";
      keep[oid] = true;
      var over = entities[oid];
      if (oimg) {
        if (!over) {
          over = viewer.entities.add({
            id: oid,
            position: pos,
            billboard: {
              image: oimg,
              width: markSize(row) + 4,
              height: markSize(row) + 4,
              rotation: HEADING[row.layer] ? headingRad(row) : 0,
              alignedAxis: HEADING[row.layer]
                ? Cesium.Cartesian3.UNIT_Z
                : Cesium.Cartesian3.ZERO,
              disableDepthTestDistance: Number.POSITIVE_INFINITY
            }
          });
          entities[oid] = over;
        } else {
          over.position = pos;
          if (over.billboard) {
            over.billboard.image = oimg;
            over.billboard.rotation = HEADING[row.layer] ? headingRad(row) : 0;
            over.billboard.alignedAxis = HEADING[row.layer]
              ? Cesium.Cartesian3.UNIT_Z
              : Cesium.Cartesian3.ZERO;
          }
        }
      } else if (over) {
        viewer.entities.remove(over);
        delete entities[oid];
        keep[oid] = false;
      }
    });
    Object.keys(entities).forEach(function (id) {
      if (!keep[id]) {
        viewer.entities.remove(entities[id]);
        delete entities[id];
      }
    });
    viewer.scene.requestRender();
  }

  function setPlaces(rows) {
    if (!viewer) return;
    var key = (rows || []).map(function (row) { return row.name; }).join("|");
    if (key === lastPlacesKey) return;
    lastPlacesKey = key;
    Object.keys(labels).forEach(function (id) {
      viewer.entities.remove(labels[id]);
      delete labels[id];
    });
    (rows || []).forEach(function (row, i) {
      var id = "place:" + i + ":" + row.name;
      labels[id] = viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(row.lon, row.lat, 0),
        label: {
          text: row.name,
          font: "12px sans-serif",
          fillColor: Cesium.Color.fromCssColorString("#d8a482"),
          outlineColor: Cesium.Color.fromCssColorString("#160d07"),
          outlineWidth: 2,
          pixelOffset: new Cesium.Cartesian2(6, -4),
          disableDepthTestDistance: Number.POSITIVE_INFINITY
        }
      });
    });
    viewer.scene.requestRender();
  }

  function flyTo(payload) {
    if (!viewer || !payload) return;
    var pose = saneLla(payload.lat, payload.lon, payload.alt_m || 8e3);
    if (!pose) return;
    var cam = viewer.camera.positionCartographic;
    var fromAlt = cam ? cam.height : pose.alt;
    var dlat = cam ? Cesium.Math.toDegrees(cam.latitude) - pose.lat : 0;
    var dlon = cam ? Cesium.Math.toDegrees(cam.longitude) - pose.lon : 0;
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(pose.lon, pose.lat, pose.alt),
      orientation: {
        heading: 0,
        pitch: Cesium.Math.toRadians(-90),
        roll: 0
      },
      duration: flySeconds(fromAlt, pose.alt, dlat, dlon),
      easingFunction: Cesium.EasingFunction.QUADRATIC_IN_OUT
    });
  }

  function recoverRender() {
    if (!viewer) return;
    try {
      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(0, 20, 2.0e7),
        orientation: {
          heading: 0,
          pitch: Cesium.Math.toRadians(-90),
          roll: 0
        }
      });
      viewer.scene.requestRender();
    } catch (err) {}
  }

  function emitCamera() {
    if (!viewer || pushing || !bridge) return;
    var now = Date.now();
    if (now - lastEmit < 120) return;
    lastEmit = now;
    var carto = viewer.camera.positionCartographic;
    if (!carto) return;
    var alt = carto.height;
    viewer.scene.fog.enabled = alt < 400000;
    dressLighting(alt);
    syncPhotoreal(alt);
    bridge.cameraMoved(JSON.stringify({
      lat: Cesium.Math.toDegrees(carto.latitude),
      lon: Cesium.Math.toDegrees(carto.longitude),
      alt_m: alt,
      heading: Cesium.Math.toDegrees(viewer.camera.heading),
      pitch: Cesium.Math.toDegrees(viewer.camera.pitch),
      mpp: metersPerPixel(),
      nadir_m: lookRange()
    }));
  }

  function makeViewer(alpha) {
    var opts = {
      animation: false,
      timeline: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      baseLayerPicker: false,
      navigationHelpButton: false,
      fullscreenButton: false,
      vrButton: false,
      infoBox: false,
      selectionIndicator: false,
      baseLayer: false,
      creditContainer: document.createElement("div"),
      requestRenderMode: true,
      maximumRenderTimeChange: Infinity,
      terrainProvider: new Cesium.EllipsoidTerrainProvider()
    };
    if (alpha) {
      opts.contextOptions = { webgl: { alpha: true } };
    }
    return new Cesium.Viewer("globe", opts);
  }

  function boot(stack) {
    var base = stack.cesiumBase || String(stack.cesiumJs || "").replace(/Cesium\.js(\?.*)?$/, "");
    if (base) window.CESIUM_BASE_URL = base;
    loadCss(stack.cesiumCss);
    return loadScript(stack.cesiumJs).then(function () {
      viewer = makeViewer(false);
      dressSpace();
      if (viewer.cesiumWidget) {
        viewer.cesiumWidget.showErrorPanel = function (title, message, error) {
          console.error("cesium render", title, message, error);
          recoverRender();
        };
      }
      viewer.scene.renderError.addEventListener(function () {
        recoverRender();
      });
      window.addEventListener("keydown", function (ev) {
        hoseKey(ev, true);
      }, true);
      window.addEventListener("keyup", function (ev) {
        hoseKey(ev, false);
      }, true);
      viewer.screenSpaceEventHandler.setInputAction(function (click) {
        var picked = viewer.scene.pick(click.position);
        if (Cesium.defined(picked) && picked.id && picked.id.id && bridge) {
          var id = String(picked.id.id);
          if (id !== "arelis:ground-pin"
              && id.indexOf("place:") !== 0 && id.indexOf("bldg:") !== 0
              && id.indexOf("road:") !== 0 && id.indexOf(":mark-overlay") < 0) {
            bridge.picked(id);
            return;
          }
        }
        if (!bridge || !bridge.groundPicked) return;
        var ray = viewer.camera.getPickRay(click.position);
        var cart = ray ? viewer.scene.globe.pick(ray, viewer.scene) : undefined;
        if (!Cesium.defined(cart)) {
          cart = viewer.camera.pickEllipsoid(
            click.position,
            viewer.scene.globe.ellipsoid
          );
        }
        if (!Cesium.defined(cart)) return;
        var carto = Cesium.Cartographic.fromCartesian(cart);
        var cam = viewer.camera.positionCartographic;
        var slant = Cesium.Cartesian3.distance(viewer.camera.positionWC, cart);
        setGroundPin(
          Cesium.Math.toDegrees(carto.latitude),
          Cesium.Math.toDegrees(carto.longitude),
          slant
        );
        bridge.groundPicked(JSON.stringify({
          lat: Cesium.Math.toDegrees(carto.latitude),
          lon: Cesium.Math.toDegrees(carto.longitude),
          slant_m: slant,
          agl_m: cam ? cam.height : 0
        }));
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
      viewer.camera.changed.addEventListener(emitCamera);
      applyStack(stack);
      if (bridge) bridge.ready(lastKind || stack.kind);
      lastEmit = 0;
      emitCamera();
    });
  }

  function attach(obj) {
    bridge = obj;
    obj.start.connect(function (raw) {
      var stack = JSON.parse(raw);
      boot(stack).catch(function (err) {
        var msg = (err && err.message) ? err.message : String(err);
        console.error("cesium boot: " + msg);
        if (bridge) bridge.failed("cesium");
      });
    });
    obj.setCameraJson.connect(function (raw) {
      setCamera(JSON.parse(raw));
    });
    if (obj.nudgeJson) {
      obj.nudgeJson.connect(function (raw) {
        applyNudge(JSON.parse(raw));
      });
    }
    if (obj.lookJson) {
      obj.lookJson.connect(function (raw) {
        applyLook(JSON.parse(raw));
      });
    }
    if (obj.aimJson) {
      obj.aimJson.connect(function (raw) {
        lookTarget(JSON.parse(raw));
      });
    }
    obj.upsertJson.connect(function (raw) {
      upsert(JSON.parse(raw));
    });
    obj.placesJson.connect(function (raw) {
      setPlaces(JSON.parse(raw));
    });
    obj.flyJson.connect(function (raw) {
      flyTo(JSON.parse(raw));
    });
    obj.stackJson.connect(function (raw) {
      if (viewer) applyStack(JSON.parse(raw));
    });
    obj.showStreets.connect(function (on) {
      setStreets(!!on);
    });
    obj.buildingsJson.connect(function (raw) {
      setBuildings(JSON.parse(raw));
    });
    if (obj.roadsJson) {
      obj.roadsJson.connect(function (raw) {
        setRoads(JSON.parse(raw));
      });
    }
    if (obj.marksJson) {
      obj.marksJson.connect(function (raw) {
        setMarks(JSON.parse(raw));
      });
    }
    if (obj.findOpen) {
      obj.findOpen.connect(function (on) { findOpen = !!on; });
    }
    obj.hello();
  }

  if (typeof qt !== "undefined" && qt.webChannelTransport) {
    new QWebChannel(qt.webChannelTransport, function (channel) {
      attach(channel.objects.bridge);
    });
  }
})();
