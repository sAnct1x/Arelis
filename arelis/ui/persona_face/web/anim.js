// Motion layer (animation job, on top of the locked pass 14 look). Moves bones, morphs and a few
// shader multipliers only; shapes and shading are untouched (all multipliers are neutral at rest).
//
// Design notes
// - Every bone offset is a world-space rotation conjugated into the bone's rest frame, so axes
//   don't depend on how the rig's bones are oriented.
// - Motion is layered noise (several incommensurate sines per channel, per-channel seeds), so
//   nothing visibly loops; small left/right asymmetries are deliberate.
// - States blend through weights filtered by two cascaded first-order lags (~0.45 s S-curve).

const MODES = ['idle', 'listening', 'thinking', 'speaking', 'done'];
const ALIAS = { talking: 'speaking' };

// per-state targets; blended by state weights every frame
const P = {
  //             breath/s depth  lean   tilt   look-up sway  flow  rim   shimmer gaze-range saccade-gap  smile  browUp browIn press
  idle:      { br: 0.23, bd: 1.0, lean: 0.0,   tilt: 0.0,   up: 0.0,   sway: 1.0, flow: 1.0, rim: 1.0,  sh: 0, gr: 1.0,  gap: 1.0, smile: 0.05, bu: 0.0,  bi: 0.0,  pr: 0.0 },
  listening: { br: 0.22, bd: 0.85, lean: 0.045, tilt: 0.055, up: 0.0,   sway: 0.5, flow: 1.1, rim: 1.38, sh: 0, gr: 0.25, gap: 1.5, smile: 0.12, bu: 0.12, bi: 0.10, pr: 0.0 },
  thinking:  { br: 0.21, bd: 0.95, lean: -0.01, tilt: -0.03, up: 0.16,  sway: 0.6, flow: 2.3, rim: 1.08, sh: 1, gr: 0.45, gap: 1.6, smile: 0.0,  bu: 0.0,  bi: 0.05, pr: 0.14 },
  speaking:  { br: 0.26, bd: 0.75, lean: 0.02, tilt: 0.0,   up: 0.0,   sway: 0.8, flow: 1.25, rim: 1.12, sh: 0, gr: 0.4, gap: 0.8, smile: 0.09, bu: 0.0,  bi: 0.0,  pr: 0.0 },
  done:      { br: 0.2, bd: 1.15, lean: -0.012, tilt: 0.0, up: -0.02, sway: 0.55, flow: 0.8, rim: 1.0, sh: 0, gr: 0.6, gap: 1.4, smile: 0.16, bu: 0.0,  bi: 0.0,  pr: 0.0 },
};
const KEYS = Object.keys(P.idle);

export function createAnimator(THREE, root, face, uAnim, opts = {}) {
  /* vr4: own seeded RNG for the choreography (?aseed=, test renders only), so particle sampling changes no longer reshuffle her idle poses */
  const QS = typeof location !== 'undefined' ? new URLSearchParams(location.search) : null; let aseed = QS && QS.has('aseed') ? (+QS.get('aseed') >>> 0) : null;
  const rnd = () => aseed === null ? Math.random() : ((aseed = (aseed * 1664525 + 1013904223) >>> 0) / 4294967296);
  root.updateMatrixWorld(true);
  const bone = (n) => root.getObjectByName(n);
  const R = {};
  for (const n of ['Hip', 'Waist', 'Spine01', 'Spine02', 'NeckTwist01', 'NeckTwist02', 'Head', 'L_Clavicle', 'R_Clavicle',
                   'L_Upperarm', 'R_Upperarm', 'L_Forearm', 'R_Forearm', 'L_Hand', 'R_Hand', 'L_Eye', 'R_Eye', 'JawRoot',
                   ...['L', 'R'].flatMap((s) => [s + '_Thumb1']), ...['L', 'R'].flatMap((s) => ['Index', 'Mid', 'Ring', 'Pinky'].flatMap((f) => [1, 2, 3].map((k) => s + '_' + f + k)))]) {
    const b = bone('CC_Base_' + n); if (!b) continue;
    const pw = b.parent.getWorldQuaternion(new THREE.Quaternion());
    R[n] = { b, q0: b.quaternion.clone(), pw, pwi: pw.clone().invert() };
  }
  const e = new THREE.Euler(), q = new THREE.Quaternion();
  const V3 = () => new THREE.Vector3(), Q = () => new THREE.Quaternion();
  const wpos = (b) => b.getWorldPosition(V3()), wq = (b) => b.getWorldQuaternion(Q());
  // ---- legs: analytic two-bone IK so the feet stay planted while the pelvis shifts ----
  const hip = R.Hip, hipP0 = hip ? hip.b.position.clone() : null;
  const hipPS = hip ? hip.b.parent.getWorldScale(V3()).x : 1;
  const LEGS = ['L', 'R'].map((s) => { const th = bone('CC_Base_' + s + '_Thigh'), ca = bone('CC_Base_' + s + '_Calf'), ft = bone('CC_Base_' + s + '_Foot');
    if (!th || !ca || !ft) return null;
    const H = wpos(th), K = wpos(ca), A = wpos(ft), d = A.clone().sub(H).normalize();
    let pole = K.clone().sub(H).sub(d.clone().multiplyScalar(K.clone().sub(H).dot(d)));
    pole = pole.length() > 0.004 ? pole.normalize() : new THREE.Vector3(0, 0, 1); if (pole.z < 0) pole.set(0, 0, 1);
    return { th, ca, ft, A, L1: K.distanceTo(H), L2: A.distanceTo(K), pole, td: K.clone().sub(H).normalize(), cd: A.clone().sub(K).normalize(),
      tq: wq(th), cq: wq(ca), fq: wq(ft) }; }).filter(Boolean);
  const setW = (b, qw) => { b.quaternion.copy(wq(b.parent).invert().multiply(qw)); };
  const tv = V3(), tv2 = V3(), qa = Q();
  function solveLegs() {
    for (const L of LEGS) { const H = wpos(L.th), d = tv.copy(L.A).sub(H); let dist = d.length(); d.normalize();
      dist = Math.min(dist, L.L1 + L.L2 - 1e-4);
      const a = (L.L1 * L.L1 - L.L2 * L.L2 + dist * dist) / (2 * dist), h = Math.sqrt(Math.max(0, L.L1 * L.L1 - a * a));
      const pole = tv2.copy(L.pole).sub(d.clone().multiplyScalar(L.pole.dot(d))).normalize();
      const K = H.clone().add(d.clone().multiplyScalar(a)).add(pole.multiplyScalar(h));
      setW(L.th, qa.setFromUnitVectors(L.td, K.clone().sub(H).normalize()).multiply(L.tq));
      setW(L.ca, qa.setFromUnitVectors(L.cd, L.A.clone().sub(K).normalize()).multiply(L.cq));
      setW(L.ft, L.fq); } }
  const legSlack = () => Math.max(0, ...LEGS.map((L) => wpos(L.th).distanceTo(L.A) - (L.L1 + L.L2 - 0.003)));
  // ---- fingers: micro-curl axis per finger, sign measured so + always curls toward the palm ----
  const FING = [], THUMB = [];
  for (const s of ['L', 'R']) { const hb = bone('CC_Base_' + s + '_Hand'); if (!hb || !R[s + '_Index1']) continue;
    const across = wpos(bone('CC_Base_' + s + '_Index1')).sub(wpos(bone('CC_Base_' + s + '_Pinky1'))).normalize();
    const hpos = wpos(hb), thumb = wpos(bone('CC_Base_' + s + '_Thumb3'));
    const nrm = V3().crossVectors(across, wpos(bone('CC_Base_' + s + '_Mid1')).sub(hpos).normalize()).normalize(); if (nrm.dot(thumb.sub(hpos)) < 0) nrm.negate();
    for (const f of ['Index', 'Mid', 'Ring', 'Pinky']) { const tip = bone('CC_Base_' + s + '_' + f + '3'), b1 = R[s + '_' + f + '1'];
      const score = () => { root.updateMatrixWorld(true); return wpos(tip).sub(wpos(hb)).dot(nrm); };
      const segs = [1, 2, 3].map((k) => { const r = R[s + '_' + f + k]; return { r, ax: across.clone().applyQuaternion(wq(r.b).invert()).normalize() }; });
      const s0 = score(); const q0 = b1.b.quaternion.clone(); b1.b.quaternion.multiply(Q().setFromAxisAngle(segs[0].ax, 0.1)); const sg = score() > s0 ? 1 : -1; b1.b.quaternion.copy(q0);
      let sax = null, ssg = 0; if (f !== 'Mid') { sax = nrm.clone().applyQuaternion(wq(b1.b).invert()).normalize(); const m1 = wpos(bone('CC_Base_' + s + '_Mid3')); const d0 = wpos(tip).distanceTo(m1);
        b1.b.quaternion.multiply(Q().setFromAxisAngle(sax, 0.1)); root.updateMatrixWorld(true); ssg = wpos(tip).distanceTo(m1) < d0 ? 1 : -1; b1.b.quaternion.copy(q0); root.updateMatrixWorld(true); }   // v10: spread axis, + closes toward the middle finger
      FING.push({ s, f, sg, segs, sax, ssg }); }
    { const t1 = R[s + '_Thumb1'], t3 = bone('CC_Base_' + s + '_Thumb3'), i1 = bone('CC_Base_' + s + '_Index1');   // v9d: thumb abduction axis (palm normal), + = away from the index
      if (t1 && t3 && i1) { const ax = nrm.clone().applyQuaternion(wq(t1.b).invert()).normalize(); const d0 = wpos(t3).distanceTo(wpos(i1)); const q0 = t1.b.quaternion.clone();
        t1.b.quaternion.multiply(Q().setFromAxisAngle(ax, 0.1)); root.updateMatrixWorld(true); const sg = wpos(t3).distanceTo(wpos(i1)) > d0 ? 1 : -1; t1.b.quaternion.copy(q0); root.updateMatrixWorld(true); THUMB.push({ s, r: t1, ax, sg }); } } }
  root.updateMatrixWorld(true);
  // world-space rotation (pitch x, yaw y, roll z) applied on top of the rest pose
  const rot = (n, x, y, z) => { const r = R[n]; if (!r) return;
    q.setFromEuler(e.set(x, y, z, 'YXZ')); r.b.quaternion.copy(r.pwi).multiply(q).multiply(r.pw).multiply(r.q0); };

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
    setState(m) { m = ALIAS[m] || m; if (m === 'walk') { walkOn = true; return; } walkOn = false; if (!MODES.includes(m) || m === mode) return; prevMode = mode; mode = m;
      if (m === 'done') settleT = 0; if (m !== 'speaking') lvl.target = 0; },
    setLevel(v) { lvl.target = Math.max(0, Math.min(1, +v || 0)); },
    get state() { return mode; },
  };

  // ---- breathing ----
  let bph = rnd(), bDepth = 1, sighIn = 18 + rnd() * 14, sigh = 0, bRate = 1, bHold = 0, sighK = 1;
  // ---- body state ----
  const ws = { cur: 0, from: 0, to: rnd() < 0.5 ? 0.6 : -0.6, u: 1, dur: 2, next: 2 + rnd() * 3 };
  const fol = { x: 0, y: 0 }, arm = { pw: 0, pa: 0, L: { x: 0, v: 0 }, R: { x: 0, v: 0 } };
  const fc = { L: { t: -1, next: 6 + rnd() * 8, amp: 0.1, dir: 1 }, R: { t: -1, next: 10 + rnd() * 8, amp: 0.1, dir: 1 } };   // v10: rare relaxed flex
  const wst = { L: { t: 4 + rnd() * 6, x: 0, z: 0, gx: 0, gz: 0, vx: 0, vz: 0 }, R: { t: 7 + rnd() * 6, x: 0, z: 0, gx: 0, gz: 0, vx: 0, vz: 0 } };   // v10: occasional wrist settle
  let FFB = null;   // v15: finger output filter state
  const MF = { L: [0, 0, 0, 0, 0], R: [0, 0, 0, 0, 0] };   // v10: Mixamo finger track (per-finger curl deltas + thumb)
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
  const MOUTH = [...new Set(Object.values(SH).flatMap((s) => Object.keys(s)).filter((n) => n !== 'jaw'))];
  const VIS = MOUTH;
  const sp = { cur: Object.fromEntries(MOUTH.map((n) => [n, 0])), tgt: {}, jaw: 0, lastL: 0, age: 1, peak: 0, falling: true, lmax: 0, lmin: 9, cons: null, cdur: 0.06, vow: 'a', stress: 0, stressT: 9 };
  // phrase / gesture / event state
  const hs = { x: 0, vx: 0, y: 0, vy: 0, z: 0, vz: 0, s: 0, vs: 0 };
  const ph = { on: false, t: 0, off: 9, warm: 0, warmT: 0, lift: 9, nod: 9, nodK: 0, tiltK: 0 };
  const gest = { L: { a: 0, v: 0, tgt: 0, beat: 0, k: 1, open: 0, key: 'lowFwd', Q: {}, QV: {} }, R: { a: 0, v: 0, tgt: 0, beat: 0, k: 1, open: 0, key: 'lowFwd', Q: {}, QV: {} }, last: 'R', lastKey: '' };
  const ev = { sighAt: 3 + rnd() * 6, stretchAt: 6 + rnd() * 5, st: -1, side: 1, stretchDur: 3.6 };
  // event-based drift: holds a value, then glides (min-jerk) to a new one at irregular times
  const drifts = {}; let dtNow = 0;
  const D = (k, gmin = 2, gmax = 7, dmin = 0.8, dmax = 2.4) => { let d = drifts[k];
    if (!d) d = drifts[k] = { v: 0, from: 0, to: 0, u: 1, dur: 1, next: rnd() * gmax };
    d.next -= dtNow; if (d.next <= 0) { d.from = d.v; d.to = (rnd() * 2 - 1) * (rnd() < 0.3 ? 1 : 0.55); d.u = 0; d.dur = dmin + rnd() * (dmax - dmin); d.next = d.dur + gmin + rnd() * (gmax - gmin); }
    if (d.u < 1) { d.u = Math.min(1, d.u + dtNow / d.dur); const u = d.u; d.v = d.from + (d.to - d.from) * u * u * u * (10 - 15 * u + 6 * u * u); }
    return d.v; };
  const HX = 0, HZ = 0;   // wrist offsets during a gesture (tuned by eye)
  // v7: speaking gesture key poses retargeted from CMU mocap 18_08 'conversation - explain with hand gestures' (subject A),
  // apex frames at 9.17 s (lowFwd), 13.97 s (lowOpen), 0.33 s (midFwd), 1.5 s (both); mirrored for the other arm, fitted on the rig (mocap/tools/fit7.js).
  const GP = {
    lowFwd: { L: {ux: 0.188, uy: -0.548, uz: -0.105, fx: -0.884, fy: 0.325, fz: 0.092, hx: 1.209, hy: -0.149, hz: 0.821}, R: {ux: 0.084, uy: -1.195, uz: -0.249, fx: -0.552, fy: 0.474, fz: 0.526, hx: -0.373, hy: 0.057, hz: 0.07} },
    lowOpen: { L: {ux: 0, uy: 0.024, uz: 0.35, fx: -0.35, fy: 0.287, fz: -0.35, hx: 0.063, hy: 0.087, hz: 0.35}, R: {ux: 0, uy: 0.036, uz: 0.302, fx: -0.35, fy: -0.192, fz: 0.072, hx: 0.35, hy: 0.585, hz: 0.315} },
    midFwd: { L: {ux: -0.129, uy: -0.324, uz: -0.032, fx: -0.851, fy: -0.032, fz: 0.35, hx: -0.637, hy: 0, hz: 0}, R: {ux: 0.054, uy: 0.461, uz: -0.178, fx: -1.251, fy: 0.051, fz: -0.744, hx: -0.942, hy: 1.521, hz: -0.856} },
    both: { L: {ux: 0.075, uy: -1.202, uz: -0.199, fx: 0.457, fy: -0.383, fz: 1.048, hx: 0.947, hy: 0.693, hz: -0.884}, R: {ux: 0.008, uy: 0.109, uz: 0.005, fx: -0.786, fy: -0.567, fz: 0.094, hx: 0.762, hy: 0.132, hz: 0.82} }
  };
  const GKEYS = ['lowFwd', 'lowOpen', 'midFwd'];
  // v8: continuous gesture track: real time segments of CMU 18_08 (arms per-frame retargeted + fitted, spine/head high-passed rotations), 30 fps
  let TRK = null; try { fetch(new URL(new URLSearchParams(location.search).get('track') === 'cmu' ? './gesture-track.json' : './gesture-track-mix.json', import.meta.url)).then((r) => r.json()).then((j) => { TRK = j; api.trackReady = true; console.info('[avatar] clip loaded name=gesture-track-mix segs=' + j.segs.length); }).catch(() => {}); } catch (e) {}
const _eA = new THREE.Vector3(), _eB = new THREE.Vector3(), _eAx = new THREE.Vector3(), _eQ1 = new THREE.Quaternion(), _eQ2 = new THREE.Quaternion(), _eQ3 = new THREE.Quaternion();   // v13 end-on wrist
  const mo = { slots: [], last: -1, wasOn: false };
  let mseed = 9173; const mrnd = () => ((mseed = (mseed * 1664525 + 1013904223) >>> 0) / 4294967296);   // v8b: own RNG so the face timeline matches v7
  const SPK = 0.05;   // v8b: mocap spine damped (was 0.6; it carries the head)
  const HDK = 0.02;   // v8b: mocap head damped (was 0.4)   // v8b: mocap head damped (was 0.4)
  const K9N = ['ux', 'uy', 'uz', 'fx', 'fy', 'fz', 'hx', 'hy', 'hz'];
  const MQ = { L: {}, R: {} }, MSP = [0, 0, 0], MHD = [0, 0, 0];
  const moStart = (t0) => { let i, m; do { i = Math.floor(mrnd() * TRK.segs.length); m = mrnd() < 0.5; } while (i === mo.lastI && TRK.segs.length > 1); mo.lastI = i; mo.last = i + (m ? 'm' : ''); console.info('[avatar] clip play name=gesture seg=' + i + ' mirror=' + m);   /* v15: never the same segment twice in a row (Agreeing chained into itself) */   // v8b: random span + mirror, never the same pair twice in a row
    const len = TRK.segs[i].n / TRK.fps; for (const sl of mo.slots) sl.tg = 0;
    mo.slots.push({ i, m, t: Math.min(t0 ?? 0, Math.max(0, len - 2.6)) + mrnd() * Math.max(0, len - 2.2 - (t0 ?? 0)), w: 0, v: 0, tg: 1 }); };   /* v15: short segments (Agreeing, 1.9 s) start at their head */
  const moSample = (sl, key, j) => { if (sl.m) { if (key === 'L' || key === 'R') key = key === 'L' ? 'R' : 'L'; else if (j > 0) return -moSample({ ...sl, m: false }, key, j); } const S = TRK.segs[sl.i], f = Math.min(S.n - 1.001, sl.t * TRK.fps), i0 = Math.floor(f), u = f - i0; return S[key][i0][j] * (1 - u) + S[key][i0 + 1][j] * u; };
  const pulse = (x, a, r) => x < 0 ? 0 : x < a ? ease(x / a) : Math.exp(-(x - a) / r);   // attack then exp release

  // v5: idle arm poses (world-space offsets per arm; y/z mirrored for the right arm). u* upper arm, f* forearm, h* hand.
  const ZP = { ux: 0, uy: 0, uz: 0, fx: 0, fy: 0, fz: 0, hx: 0, hy: 0, hz: 0, c: 0, cIndex: 0, cMid: 0, cRing: 0, cPinky: 0, tb: 0, sp: 0, hipw: 0 };   // v10: + sp (finger spread, - = more spread); v9d: per-finger curl offsets + thumb abduction
  // v6: arm poses retargeted from real mocap (CMU Graphics Lab Motion Capture Database, subject 137 trial 37 "Sexy Lady Wait", hands on hips at 4-5 s;
  // BVH conversion by B. Hahne / cgspeed). Bone directions (upper arm, forearm, hand) in the actor's chest frame were mapped onto ellah's
  // arm lengths and fitted to the CC rig (tools/fitM.js). Hand-tuned cross/touch/clasp/shift poses were dropped.
  const POSE = {
    hip:     { L: { ux: -0.117, uy: -0.684, uz: 0.354, fx: -0.923, fy: 0.925, fz: -0.573, hx: -0.088, hy: -1.6, hz: 1.522, tb: 0, c: 0, cIndex: 0, cMid: 0, cRing: 0, cPinky: 0, sp: 0, hipw: 1 }, R: null },   // v13e: mesh-distance refit (scratch/hipfit13q.js): less thumb wrap (tb 1.335 -> 1.136), hand 0.9 cm further out   /* v14: curls/thumb now come from the Blender pose (BLQ) */
    hipRfit: { L: null, R: { ux: 0.592, uy: -1.847, uz: -0.086, fx: -1.362, fy: 0.536, fz: -0.346, hx: -0.184, hy: -0.865, hz: 0.968, tb: 1.099, c: -0.019, cIndex: 0.317, cMid: 0.52, cRing: 0.725, cPinky: 1.427, sp: -0.25, hipw: 1 } },
    hipBoth: { L: { ux: 0.447, uy: -0.552, uz: 0.266, fx: -1.164, fy: 0.936, fz: -0.991, hx: -0.288, hy: -1.43, hz: 1.484, tb: 0, c: 0, cIndex: 0, cMid: 0, cRing: 0, cPinky: 0, sp: 0, hipw: 1 }, R: { ux: 0.447, uy: -0.552, uz: 0.266, fx: -1.164, fy: 0.936, fz: -0.991, hx: -0.288, hy: -1.43, hz: 1.484, tb: 0, c: 0, cIndex: 0, cMid: 0, cRing: 0, cPinky: 0, sp: 0, hipw: 1 } },   // v13e: mesh-distance refit, R = L mirrored (tb 1.959 -> 1.169)   /* v14: curls/thumb now come from the Blender pose (BLQ) */
  };
  POSE.hipBothR = POSE.hipBoth;
  api.poseTab = POSE;   // v10 test hook (contact sweep)
  /* v14: hand-set hip pose from Blender (scratch/bl14/pose.py, candidate f2): world-space rotation deltas from rest, three axes [x,y,z,w] */
  const BLH = {"L_Upperarm":[0.08478,0.14178,-0.16482,0.97239],"R_Upperarm":[0.08478,-0.14178,0.16482,0.97239],"L_Forearm":[0.16792,0.03797,0.75658,-0.63084],"R_Forearm":[0.16792,-0.03797,-0.75658,-0.63084],"L_Hand":[0.225,0.44072,0.31845,-0.80853],"R_Hand":[0.225,-0.44072,-0.31845,-0.80853],"L_Pinky1":[0.19307,0.51,0.44716,-0.70899],"R_Pinky1":[0.19307,-0.51,-0.44716,-0.70899],"L_Pinky2":[0.14146,0.54669,0.54823,-0.6169],"R_Pinky2":[0.14146,-0.54669,-0.54823,-0.6169],"L_Pinky3":[0.12938,0.54754,0.57708,-0.59199],"R_Pinky3":[0.12938,-0.54754,-0.57708,-0.59199],"L_Ring1":[0.18731,0.51234,0.45504,-0.70382],"R_Ring1":[0.18731,-0.51234,-0.45504,-0.70382],"L_Ring2":[0.14602,0.54691,0.54974,-0.61429],"R_Ring2":[0.14602,-0.54691,-0.54974,-0.61429],"L_Ring3":[0.13395,0.54755,0.57864,-0.58943],"R_Ring3":[0.13395,-0.54755,-0.57864,-0.58943],"L_Mid1":[0.17076,0.51892,0.4782,-0.68767],"R_Mid1":[0.17076,-0.51892,-0.4782,-0.68767],"L_Mid2":[0.1033,0.55939,0.59429,-0.56854],"R_Mid2":[0.1033,-0.55939,-0.59429,-0.56854],"L_Mid3":[0.09135,0.55907,0.6212,-0.54148],"R_Mid3":[0.09135,-0.55907,-0.6212,-0.54148],"L_Index1":[0.17834,0.52015,0.47928,-0.68405],"R_Index1":[0.17834,-0.52015,-0.47928,-0.68405],"L_Index2":[0.10483,0.55852,0.59185,-0.57165],"R_Index2":[0.10483,-0.55852,-0.59185,-0.57165],"L_Index3":[0.09286,0.5583,0.61886,-0.54469],"R_Index3":[0.09286,-0.5583,-0.61886,-0.54469],"L_Thumb1":[0.69537,0.56445,0.22537,-0.38349],"R_Thumb1":[0.69537,-0.56445,-0.22537,-0.38349],"L_Thumb2":[0.75025,0.59454,0.1645,-0.23788],"R_Thumb2":[0.75025,-0.59454,-0.1645,-0.23788],"L_Thumb3":[0.75025,0.59454,0.1645,-0.23788],"R_Thumb3":[0.75025,-0.59454,-0.1645,-0.23788]};
  const BLW = {}, BLQ = {};
  { root.updateMatrixWorld(true); const Dq = (n) => BLH[n] ? new THREE.Quaternion(...BLH[n]) : new THREE.Quaternion();
    let SKM = null; root.traverse((m) => { if (!SKM && m.isSkinnedMesh && /Body/i.test(m.name)) SKM = m; });   /* bind (rest A-pose) world rotations: the live skeleton is already arms-down at init */
    const rw = (b) => { const i = SKM ? SKM.skeleton.bones.indexOf(b) : -1; if (i < 0) return b.getWorldQuaternion(new THREE.Quaternion()); const M = SKM.matrixWorld.clone().multiply(SKM.bindMatrix).multiply(SKM.skeleton.boneInverses[i].clone().invert()); const p = new THREE.Vector3(), q = new THREE.Quaternion(), sc = new THREE.Vector3(); M.decompose(p, q, sc); return q; };
    const rp = (b) => { const i = SKM.skeleton.bones.indexOf(b); return new THREE.Vector3().setFromMatrixPosition(SKM.matrixWorld.clone().multiply(SKM.bindMatrix).multiply(SKM.skeleton.boneInverses[i].clone().invert())); };
    const tw = (n) => { const b = bone('CC_Base_' + n); return b ? Dq(n).multiply(rw(b)) : null; };
    const P0 = rw(bone('CC_Base_Pelvis') || bone('CC_Base_Hip')).invert();
    for (const s of ['L', 'R']) { for (const n of ['Upperarm', 'Forearm', 'Hand']) { const t = tw(s + '_' + n); if (t) BLW[s + '_' + n] = P0.clone().multiply(t); }
      for (const f of ['Thumb', 'Index', 'Mid', 'Ring', 'Pinky']) for (const k of [1, 2, 3]) { const n = s + '_' + f + k, pn = k === 1 ? s + '_Hand' : s + '_' + f + (k - 1); const a = tw(pn), b = tw(n); if (a && b) BLQ[n] = a.invert().multiply(b); } } }
  api.blendHip = 1;   /* v14: 0 = off (old POSE-driven hip hands) */
  const PELV = bone('CC_Base_Pelvis') || bone('CC_Base_Hip'), HB = { L: bone('CC_Base_L_Hand'), R: bone('CC_Base_R_Hand') }, M1 = { L: bone('CC_Base_L_Mid1'), R: bone('CC_Base_R_Mid1') };
  // v13b: contact helpers (local hip skin patch around the hand, CPU-skinned each frame; signed point-to-triangle distance)
  const CT = { L: null, R: null }; api.contactDbg = CT;
  const CARM = /(Clavicle|Upperarm|UpArm|Forearm|Elbow|Hand|Index|Mid|Ring|Pinky|Thumb|Finger)/i;
  function ctBuild(c0) { const parts = []; const v = V3();
    root.traverse((m) => { if (!(m.isSkinnedMesh && /Body/i.test(m.name))) return; const g = m.geometry, pos = g.attributes.position, si = g.attributes.skinIndex, sw = g.attributes.skinWeight, bn = m.skeleton.bones, idx = g.index;
      const keep = new Int32Array(pos.count).fill(-1), vi = [];
      if (!m.__ctBody) { const B = []; for (let i = 0; i < pos.count; i++) { let a = 0; for (let k = 0; k < 4; k++) if (CARM.test(bn[si.getComponent(i, k)].name)) a += sw.getComponent(i, k); if (a <= 0.05) B.push(i); } m.__ctBody = Int32Array.from(B); }   // skin weights never change: the arm filter runs once, not on every rebuild
      for (const i of m.__ctBody) {
        v.fromBufferAttribute(pos, i); m.applyBoneTransform(i, v); v.applyMatrix4(m.matrixWorld); if (v.distanceToSquared(c0) > 0.0225) continue; keep[i] = vi.length; vi.push(i); }
      if (!vi.length) return; const tri = []; const ia = idx ? idx.array : null, n = idx ? ia.length : pos.count;
      for (let t = 0; t < n; t += 3) { const a = keep[ia ? ia[t] : t], b = keep[ia ? ia[t + 1] : t + 1], c = keep[ia ? ia[t + 2] : t + 2]; if (a < 0 || b < 0 || c < 0) continue; tri.push(a, b, c); }
      parts.push({ m, vi, tri: new Int32Array(tri), W: new Float32Array(vi.length * 3), N: new Float32Array(vi.length * 3) }); });
    return { parts }; }
  function ctSkin(C) { const v = V3(); for (const P of C.parts) { const { m, vi, W } = P; const pos = m.geometry.attributes.position;
    const nm = m.geometry.attributes.normal, N = P.N, u = V3();
    for (let k = 0; k < vi.length; k++) { v.fromBufferAttribute(pos, vi[k]); u.fromBufferAttribute(nm, vi[k]).multiplyScalar(0.01).add(v); m.applyBoneTransform(vi[k], v); m.applyBoneTransform(vi[k], u); v.applyMatrix4(m.matrixWorld); u.applyMatrix4(m.matrixWorld);
      W[3 * k] = v.x; W[3 * k + 1] = v.y; W[3 * k + 2] = v.z; u.sub(v).normalize(); N[3 * k] = u.x; N[3 * k + 1] = u.y; N[3 * k + 2] = u.z; } } }
  const _cA = V3(), _cB = V3(), _cC = V3(), _cP = V3(), _cQ = V3(), _cN = V3();
  const _cAC = V3(), _cAP = V3(), _cBP = V3(), _cCP = V3(), _cBC = V3();   // scratch: ctClosest runs per triangle per sample every frame
  function ctClosest(p, a, b, c, out) { const ab = _cQ.subVectors(b, a), ac = _cAC.subVectors(c, a), ap = _cAP.subVectors(p, a); const d1 = ab.dot(ap), d2 = ac.dot(ap); if (d1 <= 0 && d2 <= 0) return out.copy(a);
    const bp = _cBP.subVectors(p, b), d3 = ab.dot(bp), d4 = ac.dot(bp); if (d3 >= 0 && d4 <= d3) return out.copy(b);
    const vc = d1 * d4 - d3 * d2; if (vc <= 0 && d1 >= 0 && d3 <= 0) return out.copy(a).addScaledVector(ab, d1 / (d1 - d3));
    const cp = _cCP.subVectors(p, c), d5 = ab.dot(cp), d6 = ac.dot(cp); if (d6 >= 0 && d5 <= d6) return out.copy(c);
    const vb = d5 * d2 - d1 * d6; if (vb <= 0 && d2 >= 0 && d6 <= 0) return out.copy(a).addScaledVector(ac, d2 / (d2 - d6));
    const va = d3 * d6 - d5 * d4; if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) return out.copy(b).addScaledVector(_cBC.subVectors(c, b), (d4 - d3) / ((d4 - d3) + (d5 - d6)));
    const dn = 1 / (va + vb + vc); return out.copy(a).addScaledVector(ab, vb * dn).addScaledVector(ac, vc * dn); }
  function ctNear(C, c, r) { const r2 = r * r; for (const P of C.parts) { const W = P.W, T = P.tri, nl = []; for (let t = 0; t < T.length; t += 3) { const i = 3 * T[t]; const dx = W[i] - c.x, dy = W[i + 1] - c.y, dz = W[i + 2] - c.z; if (dx * dx + dy * dy + dz * dz < r2) nl.push(t); } P.near = nl;
    /* m1: a bounding sphere per near triangle (centroid + radius) lets ctSD skip triangles that cannot beat the best so far. Same answer, a fraction of the work: */
    /* the idle hip pose ran ctSD over every near triangle for every hand sample, about 45 ms a frame, which held idle at 8-20 fps. */
    const B = P.nb && P.nb.length >= 4 * nl.length ? P.nb : (P.nb = new Float64Array(4 * nl.length + 64));
    for (let q = 0; q < nl.length; q++) { const t = nl[q], a = 3 * T[t], b = 3 * T[t + 1], e = 3 * T[t + 2]; const cx = (W[a] + W[b] + W[e]) / 3, cy = (W[a + 1] + W[b + 1] + W[e + 1]) / 3, cz = (W[a + 2] + W[b + 2] + W[e + 2]) / 3;
      let rr = 0; for (const k of [a, b, e]) { const ex = W[k] - cx, ey = W[k + 1] - cy, ez = W[k + 2] - cz; rr = Math.max(rr, ex * ex + ey * ey + ez * ez); }
      B[4 * q] = cx; B[4 * q + 1] = cy; B[4 * q + 2] = cz; B[4 * q + 3] = Math.sqrt(rr) + 1e-6; }
  } }
  const HV = { L: null, R: null }; const HGR = /_(Hand|Thumb|Index|Mid|Ring|Pinky)\d?$/;
  function hvGet(s) { if (HV[s]) return HV[s]; const H = { Palm: [], Thumb: [], Index: [], Mid: [], Ring: [], Pinky: [] }; const cnt = {};
    root.traverse((m) => { if (!(m.isSkinnedMesh && /Body/i.test(m.name))) return; const g = m.geometry, si = g.attributes.skinIndex, sw = g.attributes.skinWeight, bn = m.skeleton.bones;
      for (let i = 0; i < g.attributes.position.count; i++) { let bw = 0, nm = ''; for (let k = 0; k < 4; k++) { const w = sw.getComponent(i, k); if (w > bw) { bw = w; nm = bn[si.getComponent(i, k)].name; } }
        if (!nm.startsWith('CC_Base_' + s + '_')) continue; const mm = nm.match(HGR); if (!mm) continue; const key = mm[1] === 'Hand' ? 'Palm' : mm[1]; cnt[key] = (cnt[key] || 0) + 1;
        if (cnt[key] % (key === 'Palm' ? 4 : 3) === 0) H[key].push({ m, i }); } });
    return (HV[s] = H); }
  const _hv = V3(); function hvPos(it) { const v = V3().fromBufferAttribute(it.m.geometry.attributes.position, it.i); it.m.applyBoneTransform(it.i, v); return v.applyMatrix4(it.m.matrixWorld); }
  const _cBC2 = V3();
  function ctSD(C, p, hk) { let best = 1e9, bq = -1, bP = null; const tmp = _cBC2, px = p.x, py = p.y, pz = p.z;
    for (let pi = 0; pi < C.parts.length; pi++) { const P = C.parts[pi], W = P.W, T = P.tri, NL = P.near, NB = NL ? P.nb : null, nn = NL ? NL.length : T.length / 3;
      /* m1b: hand samples sit about 5 cm off the skin and the finger flex search asks about 14-40k of them a frame, so each query must be cheap. */
      /* A triangle is tried only if its bounding sphere can beat the best so far (seeded from this sample's last winner). The scan keeps the original order, so the winner and its normal are unchanged. */
      let su = Math.sqrt(best); const hq = NB && hk && hk.q ? hk.q[pi] : undefined;
      if (hq !== undefined && hq < nn) { const t0 = NL[hq]; _cA.fromArray(W, 3 * T[t0]); _cB.fromArray(W, 3 * T[t0 + 1]); _cC.fromArray(W, 3 * T[t0 + 2]); su = Math.min(su, Math.sqrt(ctClosest(p, _cA, _cB, _cC, tmp).distanceToSquared(p))); }
      for (let q = 0; q < nn; q++) { if (NB) { const ex = px - NB[4 * q], ey = py - NB[4 * q + 1], ez = pz - NB[4 * q + 2], rq = NB[4 * q + 3] + su; if (ex * ex + ey * ey + ez * ez > rq * rq) continue; }
        const t = NL ? NL[q] : 3 * q; _cA.fromArray(W, 3 * T[t]); _cB.fromArray(W, 3 * T[t + 1]); _cC.fromArray(W, 3 * T[t + 2]);
        const d = ctClosest(p, _cA, _cB, _cC, tmp).distanceToSquared(p); if (d < best) { best = d; bq = t; bP = P; if (NL && hk) (hk.q || (hk.q = []))[pi] = q; if (NB) su = Math.min(su, Math.sqrt(d)); } } }
    const bc = V3(), fn = V3();
    if (bP) { const W = bP.W, T = bP.tri, N = bP.N, i0 = 3 * T[bq], i1 = 3 * T[bq + 1], i2 = 3 * T[bq + 2]; _cA.fromArray(W, i0); _cB.fromArray(W, i1); _cC.fromArray(W, i2); ctClosest(p, _cA, _cB, _cC, bc); fn.set(N[i0] + N[i1] + N[i2], N[i0 + 1] + N[i1 + 1] + N[i2 + 1], N[i0 + 2] + N[i1 + 2] + N[i2 + 2]); }
    const dir = V3().subVectors(p, bc); const d = Math.sqrt(best); fn.normalize();
    const sg = dir.dot(fn) >= 0 ? 1 : -1;   // side from the skinned vertex normals (triangle winding is not consistent on this mesh)
    return { d: sg * d, n: d > 1e-6 ? dir.multiplyScalar(sg / d) : fn }; }
  const HIPANC = { L: [15.925, 4.403, 0.959], R: [-15.925, 4.403, 0.959] };   /* v14: palm point of the Blender pose (scratch/bl14 f2) in the pelvis frame (v13e was 15.818, 3.525, 6.142) */   // v13e: mesh refit (v13c was 14.895, 3.456, 5.675)
    // v13: palm 2.7 cm out and 1.4 cm forward further out (it sank into the hip/thigh in idle 0:02-0:05); was L 13.917, R -13.028
    // v10: palm contact point in the pelvis frame (cm), fit against the live skin
  api.hipAnc = HIPANC;
  const HIPANCB = { L: [15.925, 4.403, 0.959], R: [-15.925, 4.403, 0.959] };   /* v14: Blender pose palm point (v13e was 16.015, 2.311, 6.548) */   // v13e: mesh refit (v13c was 14.4, 2.386, 6.527)
    // v13: 1.5 cm out, 1.4 cm forward (was L 15.45/0.809, R -12.228/-1.242): palms sank into the hips in idle   // v10b: separate anchor for hipBoth
  api.hipAncB = HIPANCB;   // v13b test hook (contact refit)
  const HROT = { L: null, R: null }; const HROTt = { L: 0, R: 0 }; api.clearHrot = () => { HROT.L = HROT.R = null; HROTt.L = HROTt.R = 0; };   // v13b test hook api.hipRot = HROT;
  const PKEYS = Object.keys(ZP);
  const WS_MOCAP = [-0.032, -0.047, -0.062, -0.057, -0.061, -0.061, -0.031, 0.021, 0.114, 0.245, 0.402, 0.561, 0.712, 0.822, 0.877, 0.874, 0.81, 0.688, 0.538, 0.378, 0.215, 0.074, -0.019, -0.076, -0.108, -0.121, -0.126, -0.129, -0.118, -0.093, -0.039, 0.044, 0.143, 0.244, 0.357, 0.483, 0.599, 0.694, 0.765, 0.805, 0.806, 0.783, 0.731, 0.624, 0.457, 0.233, -0.028, -0.293, -0.474, -0.489, -0.365, -0.149, 0.18, 0.523, 0.753, 0.835, 0.763, 0.522, 0.185, -0.171, -0.467, -0.661, -0.746, -0.745, -0.677, -0.563, -0.407, -0.251, -0.137, -0.058, 0.008, 0.054, 0.096, 0.145, 0.181, 0.185, 0.159, 0.111, 0.051, 0.0, -0.032, -0.053, -0.075, -0.104, -0.142, -0.189, -0.229, -0.238, -0.195, -0.103, 0.037, 0.208, 0.364, 0.481, 0.554, 0.575, 0.555, 0.507, 0.404, 0.218, -0.017, -0.273, -0.489, -0.59, -0.565, -0.495, -0.434, -0.415, -0.489, -0.618, -0.74, -0.815, -0.842, -0.809, -0.749, -0.659, -0.555, -0.457, -0.372, -0.314, -0.293, -0.307, -0.337, -0.374, -0.391, -0.377, -0.338, -0.298, -0.258, -0.227, -0.201, -0.184, -0.181, -0.172, -0.175, -0.187, -0.212, -0.24, -0.278, -0.306, -0.339, -0.362, -0.377, -0.38, -0.373, -0.333, -0.253, -0.11, 0.073, 0.254, 0.381, 0.422, 0.33, 0.111, -0.158, -0.424, -0.64, -0.768, -0.787, -0.731, -0.609, -0.478, -0.356, -0.233, -0.079, 0.105, 0.314, 0.528, 0.71, 0.815, 0.824, 0.771, 0.698, 0.606, 0.511, 0.426, 0.355, 0.289, 0.248, 0.248, 0.268, 0.31, 0.361, 0.413, 0.444, 0.473, 0.491, 0.514, 0.542, 0.569, 0.605, 0.641, 0.665, 0.668, 0.641, 0.567, 0.459, 0.337, 0.243, 0.221, 0.234, 0.195, 0.074, -0.104, -0.319, -0.556, -0.734, -0.843, -0.896, -0.905, -0.807, -0.59, -0.262, 0.119, 0.478, 0.743, 0.878, 0.908, 0.819, 0.657, 0.446, 0.228, -0.009, -0.224, -0.387, -0.494, -0.555, -0.561, -0.52, -0.475, -0.424, -0.364, -0.294, -0.209, -0.106, 0.004, 0.094, 0.153, 0.181, 0.178, 0.132, -0.015, -0.243, -0.508, -0.772, -0.974, -1.0, -0.848, -0.575, -0.252, 0.07, 0.328, 0.485, 0.519, 0.455, 0.324, 0.145, -0.04, -0.198, -0.307, -0.37, -0.371, -0.328, -0.242, -0.16];   // 10 Hz, normalised to +-1 (+ = weight on her left leg)
  const wsOff = rnd() * 20;
  const WS_MIX = [0.580, 0.573, 0.602, 0.609, 0.618, 0.636, 0.648, 0.663, 0.684, 0.706, 0.732, 0.735, 0.729, 0.724, 0.704, 0.706, 0.708, 0.716, 0.725, 0.689, 0.634, 0.597, 0.565, 0.552, 0.547, 0.547, 0.537, 0.521, 0.502, 0.508, 0.558, 0.601, 0.619, 0.577, 0.438, 0.274, 0.093, -0.074, -0.197, -0.289, -0.276, -0.179, 0.015, 0.151, 0.174, 0.058, -0.131, -0.328, -0.516, -0.648, -0.665, -0.662, -0.666, -0.678, -0.693, -0.712, -0.716, -0.724, -0.750, -0.775, -0.808, -0.831, -0.852, -0.861, -0.846, -0.815, -0.781, -0.756, -0.740, -0.738, -0.723, -0.718, -0.715, -0.717, -0.679, -0.622, -0.594, -0.616, -0.642, -0.679, -0.713, -0.735, -0.734, -0.719, -0.699, -0.682, -0.674, -0.682, -0.678, -0.664, -0.655, -0.620, -0.640, -0.660, -0.652, -0.648, -0.672, -0.722, -0.776, -0.774, -0.716, -0.597, -0.478, -0.420, -0.415, -0.496, -0.652, -0.894, -1.061, -1.046, -0.885, -0.629, -0.343, -0.044, 0.209, 0.335, 0.344, 0.362, 0.393, 0.412, 0.423, 0.409, 0.388, 0.402, 0.434, 0.479, 0.490, 0.514, 0.531, 0.533, 0.531, 0.499, 0.469, 0.478, 0.472, 0.476, 0.461, 0.454, 0.449, 0.443, 0.415, 0.386, 0.369, 0.347, 0.347, 0.368, 0.386, 0.422, 0.458, 0.493, 0.509, 0.494, 0.506, 0.516, 0.522, 0.536, 0.558, 0.583, 0.584, 0.568, 0.543, 0.505, 0.500, 0.502, 0.512, 0.540, 0.575];   // v9: Mixamo 'Idle' hips lateral offset over the feet, 10 Hz, scaled to the CMU range
  const WSA = new URLSearchParams(location.search).get('ws') === 'mix' ? WS_MIX : WS_MOCAP;
  const wsMocap = (t) => { const n = WSA.length - 1, u = ((t + wsOff) * 10) % (2 * n), x = u <= n ? u : 2 * n - u, i = Math.min(n - 1, Math.floor(x)), f = x - i; return WSA[i] * (1 - f) + WSA[i + 1] * f; };
  const ip = { name: null, last: null, side: 'L', next: 1 + rnd() * 1.5, hold: 0, L: { ...ZP }, R: { ...ZP }, vL: { ...ZP }, vR: { ...ZP } };
  const reseedIdle = (n) => { aseed = n >>> 0; ip.name = null; ip.last = null; ip.next = 1 + rnd() * 1.5; ip.hold = 0; };   // vr4: test hook (seed search)
  api.reseedIdle = reseedIdle;
  const pst = { v: 0, from: 0, to: 0, u: 1, dur: 2, next: 4 + rnd() * 6 };   // posture: + = upright/chest up, - = relaxed/slouch
  const morphs = {};   // name -> value, written to every face mesh that has it
  const FACE_NAMES = new Set([...VIS, 'Eye_Squint_L', 'Eye_Squint_R', 'Eye_Wide_L', 'Eye_Wide_R', 'Cheek_Raise_L', 'Cheek_Raise_R', 'Eye_Blink_L', 'Eye_Blink_R', 'Eye_L_Look_Down', 'Eye_R_Look_Down', ...MICRO.flatMap((u) => Object.keys(u.m)),
    'Mouth_Smile_L', 'Mouth_Smile_R', 'Brow_Raise_Inner_L', 'Brow_Raise_Inner_R', 'Brow_Compress_L', 'Brow_Compress_R', 'Mouth_Press_L', 'Mouth_Press_R', 'Brow_Raise_Outer_L', 'Brow_Raise_Outer_R',
    'Nose_Crease_L', 'Nose_Crease_R', 'Nose_Sneer_L', 'Nose_Sneer_R', 'Nose_Nostril_Raise_L', 'Nose_Nostril_Raise_R', 'Mouth_Dimple_L', 'Mouth_Dimple_R', 'Mouth_Tighten_L', 'Mouth_Tighten_R', 'Cheek_Puff_L', 'Cheek_Puff_R']);   // v9: + richer expression keys
  const slots = face.visemes.map((f) => ({ inf: f.inf, idx: Object.fromEntries([...FACE_NAMES].map((n) => [n, f.dict[n]]).filter(([, i]) => i !== undefined)) }));
  api.faceNames = [...FACE_NAMES];   // v9 test hook: morphs driven

  let T = 0;
  // ---- v10 walk layer (merged from anim-walk.js, approved walk v2). setState('walk') / api.setWalk(true) blends idle -> walk; any other state blends back.
  // The baked track (walk-track.json) drives the body bones; the face, look, fingers and hands' finger motion stay from this animator.
  let WTRK = null, WTR = null, wT = 0, sT = 0, wph = 0, wk = 0, walkOn = false;  let wkA = 0;   // v15: slower walk-in weight for the arms (hands leave the hip over 0.75 s, not 0.3 s)   // wph: 0 idle, 1 start clip, 2 walk cycle, 3 stop clip, 4 settle to idle
  const WB = {}, GL = V3(), GW = V3(), hipB0 = hipP0 ? hipP0.clone() : null;
  const HEAD0 = R.Head ? wpos(R.Head.b) : V3(), HIP0 = hip ? wpos(hip.b) : V3(), wqa = Q(), wqb = Q();
  try { fetch(new URL('./walk-track.json', import.meta.url)).then((r) => r.json()).then((j) => { WTRK = j; console.info('[avatar] clip loaded name=walk-track'); for (const n of j.bones) { const b = bone('CC_Base_' + n); if (b) WB[n] = b; } api.walkReady = true; }).catch(() => {}); } catch (e) {}
  // v10c: Mixamo FemaleStartWalking / FemaleStopWalking transitions (walk-trans.json; root forward stripped into tz, re-applied as travel)
  try { fetch(new URL('./walk-trans.json', import.meta.url)).then((r) => r.json()).then((j) => { WTR = j; api.transReady = true; console.info('[avatar] clip loaded name=walk-trans'); }).catch(() => {}); } catch (e) {}
  const WPQ = [], WPB = [], wHQ = Q(), wHB = Q(), wHP = V3(), wHPB = V3(), wsm = (x) => { x = Math.max(0, Math.min(1, x)); return x * x * (3 - 2 * x); };
  api.setWalk = (on) => { walkOn = !!on; };
  Object.defineProperty(api, 'walkW', { get: () => wk });
  Object.defineProperty(api, 'level', { get: () => lvl.med || 0 });   // v11: smoothed voice level for the aether
  function update(dt) {
    T += dt; if (api.freezeT !== undefined) T = api.freezeT; const t = T; const dtc = api.freezeClocks ? 0 : dt;   // v13b test hook: freezeClocks stops breath, weight shift, posture, wrist drift and finger fidget clocks (contact fitting)   // v10 test hook: freezeT
    if (wph !== api.__logWph) { api.__logWph = wph; console.info('[avatar] clip play name=' + ['idle', 'walk-start', 'walk', 'walk-stop', 'settle'][wph]); }
    { if (walkOn && WTRK && WTR && (wph === 0 || (wph === 3 && sT >= WTR.stop.n - 2.02))) { if (wph === 3) { GL.addScaledVector(WTR.offE, 1 - (WTR.fE || 0)); WTR.fE = 0; } wph = 1; sT = 0; }   // idle -> start clip
      if (hipP0) hipP0.copy(hipB0).add(GL); for (const L of LEGS) if (L) { if (!L.A0) L.A0 = L.A.clone(); L.A.copy(L.A0).add(GW); } }   // idle stands where the walk stopped
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
      // gesture plan for this phrase
      gest.next = Math.min(gest.next ?? 0, 0.15 + rnd() * 0.3); }
    // gestures: start at irregular times inside phrases, hold 1.2-3 s (beats on stressed syllables), then drop
    gest.next = (gest.next ?? 1) - dt; gest.hold = (gest.hold ?? 0) - dt;
    if (gest.hold <= 0 && gest.next > 50) { gest.L.tgt = gest.R.tgt = 0; gest.next = 0.5 + rnd() * 1.8; }
    if (ph.on && gest.next <= 0 && !gest.L.tgt && !gest.R.tgt) { gest.next = 99; gest.hold = 1.4 + rnd() * 2.2;
      if (gest.fired && rnd() >= 0.9) gest.hold = 0.4 + rnd() * 0.6;   // v4: a skipped gesture only waits a moment (never the first)
      else { gest.fired = true; const side = rnd() < 0.7 ? (gest.last === 'L' ? 'R' : 'L') : gest.last; gest.last = side;
        let key; do { key = rnd() < 0.2 ? 'both' : GKEYS[Math.floor(rnd() * GKEYS.length)]; } while (key === gest.lastKey); gest.lastKey = key; const o = side === 'L' ? 'R' : 'L';
        gest[side].key = gest[o].key = key; gest[side].tgt = 0.8 + rnd() * 0.2; gest[side].k = rnd(); gest[o].k = rnd();
        if (key === 'both') gest[o].tgt = 0.75 + rnd() * 0.2; else if (rnd() < 0.3) gest[o].tgt = 0.3 + rnd() * 0.2; } }   // v7: one mocap key per phrase
    if (ph.on && (ph.quiet > 0.16 || w.speaking < 0.4)) { ph.on = false; ph.off = 0; ph.nod = 0;
      ph.nodK = rnd() < 0.55 ? (0.6 + rnd() * 0.5) : 0; ph.tiltK = ph.nodK ? (rnd() < 0.3 ? (rnd() < 0.5 ? -1 : 1) * 0.5 : 0) : (rnd() < 0.5 ? -1 : 1) * (0.6 + rnd() * 0.4);
      if (gest.hold <= 0.3 || w.speaking < 0.4) { gest.L.tgt = gest.R.tgt = 0; gest.hold = 0; gest.next = 0.3 + rnd() * 1.2; } }   // v4: a gesture may carry over a short pause
    if (ph.on) ph.t += dt; ph.off += dt; ph.lift += dt; ph.nod += dt;
    if (TRK) {   // v8: segment player (start at phrase start, crossfade on springs, ease out at phrase end)
      const want = (ph.on || ph.off < 0.5) ? w.speaking : 0;
      if (ph.on && !mo.wasOn && !mo.slots.some((sl) => sl.tg > 0 && sl.w > 0.3)) moStart();
      mo.wasOn = ph.on;
      const cur = mo.slots[mo.slots.length - 1];
      if (cur && cur.tg > 0 && cur.t > TRK.segs[cur.i].n / TRK.fps - 1.3) moStart(0.2 + mrnd() * 1.5);   /* v15: hand over earlier, so the old segment is still moving while it fades */
      if (api.forceTrack) { mo.slots = [{ i: api.forceTrack.seg, t: api.forceTrack.t, w: 1, v: 0, tg: 1 }]; }
      for (const sl of mo.slots) { const g = (sl === mo.slots[mo.slots.length - 1] ? sl.tg : 0) * (api.forceTrack ? 1 : want), om = 3.2, h = Math.min(dt, 0.05);
        if (api.forceTrack) { sl.w = 1; sl.v = 0; } else { sl.v += (-2 * om * sl.v - om * om * (sl.w - g)) * h; sl.w = Math.max(0, Math.min(1, sl.w + sl.v * h)); }
        if (!api.forceTrack) { const rem = TRK.segs[sl.i].n / TRK.fps - 0.04 - sl.t; const rr = TRK.segs[sl.i].rate || 1; sl.t += rem > 0.5 ? dt * rr : Math.max(0, rem) * (1 - Math.exp(-dt * rr / 0.5)); }   /* v15: per-segment playback rate (Talking 0.8) */ }   /* v15: decelerate into the segment end (was a hard stop mid-crossfade: jerk at speaking f581) */
      mo.slots = mo.slots.filter((sl, k) => k === mo.slots.length - 1 || sl.w > 0.002);
      for (const s2 of ['L', 'R']) for (let j = 0; j < 9; j++) MQ[s2][K9N[j]] = mo.slots.reduce((a2, sl) => a2 + sl.w * moSample(sl, s2, j), 0);
      for (const s2 of ['L', 'R']) for (let j = 0; j < 5; j++) MF[s2][j] = TRK.segs[0][s2][0].length > 9 ? mo.slots.reduce((a2, sl) => a2 + sl.w * moSample(sl, s2, 9 + j), 0) : 0;
      for (let j = 0; j < 3; j++) { MSP[j] = mo.slots.reduce((a2, sl) => a2 + sl.w * moSample(sl, 'sp', j), 0); MHD[j] = mo.slots.reduce((a2, sl) => a2 + sl.w * moSample(sl, 'hd', j), 0); } }
    ph.warmT += ((ph.on ? ph.warm : 0) * w.speaking - ph.warmT) * (1 - Math.exp(-dt / 0.35));
    const lift = pulse(ph.lift, 0.35, 0.9) * w.speaking;                     // posture lift at phrase start
    const nodE = ph.nod < 1.1 ? Math.sin(Math.PI * Math.min(1, ph.nod / 0.75)) * (ph.nod < 0.75 ? 1 : 0) : 0;   // phrase-end nod / tilt
    if (api.forceGest) { gest.L.tgt = api.forceGest.L || 0; gest.R.tgt = api.forceGest.R || 0; gest.L.k = gest.R.k = api.forceGest.k ?? 0.5; if (api.forceGest.key) gest.L.key = gest.R.key = api.forceGest.key; gest.next = 99; gest.hold = 99; }   // test hook
    // gestures: critically damped toward the planned amount; beats ride stressed syllables
    for (const s of ['L', 'R']) { const G = gest[s], om2 = 5.5;
      G.v += (-2 * om2 * G.v - om2 * om2 * (G.a - G.tgt * w.speaking)) * dt; G.a += G.v * dt;
      if (TRK) G.Q = MQ[s]; else { const tg = GP[G.key][s], h3 = Math.min(dt, 0.05), om3 = api.forceGest ? 30 : 4.5; for (const k2 of ['ux', 'uy', 'uz', 'fx', 'fy', 'fz', 'hx', 'hy', 'hz']) { const g3 = (tg[k2] || 0) * Math.max(0, G.tgt) * w.speaking;
        if (om3 > 10) { G.Q[k2] = g3; G.QV[k2] = 0; continue; } G.QV[k2] = (G.QV[k2] || 0) + (-2 * om3 * (G.QV[k2] || 0) - om3 * om3 * ((G.Q[k2] || 0) - g3)) * h3; G.Q[k2] = (G.Q[k2] || 0) + G.QV[k2] * h3; } }   // v7 fallback: key pose on a spring (v8 uses the track)
      if (syl && (sp.stressT === 0 || rnd() < 0.3) && G.a > 0.2) G.beat = 0; G.beat = G.beat === undefined ? 9 : G.beat + dt; }
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

    // ---- body ----
    // weight shift: settle onto one leg, hold 6-12 s, transfer over ~1.5-2.5 s (min-jerk); slow noise on top
    ws.next -= dtc;
    if (ws.next <= 0) { ws.from = ws.cur; ws.to = (ws.to > 0 ? -1 : 1) * (0.45 + rnd() * 0.55) * (rnd() < 0.2 ? -1 : 1) * 1; ws.u = 0; ws.dur = 1.2 + rnd() * 2.0; ws.next = (rnd() < 0.3 ? 2.5 : 5) + rnd() * 8; }
    ws.u = Math.min(1, ws.u + dtc / ws.dur); const wu = ws.u, mjw = wu * wu * wu * (10 - 15 * wu + 6 * wu * wu);
    ws.cur = ws.from + (ws.to - ws.from) * mjw;
    ip.hb = ip.hb || 0; { const hbT = ip.name === 'hip' ? (ip.side === 'L' ? 1 : -1) * (ip.calmPrev ?? 1) : 0; { const om = 3.4, h4 = Math.min(dt, 0.05); ip.hbV = (ip.hbV || 0) + (-2 * 0.72 * om * (ip.hbV || 0) - om * om * (ip.hb - hbT)) * h4; ip.hb += ip.hbV * h4; } }   // v13: weight moves on a soft spring (slight overshoot, then settles) if (api.hbForce !== undefined) ip.hb = api.hbForce;   // v10 test hook (contact fit in the live pose)   // v9: hip pops toward the hand side
    const sw = p.sway, wgt = wsMocap(t) * sw * (1 - 0.6 * Math.abs(ip.hb)) + 0.9 * ip.hb - 0.1 * (ip.hbV || 0);   // v13: anticipation (the pelvis dips the other way as the shift starts)   // v6: real idle weight shift (CMU 140_06 'Idle' pelvis lateral offset, ping-pong looped)   // + = weight on her left leg (+x)
    const swz = (0.65 * D('sz', 2, 6) + 0.35 * N(t * 0.19, 'sz')) * sw, swy = (0.65 * D('sy', 3, 8) + 0.35 * N(t * 0.16, 'sy')) * sw;            // fore-aft sway, slow hip yaw
    // pelvis: shifts over the stance leg, stance hip hikes (roll), tiny yaw; drops a hair so the knees stay soft
    if (hip) {
      const dx = 0.05 * wgt, dz = 0.01 * swz + 0.012 * p.lean, r = 0.09 * wgt;
      const off = new THREE.Vector3(dx, 0, dz).applyQuaternion(wq(hip.b.parent).invert()).divideScalar(hipPS);
      hip.b.position.copy(hipP0).add(off);
      rot('Hip', 0.01 * swz, 0.045 * swy, r);
      hip.b.updateMatrixWorld(true);
      const slack = legSlack() + 0.004 + 0.003 * Math.abs(wgt);   // soft knees, a little more give on the free leg
      off.add(new THREE.Vector3(0, -slack, 0).applyQuaternion(wq(hip.b.parent).invert()).divideScalar(hipPS));
      hip.b.position.copy(hipP0).add(off); hip.b.updateMatrixWorld(true);
      solveLegs();
    }
    // spine: counter-rotates the pelvis (contrapposto), breath arches the chest, shoulders follow head turns with a lag
    const r = 0.09 * wgt;
    fol.y += (gz.hy - fol.y) * (1 - Math.exp(-dt / 0.35)); fol.x += (gz.hx - fol.x) * (1 - Math.exp(-dt / 0.45));
    const brR = 0.012 * N(t * 0.6, 'brr');   // breath is not perfectly symmetric
    pst.next -= dtc; if (pst.next <= 0) { pst.from = pst.v; pst.to = (rnd() < 0.5 ? -1 : 1) * (0.5 + 0.5 * rnd()); pst.u = 0; pst.dur = 1.5 + rnd() * 2; pst.next = 5 + rnd() * 9; }
    pst.u = Math.min(1, pst.u + dtc / pst.dur); { const u = pst.u, m = u * u * (3 - 2 * u); pst.v = pst.from + (pst.to - pst.from) * m; }
    const pv = pst.v * (1 - 0.4 * w.speaking);   // + = chest up/upright, - = relaxed slouch
    rot('Waist', -0.004 * b + 0.003 * N(t * 0.23, 'wp'), -0.022 * swy + 0.06 * fol.y, -0.55 * r);
    rot('Spine01', -0.012 * b - 0.03 * pv + p.lean * 0.4 + 0.004 * N(t * 0.31, 'sp1'), -0.012 * swy + 0.09 * fol.y, -0.35 * r + 0.004 * N(t * 0.27, 'sr'));
    rot('Spine02', -0.042 * b - 0.05 * pv - 0.03 * sg2 + p.lean * 0.6 + 0.012 * settle + 0.05 * fol.x - 0.035 * lift - 0.012 * stress * w.speaking + 0.25 * hs.x + 0.006 * D('sp2', 3, 9) + SPK * MSP[0], 0.12 * fol.y + SPK * MSP[1], -0.2 * r + brR * b + 0.25 * stR + SPK * MSP[2]);   // v8: + mocap spine (high-passed)
    // shoulders ride the breath (left a touch more), drop on the settle, a slow independent shrug drift
    const sh = 0.05 * b + 0.05 * sg2 - 0.03 * settle + 0.02 * lift + 0.022 * stress * w.speaking;
    const shL = sh * 1.1 + 0.008 * D('cl', 3, 9) + 0.004 * N(t * 0.21, 'cl') - 0.03 * Math.max(0, -stR / 0.17) * stE, shR = sh * 0.92 + 0.008 * D('cr', 3, 9) + 0.004 * N(t * 0.24, 'cr') - 0.03 * Math.max(0, stR / 0.17) * stE;
    rot('L_Clavicle', 0, 0.01 * b, shL + 0.09 * Math.max(0, ip.hb)); rot('R_Clavicle', 0, -0.01 * b, -(shR + 0.09 * Math.max(0, -ip.hb)));   // v9: hand-side shoulder lifts a touch
    // arms: hang from the shoulder (cancel most of the shoulder roll + torso roll), damped pendulum swing driven by the pelvis shift
    const torsoRoll = r * (1 - 0.55 - 0.35 - 0.2);
    const vel = (wgt - arm.pw) / Math.max(dt, 1e-3); arm.pw = wgt; const accel = (vel - arm.pa) / Math.max(dt, 1e-3); arm.pa = vel;
    // ---- v5 idle arm poses: pick one now and then (hand on hip, loose arm cross, touch forearm, clasp, shift hands), hold, release ----
    ip.next -= dt; ip.hold -= dt;
    const calmA = (w.idle + w.done + 0.6 * w.listening) * (1 - w.speaking) * (wph !== 0 || walkOn ? 0 : 1); ip.calmPrev = calmA;
    if (ip.name && (ip.hold <= 0 || calmA < 0.5)) { ip.last = ip.name; ip.name = null; ip.next = 1.5 + rnd() * 3.5; }
    if (!ip.name && ip.next <= 0 && calmA > 0.7) { const names = ['hip', 'hip', 'hipBoth'];
      do { ip.name = names[Math.floor(rnd() * names.length)]; } while (ip.name === ip.last); ip.side = rnd() < 0.5 ? 'L' : 'R'; ip.hold = 3 + rnd() * 4; ip.k = 1; }
    if (api.forcePose !== undefined) { ip.name = api.forcePose && api.forcePose.name; ip.side = api.forcePose && api.forcePose.side || 'L'; ip.k = 1; ip.hold = 99; }
    for (const s of ['L', 'R']) { let tgt = ZP; const P0 = ip.name && POSE[ip.name];
      if (P0) { const own = POSE[ip.name + ip.side]; const k3 = own || ip.side === 'L' ? s : (s === 'L' ? 'R' : 'L'); tgt = (own || P0)[k3] || ZP; }
      if (api.poseRaw) tgt = api.poseRaw[s] || ZP;   // test hook (tuning)
      const cA5 = Math.min(1, Math.max(0, (calmA - 0.45) / 0.25));   // v13b: full pose once calm (calmA sits ~0.7-0.8 in idle; scaling by it left the hand 25% short of the hip)
      const X = ip[s], Vv = ip['v' + s], om5 = api.forcePose !== undefined || api.poseRaw ? 30 : 3.2;
      if (s === 'L') api.__sinceWalk = api.walkPhase > 0 ? 0 : (api.__sinceWalk ?? 99) + dt; const Gf = ip['g' + s] || (ip['g' + s] = {});   /* v15c: the eased pose start only runs in the 4 s after a walk (the settle), so plain idle is exactly v15 */ for (const k2 of PKEYS) { const g0 = (tgt[k2] || 0) * (ip.k || 1) * cA5; if (Gf[k2] === undefined || om5 > 10 || !(api.__sinceWalk < 4) || new RegExp(api.poseNoEase ?? '^(c|tb|sp|hipw)').test(k2)) Gf[k2] = g0;   /* v15c: fingers, thumb, spread and the hip-contact weight keep the v15 spring (the eased target made idle finger jolts f278/f393) */ else Gf[k2] += (g0 - Gf[k2]) * Math.min(1, dt / (api.poseTau ?? 0.3)); const g2 = Gf[k2];   /* v15b2: the pose spring follows an eased target, so a new pose starts without a kick (walk-to-idle settle f338) */ if (om5 > 10) { X[k2] = g2; Vv[k2] = 0; continue; } const h2 = Math.min(dt, 0.05); Vv[k2] += (-2 * om5 * Vv[k2] - om5 * om5 * (X[k2] - g2)) * h2; X[k2] += Vv[k2] * h2; } }
    for (const s of ['L', 'R']) { const A = arm[s], sg = s === 'L' ? 1 : -1, PZ = ip[s];
      A.v += (-25 * A.x - 3.2 * A.v - 0.15 * Math.max(-3, Math.min(3, accel))) * dt; A.x += A.v * dt; A.x = Math.max(-0.05, Math.min(0.05, A.x));
      const G = gest[s], ga = Math.max(0, G.a), beat = pulse(G.beat, 0.06, 0.18) * Math.min(1, ga * 2);
      const fwd = 0.016 * D('af' + s, 2, 7) + 0.008 * N(t * 0.33, 'af' + s) + 0.012 * b * (s === 'L' ? 1 : 0.8) - 0.04 * beat;
      const out = sg * (-(s === 'L' ? shL : shR) * 0.7) - torsoRoll * 0.8 + A.x + 0.007 * D('ao' + s, 3, 8) + 0.004 * N(t * 0.29, 'ao' + s) ;
      const Q = G.Q; rot(s + '_Upperarm', fwd + PZ.ux + (Q.ux || 0), 0.015 * N(t * 0.2, 'ay' + s) + sg * (PZ.uy + (Q.uy || 0)), out + sg * (PZ.uz + (Q.uz || 0)));
      // elbow: a soft bend that breathes slowly (never straighter than pass 14)
      const bend = 0.035 * (0.5 + 0.5 * D('eb' + s, 2, 6)) + 0.01 * b - 0.12 * beat + 0.03 * ga * N(t * 0.8, 'gw' + s);
      rot(s + '_Forearm', -bend + PZ.fx + (Q.fx || 0), sg * (PZ.fy + (Q.fy || 0) * (api.gTw ?? 0.6)), sg * (PZ.fz + (Q.fz || 0)));   // v7: mocap forearm; twist scaled (flare)
      // wrist drift (small; forearm twist untouched so the palms keep the pass 14 turn)
      const W = wst[s]; W.t -= dtc; if (W.t <= 0) { W.t = (w.speaking > 0.5 ? 4 : 7) + rnd() * 9; W.gx = (rnd() * 2 - 1) * 0.06; W.gz = (rnd() * 2 - 1) * 0.05; }
      { const om6 = 2.6, h6 = Math.min(dt, 0.05); W.vx += (-2 * om6 * W.vx - om6 * om6 * (W.x - W.gx)) * h6; W.x += W.vx * h6; W.vz += (-2 * om6 * W.vz - om6 * om6 * (W.z - W.gz)) * h6; W.z += W.vz * h6; }
      const rk = 1 - Math.min(1, Math.max(0, PZ.hipw || 0));   // free hand (not on the hip)
      const wEmp = (0.07 * Math.max(0, lvl.nod - 0.05) * 1.5 + 0.05 * stress) * w.speaking * rk;   // v10: wrist lifts a little on emphasis
      rot(s + '_Hand', 0.03 * D('hx' + s, 2, 6) + 0.02 * N(t * 0.41, 'hx' + s) + (Q.hx || 0) + PZ.hx + rk * W.x - wEmp, 0.025 * N(t * 0.37, 'hy' + s) + sg * (PZ.hy + (Q.hy || 0)), sg * (0.04 * N(t * 0.35, 'hz' + s) + (Q.hz || 0) + PZ.hz + rk * W.z));
    }
    // v13: no end-on hands. When a gesture points the hand at the camera (+z), its fingers read as a glowing ring; ease the wrist down
    // (world-space flexion, a smooth function of how end-on it is, so there is no pop).
    for (const s of ['L', 'R']) { const hb = HB[s], fb = hb && hb.parent; if (!fb || !fb.parent) continue;   // forearm first: an end-on forearm shows its whole rim as a ring
      fb.updateWorldMatrix(true, true); const f0 = fb.getWorldPosition(_eA), d = hb.getWorldPosition(_eB).sub(f0).normalize();
      const k = Math.max(0, Math.min(1, (d.z - 0.45) / 0.45)), ang = 0.55 * k * k * (3 - 2 * k); if (ang < 1e-4) continue;
      _eAx.set(d.z, 0, -d.x); if (_eAx.lengthSq() < 1e-6) continue; _eAx.normalize();
      const pw = fb.parent.getWorldQuaternion(_eQ1), wq = _eQ2.copy(pw).multiply(fb.quaternion);
      wq.premultiply(_eQ3.setFromAxisAngle(_eAx, ang)); fb.quaternion.copy(pw.invert().multiply(wq)); }
    for (const s of ['L', 'R']) { const hb = HB[s], m1 = M1[s]; if (!hb || !m1 || !hb.parent) continue;
      hb.updateWorldMatrix(true, true); const h0 = hb.getWorldPosition(_eA), d = m1.getWorldPosition(_eB).sub(h0).normalize();
      const k = Math.max(0, Math.min(1, (d.z - 0.35) / 0.5)), ang = 0.75 * k * k * (3 - 2 * k); if (ang < 1e-4) continue;
      _eAx.set(d.z, 0, -d.x).normalize(); if (_eAx.lengthSq() < 0.5) continue;   // tilt the finger direction toward -y
      const pw = hb.parent.getWorldQuaternion(_eQ1), wq = _eQ2.copy(pw).multiply(hb.quaternion);
      wq.premultiply(_eQ3.setFromAxisAngle(_eAx.set(-d.z, 0, d.x).normalize(), -ang)); hb.quaternion.copy(pw.invert().multiply(wq)); }
    /* v14: hand-set Blender hip pose: arm and hand rotations held in the pelvis frame, fingers/thumb local (blended by hipw), then the anchor IK pins the palm */
    if (api.blendHip && PELV) for (const s of ['L', 'R']) { const wA = Math.min(1, Math.max(0, ip[s].hipw || 0)); if (wA < 0.01) continue; const pq = wq(PELV);
      for (const n of ['Upperarm', 'Forearm', 'Hand']) { const r = R[s + '_' + n]; if (!r || !BLW[s + '_' + n]) continue; const b = r.b, T = pq.clone().multiply(BLW[s + '_' + n]);
        const cw = wq(b), tq = cw.clone().slerp(T, wA), pw = wq(b.parent); b.quaternion.copy(pw.invert().multiply(tq)); b.updateMatrixWorld(true); (api.blDbg = api.blDbg || {})[s + n] = [wA, +wq(b).angleTo(T).toFixed(3)]; }
      for (const k of [2, 3]) { const b = bone('CC_Base_' + s + '_Thumb' + k); if (b && BLQ[s + '_Thumb' + k]) { b.quaternion.slerp(BLQ[s + '_Thumb' + k], 0.6 * wA); } } }
    // v10: hand-on-hip contact anchor. The palm point (wrist -> middle knuckle, 60 %) is pinned to a spot fixed in the pelvis frame
    // (fit with scratch/contact.js against the live skin), so weight shift and breathing no longer open a gap or push the hand in.
    if (!api.noAnchor && PELV) for (const s of ['L', 'R']) { const PZ = ip[s], wA = Math.min(1, Math.max(0, PZ.hipw || 0)), an = ((ip.ancN = ip.name || ip.ancN) === 'hipBoth' ? HIPANCB : HIPANC)[s];
      if (wA < 0.01 || !an || !HB[s]) continue;
      PELV.updateWorldMatrix(true, false); const tg = new THREE.Vector3(an[0], an[1], an[2]).applyMatrix4(PELV.matrixWorld); if (ip.ancN !== 'hipBoth') tg.applyAxisAngle ? tg.add(new THREE.Vector3(0, 0, (api.hipFwd ?? 0.025)).applyQuaternion(wq(PELV.parent || PELV)).setY(0)) : 0;   /* vr2: palm a little forward on the side of the hip so the fingers show from the front camera (they sat behind the hip silhouette) */
      for (let it = 0; it < 2; it++) for (const n of [s + '_Forearm', s + '_Upperarm']) { const bb = R[n] && R[n].b; if (!bb) continue; const bp = wpos(bb);
        const pal = wpos(HB[s]).lerp(wpos(M1[s]), 0.6), dq = Q().slerp(Q().setFromUnitVectors(pal.sub(bp).normalize(), tg.clone().sub(bp).normalize()), wA);
        const pw = wq(bb.parent); bb.quaternion.copy(pw.clone().invert().multiply(dq).multiply(pw).multiply(bb.quaternion)); bb.updateMatrixWorld(true); } }
    // v10b: hipBoth also holds each hand's orientation in the pelvis frame (captured once the pose is reached), so torso sway can't roll the fingertips into the skin
    if (!api.noAnchor && PELV && ip.ancN === 'hipBoth') for (const s of ['L', 'R']) { const wA = Math.min(1, Math.max(0, ip[s].hipw || 0)), hb = HB[s]; if (!hb) continue;
      if (wA < 0.02) { HROT[s] = null; HROTt[s] = 0; continue; }   /* v15: the held hand orientation fades out with hipw (was dropped at 0.5: wrist snap at walk f62) */ const pq = wq(PELV);
      if (wA > 0.98) HROTt[s] += dt; if (!HROT[s] && HROTt[s] > 0.6) HROT[s] = pq.clone().invert().multiply(wq(hb));   // v13b: capture once the pose has settled (it was taken mid-transition)
      if (HROT[s]) { const tgt = wq(hb).slerp(pq.multiply(HROT[s]), wA); hb.quaternion.copy(wq(hb.parent).invert().multiply(tgt)); hb.updateMatrixWorld(true); } }
    if (ip.ancN !== 'hipBoth') { HROT.L = HROT.R = null; HROTt.L = HROTt.R = 0; }
    // fingers: slow breathing curl + occasional micro-curl ripple (index -> pinky), per hand
    for (const s of ['L', 'R']) { const F = fc[s]; F.next -= dtc;
      if (F.t < 0 && F.next <= 0) { F.t = 0; F.amp = 0.08 + rnd() * 0.1; F.dir = rnd() < 0.5 ? 1 : -1; F.next = (w.speaking > 0.5 ? 6 : 10) + rnd() * 12; }
      if (F.t >= 0) { F.t += dtc; if (F.t > 1.6) F.t = -1; } }
    const emF = (Math.max(0, lvl.nod - 0.05) * 1.5 + 0.7 * stress) * w.speaking;   // v10: phrase emphasis opens the free hand a little
    for (const F of FING) { const C = fc[F.s], ord = ['Index', 'Mid', 'Ring', 'Pinky'].indexOf(F.f), PZ = ip[F.s];
      const rk = 1 - Math.min(1, Math.max(0, PZ.hipw || 0));   // 1 = free hand, 0 = posed (hip)
      const amp = 0.035 + 0.025 * w.speaking;   // slow, out-of-phase per-finger curl (a bit more alive when speaking)
      let c = PZ.c + (PZ['c' + F.f] || 0) + rk * [0.06, 0.1, 0.14, 0.18][ord]   // soft resting cascade (index straightest)
        + rk * (amp * N(t * (0.15 + 0.035 * ord), 'fc' + F.s + F.f) + 0.6 * amp * N(t * 0.11, 'fc' + F.s)) + 0.015 * b
        + rk * MF[F.s][ord]   // Mixamo finger track (gestures)
        - rk * emF * (0.1 - 0.02 * ord)   // emphasis: index leads the opening
        - 0.09 * Math.max(0, gest[F.s].a) * (1 - 0.15 * ord) + 0.03 * ord * Math.max(0, gest[F.s].a);
      { const hw = Math.min(1, Math.max(0, PZ.hipw || 0)); if (hw > 0.02 && hw < 0.95) { const g = Math.min(1, Math.max(0, (hw - 0.7) / 0.25)); c -= (1 - g) * hw * Math.max(0, PZ.c + (PZ['c' + F.f] || 0)) + (1 - g) * 0.04 * ord; } }   /* v13h: fingers stay open until the hand is near contact (hipw > 0.7), ring/pinky most */
      c = Math.max(c, -0.12);   // v10b: stronger index lead may open past straight; allow only a slight hyperextension
      if (C.t >= 0) { const u = (C.t - ord * 0.09) / 1.2; if (u > 0 && u < 1) c += rk * C.dir * C.amp * Math.sin(Math.PI * u) ** 2; }   // rare relaxed flex (curl or open), rippling index -> pinky
      const wBH = api.blendHip ? Math.min(1, Math.max(0, PZ.hipw || 0)) : 0;
      F.segs.forEach((g, k) => { const nm = F.s + '_' + F.f + (k + 1); g.r.b.quaternion.copy(wBH > 0 && BLQ[nm] ? g.r.q0.clone().slerp(BLQ[nm], wBH) : g.r.q0).multiply(q.setFromAxisAngle(g.ax, F.sg * c * (k === 0 ? 0.6 : 1))); });
      if (F.sax) { const spv = (PZ.sp || 0) * (ord === 0 ? 1 : ord === 2 ? 0.5 : 1); F.segs[0].r.b.quaternion.multiply(q.setFromAxisAngle(F.sax, F.ssg * -spv)); } }
    for (const Th of THUMB) Th.r.b.quaternion.copy(api.blendHip && BLQ[Th.s + '_Thumb1'] && (ip[Th.s].hipw || 0) > 0 ? Th.r.q0.clone().slerp(BLQ[Th.s + '_Thumb1'], 0.6 * Math.min(1, ip[Th.s].hipw))   /* vr3: thumb relaxed 40% toward rest (was stretched) */ : Th.r.q0).multiply(q.setFromAxisAngle(Th.ax, Th.sg * ((ip[Th.s].tb || 0) + (1 - Math.min(1, Math.max(0, ip[Th.s].hipw || 0))) * (Math.max(-0.15, Math.min(0.3, MF[Th.s][4])) + 0.03 * N(t * 0.13, 'tb' + Th.s)))));   // v9d: thumb abduction (hand-on-hip)
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
    gz.hvy += (-2 * om * gz.hvy - om * om * (gz.hy - hY)) * dt; gz.hy += gz.hvy * dt;
    gz.hvx += (-2 * om * gz.hvx - om * om * (gz.hx - hX)) * dt; gz.hx += gz.hvx * dt;
    // v4: speech head motion is a critically damped spring kicked by syllables (velocity impulses), never a position step.
    //     v3 added 0.03*stress straight to the head pitch with an 80 ms attack -> ~0.6 deg/frame jumps that made the
    //     alpha-tested back hair seen through the see-through neck crawl (the 5-7 s neck flicker).
    if (syl) { const a = Math.min(1, L * 1.4) * w.speaking, st0 = sp.stressT === 0;
      hs.vx += (st0 ? 0.55 * sp.stress : 0.16 + 0.12 * rnd()) * a;                 // nod down on each syllable, bigger on stress
      hs.vz += (st0 ? (rnd() < 0.5 ? -1 : 1) * 0.35 : (rnd() - 0.5) * 0.18) * a;   // small tilt, a clear one on stress
      hs.vy += (rnd() - 0.5) * 0.16 * a; }
    { const om3 = 11, om4 = 8; hs.vx += (-2 * om3 * hs.vx - om3 * om3 * hs.x) * dt; hs.x += hs.vx * dt;
      hs.vz += (-2 * om4 * hs.vz - om4 * om4 * hs.z) * dt; hs.z += hs.vz * dt; hs.vy += (-2 * om4 * hs.vy - om4 * om4 * hs.y) * dt; hs.y += hs.vy * dt;
      const tgt = w.speaking * (0.03 * lvl.nod + 0.008 * N(t * 0.9, 'nod') + 0.07 * ph.nodK * nodE - 0.03 * lift) + 0.03 * sg2 * (1 - 2 * (bph % 1 > 0.4));
      hs.vs += (-2 * 7 * hs.vs - 49 * (hs.s - tgt)) * dt; hs.s += hs.vs * dt; }
    const hy = hs.y + gz.hy + 0.04 * D('hy', 2, 6) + 0.012 * N(t * 0.37, 'hy') + 0.005 * N(t * 1.3, 'hy2');
    const hx = gz.hx + 0.022 * D('hx', 2, 7) + 0.008 * N(t * 0.29, 'hx') + 0.004 * N(t * 1.1, 'hx2') + 0.008 * b - p.up * 0.35 + 0.05 * settle
             + hs.s + hs.x + stP;   // beats on stress, nod at phrase end
    const hz = hs.z + p.tilt + 0.026 * D('hz', 3, 9) + 0.008 * N(t * 0.21, 'hz') + 0.25 * r + 0.07 * ph.tiltK * nodE * w.speaking + stR;
    const hyL = hy - 0.27 * fol.y, hxL = hx - 0.05 * fol.x;   // the upper spine already carries part of the turn
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

    for (const s of slots) for (const [n, i] of Object.entries(s.idx)) s.inf[i] = Math.max(0, Math.min(1, morphs[n] || 0));

    // ---- v10 walk layer: blend the baked walk over the body; travel accumulates only while walking (feet stay planted at full weight) ----
    if (WTRK && WTR && wph !== 0) { const n = WTRK.n, fr = dt * (WTR.rate || 1) * WTR.fps, par = hip ? hip.b.parent : null;
      // samplers: walk cycle (in place: within-cycle glide removed) and a transition clip (in place; travel from tz)
      const sWalk = (f, QO, HQ, HP) => { const fi = ((f % n) + n) % n, i0 = Math.floor(fi), i1 = (i0 + 1) % n, u = fi - i0;
        WTRK.bones.forEach((nm, k) => { (QO[k] || (QO[k] = Q())).fromArray(WTRK.q[i0][k]).slerp(wqb.fromArray(WTRK.q[i1][k]), u); });
        HQ.fromArray(WTRK.hipQ[i0]).slerp(wqb.fromArray(WTRK.hipQ[i1]), u);
        const SL = par.worldToLocal(V3().set(0, 0, WTRK.stride)).sub(par.worldToLocal(V3())), p1 = V3().fromArray(WTRK.hip[i1]); if (i1 === 0) p1.add(SL);
        HP.fromArray(WTRK.hip[i0]).lerp(p1, u).addScaledVector(SL, -fi / n); };
      const sClip = (C, f, QO, HQ, HP) => { const fi = Math.max(0, Math.min(C.n - 2, f)), i0 = Math.min(C.n - 2, Math.floor(fi)), i1 = i0 + 1, u = fi - i0;
        WTR.bones.forEach((nm, k) => { (QO[k] || (QO[k] = Q())).fromArray(C.q[i0][k]).slerp(wqb.fromArray(C.q[i1][k]), u); });
        HQ.fromArray(C.hipQ[i0]).slerp(wqb.fromArray(C.hipQ[i1]), u); HP.fromArray(C.hip[i0]).lerp(V3().fromArray(C.hip[i1]), u); return C.tz[i0] + (C.tz[i1] - C.tz[i0]) * u; };
      let d = 0, x = 0, A = null;
      // join offsets (hip-parent local): the clips' in-place origin differs from the walk's; measured mid-crossfade so the planted foot does not slide, folded into GL when the clip hands over
      if (!WTR.offS) { const t1 = V3(), t2 = V3(), hq = Q(), tq = [], [J0, JW, JN] = WTR.startJoin, [SJ, S0, SN] = WTR.stopJoin;
        sClip(WTR.start, J0 + JN / 2, tq, hq, t1); sWalk(JW + JN / 2, tq, hq, t2); WTR.offS = t1.clone().sub(t2);
        sClip(WTR.stop, S0 + SN / 2, tq, hq, t1); sWalk(SJ + SN / 2, tq, hq, t2); WTR.offE = t2.clone().sub(t1); WTR.offS.z = 0; WTR.offE.z = 0; WTR.offS.x = 0; WTR.offE.x = 0; /* local z is height: keep the vertical out of the travel */ api.walkOff = [WTR.offS.toArray(), WTR.offE.toArray()]; }
      if (wph === 1) { const C = WTR.start, [J0, JW, JN] = WTR.startJoin; const z0 = sClip(C, sT, WPB, wHB, wHPB); sT += fr; const z1 = sClip(C, sT, WPB, wHB, wHPB); d = z1 - z0;
        wk = Math.min(1, wk + dt / 0.3);   // short crossfade from idle into the clip's first (standing) frames
        if (sT > J0) { x = wsm((sT - J0) / JN); wT = JW + (sT - J0); sWalk(wT, WPQ, wHQ, wHP); wHP.add(WTR.offS); d = (1 - x) * d + x * fr * WTRK.stride / n; A = 'mix'; }
        if (sT >= J0 + JN) { wph = 2; x = 1; GL.add(WTR.offS); wHP.sub(WTR.offS); } }
      else if (wph === 2) { const f0 = ((wT % n) + n) % n; wT += fr; const f1 = ((wT % n) + n) % n; d = fr * WTRK.stride / n; sWalk(wT, WPQ, wHQ, wHP); x = 1; A = 'walk';
        const J = WTR.stopJoin[0]; if (!walkOn && (f0 < J && (f1 >= J || f1 < f0))) { wph = 3; WTR.fE = 0; sT = WTR.stopJoin[1] + (f1 >= J ? f1 - J : f1 + n - J); } }
      else if (wph === 3) { const C = WTR.stop, [, S0, JN] = WTR.stopJoin; const z0 = sClip(C, sT, WPB, wHB, wHPB); sT += fr * Math.max(0.06, Math.min(1, (C.n - 2 - sT) / (api.stopEase ?? 16)));   /* v15d: decelerate over the last ~20 clip frames (was 7) so the lean-out eases instead of halting (spine 1.1 to 0 deg/frame at f290) */ const z1 = sClip(C, sT, WPB, wHB, wHPB);   /* the clip ends mid-motion: ease its last frames to rest (no halt) */
        wHPB.addScaledVector(WTR.offE, 1 - (WTR.fE || 0)); const y = wsm((sT - S0) / JN); wT += fr; sWalk(wT, WPQ, wHQ, wHP); x = 1 - y; d = y * (z1 - z0) + x * fr * WTRK.stride / n; A = 'mix'; if (sT >= C.n - 2.02) { wk = Math.max(0, wk - dt / 0.8); const p = 1 - wk; GL.addScaledVector(WTR.offE, p - (WTR.fE || 0)); WTR.fE = p; if (wk <= 0) { wph = 0; wk = 0; WTR.fE = 0; } } }   /* settle: the clip holds its last frame while idle fades back in; the join offset moves into the travel at the same rate */   // settle: the clip holds its last frame while idle fades back in
      else if (wph === 4) { sClip(WTR.stop, WTR.stop.n - 1, WPB, wHB, wHPB); wk = Math.max(0, wk - dt / 0.8); x = 0; if (wk <= 0) { wph = 0; wk = 0; } }
      // pose = clip pose (WPB) blended toward the walk pose (WPQ) by x, then over the idle body by wk (smoothstep)
      const ws = wsm(wk); if (wph === 1 || wph === 2) wkA = Math.min(wk, wkA + dt / 0.75); else wkA = Math.min(wkA, wk); const wsA = wsm(wkA); if (wph === 1 || wph === 2) api.__wkU = Math.min(wk, (api.__wkU || 0) + dt / 0.5); else api.__wkU = Math.min(api.__wkU || 0, wk); const wsU = wsm(api.__wkU);   /* v15b2: spine/neck/head walk-in over 0.5 s (the 0.3 s fade ended in a kink at f69 that the arms inherit) */
      WTR.bones.forEach((nm, k) => { const b = WB[nm]; if (!b) return; if (x > 0) WPB[k].slerp(WPQ[k], x); b.quaternion.slerp(WPB[k], /(Clavicle|Upperarm|Forearm|Hand|Index|Mid|Ring|Pinky|Thumb)/.test(nm) ? wsA : /(Spine0|Neck|Head)/.test(nm) ? wsU : ws); });
      if (hip && par) { if (x > 0) { wHB.slerp(wHQ, x); wHPB.lerp(wHP, x); } hip.b.quaternion.slerp(wHB, ws);
        const SLu = par.worldToLocal(V3().set(0, 0, 1)).sub(par.worldToLocal(V3())); GL.addScaledVector(SLu, d); hip.b.position.lerp(wHPB.add(GL), ws);   /* travel first, so the pose and its travel are the same frame */ GW.copy(par.localToWorld(hipB0.clone().add(GL))).sub(par.localToWorld(hipB0.clone())); }
      { /* v15d r2: torso lean-out low-pass (2 cascaded 1st-order slerp filters) through stop + settle, faded out after */ const TS = api.__ts = api.__ts || { f1: {}, f2: {}, on: 0 }; const act = WTR && (wph === 3 || wph === 4); TS.on = act ? 1 : Math.max(0, TS.on - dt / 0.5); const al = 1 - Math.exp(-dt / (api.tsTau ?? 0.11));
        for (const nm of ['Hip', 'Waist', 'Spine01', 'Spine02']) { const b = nm === 'Hip' ? (hip && hip.b) : WB[nm]; if (!b) continue; if (!TS.f1[nm] || !(TS.on > 0) || api.tsOff) { TS.f1[nm] = b.quaternion.clone(); TS.f2[nm] = b.quaternion.clone(); continue; } const aa = nm === 'Hip' ? 1 - Math.exp(-dt / (api.tsTauH ?? 0.06)) : al; TS.f1[nm].slerp(b.quaternion, aa); TS.f2[nm].slerp(TS.f1[nm], aa); b.quaternion.slerp(TS.f2[nm], wsm(TS.on)); } }
      api.walkPhase = wph; api.walkDbg = { sT, wT, x, wk, d };
      root.updateMatrixWorld(true); }
    // vr2: toe pin. The baked walk drags the push-off toe forward ~10 cm along the floor before it lifts (heel up, toe 3 cm high: reads as a slide).
    // While a toe is on the floor during the walk its world xz is held; the leg is re-solved (two-bone, current knee plane, foot world rotation kept). The hold eases off over ~4 frames once the toe lifts.
    if (WTR && hip && LEGS.length) { api.__tp = api.__tp || {}; const walking = wph === 1 || wph === 2 || wph === 3;
      /* vr5: when a lifting toe is out of the leg's reach (stop clip f259: leg straight, toe could only rise 12-17 mm) raise the hips by last frame's shortfall, eased */
      { const tgt = walking ? Math.min(0.03, api.__hipNeed || 0) : 0; api.__hipL = (api.__hipL || 0) + (tgt - (api.__hipL || 0)) * Math.min(1, dt / (tgt > (api.__hipL || 0) ? 0.04 : 0.2)); api.__hipNeed = 0;
        if (api.__hipL > 1e-4 && hip.b.parent) { const up = hip.b.parent.worldToLocal(V3().set(0, 1, 0)).sub(hip.b.parent.worldToLocal(V3())); hip.b.position.addScaledVector(up, api.__hipL); root.updateMatrixWorld(true); } }
      for (const L of LEGS) { const toe = L.toe || (L.toe = L.ft.children.find((c) => /ToeBase$/.test(c.name))); if (!toe) continue;
        const st = api.__tp[L.ft.name] || (api.__tp[L.ft.name] = { lock: null, off: V3(), w: 0 }); const T = wpos(toe);
        const fadeOnly = !walking; if (fadeOnly) { st.lock = null; if (api.toePin === 0 || api.noStopFade || !(st.w > 1e-3) || st.wTmp) { st.w = 0; continue; } st.w = Math.max(0, st.w - dt / (api.tpStopFade ?? 1.0)); st.lf = 0; }   /* v15d: when the walk ends the pinned toe hands over to idle over 1 s (was dropped in one frame: R toe 2.8 cm jump f337) */
        const spd = fadeOnly ? 0 : st.prev && dt > 0 ? Math.hypot(T.x - st.prev.x, T.z - st.prev.z) / dt : 9; st.prev = T.clone();   /* raw (unpinned) toe speed */
        if (st.lock && (T.y > (wph === 3 ? 0.08 : (api.tpUp ?? 0.045)) || Math.hypot(st.lock.x - T.x, st.lock.z - T.z) > (wph === 3 ? 0.2 : (api.tpMax ?? 0.12)))) { st.rel = Math.hypot(st.lock.x - T.x, st.lock.z - T.z) > 0.03 ? (api.tpRelL ?? 0.45) : 0.12; st.lock = null; st.lf = Math.max(st.lf || 0, (api.tpRelLift ?? 0) * ((api.tpClr ?? 0.04) - T.y)); }   /* vr6: a release with >3 cm of debt (stop clip L f259-260: 61 mm one-frame jump; walk L f139, R f117) eases over 0.45 s and its lift rises through the smoothed lift, not in one frame */   /* vr4: release frame lifts first */
        if (!fadeOnly && !st.lock && T.y < (api.tpDn ?? 0.035) && spd < (api.tpV ?? 1.0))   /* v15b: lock a bit earlier (was 0.026 m, 0.6 m/s) */ { st.lock = T.clone(); }
        if (st.lock) { st.off.set(st.lock.x - T.x, 0, st.lock.z - T.z); st.w = 1; { const dbt = Math.hypot(st.off.x, st.off.z), cap = dbt > 0.025 ? 0.025 + (dbt - 0.025) * (wph === 3 ? 1 : (api.tpSoft ?? 0.4)) : dbt; if (dbt > 1e-6) st.off.multiplyScalar(cap / dbt); }   /* vr6: soft pin (all walk phases): past 2.5 cm of debt the toe creeps (40% of the baked motion) so the release has less to give back */ if (wph === 3) api.__hipNeed = Math.max(api.__hipNeed || 0, 0.02 * Math.min(1, Math.max(0, (Math.hypot(st.off.x, st.off.z) - 0.05) / 0.04))); }   /* vr5: stop clip: a pinned toe that has built up >5 cm of debt is about to release with a straight leg; raise the hips ahead of it */ else st.w = Math.max(0, st.w - dt / (st.rel ?? 0.12));
        /* a moving toe skimming the floor (start/stop clip steps dip to y<=0 at 3 m/s) also reads as a slide: give it a few cm of clearance */
        const lift = st.lock ? 0 : Math.max(0, (api.tpClr ?? 0.04) - T.y) * Math.max(0, Math.min(1, (spd - 1) / 0.6)); st.lf = (st.lf || 0) + (lift - (st.lf || 0)) * Math.min(1, dt / (st.rel > 0.12 && st.w > 0 ? 0.1 : 0.05)); st.lf = Math.max(st.lf, Math.max(0, 0.006 - T.y)); /* vr4: pinned toes sank to -23 mm under the floor right before lift-off; floor clamp also while pinned */ if (!st.lock) st.lf = Math.max(st.lf, Math.max(0, 0.012 - T.y), spd > 1.5 && !(st.rel > 0.12 && st.w > 0) ? Math.max(0, (api.tpClr ?? 0.04) - T.y) : 0);   /* vr6: not during an eased debt release (the smoothed lift carries it) */   /* vr3: one-frame skims (f117 R, f259-260 L) slipped under the smoothed lift: unsmoothed floor clamp + full clearance for fast toes */
        if (st.w <= 1e-3) st.off.set(0, 0, 0); st.off.y = (st.lock ? Math.min(0, st.lock.y - T.y) : 0) + st.lf / Math.max(1e-3, wsm(Math.max(st.w, 1e-3)));   /* vr5: a pinned toe also keeps its height when the hips rise */
        if ((st.w <= 1e-3 && st.lf < 1e-4) || st.off.lengthSq() < 1e-8) continue; if (st.w <= 1e-3) st.w = 1, st.off.set(0, st.lf, 0), st.wTmp = 1; else st.wTmp = 0;
        const H = wpos(L.th), K = wpos(L.ca), A = wpos(L.ft), fq0 = wq(L.ft), A2 = A.clone().addScaledVector(st.off, wsm(st.w));
        const l1 = K.distanceTo(H), l2 = A.distanceTo(K), d = A2.clone().sub(H); if (st.lf > 0.01) api.__hipNeed = Math.max(api.__hipNeed || 0, d.length() - (l1 + l2 - 0.004)); let dist = Math.min(d.length(), l1 + l2 - 1e-4); d.normalize();
        const n0 = K.clone().sub(H); const pole = n0.sub(d.clone().multiplyScalar(n0.dot(d))).normalize();
        const a = (l1 * l1 - l2 * l2 + dist * dist) / (2 * dist), h = Math.sqrt(Math.max(0, l1 * l1 - a * a)), K2 = H.clone().addScaledVector(d, a).addScaledVector(pole, h);
        setW(L.th, Q().setFromUnitVectors(K.clone().sub(H).normalize(), K2.clone().sub(H).normalize()).multiply(wq(L.th))); L.th.updateMatrixWorld(true);
        const Kn = wpos(L.ca), An = wpos(L.ft); setW(L.ca, Q().setFromUnitVectors(An.clone().sub(Kn).normalize(), A2.clone().sub(Kn).normalize()).multiply(wq(L.ca))); L.ca.updateMatrixWorld(true);
        setW(L.ft, fq0); L.th.updateMatrixWorld(true); if (st.wTmp) st.w = 0; } }
    // v14f: walk-out settle. From the stop clip into idle the right arm swung back and the hand lay on the buttock (3/4-back camera: no fingers, read as a blob in the hip).
    // Hold the right arm a little abducted and forward with a touch more elbow bend while the stop clip and its fade run, then ease it out slowly in idle.
    { const inS = WTR && (wph === 3 || wph === 4 || (wph === 0 && api.__soW > 0)); const tgt = (wph === 3 || wph === 4) ? 1 : 0;
      api.__soW = Math.max(0, Math.min(1, (api.__soW || 0) + (tgt ? dt / 0.6 : -dt / (api.soOut ?? 2.5))));
      const k = wsm ? wsm(api.__soW) : api.__soW;
      /* vr2: both arms. The left hand settles beside the front of the hip and, from the 3/4-front camera, its fingers overlapped the hip silhouette and merged (Vela 0:11). Same offset, mirrored. */
      for (const S of ['R', 'L']) { const ua = R[S + '_Upperarm'] && R[S + '_Upperarm'].b, fa = R[S + '_Forearm'] && R[S + '_Forearm'].b, hd = R[S + '_Hand'] ? R[S + '_Hand'].b : fa;
        const hw = Math.min(1, Math.max(0, (ip[S] && ip[S].hipw) || 0)), a = k * (1 - wsm((hw - 0.8) / 0.18)) * (S === 'L' ? (api.soL ?? 1) : 1);   /* vr4: L x2.4 (was 1: crops at f315-344 unchanged, hand still hid behind the hip) */   /* keep the arm out through the hip-pose transit, release only as the hand arrives (contact pass takes over at 0.85) */
        if (!(inS && a > 1e-3 && hip && ua && fa)) continue; root.updateMatrixWorld(true);
        const fwd = V3().set(0, 0, 1)   /* she faces and travels +z (world) */, lat = V3().set(0, 1, 0).cross(fwd).normalize();   /* lat: her left */
        const turn = (bb, axis, ang) => { const pw = wq(bb.parent), dq = Q().setFromAxisAngle(axis, ang); bb.quaternion.copy(pw.clone().invert().multiply(dq).multiply(pw).multiply(bb.quaternion)); bb.updateMatrixWorld(true); };
        const sh = wpos(ua), h0 = wpos(hd).sub(sh);
        const sAb = (fwd.clone().cross(h0).dot(lat) < 0 ? 1 : -1) * (S === 'L' ? -1 : 1);   /* sign that moves the hand away from her body */
        turn(ua, fwd, sAb * (api.soAb ?? 0.12) * a * (S === 'L' ? (api.soLab ?? 3.2) : 1)); turn(ua, lat, -(api.soFl ?? 0.08) * a);   /* vr5b: L arm out to the side (x3.2 abduction, no extra elbow bend: bending folded the forearm onto her back) */
        const el = wpos(fa), w0 = wpos(hd).sub(el), eax = w0.clone().cross(fwd).normalize();
        if (eax.lengthSq() > 0.5 && S !== 'L') turn(fa, eax, (api.soEl ?? 0.12) * a);
        (api.soDbg || (api.soDbg = {}))[S] = { dh: +wpos(hd).sub(sh).sub(h0).length().toFixed(4), a, sAb, hw }; } }
    // the shading uses a few world-space anchors (face centre, navel, hip height): carry them with her travel (walk-copy fix); at rest they are unchanged
    { const L = opts.links || {}, U = L.U; if (U && R.Head && hip) { const hd = wpos(R.Head.b).sub(HEAD0).sub(GW).multiplyScalar(wk).add(GW), hp = wpos(hip.b).sub(HIP0).sub(GW).multiplyScalar(wk).add(GW);
        U.FACE.value.set(U.rest.face.x + hd.x, U.rest.face.y + hd.y, U.rest.face.z + hd.z, U.rest.face.w);
        U.NAVEL.value.set(U.rest.navel.x + hp.x, U.rest.navel.y + hp.y, U.rest.navel.z + hp.z, U.rest.navel.w); U.HIPY.value = U.rest.hipY + hp.y; }
      api.glide = GW.z; if (L.aura) L.aura.position.z = GW.z; if (L.floorRing) L.floorRing.position.z = GW.z; }
    // ---- light: glow breathes; pulses with the voice; rim up while listening; shimmer while thinking ----
    uAnim.value.set((1 + 0.04 * (b - 0.5)) * (1 + 0.16 * lvl.med + 0.1 * lvl.slow), p.rim + 0.12 * lvl.med, p.sh * (0.75 + 0.25 * N(t * 0.9, 'shm')), 0);
    // v13b: hip-hand contact pass. Each frame, while a hand is on the hip, the palm and each fingertip pad are pulled to the skin
    // (palm centre 13 mm, finger pads 6 mm, thumb pad 7 mm from the surface: real contact, no sinking). Signed distance against
    // the live skinned hip skin near the hand (arm verts excluded); the palm by a small forearm/upper-arm turn, the fingers and
    // thumb by a turn of their first joint. Stateless per frame, so it follows breathing, weight shift and torso sway.
    if (!api.noContact && PELV) for (const s of ['L', 'R']) { const PZ = ip[s]; let wA = Math.min(1, Math.max(0, PZ.hipw || 0));
      if (wA < 0.02 && HB[s] && M1[s] && api.gestContact) { PELV.updateWorldMatrix(true, false); const an = HIPANC[s], tg = new THREE.Vector3(an[0], an[1], an[2]).applyMatrix4(PELV.matrixWorld), dP = wpos(HB[s]).lerp(wpos(M1[s]), 0.6).distanceTo(tg);
        const nw = 1 - Math.min(1, Math.max(0, (dP - 0.07) / 0.08)); if (nw > 0) wA = 0.3 * nw * nw * (3 - 2 * nw); }   /* v15b (rejected, opt-in only): push-only contact for a gesture hand near the hip; made 30 px finger snaps */
      if (wA < 0.02 && HB[s] && M1[s] && !api.noGestCurl) { PELV.updateWorldMatrix(true, false); const an = HIPANC[s], tg = new THREE.Vector3(an[0], an[1], an[2]).applyMatrix4(PELV.matrixWorld), dP = wpos(HB[s]).lerp(wpos(M1[s]), 0.6).distanceTo(tg);
        api["__gcD" + s] = dP; const n0 = 1 - Math.min(1, Math.max(0, (dP - 0.09) / 0.1)), nT = n0 * n0 * (3 - 2 * n0), gk = '__gc' + s; api[gk] = (api[gk] || 0) + (nT - (api[gk] || 0)) * Math.min(1, dt / 0.2); const cv = (api.gestCurl ?? 0.3) * api[gk];
        if (cv > 1e-3) { for (const F of FING) { if (F.s !== s) continue; const WS = [0.45, 0.35, 0.2]; F.segs.forEach((g, k) => g.r.b.quaternion.multiply(Q().setFromAxisAngle(g.ax, F.sg * cv * WS[k]))); } HB[s].updateMatrixWorld(true); } }   /* v15b2: a gesture hand resting near the hip (AskingAQuestion) curls its fingers a little, by a smooth proximity weight (no contact test, so no snaps) */
      if (wA < 0.02 || !HB[s]) { CT[s] = null; continue; }
      // v13c: contact on the real meshes. Hand-mesh vertices (sampled) against the live hip skin; palm/thenar and thumb pushed out
      // of the body at full strength and pulled onto it (0.5 mm) once the pose has arrived; fingers bend only about their curl axis.
      root.updateMatrixWorld(true); const pal = () => wpos(HB[s]).lerp(wpos(M1[s]), 0.6);
      { const c0 = pal(); if (!CT[s] || CT[s].c0.distanceTo(c0) > 0.04) { CT[s] = ctBuild(c0); CT[s].c0 = c0; } }
      const C = CT[s]; C.w = wA; ctSkin(C); ctNear(C, pal(), 0.09); const kp = Math.min(1, Math.max(0, (wA - 0.85) / 0.15));
      const H = hvGet(s); const TG = 0.002;
      const deep = (g) => { let best = null; for (const it of H[g]) { const v = hvPos(it); const r = ctSD(C, v, it); if (!best || r.d < best.d) best = { d: r.d, n: r.n, p: v }; } return best; };
      const move = (r, tgt, bones, k) => { if (!r) return; const e = Math.max(-0.015, Math.min(0.003, (r.d - tgt) * (r.d < tgt ? 1 : k)));   /* v13e: pulls capped at 3 mm (the fitted pose does the placing), pushes up to 15 mm */ if (Math.abs(e) < 1e-4) return; let p = r.p; const goal = p.clone().addScaledVector(r.n, -e);
        for (const bb of bones) { const bp = wpos(bb), a = p.clone().sub(bp), g = goal.clone().sub(bp); if (a.lengthSq() < 1e-8) continue;
          const dq = Q().setFromUnitVectors(a.normalize(), g.normalize()); const pw = wq(bb.parent); bb.quaternion.copy(pw.clone().invert().multiply(dq).multiply(pw).multiply(bb.quaternion)); bb.updateMatrixWorld(true); p = goal; } };
      const FA = R[s + '_Forearm'] && R[s + '_Forearm'].b;
      for (let it = 0; it < 3; it++) { const r = deep('Palm'); move(r, TG, [FA], kp); }
      { const t1 = R[s + '_Thumb1'] && R[s + '_Thumb1'].b; if (t1) for (let it = 0; it < 4; it++) { const r = deep('Thumb'); if (r && (r.d < 0 || (api.blendHip && kp > 0))) move(r, TG, [t1], r.d < 0 ? 1 : kp); } }   /* v14: the Blender thumb may also be pulled the last mm onto the waist */
      for (const f of ['Index', 'Mid', 'Ring', 'Pinky']) { const Fe = FING.find((q) => q.s === s && q.f === f); if (!Fe || !H[f].length) continue; const b1 = Fe.segs[0].r.b;
        const qb = Fe.segs.map((g) => g.r.b.quaternion.clone()), WS = [0.45, 0.35, 0.2];
        const setF = (dl) => { Fe.segs.forEach((g, k) => g.r.b.quaternion.copy(qb[k]).multiply(Q().setFromAxisAngle(g.ax, Fe.sg * dl * WS[k]))); b1.updateMatrixWorld(true); };
        const cost = () => { const d = deep(f).d; return { e: ((d - TG) / 0.001) ** 2 + 50 * (Math.max(0, -d) / 0.001) ** 2, pen: d < 0 }; };
        const c0 = cost(); let bd = 0, be = c0.e;
        const FR = api.blendHip && wA > 0.9 ? (api.flexR ?? 0.36) : 1.2;   /* v14b: full flex range on the way in/out (ring/pinky cut 8 mm at hipw 0.3-0.45) */ for (let dl = -FR; dl <= FR + 0.01; dl += FR / 8) { setF(dl); const c = cost(); if (c.e < be) { be = c.e; bd = dl; } }
        for (const dd of [-0.07, -0.035, 0.035, 0.07]) { setF(bd + dd); const c = cost(); if (c.e < be) { be = c.e; bd += dd; } }
        for (const dd of [-0.015, 0.015]) { setF(bd + dd); const c = cost(); if (c.e < be) { be = c.e; bd += dd; } }
        setF(bd * (c0.pen ? 1 : kp)); }   /* v14: the Blender pose sets the finger shape; the flex search only trims the last mm (range FR) */
      // v13e: on the way in/out the ring/pinky edge can still cut into the hip/thigh after the finger flex; turn the wrist just enough to clear it
      for (let it = 0; it < 4; it++) for (const f of ['Pinky', 'Ring', 'Mid', 'Index']) { const r = H[f].length && deep(f); if (!r || r.d >= 0) continue; move(r, TG, [HB[s]], 1); }
      for (let it = 0; it < 2; it++) { const r = deep('Palm'); if (!r || r.d >= 0) break; move(r, TG, [FA], 1); }
      if (api.contactLog) { C.log = {}; for (const g of ['Palm', 'Thumb', 'Index', 'Mid', 'Ring', 'Pinky']) { const r = deep(g); C.log[g] = r ? +(r.d * 1000).toFixed(1) : null; } } }
    /* v15: finger/thumb output filter. Two cascaded first-order lags (tau 45 ms each) on every finger and thumb bone's local rotation, so the
       hip-pose blend, the hipw gate and the contact flex grid search can never snap a finger in one frame; the Mixamo finger data passes through (about 90 ms lag). */
    if (!api.noFingerFilter) { if (!FFB) { FFB = []; for (const F of FING) for (const g of F.segs) FFB.push({ b: g.r.b }); for (const s of ['L', 'R']) for (const k of [1, 2, 3]) { const bb = bone('CC_Base_' + s + '_Thumb' + k); if (bb) FFB.push({ b: bb }); } }
      const al = api.freezeClocks ? 1 : 1 - Math.exp(-Math.min(dt, 0.1) / 0.045);
      for (const e of FFB) { const qt = e.b.quaternion; if (!e.q1 || al >= 1) { e.q1 = qt.clone(); e.q2 = qt.clone(); continue; } e.q1.slerp(qt, al); e.q2.slerp(e.q1, al); qt.copy(e.q2); } root.updateMatrixWorld(true); }
    api.moDbg = mo.slots.map((sl) => [sl.i, +sl.w.toFixed(3), +sl.t.toFixed(2), sl.m ? 1 : 0]);   // v15 test hook: active gesture segments
    api.dbg = { t, b, wgt, ipn: ip.name, ips: ip.side, ...(api.debugBones ? { foot: Math.max(0, ...LEGS.map((L) => wpos(L.ft).distanceTo(L.A))), hipY: hip ? wpos(hip.b).y : 0 } : {}), vow: sp.vow, cons: inCons ? sp.cons : '', stress, phr: ph.on, gL: gest.L.a, gR: gest.R.a, gn: gest.next, gh: gest.hold, gLt: gest.L.tgt, stR, stP, gx, gy, hx, hy, ex: eyX, ey: eyY, bL, bR, L, glow: uAnim.value.x, rim: uAnim.value.y, sh: uAnim.value.z, flow: p.flow, settle, jaw: sp.jaw, smile: morphs.Mouth_Smile_L, w: { ...w } };
    return p.flow;   // swirl/thread flow rate (aether.js advances uFlow with it)
  }
  return { update, api };
}
