// anim-mixer.js: body motion from authored clips baked in ellah-anim.glb, played by three.js AnimationMixer.
// The original animator (anim.js, imported under a different URL so the import map does not loop) still runs first for
// the face, lips, eyes, neck and head; the mixer then writes every body bone its clips carry. All timing is dt-driven.
import { createAnimator as createBase } from './anim.js?base';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
// Arelis: the clip file is not shipped in web/. The host passes ?clips=<file url>; else it sits beside the mesh (?glb=);
// else ./ellah-anim.glb. The clips are required: if they fail to load, an error is logged and the body holds its rest pose.
const Q = new URLSearchParams(location.search);
const CLIP_URL = Q.get('clips') || (Q.get('glb') ? Q.get('glb').replace(/[^/]*$/, 'ellah-anim.glb') : './ellah-anim.glb');
const ALIAS = { talking: 'speaking', rest: 'idle' };   // same names anim.js accepts
const KEEP_BASE = /^CC_Base_(NeckTwist0[12]|Head|FacialBone|JawRoot|.*Eye|Tongue.*|Teeth.*|UpperJaw)\./;   // head rows stay from anim.js
const POOLS = {   // repeats = weight
  idle: ['Idle', 'Idle', 'WeightShift', 'WeightShift', 'v2_BreathingIdle', 'v2_BreathingIdle', 'v2_HappyIdle'],
  listening: ['Listening', 'Listening', 'v2_ThoughtfulHeadNod', 'Agreeing'],   // no idle clip: entering listening always fades away from idle
  thinking: ['v2_BreathingIdle', 'Idle', 'v2_ThoughtfulHeadNod'],
  speaking: ['Talking', 'Talking', 'Agreeing'],
  done: ['v2_BreathingIdle', 'Idle'] };export function createAnimator(THREE, root, face, uAnim, opts = {}) {
  const REST = [];   // every body bone's rest transform (the GLB's node pose, arms down), taken before anything moves
  root.traverse((o) => { if (o.isBone && !KEEP_BASE.test(o.name + '.')) REST.push([o, o.position.clone(), o.quaternion.clone()]); });
  const holdRest = () => { for (const [o, p, q] of REST) { o.position.copy(p); o.quaternion.copy(q); } };
  const base = createBase(THREE, root, face, uAnim, opts), api = base.api;
  let seed = 1234567; const rnd = () => ((seed = (seed * 1103515245 + 12345) >>> 0) / 4294967296);   // own rng: never touches anim.js's
  const M = { mixer: null, clips: {}, cur: null, curName: '', mode: 'idle', left: 0, fade: 0.8 };
  api.mixer = M; api.mixerReady = false; const TW = [], tq = new THREE.Quaternion(), Y = new THREE.Vector3(0, 1, 0);
  api.mixerProbe = (names) => names.map((n) => { const o = root.getObjectByName(n); if (!o) return null; const v = new THREE.Vector3(); o.getWorldPosition(v); return [v.x, v.y, v.z]; });   // test hook
  const baseSet = api.setState; api.setState = (m) => { M.mode = ALIAS[m] || m; M.wantSwitch = true; return baseSet(m); };
  new GLTFLoader().load(CLIP_URL, (g) => {
    M.mixer = new THREE.AnimationMixer(root);
    for (const c of g.animations) { c.tracks = c.tracks.filter((t) => !KEEP_BASE.test(t.name)); M.clips[c.name] = c; }
    // wrist roll spread: clips carry no twist tracks, so a big hand roll would candy-wrap the forearm. Share the hand's
    // roll about the forearm axis (+Y) with ForearmTwist01 (20%) and Twist02 (+30%, i.e. 50% at mid forearm). Pure function of the pose.
    for (const s of ['L', 'R']) { const h = root.getObjectByName('CC_Base_' + s + '_Hand'), t1 = root.getObjectByName('CC_Base_' + s + '_ForearmTwist01'), t2 = root.getObjectByName('CC_Base_' + s + '_ForearmTwist02');
      let sk = null; root.traverse((x) => { if (x.isSkinnedMesh && !sk && x.skeleton.bones.includes(h)) sk = x.skeleton; });
      if (!h || !t1 || !t2 || !sk) continue;
      const wf = sk.boneInverses[sk.bones.indexOf(h.parent)].clone().invert(), wh = sk.boneInverses[sk.bones.indexOf(h)].clone().invert();
      const qf = new THREE.Quaternion(), qh = new THREE.Quaternion(), v = new THREE.Vector3(), sc = new THREE.Vector3();
      wf.decompose(v, qf, sc); wh.decompose(v, qh, sc);
      TW.push({ h, t1, t2, rest: qf.invert().multiply(qh).invert() }); }
    api.mixerReady = true; api.mixerClips = Object.keys(M.clips);
    console.info('[avatar] mixer clips=' + api.mixerClips.length);
  }, undefined, (e) => { api.mixerError = String(e); console.error('[avatar] clips missing at ' + CLIP_URL); });
  api.mixerPlay = (name, fade = 0.3) => { api.mixerForce = name; if (M.mixer && M.clips[name]) play(name, fade); };   // test hook: hold one clip
  function pick() { if (api.mixerForce && M.clips[api.mixerForce]) return api.mixerForce; const pool = (POOLS[M.mode] || POOLS.idle).filter((n) => M.clips[n]); let n = pool[Math.floor(rnd() * pool.length)];
    if (n === M.curName && pool.length > 1) n = pool[(pool.indexOf(n) + 1) % pool.length]; return n; }
  function play(name, fade) { const c = M.clips[name]; const a = M.mixer.clipAction(c); a.reset(); a.setLoop(THREE.LoopOnce, 1); a.clampWhenFinished = true;
    a.timeScale = 1; a.setEffectiveWeight(1);
    if (M.cur && M.cur !== a) { a.play(); M.cur.crossFadeTo(a, fade, false); } else a.play();
    M.cur = a; M.curName = name; M.left = c.duration; }
  function update(dt) {
    const flow = base.update(dt);
    if (!M.mixer) holdRest();   // loading, or no clips: a neutral standing pose, never a half-posed body
    else {
      if (!M.cur) play(pick(), 0);
      else if (M.wantSwitch && !(POOLS[M.mode] || POOLS.idle).includes(M.curName)) play(pick(), M.fade);   // state change: fade to a clip of the new pool
      M.wantSwitch = false;
      // sub-step so the next variant starts at exactly (end - fade) of clip time whatever the frame dt (load-stable)
      let rem = dt, guard = 0;
      while (rem > 1e-9 && guard++ < 8) { if (M.left <= M.fade + 1e-6) play(pick(), M.fade); const st = Math.min(rem, Math.max(1e-6, M.left - M.fade)); M.mixer.update(st); M.left -= st; rem -= st; }
      if (!api.twistOff) for (const w of TW) { tq.copy(w.h.quaternion).multiply(w.rest); const sg = tq.w < 0 ? -1 : 1; const ang = 2 * Math.atan2(sg * tq.y, sg * tq.w);
        w.t1.quaternion.setFromAxisAngle(Y, 0.2 * ang); w.t2.quaternion.setFromAxisAngle(Y, 0.3 * ang); }
      api.mixerTwist = TW.map((w) => +(2 * Math.atan2(w.t1.quaternion.y, w.t1.quaternion.w) / 0.2 * 57.2958).toFixed(1));
      root.updateMatrixWorld(true);
      api.mixerDbg = { clip: M.curName, left: +M.left.toFixed(3), mode: M.mode };
    }
    return flow;
  }
  return { update, api };
}
