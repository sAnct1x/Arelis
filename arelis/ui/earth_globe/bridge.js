/* Arelis Earth globe. Cesium draws the planet. Space and HUD stay in Qt. */
(function () {
  "use strict";

  var viewer = null;
  var tileset = null;
  var osmLayer = null;
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
  var photorealAltM = 80000;
  var atlas = {};

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
    viewer.scene.globe.enableLighting = true;
    viewer.clock.currentTime = Cesium.JulianDate.now();
    viewer.clock.shouldAnimate = false;
  }

  function dressSpace() {
    if (viewer.scene.skyBox) viewer.scene.skyBox.show = false;
    if (viewer.scene.sun) viewer.scene.sun.show = false;
    if (viewer.scene.moon) viewer.scene.moon.show = false;
    viewer.scene.skyAtmosphere.show = true;
    viewer.scene.fog.enabled = false;
    viewer.scene.backgroundColor = Cesium.Color.TRANSPARENT;
    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#160d07");
    if (viewer.scene.globe.translucency) {
      viewer.scene.globe.translucency.enabled = false;
    }
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
    photorealAltM = Number(stack.photorealAltM || 80000);
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
        flat.push(pt[1], pt[0]);
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
    if (!viewer || !lastStack) return;
    if (on && !osmLayer) {
      osmLayer = viewer.imageryLayers.addImageryProvider(
        new Cesium.UrlTemplateImageryProvider({
          url: lastStack.osm,
          maximumLevel: 15,
          credit: "OSM"
        })
      );
      viewer.scene.requestRender();
    } else if (!on && osmLayer) {
      viewer.imageryLayers.remove(osmLayer);
      osmLayer = null;
      viewer.scene.requestRender();
    }
  }

  function setCamera(payload) {
    if (!viewer || !payload) return;
    var carto = viewer.camera.positionCartographic;
    if (carto) {
      var dlat = Math.abs(Cesium.Math.toDegrees(carto.latitude) - payload.lat);
      var dlon = Math.abs(Cesium.Math.toDegrees(carto.longitude) - payload.lon);
      var dalt = Math.abs(carto.height - (payload.alt_m || 0));
      if (dlat < 1e-4 && dlon < 1e-4 && dalt < 80) return;
    }
    pushing = true;
    var dest = Cesium.Cartesian3.fromDegrees(
      payload.lon, payload.lat, payload.alt_m || 4e6
    );
    var heading = payload.heading;
    var pitch = payload.pitch;
    if (heading == null) heading = 0;
    if (pitch == null) pitch = -90;
    viewer.camera.setView({
      destination: dest,
      orientation: {
        heading: Cesium.Math.toRadians(heading),
        pitch: Cesium.Math.toRadians(pitch),
        roll: 0
      }
    });
    viewer.scene.fog.enabled = (payload.alt_m || 0) < 400000;
    syncPhotoreal(payload.alt_m || currentAlt());
    viewer.scene.requestRender();
    setTimeout(function () { pushing = false; }, 40);
  }

  function markSize(row) {
    if (row.layer === "iss") return 22;
    if (row.band === "space") return 12;
    if (row.band === "approach") return 14;
    if (row.band === "near") return 16;
    return 18;
  }

  function markImage(row) {
    var mark = row.mark || row.layer;
    var band = row.band || "city";
    return atlas[mark + ":" + band] || atlas[mark] || "";
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
    var rot = headingRad(row);
    if (!ent.billboard) return;
    if (img) ent.billboard.image = img;
    ent.billboard.width = px;
    ent.billboard.height = px;
    ent.billboard.rotation = rot;
    ent.billboard.alignedAxis = Cesium.Cartesian3.UNIT_Z;
    ent.billboard.color = Cesium.Color.WHITE;
    if (row.freshness === "stale") {
      ent.billboard.color = Cesium.Color.WHITE.withAlpha(0.45);
    } else if (row.freshness === "dead-reckoned") {
      ent.billboard.color = Cesium.Color.WHITE.withAlpha(0.7);
    }
  }

  function upsert(rows) {
    if (!viewer || !rows) return;
    var key = rows.map(function (row) {
      return row.id + ":" + Math.round(row.lat * 100) + ":" + Math.round(row.lon * 100)
        + ":" + (row.mark || row.layer) + ":" + (row.heading_deg || 0)
        + ":" + (row.freshness || "") + ":" + (row.band || "");
    }).join("|");
    if (key === lastEntityKey) return;
    lastEntityKey = key;
    var keep = {};
    rows.forEach(function (row) {
      keep[row.id] = true;
      var pos = Cesium.Cartesian3.fromDegrees(row.lon, row.lat, row.alt_m || 0);
      var ent = entities[row.id];
      if (!ent) {
        ent = viewer.entities.add({
          id: row.id,
          position: pos,
          billboard: {
            image: markImage(row),
            width: markSize(row),
            height: markSize(row),
            rotation: headingRad(row),
            alignedAxis: Cesium.Cartesian3.UNIT_Z,
            color: Cesium.Color.WHITE,
            disableDepthTestDistance: Number.POSITIVE_INFINITY
          },
          label: {
            text: row.label || "",
            font: "12px sans-serif",
            fillColor: Cesium.Color.fromCssColorString("#fae8dc"),
            pixelOffset: new Cesium.Cartesian2(8, -8),
            show: !!(row.label && (row.layer === "iss" || row.hot)),
            disableDepthTestDistance: Number.POSITIVE_INFINITY
          }
        });
        entities[row.id] = ent;
      } else {
        ent.position = pos;
        dressBillboard(ent, row);
        if (ent.label && row.label) ent.label.text = row.label;
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
              rotation: headingRad(row),
              alignedAxis: Cesium.Cartesian3.UNIT_Z,
              disableDepthTestDistance: Number.POSITIVE_INFINITY
            }
          });
          entities[oid] = over;
        } else {
          over.position = pos;
          if (over.billboard) {
            over.billboard.image = oimg;
            over.billboard.rotation = headingRad(row);
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
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(
        payload.lon, payload.lat, payload.alt_m || 8e4
      ),
      duration: 1.05
    });
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
    syncPhotoreal(alt);
    bridge.cameraMoved(JSON.stringify({
      lat: Cesium.Math.toDegrees(carto.latitude),
      lon: Cesium.Math.toDegrees(carto.longitude),
      alt_m: alt,
      heading: Cesium.Math.toDegrees(viewer.camera.heading),
      pitch: Cesium.Math.toDegrees(viewer.camera.pitch)
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
      skyBox: false,
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
      try {
        viewer = makeViewer(true);
      } catch (err) {
        viewer = makeViewer(false);
      }
      dressSpace();
      viewer.screenSpaceEventHandler.setInputAction(function (click) {
        var picked = viewer.scene.pick(click.position);
        if (Cesium.defined(picked) && picked.id && picked.id.id && bridge) {
          var id = String(picked.id.id);
          if (id.indexOf("place:") !== 0 && id.indexOf("bldg:") !== 0
              && id.indexOf(":mark-overlay") < 0) {
            bridge.picked(id);
          }
        }
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
      viewer.camera.changed.addEventListener(emitCamera);
      applyStack(stack);
      if (bridge) bridge.ready(lastKind || stack.kind);
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
    if (obj.marksJson) {
      obj.marksJson.connect(function (raw) {
        setMarks(JSON.parse(raw));
      });
    }
    obj.hello();
  }

  if (typeof qt !== "undefined" && qt.webChannelTransport) {
    new QWebChannel(qt.webChannelTransport, function (channel) {
      attach(channel.objects.bridge);
    });
  }
})();
