/**
 * Procedural 3D Matrix Sentinel Biomechanical Actor & 8..12 Tentacle Verlet/IK Solver.
 * Includes 3D Thruster Wake Trail History & Dynamic Claw Articulation.
 * Zero external dependencies. Runs at 60 FPS.
 */

(function (global) {
  "use strict";

  function vec3Add(a, b) { return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]; }
  function vec3Sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
  function vec3Scale(a, s) { return [a[0] * s, a[1] * s, a[2] * s]; }
  function vec3Len(a) { return Math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]); }
  function vec3Norm(a) {
    const l = vec3Len(a);
    return l > 1e-5 ? [a[0] / l, a[1] / l, a[2] / l] : [0, 0, 1];
  }
  function vec3Cross(a, b) {
    return [
      a[1] * b[2] - a[2] * b[1],
      a[2] * b[0] - a[0] * b[2],
      a[0] * b[1] - a[1] * b[0],
    ];
  }
  function vec3Lerp(a, b, t) {
    return [
      a[0] + (b[0] - a[0]) * t,
      a[1] + (b[1] - a[1]) * t,
      a[2] + (b[2] - a[2]) * t,
    ];
  }

  /**
   * Build a horizon-stabilized, singularity-free orthonormal basis {fwd, right, up}
   * from a heading vector (and optional fallback right vector) so Sentinels never
   * suffer 90-degree roll snaps when pitching steeply up or down.
   */
  function buildBasis(heading, fallbackRight) {
    const fwd = vec3Norm(heading);
    const horizLen = Math.hypot(fwd[0], fwd[2]);
    let right;
    if (horizLen > 1e-4) {
      // Cross([0, 1, 0], fwd) = [fwd[2], 0, -fwd[0]] -> strictly horizontal, zero gimbal flip
      right = [fwd[2] / horizLen, 0, -fwd[0] / horizLen];
    } else if (fallbackRight) {
      right = vec3Norm(fallbackRight);
    } else {
      right = [1, 0, 0];
    }
    const up = vec3Norm(vec3Cross(fwd, right));
    return { fwd, right, up };
  }

  class SentinelVisualActor {
    constructor(unitData) {
      this.unit_id = unitData.unit_id;
      this.caste = unitData.caste || "harvester";
      this.tier = unitData.tier || "mk1";
      this.doctrine = unitData.doctrine || "HUNTER-SEEKER";
      this.pack_id = unitData.pack_id || null;
      this.pack_role = unitData.pack_role || "SOLO";
      this.pack_slot = unitData.pack_slot || 0;
      this.pack_size = unitData.pack_size || 1;
      this.tentacleCount = unitData.tentacles || 8;
      this.scale = unitData.scale || 1.0;

      this.pos = (unitData.position || [0, 0, 15]).slice();
      this.targetServerPos = this.pos.slice();
      this.vel = (unitData.velocity || [0, 0, 0]).slice();
      this.heading = vec3Norm((unitData.heading || [0, 0, 1]).slice());
      this.smoothHeading = this.heading.slice();
      this.lastRight = [1, 0, 0];

      this.state = unitData.state || "PATROLLING";
      this.current_task = unitData.current_task || "";
      this.laser_active = !!unitData.laser_active;
      this.laser_target = unitData.laser_target ? unitData.laser_target.slice() : null;
      this.laser_kind = unitData.laser_kind || "none";
      this.carrying_orb = !!unitData.carrying_orb;
      this.orb_color = unitData.orb_color || "#ff7a22";
      this.missions_completed = unitData.missions_completed || 0;
      this.bytes_processed = unitData.bytes_processed || 0;
      this.threats_neutralized = unitData.threats_neutralized || 0;

      this.phaseSeed = Array.from(this.unit_id || "unit").reduce((n, c) => n + c.charCodeAt(0), 0) % 628 / 100;
      this.motionTime = 0;
      this.workBlend = 0;
      this.segmentsPerTentacle = 8;
      this.segmentLength = 0.64 * this.scale;
      this.tentacles = [];
      this.trailHistory = [];
      this._trailSampleTimer = 0;
      this._initTentacles();
    }

    _initTentacles() {
      this.tentacles = [];
      const basis = buildBasis(this.smoothHeading, this.lastRight);
      this.lastRight = basis.right;
      for (let t = 0; t < this.tentacleCount; t++) {
        const angle = (t / this.tentacleCount) * Math.PI * 2;
        const points = [];
        for (let s = 0; s < this.segmentsPerTentacle; s++) {
          const backDist = (s + 1) * this.segmentLength;
          const pt = [
            this.pos[0] - basis.fwd[0] * backDist + Math.cos(angle) * 0.45,
            this.pos[1] - basis.fwd[1] * backDist + Math.sin(angle) * 0.45,
            this.pos[2] - basis.fwd[2] * backDist,
          ];
          points.push(pt);
        }
        this.tentacles.push({ angle, points });
      }
    }

    syncFromServer(data) {
      this.caste = data.caste || this.caste;
      this.tier = data.tier || this.tier;
      this.doctrine = data.doctrine || this.doctrine;
      this.pack_id = data.pack_id || null;
      this.pack_role = data.pack_role || "SOLO";
      this.pack_slot = data.pack_slot || 0;
      this.pack_size = data.pack_size || 1;
      const newTentacles = data.tentacles || 8;
      this.scale = data.scale || 1.0;
      this.segmentLength = 0.64 * this.scale;
      if (newTentacles !== this.tentacleCount) {
        this.tentacleCount = newTentacles;
        this._initTentacles();
      }
      if (data.position) this.targetServerPos = data.position.slice();
      if (data.velocity) this.vel = data.velocity.slice();
      if (data.heading) this.heading = vec3Norm(data.heading.slice());
      this.state = data.state || this.state;
      this.current_task = data.current_task || "";
      this.laser_active = !!data.laser_active;
      this.laser_target = data.laser_target ? data.laser_target.slice() : null;
      this.laser_kind = data.laser_kind || "none";
      this.carrying_orb = !!data.carrying_orb;
      this.orb_color = data.orb_color || this.orb_color;
      this.missions_completed = data.missions_completed || 0;
      this.bytes_processed = data.bytes_processed || 0;
      this.threats_neutralized = data.threats_neutralized || 0;
    }

    stepPhysics(dt, timeSec) {
      if (this.state === "EMP_DISABLED") { this.trailHistory.length = 0; return; }
      dt = Math.max(0, Math.min(dt, 0.05));
      this.motionTime += dt;
      timeSec = this.motionTime;
      const lerpAlpha = Math.min(1.0, dt * 11.5);
      this.pos = vec3Lerp(this.pos, this.targetServerPos, lerpAlpha);

      // Avoid zero-vector singularity if heading reverses 180 degrees
      const dotH =
        this.smoothHeading[0] * this.heading[0] +
        this.smoothHeading[1] * this.heading[1] +
        this.smoothHeading[2] * this.heading[2];
      let startH = this.smoothHeading;
      if (dotH < -0.92) {
        startH = vec3Norm(vec3Add(this.smoothHeading, vec3Scale(this.lastRight, 0.35)));
      }
      this.smoothHeading = vec3Norm(vec3Lerp(startH, this.heading, Math.min(1.0, dt * 8.5)));

      // Record 3D flight wake trail
      this._trailSampleTimer += dt;
      if (this._trailSampleTimer >= 0.04) {
        this._trailSampleTimer = 0;
        this.trailHistory.push(this.pos.slice());
        const maxTrail = this.state === "PATROLLING" ? 10 : 18;
        while (this.trailHistory.length > maxTrail) {
          this.trailHistory.shift();
        }
      }

      const basis = buildBasis(this.smoothHeading, this.lastRight);
      this.lastRight = basis.right;
      const speed = vec3Len(this.vel);
      const engaged =
        this.state === "ENGAGED_HARVEST" ||
        this.state === "ENGAGED_SANITIZE" ||
        this.state === "ENGAGED_DEFENSE" ||
        this.state === "ENGAGED_EXECUTION" ||
        this.state === "QUARANTINING";

      this.workBlend += ((engaged ? 1 : 0) - this.workBlend) * (1 - Math.exp(-dt * 6));
      const docked = this.state === "DOCKED";
      const collarRadius = 0.58 * this.scale;
      const segLen = this.segmentLength;

      for (let t = 0; t < this.tentacles.length; t++) {
        const tent = this.tentacles[t];
        const ang = tent.angle;
        const radialDir = vec3Add(
          vec3Scale(basis.right, Math.cos(ang)),
          vec3Scale(basis.up, Math.sin(ang))
        );

        // Root socket on the collar of the Sentinel carapace (shifts forward when grappling)
        const collarOffset = -0.58;
        const socketPos = vec3Add(
          vec3Add(this.pos, vec3Scale(basis.fwd, collarOffset * this.scale)),
          vec3Scale(radialDir, collarRadius)
        );
        tent.points[0] = socketPos;

        for (let s = 1; s < this.segmentsPerTentacle; s++) {
          const prev = tent.points[s - 1];
          const curr = tent.points[s];
          const ratio = s / this.segmentsPerTentacle;

          let desiredDir;
          if (engaged && this.laser_target) {
            // Matrix Grappling Mode: arch outward around the head, then clamp inward onto the target!
            const toTarget = vec3Norm(vec3Sub(this.laser_target, prev));
            const clampCurve = ratio < 0.55 ? Math.sin(ratio * Math.PI) * 0.85 : -0.38;
            const writhe = Math.cos(timeSec * 2.2 + t * 0.9 - s * 0.6) * 0.045;
            desiredDir = vec3Norm(
              vec3Add(toTarget, vec3Scale(radialDir, clampCurve + writhe))
            );
          } else if (engaged) {
            // Local analysis: symmetric tool cradle, with restrained servo travel.
            desiredDir = vec3Norm(vec3Add(vec3Scale(basis.fwd, 0.3 + ratio),
              vec3Scale(radialDir, (ratio < 0.55 ? 1.1 : -0.6) + Math.sin(timeSec * 1.8 + t * 0.8 - s * 0.4) * 0.08 * ratio)));
          } else if (this.carrying_orb) {
            // Basket cage around the carried Warrant Orb behind the torso
            const cagePull = ratio > 0.45 ? -0.32 : 0.42;
            const trailDir = vec3Scale(basis.fwd, -1.0);
            desiredDir = vec3Norm(
              vec3Add(trailDir, vec3Scale(radialDir, cagePull))
            );
          } else {
            // Trail behind the Sentinel with biomechanical sinusoidal swimming wave
            const waveFreq = (this.state === "VECTORING" ? 6.2 : 3.8) + speed * 0.16;
            const waveAmp = (docked ? 0 : 0.035 + Math.min(0.22, speed * 0.012)) * ratio;
            const wave = Math.sin(timeSec * waveFreq - s * 0.72 + t * 0.85 + this.phaseSeed) * waveAmp;
            const trailDir = vec3Scale(basis.fwd, -1.0);
            desiredDir = vec3Norm(
              vec3Add(
                trailDir,
                vec3Scale(radialDir, (this.state === "VECTORING" ? 0.11 : 0.18) + wave)
              )
            );
          }

          const idealPt = vec3Add(prev, vec3Scale(desiredDir, segLen));
          const blended = vec3Lerp(curr, idealPt, Math.min(1.0, dt * (15.5 - s * 1.05)));
          const diff = vec3Norm(vec3Sub(blended, prev));
          tent.points[s] = vec3Add(prev, vec3Scale(diff, segLen));
        }
      }
    }
  }

  global.SentinelMesh = {
    SentinelVisualActor,
    buildBasis,
    vec3Add,
    vec3Sub,
    vec3Scale,
    vec3Len,
    vec3Norm,
    vec3Lerp,
  };
})(window);
