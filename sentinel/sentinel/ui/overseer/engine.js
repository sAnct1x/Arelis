/**
 * Sentinel v0.2 — 60 FPS 3D Overseer Rendering & Particle/Packet FX Engine.
 * Zero external CDN dependencies — 100% local-first, AMD driver safe.
 */

(function (global) {
  "use strict";

  const { SentinelVisualActor, buildBasis, vec3Add, vec3Sub, vec3Scale, vec3Lerp } = global.SentinelMesh;

  // Polyfill CanvasRenderingContext2D.roundRect for older QtWebEngine / Chromium builds
  if (global.CanvasRenderingContext2D && !global.CanvasRenderingContext2D.prototype.roundRect) {
    global.CanvasRenderingContext2D.prototype.roundRect = function (x, y, w, h, r) {
      const rr = Math.max(0, Math.min(typeof r === "number" ? r : 0, Math.abs(w) / 2, Math.abs(h) / 2));
      this.moveTo(x + rr, y);
      this.lineTo(x + w - rr, y);
      this.arcTo(x + w, y, x + w, y + rr, rr);
      this.lineTo(x + w, y + h - rr);
      this.arcTo(x + w, y + h, x + w - rr, y + h, rr);
      this.lineTo(x + rr, y + h);
      this.arcTo(x, y + h, x, y + h - rr, rr);
      this.lineTo(x, y + rr);
      this.arcTo(x, y, x + rr, y, rr);
      this.closePath();
      return this;
    };
  }

  // Golden-ratio icosahedron vertices & edges for the Arelis Sovereign Core
  const PHI = (1 + Math.sqrt(5)) / 2;
  const RAW_ICO_VERTS = [
    [-1, PHI, 0], [1, PHI, 0], [-1, -PHI, 0], [1, -PHI, 0],
    [0, -1, PHI], [0, 1, PHI], [0, -1, -PHI], [0, 1, -PHI],
    [PHI, 0, -1], [PHI, 0, 1], [-PHI, 0, -1], [-PHI, 0, 1],
  ].map((v) => {
    const l = Math.hypot(v[0], v[1], v[2]);
    return [v[0] / l, v[1] / l, v[2] / l];
  });

  const ICO_EDGES = [];
  for (let i = 0; i < RAW_ICO_VERTS.length; i++) {
    for (let j = i + 1; j < RAW_ICO_VERTS.length; j++) {
      const d = Math.hypot(
        RAW_ICO_VERTS[i][0] - RAW_ICO_VERTS[j][0],
        RAW_ICO_VERTS[i][1] - RAW_ICO_VERTS[j][1],
        RAW_ICO_VERTS[i][2] - RAW_ICO_VERTS[j][2]
      );
      if (d < 1.2) ICO_EDGES.push([i, j]);
    }
  }

  class OverseerEngine {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d", { alpha: false });
      this.width = window.innerWidth;
      this.height = window.innerHeight;
      this.dpr = Math.min(window.devicePixelRatio || 1, 2);

      // 3D Camera state
      this.camMode = "orbit"; // "orbit" | "top" | "core" | "chase"
      this.yaw = 0.55;
      this.pitch = 0.46;
      this.distance = 53.0;
      this.target = [0, 0, 0];
      this.fov = 520;

      // World state synced from Python Hive
      this.actors = new Map();
      this.nodes = new Map();
      this.nodeAge = new Map();
      this.selectedId = null;
      this.selectedKind = null; // "unit" | "node"
      this.onSelectionChanged = null;

      // 3D FX state (packets, explosions, scan waves)
      this.seenFxIds = new Set();
      this.packets = [];
      this.sparks = [];
      this.scanWaves = [];

      this.theme = {
        id: "sodium",
        bg0: "#100d0b",
        void_rgb: [16, 13, 11],
        core_hex: "#ffe4cc",
        core_halo_hex: "#ffb06c",
        accent: "#ff7a22",
        accent2: "#ffc08a",
        danger: "#ff2a3a",
        sentinel_armor: "#231e1b",
        sentinel_eye: "#ff2a3a",
        laser_harvest: "#ff9844",
        laser_sanitize: "#52e5a8",
        laser_defense: "#ff1e27",
        wall_hex: "#ff7a22",
        filament_strands: false,
      };

      this.empTripped = false;
      this.lastSnapshotAt = -Infinity;
      this.empWaveRadius = 0;
      this.empWaveAlpha = 0;

      // Ambient 3D dust motes
      this.dust = [];
      for (let i = 0; i < 100; i++) {
        const a = Math.random() * Math.PI * 2;
        const r = 4 + Math.random() * 54;
        this.dust.push({
          x: Math.cos(a) * r,
          y: (Math.random() - 0.5) * 28,
          z: Math.sin(a) * r,
          vy: (Math.random() - 0.5) * 0.65,
          size: 0.8 + Math.random() * 1.9,
          warm: Math.random(),
        });
      }

      this.screenPickables = [];
      this.keys = {};
      this.lastTime = performance.now();
      this.fpsSmoothed = 60;

      this._bindEvents();
      this._resize();
    }

    _resize() {
      this.width = window.innerWidth;
      this.height = window.innerHeight;
      this.canvas.width = Math.floor(this.width * this.dpr);
      this.canvas.height = Math.floor(this.height * this.dpr);
      this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      this.fov = Math.min(this.width, this.height) * 0.74;
    }

    _bindEvents() {
      window.addEventListener("resize", () => this._resize());

      let dragging = false;
      let dragButton = 0;
      let startX = 0;
      let startY = 0;
      let moved = 0;

      this.canvas.addEventListener("contextmenu", (e) => e.preventDefault());

      this.canvas.addEventListener("mousedown", (e) => {
        dragging = true;
        dragButton = e.button;
        startX = e.clientX;
        startY = e.clientY;
        moved = 0;
      });

      window.addEventListener("mousemove", (e) => {
        if (!dragging) return;
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;
        moved += Math.abs(dx) + Math.abs(dy);
        startX = e.clientX;
        startY = e.clientY;

        if (dragButton === 0) {
          this.yaw -= dx * 0.0065;
          this.pitch = Math.max(-1.45, Math.min(1.45, this.pitch - dy * 0.0065));
        } else if (dragButton === 2) {
          const panScale = this.distance * 0.0016;
          const right = [Math.cos(this.yaw), 0, -Math.sin(this.yaw)];
          this.target[0] -= right[0] * dx * panScale;
          this.target[2] -= right[2] * dx * panScale;
          this.target[1] += dy * panScale;
        }
      });

      window.addEventListener("mouseup", (e) => {
        if (dragging && moved < 6 && e.button === 0) {
          this._handlePick(e.clientX, e.clientY);
        }
        dragging = false;
      });

      this.canvas.addEventListener(
        "wheel",
        (e) => {
          e.preventDefault();
          this.distance = Math.max(12.0, Math.min(150.0, this.distance * (1 + e.deltaY * 0.001)));
        },
        { passive: false }
      );

      window.addEventListener("keydown", (e) => {
        if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "SELECT")) return;
        this.keys[e.key.toLowerCase()] = true;
      });

      window.addEventListener("keyup", (e) => {
        this.keys[e.key.toLowerCase()] = false;
      });
    }

    _handlePick(mx, my) {
      let best = null;
      let bestDist = 30;
      for (const item of this.screenPickables) {
        const d = Math.hypot(item.sx - mx, item.sy - my);
        if (d < bestDist) {
          bestDist = d;
          best = item;
        }
      }
      if (best) {
        this.selectedId = best.id;
        this.selectedKind = best.kind;
      } else {
        this.selectedId = null;
        this.selectedKind = null;
      }
      if (this.onSelectionChanged) {
        this.onSelectionChanged(this.selectedId, this.selectedKind);
      }
    }

    setCameraMode(mode) {
      this.camMode = mode;
      if (mode === "top") {
        this.pitch = 1.38;
        this.distance = 76.0;
        this.target = [0, 0, 0];
      } else if (mode === "core") {
        this.pitch = 0.25;
        this.distance = 24.0;
        this.target = [0, 0, 0];
      } else if (mode === "orbit") {
        this.pitch = 0.46;
        this.distance = 62.0;
        this.target = [0, 0, 0];
      }
    }

    triggerEmpShockwave() {
      this.empWaveRadius = 1.0;
      this.empWaveAlpha = 1.0;
    }

    _spawnFxEvent(fx) {
      const origin = fx.origin || [0, 0, 0];
      const target = fx.target || [0, 0, 0];
      const color = fx.color || "#ff2a3a";

      if (fx.kind === "packet_salvo") {
        const count = fx.count || 12;
        for (let i = 0; i < count; i++) {
          this.packets.push({
            origin: origin.slice(),
            target: target.slice(),
            color,
            progress: -i * 0.09, // staggered launch
            speed: 0.72 + Math.random() * 0.25,
            arcHeight: (Math.random() - 0.35) * 3.2,
            size: 2.2 + Math.random() * 1.4,
          });
        }
      } else if (fx.kind === "explosion") {
        const count = fx.count || 26;
        for (let i = 0; i < count; i++) {
          const theta = Math.random() * Math.PI * 2;
          const phi = (Math.random() - 0.5) * Math.PI;
          const spd = 6.0 + Math.random() * 18.0;
          this.sparks.push({
            pos: origin.slice(),
            vel: [
              Math.cos(theta) * Math.cos(phi) * spd,
              Math.sin(phi) * spd + 2.5,
              Math.sin(theta) * Math.cos(phi) * spd,
            ],
            color: i % 3 === 0 ? "#ffffff" : color,
            life: 1.0,
            decay: 0.65 + Math.random() * 0.55,
            size: 1.8 + Math.random() * 2.2,
          });
        }
        this.scanWaves.push({
          origin: origin.slice(),
          color,
          radius: 0.6,
          maxRadius: 11.0,
          alpha: 1.0,
          speed: 14.0,
        });
      } else if (fx.kind === "scan_wave") {
        this.scanWaves.push({
          origin: origin.slice(),
          color,
          radius: 1.0,
          maxRadius: 29.0,
          alpha: 0.9,
          speed: 19.0,
        });
      } else if (fx.kind === "orb_deposit") {
        this.scanWaves.push({
          origin: [0, 0, 0],
          color: this.theme.accent2 || "#ffc08a",
          radius: 2.5,
          maxRadius: 14.0,
          alpha: 0.95,
          speed: 12.0,
        });
      }
    }

    syncSnapshot(snap) {
      if (snap.theme) {
        this.theme = snap.theme;
      }
      if (snap.host_telemetry) {
        this.hostTelemetry = snap.host_telemetry;
      }
      this.lastSnapshotAt = performance.now();
      const wasEmp = this.empTripped;
      this.empTripped = !!(snap.emp && snap.emp.tripped);
      if (this.empTripped && !wasEmp) {
        this.triggerEmpShockwave();
      }

      // Sync FX events
      for (const fx of snap.fx_events || []) {
        if (fx.fx_id && !this.seenFxIds.has(fx.fx_id)) {
          this.seenFxIds.add(fx.fx_id);
          this._spawnFxEvent(fx);
        }
      }
      if (this.seenFxIds.size > 400) {
        const arr = Array.from(this.seenFxIds);
        this.seenFxIds = new Set(arr.slice(arr.length - 200));
      }

      const seenUnits = new Set();
      for (const u of snap.units || []) {
        seenUnits.add(u.unit_id);
        let actor = this.actors.get(u.unit_id);
        if (!actor) {
          actor = new SentinelVisualActor(u);
          this.actors.set(u.unit_id, actor);
        } else {
          actor.syncFromServer(u);
        }
      }
      for (const id of Array.from(this.actors.keys())) {
        if (!seenUnits.has(id)) this.actors.delete(id);
      }

      const nextNodes = new Map();
      const nowSec = performance.now() * 0.001;
      for (const n of snap.nodes || []) {
        nextNodes.set(n.node_id, n);
        if (!this.nodeAge.has(n.node_id)) {
          this.nodeAge.set(n.node_id, nowSec);
        }
      }
      this.nodes = nextNodes;
    }

    project(pt, camBasis) {
      if (!pt || !Number.isFinite(pt[0]) || !Number.isFinite(pt[1]) || !Number.isFinite(pt[2])) {
        return null;
      }
      const dx = pt[0] - camBasis.eye[0];
      const dy = pt[1] - camBasis.eye[1];
      const dz = pt[2] - camBasis.eye[2];

      const cx = dx * camBasis.right[0] + dy * camBasis.right[1] + dz * camBasis.right[2];
      const cy = dx * camBasis.up[0] + dy * camBasis.up[1] + dz * camBasis.up[2];
      const cz = dx * camBasis.fwd[0] + dy * camBasis.fwd[1] + dz * camBasis.fwd[2];

      // Near-plane clip at cz <= 3.6 so objects passing the camera lens never explode to 1000px+ screen flashes
      if (cz <= 3.6) return null;
      const rawScale = this.fov / cz;
      const scale = Math.min(rawScale, 82.0);
      const sx = this.width * 0.5 + cx * rawScale;
      const sy = this.height * 0.5 - cy * rawScale;
      if (!Number.isFinite(sx) || !Number.isFinite(sy)) return null;
      return {
        sx,
        sy,
        cz,
        scale,
      };
    }

    _computeCamera(dt) {
      const moveSpd = 26.0 * dt;
      const fwdXZ = [-Math.sin(this.yaw), 0, -Math.cos(this.yaw)];
      const rightXZ = [Math.cos(this.yaw), 0, -Math.sin(this.yaw)];
      if (this.keys["w"]) {
        this.target[0] += fwdXZ[0] * moveSpd;
        this.target[2] += fwdXZ[2] * moveSpd;
      }
      if (this.keys["s"]) {
        this.target[0] -= fwdXZ[0] * moveSpd;
        this.target[2] -= fwdXZ[2] * moveSpd;
      }
      if (this.keys["a"]) {
        this.target[0] -= rightXZ[0] * moveSpd;
        this.target[2] -= rightXZ[2] * moveSpd;
      }
      if (this.keys["d"]) {
        this.target[0] += rightXZ[0] * moveSpd;
        this.target[2] += rightXZ[2] * moveSpd;
      }
      if (this.keys["e"]) this.target[1] += moveSpd * 0.7;
      if (this.keys["q"]) this.target[1] -= moveSpd * 0.7;

      // If chase target was a temporary node/unit that has been removed, smoothly return to orbital view
      if (this.selectedId) {
        const missingNode = this.selectedKind === "node" && !this.nodes.has(this.selectedId);
        const missingUnit = this.selectedKind === "unit" && !this.actors.has(this.selectedId);
        if (missingNode || missingUnit) {
          this.selectedId = null;
          this.selectedKind = null;
          if (this.camMode === "chase") {
            this.camMode = "orbit";
            this.target = [0, 0, 0];
          }
          if (this.onSelectionChanged) {
            this.onSelectionChanged(null, null);
          }
        }
      }

      if (this.camMode === "chase" && this.selectedId) {
        if (this.selectedKind === "core") {
          this.target[0] += (0 - this.target[0]) * Math.min(1, dt * 8);
          this.target[1] += (0 - this.target[1]) * Math.min(1, dt * 8);
          this.target[2] += (0 - this.target[2]) * Math.min(1, dt * 8);
        } else if (this.selectedKind === "unit" && this.actors.has(this.selectedId)) {
          const act = this.actors.get(this.selectedId);
          this.target[0] += (act.pos[0] - this.target[0]) * Math.min(1, dt * 8);
          this.target[1] += (act.pos[1] - this.target[1]) * Math.min(1, dt * 8);
          this.target[2] += (act.pos[2] - this.target[2]) * Math.min(1, dt * 8);
        } else if (this.selectedKind === "node" && this.nodes.has(this.selectedId)) {
          const nd = this.nodes.get(this.selectedId);
          this.target[0] += (nd.position[0] - this.target[0]) * Math.min(1, dt * 8);
          this.target[1] += (nd.position[1] - this.target[1]) * Math.min(1, dt * 8);
          this.target[2] += (nd.position[2] - this.target[2]) * Math.min(1, dt * 8);
        }
      } else if (this.camMode === "orbit" || (this.camMode === "chase" && !this.selectedId)) {
        this.yaw += dt * 0.042;
      }

      const cp = Math.cos(this.pitch);
      const sp = Math.sin(this.pitch);
      const cy = Math.cos(this.yaw);
      const sy = Math.sin(this.yaw);

      const eye = [
        this.target[0] + sy * cp * this.distance,
        this.target[1] + sp * this.distance,
        this.target[2] + cy * cp * this.distance,
      ];

      const fwd = [
        (this.target[0] - eye[0]) / this.distance,
        (this.target[1] - eye[1]) / this.distance,
        (this.target[2] - eye[2]) / this.distance,
      ];
      const right = [cy, 0, -sy];
      const up = [
        fwd[1] * right[2] - fwd[2] * right[1],
        fwd[2] * right[0] - fwd[0] * right[2],
        fwd[0] * right[1] - fwd[1] * right[0],
      ];

      return { eye, fwd, right, up };
    }

    renderFrame(nowMs) {
      const dt = Math.min(0.05, Math.max(0.001, (nowMs - this.lastTime) / 1000));
      this.lastTime = nowMs;
      const instFps = 1.0 / dt;
      this.fpsSmoothed = this.fpsSmoothed * 0.92 + instFps * 0.08;
      const telemetryFresh = nowMs - this.lastSnapshotAt < 2500;
      const timeSec = (telemetryFresh && !this.empTripped ? nowMs : (Number.isFinite(this.lastSnapshotAt) ? this.lastSnapshotAt : 0)) * 0.001;

      const ctx = this.ctx;
      // Hard-reset canvas state every frame so any prior partial frame can never leak state
      ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
      ctx.setLineDash([]);
      ctx.lineCap = "butt";
      ctx.lineJoin = "miter";
      const cam = this._computeCamera(dt);
      this.screenPickables = [];

      // 1. Background Void & Atmospheric Lamp Bloom
      ctx.fillStyle = this.theme.bg0 || "#100d0b";
      ctx.fillRect(0, 0, this.width, this.height);

      const coreProj = this.project([0, 0, 0], cam);
      if (coreProj) {
        const grad = ctx.createRadialGradient(
          coreProj.sx,
          coreProj.sy,
          4,
          coreProj.sx,
          coreProj.sy,
          Math.max(this.width, this.height) * 0.54
        );
        grad.addColorStop(0, this._hexAlpha(this.theme.core_halo_hex || "#ff7a22", 0.14));
        grad.addColorStop(0.38, this._hexAlpha(this.theme.accent || "#ff7a22", 0.08));
        grad.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, this.width, this.height);
      }

      // 2. Subterranean Floor Grid & Caste Orbit Rings
      this._drawRingsAndGrid(ctx, cam, timeSec);

      // 3. Filament Flowing Current Strands & Dust Motes
      this._drawDustAndStrands(ctx, cam, dt, timeSec);

      // 4. Step & Draw 3D Scan Waves
      this._stepAndDrawScanWaves(ctx, cam, telemetryFresh && !this.empTripped ? dt : 0);

      // 5. Advance Sentinel Physics & Collect Depth-Sorted Renderables
      const renderQueue = [];

      if (coreProj) {
        renderQueue.push({ kind: "core", cz: coreProj.cz, proj: coreProj });
      }

      for (const node of this.nodes.values()) {
        const p = this.project(node.position, cam);
        if (p) {
          renderQueue.push({ kind: "node", cz: p.cz, node, proj: p });
        }
      }

      const packAlphas = new Map();
      for (const actor of this.actors.values()) {
        if (!this.empTripped && nowMs - this.lastSnapshotAt < 2500) actor.stepPhysics(dt, timeSec);
        const p = this.project(actor.pos, cam);
        if (p) {
          renderQueue.push({ kind: "sentinel", cz: p.cz, actor, proj: p });
          if (actor.pack_id && actor.pack_role === "ALPHA") {
            packAlphas.set(actor.pack_id, { actor, proj: p });
          }
        }
      }

      // Draw Pack Neural Link Tethers connecting Wingmen to their Pack Alpha
      for (const actor of this.actors.values()) {
        if (actor.pack_id && actor.pack_role === "WINGMAN") {
          const alphaInfo = packAlphas.get(actor.pack_id);
          const wProj = this.project(actor.pos, cam);
          if (alphaInfo && wProj) {
            ctx.save();
            ctx.strokeStyle = this._hexAlpha(this.theme.accent || "#ff7a22", 0.36);
            ctx.lineWidth = 1.15;
            ctx.setLineDash([3, 4]);
            ctx.beginPath();
            ctx.moveTo(alphaInfo.proj.sx, alphaInfo.proj.sy);
            ctx.lineTo(wProj.sx, wProj.sy);
            ctx.stroke();
            ctx.restore();
          }
        }
      }

      renderQueue.sort((a, b) => b.cz - a.cz);

      for (const item of renderQueue) {
        if (item.kind === "core") {
          this._drawArelisCore(ctx, cam, item.proj, timeSec);
        } else if (item.kind === "node") {
          this._drawWorldNode(ctx, cam, item.node, item.proj, timeSec);
        } else if (item.kind === "sentinel") {
          this._drawSentinel(ctx, cam, item.actor, item.proj, timeSec);
        }
      }

      // 6. Step & Draw 3D Packet Salvos and Explosion Shrapnel Sparks on top
      this._stepAndDrawPacketsAndSparks(ctx, cam, telemetryFresh && !this.empTripped ? dt : 0);

      // 7. EMP Shockwave Sphere if triggered
      if (this.empWaveAlpha > 0.01 && coreProj) {
        this.empWaveRadius += dt * 95.0;
        this.empWaveAlpha = Math.max(0, this.empWaveAlpha - dt * 0.85);
        const rPx = Math.min(this.empWaveRadius * coreProj.scale, Math.max(this.width, this.height) * 1.5);
        ctx.save();
        ctx.strokeStyle = `rgba(255, 42, 68, ${this.empWaveAlpha.toFixed(3)})`;
        ctx.lineWidth = 3.5;
        ctx.beginPath();
        ctx.arc(coreProj.sx, coreProj.sy, rPx, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }
    }

    _stepAndDrawScanWaves(ctx, cam, dt) {
      for (let i = this.scanWaves.length - 1; i >= 0; i--) {
        const w = this.scanWaves[i];
        w.radius += w.speed * dt;
        w.alpha = Math.max(0, 1.0 - w.radius / w.maxRadius);
        if (w.radius >= w.maxRadius || w.alpha <= 0.02) {
          this.scanWaves.splice(i, 1);
          continue;
        }
        ctx.beginPath();
        const steps = 48;
        let started = false;
        for (let s = 0; s <= steps; s++) {
          const a = (s / steps) * Math.PI * 2;
          const pt = [
            w.origin[0] + Math.cos(a) * w.radius,
            w.origin[1],
            w.origin[2] + Math.sin(a) * w.radius,
          ];
          const p = this.project(pt, cam);
          if (!p) {
            started = false;
            continue;
          }
          if (!started) {
            ctx.moveTo(p.sx, p.sy);
            started = true;
          } else {
            ctx.lineTo(p.sx, p.sy);
          }
        }
        ctx.strokeStyle = this._hexAlpha(w.color, w.alpha * 0.78);
        ctx.lineWidth = 2.2;
        ctx.stroke();
      }
    }

    _stepAndDrawPacketsAndSparks(ctx, cam, dt) {
      // 1. 3D Packet Salvos (exploit bursts or verified data streams)
      for (let i = this.packets.length - 1; i >= 0; i--) {
        const pkt = this.packets[i];
        pkt.progress += pkt.speed * dt;
        if (pkt.progress >= 1.0) {
          this.packets.splice(i, 1);
          continue;
        }
        if (pkt.progress < 0) continue;

        const u = pkt.progress;
        const pos = vec3Lerp(pkt.origin, pkt.target, u);
        pos[1] += Math.sin(u * Math.PI) * pkt.arcHeight;

        const prevU = Math.max(0, u - 0.09);
        const tailPos = vec3Lerp(pkt.origin, pkt.target, prevU);
        tailPos[1] += Math.sin(prevU * Math.PI) * pkt.arcHeight;

        const pHead = this.project(pos, cam);
        const pTail = this.project(tailPos, cam);
        if (!pHead || !pTail) continue;

        ctx.save();
        ctx.strokeStyle = this._hexAlpha(pkt.color, 0.85);
        ctx.lineWidth = Math.max(1.8, Math.min(pkt.size * pHead.scale * 0.14, 12.0));
        ctx.beginPath();
        ctx.moveTo(pTail.sx, pTail.sy);
        ctx.lineTo(pHead.sx, pHead.sy);
        ctx.stroke();

        ctx.fillStyle = "#ffffff";
        ctx.beginPath();
        ctx.arc(pHead.sx, pHead.sy, Math.max(2.0, Math.min(pkt.size * pHead.scale * 0.12, 10.0)), 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      // 2. 3D Explosion Shrapnel Sparks
      for (let i = this.sparks.length - 1; i >= 0; i--) {
        const sp = this.sparks[i];
        sp.life -= sp.decay * dt;
        if (sp.life <= 0) {
          this.sparks.splice(i, 1);
          continue;
        }
        sp.vel[1] -= 9.5 * dt; // subtle gravity arc
        sp.pos[0] += sp.vel[0] * dt;
        sp.pos[1] += sp.vel[1] * dt;
        sp.pos[2] += sp.vel[2] * dt;

        const p = this.project(sp.pos, cam);
        if (!p) continue;
        const r = Math.max(1.4, Math.min(sp.size * sp.life * p.scale * 0.14, 8.0));
        ctx.fillStyle = this._hexAlpha(sp.color, Math.min(1, sp.life * 1.2));
        ctx.beginPath();
        ctx.arc(p.sx, p.sy, r, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    updateCasteProfiles(castes) {
      if (!castes || !castes.length) return;
      this.casteProfiles = castes.map((c) => ({
        r: c.orbit_radius || 20.0,
        y: c.orbit_y_band || 0.0,
        alpha: 0.22,
        dashed: false,
        label: `${(c.title || c.caste_id).toUpperCase()} ORBIT (R=${(c.orbit_radius || 20.0).toFixed(1)})`,
        color: c.eye_color || "#ff2a3a",
      }));
    }

    _drawRingsAndGrid(ctx, cam, timeSec) {
      const radii = this.casteProfiles || [
        { r: 12.5, y: 3.0, alpha: 0.19, dashed: true, label: "SANITIZER SCRUB RING (R=12.5)" },
        { r: 18.0, y: 4.0, alpha: 0.22, dashed: false, label: "HARVESTER ORBIT (R=18.0)" },
        { r: 24.0, y: -3.5, alpha: 0.20, dashed: true, label: "MERKLE TRIPWIRE RING (R=24.0)" },
        { r: 28.0, y: 0.0, alpha: 0.42, dashed: false, label: "WARDEN PERIMETER WALL (R=28.0)" },
      ];

      for (const ring of radii) {

        ctx.beginPath();
        const steps = 72;
        let started = false;
        for (let i = 0; i <= steps; i++) {
          const a = (i / steps) * Math.PI * 2;
          const pt = [Math.cos(a) * ring.r, ring.y, Math.sin(a) * ring.r];
          const p = this.project(pt, cam);
          if (!p) {
            started = false;
            continue;
          }
          if (!started) {
            ctx.moveTo(p.sx, p.sy);
            started = true;
          } else {
            ctx.lineTo(p.sx, p.sy);
          }
        }
        ctx.strokeStyle = this._hexAlpha(this.theme.wall_hex || "#ff7a22", ring.alpha);
        ctx.lineWidth = ring.r === 28.0 ? 1.8 : 1.05;
        if (ring.dashed) ctx.setLineDash([4, 6]);
        else ctx.setLineDash([]);
        ctx.stroke();
      }
      ctx.setLineDash([]);

      // Fixed architectural sectors; structural lights do not claim enforcement.
      const color = this.empTripped ? '#647080' : (this.theme.wall_hex || '#ff7a22');
      const line = (points, stroke, width=1) => {
        const p = points.map(v => this.project(v, cam));
        if(p.some(v => !v)) return;
        ctx.beginPath(); p.forEach((v,i) => i ? ctx.lineTo(v.sx,v.sy) : ctx.moveTo(v.sx,v.sy));
        ctx.strokeStyle=stroke; ctx.lineWidth=width; ctx.stroke();
      };
      // Deck grid and concentric service tracks establish scale and altitude.
      for(let n=-36;n<=36;n+=4) {
        const extent=Math.sqrt(38*38-n*n);
        line([[n,-7,-extent],[n,-7,extent]],'rgba(130,155,180,0.08)');
        line([[-extent,-7,n],[extent,-7,n]],'rgba(130,155,180,0.08)');
      }
      for(let i=0;i<32;i++) {
        const a=i/32*Math.PI*2, b=(i+1)/32*Math.PI*2;
        const pt=(r,y,ang)=>[Math.cos(ang)*r,y,Math.sin(ang)*r];
        const corners=[pt(28,-6,a),pt(28,3,a),pt(28,3,b),pt(28,-6,b)];
        const p=corners.map(v=>this.project(v,cam));
        if(p.every(Boolean)) {
          ctx.beginPath();p.forEach((v,j)=>j?ctx.lineTo(v.sx,v.sy):ctx.moveTo(v.sx,v.sy));ctx.closePath();
          ctx.fillStyle='rgba(40,54,67,0.09)';ctx.fill();
        }
        line([pt(28,-6,a),pt(28,3,a)],this._hexAlpha(color,0.25),2);
        line([pt(28,3,a),pt(28,3,b)],this._hexAlpha(color,0.36),1.5);
        line([pt(28,-6,a),pt(28,-6,b)],'rgba(161,185,200,0.28)',2);
        line([pt(28,2.7,a),pt(28,2.7,b)],this._hexAlpha(color,0.12));
        line([pt(28,-6,a),pt(30,-7,a)],'rgba(161,185,200,0.35)',3);
        const foot=[pt(27.6,-6.8,a-.018),pt(30.3,-7,a-.018),pt(30.3,-7,a+.018),pt(27.6,-6.8,a+.018)].map(v=>this.project(v,cam));
        if(foot.every(Boolean)){ctx.beginPath();foot.forEach((v,j)=>j?ctx.lineTo(v.sx,v.sy):ctx.moveTo(v.sx,v.sy));ctx.closePath();ctx.fillStyle='#283540';ctx.fill();ctx.strokeStyle='#50606b';ctx.lineWidth=.7;ctx.stroke();}
        if(i%4===0) {
          const tag=this.project(pt(30,-7,a),cam);
          if(tag) {ctx.font='9px Consolas';ctx.textAlign='center';ctx.fillStyle=this._hexAlpha(color,0.65);ctx.fillText('SECTOR '+String(i/4+1).padStart(2,'0'),tag.sx,tag.sy+14);}
        }
      }
      ctx.save();ctx.font='10px Consolas';ctx.textAlign='center';ctx.fillStyle='rgba(192,207,219,0.65)';
      ctx.fillText('PERIMETER / POLICY TOPOLOGY',this.width/2,145);
      if(performance.now()-this.lastSnapshotAt>=2500) {ctx.fillStyle='#d6af76';ctx.fillText('TELEMETRY UNAVAILABLE — LAST OBSERVED STATE',this.width/2,161);}
      ctx.restore();
    }

    _drawDustAndStrands(ctx, cam, dt, timeSec) {
      for (const d of this.dust) {
        d.y += d.vy * dt;
        if (d.y > 14) d.y = -14;
        if (d.y < -14) d.y = 14;
        const p = this.project([d.x, d.y, d.z], cam);
        if (!p) continue;
        const alpha = Math.min(0.45, 14.0 / p.cz);
        ctx.fillStyle = d.warm > 0.5
          ? this._hexAlpha(this.theme.accent2 || "#ffc08a", alpha)
          : this._hexAlpha(this.theme.accent || "#ff7a22", alpha * 0.8);
        const sz = Math.max(1.0, Math.min(d.size * p.scale * 0.08, 4.0));
        ctx.fillRect(p.sx - sz * 0.5, p.sy - sz * 0.5, sz, sz);
      }

      if (this.theme.filament_strands) {
        for (let s = 0; s < 4; s++) {
          ctx.beginPath();
          let started = false;
          for (let i = 0; i <= 64; i++) {
            const u = i / 64;
            const ang = u * Math.PI * 2 + timeSec * 0.22 + s * 0.5;
            const r = 9.5 + Math.sin(u * Math.PI * 4 + timeSec + s) * 2.2;
            const y = Math.cos(u * Math.PI * 3 - timeSec * 0.8 + s * 1.1) * 3.2;
            const p = this.project([Math.cos(ang) * r, y, Math.sin(ang) * r], cam);
            if (!p) {
              started = false;
              continue;
            }
            if (!started) {
              ctx.moveTo(p.sx, p.sy);
              started = true;
            } else {
              ctx.lineTo(p.sx, p.sy);
            }
          }
          ctx.strokeStyle = this._hexAlpha(this.theme.accent2 || "#e4c896", 0.25);
          ctx.lineWidth = 1.25;
          ctx.stroke();
        }
      }
    }

    _drawArelisCore(ctx, cam, proj, timeSec) {
      const isSelected = this.selectedKind === "core";
      this.screenPickables.push({ id: "arelis-core", kind: "core", sx: proj.sx, sy: proj.sy });

      const coreRadius = 3.8;
      const rotY = timeSec * 0.55;
      const rotX = timeSec * 0.32;
      const cy = Math.cos(rotY), sy = Math.sin(rotY);
      const cx = Math.cos(rotX), sx = Math.sin(rotX);

      const pVerts = RAW_ICO_VERTS.map((v) => {
        const x1 = v[0] * cy - v[2] * sy;
        const z1 = v[0] * sy + v[2] * cy;
        const y2 = v[1] * cx - z1 * sx;
        const z2 = v[1] * sx + z1 * cx;
        return this.project([x1 * coreRadius, y2 * coreRadius, z2 * coreRadius], cam);
      });

      // Outer radial halo
      const haloR = Math.max(20, Math.min(coreRadius * proj.scale * 1.95, 260));
      const grad = ctx.createRadialGradient(proj.sx, proj.sy, 2, proj.sx, proj.sy, haloR);
      grad.addColorStop(0, this.theme.core_hex || "#ffe4cc");
      grad.addColorStop(0.30, this._hexAlpha(this.theme.core_halo_hex || "#ffb06c", 0.68));
      grad.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(proj.sx, proj.sy, haloR, 0, Math.PI * 2);
      ctx.fill();

      // Wireframe icosahedron struts
      ctx.strokeStyle = isSelected ? "#ffffff" : this._hexAlpha(this.theme.core_hex || "#ffe4cc", 0.78);
      ctx.lineWidth = isSelected ? 2.2 : 1.45;
      ctx.beginPath();
      for (const [i, j] of ICO_EDGES) {
        const a = pVerts[i];
        const b = pVerts[j];
        if (a && b) {
          ctx.moveTo(a.sx, a.sy);
          ctx.lineTo(b.sx, b.sy);
        }
      }
      ctx.stroke();

      // Sovereign Core Label with dark HUD pill backdrop for crisp legibility
      const baseY = proj.sy + coreRadius * proj.scale + 16;
      const ht = this.hostTelemetry;
      const subText = ht
        ? `CPU ${ht.cpu_percent ?? 0}% • RAM ${ht.ram_used_gb ?? 0}/${ht.ram_total_gb ?? 64}G • ${ht.listening_tcp_count ?? 0} TCP • ${ht.merkle_files_hashed ?? 0} MERKLE FILES`
        : "";
      const pillW = subText ? Math.max(210, subText.length * 5.3 + 22) : 176;
      const pillH = subText ? 31 : 19;
      ctx.save();
      ctx.fillStyle = "rgba(8, 10, 14, 0.78)";
      ctx.strokeStyle = this._hexAlpha(this.theme.accent || "#ff7a22", 0.35);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(proj.sx - pillW * 0.5, baseY - 12, pillW, pillH, 5);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = this.theme.core_hex || "#ffe4cc";
      ctx.font = '700 10.5px "Space Mono", "Consolas", monospace';
      ctx.textAlign = "center";
      ctx.fillText("ARELIS SOVEREIGN CORE", proj.sx, baseY);

      if (subText) {
        ctx.font = '600 8.5px "Space Mono", "Consolas", monospace';
        ctx.fillStyle = this._hexAlpha(this.theme.accent2 || "#ffc08a", 0.92);
        ctx.fillText(subText, proj.sx, baseY + 13);
      }
      ctx.restore();
    }

    _drawWorldNode(ctx, cam, node, proj, timeSec) {
      const isSelected = this.selectedKind === "node" && this.selectedId === node.node_id;
      this.screenPickables.push({ id: node.node_id, kind: "node", sx: proj.sx, sy: proj.sy });

      const isThreat = node.kind === "threat" || node.status === "quarantined" || node.severity === "critical" || node.status === "under_attack";
      const isHarvest = node.kind === "harvest_target";
      const isMerkle = node.node_id && node.node_id.startsWith("merkle-root-");
      const isBastion = node.kind === "bastion";
      const isListeningBastion = isBastion && !!(node.metadata && node.metadata.listening);

      let color = this.theme.accent || "#ff7a22";
      if (isThreat) {
        color = this.theme.danger || "#ff2a3a";
      } else if (isHarvest) {
        color = this.theme.accent2 || "#ffc08a";
      } else if (isMerkle) {
        color = this.theme.laser_sanitize || "#52e5a8";
      } else if (isBastion) {
        color = isListeningBastion ? (this.theme.laser_sanitize || "#52e5a8") : (this.theme.wall_hex || "#ff7a22");
      }

      const rPx = Math.max(7, Math.min((isBastion ? 1.85 : isMerkle ? 2.05 : 2.35) * proj.scale, 75));
      const glowAlpha = isThreat ? 0.88 : isBastion && !isListeningBastion ? 0.35 : 0.74;

      // Node glow
      const g = ctx.createRadialGradient(proj.sx, proj.sy, 1, proj.sx, proj.sy, rPx * 2.8);
      g.addColorStop(0, this._hexAlpha(color, glowAlpha));
      g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(proj.sx, proj.sy, rPx * 2.8, 0, Math.PI * 2);
      ctx.fill();

      // Pulsing outer target reticle for active threats, harvest targets, or live listening Bastion ports
      if (isThreat || isHarvest || isListeningBastion || isMerkle) {
        const pulseR = rPx * (1.48 + Math.sin(timeSec * (isThreat ? 6.5 : 3.2)) * 0.2);
        ctx.strokeStyle = this._hexAlpha(color, isThreat || isHarvest ? 0.58 : 0.38);
        ctx.lineWidth = 1.2;
        if (isThreat || isHarvest) ctx.setLineDash([4, 4]);
        else ctx.setLineDash([]);
        ctx.beginPath();
        ctx.arc(proj.sx, proj.sy, pulseR, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // Rotating 3D-projected polyhedron icon
      ctx.save();
      ctx.translate(proj.sx, proj.sy);
      ctx.rotate(timeSec * (isBastion ? 0.35 : isMerkle ? -0.45 : 1.4));
      ctx.strokeStyle = color;
      ctx.fillStyle = this._hexAlpha(color, isBastion && !isListeningBastion ? 0.10 : 0.24);
      ctx.lineWidth = isSelected ? 2.6 : 1.7;
      ctx.beginPath();
      const sides = isBastion ? 6 : isMerkle ? 8 : 4;
      for (let i = 0; i <= sides; i++) {
        const a = (i / sides) * Math.PI * 2;
        const x = Math.cos(a) * rPx;
        const y = Math.sin(a) * rPx;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.fill();
      ctx.stroke();
      ctx.restore();

      // If quarantined, draw red laser containment cage
      if (node.kind === "quarantine" || node.status === "quarantined") {
        ctx.strokeStyle = this.theme.danger || "#ff2a3a";
        ctx.lineWidth = 1.8;
        ctx.strokeRect(proj.sx - rPx * 1.5, proj.sy - rPx * 1.5, rPx * 3.0, rPx * 3.0);
      }

      // Floating 3D Tactical Callout Box above active Threats / Harvests / Selected Nodes
      if (isThreat || isHarvest || isSelected) {
        let tagText = "PERIMETER NODE";
        if (node.status === "quarantined") tagText = "QUARANTINED PAYLOAD";
        else if (node.status === "under_attack") tagText = "⚠ UNDER CYBER ATTACK";
        else if (isThreat) tagText = "🚨 ACTIVE INTRUSION / PAYLOAD";
        else if (isHarvest) tagText = "🔭 HARVEST TARGET";
        else if (isMerkle) tagText = "🛡 BLAKE2B MERKLE ANCHOR";
        else if (isListeningBastion) tagText = "🟢 LIVE OS SOCKET LISTENING";
        else if (isBastion) tagText = "⚪ BASTION PORT STANDBY";

        const labelText = (node.label || node.node_id).slice(0, 42);
        const boxW = Math.max(154, labelText.length * 6.4 + 18);
        const boxH = 34;
        const bx = proj.sx - boxW * 0.5;
        const by = proj.sy - rPx - boxH - 10;

        ctx.save();
        ctx.fillStyle = "rgba(10, 12, 16, 0.88)";
        ctx.strokeStyle = this._hexAlpha(color, 0.85);
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.roundRect(bx, by, boxW, boxH, 5);
        ctx.fill();
        ctx.stroke();

        // Callout header
        ctx.fillStyle = color;
        ctx.font = '700 8.5px "Space Mono", "Consolas", monospace';
        ctx.textAlign = "left";
        ctx.fillText(tagText, bx + 7, by + 11);

        // Callout label
        ctx.fillStyle = "#ffffff";
        ctx.font = '600 9.5px "Space Mono", "Consolas", monospace';
        ctx.fillText(labelText, bx + 7, by + 23);

        // Animated progress bar at bottom of callout box
        // Progress is reported telemetry, never a looping timer.
        const prog = Number.isFinite(node.progress) ? Math.max(0, Math.min(1, node.progress)) : 0;
        ctx.fillStyle = "rgba(255,255,255,0.12)";
        ctx.fillRect(bx + 6, by + 28, boxW - 12, 3);
        ctx.fillStyle = color;
        ctx.fillRect(bx + 6, by + 28, (boxW - 12) * prog, 3);
        ctx.restore();
      } else {
        // Compact label with translucent pill backdrop for Bastion gates & Merkle anchors
        const lbl = node.label || node.node_id;
        const lw = Math.max(76, lbl.length * 5.6 + 12);
        const ly = proj.sy - rPx - 8;
        ctx.save();
        ctx.fillStyle = "rgba(8, 10, 14, 0.72)";
        ctx.beginPath();
        ctx.roundRect(proj.sx - lw * 0.5, ly - 10, lw, 14, 4);
        ctx.fill();
        ctx.fillStyle = isBastion && !isListeningBastion ? this._hexAlpha(color, 0.78) : color;
        ctx.font = '600 9.2px "Space Mono", "Consolas", monospace';
        ctx.textAlign = "center";
        ctx.fillText(lbl, proj.sx, ly);
        ctx.restore();
      }
    }

    _drawSentinel(ctx, cam, actor, proj, timeSec) {
      if (proj.cz < 4.5) return; // Clean near-camera fade/cull so Sentinel never clips into lens
      const isSelected = this.selectedKind === "unit" && this.selectedId === actor.unit_id;
      this.screenPickables.push({ id: actor.unit_id, kind: "unit", sx: proj.sx, sy: proj.sy });

      const basis = buildBasis(actor.smoothHeading, actor.lastRight);
      const scale = actor.scale;

      // Determine eye / caste accent color
      let eyeColor = actor.orb_color || this.theme.sentinel_eye || "#ff2a3a";
      if (this.empTripped || actor.state === "EMP_DISABLED") {
        eyeColor = "#555a64";
      } else if (actor.caste === "sanitizer") {
        eyeColor = this.theme.laser_sanitize || "#52e5a8";
      } else if (actor.caste === "harvester" && actor.state !== "ENGAGED_DEFENSE") {
        eyeColor = this.theme.accent || "#ff7a22";
      } else if (actor.caste === "tripwire") {
        eyeColor = this.theme.accent2 || "#ffc08a";
      } else if (actor.orb_color) {
        eyeColor = actor.orb_color;
      }


      // 0. Draw 3D Flight Thruster Wake Trail behind the Sentinel
      if (!this.empTripped && performance.now() - this.lastSnapshotAt < 2500 && actor.trailHistory.length > 2 && actor.state !== "EMP_DISABLED") {
        ctx.save();
        for (let i = 0; i < actor.trailHistory.length - 1; i++) {
          const pA = this.project(actor.trailHistory[i], cam);
          const pB = this.project(actor.trailHistory[i + 1], cam);
          if (!pA || !pB) continue;
          const frac = (i + 1) / actor.trailHistory.length;
          ctx.strokeStyle = this._hexAlpha(eyeColor, frac * (actor.state === "PATROLLING" ? 0.18 : 0.42));
          ctx.lineWidth = Math.max(1.0, Math.min(frac * 0.22 * pB.scale * scale, 6.0));
          ctx.beginPath();
          ctx.moveTo(pA.sx, pA.sy);
          ctx.lineTo(pB.sx, pB.sy);
          ctx.stroke();
        }
        ctx.restore();
      }

      // 1. Volumetric Forward Optical Scan Cone
      if (!this.empTripped && actor.laser_active && actor.state !== "EMP_DISABLED" && performance.now() - this.lastSnapshotAt < 2500) {
        const coneDist = (actor.state === "PATROLLING" ? 3.2 : 5.2) * scale;
        const coneSpread = (actor.state === "PATROLLING" ? 0.85 : 1.35) * scale;
        const nose3d = vec3Add(actor.pos, vec3Scale(basis.fwd, 0.9 * scale));
        const farCenter = vec3Add(actor.pos, vec3Scale(basis.fwd, coneDist));
        const farL = vec3Add(farCenter, vec3Scale(basis.right, coneSpread));
        const farR = vec3Add(farCenter, vec3Scale(basis.right, -coneSpread));

        const pNose = this.project(nose3d, cam);
        const pFL = this.project(farL, cam);
        const pFR = this.project(farR, cam);
        if (pNose && pFL && pFR) {
          ctx.save();
          const cg = ctx.createLinearGradient(pNose.sx, pNose.sy, (pFL.sx + pFR.sx) * 0.5, (pFL.sy + pFR.sy) * 0.5);
          cg.addColorStop(0, this._hexAlpha(eyeColor, actor.state === "PATROLLING" ? 0.22 : 0.38));
          cg.addColorStop(1, "rgba(0,0,0,0)");
          ctx.fillStyle = cg;
          ctx.beginPath();
          ctx.moveTo(pNose.sx, pNose.sy);
          ctx.lineTo(pFL.sx, pFL.sy);
          ctx.lineTo(pFR.sx, pFR.sy);
          ctx.closePath();
          ctx.fill();
          ctx.restore();
        }
      }

      // 2. Draw Active Cutting / Extraction / Sanitization / Defense Laser Beam
      if (!this.empTripped && actor.state !== "EMP_DISABLED" && performance.now() - this.lastSnapshotAt < 2500 && actor.laser_active && actor.laser_target) {
        const tProj = this.project(actor.laser_target, cam);
        if (tProj) {
          let lColor = this.theme.laser_harvest || "#ff9844";
          if (actor.laser_kind === "sanitize") lColor = this.theme.laser_sanitize || "#52e5a8";
          else if (actor.laser_kind === "defense") lColor = this.theme.laser_defense || "#ff1e27";

          ctx.save();
          // Outer laser plasma sheath
          ctx.strokeStyle = this._hexAlpha(lColor, 0.44);
          ctx.lineWidth = Math.max(6.0, Math.min(0.44 * proj.scale, 24.0));
          ctx.beginPath();
          ctx.moveTo(proj.sx, proj.sy);
          ctx.lineTo(tProj.sx, tProj.sy);
          ctx.stroke();

          // Pulsing energy rings along the laser beam
          const pulseU = (timeSec * 3.5) % 1.0;
          const beamPulseX = proj.sx + (tProj.sx - proj.sx) * pulseU;
          const beamPulseY = proj.sy + (tProj.sy - proj.sy) * pulseU;
          ctx.fillStyle = "#ffffff";
          ctx.beginPath();
          ctx.arc(beamPulseX, beamPulseY, Math.max(3.0, Math.min(0.22 * proj.scale, 12.0)), 0, Math.PI * 2);
          ctx.fill();

          // Inner white-hot core beam
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = Math.max(1.8, Math.min(0.14 * proj.scale, 8.0));
          ctx.beginPath();
          ctx.moveTo(proj.sx, proj.sy);
          ctx.lineTo(tProj.sx, tProj.sy);
          ctx.stroke();

          // Impact flare at target
          const impactR = Math.max(6, Math.min((0.65 + Math.sin(timeSec * 28) * 0.25) * tProj.scale, 40));
          ctx.fillStyle = lColor;
          ctx.beginPath();
          ctx.arc(tProj.sx, tProj.sy, impactR, 0, Math.PI * 2);
          ctx.fill();
          ctx.restore();
        }
      }

      // 3. Draw 8..12 Articulated 3D Biomechanical Tentacles & Claws (batched for 60 FPS)
      const baseScale = Math.min(proj.scale * scale, 75.0);
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      const allJoints = [];

      for (let t = 0; t < actor.tentacles.length; t++) {
        const tent = actor.tentacles[t];
        const pts2d = [];
        for (let s = 0; s < tent.points.length; s++) {
          const p2 = this.project(tent.points[s], cam);
          if (!p2) break;
          pts2d.push(p2);
        }
        if (pts2d.length < 2) continue;

        // Outer dark biomechanical armor polyline (1 stroke call per tentacle)
        ctx.strokeStyle = "#121c25";
        ctx.lineWidth = Math.max(1.8, 0.19 * baseScale);
        ctx.beginPath();
        ctx.moveTo(pts2d[0].sx, pts2d[0].sy);
        for (let s = 1; s < pts2d.length; s++) {
          ctx.lineTo(pts2d[s].sx, pts2d[s].sy);
        }
        ctx.stroke();

        // Inner glowing biomechanical conduit polyline (1 stroke call per tentacle)
        ctx.strokeStyle = this._hexAlpha(eyeColor, actor.state === "EMP_DISABLED" ? 0.08 : 0.28);
        ctx.lineWidth = Math.max(1.0, 0.035 * baseScale);
        ctx.beginPath();
        ctx.moveTo(pts2d[0].sx, pts2d[0].sy);
        for (let s = 1; s < pts2d.length; s++) {
          ctx.lineTo(pts2d[s].sx, pts2d[s].sy);
        }
        ctx.stroke();

        for(let s=1;s<pts2d.length;s++) {
          const a=pts2d[s-1],b=pts2d[s], taper=1-s/pts2d.length;
          const x=a.sx+(b.sx-a.sx)*0.18,y=a.sy+(b.sy-a.sy)*0.18;
          const ex=a.sx+(b.sx-a.sx)*0.82,ey=a.sy+(b.sy-a.sy)*0.82;
          ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(ex,ey);
          ctx.lineWidth=Math.max(1.2,(0.09+0.13*taper)*baseScale);ctx.strokeStyle='#536675';ctx.stroke();
          ctx.beginPath();ctx.moveTo(x-0.5,y-0.6);ctx.lineTo(ex-0.5,ey-0.6);
          ctx.lineWidth=Math.max(0.6,0.035*baseScale);ctx.strokeStyle='#a4b5bc';ctx.stroke();
        }
        for (let s = 0; s < pts2d.length - 1; s += 2) {
          const taper = 1.0 - s / pts2d.length;
          allJoints.push({
            sx: pts2d[s].sx,
            sy: pts2d[s].sy,
            r: Math.max(1.1, taper * 0.09 * baseScale),
          });
        }

        // Terminal 3-prong mechanical claw at tentacle tip
        const tip = pts2d[pts2d.length - 1];
        const prev = pts2d[pts2d.length - 2];
        const dirX = tip.sx - prev.sx;
        const dirY = tip.sy - prev.sy;
        const dirLen = Math.hypot(dirX, dirY) || 1;
        const ux = dirX / dirLen;
        const uy = dirY / dirLen;
        const clawLen = Math.max(3.0, Math.min(0.22 * tip.scale * scale, 18.0));
        ctx.strokeStyle = this._hexAlpha(eyeColor, 0.92);
        ctx.lineWidth = 1.25;
        const aperture = actor.carrying_orb ? 0.18 : 0.35 + actor.workBlend * (0.4 + 0.08 * Math.sin(actor.motionTime * 1.8 + t));
        ctx.beginPath();
        ctx.moveTo(tip.sx, tip.sy);
        ctx.lineTo(tip.sx + (ux - uy * aperture) * clawLen, tip.sy + (uy + ux * aperture) * clawLen);
        ctx.moveTo(tip.sx, tip.sy);
        ctx.lineTo(tip.sx + (ux + uy * aperture) * clawLen, tip.sy + (uy - ux * aperture) * clawLen);
        ctx.moveTo(tip.sx, tip.sy);
        ctx.lineTo(tip.sx + ux * clawLen * 1.15, tip.sy + uy * clawLen * 1.15);
        ctx.stroke();
      }

      // Single batched draw call for all tentacle articulation joints on this Sentinel
      if (allJoints.length > 0) {
        ctx.fillStyle = "#1d2b35";
        ctx.beginPath();
        for (let j = 0; j < allJoints.length; j++) {
          const jt = allJoints[j];
          ctx.moveTo(jt.sx + jt.r, jt.sy);
          ctx.arc(jt.sx, jt.sy, jt.r, 0, Math.PI * 2);
        }
        ctx.fill();
      }

      // 4. If Carrying Harvested Data Orb, draw glowing orb in tentacle basket
      if (actor.carrying_orb) {
        const orbWorld = vec3Add(actor.pos, vec3Scale(basis.fwd, -1.15 * scale));
        const orbProj = this.project(orbWorld, cam);
        if (orbProj) {
          const orbR = Math.max(5.5, Math.min(0.65 * orbProj.scale, 28.0));
          const og = ctx.createRadialGradient(orbProj.sx, orbProj.sy, 1, orbProj.sx, orbProj.sy, orbR * 2.2);
          og.addColorStop(0, "#ffffff");
          og.addColorStop(0.45, this.theme.accent2 || "#ffc08a");
          og.addColorStop(1, "rgba(0,0,0,0)");
          ctx.fillStyle = og;
          ctx.beginPath();
          ctx.arc(orbProj.sx, orbProj.sy, orbR * 2.2, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      // Layered ellipsoidal armor. Depth-sort facets for every camera orientation.
      const local=(x,y,z)=>vec3Add(actor.pos,vec3Add(vec3Scale(basis.right,x*scale),vec3Add(vec3Scale(basis.up,y*scale),vec3Scale(basis.fwd,z*scale))));
      const facets=[];
      const rings=[[-0.9,0.30],[-0.55,0.73],[0.1,0.83],[0.65,0.59],[1.12,0.24]];
      for(let r=0;r<rings.length-1;r++) for(let j=0;j<10;j++) {
        const a=j/10*Math.PI*2,b=(j+1)/10*Math.PI*2;
        const vertices=[[r,a],[r,b],[r+1,b],[r+1,a]].map(([k,v])=>this.project(local(Math.cos(v)*rings[k][1],Math.sin(v)*rings[k][1]*0.8,rings[k][0]),cam));
        if(vertices.every(Boolean)) facets.push({p:vertices,shade:Math.round(43+27*Math.max(0,Math.sin((a+b)/2))+r*5),depth:vertices.reduce((s,p)=>s+p.cz,0)/4});
      }
      facets.sort((a,b)=>b.depth-a.depth);
      for(const f of facets) {
        ctx.beginPath();f.p.forEach((p,i)=>i?ctx.lineTo(p.sx,p.sy):ctx.moveTo(p.sx,p.sy));ctx.closePath();
        ctx.fillStyle='rgb('+f.shade+','+(f.shade+12)+','+(f.shade+20)+')';ctx.fill();
        ctx.strokeStyle='#131e28';ctx.lineWidth=1.1;ctx.stroke();
        if(baseScale>10) {const p=f.p[0];ctx.fillStyle='#a3b1ba';ctx.fillRect(p.sx-0.7,p.sy-0.7,1.4,1.4);}
      }
      // Recessed optical bank: bezels, colored lenses and specular highlights.
      const opticalCount = actor.caste==='warden'?3:actor.caste==='cryptarch'?6:4;
      for(let i=0;i<opticalCount;i++) {
        const angle=i/opticalCount*Math.PI*2;
        const p=this.project(local(Math.cos(angle)*0.28,Math.sin(angle)*0.21,1.03),cam);
        if(!p)continue;
        const radius=Math.max(1.2,Math.min(0.105*p.scale*scale,8));
        ctx.fillStyle='#0a111a';ctx.beginPath();ctx.arc(p.sx,p.sy,radius*1.6,0,Math.PI*2);ctx.fill();
        ctx.fillStyle=eyeColor;ctx.beginPath();ctx.arc(p.sx,p.sy,radius,0,Math.PI*2);ctx.fill();
        ctx.fillStyle='#dcebf0';ctx.beginPath();ctx.arc(p.sx-radius*0.25,p.sy-radius*0.3,radius*0.27,0,Math.PI*2);ctx.fill();
      }
      // Instrument housings give each working role a readable silhouette.
      const role = {harvester:[.75,.28],sanitizer:[.62,.42],warden:[.94,.5],tripwire:[1.02,.16],interceptor:[.78,.35],cryptarch:[.6,.6],stalker:[1.08,.24]}[actor.caste] || [.7,.3];
      for(const side of [-1,1]) {
        const a=this.project(local(side*.55,.1,-.3),cam),b=this.project(local(side*role[0],role[1],.25),cam);
        if(a&&b){ctx.beginPath();ctx.moveTo(a.sx,a.sy);ctx.lineTo(b.sx,b.sy);ctx.strokeStyle='#17222c';ctx.lineWidth=Math.max(2,baseScale*.2);ctx.stroke();ctx.strokeStyle='#82939c';ctx.lineWidth=Math.max(1,baseScale*.09);ctx.stroke();ctx.fillStyle=eyeColor;ctx.beginPath();ctx.arc(b.sx,b.sy,Math.max(1,baseScale*.055),0,Math.PI*2);ctx.fill();}
      }
      // Dorsal heat-exchanger ribs and caste identification stripe.
      for(let i=0;i<5;i++) {
        const a=this.project(local(-0.3,0.58,-0.4+i*0.16),cam),b=this.project(local(0.3,0.58,-0.4+i*0.16),cam);
        if(a&&b){ctx.beginPath();ctx.moveTo(a.sx,a.sy);ctx.lineTo(b.sx,b.sy);ctx.strokeStyle=i===0?eyeColor:'#172530';ctx.lineWidth=Math.max(1,baseScale*0.06);ctx.stroke();}
      }
      // 7. Selection Reticle OR Engaged Alpha Callout Tag (no clutter on idle/EMP units)
      const isEngaged = actor.state.startsWith("ENGAGED_") || actor.state === "QUARANTINING";
      const showCallout = isSelected || (isEngaged && (actor.pack_role !== "WINGMAN" || actor.laser_active));
      if (showCallout) {
        const rRet = Math.max(12, Math.min(1.35 * proj.scale * scale, 60.0));
        if (isSelected) {
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 1.6;
          ctx.strokeRect(proj.sx - rRet, proj.sy - rRet, rRet * 2, rRet * 2);
        }

        const packTag = actor.pack_size > 1 ? ` [PACK x${actor.pack_size}]` : "";
        const label = `${actor.unit_id} / ${actor.caste.toUpperCase()} / ${actor.state.replaceAll("_", " ")}${packTag}`;
        ctx.font = '700 9.2px "Space Mono", "Consolas", monospace';
        ctx.textAlign = "center";
        ctx.fillStyle = "rgba(8, 10, 14, 0.85)";
        const tw = label.length * 5.8 + 12;
        ctx.fillRect(proj.sx - tw * 0.5, proj.sy - rRet - 17, tw, 14);
        ctx.fillStyle = isSelected ? "#ffffff" : eyeColor;
        ctx.fillText(label, proj.sx, proj.sy - rRet - 7);
      }
    }

    _hexAlpha(hex, alpha) {
      const clean = (hex || "#ff7a22").replace("#", "");
      if (clean.length !== 6) return `rgba(255, 122, 34, ${alpha})`;
      const r = parseInt(clean.slice(0, 2), 16);
      const g = parseInt(clean.slice(2, 4), 16);
      const b = parseInt(clean.slice(4, 6), 16);
      return `rgba(${r}, ${g}, ${b}, ${alpha.toFixed(3)})`;
    }
  }

  global.OverseerEngine = OverseerEngine;
})(window);
