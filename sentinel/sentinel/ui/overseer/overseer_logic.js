/**
 * Overseer view math shared by the canvas engine and Node checks.
 * Zoom, LOD, list windowing, and snapshot filtering. No DOM.
 */
(function (global) {
  "use strict";

  var ZOOM_MIN = 6;
  var ZOOM_MAX = 110;
  var ZOOM_NOTCH = 1.18;
  var RUBBER = 0.08;
  var RUBBER_MS = 220;
  var SPRING_MS = 180;
  var FOCUS_MS = 450;
  var REDUCED_ZOOM_MS = 120;
  var LOD0_PX = 180;
  var LOD1_PX = 60;
  var HYST = 0.15;
  var LABEL_EXPAND_PX = 48;
  var LABEL_COLLAPSE_PX = 36;
  var WIDE_CHIP_PX = 40;
  var WIDE_UNIT_COUNT = 30;
  var INSPECTOR_COLLAPSE_T = 0.7;
  var LIST_ROW_PX = 44;
  var LIST_POOL = 6;
  var PITCH_CLOSE_DEG = 22;
  var PITCH_WIDE_DEG = 55;
  var FADE_OPEN = 0.2;
  var CASTE_ROLE = {
    warden: "Defend",
    stalker: "Hunt",
    harvester: "Gather",
    sanitizer: "Quarantine",
    tripwire: "Watch",
  };
  var ROLE_CASTE = {
    Defend: "warden",
    Hunt: "stalker",
    Gather: "harvester",
    Quarantine: "sanitizer",
    Watch: "tripwire",
  };
  var CASTE_COLOR = {
    warden: "#a78bfa",
    stalker: "#e879f9",
    harvester: "#8fd3ff",
    sanitizer: "#f2c56b",
    tripwire: "#7ee0c8",
  };
  var SUPPORTED_ACTIONS = {
    deploy: true,
    recall: true,
    retire: true,
    retask: true,
    emp_halt: true,
    emp_restore: true,
    dispatch: true,
    open_folder: true,
    unban: true,
    clear_selection: true,
    close: true,
    zoom_in: true,
    zoom_out: true,
    zoom_fit: true,
  };

  function zoomT(distance) {
    var d = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, distance));
    return Math.log(d / ZOOM_MIN) / Math.log(ZOOM_MAX / ZOOM_MIN);
  }

  function pitchDeg(distance) {
    return PITCH_CLOSE_DEG + zoomT(distance) * (PITCH_WIDE_DEG - PITCH_CLOSE_DEG);
  }

  function rubberBand(distance) {
    var lo = ZOOM_MIN * (1 - RUBBER);
    var hi = ZOOM_MAX * (1 + RUBBER);
    return Math.max(lo, Math.min(hi, distance));
  }

  function settleDistance(distance) {
    return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, distance));
  }

  function wheelStep(distance, notches) {
    var next = distance * Math.pow(ZOOM_NOTCH, notches);
    return rubberBand(next);
  }

  function cursorDolly(target, pivot, dOld, dNew) {
    if (!dOld) {
      return target.slice();
    }
    var s = dNew / dOld;
    return [
      pivot[0] + (target[0] - pivot[0]) * s,
      pivot[1] + (target[1] - pivot[1]) * s,
      pivot[2] + (target[2] - pivot[2]) * s,
    ];
  }

  function chooseLod(heightPx, prevLod) {
    var enter0 = LOD0_PX * (1 + HYST);
    var leave0 = LOD0_PX * (1 - HYST);
    var enter1 = LOD1_PX * (1 + HYST);
    var leave1 = LOD1_PX * (1 - HYST);
    var lod = prevLod;
    if (lod === undefined || lod === null) {
      if (heightPx > LOD0_PX) return 0;
      if (heightPx > LOD1_PX) return 1;
      return 2;
    }
    if (lod === 0) {
      if (heightPx < leave0) lod = heightPx < leave1 ? 2 : 1;
    } else if (lod === 1) {
      if (heightPx > enter0) lod = 0;
      else if (heightPx < leave1) lod = 2;
    } else {
      if (heightPx > enter0) lod = 0;
      else if (heightPx > enter1) lod = 1;
    }
    return lod;
  }

  function silhouette(lod) {
    if (lod === 2) {
      return {
        lod: 2,
        head: "tapered",
        lenses: 1,
        tentacles: 4,
        claws: true,
        plates: false,
        eyeCluster: false,
        linkChains: false,
        unitLight: false,
      };
    }
    if (lod === 1) {
      return {
        lod: 1,
        head: "armoured",
        lenses: 4,
        tentacles: 8,
        claws: true,
        plates: true,
        eyeCluster: true,
        linkChains: false,
        unitLight: true,
      };
    }
    return {
      lod: 0,
      head: "armoured",
      lenses: 10,
      tentacles: 12,
      claws: true,
      plates: true,
      eyeCluster: true,
      linkChains: true,
      unitLight: true,
    };
  }

  function chipState(heightPx, prevShown, unitCountOnScreen) {
    if (unitCountOnScreen > WIDE_UNIT_COUNT || heightPx < WIDE_CHIP_PX) {
      if (prevShown && heightPx >= LABEL_COLLAPSE_PX && unitCountOnScreen <= WIDE_UNIT_COUNT) {
        return { chips: true, badges: false };
      }
      return { chips: false, badges: true };
    }
    if (prevShown) {
      return { chips: heightPx >= LABEL_COLLAPSE_PX, badges: heightPx < LABEL_COLLAPSE_PX };
    }
    return { chips: heightPx >= LABEL_EXPAND_PX, badges: heightPx < LABEL_EXPAND_PX };
  }

  function inspectorCollapsed(distance, selected) {
    if (selected) return false;
    return zoomT(distance) > INSPECTOR_COLLAPSE_T;
  }

  function virtualWindow(scrollY, viewportH, count, rowH, pool) {
    rowH = rowH || LIST_ROW_PX;
    pool = pool === undefined ? LIST_POOL : pool;
    var first = Math.max(0, Math.floor(Math.max(0, scrollY) / rowH));
    var visible = Math.max(1, Math.ceil(viewportH / rowH));
    var last = Math.min(count, first + visible + pool);
    first = Math.min(first, Math.max(0, count - (last - first)));
    if (first < 0) first = 0;
    last = Math.min(count, first + visible + pool);
    return {
      first: first,
      last: last,
      alive: Math.max(0, last - first),
      rowH: rowH,
      offsetPx: first * rowH,
      spacer: Math.max(0, count) * rowH,
    };
  }

  function groupUnits(units, by) {
    var groups = {};
    var order = [];
    (units || []).forEach(function (u) {
      var key;
      if (by === "task") key = u.current_task || u.state || "idle";
      else if (by === "ring") key = String(u.ring != null ? u.ring : "unassigned");
      else key = u.caste || "unknown";
      if (!groups[key]) {
        groups[key] = { key: key, units: [], active: 0 };
        order.push(key);
      }
      groups[key].units.push(u);
      var st = String(u.state || "");
      if (st.indexOf("ENGAGED") === 0 || st === "QUARANTINING" || st === "VECTORING") {
        groups[key].active += 1;
      }
    });
    order.forEach(function (key) {
      groups[key].units.sort(function (a, b) {
        var ae = String(a.state || "").indexOf("ENGAGED") === 0 ? 0 : 1;
        var be = String(b.state || "").indexOf("ENGAGED") === 0 ? 0 : 1;
        if (ae !== be) return ae - be;
        return String(a.unit_id).localeCompare(String(b.unit_id));
      });
    });
    return order.map(function (key) {
      return groups[key];
    });
  }

  function snapshotUnits(snap) {
    if (!snap || typeof snap !== "object") return [];
    if (snap.demo || snap.scenario || snap.theater) return [];
    var out = [];
    (snap.units || []).forEach(function (u) {
      if (!u || !u.unit_id) return;
      if (u.demo || u.synthetic || u.scenario) return;
      out.push(u);
    });
    return out;
  }

  function actionAllowed(name) {
    return !!SUPPORTED_ACTIONS[name];
  }

  function emptyTaskLabel(state) {
    return state ? String(state).replace(/_/g, " ").toLowerCase() : "idle";
  }

  function zoomDuration(kind, reduced) {
    if (reduced) return REDUCED_ZOOM_MS;
    if (kind === "focus" || kind === "fit") return FOCUS_MS;
    return SPRING_MS;
  }

  var api = {
    ZOOM_MIN: ZOOM_MIN,
    ZOOM_MAX: ZOOM_MAX,
    ZOOM_NOTCH: ZOOM_NOTCH,
    RUBBER: RUBBER,
    RUBBER_MS: RUBBER_MS,
    LOD0_PX: LOD0_PX,
    LOD1_PX: LOD1_PX,
    LIST_ROW_PX: LIST_ROW_PX,
    LIST_POOL: LIST_POOL,
    FADE_OPEN: FADE_OPEN,
    CASTE_ROLE: CASTE_ROLE,
    ROLE_CASTE: ROLE_CASTE,
    CASTE_COLOR: CASTE_COLOR,
    zoomT: zoomT,
    pitchDeg: pitchDeg,
    rubberBand: rubberBand,
    settleDistance: settleDistance,
    wheelStep: wheelStep,
    cursorDolly: cursorDolly,
    chooseLod: chooseLod,
    silhouette: silhouette,
    chipState: chipState,
    inspectorCollapsed: inspectorCollapsed,
    virtualWindow: virtualWindow,
    groupUnits: groupUnits,
    snapshotUnits: snapshotUnits,
    actionAllowed: actionAllowed,
    emptyTaskLabel: emptyTaskLabel,
    zoomDuration: zoomDuration,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  global.OverseerLogic = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
