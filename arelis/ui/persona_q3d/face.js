// Face layer for the Qt Quick 3D avatar: a port of the neck, head, eye, jaw and face-morph drive in
// ../persona_face/web/anim.js (blinks, gaze, head springs, micro-expressions, lip-sync visemes from the
// speaking level). Body clips stay with the mixer; the light terms (uAnim) stay with the look track,
// which can read level and flow from the returned api.
//
// Use from QML:  import "face.js" as Face
//   const f = Face.create(ellahNode, { seed: 12345 })
//   f.setState('speaking'); f.setSpeaking(0.8); f.update(dtSeconds)   // once per frame, after the clips
// Every morph name is applied on every MorphTarget copy with that objectName (balsam repeats the list
// per submesh: 888 on the body). Weights are only written when they move by more than EPS.
// Not ported: the CMU gesture-track head term (HDK 0.02, MHD stays 0) and the uAnim light write.
.pragma library

const EPS = 1e-4;

const MODES = ['idle', 'listening', 'thinking', 'speaking', 'done'];
const ALIAS = { talking: 'speaking' };

// per-state targets; blended by state weights every frame
const P = {
  //             breath/s depth  lean   tilt   look-up sway  flow  rim   shimmer gaze-range saccade-gap  smile  browUp browIn press
  idle:      { br: 0.23, bd: 1.0, lean: 0.0,   tilt: 0.0,   up: 0.0,   sway: 1.0, flow: 1.0, rim: 1.0,  sh: 0, gr: 1.0,  gap: 1.0, smile: 0.05, bu: 0.0,  bi: 0.0,  pr: 0.0 },
  listening: { br: 0.22, bd: 0.85, lean: 0.08,  tilt: 0.13,  up: 0.0,   sway: 0.5, flow: 1.1, rim: 1.38, sh: 0, gr: 0.25, gap: 1.5, smile: 0.12, bu: 0.12, bi: 0.10, pr: 0.0 },
  thinking:  { br: 0.21, bd: 0.95, lean: -0.01, tilt: -0.03, up: 0.16,  sway: 0.6, flow: 2.3, rim: 1.08, sh: 1, gr: 0.45, gap: 1.6, smile: 0.0,  bu: 0.0,  bi: 0.05, pr: 0.14 },
  speaking:  { br: 0.26, bd: 0.75, lean: 0.02, tilt: 0.0,   up: 0.0,   sway: 0.8, flow: 1.25, rim: 1.12, sh: 0, gr: 0.4, gap: 0.8, smile: 0.09, bu: 0.0,  bi: 0.0,  pr: 0.0 },
  done:      { br: 0.2, bd: 1.15, lean: -0.012, tilt: 0.0, up: -0.02, sway: 0.55, flow: 0.8, rim: 1.0, sh: 0, gr: 0.6, gap: 1.4, smile: 0.16, bu: 0.0,  bi: 0.0,  pr: 0.0 },
};
const KEYS = Object.keys(P.idle);

function qmul(a, b) { return [a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3],
  a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2], a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1],
  a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0]]; }
function qeulerYXZ(x, y, z) {   // same as three.js Euler(x, y, z, 'YXZ'), as [w, x, y, z]
  const c1 = Math.cos(x / 2), c2 = Math.cos(y / 2), c3 = Math.cos(z / 2), s1 = Math.sin(x / 2), s2 = Math.sin(y / 2), s3 = Math.sin(z / 2);
  return [c1 * c2 * c3 + s1 * s2 * s3, s1 * c2 * c3 + c1 * s2 * s3, c1 * s2 * c3 - s1 * c2 * s3, c1 * c2 * s3 - s1 * s2 * c3]; }
// the QML engine (V4) has no Array.flatMap or Object.fromEntries
const flatMap = (a, fn) => a.reduce((o, x) => o.concat(fn(x)), []);
const fromEntries = (ps) => { const o = {}; for (const [k, v] of ps) o[k] = v; return o; };
const qarr = (q) => [q.scalar, q.x, q.y, q.z];
// One step of a critically damped spring toward `to`, solved exactly rather than with an Euler step, so a long
// frame (the mixer passes up to 0.1 s after a stall) lands where the spring would have been instead of overshooting.
// An Euler step with om * dt near 1 throws the head past its target and, held there, rings out of range.
function spring(o, x, v, to, om, dt) { const d = o[x] - to, j = o[v] + om * d, e = Math.exp(-om * dt);
  o[x] = to + (d + j * dt) * e; o[v] = (o[v] - om * j * dt) * e; }
function walk(n, f) { f(n); const c = n.children || []; for (let i = 0; i < c.length; i++) walk(c[i], f); }

function create(root, opts) {
  opts = opts || {};
  const eps = opts.eps === undefined ? EPS : opts.eps;
  let aseed = opts.seed === undefined ? null : (opts.seed >>> 0);
  const rnd = () => aseed === null ? Math.random() : ((aseed = (aseed * 1664525 + 1013904223) >>> 0) / 4294967296);
  const face = {};
  const nodes = {}, models = [];
  walk(root, (n) => { if (n.objectName && n.objectName.startsWith('CC_Base_')) nodes[n.objectName] = n; if (n.morphTargets !== undefined && models.indexOf(n) < 0) models.push(n); });
  // The face owns these bones (anim-mixer.js KEEP_BASE strips their clip tracks in v14k). Clips in the
  // balsam Timelines still carry them, so every update puts the ones not driven below back to rest first.
  const KEEP = /^CC_Base_(NeckTwist0[12]|Head|FacialBone|JawRoot|.*Eye|Tongue.*|Teeth.*|UpperJaw)$/;
  const keep = Object.keys(nodes).filter((n) => KEEP.test(n)).map((n) => [nodes[n], nodes[n].position, nodes[n].rotation]);
  const R = {};
  for (const n of ['NeckTwist01', 'Head', 'L_Eye', 'R_Eye', 'JawRoot']) {
    const b = nodes['CC_Base_' + n]; if (!b) continue;
    const pw = qarr(b.parent.sceneRotation);
    R[n] = { b, q0: qarr(b.rotation), pw, pwi: [pw[0], -pw[1], -pw[2], -pw[3]] };
  }
  // world-space rotation (pitch x, yaw y, roll z) applied on top of the rest pose
  const rot = (n, x, y, z) => { const r = R[n]; if (!r) return;
    const o = qmul(qmul(qmul(r.pwi, qeulerYXZ(x, y, z)), r.pw), r.q0); r.b.rotation = Qt.quaternion(o[0], o[1], o[2], o[3]); };

  // layered noise, roughly -1..1, never repeats in practice
  const seeds = {}; const S = (k) => seeds[k] ?? (seeds[k] = rnd() * 100);
  const N = (t, k) => { const s = S(k);
    return 0.5 * Math.sin(t * 0.31 + s) + 0.3 * Math.sin(t * 0.737 + s * 2.1) + 0.15 * Math.sin(t * 1.513 + s * 3.3) + 0.05 * Math.sin(t * 3.17 + s * 5.7); };
  const ease = (x) => x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x);

  // ---- state weights (two cascaded lags -> smooth S-curve, ~0.45 s) ----
  let mode = 'idle'; const w1 = {}, w = {}; for (const m of MODES) { w1[m] = w[m] = m === 'idle' ? 1 : 0; }
  let settleT = 99, prevMode = 'idle';
  const lvl = { target: 0, fast: 0, med: 0, slow: 0, nod: 0 };
  const api = {
    setState(m) { m = ALIAS[m] || m; if (!MODES.includes(m) || m === mode) return; prevMode = mode; mode = m;
      if (m === 'done') settleT = 0; if (m !== 'speaking') lvl.target = 0; },
    setLevel(v) { lvl.target = Math.max(0, Math.min(1, +v || 0)); },
    get state() { return mode; },
  };

  // ---- breathing ----
  let bph = rnd(), bDepth = 1, sighIn = 18 + rnd() * 14, sigh = 0, bRate = 1, bHold = 0, sighK = 1;
  // ---- gaze ----
  const gz = { tx: 0, ty: 0, ex: 0, ey: 0, sx: 0, sy: 0, st: 1, dur: 0.05, next: 0.6, hx: 0, hy: 0, hvx: 0, hvy: 0, mx: 0, my: 0, mnext: 0.3 };
  // ---- blinks ----
  const bl = { next: 1.5 + rnd() * 2.5, t: -1, dbl: false, shape: 0 };
  // ---- micro-expressions ----
  const MICRO = [
    { m: { Mouth_Smile_L: 0.22, Mouth_Smile_R: 0.16, Cheek_Raise_L: 0.08, Cheek_Raise_R: 0.05 } },   // small asymmetric smile
    { m: { Brow_Raise_Inner_L: 0.45, Brow_Raise_Inner_R: 0.5, Brow_Raise_Outer_L: 0.35, Brow_Raise_Outer_R: 0.28 } },        // soft interest
    { m: { Mouth_Press_L: 0.18, Mouth_Press_R: 0.14 } },                                              // lips press
    { m: { Mouth_Smile_R: 0.12, Mouth_Dimple_R: 0.12, Brow_Raise_Outer_R: 0.1 } },                    // one-sided half smile
    { m: { Nose_Nostril_Dilate_L: 0.25, Nose_Nostril_Dilate_R: 0.25, Brow_Drop_L: 0.06 } },
    { m: { Brow_Raise_Outer_L: 0.42, Brow_Raise_Inner_L: 0.15, Brow_Compress_R: 0.2 } },                // one brow up (quizzical)
    { m: { Brow_Compress_L: 0.35, Brow_Compress_R: 0.32, Brow_Drop_L: 0.12, Brow_Drop_R: 0.1 } },     // brief knit
    { m: { Mouth_Smile_L: 0.16, Mouth_Dimple_L: 0.16, Mouth_Pull_Upper_L: 0.05, Cheek_Raise_L: 0.08, Mouth_Tighten_R: 0.06 } },   // v9: slight asymmetric smirk (left)
    { m: { Mouth_Tighten_L: 0.12, Mouth_Tighten_R: 0.1, Mouth_Shrug_Lower: 0.12, Mouth_Frown_L: 0.05, Mouth_Frown_R: 0.04 } },   // v9: 'hm' corners in          // breath through the nose
  ];
  const micro = { next: 2 + rnd() * 3, t: -1, cur: null, a: 0.4, s: 1, r: 0.9 };
  // ---- speech ----
  // Mouth shapes built from the model's own CC morphs (lips do the work; the jaw only helps).
  const SH = {
    rest: {},
    a:  { V_Open: 0.8, Jaw_Open: 0.45, V_Lip_Open: 0.3, Mouth_Shrug_Upper: 0.1, jaw: 0.6 },
    e:  { V_Wide: 0.55, Mouth_Stretch_L: 0.28, Mouth_Stretch_R: 0.24, Mouth_Smile_L: 0.12, Mouth_Smile_R: 0.1, V_Lip_Open: 0.2, Jaw_Open: 0.07, jaw: 0.3 },
    i:  { V_Wide: 0.7, Mouth_Stretch_L: 0.38, Mouth_Stretch_R: 0.34, Mouth_Smile_Sharp_L: 0.15, Mouth_Smile_Sharp_R: 0.13, Jaw_Open: 0.03, jaw: 0.15 },
    o:  { V_Tight_O: 0.65, Mouth_Funnel_Up_L: 0.35, Mouth_Funnel_Up_R: 0.35, Mouth_Funnel_Down_L: 0.3, Mouth_Funnel_Down_R: 0.3, Jaw_Open: 0.1, jaw: 0.35 },
    u:  { V_Tight_O: 0.5, Mouth_Pucker_Up_L: 0.55, Mouth_Pucker_Up_R: 0.55, Mouth_Pucker_Down_L: 0.5, Mouth_Pucker_Down_R: 0.5, Mouth_Funnel_Up_L: 0.2, Mouth_Funnel_Up_R: 0.2, jaw: 0.1 },
    uh: { V_Lip_Open: 0.45, V_Open: 0.15, Jaw_Open: 0.08, jaw: 0.35 },
    mbp: { V_Explosive: 0.55, Cheek_Puff_L: 0.05, Cheek_Puff_R: 0.05, Mouth_Press_L: 0.45, Mouth_Press_R: 0.45, Mouth_Roll_In_Upper_L: 0.2, Mouth_Roll_In_Upper_R: 0.2, Mouth_Roll_In_Lower_L: 0.25, Mouth_Roll_In_Lower_R: 0.25, Mouth_Close: 0.2, jaw: 0 },
    fv: { V_Dental_Lip: 0.85, Mouth_Roll_In_Lower_L: 0.55, Mouth_Roll_In_Lower_R: 0.55, Mouth_Up_Upper_L: 0.15, Mouth_Up_Upper_R: 0.15, jaw: 0.08 },
    ch: { V_Affricate: 0.6, Mouth_Funnel_Up_L: 0.2, Mouth_Funnel_Up_R: 0.2, jaw: 0.1 },
    st: { V_Tight: 0.45, V_Wide: 0.2, Mouth_Stretch_L: 0.1, Mouth_Stretch_R: 0.1, jaw: 0.08 },
  };
  for (const s of Object.values(SH)) delete s.Mouth_Drop_Lower_L;
  const VOW = ['a', 'e', 'i', 'o', 'u', 'uh'], VOWP = [0.26, 0.2, 0.14, 0.15, 0.1, 0.15];
  const CONS = [['mbp', 0.24], ['fv', 0.12], ['ch', 0.1], ['st', 0.16], [null, 0.38]];
  const pick = (arr, pr) => { let x = rnd(), i = 0; for (; i < arr.length - 1; i++) { x -= pr[i]; if (x < 0) break; } return arr[i]; };
  const MOUTH = [...new Set(flatMap(Object.values(SH), (s) => Object.keys(s)).filter((n) => n !== 'jaw'))];
  const VIS = MOUTH;
  const sp = { cur: fromEntries(MOUTH.map((n) => [n, 0])), tgt: {}, jaw: 0, lastL: 0, age: 1, peak: 0, falling: true, lmax: 0, lmin: 9, cons: null, cdur: 0.06, vow: 'a', stress: 0, stressT: 9 };
  // phrase / gesture / event state
  const hs = { x: 0, vx: 0, y: 0, vy: 0, z: 0, vz: 0, s: 0, vs: 0 };
  const ph = { on: false, t: 0, off: 9, warm: 0, warmT: 0, lift: 9, nod: 9, nodK: 0, tiltK: 0 };
  const ev = { sighAt: 3 + rnd() * 6, stretchAt: 6 + rnd() * 5, st: -1, side: 1, stretchDur: 3.6 };
  // event-based drift: holds a value, then glides (min-jerk) to a new one at irregular times
  const drifts = {}; let dtNow = 0;
  const D = (k, gmin = 2, gmax = 7, dmin = 0.8, dmax = 2.4) => { let d = drifts[k];
    if (!d) d = drifts[k] = { v: 0, from: 0, to: 0, u: 1, dur: 1, next: rnd() * gmax };
    d.next -= dtNow; if (d.next <= 0) { d.from = d.v; d.to = (rnd() * 2 - 1) * (rnd() < 0.3 ? 1 : 0.55); d.u = 0; d.dur = dmin + rnd() * (dmax - dmin); d.next = d.dur + gmin + rnd() * (gmax - gmin); }
    if (d.u < 1) { d.u = Math.min(1, d.u + dtNow / d.dur); const u = d.u; d.v = d.from + (d.to - d.from) * u * u * u * (10 - 15 * u + 6 * u * u); }
    return d.v; };
  // v8: continuous gesture track: real time segments of CMU 18_08 (arms per-frame retargeted + fitted, spine/head high-passed rotations), 30 fps
  let mseed = 9173; const mrnd = () => ((mseed = (mseed * 1664525 + 1013904223) >>> 0) / 4294967296);   // v8b: own RNG so the face timeline matches v7
  const HDK = 0.02;   // v8b: mocap head damped (was 0.4)   // v8b: mocap head damped (was 0.4)
  const MHD = [0, 0, 0];   // v8: mocap head (high-passed), additive on the head
  const pulse = (x, a, r) => x < 0 ? 0 : x < a ? ease(x / a) : Math.exp(-(x - a) / r);   // attack then exp release
  const morphs = {};   // name -> value, written to every face mesh that has it
  const FACE_NAMES = new Set([...VIS, 'Eye_Squint_L', 'Eye_Squint_R', 'Eye_Wide_L', 'Eye_Wide_R', 'Cheek_Raise_L', 'Cheek_Raise_R', 'Eye_Blink_L', 'Eye_Blink_R', 'Eye_L_Look_Down', 'Eye_R_Look_Down', ...flatMap(MICRO, (u) => Object.keys(u.m)),
    'Mouth_Smile_L', 'Mouth_Smile_R', 'Brow_Raise_Inner_L', 'Brow_Raise_Inner_R', 'Brow_Compress_L', 'Brow_Compress_R', 'Mouth_Press_L', 'Mouth_Press_R', 'Brow_Raise_Outer_L', 'Brow_Raise_Outer_R',
    'Nose_Crease_L', 'Nose_Crease_R', 'Nose_Sneer_L', 'Nose_Sneer_R', 'Nose_Nostril_Raise_L', 'Nose_Nostril_Raise_R', 'Mouth_Dimple_L', 'Mouth_Dimple_R', 'Mouth_Tighten_L', 'Mouth_Tighten_R', 'Cheek_Puff_L', 'Cheek_Puff_R']);   // v9: + richer expression keys
  const targets = {};   // name -> every MorphTarget copy with that name, across all models and submeshes
  let copies = 0;
  for (const m of models) { const ts = m.morphTargets; for (let i = 0; i < ts.length; i++) { const n = ts[i].objectName;
    if (!FACE_NAMES.has(n)) continue; (targets[n] = targets[n] || []).push(ts[i]); copies++; } }
  const applied = {};
  api.faceNames = [...FACE_NAMES];
  api.targets = targets;
  api.stats = { models: models.length, names: Object.keys(targets).length, copies, writes: 0, bones: Object.keys(R).length };
  api.setSpeaking = (v) => api.setLevel(v);
  api.holdBlink = (v) => { face.hold = v === null || v === undefined ? undefined : +v; };
  api.morph = (n) => applied[n] || 0;

  let T = 0;
  Object.defineProperty(api, 'level', { get: () => lvl.med || 0 });   // smoothed voice level for the look track

  function update(dt) {
    T += dt; if (api.freezeT !== undefined) T = api.freezeT; const t = T; const dtc = api.freezeClocks ? 0 : dt;   // v13b test hook: freezeClocks stops breath, weight shift, posture, wrist drift and finger fidget clocks (contact fitting)   // v10 test hook: freezeT
    // weights
    const k = 1 - Math.exp(-dt / 0.11);
    for (const m of MODES) { w1[m] += ((m === mode ? 1 : 0) - w1[m]) * k; w[m] += (w1[m] - w[m]) * k; }
    const p = {}; for (const key of KEYS) { let s = 0; for (const m of MODES) s += w[m] * P[m][key]; p[key] = s; }
    // voice level: fast attack, slower release; slow follower for body/glow
    const lt = lvl.target * w.speaking;
    lvl.fast += (lt - lvl.fast) * (1 - Math.exp(-dt / (lt > lvl.fast ? 0.03 : 0.08)));
    lvl.med += (lvl.fast - lvl.med) * (1 - Math.exp(-dt / 0.15));
    lvl.slow += (lt - lvl.slow) * (1 - Math.exp(-dt / 0.6));
    lvl.nod += (Math.max(0, lvl.med - lvl.slow) - lvl.nod) * (1 - Math.exp(-dt / 0.18));   // phrase emphasis, smoothed (no syllable jitter)
    settleT += dt; const settle = settleT < 3 ? Math.sin(Math.PI * ease(settleT / 2.2)) * (settleT < 2.2 ? 1 : 0) : 0;   // done: one slow exhale + nod

    for (const [nd, p0, r0] of keep) { nd.position = p0; nd.rotation = r0; }
    dtNow = dt;
    // ---- speech timing: syllable onsets from the level envelope, stress, phrase boundaries ----
    const L = lvl.fast, dL = L - sp.lastL; sp.lastL = L; sp.age += dt; sp.stressT += dt;
    if (dL < -0.001) { sp.falling = true; sp.lmin = Math.min(sp.lmin, L); } else if (!sp.falling) sp.lmax = Math.max(sp.lmax, L);
    const onset = (sp.falling && dL > 0.001 && sp.lmax - sp.lmin > 0.08 && sp.age > 0.08) || (L > 0.25 && sp.age > 0.32);
    if (onset) { sp.lmax = L; sp.lmin = 9; }
    if (sp.falling && dL > 0.001 && !onset) sp.falling = false;
    let syl = false;
    if (onset && w.speaking > 0.3) { syl = true; sp.falling = false; sp.age = 0;
      sp.cons = pick(CONS.map((c) => c[0]), CONS.map((c) => c[1])); sp.cdur = sp.cons === 'mbp' ? 0.075 : 0.06;
      let v; do v = pick(VOW, VOWP); while (v === sp.vow && rnd() < 0.6); sp.vow = v;
      // stress: first syllable of a phrase often, then ~1 in 4, never two in a row too fast
      if (sp.stressT > 0.45 && (ph.t < 0.25 ? rnd() < 0.7 : rnd() < 0.27)) { sp.stressT = 0; sp.stress = 0.6 + rnd() * 0.4; } }
    const stress = pulse(sp.stressT, 0.08, 0.32) * sp.stress;
    // phrases (hysteresis on the slow level)
    ph.quiet = L < 0.08 ? (ph.quiet || 0) + dt : 0;
    if (!ph.on && L > 0.15 && w.speaking > 0.4) { ph.on = true; ph.t = 0; ph.lift = ph.off > 0.6 ? 0 : 9;
      ph.warm = rnd() < 0.35 ? 0.6 + rnd() * 0.4 : 0;   // some phrases are said with a warm smile
    }
    if (ph.on && (ph.quiet > 0.16 || w.speaking < 0.4)) { ph.on = false; ph.off = 0; ph.nod = 0;
      ph.nodK = rnd() < 0.55 ? (0.6 + rnd() * 0.5) : 0; ph.tiltK = ph.nodK ? (rnd() < 0.3 ? (rnd() < 0.5 ? -1 : 1) * 0.5 : 0) : (rnd() < 0.5 ? -1 : 1) * (0.6 + rnd() * 0.4); }
    if (ph.on) ph.t += dt; ph.off += dt; ph.lift += dt; ph.nod += dt;
    ph.warmT += ((ph.on ? ph.warm : 0) * w.speaking - ph.warmT) * (1 - Math.exp(-dt / 0.35));
    const lift = pulse(ph.lift, 0.35, 0.9) * w.speaking;                     // posture lift at phrase start
    const nodE = ph.nod < 1.1 ? Math.sin(Math.PI * Math.min(1, ph.nod / 0.75)) * (ph.nod < 0.75 ? 1 : 0) : 0;   // phrase-end nod / tilt
    // idle events: deeper sighs and a neck stretch / head roll, at irregular times
    const calm = w.idle + w.done;
    ev.stretchAt -= dt;
    if (ev.st < 0 && ev.stretchAt <= 0 && calm > 0.7) { ev.st = 0; ev.side = rnd() < 0.5 ? -1 : 1; ev.stretchDur = 3.2 + rnd() * 1.2; ev.k = 0.8 + rnd() * 0.3; }
    let stR = 0, stP = 0, stE = 0;
    if (ev.st >= 0) { ev.st += dt; const u = ev.st / ev.stretchDur;
      if (u >= 1) { ev.st = -1; ev.stretchAt = 8 + rnd() * 22; }
      else { const m = Math.pow(Math.sin(Math.PI * u), 1.2) * 0.2 * ev.k * calm, th = -Math.PI / 2 + u * Math.PI * 0.8;   // side -> forward -> part way over
        stR = m * Math.sin(th) * ev.side; stP = m * Math.cos(th) * 0.75; stE = Math.sin(Math.PI * u); } }
    // ---- breath (asymmetric: inhale 40 %, exhale 60 %; depth varies per breath; an occasional sigh) ----
    const rate = p.br * bRate * (1 + 0.08 * N(t * 0.4, 'br'));
    const prevPh = bph; if (bHold > 0) bHold -= dt; else bph += dtc * rate;   // v4: occasional pause after an exhale
    ev.sighAt -= dt;
    if (Math.floor(bph) !== Math.floor(prevPh)) { bDepth = 0.6 + rnd() * 0.75; bRate = 0.72 + rnd() * 0.6;   // v4: every breath its own depth and length
      if (calm > 0.6 && rnd() < 0.22) bHold = 0.3 + rnd() * rnd() * 2.2;   // ... and sometimes a still pause
      if (ev.sighAt <= 0 && calm > 0.6) { sigh = 1; sighK = 0.7 + rnd() * 0.6; bHold = 0.2 + rnd() * 0.9; ev.sighAt = 7 + rnd() * rnd() * 22; } else sigh = 0; }
    if (sigh) bph += -dt * rate * 0.4;   // a sigh is slower
    const x = bph % 1; let b = x < 0.4 ? ease(x / 0.4) : 1 - ease((x - 0.4) / 0.6);
    b *= p.bd * bDepth * (1 + 2.1 * sigh * sighK) + 0.6 * settle;
    const sg2 = sigh ? b : 0;   // v4: sigh lifts shoulders + head and drops them on the way out
    // speaking: breath catches between phrases (shallower, a bit irregular)
    b += 0.15 * w.speaking * N(t * 1.7, 'spb');
    // ---- gaze: eyes saccade (fast min-jerk), head follows with a lag, eyes counter-rotate (VOR) ----
    gz.next -= dt;
    if (gz.next <= 0) {
      // attention point: held for a while; most saccades are small re-fixations around it, some move it
      const range = p.gr, base = { x: p.up * -0.9, y: w.thinking * 0.22 };
      gz.att = gz.att || { x: 0, y: 0, t: 0 }; gz.att.t -= 1;
      if (gz.att.t <= 0 || rnd() < 0.12) { const far = rnd() < 0.35;
        gz.att = { x: base.x + (rnd() * 2 - 1) * (far ? 0.12 : 0.05) * range, y: base.y + (rnd() * 2 - 1) * (far ? 0.3 : 0.1) * range, t: 2 + Math.floor(rnd() * 4) };
        if (w.listening > 0.5 || w.idle > 0.5 && rnd() < 0.4) { gz.att.x *= 0.3; gz.att.y *= 0.3; } }   // back to the viewer
      let ny = gz.att.y + (rnd() * 2 - 1) * 0.035, nx = gz.att.x + (rnd() * 2 - 1) * 0.025;
      if (w.speaking > 0.5 && rnd() < 0.18) ny += (rnd() < 0.5 ? -1 : 1) * 0.18;   // glance away mid-sentence
      const amp = Math.hypot(ny - gz.ty, nx - gz.tx);
      gz.sx = gz.ex; gz.sy = gz.ey; gz.tx = nx; gz.ty = ny; gz.st = 0; gz.dur = Math.min(0.06, 0.03 + amp * 0.1); gz.hd = 0.06 + rnd() * 0.08;
      gz.next = Math.max(0.3, Math.min(2, (0.3 + rnd() * 1.4) * p.gap));
      if (amp > 0.22 && rnd() < 0.45 && bl.t < 0) bl.next = Math.min(bl.next, 0.02);   // blinks ride big saccades
    }
    gz.st += dt; const g = ease(Math.min(1, gz.st / gz.dur)), mj = g * g * (3 - 2 * g);
    const gx = gz.sx + (gz.tx - gz.sx) * mj, gy = gz.sy + (gz.ty - gz.sy) * mj; gz.ex = gx; gz.ey = gy;
    // micro-saccades
    gz.mnext -= dt; if (gz.mnext <= 0) { gz.mx = (rnd() - 0.5) * 0.012; gz.my = (rnd() - 0.5) * 0.016; gz.mnext = 0.25 + rnd() * 0.6; }
    // head: critically damped spring toward ~55 % of gaze yaw / 40 % of pitch, starts after the eyes
    if (gz.st >= (gz.hd || 0)) { gz.htY = gz.ty * 0.55; gz.htX = gz.tx * 0.4; }   // head starts 60-140 ms after the eyes
    const hY = gz.htY || 0, hX = gz.htX || 0;
    const om = 6.5;
    spring(gz, 'hy', 'hvy', hY, om, dt); spring(gz, 'hx', 'hvx', hX, om, dt);
    // v4: speech head motion is a critically damped spring kicked by syllables (velocity impulses), never a position step.
    //     v3 added 0.03*stress straight to the head pitch with an 80 ms attack -> ~0.6 deg/frame jumps that made the
    //     alpha-tested back hair seen through the see-through neck crawl (the 5-7 s neck flicker).
    if (syl) { const a = Math.min(1, L * 1.4) * w.speaking, st0 = sp.stressT === 0;
      hs.vx += (st0 ? 0.55 * sp.stress : 0.16 + 0.12 * rnd()) * a;                 // nod down on each syllable, bigger on stress
      hs.vz += (st0 ? (rnd() < 0.5 ? -1 : 1) * 0.35 : (rnd() - 0.5) * 0.18) * a;   // small tilt, a clear one on stress
      hs.vy += (rnd() - 0.5) * 0.16 * a; }
    { const om3 = 11, om4 = 8; spring(hs, 'x', 'vx', 0, om3, dt); spring(hs, 'z', 'vz', 0, om4, dt); spring(hs, 'y', 'vy', 0, om4, dt);
      const tgt = w.speaking * (0.03 * lvl.nod + 0.008 * N(t * 0.9, 'nod') + 0.07 * ph.nodK * nodE - 0.03 * lift) + 0.03 * sg2 * (1 - 2 * (bph % 1 > 0.4));
      spring(hs, 's', 'vs', tgt, 7, dt); }
    const hy = hs.y + gz.hy + 0.04 * D('hy', 2, 6) + 0.012 * N(t * 0.37, 'hy') + 0.005 * N(t * 1.3, 'hy2');
    const hx = gz.hx + 0.022 * D('hx', 2, 7) + 0.008 * N(t * 0.29, 'hx') + 0.004 * N(t * 1.1, 'hx2') + 0.008 * b - p.up * 0.35 + 0.05 * settle
             + hs.s + hs.x + stP;   // beats on stress, nod at phrase end
    const hz = hs.z + p.tilt + 0.026 * D('hz', 3, 9) + 0.008 * N(t * 0.21, 'hz') + 0.07 * ph.tiltK * nodE * w.speaking + stR;
    const hyL = hy, hxL = hx;   // m1 mixer: no scripted spine carries part of the turn any more
    rot('NeckTwist01', hxL * 0.3 - 0.008 * b, hyL * 0.35, hz * 0.35);
    rot('Head', hxL * 0.7 - p.lean * 0.6 + 0.02 * b + HDK * MHD[0], hyL * 0.65 + HDK * MHD[1], hz * 0.65 + HDK * MHD[2]);   // v8: + mocap head (high-passed, additive)
    // eyes = gaze minus what the head already did
    const eyY = Math.max(-0.4, Math.min(0.4, gy - gz.hy)) + gz.my, eyX = Math.max(-0.25, Math.min(0.25, gx - gz.hx)) + gz.mx;
    rot('L_Eye', eyX, eyY, 0); rot('R_Eye', eyX, eyY * 0.97, 0);

    // ---- blinks: 2-6 s, ~15 % doubles; close 70 ms, open 120 ms; right lid trails by 12 ms ----
    bl.next -= dt;
    if (bl.t < 0 && bl.next <= 0) bl.t = 0;
    let bL = 0, bR = 0;
    if (bl.t >= 0) { bl.t += dt; const lid = (s) => s < 0 ? 0 : s < 0.07 ? ease(s / 0.07) : s < 0.1 ? 1 : s < 0.22 ? 1 - ease((s - 0.1) / 0.12) : 0;
      bL = lid(bl.t); bR = lid(bl.t - 0.012);
      if (bl.t > 0.24) { bl.t = -1;
        if (!bl.second && rnd() < 0.15) { bl.second = true; bl.next = 0.06; }   // double blink
        else { bl.second = false; bl.next = (2 + rnd() * 4) * (1 - 0.15 * w.speaking + 0.2 * w.thinking); } } }
    const lidDown = Math.max(0, eyX) * 0.9;   // upper lid follows the eye down
    morphs.Eye_Blink_L = Math.min(1, bL + lidDown * 0.5 + 0.03 * settle + 0.45 * stE); morphs.Eye_Blink_R = Math.min(1, bR + lidDown * 0.5 + 0.03 * settle + 0.42 * stE);
    if (face.hold !== undefined) morphs.Eye_Blink_L = morphs.Eye_Blink_R = face.hold;

    // ---- micro-expressions (attack / sustain / release envelopes) + state baselines ----
    for (const n of FACE_NAMES) if (!n.startsWith('Eye_')) morphs[n] = 0;
    micro.next -= dt;
    if (micro.t < 0 && micro.next <= 0) { micro.cur = MICRO[Math.floor(rnd() * MICRO.length)]; micro.t = 0; micro.a = 0.35 + rnd() * 0.3; micro.s = 0.5 + rnd() * 1.2; micro.r = 0.7 + rnd() * 0.6; micro.k = 0.9 + rnd() * 0.8; }
    if (micro.t >= 0) { micro.t += dt; const m = micro.t;
      const env = m < micro.a ? ease(m / micro.a) : m < micro.a + micro.s ? 1 : 1 - ease((m - micro.a - micro.s) / micro.r);
      const scale = micro.k * (1 - 0.6 * w.speaking);
      for (const [n, v] of Object.entries(micro.cur.m)) morphs[n] = (morphs[n] || 0) + v * env * scale;
      if (m > micro.a + micro.s + micro.r) { micro.t = -1; micro.next = (1.5 + rnd() * rnd() * 9) * (w.listening > 0.5 ? 0.7 : 1); } }
    morphs.Mouth_Smile_L += p.smile * 1.05 + 0.02 * N(t * 0.2, 'sm'); morphs.Mouth_Smile_R += p.smile * 0.9;
    morphs.Brow_Raise_Inner_L += p.bi + p.bu * 0.5; morphs.Brow_Raise_Inner_R += p.bi * 1.1 + p.bu * 0.5;
    morphs.Brow_Raise_Outer_L += p.bu; morphs.Brow_Raise_Outer_R += p.bu * 0.85;
    morphs.Brow_Compress_L = (morphs.Brow_Compress_L || 0) + p.pr * 0.6 * (1 + 0.3 * N(t * 0.5, 'bc')); morphs.Brow_Compress_R = (morphs.Brow_Compress_R || 0) + p.pr * 0.5;
    morphs.Mouth_Press_L += p.pr; morphs.Mouth_Press_R += p.pr * 0.85;
    // speaking: brows lift on emphasis
    const emph = Math.max(0, lvl.nod - 0.05) * w.speaking * 1.5;
    morphs.Brow_Raise_Inner_L += emph * 0.5 + 0.6 * stress; morphs.Brow_Raise_Inner_R += emph * 0.55 + 0.65 * stress;
    morphs.Brow_Raise_Outer_L += emph * 0.35 + 0.55 * stress; morphs.Brow_Raise_Outer_R += emph * 0.3 + 0.48 * stress;
    morphs.Eye_Wide_L = 0.12 * stress; morphs.Eye_Wide_R = 0.1 * stress;
    // warm phrases: smile reaches the eyes (cheek raise + slight squint); small resting smile always
    const warm = ph.warmT + 0.25 * w.listening;
    morphs.Mouth_Smile_L += 0.08 + 0.22 * warm; morphs.Mouth_Smile_R += 0.065 + 0.19 * warm;
    morphs.Cheek_Raise_L += 0.03 + 0.3 * warm; morphs.Cheek_Raise_R += 0.025 + 0.26 * warm;
    morphs.Eye_Squint_L = 0.04 + 0.22 * warm + 0.06 * w.thinking; morphs.Eye_Squint_R = 0.04 + 0.2 * warm + 0.08 * w.thinking;

    // ---- speech: consonant shape then vowel shape per syllable, from CC lip morphs; each morph smoothed on its own
    //      (coarticulation: the next vowel starts forming inside the consonant, shapes overlap). Jaw only assists.
    const env = Math.min(1, L * 1.3), act = Math.min(1, lvl.slow * 4) * w.speaking;
    for (const n of MOUTH) sp.tgt[n] = 0;
    const inCons = sp.cons && sp.age < sp.cdur;
    let jawW = 0;
    if (inCons) { const C = SH[sp.cons]; for (const [n, x] of Object.entries(C)) if (n !== 'jaw') sp.tgt[n] += x * act; jawW = C.jaw * act; }
    const vS = SH[sp.vow], vw = inCons ? (sp.cons === 'mbp' ? 0.15 : 0.4) : 1, vk = Math.pow(env, 0.7);   // shapes hold even on quiet syllables
    for (const [n, x] of Object.entries(vS)) if (n !== 'jaw') sp.tgt[n] += x * vk * vw;
    jawW = inCons ? jawW + vS.jaw * env * 0.2 : vS.jaw * env;
    if (api.force) { for (const n of MOUTH) sp.tgt[n] = 0; for (const [n, x] of Object.entries(SH[api.force])) if (n !== 'jaw') sp.tgt[n] = x; jawW = SH[api.force].jaw; }   // test hook: hold one mouth shape
    // lips at rest between phrases: closed, relaxed
    for (const n of MOUTH) { const tau = sp.tgt[n] > sp.cur[n] ? 0.04 : 0.07; sp.cur[n] += (sp.tgt[n] - sp.cur[n]) * (1 - Math.exp(-dt / tau)); morphs[n] = (morphs[n] || 0) + sp.cur[n]; }
    sp.jaw += (jawW * (0.9 + 0.1 * N(t * 2.3, 'jaw')) - sp.jaw) * (1 - Math.exp(-dt / 0.06));
    rot('JawRoot', sp.jaw * 0.3 + 0.004 * settle, 0, 0);   // v4: jaw carries more of the opening (lip morphs unchanged)
    // v4: cheeks ride the jaw and the wide vowels (cheek morphs only; mouth shapes untouched)
    const wide = (sp.cur.V_Wide || 0);
    morphs.Cheek_Raise_L += 0.35 * wide + 0.18 * sp.jaw + 0.15 * stress * w.speaking; morphs.Cheek_Raise_R += 0.32 * wide + 0.16 * sp.jaw + 0.13 * stress * w.speaking;

    // v9: richer expression layer (morph weights only, all subtle)
    { const smL = Math.max(0, morphs.Mouth_Smile_L - 0.08), smR = Math.max(0, morphs.Mouth_Smile_R - 0.065);   // smile above the resting one
      // Duchenne: a real smile reaches the eyes (cheek raise + lower-lid squint), the nose creases a touch, corners dimple
      morphs.Cheek_Raise_L += 0.35 * smL; morphs.Cheek_Raise_R += 0.32 * smR;
      morphs.Eye_Squint_L += 0.45 * smL; morphs.Eye_Squint_R += 0.4 * smR;
      morphs.Nose_Crease_L += 0.12 * smL; morphs.Nose_Crease_R += 0.1 * smR;
      morphs.Mouth_Dimple_L += 0.3 * smL; morphs.Mouth_Dimple_R += 0.26 * smR;
      // nose micro-moves on stressed syllables (nostrils lift, a trace of sneer on one side)
      morphs.Nose_Nostril_Raise_L += 0.14 * stress * w.speaking; morphs.Nose_Nostril_Raise_R += 0.12 * stress * w.speaking;
      morphs.Nose_Sneer_L += 0.04 * stress * w.speaking;
      // thinking: lid tension + lips tighten slightly, a little asymmetric
      morphs.Eye_Squint_L += 0.08 * w.thinking; morphs.Eye_Squint_R += 0.12 * w.thinking;
      morphs.Mouth_Tighten_L += 0.12 * w.thinking; morphs.Mouth_Tighten_R += 0.08 * w.thinking;
      if (api.forceExpr) { for (const n of FACE_NAMES) if (!n.startsWith('Eye_Blink') && !n.startsWith('Eye_L_') && !n.startsWith('Eye_R_')) morphs[n] = 0; for (const [n, x] of Object.entries(api.forceExpr)) morphs[n] = x; } }   // test hook (expressions sheet)

    let writes = 0;
    for (const n in targets) { const v = Math.max(0, Math.min(1, morphs[n] || 0));
      if (Math.abs(v - (applied[n] === undefined ? -1 : applied[n])) <= eps) continue;
      applied[n] = v; const ts = targets[n]; for (let i = 0; i < ts.length; i++) ts[i].weight = v; writes += ts.length; }
    api.stats.writes = writes;
    api.flow = p.flow; api.breath = b;   // for the look track (aether's uFlow and glow breath)
    return p.flow;
  }
  api.update = update;
  return api;
}
