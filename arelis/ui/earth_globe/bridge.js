/* Arelis Earth globe. Cesium draws the planet and the starfield.
   Sodium HUD stays in Qt, pinned over this plate. */
(function () {
  "use strict";

  var viewer = null;
  var tileset = null;
  var dayLayer = null;
  var nightLayer = null;
  var nearLayer = null;
  var lastRideDest = null;
  var photoSSETimer = 0;
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
  var EARTH_FOV_Y = 0.70;
  var coastHold = false;
  var coastWanted = false;
  var zoomHold = false;
  var goLock = false;
  var goTimer = 0;
  var flyGen = 0;
  var rideId = "";
  var pendingRide = "";
  var rideEmitForce = false;
  var coastTimer = 0;
  var atlas = {};
  var findOpen = false;
  var selectedId = "";
  var pending = {entities: null, places: null, roads: null, buildings: null, marks: null};

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

  function dressWorld(alt) {
    /* One planet. Not a day slide, then a lights slide, then near. */
    if (!viewer) return;
    dressLighting(alt);
    var wantPhoto = wantPhotoreal(alt);
    if (wantPhoto !== !!(tileset && tileset.show)) {
      syncPhotoreal(alt);
    }
  }

  function dressLighting(alt) {
    if (!viewer) return;
    var globe = viewer.scene.globe;
    alt = finite(alt, 1e7);
    // City photoreal stays unlit. Approach (50 km DC at 2am) still
    // needs the terminator. Daytime never paints city lights.
    if (alt <= 4e4) {
      globe.enableLighting = false;
      dressNightLayer(alt);
      dressNearLayer(alt);
      return;
    }
    globe.enableLighting = true;
    if (globe.nightFadeOutDistance !== undefined) {
      globe.nightFadeOutDistance = 5.0e5;
      globe.nightFadeInDistance = 2.5e6;
    }
    dressNightLayer(alt);
    dressNearLayer(alt);
  }

  function dressNearLayer(alt) {
    if (!nearLayer) return;
    nearLayer.show = finite(alt, 1e7) <= 2.5e6;
  }

  function dressNightLayer(alt) {
    var night = finite(alt, 1e7) > 4e4;
    if (nightLayer) {
      /* Night side only. dayAlpha stays 0 — daytime is not lit cities. */
      nightLayer.show = night;
      if (nightLayer.nightAlpha !== undefined) {
        nightLayer.nightAlpha = night ? 1 : 0;
        nightLayer.dayAlpha = 0;
      }
    }
    if (dayLayer && dayLayer.nightAlpha !== undefined) {
      dayLayer.dayAlpha = 1;
      dayLayer.nightAlpha = night ? 0.18 : 1;
    }
    if (nearLayer && nearLayer.nightAlpha !== undefined) {
      nearLayer.dayAlpha = 1;
      nearLayer.nightAlpha = 0;
    }
  }

  function dressGlobeLod() {
    if (!viewer || !viewer.scene || !viewer.scene.globe) return;
    var globe = viewer.scene.globe;
    globe.tileCacheSize = 1000;
    globe.preloadAncestors = true;
    globe.preloadSiblings = true;
    /* Parent tiles first. A spray of children is the frame-by-frame crawl. */
    globe.loadingDescendantLimit = goLock ? 4 : 24;
    globe.maximumScreenSpaceError = goLock ? 3 : 1.6;
  }

  function dressSpace() {
    /* Qt stars die when solar GL parks. Opaque Cesium skybox — not a hole. */
    if (viewer.scene.skyBox) viewer.scene.skyBox.show = true;
    if (viewer.scene.sun) viewer.scene.sun.show = false;
    if (viewer.scene.moon) viewer.scene.moon.show = false;
    viewer.scene.skyAtmosphere.show = true;
    viewer.scene.fog.enabled = false;
    viewer.scene.globe.depthTestAgainstTerrain = false;
    viewer.scene.backgroundColor = Cesium.Color.fromCssColorString("#040508");
    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#0c1814");
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
    c.minimumZoomDistance = 200;
  }

  function pickedMarkId(click) {
    if (!viewer || !click) return "";
    var picked = viewer.scene.pick(click.position);
    if (!Cesium.defined(picked) || !picked.id || !picked.id.id) return "";
    var id = String(picked.id.id);
    if (id === "arelis:ground-pin"
        || id.indexOf("place:") === 0 || id.indexOf("bldg:") === 0
        || id.indexOf("road:") === 0 || id.indexOf(":mark-overlay") >= 0) {
      return "";
    }
    return id;
  }

  function markCarto(entity) {
    if (!entity || !entity.position) return undefined;
    var cart = entity.position.getValue(Cesium.JulianDate.now());
    return cart ? Cesium.Cartographic.fromCartesian(cart) : undefined;
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
    return ev.key === "/" || ev.key === "Escape";
  }

  function hoseKey(ev, down) {
    if (!shouldHose(ev)) return false;
    ev.preventDefault();
    ev.stopPropagation();
    if (bridge && bridge.keyStruck) {
      bridge.keyStruck(JSON.stringify({
        down: !!down,
        key: qtKey(ev),
        mod: jsMod(ev),
        text: ev.key && ev.key.length === 1 ? ev.key : "",
        auto: !!ev.repeat
      }));
    }
    return true;
  }

  function updateCredits() {
    var credit = document.getElementById("credit");
    if (!credit) return;
    var bits = ["NASA GIBS Blue Marble", "NASA Black Marble", "© OpenStreetMap"];
    if (tileset && tileset.show) bits = ["Google", "Cesium"].concat(bits);
    else if (lastKind === "ion") bits = ["Cesium ion"].concat(bits);
    credit.textContent = bits.join(" · ");
  }

  function currentAlt() {
    if (!viewer) return 1e7;
    var carto = viewer.camera.positionCartographic;
    return carto ? carto.height : 1e7;
  }

  function wantPhotoreal(alt) {
    /* A hop stays on the finished mosaic. 3D is a city sit, not the flight. */
    if (goLock) return false;
    return lastKind === "photoreal" && lastStack && lastStack.googleKey && alt < photorealAltM;
  }

  function gibsProvider(url, maxLevel) {
    return new Cesium.UrlTemplateImageryProvider({
      url: url,
      tilingScheme: new Cesium.WebMercatorTilingScheme(),
      maximumLevel: maxLevel || 8,
      tileWidth: 256,
      tileHeight: 256,
      credit: "NASA GIBS"
    });
  }

  function ensureGlobe() {
    if (!viewer || !viewer.scene || !viewer.scene.globe) return;
    viewer.scene.globe.show = true;
    viewer.scene.globe.depthTestAgainstTerrain = false;
    viewer.scene.fog.enabled = false;
    dressGlobeLod();
    if (viewer.imageryLayers && viewer.imageryLayers.length === 0 && lastStack && lastStack.gibs) {
      applyImagery(lastStack);
    }
  }

  function applyImagery(stack) {
    if (!viewer || !stack) return;
    viewer.imageryLayers.removeAll();
    osmLayer = null;
    dayLayer = viewer.imageryLayers.addImageryProvider(gibsProvider(stack.gibs, 8));
    nearLayer = null;
    if (stack.gibsNear) {
      try {
        nearLayer = viewer.imageryLayers.addImageryProvider(
          gibsProvider(stack.gibsNear, 9)
        );
        if (nearLayer.nightAlpha !== undefined) {
          nearLayer.dayAlpha = 1;
          nearLayer.nightAlpha = 0;
        }
      } catch (err) {
        nearLayer = null;
      }
    }
    nightLayer = null;
    if (stack.gibsNight) {
      nightLayer = viewer.imageryLayers.addImageryProvider(gibsProvider(stack.gibsNight, 8));
      if (nightLayer.nightAlpha !== undefined) {
        nightLayer.dayAlpha = 0;
        nightLayer.nightAlpha = 1;
      }
    }
    dressNightLayer(currentAlt());
    dressNearLayer(currentAlt());
  }

  function tunePhotoreal(set) {
    /* Coarse mesh in the look cone first, then sharpen. Not a spray of
       street tiles across the whole frustum while you are still flying. */
    set.maximumScreenSpaceError = 28;
    set.dynamicScreenSpaceError = true;
    set.dynamicScreenSpaceErrorFactor = 24;
    set.dynamicScreenSpaceErrorDensity = 2.0e-4;
    set.foveatedScreenSpaceError = true;
    set.foveatedConeSize = 0.35;
    set.foveatedTimeDelay = 0.2;
    set.foveatedMinimumScreenSpaceErrorRelaxation = 12;
    set.preloadWhenHidden = false;
    set.cullRequestsWhileMoving = true;
    set.cullRequestsWhileMovingMultiplier = 80;
    set.skipLevelOfDetail = true;
    set.immediatelyLoadDesiredLevelOfDetail = false;
    set.loadSiblings = false;
    if (photoSSETimer) clearTimeout(photoSSETimer);
    photoSSETimer = setTimeout(function () {
      if (tileset === set && set.show) set.maximumScreenSpaceError = 16;
    }, 1800);
  }

  function parkPhotoreal() {
    if (!tileset) return;
    tileset.show = false;
    tileset.maximumScreenSpaceError = 1024;
    tileset.preloadWhenHidden = false;
  }

  function syncPhotoreal(alt) {
    if (!viewer || !lastStack) return;
    ensureGlobe();
    if (!wantPhotoreal(alt)) {
      parkPhotoreal();
      viewer.scene.globe.depthTestAgainstTerrain = false;
      updateCredits();
      viewer.scene.requestRender();
      return;
    }
    if (tileset) {
      var was = tileset.show;
      tileset.show = true;
      if (!was) tunePhotoreal(tileset);
      viewer.scene.globe.depthTestAgainstTerrain = false;
      updateCredits();
      viewer.scene.requestRender();
      return;
    }
    var url = lastStack.google3d + "?key=" + encodeURIComponent(lastStack.googleKey);
    Cesium.Cesium3DTileset.fromUrl(url).then(function (set) {
      if (!wantPhotoreal(currentAlt())) {
        parkPhotoreal();
        return;
      }
      if (tileset && tileset !== set) viewer.scene.primitives.remove(tileset);
      /* Stream tiles as they land. Waiting for tilesLoaded hid the city
         and left GIBS mush plus leftover road wires. */
      tunePhotoreal(set);
      set.show = true;
      viewer.scene.primitives.add(set);
      tileset = set;
      viewer.scene.globe.depthTestAgainstTerrain = false;
      ensureGlobe();
      updateCredits();
      if (bridge) bridge.tilesReady(lastKind);
      viewer.scene.requestRender();
    }).catch(function () {
      tileset = null;
      ensureGlobe();
      updateCredits();
      viewer.scene.requestRender();
    });
  }

  function applyStack(stack) {
    lastStack = stack;
    lastKind = stack.kind || "gibs";
    photorealAltM = Number(stack.photorealAltM || 8000);
    if (stack.ionToken) {
      Cesium.Ion.defaultAccessToken = stack.ionToken;
    }
    applyImagery(stack);
    if (stack.kind === "ion" && stack.ionToken) {
      viewer.terrainProvider = Cesium.CesiumTerrainProvider.fromIonAssetId(1);
    } else {
      viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
    }
    dressGlobeLod();
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
    if (!viewer) { pending.buildings = rings; return; }
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
          clampToGround: true,
          disableDepthTestDistance: Number.POSITIVE_INFINITY
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
    if (kind === "motorway" || kind === "trunk") return 4.4;
    if (kind === "primary") return 3.2;
    if (kind === "secondary") return 2.4;
    return 1.6;
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

  function setRoads(_rows) {
    if (!viewer) return;
    /* Photoreal already is the streets. Overpass wires on a loading
       globe are the yellow-lines-no-city lie. */
    clearRoads();
    lastRoadsKey = "";
  }

  function bumpFly() {
    flyGen += 1;
    goLock = false;
    rideId = "";
    pendingRide = "";
    lastRideDest = null;
    clearGoTimer();
  }

  function releaseCameraLock() {
    if (!viewer) return;
    bumpFly();
    try { viewer.camera.cancelFlight(); } catch (err) {}
    viewer.trackedEntity = undefined;
    viewer.selectedEntity = undefined;
    var cam = viewer.camera;
    var pos = Cesium.Cartesian3.clone(cam.positionWC);
    var dir = Cesium.Cartesian3.clone(cam.directionWC);
    var up = Cesium.Cartesian3.clone(cam.upWC);
    cam.lookAtTransform(Cesium.Matrix4.IDENTITY);
    cam.position = pos;
    cam.direction = dir;
    cam.up = up;
    cam.right = Cesium.Cartesian3.cross(dir, up, new Cesium.Cartesian3());
  }

  function sitCamera(pose, heading, pitch) {
    heading = heading == null ? 0 : heading;
    pitch = pitch == null ? -90 : pitch;
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(pose.lon, pose.lat, pose.alt),
      orientation: {
        heading: Cesium.Math.toRadians(heading),
        pitch: Cesium.Math.toRadians(pitch),
        roll: 0
      }
    });
    viewer.scene.fog.enabled = false;
    dressLighting(pose.alt);
    syncPhotoreal(pose.alt);
    ensureGlobe();
    viewer.scene.requestRender();
    lastEmit = 0;
    emitCamera(true);
  }

  function clearGoTimer() {
    if (goTimer) {
      clearTimeout(goTimer);
      goTimer = 0;
    }
  }

  function followLla(payload) {
    if (!viewer || !payload) return;
    var pose = saneLla(payload.lat, payload.lon, payload.alt_m);
    if (!pose) return;
    flyGen += 1;
    goLock = false;
    clearGoTimer();
    try { viewer.camera.cancelFlight(); } catch (err) {}
    try { viewer.trackedEntity = undefined; } catch (err) {}
    var heading = finite(payload.heading, 0);
    var pitch = payload.pitch == null ? -28 : finite(payload.pitch, -28);
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(pose.lon, pose.lat, pose.alt),
      orientation: {
        heading: Cesium.Math.toRadians(heading),
        pitch: Cesium.Math.toRadians(pitch),
        roll: 0
      }
    });
    lastEmit = 0;
    emitCamera(true);
    viewer.scene.requestRender();
  }

  function setCamera(payload) {
    if (!viewer || !payload) return;
    var pose = saneLla(payload.lat, payload.lon, payload.alt_m);
    if (!pose) return;
    var soft = !!payload.soft;
    var keepRide = !!payload.keepRide;
    var heading = finite(payload.heading, 0);
    var pitch = payload.pitch == null ? -90 : finite(payload.pitch, -90);
    if (goLock && !keepRide) return;
    if (keepRide) {
      goLock = false;
      clearGoTimer();
      try { viewer.camera.cancelFlight(); } catch (err) {}
    }
    if (!soft) {
      clearGoTimer();
      goLock = false;
      if (!keepRide) releaseCameraLock();
    } else if (!goLock || keepRide) {
      /* ride follow while no hop is in the air */
    } else {
      return;
    }
    var carto = viewer.camera.positionCartographic;
    if (carto) {
      var dlat = Math.abs(Cesium.Math.toDegrees(carto.latitude) - pose.lat);
      var dlon = Math.abs(Cesium.Math.toDegrees(carto.longitude) - pose.lon);
      var dalt = Math.abs(carto.height - pose.alt);
      var dh = Math.abs(Cesium.Math.toDegrees(viewer.camera.heading) - heading);
      var dp = Math.abs(Cesium.Math.toDegrees(viewer.camera.pitch) - pitch);
      if (dlat < 1e-4 && dlon < 1e-4 && dalt < 80 && dh < 0.25 && dp < 0.25) {
        lastEmit = 0;
        emitCamera(true);
        return;
      }
    }
    if (!soft) pushing = true;
    var dest = Cesium.Cartesian3.fromDegrees(pose.lon, pose.lat, pose.alt);
    var orient = {
      heading: Cesium.Math.toRadians(heading),
      pitch: Cesium.Math.toRadians(pitch),
      roll: 0
    };
    viewer.camera.setView({
      destination: dest,
      orientation: orient
    });
    viewer.scene.fog.enabled = false;
    dressLighting(pose.alt);
    syncPhotoreal(pose.alt);
    ensureGlobe();
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
    var layer = row && row.layer;
    if (
      layer === "flights"
      || layer === "military"
      || layer === "drones"
      || layer === "vessels"
      || layer === "iss"
      || layer === "satellites"
    ) {
      return Number.POSITIVE_INFINITY;
    }
    return 0;
  }

  function flySeconds(fromAlt, toAlt, dlat, dlon) {
    var deg = Math.hypot(finite(dlat, 0), finite(dlon, 0));
    var km = Math.abs(finite(fromAlt, 0) - finite(toAlt, 0)) / 1000 + deg * 111;
    return Math.min(4.2, Math.max(1.1, Math.log10(km + 25) * 1.55));
  }

  var HEADING = {flights: 1, military: 1, drones: 1, vessels: 1};
  var RIDE_LAYERS = {cameras: 1, flights: 1, drones: 1, military: 1, vessels: 1, iss: 1};

  function markSize(row) {
    if (row.layer === "iss") return row.hot ? 72 : 56;
    if (row.layer === "satellites") return row.band === "space" ? 44 : 32;
    if (row.band === "space") return 36;
    if (row.band === "approach") return 32;
    if (row.band === "near") return 34;
    return 36;
  }

  function markImage(row) {
    var mark = row.mark || row.layer;
    var band = row.band || "city";
    return atlas[mark + ":" + band] || atlas[mark] || "";
  }

  function cameraBand() {
    var h = 2.5e7;
    if (viewer && viewer.camera && viewer.camera.positionCartographic) {
      h = viewer.camera.positionCartographic.height;
    }
    if (h >= 2.5e6) return "space";
    if (h >= 4e5) return "approach";
    if (h >= 4e4) return "near";
    return "city";
  }

  function wantLabel(row) {
    if (!row) return false;
    if (row.layer === "radio" || row.layer === "cameras" || row.layer === "weather") {
      return false;
    }
    if (row.hot) return true;
    if (!row.label) return false;
    if (row.layer === "iss") {
      var issBand = cameraBand();
      return row.hot || issBand === "space" || issBand === "approach";
    }
    if (row.layer === "satellites") return false;
    var band = cameraBand();
    return band === "city";
  }

  function applyEarthFov() {
    if (!viewer || !viewer.camera || !viewer.camera.frustum) return;
    var fr = viewer.camera.frustum;
    if (typeof fr.fov !== "number") return;
    var w = viewer.canvas ? (viewer.canvas.clientWidth || 1) : 1;
    var h = viewer.canvas ? (viewer.canvas.clientHeight || 1) : 1;
    var aspect = w / Math.max(h, 1);
    if (aspect > 1) {
      fr.fov = 2 * Math.atan(Math.tan(EARTH_FOV_Y * 0.5) * aspect);
    } else {
      fr.fov = EARTH_FOV_Y;
    }
  }

  function moving(row) {
    if (!row || row.freshness === "stale") return false;
    var vx = finite(row.vx, 0);
    var vy = finite(row.vy, 0);
    var vz = finite(row.vz, 0);
    return (vx * vx + vy * vy + vz * vz) >= 0.25;
  }

  function farSide(row) {
    if (!viewer || !row) return false;
    var pos = coastFromRow(row);
    var cam = viewer.camera.positionWC;
    if (!pos || !cam) return false;
    var u = Cesium.Cartesian3.normalize(pos, new Cesium.Cartesian3());
    var c = Cesium.Cartesian3.normalize(cam, new Cesium.Cartesian3());
    return Cesium.Cartesian3.dot(u, c) < 0.12;
  }

  function hideFarSide() {
    Object.keys(entities).forEach(function (id) {
      var ent = entities[id];
      var row = ent && ent.arelisRow;
      if (!ent || !row) return;
      var hide = farSide(row);
      if (ent.billboard) ent.billboard.show = !hide;
      if (ent.label) ent.label.show = wantLabel(row) && !hide;
    });
  }

  function bindRide(ent) {
    if (!viewer || !ent) return;
    try {
      ent.viewFrom = new Cesium.Cartesian3(0, -140000, 70000);
      viewer.trackedEntity = ent;
    } catch (err) {}
  }

  function armRide(id) {
    rideId = String(id || "");
    lastRideDest = null;
    zoomHold = false;
    if (!viewer) return;
    try { viewer.camera.cancelFlight(); } catch (err) {}
    goLock = false;
    clearGoTimer();
    pendingRide = "";
    if (!rideId) {
      try { viewer.trackedEntity = undefined; } catch (err) {}
      holdCoast(coastWanted);
      viewer.scene.requestRender();
      return;
    }
    coastWanted = true;
    rideEmitForce = true;
    /* A leftover hop goLock froze follow. Sit is ours — coast. */
    var ent = entities[rideId];
    if (ent) {
      bindRide(ent);
      followRide(ent);
    }
    holdCoast(true);
    viewer.scene.requestRender();
  }

  function followRide(ent) {
    var row = ent && ent.arelisRow;
    if (!row) return;
    var pos = coastFromRow(row);
    var mag = Cesium.Cartesian3.magnitude(pos);
    if (mag < 1) return;
    var sit = row.layer === "iss" ? 80000 : 250;
    var n = Cesium.Cartesian3.multiplyByScalar(
      pos,
      (mag + sit) / mag,
      new Cesium.Cartesian3()
    );
    /* ISS is 7.7 km/s. 400 m skipped a 50 ms tick. */
    var step = row.layer === "iss" ? 80 : 2500;
    if (lastRideDest && Cesium.Cartesian3.distance(n, lastRideDest) < step) {
      return;
    }
    lastRideDest = Cesium.Cartesian3.clone(n);
    /* setView fires camera.changed. Mark it ours or holdZoom kills the timer. */
    pushing = true;
    viewer.camera.setView({
      destination: n,
      orientation: {
        heading: Cesium.Math.toRadians(finite(row.heading_deg, 0)),
        pitch: Cesium.Math.toRadians(row.layer === "iss" ? -28 : -12),
        roll: 0
      }
    });
    pushing = false;
    emitCamera(true);
    rideEmitForce = false;
  }

  function stepCoast() {
    if (!viewer) return;
    hideFarSide();
    if (rideId) {
      if (goLock) {
        goLock = false;
        try { viewer.camera.cancelFlight(); } catch (err) {}
      }
      var ent = entities[rideId];
      if (ent) {
        if (viewer.trackedEntity !== ent) bindRide(ent);
        if (!viewer.trackedEntity) followRide(ent);
      }
      emitCamera(true);
    }
    viewer.scene.requestRender();
  }

  function holdCoast(on) {
    if (!viewer || !viewer.scene) return;
    var next = !!on && (!zoomHold || !!rideId);
    if (next === coastHold && (!next || coastTimer)) {
      viewer.scene.requestRenderMode = false;
      return;
    }
    coastHold = next;
    viewer.scene.requestRenderMode = false;
    if (next) {
      if (!coastTimer) {
        coastTimer = setInterval(stepCoast, 50);
      }
    } else if (coastTimer) {
      clearInterval(coastTimer);
      coastTimer = 0;
    }
    viewer.scene.requestRender();
  }

  function holdZoom(on) {
    if (on && (rideId || pushing)) return;
    zoomHold = !!on;
    if (zoomHold) holdCoast(false);
    else holdCoast(coastWanted || !!rideId);
  }

  function coastFromRow(row) {
    var x = finite(row.x, 0);
    var y = finite(row.y, 0);
    var z = finite(row.z, 0);
    var vx = finite(row.vx, 0);
    var vy = finite(row.vy, 0);
    var vz = finite(row.vz, 0);
    var when = finite(row.when_unix, 0);
    var lat = finite(row.lat, 0);
    var lon = finite(row.lon, 0);
    var alt = clampMarkAlt(row.alt_m || 0);
    if (!moving(row) || when <= 0 || (Math.abs(x) + Math.abs(y) + Math.abs(z) <= 1)) {
      return Cesium.Cartesian3.fromDegrees(lon, lat, alt);
    }
    var dt = (Date.now() / 1000) - when;
    if (dt < 0) dt = 0;
    var cap = (row.layer === "iss" || row.layer === "satellites") ? 90 : 8;
    if (dt > cap) dt = cap;
    return new Cesium.Cartesian3(x + vx * dt, y + vy * dt, z + vz * dt);
  }

  function coastPosition(ent) {
    return new Cesium.CallbackProperty(function () {
      return coastFromRow(ent.arelisRow || {});
    }, false);
  }

  function selectedWindowPos() {
    if (!viewer || !selectedId) return null;
    var ent = entities[selectedId];
    var carto = markCarto(ent);
    if (!carto) return null;
    var cart = Cesium.Cartesian3.fromRadians(
      carto.longitude, carto.latitude, carto.height || 0
    );
    var win = Cesium.SceneTransforms.wgs84ToWindowCoordinates(viewer.scene, cart);
    if (!win || !isFinite(win.x) || !isFinite(win.y)) return null;
    return { id: selectedId, x: win.x, y: win.y };
  }

  function labelDepth(row) {
    if (row.layer === "satellites" || row.layer === "iss") {
      return orbitalDepth(row);
    }
    return 0;
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
    // Atlas nose is up (north). Cesium rotation is CCW; aviation is CW.
    return Cesium.Math.toRadians(-(Number(deg) || 0));
  }

  function setMarks(map) {
    atlas = map || {};
    lastEntityKey = "";
  }

  function flushPending() {
    if (pending.marks) {
      var marks = pending.marks;
      pending.marks = null;
      setMarks(marks);
    }
    if (pending.entities) {
      var rows = pending.entities;
      pending.entities = null;
      upsert(rows);
    }
    if (pending.places) {
      var places = pending.places;
      pending.places = null;
      setPlaces(places);
    }
    if (pending.roads) {
      var roads = pending.roads;
      pending.roads = null;
      setRoads(roads);
    }
    if (pending.buildings) {
      var rings = pending.buildings;
      pending.buildings = null;
      setBuildings(rings);
    }
  }

  function dressBillboard(ent, row) {
    var img = markImage(row);
    var px = markSize(row);
    if (row.hot) px = Math.round(px * 1.45);
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
    var tint = ink(row.layer);
    if (row.hot) {
      ent.billboard.color = Cesium.Color.fromCssColorString("#ff7a22");
    } else if (row.freshness === "stale") {
      ent.billboard.color = tint.withAlpha(0.45);
    } else if (row.freshness === "dead-reckoned") {
      ent.billboard.color = tint.withAlpha(0.7);
    } else {
      ent.billboard.color = tint;
    }
    ent.billboard.disableDepthTestDistance = orbitalDepth(row);
  }

  function upsert(rows) {
    if (!viewer) { pending.entities = rows; return; }
    if (!rows) return;
    var key = rows.map(function (row) {
      return row.id + ":" + Math.round(row.lat * 100) + ":" + Math.round(row.lon * 100)
        + ":" + Math.round(row.alt_m || 0)
        + ":" + Math.round(row.vx || 0) + ":" + Math.round(row.when_unix || 0)
        + ":" + (row.mark || row.layer) + ":" + (row.heading_deg || 0)
        + ":" + (row.freshness || "") + ":" + (row.band || "")
        + ":" + (row.hot ? "1" : "0") + ":" + (row.ride ? "1" : "0");
    }).join("|");
    if (key === lastEntityKey) return;
    lastEntityKey = key;
    var keep = {};
    var anyHot = false;
    var anyMove = false;
    var riding = "";
    rows.forEach(function (row) {
      if (!row || !row.id) return;
      var pose = saneMarkLla(row.lat, row.lon, row.alt_m || 0);
      if (!pose) return;
      keep[row.id] = true;
      if (moving(row)) anyMove = true;
      if (row.ride) riding = row.id;
      var ent = entities[row.id];
      if (!ent) {
        ent = viewer.entities.add({
          id: row.id,
          position: Cesium.Cartesian3.fromDegrees(pose.lon, pose.lat, pose.alt),
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
            disableDepthTestDistance: labelDepth(row)
          }
        });
        entities[row.id] = ent;
        ent.arelisRow = row;
        ent.position = coastPosition(ent);
        dressBillboard(ent, row);
      } else {
        ent.arelisRow = row;
        if (!ent.position || !ent.position.getValue) {
          ent.position = coastPosition(ent);
        }
        dressBillboard(ent, row);
      }
      if (ent.label) {
        ent.label.text = row.label || "";
        ent.label.show = wantLabel(row);
        ent.label.disableDepthTestDistance = labelDepth(row);
        ent.label.pixelOffset = row.hot
          ? new Cesium.Cartesian2(16, -18)
          : new Cesium.Cartesian2(12, -12);
      }
      ent.arelisLayer = row.layer || "";
      if (row.hot) {
        selectedId = row.id;
        anyHot = true;
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
            position: Cesium.Cartesian3.fromDegrees(pose.lon, pose.lat, pose.alt),
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
          over.arelisRow = row;
          over.position = coastPosition(over);
        } else {
          over.arelisRow = row;
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
    if (!anyHot) selectedId = "";
    if (riding) rideId = riding;
    if (rideId && entities[rideId]) bindRide(entities[rideId]);
    hideFarSide();
    coastWanted = anyMove || !!rideId;
    if (!zoomHold || rideId) holdCoast(coastWanted);
    Object.keys(entities).forEach(function (id) {
      if (!keep[id]) {
        viewer.entities.remove(entities[id]);
        delete entities[id];
      }
    });
    viewer.scene.requestRender();
  }

  function setPlaces(rows) {
    if (!viewer) { pending.places = rows; return; }
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
    releaseCameraLock();
    clearRoads();
    lastRoadsKey = "";
    var gen = ++flyGen;
    goLock = true;
    dressWorld(pose.alt);
    viewer.scene.requestRenderMode = false;
    var cam = viewer.camera.positionCartographic;
    var fromAlt = cam ? cam.height : pose.alt;
    var dlat = cam ? Cesium.Math.toDegrees(cam.latitude) - pose.lat : 0;
    var dlon = cam ? Cesium.Math.toDegrees(cam.longitude) - pose.lon : 0;
    var secs = flySeconds(fromAlt, pose.alt, dlat, dlon);
    function finish() {
      if (gen !== flyGen || !goLock) return;
      goLock = false;
      clearGoTimer();
      /* Always sit. Skipping when rideId left the HWND on the enter still
         while Python thought we were over Singapore. */
      sitCamera(pose, 0, rideId ? -28 : -90);
      dressGlobeLod();
      if (pendingRide) {
        rideId = pendingRide;
        pendingRide = "";
        lastRideDest = null;
        holdCoast(true);
        if (entities[rideId]) followRide(entities[rideId]);
      }
      viewer.scene.requestRenderMode = false;
    }
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(pose.lon, pose.lat, pose.alt),
      orientation: {
        heading: 0,
        pitch: Cesium.Math.toRadians(-90),
        roll: 0
      },
      duration: secs,
      easingFunction: Cesium.EasingFunction.QUADRATIC_IN_OUT,
      complete: finish,
      cancel: function () {
        if (gen === flyGen) {
          goLock = false;
          clearGoTimer();
        }
      }
    });
    viewer.scene.requestRender();
    goTimer = setTimeout(finish, Math.round(secs * 1000) + 900);
  }

  function recoverRender() {
    /* A WebGL hiccup used to sit the camera at 20 Mm. Every hop and
       the ISS ride looked like they never started. Leave the eye. */
    if (!viewer) return;
    try { viewer.scene.requestRender(); } catch (err) {}
  }

  function emitCamera(force) {
    if (!viewer || !bridge) return;
    if (!force && pushing) return;
    var now = Date.now();
    if (!force && now - lastEmit < 280) return;
    lastEmit = now;
    var carto = viewer.camera.positionCartographic;
    if (!carto) return;
    var alt = carto.height;
    applyEarthFov();
    viewer.scene.fog.enabled = false;
    if (!goLock) dressWorld(alt);
    var payload = {
      lat: Cesium.Math.toDegrees(carto.latitude),
      lon: Cesium.Math.toDegrees(carto.longitude),
      alt_m: alt,
      heading: Cesium.Math.toDegrees(viewer.camera.heading),
      pitch: Cesium.Math.toDegrees(viewer.camera.pitch),
      mpp: metersPerPixel(),
      nadir_m: lookRange()
    };
    var ground = lookHit(canvasMid());
    if (Cesium.defined(ground)) {
      var g = Cesium.Cartographic.fromCartesian(ground);
      payload.look_lat = Cesium.Math.toDegrees(g.latitude);
      payload.look_lon = Cesium.Math.toDegrees(g.longitude);
    }
    var hot = selectedWindowPos();
    if (hot) {
      payload.hot_id = hot.id;
      payload.hot_x = hot.x;
      payload.hot_y = hot.y;
    }
    bridge.cameraMoved(JSON.stringify(payload));
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
      requestRenderMode: false,
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
      window.viewer = viewer;
      dressSpace();
      applyEarthFov();
      window.addEventListener("resize", function () {
        applyEarthFov();
        if (viewer) viewer.scene.requestRender();
      });
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
      viewer.screenSpaceEventHandler.removeInputAction(
        Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK
      );
      viewer.screenSpaceEventHandler.setInputAction(function (click) {
        var id = pickedMarkId(click);
        if (id && bridge) {
          var picked = viewer.scene.pick(click.position);
          var layer = picked && picked.id ? String(picked.id.arelisLayer || "") : "";
          if (RIDE_LAYERS[layer] && bridge.ridden) {
            bridge.ridden(id);
            return;
          }
          if (layer && !RIDE_LAYERS[layer] && layer !== "satellites") {
            var carto = picked && picked.id ? markCarto(picked.id) : undefined;
            if (carto) {
              flyTo({
                lat: Cesium.Math.toDegrees(carto.latitude),
                lon: Cesium.Math.toDegrees(carto.longitude),
                alt_m: 8000
              });
            }
          }
          if (bridge.picked) bridge.picked(id);
          return;
        }
      }, Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
      viewer.screenSpaceEventHandler.setInputAction(function (click) {
        var id = pickedMarkId(click);
        if (id && bridge) {
          selectedId = id;
          if (bridge.picked) bridge.picked(id);
          lastEmit = 0;
          emitCamera(true);
          return;
        }
        selectedId = "";
        if (!bridge || !bridge.groundPicked) return;
        var ray = viewer.camera.getPickRay(click.position);
        var cart = ray ? viewer.scene.globe.pick(ray, viewer.scene) : undefined;
        if (!Cesium.defined(cart)) {
          cart = viewer.camera.pickEllipsoid(
            click.position,
            viewer.scene.globe.ellipsoid
          );
        }
        if (!Cesium.defined(cart)) {
          bridge.groundPicked(JSON.stringify({ sky: true }));
          return;
        }
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
      viewer.camera.changed.addEventListener(function () {
        if (!pushing && !rideId) holdZoom(true);
        emitCamera();
      });
      viewer.camera.moveEnd.addEventListener(function () {
        holdZoom(false);
        if (coastWanted || rideId) holdCoast(true);
        lastEmit = 0;
        emitCamera(true);
      });
      applyStack(stack);
      if (bridge) bridge.ready(lastKind || stack.kind);
      lastEmit = 0;
      emitCamera();
      flushPending();
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
    if (obj.releaseCamera) {
      obj.releaseCamera.connect(function () {
        releaseCameraLock();
        if (viewer) viewer.scene.requestRender();
      });
    }
    if (obj.armRide) {
      obj.armRide.connect(function (id) {
        armRide(id);
      });
    }
    if (obj.followJson) {
      obj.followJson.connect(function (raw) {
        followLla(JSON.parse(raw));
      });
    }
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

  window.arelisFollowLla = followLla;
  window.arelisArmRide = armRide;

  if (typeof qt !== "undefined" && qt.webChannelTransport) {
    new QWebChannel(qt.webChannelTransport, function (channel) {
      attach(channel.objects.bridge);
    });
  }
})();
