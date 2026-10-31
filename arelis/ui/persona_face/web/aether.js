// Aether layer over an unaltered rigged GLB. No network: three.js is vendored.
// v3: stars and ribbons are skinned and animated entirely on the GPU (no per-frame CPU work).
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { createAnimator } from './anim.js';
import { GLB_PATH, FALLBACK_GLB_PATH, LOOK, MODEL_LOOK } from './config.js';
// v13: elbow volume. Linear blend skinning collapses the forearm/biceps where the elbow bends (the "candy wrapper").
// Vertices weighted only to arm bones (aElb, baked from skin weights) are skinned with dual quaternions instead,
// which keeps their volume; everything else (face, hands, shoulders, legs) keeps the exact linear skinning, and aElb is
// smooth at the edges so there is no seam. Applies to every skinned layer (hard body, depth, shell) so they stay in register.
THREE.ShaderChunk.skinning_pars_vertex += /* glsl */`
#ifdef USE_SKINNING
  attribute float aElb;
  vec4 m2q(mat3 m){ float t=m[0][0]+m[1][1]+m[2][2]; vec4 q;
    if(t>0.0){ float s=sqrt(t+1.0)*2.0; q=vec4((m[1][2]-m[2][1])/s,(m[2][0]-m[0][2])/s,(m[0][1]-m[1][0])/s,0.25*s); }
    else if(m[0][0]>m[1][1]&&m[0][0]>m[2][2]){ float s=sqrt(1.0+m[0][0]-m[1][1]-m[2][2])*2.0; q=vec4(0.25*s,(m[1][0]+m[0][1])/s,(m[2][0]+m[0][2])/s,(m[1][2]-m[2][1])/s); }
    else if(m[1][1]>m[2][2]){ float s=sqrt(1.0+m[1][1]-m[0][0]-m[2][2])*2.0; q=vec4((m[1][0]+m[0][1])/s,0.25*s,(m[2][1]+m[1][2])/s,(m[2][0]-m[0][2])/s); }
    else { float s=sqrt(1.0+m[2][2]-m[0][0]-m[1][1])*2.0; q=vec4((m[2][0]+m[0][2])/s,(m[2][1]+m[1][2])/s,0.25*s,(m[0][1]-m[1][0])/s); }
    return normalize(q); }
  vec4 qmul(vec4 a, vec4 b){ return vec4(a.w*b.xyz+b.w*a.xyz+cross(a.xyz,b.xyz), a.w*b.w-dot(a.xyz,b.xyz)); }
  vec3 qrot(vec4 q, vec3 v){ return v + 2.0*cross(q.xyz, cross(q.xyz, v) + q.w*v); }
  void dqOf(mat4 M, out vec4 r, out vec4 d){ mat3 R=mat3(M); float sc=length(R[0]); r=m2q(R/max(sc,1e-6)); d=0.5*qmul(vec4(M[3].xyz,0.0), r); }
#endif
`;
THREE.ShaderChunk.skinning_vertex = THREE.ShaderChunk.skinning_vertex.replace('transformed = ( bindMatrixInverse * skinned ).xyz;', `transformed = ( bindMatrixInverse * skinned ).xyz;
  if (aElb > 0.001) { vec3 dqp = ( bindMatrixInverse * vec4( qrot(dqR, skinVertex.xyz) + 2.0*( dqR.w*dqD.xyz - dqD.w*dqR.xyz + cross(dqR.xyz, dqD.xyz) ), 1.0 ) ).xyz;
    transformed = mix(transformed, dqp, aElb); }`);
THREE.ShaderChunk.skinbase_vertex += /* glsl */`
#ifdef USE_SKINNING
  vec4 dqR = vec4(0.0,0.0,0.0,1.0), dqD = vec4(0.0);
  if (aElb > 0.001) { vec4 r0,d0,r1,d1,r2,d2,r3,d3; dqOf(boneMatX,r0,d0); dqOf(boneMatY,r1,d1); dqOf(boneMatZ,r2,d2); dqOf(boneMatW,r3,d3);
    float s1=sign(dot(r0,r1)+1e-6), s2=sign(dot(r0,r2)+1e-6), s3=sign(dot(r0,r3)+1e-6);
    vec4 R=r0*skinWeight.x + r1*s1*skinWeight.y + r2*s2*skinWeight.z + r3*s3*skinWeight.w;
    vec4 D=d0*skinWeight.x + d1*s1*skinWeight.y + d2*s2*skinWeight.z + d3*s3*skinWeight.w;
    float L=length(R); dqR=R/L; dqD=D/L; }
#endif
`;
THREE.ShaderChunk.skinnormal_vertex = THREE.ShaderChunk.skinnormal_vertex.replace('objectNormal = vec4( skinMatrix * vec4( objectNormal, 0.0 ) ).xyz;', `vec3 nB = objectNormal; objectNormal = vec4( skinMatrix * vec4( objectNormal, 0.0 ) ).xyz;
  if (aElb > 0.001) objectNormal = mix(objectNormal, mat3(bindMatrixInverse) * qrot(dqR, mat3(bindMatrix) * nB), aElb);`);
if (new URLSearchParams(location.search).has('freeze')) { let s = 12345; Math.random = () => { s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }   // test hook: seeded randoms so ?freeze A/B renders match

const status = document.getElementById('s');
const params = new URLSearchParams(location.search);
const V = (a) => new THREE.Color(...a);

// ?transparent=1 (Arelis dock): clear to alpha 0 and give the final image alpha = its brightest channel,
// premultiplied. Over black that composites to exactly the opaque image; elsewhere only her light shows.
const TRANSPARENT = params.has('transparent');
if (TRANSPARENT) { document.documentElement.style.background = 'transparent'; document.body.style.background = 'transparent'; }
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true, alpha: TRANSPARENT, premultipliedAlpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.setClearColor(0x000000, TRANSPARENT ? 0 : 1);
// A lost context never comes back on its own here; report it so the panel shows the painted face instead of nothing.
renderer.domElement.addEventListener('webglcontextlost', () => { console.warn('[avatar] webgl lost'); window.__error = 'WebGL context lost'; });
renderer.domElement.addEventListener('webglcontextrestored', () => console.info('[avatar] webgl restored'));
console.info('[avatar] renderer init webgl2=' + renderer.capabilities.isWebGL2 + ' ratio=' + renderer.getPixelRatio() + ' size=' + innerWidth + 'x' + innerHeight);
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(30, innerWidth / innerHeight, 0.05, 200);
// Full-body framing at any aspect: her rest-pose skinned box (Box3 precise) plus a margin fits both the
// vertical and the horizontal field of view; the slight look-down of the old fixed camera is kept.
const FIT = { box: null, margin: 1.18, minW: 0.5 };   // minW: width floor (x height) so gestures stay in frame
function fitFull() { const b = FIT.box; if (!b) return; const s = b.getSize(new THREE.Vector3()), c = b.getCenter(new THREE.Vector3());
  const tv = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)), H = s.y * FIT.margin, W = Math.max(s.x, s.y * FIT.minW) * FIT.margin;
  const d = Math.max(H / 2 / tv, W / 2 / (tv * camera.aspect)) + s.z / 2;
  camera.position.set(c.x, c.y + d * 0.03, c.z + d); camera.lookAt(c.x, c.y, c.z); }
const uTime = { value: 0 };
const uFlow = { value: 0 };   // anim: flow clock for threads/swirls/stars (runs faster while thinking; equals uTime at rate 1)
const uAnim = { value: new THREE.Vector4(1, 1, 0, 0) };   // anim: x glow mul, y rim mul, z shimmer (neutral = 1,1,0)
const herLayers = [];   // her own layers that fade in with the reveal
const links = { U: null, aura: null, floorRing: null };   // shared with anim.js: look anchors and the parts that follow her walk
let armBones = null;
const state = { mode: 'idle', level: 0 };           // idle | thinking | talking; level = voice 0..1
const face = { blinkAt: 2 + Math.random() * 3, blinkT: -1, visemes: [] };   // filled once morph targets are found
window.aether = { setState: (m) => (state.mode = m), setLevel: (v) => (state.level = v),
  blinkNow: () => { face.blinkT = 0; }, holdBlink: (v) => { face.hold = v; } };

// ---------- shared GLSL ----------
const NOISE = /* glsl */`
  vec3 hash3(vec3 p){ p=vec3(dot(p,vec3(127.1,311.7,74.7)),dot(p,vec3(269.5,183.3,246.1)),dot(p,vec3(113.5,271.9,124.6)));
    return -1.0+2.0*fract(sin(p)*43758.5453123); }
  float noise(vec3 p){ vec3 i=floor(p), f=fract(p); vec3 u=f*f*(3.0-2.0*f);
    return mix(mix(mix(dot(hash3(i),f),dot(hash3(i+vec3(1,0,0)),f-vec3(1,0,0)),u.x),
                   mix(dot(hash3(i+vec3(0,1,0)),f-vec3(0,1,0)),dot(hash3(i+vec3(1,1,0)),f-vec3(1,1,0)),u.x),u.y),
               mix(mix(dot(hash3(i+vec3(0,0,1)),f-vec3(0,0,1)),dot(hash3(i+vec3(1,0,1)),f-vec3(1,0,1)),u.x),
                   mix(dot(hash3(i+vec3(0,1,1)),f-vec3(0,1,1)),dot(hash3(i+vec3(1,1,1)),f-vec3(1,1,1)),u.x),u.y),u.z); }`;
// Skin a bind-pose point with the shared skeleton's bone texture (same layout as three's skinning chunk).
const SKIN = /* glsl */`
  uniform highp sampler2D boneTex; uniform mat4 bindM; uniform mat4 bindMInv; uniform mat4 uModel;
  mat4 boneM(float i){ int size=textureSize(boneTex,0).x; int j=int(i)*4; int x=j%size; int y=j/size;
    return mat4(texelFetch(boneTex,ivec2(x,y),0),texelFetch(boneTex,ivec2(x+1,y),0),texelFetch(boneTex,ivec2(x+2,y),0),texelFetch(boneTex,ivec2(x+3,y),0)); }
  vec3 skinPoint(vec3 p, vec4 si, vec4 sw){ vec4 b=bindM*vec4(p,1.0);
    vec4 s=boneM(si.x)*b*sw.x + boneM(si.y)*b*sw.y + boneM(si.z)*b*sw.z + boneM(si.w)*b*sw.w;
    return (uModel*(bindMInv*s)).xyz; }`;

// ---------- body shell: rim + dense irregular threads + inner glow ----------
const SHELL_VS = /* glsl */`
  #include <common>
  #include <morphtarget_pars_vertex>
  #include <skinning_pars_vertex>
  varying vec3 vN; varying vec3 vV; varying vec3 vW; varying vec3 vO; varying vec2 vUv2;
  attribute float aCav; attribute float aCavF; varying float vCav; varying float vCavF;
  attribute float aHand; varying float vHand; attribute float aWr; varying float vWr;   // pass 14: skin weight on hand/finger bones
  void main(){
    vO = position; vUv2 = uv; vCav = aCav; vCavF = aCavF; vHand = aHand; vWr = aWr;
    #include <beginnormal_vertex>
    #include <morphnormal_vertex>
    #include <skinbase_vertex>
    #include <skinnormal_vertex>
    #include <defaultnormal_vertex>
    #include <begin_vertex>
    #include <morphtarget_vertex>
    #include <skinning_vertex>
    #include <project_vertex>
    vN = normalize(transformedNormal); vV = normalize(-mvPosition.xyz);
    vW = (modelMatrix * vec4(transformed,1.0)).xyz;
  }`;
const SHELL_FS = /* glsl */`
  uniform vec4 uAnim;
  uniform float uTime; uniform vec3 uA; uniform vec3 uB; uniform float uGlow; uniform float uDen; uniform float uNeckY; uniform float uCollar; uniform float uWrist; uniform float uPalm; uniform vec2 uWrK; uniform vec2 uSeam;
  uniform sampler2D uAlphaMap; uniform float uHair; uniform vec4 uFace; uniform float uHipY; uniform float uFeat; uniform float uForm; uniform vec4 uNavel; uniform float uDbg; varying vec2 vUv2;
  varying vec3 vN; varying vec3 vV; varying vec3 vW; varying vec3 vO; varying float vCav; varying float vCavF; varying float vHand; varying float vWr;
  ${NOISE}
  float thread(float x){ float d=abs(fract(x)-0.5); float w=fwidth(x)*0.7; return smoothstep(w,0.0,d); }
  void main(){
    float ndv = abs(dot(normalize(vN), normalize(vV)));
    float rim = pow(1.0 - ndv, 2.4);
    // v8: the dress has a vertical mesh seam on the centre line (split normals), which the rim lit up. Turn the rim down there (below the neck).
    // Pelvis band: widen the fade so no small anatomical creases catch the rim (stylized, light not skin).
    float pelvis = smoothstep(uHipY - 0.2, uHipY - 0.12, vW.y) * (1.0 - smoothstep(uHipY - 0.02, uHipY + 0.04, vW.y));
    float seam = mix(1.0, smoothstep(0.004, mix(0.02, 0.07, pelvis), abs(vW.x - uFace.x)), (1.0 - smoothstep(uNeckY - 0.02, uNeckY + 0.03, vW.y)));   // world space: works whatever the mesh's bind axes
    seam *= 1.0 - 0.8*smoothstep(0.5, 0.85, normalize(vN).y) * (1.0 - smoothstep(uNeckY - 0.02, uNeckY + 0.03, vW.y)) * smoothstep(0.025, 0.06, abs(vW.x - uFace.x));   /* vr3: probe showed the neck-base line is the up-facing trapezius rim inside |x|<0.07 (row 183 contrast 1.45; layer toggles: body shells only); gate now reaches in to the neck */   // pass 9: shoulder tops at grazing angle lit a rim strip that bloomed into soft boxes
    rim *= seam;
    vec3 p = vO * uDen;
    // Domain-warped thread families -> irregular, interlaced, mostly running along the body.
    vec3 w1 = vec3(noise(p*0.18 + vec3(0.0,uTime*0.04,0.0)), noise(p*0.18+5.2), noise(p*0.18+9.7));
    vec3 q = p + w1*3.5;
    float t = 0.0;
    t += thread(q.x*0.55 + q.z*0.3 + noise(q*0.3)*1.5);
    t += thread(-q.x*0.5 + q.z*0.45 + noise(q*0.33+3.1)*1.6);
    t += 0.8*thread(q.z*0.6 + q.y*0.12 + noise(q*0.27+7.3)*1.8);
    t += 0.6*thread(q.x*1.3 + q.y*0.2 + noise(q*0.5+1.7)*2.0);
    t += 0.5*thread(q.y*0.25 + noise(q*0.22+4.4)*2.2);
    if (uForm > 0.0 && vW.y < uNeckY) {   // body: contour threads that wrap her curves (height iso-lines + two gentle spirals around the body axis)
      float az = atan(vW.x - uFace.x, vW.z - uFace.z + 0.06);
      float wob = noise(vW*6.0 + vec3(0.0, uTime*0.05, 0.0));
      float tc = 0.55*thread(vW.y*42.0 + wob*1.4)
               + 0.8*thread(vW.y*26.0 + az*1.6 + wob*1.2)
               + 0.8*thread(vW.y*26.0 - az*1.6 + wob*1.2 + 0.5);
      float arm = smoothstep(0.13, 0.2, abs(vW.x - uFace.x));   // pass 8: arms keep the woven threads (iso-lines striped them)
      t = mix(t, tc*1.3 + t*0.25, min(uForm, 1.0) * (1.0 - arm));
    }
    float vary = 0.45 + 0.55*smoothstep(-0.3, 0.5, noise(p*0.12 + vec3(0.0,-uTime*0.12,0.0)));  // brightness varies along threads
    float flow = 0.7 + 0.3*sin(vW.y*6.0 - uTime*1.3 + noise(p*0.1)*4.0);
    float patchy = smoothstep(-0.35, 0.45, noise(p*0.07 + vec3(3.0, uTime*0.03, 1.0)));   // uneven inner fill
    vec3 c = mix(uA, uB, 0.15 + 0.85*rim);
    float th = t*vary*flow;
    float calm = smoothstep(uNeckY - 0.11, uNeckY + 0.03, vW.y + 0.02*(1.0 - ndv));   // pass 8: same wide band as the interior fade (height + normal)      // head/face: few threads, smooth glow (world space)
    rim *= mix(1.0, 0.45, calm * uFace.w);
    th *= mix(1.0, 0.12, calm);
    float glow = uGlow*mix(0.65 + 0.35*patchy, 1.25, calm)*(0.6 + 0.4*(1.0-ndv));
    vec3 col = c*(rim*0.95 + glow) + mix(uB, vec3(0.62,0.44,1.0), clamp(th*th*0.2,0.0,1.0))*th*1.05;
    // v7: bright white-edged rim on the outline only (bloom turns it into the soft halo).
    // v8: the dress has a vertical mesh seam at the centre line (split normals), which the rim lit up. Turn the rim down there.
    float edge = pow(1.0 - ndv, 5.0) * seam * mix(1.0, 0.4, calm * uFace.w);
    col += mix(uB, vec3(1.0,0.95,1.0), 0.4) * edge * 1.1 + uB * pow(1.0-ndv, 2.0) * 0.35 * seam;
    // Face detail (pass 2): curvature lines pick out eyelids, nostrils, lips; front-facing areas sit darker for relief.
    if (uFeat > 0.0) {
      vec3 Nn = normalize(vN);
      float curv = length(fwidth(Nn)) / max(length(fwidth(vW)), 1e-5);      // ~1/m
      float fz = calm * uFeat * uFace.w;
      float line = smoothstep(90.0, 220.0, curv) * fz * 0.35;   // only the sharpest creases (lid, lip line, nostril)
      float gf = mix(1.0, 0.3 + 1.2*pow(1.0-ndv, 1.5), fz);
      col += c*glow*(gf - 1.0) + mix(uB, vec3(0.95,0.9,1.0), 0.4) * line * 0.9;
      th += line*0.6;
    }
    if (uForm > 0.0) {
      vec3 Nn = normalize(vN);
      float body = (1.0 - calm) * min(uForm, 1.0);
      float key = dot(Nn, normalize(vec3(-0.35, 0.6, 0.72)));            // soft key from upper front-left (view space)
      float fill = dot(Nn, normalize(vec3(0.6, -0.1, 0.8)));
      float shade = clamp(0.62*smoothstep(-0.25, 1.0, key) + 0.38*smoothstep(-0.3, 1.0, fill), 0.0, 1.0);
      float chestR = smoothstep(uNeckY - 0.40, uNeckY - 0.26, vW.y) * (1.0 - smoothstep(uNeckY - 0.24, uNeckY + 0.02, vW.y)) * (1.0 - smoothstep(0.08, 0.2, abs(vW.x - uFace.x)));   // pass 8: wide, rounded (no box edges)
      shade = mix(shade, smoothstep(-0.2, 1.0, 0.5*shade + 0.3), chestR * 0.6);   // pass 10: pass 8 chest shading   // chest: soft, subdued
      float curv = length(fwidth(Nn)) / max(length(fwidth(vW)), 1e-5);
      float crease = smoothstep(25.0, 90.0, curv) * (1.0 - pelvis);     // collarbones, navel, stomach line, under-bust: soft light lines
      float small = smoothstep(25.0, 70.0, curv) * body * (1.0 - vHand);   // pass 14: fingers are tight curvature too, which killed their rim; hands keep the body rim
      // navel: a small soft hollow with a faint light ring (region-limited fine curvature)
      float nav = smoothstep(uHipY - 0.02, uHipY + 0.04, vW.y) * (1.0 - smoothstep(uHipY + 0.2, uHipY + 0.26, vW.y)) * (1.0 - smoothstep(0.04, 0.07, abs(vW.x - uFace.x))) * body;
      float dn = length((vW - uNavel.xyz) * vec3(1.0, 0.62, 1.0)) / max(uNavel.w, 1e-4);   // pass 11: slightly vertical
      float navC = smoothstep(2.3, 0.2, dn) * body;   // pass 12: a touch wider   // pass 7: located navel hollow
      nav = smoothstep(0.8, 1.15, dn) * smoothstep(2.0, 1.25, dn) * body;   // its light rim                // tiny tight bumps: no rim/edge catch (stylized, no anatomical detail)
      col -= (c*rim*0.95 + mix(uB, vec3(1.0,0.95,1.0), 0.4)*edge*1.1) * small;
      col *= mix(1.0, 0.55 * (0.3 + 0.9*shade), body);   // flat fill cut way down; soft normal shading
      // baked concavity (AO-like): hollows go dark, ridges catch light lines -> collarbones, sternum, stomach line, navel, waist/hip creases
      float chest = chestR;
      float cavS = vCav * (1.0 - chest);                             // chest stays soft and subdued
      float hol = smoothstep(0.0, 0.55, cavS) * (1.0 - 0.6*smoothstep(uNeckY - 0.24, uNeckY - 0.04, vW.y)), ridge = smoothstep(0.1, 0.8, -cavS);
      col *= mix(1.0, 1.0 - 0.85*hol, body);
      col *= 1.0 - 0.92*navC;   // pass 12: a touch deeper
      float nlip = smoothstep(0.9, 1.6, dn) * smoothstep(2.8, 1.7, dn) * smoothstep(0.004, -0.012, vW.y - uNavel.y) * body;
      col += mix(uB, vec3(0.9,0.85,1.0), 0.2) * nlip * 0.3;   // pass 11: soft light on the lower inner curve (shading, not an outline)   // pass 11: soft shaded hollow
      float sline = (1.0 - smoothstep(0.004, 0.016, abs(vW.x - uFace.x))) * smoothstep(uHipY + 0.04, uHipY + 0.1, vW.y) * (1.0 - smoothstep(uHipY + 0.24, uHipY + 0.32, vW.y)) * body;
      col *= 1.0 - 0.3*sline;   // pass 8: soft stomach line
      // pass 11: no outline ring around the navel
      col += uA * 0.16 * body * (0.6 + 0.4*shade);   // violet body glow so the see-through torso stays violet, not grey
      th *= mix(1.0, (1.0 - 0.8*hol) * (1.0 + 0.8*ridge), body);
      col += mix(uB, vec3(0.92,0.86,1.0), 0.35) * ridge * (0.35 + 0.4*rim) * body * 0.6;
      col += uB * (pow(1.0-ndv, 2.2) * 0.75 + pow(1.0-ndv, 5.0) * 0.6) * body * seam * (1.0 - small) * (1.0 - 0.65*chest);
      th *= mix(1.0, 0.3 + 1.0*shade, body);                          // threads lit by the form, so they follow it
      col += mix(uB, vec3(0.9,0.85,1.0), 0.3) * crease * (1.0 - small) * body * 0.12 * shade;
      glow *= mix(1.0, 0.55 + 0.6*shade, body);
      if (uDbg > 0.5) { float d = uDbg < 1.5 ? calm : uDbg < 2.5 ? chest : uDbg < 3.5 ? shade : uDbg < 4.5 ? hol : uDbg < 5.5 ? ridge : uDbg < 6.5 ? crease*(1.0-small) : uDbg < 7.5 ? th*0.3 : rim;
        gl_FragColor = vec4(vec3(d), 1.0); return; }
    }
    if (uForm > 1.5 && uForm < 2.5) { gl_FragColor = vec4(max(vCav,0.0), max(-vCav,0.0), max(vCavF,0.0), 1.0); return; }   // debug: ?cavdbg
    if (uForm > 2.5) { gl_FragColor = vec4(col, 1.0); return; }
    if (uHair > 2.5) {   // eyeball: glowing iris, dark pupil, soft catchlight (UV centre = iris)
      vec2 e = vUv2 - 0.5; float d = length(e);
      float ang = atan(e.y, e.x);
      float iris = smoothstep(0.15, 0.135, d), pupil = smoothstep(0.055, 0.045, d);
      float streak = 0.75 + 0.25*sin(ang*28.0 + noise(vec3(e*30.0, 1.0))*4.0);
      float limbus = smoothstep(0.09, 0.145, d) * iris;
      vec3 ic = mix(uB*1.5, vec3(0.75,0.6,1.0), smoothstep(0.13, 0.05, d)) * streak * (1.0 - 0.6*limbus);
      float catchl = smoothstep(0.03, 0.0, length(e - vec2(0.045, 0.05)));
      col = mix(uA*0.25, ic, iris) * (1.0 - pupil*0.92) + vec3(1.0,0.97,1.0) * catchl * 1.3;
      gl_FragColor = vec4(col, 1.0); return;
    }
    if (uHair < 0.5) {   // anim: listening rim boost + thinking shimmer (both zero at rest)
      col += mix(uB, vec3(1.0,0.95,1.0), 0.4) * (edge*1.1 + pow(1.0-ndv, 2.4)*0.35*seam) * (uAnim.y - 1.0);
      if (uAnim.z > 0.001) { float sp = smoothstep(0.55, 0.85, noise(vW*70.0 + vec3(0.0, -uTime*0.9, uTime*0.3)));
        col += vec3(0.85,0.8,1.0) * sp * (0.55 + 0.45*sin(uTime*6.0 + vW.y*40.0)) * uAnim.z * 0.45; }
    }
    float a = clamp(rim*0.95 + th + glow + edge, 0.0, 1.0);
    if (uForm > 0.0 && uHair < 0.5) a = mix(a, 1.0, (1.0 - calm) * 0.2);   // let the light/shadow modelling carry through instead of washing out
    if (uHair > 1.5) {   // brow / lash cards: fine bright strokes
      float ca = texture2D(uAlphaMap, vUv2).a; if (ca < 0.1) discard;
      col = mix(uB, vec3(0.92,0.86,1.0), 0.3) * ca * 1.1; a = ca * 0.8;
    } else if (uHair > 0.5) {   // hair cards: alpha from the card texture, soft glow instead of hard rim/threads
      float ca = texture2D(uAlphaMap, vUv2).a; if (ca < 0.08) discard;
      ca = smoothstep(0.08, 0.7, ca);
      ca = mix(ca, 1.0, 0.35);
      // own bright violet glow + strand-direction streaks and a sliding sheen band
      float strand = 0.55 + 0.45*sin(vUv2.x*260.0 + noise(vec3(vUv2*40.0, 0.0))*3.0);
      float sheen = pow(clamp(1.0 - abs(ndv - 0.55)*2.2, 0.0, 1.0), 3.0) * (0.6 + 0.4*sin(vW.y*40.0 - uTime*0.6));
      col = mix(uA, uB, 0.6) * (0.75 + 0.5*rim) * (0.6 + 0.5*strand) + vec3(0.85,0.78,1.0) * sheen * 0.45;
      a = ca * 0.9; col *= ca;
      // fringe over the face: fade it so the face reads through (shape unchanged)
      float fm = smoothstep(uFace.z - 0.05, uFace.z - 0.01, vW.z) * (1.0 - smoothstep(0.05, 0.09, abs(vW.x - uFace.x)))
               * smoothstep(uFace.y - 0.12, uFace.y - 0.08, vW.y) * (1.0 - smoothstep(uFace.y + 0.03, uFace.y + 0.06, vW.y));
      col *= 1.0 - 0.3*fm; a *= 1.0 - 0.3*fm;   // fringe stays, only slightly translucent
    }
    if (uHair < 0.5) { float lim = smoothstep(0.13, 0.2, abs(vW.x - uFace.x)) * (1.0 - smoothstep(uNeckY - 0.02, uNeckY + 0.03, vW.y)); col *= mix(1.0, gl_FrontFacing ? 0.78 : 0.25, max(smoothstep(0.0, 0.35, vHand), 0.6 * lim * (gl_FrontFacing ? 0.0 : 1.0))); a *= mix(1.0, 0.75, smoothstep(0.0, 0.35, vHand)); }   // v13: stacked additive finger layers summed into a glow ball; hands now sit at the forearm's level so fingers stay readable
    if (uHair < 0.5) { float hk = smoothstep(0.0, 0.35, vHand), hr = smoothstep(0.6, 1.0, vHand) * (1.0 - 0.6 * smoothstep(uWrK.x, uWrK.y, vWr)); col *= 1.0 - 0.25 * hk * smoothstep(0.4, 0.9, ndv); col += mix(mix(uA, uB, 0.75), vec3(1.0), 0.2) * hr * pow(1.0 - ndv, 1.8) * 1.1; a = max(a, 0.85 * hr * pow(1.0 - ndv, 1.8)); }   /* vr6: hands beside the thigh glow (speaking f390) read faint: front-face hand dim 0.6 -> 0.78 (r7; vr6f 0.95), rim 0.8 -> 1.1 with edge power 1.8 (narrower) and 20% whiter, rim only on vHand 0.6-1.0 (vr6c rim 1.3 / power 1.3 / 0.35-0.95 made a glow ball on the wrist: walk f320, speaking f300) so the outline separates from the violet thigh */   /* vr5: rim 0.5 -> 0.8 so hands beside the thighs separate */   /* vr4: soft hand rim: fingers outline at 1x instead of summing to a blob (interior a little dimmer, edges lit) */
    if (uHair < 0.5 && uForm > 0.0) { float nb = smoothstep(uNeckY - 0.14, uNeckY - 0.04, vW.y) * (1.0 - smoothstep(uNeckY + 0.01, uNeckY + 0.07, vW.y));
      col += mix(uA, uB, 0.5) * nb * (0.22 + 0.3 * (1.0 - ndv) * (1.0 - smoothstep(0.4, 0.8, normalize(vN).y)));   /* vr3: no grazing boost on up-facing shoulder tops */ col *= 1.0 - 0.18 * smoothstep(uNeckY + 0.02, uNeckY + 0.1, vW.y); col += mix(uA, uB, 0.5) * (uCollar) * smoothstep(uNeckY - 0.20, uNeckY - 0.06, vW.y) * (1.0 - smoothstep(uNeckY - 0.05, uNeckY - 0.015, vW.y)) * (1.0 - smoothstep(0.05, 0.12, abs(vW.x - uFace.x))); }   /* r7: f450 neck-base step (neck ~112 -> chest ~70 lum in 3 px): collar side glow ramps up to the neck so the head layer's bright neck fades into the body; zero above uNeckY+0.01, face untouched */   // v13: neck seam lifted (was a dark band under the jaw), head glow eased toward the body's level
    if (uHair < 0.5 && uForm > 0.0) { float sd = (vW.y - (uNeckY - uSeam.y)) / 0.012; col += mix(uA, uB, 0.5) * uSeam.x * exp(-sd*sd) * (1.0 - smoothstep(uNeckY - 0.03, uNeckY - 0.015, vW.y)) * (1.0 - smoothstep(0.06, 0.13, abs(vW.x - uFace.x))); }   // r8: fill the thin dark neck/chest seam line (body side, below the chin)
    if (uHair < 0.5) { float wz = smoothstep(uWrK.x, uWrK.y, vWr); col *= 1.0 - uWrist * wz; col *= 1.0 + uPalm * smoothstep(0.6, 1.0, vHand) * (1.0 - smoothstep(0.2, 0.6, vWr)); a *= 1.0 - 0.5 * uWrist * wz; }   // r8: wrist knob (hand/forearm skin-weight blend zone) dimmed incl. its bloom
    col *= uAnim.x;   // anim: breath / voice glow (1.0 at rest)
    gl_FragColor = vec4(col, a);
  }`;
const shellNeck = { value: 1e9 };   // bind-pose height of the neck/chin line, set after load
const HIPY = { value: -99 };
const NAVEL = { value: new THREE.Vector4(0, -99, 0, 0.012) };   // world pos + radius, found from the baked cavity
const FACE = { value: new THREE.Vector4(0, -99, -99, 0) };   // eye-line centre (world), set after load
const WHITE = new THREE.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1); WHITE.needsUpdate = true;
function shellMaterial(alphaMap = null, isCard = false, isEye = false) {
  return new THREE.ShaderMaterial({
    uniforms: { uTime: uFlow, uAnim, uA: { value: V(LOOK.violet) }, uB: { value: V(LOOK.lilac) },
      uGlow: { value: LOOK.innerGlow }, uDen: { value: LOOK.threadDensity }, uNeckY: shellNeck, uCollar: { value: 1.0 }, uSeam: { value: new THREE.Vector2(0.6, 0.035) }, uWrK: { value: new THREE.Vector2(0.0, 1.0) }, uPalm: { value: 0.2 }, uWrist: { value: 0.85 },
      uAlphaMap: { value: alphaMap || WHITE }, uHair: { value: isEye ? 3 : alphaMap ? (isCard ? 2 : 1) : 0 }, uFace: FACE, uHipY: HIPY, uFeat: { value: LOOK.faceDetail ?? 0 }, uDbg: { value: +(new URLSearchParams(location.search).get('term') || 0) }, uNavel: NAVEL, uForm: { value: params.has('cavdbg') ? +params.get('cavdbg') + 1 : (LOOK.bodyForm ?? 0) } },
    vertexShader: SHELL_VS, fragmentShader: SHELL_FS,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    extensions: { derivatives: true },
  });
}

// ---------- surface sampling -> bind-pose position + skin weights (for GPU skinning) ----------
function sampleSurface(meshes, count) {
  const tris = []; let total = 0;
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  for (const m of meshes) {
    const g = m.geometry, idx = g.index, pos = g.attributes.position;
    const n = idx ? idx.count / 3 : pos.count / 3;
    for (let t = 0; t < n; t++) {
      const i0 = idx ? idx.getX(3*t) : 3*t, i1 = idx ? idx.getX(3*t+1) : 3*t+1, i2 = idx ? idx.getX(3*t+2) : 3*t+2;
      a.fromBufferAttribute(pos, i0); b.fromBufferAttribute(pos, i1); c.fromBufferAttribute(pos, i2);
      total += b.clone().sub(a).cross(c.clone().sub(a)).length() * 0.5; tris.push({ m, i: [i0, i1, i2], cum: total });
    }
  }
  const out = [];
  for (let k = 0; k < count; k++) {
    const r = Math.random() * total; let lo = 0, hi = tris.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (tris[mid].cum < r) lo = mid + 1; else hi = mid; }
    let u = Math.random(), v = Math.random(); if (u + v > 1) { u = 1 - u; v = 1 - v; }
    const t = tris[lo], w = [1 - u - v, u, v], g = t.m.geometry;
    const p = new THREE.Vector3();
    for (let j = 0; j < 3; j++) p.addScaledVector(a.fromBufferAttribute(g.attributes.position, t.i[j]), w[j]);
    const dom = t.i[w.indexOf(Math.max(...w))];     // skin weights of the dominant corner
    const si = g.attributes.skinIndex, sw = g.attributes.skinWeight;
    out.push({ mesh: t.m, p, si: [si.getX(dom), si.getY(dom), si.getZ(dom), si.getW(dom)],
      sw: [sw.getX(dom), sw.getY(dom), sw.getZ(dom), sw.getW(dom)] });
  }
  return out;
}
// CPU version of the same skinning, used once at load to pick ribbon roots by height.
function skinnedNow(s, target) {
  target.copy(s.p); const m = s.mesh; const tmp = new THREE.Vector3(), acc = new THREE.Vector3();
  const v = target.clone().applyMatrix4(m.bindMatrix); const bm = m.skeleton.boneMatrices, M = new THREE.Matrix4();
  for (let k = 0; k < 4; k++) { if (!s.sw[k]) continue; M.fromArray(bm, s.si[k] * 16);
    acc.addScaledVector(tmp.copy(v).applyMatrix4(M), s.sw[k]); }
  return target.copy(acc).applyMatrix4(m.bindMatrixInverse).applyMatrix4(m.matrixWorld);
}
function skinUniforms(ref) {
  return { boneTex: { value: ref.skeleton.boneTexture }, bindM: { value: ref.bindMatrix },
    bindMInv: { value: ref.bindMatrixInverse }, uModel: { value: ref.matrixWorld } };
}

// ---------- stars (GPU-skinned surface stars + loose aura) ----------
const STAR_FS = /* glsl */`
  uniform vec3 uA; uniform vec3 uB; varying float vS; varying float vTw;
  void main(){ vec2 q=gl_PointCoord-0.5; float d=length(q); if(d>0.5) discard;
    float core=smoothstep(0.5,0.25,d); float halo=0.0;
    float big=step(0.9,vS);
    float spike=0.0;
    // big stars: gaussian-like falloff and lower peak, so bloom spreads a round glow instead of a square sprite edge
    float soft=exp(-d*d*28.0);
    core=mix(core, soft, big);
    float a=core*vTw*mix(1.0, 0.55, big);
    gl_FragColor=vec4(mix(uA,vec3(0.88,0.82,1.0),clamp(core*0.7+big*0.2,0.0,1.0))*a*1.6,a); }`;
function starMaterial(skinned, ref) {
  return new THREE.ShaderMaterial({
    uniforms: { uTime: uFlow, uA: { value: V(LOOK.violet) }, uB: { value: V(LOOK.lilac) }, uPx: { value: renderer.getPixelRatio() },
      ...(skinned ? skinUniforms(ref) : {}) },
    vertexShader: `${skinned ? SKIN : ''}
      attribute float seed; ${skinned ? 'attribute vec4 sIdx; attribute vec4 sW;' : ''}
      uniform float uTime; uniform float uPx; varying float vS; varying float vTw;
      void main(){ vS=seed;
        vec3 p = ${skinned ? 'skinPoint(position, sIdx, sW)' : '(modelMatrix*vec4(position,1.0)).xyz'};
        float ph=fract(seed*7.13+uTime*0.06);
        p += normalize(vec3(sin(seed*40.0),0.7,cos(seed*31.0)))*ph*${skinned ? '0.03' : '0.12'};
        vTw = (0.45+0.55*sin(uTime*(1.2+seed*3.0)+seed*60.0)) * (1.0-ph*0.8);
        float big=step(0.9,seed);
        vec4 mv=viewMatrix*vec4(p,1.0); gl_Position=projectionMatrix*mv;
        float att=3.0/-mv.z;
        gl_PointSize=(0.9+1.1*seed)*uPx*att + big*uPx*max(${skinned ? "2.4" : "2.0"}*att, 2.0); vTw*=0.6+big*0.6; }`,
    fragmentShader: STAR_FS,
    transparent: true, depthWrite: false, depthTest: !skinned, blending: THREE.AdditiveBlending,
  });
}
function makeSurfaceStars(samples, ref) {
  const n = samples.length, g = new THREE.BufferGeometry();
  const pos = new Float32Array(n * 3), si = new Float32Array(n * 4), sw = new Float32Array(n * 4), seed = new Float32Array(n);
  samples.forEach((s, i) => { pos.set([s.p.x, s.p.y, s.p.z], 3*i); si.set(s.si, 4*i); sw.set(s.sw, 4*i); seed[i] = Math.random(); });
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); g.setAttribute('sIdx', new THREE.BufferAttribute(si, 4));
  g.setAttribute('sW', new THREE.BufferAttribute(sw, 4)); g.setAttribute('seed', new THREE.BufferAttribute(seed, 1));
  const pts = new THREE.Points(g, starMaterial(true, ref)); pts.frustumCulled = false; pts.renderOrder = 5; return pts;
}
function makeAura(center, h) {
  const n = LOOK.auraStars, pos = new Float32Array(n * 3), seed = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const y = Math.pow(Math.random(), 1.2) * h * 1.15, r = (0.15 + Math.pow(Math.random(), 0.8) * 1.4) * (1.1 - 0.5 * y / h);
    const a = Math.random() * Math.PI * 2;
    pos.set([center.x + Math.cos(a) * r, center.y + y, center.z + Math.sin(a) * r * 0.6], 3 * i); seed[i] = Math.random();
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); g.setAttribute('seed', new THREE.BufferAttribute(seed, 1));
  const pts = new THREE.Points(g, starMaterial(false)); pts.frustumCulled = false; return pts;
}



// v12 materialize/dissolve: her own layers fill in bottom-up through a soft noisy front (screen-space height), opacity/discard only --
// geometry, face, shape keys and hair are untouched. Background, galaxy and floor stay.
const uRes = { value: new THREE.Vector2(1, 1) };
const uRvDir = { value: 1 };   // v12f: +1 materializing, -1 dissolving
const uNeckS = { value: 0.8 };   // v12b: neck height in screen space (0 bottom, 1 top)
const REVEAL_GLSL = `uniform float uApp; uniform float uAppL; uniform vec2 uRes; uniform float uNeckS; uniform float uRvDir;
  float rvH(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float rvN(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
    return mix(mix(rvH(i), rvH(i+vec2(1,0)), f.x), mix(rvH(i+vec2(0,1)), rvH(i+vec2(1,1)), f.x), f.y); }
  float revealT(){ vec2 q=gl_FragCoord.xy/uRes; float n=0.6*rvN(gl_FragCoord.xy/14.0)+0.4*rvN(gl_FragCoord.xy/4.0);
    float yy=min(q.y, uNeckS)/max(uNeckS,0.05); float hd=smoothstep(uNeckS-0.01, uNeckS+0.03, q.y); n=mix(n, 0.5+0.17*uRvDir+0.25*(rvN(gl_FragCoord.xy/40.0)-0.5), hd);   /* v12f: the head follows the neck and shoulders in both directions (arrives after them, leaves after them) */ return clamp(yy*0.3+0.7*n,0.0,1.0); }   /* v12e: the head fades as one soft piece at the shoulders' mean pace (no blotches) */   /* head shares the shoulders' threshold */
  float rvHead(){ float lo=uRvDir>0.0?0.50:0.48, hi=uRvDir>0.0?1.0:0.96;   /* vr3: dissolve head left after the body (floating head at f65-75); window raised from 0.30-0.84 */ float x=clamp((uAppL-lo)/(hi-lo),0.0,1.0); return x*x*(3.0-2.0*x); }   /* vr2: the whole head/hair fades as one piece on its own ~1.2-1.5 s smootherstep window of the appear clock (was a 0.5 R sweep: 17->77 luminance in ~20 frames, read as a pop); arrives after the shoulders, leaves after them */
  float revealM(){ float R=uAppL*2.8-0.9; float t=revealT(); float hd=smoothstep(uNeckS-0.01, uNeckS+0.03, gl_FragCoord.y/uRes.y); return mix(smoothstep(t, t+0.9, R), rvHead(), hd); }   /* vr2: body front 0.9 R wide (was 0.4) = ~0.8-1.2 s per pixel at the 3.6 s pace */
  float revealD(){ float R=uAppL*2.8-0.9; float t=revealT(); float hd=smoothstep(uNeckS-0.01, uNeckS+0.03, gl_FragCoord.y/uRes.y); return mix(smoothstep(t-0.3, t+0.35, R), rvHead(), hd); }   /* vr2: solid layers dither in over most of the glow ramp (and on the head the same curve as its glow), so the solid surface itself fades rather than appearing behind the glow */`;
function addReveal(m) {
  if (!m || m.__rev) return; m.__rev = true; const hard = !(m.blending === THREE.AdditiveBlending) && (m.depthWrite !== false);
  const wrap = (fs) => fs.replace(/void\s+main\s*\(\s*\)/, 'void main_rv()') + `\n${REVEAL_GLSL}\nvoid main(){ float m_rv=revealM(); ${hard ? 'float m_d=revealD(); if (m_d < rvH(gl_FragCoord.xy * 0.731 + 3.7)) discard;' : ''} m_rv *= mix(1.0, sqrt(m_rv), smoothstep(uNeckS-0.06, uNeckS+0.06, gl_FragCoord.y/uRes.y)); if (${hard ? 'false' : 'm_rv < 0.01'}) discard; main_rv(); ${hard ? 'gl_FragColor.rgb *= m_rv; gl_FragColor.a *= m_rv;' : 'gl_FragColor *= m_rv;'} }\n`;
  if (m.isShaderMaterial) { m.uniforms.uApp = uApp; m.uniforms.uAppL = uAppL; m.uniforms.uRes = uRes; m.uniforms.uNeckS = uNeckS; m.uniforms.uRvDir = uRvDir; m.fragmentShader = wrap(m.fragmentShader); m.needsUpdate = true; }
  else { const prev = m.onBeforeCompile; m.onBeforeCompile = (sh, r) => { prev && prev(sh, r); sh.uniforms.uApp = uApp; sh.uniforms.uAppL = uAppL; sh.uniforms.uRes = uRes; sh.uniforms.uNeckS = uNeckS; sh.uniforms.uRvDir = uRvDir; sh.fragmentShader = wrap(sh.fragmentShader); }; m.customProgramCacheKey = () => 'rv8' + (hard ? 1 : 0); m.needsUpdate = true; }
}
const revealOn = (o) => o && o.traverse((c) => { if (c.material) (Array.isArray(c.material) ? c.material : [c.material]).forEach(addReveal); });
const appear = { a: 1, from: 1, to: 1, t: 1, dur: 3.6 };
function startAppear(to, dur) { appear.from = appear.a; appear.to = to; appear.t = 0; appear.dur = Math.max(0.1, (+dur || 3.6) * (to > appear.a ? 1.35 : 1)); }   /* vr3: materialize builds 35% longer */

// ---------- v11 animated aether: curl-noise flow, limb energy, moving rim light, floor motes ----------
// Every layer is GPU-animated (no static sprite). Drawn before the post chain, so the ?hue= / setTint pass tints it like the rest.
// Nothing is emitted above the neck line, and all of it fades out under the head, so none of it can read as hair.
const uFX = { value: new THREE.Vector4(0, 0, 0, 0) };   // x voice level (smoothed), y walk weight, z travel z, w spare
const uRing = { value: new THREE.Vector3() };
const uArmPts = { value: [0,1,2,3,4,5].map(() => new THREE.Vector3(0, -9, 0)) };   // vr2: L/R shoulder, elbow, wrist (world) for the swirl arm fade
const uApp = { value: 1 };
const uAppL = { value: 1 };   // vr2: presence on a linear clock (the reveal sweep and the head fade use this; uApp stays eased for the aether layers)   // v12 materialize/dissolve progress: 0 = gone, 1 = fully present
const uGain = { value: 1 };  // v11b: LOOK.fx.gain, overall brightness of the aether layers          // floor-ring centre (follows her travel)
const CURL = /* glsl */`
  vec3 pot(vec3 p){ return vec3(noise(p), noise(p+vec3(31.4,7.1,2.9)), noise(p+vec3(-9.3,17.7,41.1))); }
  vec3 curl(vec3 p){ const float e=0.12; vec3 dx=vec3(e,0,0), dy=vec3(0,e,0), dz=vec3(0,0,e);
    vec3 a=pot(p+dy)-pot(p-dy), b=pot(p+dz)-pot(p-dz), c=pot(p+dx)-pot(p-dx);
    return vec3(a.z-b.y, b.x-c.z, c.y-a.x)/(2.0*e); }`;
const FX_FS = /* glsl */`
  uniform vec3 uA; uniform vec3 uB; uniform vec2 uRes; varying float vA; varying float vC;
  void main(){ vec2 e=min(gl_FragCoord.xy, uRes-gl_FragCoord.xy); float edge=smoothstep(0.0, 0.09*uRes.y, min(e.x,e.y));   // v11b: fade near the frame edge (no bright border pixels)
    vec2 q=gl_PointCoord-0.5; float d=length(q); if(d>0.5) discard;
    float s=exp(-d*d*18.0); float a=min(s*vA,1.0)*edge;
    gl_FragColor=vec4(mix(mix(uA,uB,clamp(vC,0.0,1.0)),vec3(0.86,0.8,1.0),clamp(vC-1.0,0.0,1.0))*a*1.5,a); }`;
function fxMaterial(vs, ref, extra = {}) {
  return new THREE.ShaderMaterial({
    uniforms: { uTime: uFlow, uFX, uRing, uApp, uGain, uRes, uNeck: shellNeck, uA: { value: V(LOOK.violet) }, uB: { value: V(LOOK.lilac) }, uPx: { value: renderer.getPixelRatio() },
      ...(ref ? skinUniforms(ref) : {}), ...extra },
    vertexShader: `${NOISE}${CURL}${ref ? SKIN : ''}
      uniform float uTime; uniform vec4 uFX; uniform vec3 uRing; uniform float uApp; uniform float uGain; uniform float uNeck; uniform float uPx; varying float vA; varying float vC;
      ${vs}`,
    fragmentShader: FX_FS, transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending });
}
const headFade = /* glsl */`(1.0 - smoothstep(uNeck - 0.06, uNeck + 0.02, p.y))`;
function surfaceGeo(samples, fill) {
  const n = samples.length, g = new THREE.BufferGeometry();
  const pos = new Float32Array(n * 3), si = new Float32Array(n * 4), sw = new Float32Array(n * 4), sd = new Float32Array(n * 4);
  samples.forEach((s, i) => { pos.set([s.p.x, s.p.y, s.p.z], 3 * i); si.set(s.si, 4 * i); sw.set(s.sw, 4 * i); sd.set(fill(s, i), 4 * i); });
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); g.setAttribute('sIdx', new THREE.BufferAttribute(si, 4));
  g.setAttribute('sW', new THREE.BufferAttribute(sw, 4)); g.setAttribute('fx', new THREE.BufferAttribute(sd, 4)); return g;
}
const pointsOf = (g, m, order) => { const p = new THREE.Points(g, m); p.frustumCulled = false; p.renderOrder = order; return p; };
// 1) flow: motes born on her skin, carried off by slow curl noise with a soft rise; they trail behind while she walks
function makeFlow(samples, ref) {
  const g = surfaceGeo(samples, () => [Math.random(), Math.random(), Math.random(), Math.random()]);
  return pointsOf(g, fxMaterial(`attribute vec4 sIdx; attribute vec4 sW; attribute vec4 fx;
    void main(){ vec3 b=skinPoint(position,sIdx,sW);
      float L=12.0+10.0*fx.y, sp=0.8+0.2*uFX.x;   /* vr3: slower, longer lives (was 8+8, 1.0) */ float ph=fract(fx.x+uTime*sp/L);
      vec3 q=b*1.6+vec3(0.0,-uTime*0.07,fx.z*5.0);
      vec3 p=b + curl(q)*0.085*ph + vec3(0.0,0.2*ph*(0.5+fx.w),0.0) + normalize(curl(q*0.5+3.0))*0.05*ph + vec3(sin(uTime*0.23+fx.z*31.0),0.0,cos(uTime*0.19+fx.w*27.0))*0.025*ph;   /* vr3: wider curl + slow lateral sway: more drifting life, same count */
      p.z -= uFX.y*0.55*ph*ph;   // walking: the flow streams back off her
      float g=smoothstep(0.0,0.6,uApp);   // v12: gather -- motes drift in from around her and settle onto her skin
      vec3 dir=normalize(fract(sin(vec3(fx.x*91.7+fx.w*13.1, fx.y*47.3+fx.z*7.9, fx.z*63.1+fx.x*29.3))*43758.5453)*2.0-1.0+vec3(0.0,0.0,0.001))*vec3(1.0,0.6,1.0);
      vec3 far=b+dir*(0.35+0.9*fx.w)+curl(b*0.8+vec3(0.0,uTime*0.05,fx.z))*0.25;
      p=mix(far,p,g*g*(3.0-2.0*g));
      float aN=sin(3.14159*ph)*(0.8+0.7*fx.w)*(0.85+0.5*uFX.x);
      vA=mix((0.55+0.6*fx.w)*smoothstep(0.0,0.15,uApp)*(0.85+0.15*sin(uTime*0.5+fx.z*30.0)), aN, smoothstep(0.55,0.85,uApp))*uGain * ${headFade};
      vC=0.35+0.9*fx.z;
      vec4 mv=viewMatrix*vec4(p,1.0); gl_Position=projectionMatrix*mv; gl_PointSize=(2.0+2.6*fx.w)*uPx*(3.0/-mv.z); }`, ref), 6);
}
// 2) energy: pulses that travel along her limbs, core -> hands and feet (and up the torso to the collarbones)
function makeEnergy(samples, ref) {
  const g = surfaceGeo(samples, (s) => [s.lc, s.lid, Math.random(), Math.random()]);
  return pointsOf(g, fxMaterial(`attribute vec4 sIdx; attribute vec4 sW; attribute vec4 fx;
    void main(){ vec3 b=skinPoint(position,sIdx,sW); vec3 p=b + curl(b*3.0+vec3(0.0,uTime*0.05,0.0))*0.006;
      float v=0.12*(1.0+0.7*uFX.x+0.4*uFX.y);   /* vr3: was 0.16 */
      float j=fx.z*0.05+floor(fx.w*6.0)/6.0; float x=fract(fx.x*0.9 + j - uTime*v + fx.y*0.37), x2=fract(fx.x*0.9 + j*1.7 - uTime*v*0.63 + fx.y*0.71 + 0.5);
      float pulse=exp(-pow((x-0.5)*7.0,2.0)) + 0.6*exp(-pow((x2-0.5)*10.0,2.0));
      float tw=0.75+0.25*sin(uTime*(0.35+fx.w*0.4)+fx.z*40.0);   /* v13: slow shimmer, no per-particle flicker (read as boiling) */
      vA=(0.08*tw + 1.3*pulse*(0.8+0.6*uFX.x)*(1.0-0.8*smoothstep(0.6,0.95,fx.x))*(fx.y<2.5?0.2:(fx.y>9.5?0.12:(fx.y>5.5?0.7:1.0))))*(0.5+0.5*fx.z) * ${headFade};
      vA=min(vA,0.55)*uGain;
      float tr=clamp((uApp-0.2)/0.5,0.0,1.0)*1.15, hump=exp(-pow((uApp-0.6)/0.17,2.0));   // v12: filaments trace her form, core -> hands/feet
      float damp=(fx.y<2.5?0.3:(fx.y>9.5?0.25:1.0)); float vis=smoothstep(fx.x-0.08,fx.x,tr)*step(0.001,tr), front=exp(-pow((fx.x-tr)*11.0,2.0))*hump*damp;
      vA=vis*vA + (front*0.7 + vis*hump*0.18)*(0.5+0.5*fx.z)*${headFade}; pulse=max(pulse,front);
      vC=0.6+0.9*pulse;
      vec4 mv=viewMatrix*vec4(p,1.0); gl_Position=projectionMatrix*mv; gl_PointSize=(1.5+1.6*fx.w+2.2*pulse)*uPx*(3.0/-mv.z); }`, ref), 6);
}
// 3) rim light: a breathing halo just off her silhouette; bright bands drift slowly up the body
function makeRim(samples, ref) {
  const g = surfaceGeo(samples, (s) => [s.n.x, s.n.y, s.n.z, Math.random()]);
  return pointsOf(g, fxMaterial(`attribute vec4 sIdx; attribute vec4 sW; attribute vec4 fx;
    void main(){ vec3 b=skinPoint(position,sIdx,sW), bn=skinPoint(position+fx.xyz*0.03,sIdx,sW); vec3 n=normalize(bn-b);
      float br=0.5+0.5*sin(uTime*1.25 + fx.w*0.6);   // ~5 s breath
      vec3 p=b + n*(0.012+0.008*br);   /* v13: no per-point radial jitter */
      vec3 vd=normalize(cameraPosition-p); float rim=pow(1.0-abs(dot(n,vd)),3.0);
      float band=0.35+0.65*pow(0.5+0.5*sin(p.y*5.0 - uTime*0.55 + 1.7*sin(uTime*0.13)),3.0);
      vA=rim*band*(0.6+0.45*br+0.5*uFX.x)*uGain*smoothstep(0.55,0.95,uApp) * ${headFade};
      vC=0.8+0.5*band;
      vec4 mv=viewMatrix*vec4(p,1.0); gl_Position=projectionMatrix*mv; gl_PointSize=(2.2+1.2*fx.w)*uPx*(3.0/-mv.z); }`, ref), 6);
}
// 4) floor motes: rise from the ring in slow spirals and fade before head height; they lag behind while she walks
function makeMotes(n, floorY, h) {
  const g = new THREE.BufferGeometry(), pos = new Float32Array(n * 3), sd = new Float32Array(n * 4);
  for (let i = 0; i < n; i++) { pos.set([Math.random() * 6.283, 0.28 + Math.pow(Math.random(), 0.7) * 0.8, floorY], 3 * i); sd.set([Math.random(), Math.random(), Math.random(), Math.random()], 4 * i); }
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); g.setAttribute('fx', new THREE.BufferAttribute(sd, 4));
  return pointsOf(g, fxMaterial(`attribute vec4 fx;
    void main(){ float L=9.5+6.5*fx.y, ph=fract(fx.x+uTime/L);   /* vr3: slower rise (was 7+5) */
      float a=position.x + ph*(0.8+0.6*fx.z)*(fx.w<0.5?1.0:-1.0), r=position.y*(1.0+0.35*ph);
      vec3 p=vec3(uRing.x+cos(a)*r, position.z + ph*${(h * 0.75).toFixed(3)}*(0.45+0.55*fx.z), uRing.z+sin(a)*r*0.85);
      p += curl(p*1.2+vec3(0.0,-uTime*0.06,fx.w*7.0))*0.06*ph;
      p.z -= uFX.y*0.8*ph;
      float col=smoothstep(0.22,0.4,length(p.xz-uRing.xz));   // keep clear of her body column
      vA=pow(sin(3.14159*ph),1.5)*(1.2+1.2*fx.w)*mix(1.0,col,smoothstep(${(floorY + h * 0.55).toFixed(3)},${(floorY + h * 0.8).toFixed(3)},p.y))*(1.0-smoothstep(${(floorY + h * 0.62).toFixed(3)},${(floorY + h * 0.85).toFixed(3)},p.y))*(0.9+0.3*uFX.x)*uGain*smoothstep(0.3,0.9,uApp);
      vC=0.3+0.9*fx.z;
      vec4 mv=viewMatrix*vec4(p,1.0); gl_Position=projectionMatrix*mv; gl_PointSize=(3.4+4.2*fx.w)*uPx*(3.0/-mv.z); }`, null), 4);
}
// limb coordinate for the energy pulses: chain order of the dominant bone + projection along it
const CHAINS = [[/Hip$|Pelvis/, /Waist/, /Spine01/, /Spine02/], [/Clavicle/, /Upperarm/, /Forearm/, /Hand$/, /(Thumb|Index|Mid|Ring|Pinky)/], [/Thigh/, /Calf/, /Foot$/, /ToeBase$/]];
function limbCoord(s, ref) { const bones = ref.skeleton.bones, k = s.sw.indexOf(Math.max(...s.sw)), bn = bones[s.si[k]]; if (!bn) return null;
  const nm = bn.name.replace(/^CC_Base_/, ''); const side = /^L_/.test(nm) ? 0 : /^R_/.test(nm) ? 1 : 2;
  for (let c = 0; c < CHAINS.length; c++) { const o = CHAINS[c].findIndex((r) => r.test(nm.replace(/^[LR]_/, ''))); if (o < 0) continue;
    const ch = bn.children.find((x) => x.isBone); const p = skinnedNow(s, new THREE.Vector3()), b0 = bn.getWorldPosition(new THREE.Vector3());
    let t = 0.5; if (ch) { const b1 = ch.getWorldPosition(new THREE.Vector3()), d = b1.clone().sub(b0); t = Math.max(0, Math.min(1, p.clone().sub(b0).dot(d) / Math.max(1e-6, d.lengthSq()))); }
    return { lc: (o + t) / CHAINS[c].length, lid: c * 3 + side + (c > 0 && o >= CHAINS[c].length - 2 ? 10 : 0) }; }   // +10: hand/finger/foot/toe (dense, would bloom)
  return null; }
function triNormal(s) { const g = s.mesh.geometry, P = g.attributes.position; let best = null, bd = 1e9; const v = new THREE.Vector3();
  // nearest vertex normal (bind pose); cheap and good enough for a halo
  if (!g.attributes.normal) g.computeVertexNormals(); const N = g.attributes.normal;
  if (!s.mesh.__grid) { const G = new Map(); for (let i = 0; i < P.count; i += 1) { v.fromBufferAttribute(P, i); const key = `${Math.round(v.x * 40)},${Math.round(v.y * 40)},${Math.round(v.z * 40)}`; if (!G.has(key)) G.set(key, i); } s.mesh.__grid = G; }
  const key = `${Math.round(s.p.x * 40)},${Math.round(s.p.y * 40)},${Math.round(s.p.z * 40)}`; let i = s.mesh.__grid.get(key);
  if (i === undefined) { for (let j = 0; j < P.count; j += 7) { v.fromBufferAttribute(P, j); const d = v.distanceToSquared(s.p); if (d < bd) { bd = d; best = j; } } i = best; }
  return new THREE.Vector3().fromBufferAttribute(N, i).normalize(); }
function makeAetherFX(notHair, ref, floorY, h, scene) {
  const F = LOOK.fx || {}; if (F.on === false) return null;
  const below = (s) => skinnedNow(s, new THREE.Vector3()).y < shellNeck.value - 0.03;
  // v13: dense at her feet, thinning going up (keep-probability falls with height: 1 at the floor, ~0.15 at the shoulders)
  const grad = (s) => { const y = (skinnedNow(s, new THREE.Vector3()).y - floorY) / Math.max(0.1, shellNeck.value - floorY); return Math.random() < 1.0 - 0.85 * Math.pow(Math.min(1, Math.max(0, y)), 0.8); };
  // v14e: filament density follows limb volume. Upper arms/forearms sit high, so the height gradient left them a few strands (arms read as strings while speaking); give them a fixed ~55% keep instead.
  const isArm = (s) => { const c = limbCoord(s, ref); return !!c && c.lid >= 3 && c.lid <= 5; };
  const isHand = (s) => { const c = limbCoord(s, ref); return !!c && c.lid >= 13 && c.lid <= 15; };   // v14e: hand/finger surface: motes there fog the fingers into a blob, keep ~1 in 4
  const gradV = (s) => isArm(s) ? Math.random() < 0.9 :   /* vr3: arm surface filaments denser (was 0.55) so arms read as volume */ isHand(s) ? Math.random() < 0.25 * (grad(s) ? 1 : 0) : grad(s);
  const body = notHair.filter((o) => !/eye|teeth|tongue|brow|lash|tear|occlu/i.test(o.name));
  const flowV = (s) => isArm(s) ? Math.random() < 0.2 : grad(s) && (skinnedNow(s, new THREE.Vector3()).y < shellNeck.value - 0.22 || Math.random() < 0.5);   /* vr3: free-floating flow motes thinned on arms and shoulders so they don't wrap her */
  const flow = sampleSurface(body, Math.round((F.flow ?? 7000) * 6)).filter(below).filter(flowV).slice(0, F.flow ?? 7000);
  const en = sampleSurface(body, Math.round((F.energy ?? 9000) * 8)).filter(below).filter(gradV).map((s) => { const c = limbCoord(s, ref); return c ? Object.assign(s, c) : null; }).filter(Boolean).slice(0, F.energy ?? 9000);
  const rim = sampleSurface(body, Math.round((F.rim ?? 6000) * 4)).filter(below).filter(grad).slice(0, F.rim ?? 6000).map((s) => Object.assign(s, { n: triNormal(s) }));
  uGain.value = F.gain ?? 1;
  const arms = sampleSurface(body, Math.round((F.arms ?? 0) * 30)).filter(below).filter(grad).filter((s) => { const c = limbCoord(s, ref); return c && c.lid >= 3 && c.lid <= 5; })   /* upper/forearm only, not the dense hands */.slice(0, F.arms ?? 0);   // v11b: extra flowing light on the arms
  const objs = [makeFlow(flow, ref), makeEnergy(en, ref), makeRim(rim, ref), makeMotes(F.motes ?? 1600, floorY, h)];
  if (arms.length) objs.push(makeFlow(arms, ref));
  for (const o of objs) scene.add(o);
  return { counts: { flow: flow.length, arms: arms.length, energy: en.length, rim: rim.length, motes: F.motes ?? 1600 } };
}

// ---------- ribbons (GPU): dress ribbons, hair wisps, wide feature swirls ----------
// One strip per ribbon: SEG x 2 vertices. Per-vertex: u (along), side (+-1).
// Per-ribbon: root (bind pose) + skin, kind (0 dress, 1 hair, 2 feature), seed/spread/width/brightness, angle.
const RIBBON_VS = /* glsl */`
  ${SKIN}
  attribute float u; attribute float side; attribute vec4 sIdx; attribute vec4 sW;
  attribute vec4 prm;    // x seed, y spread, z width, w brightness
  attribute vec2 kind;   // x kind, y base angle
  uniform float uTime; uniform float uFloor; uniform float uShinLo; uniform vec3 uCenter; uniform float uH; uniform float uHairLen; uniform float uSwirlMax; uniform vec3 uArm[6];
  varying vec2 vUv; varying float vSeed; varying float vBright; varying float vKind;
  vec3 bez(vec3 a, vec3 b, vec3 c, vec3 d, float t){ float s=1.0-t; return a*s*s*s+b*3.0*s*s*t+c*3.0*s*t*t+d*t*t*t; }
  vec3 path(vec3 r, float t){
    float sd=prm.x, sp=prm.y, k=kind.x, ang=kind.y, T=uTime;
    float sw=sin(T*(0.25+0.3*fract(sd*7.0))+sd*30.0), sw2=cos(T*(0.2+0.25*fract(sd*13.0))+sd*17.0);
    vec3 out2 = normalize(vec3(r.x-uCenter.x, 0.0, r.z-uCenter.z) + vec3(1e-4,0.0,0.0));
    if (k < 0.5) {            // dress ribbon: hugs, then S-waves down onto the floor
      float sideS = sign(r.x-uCenter.x+1e-4);
      vec3 p1 = r + vec3(sideS*(0.015+sp*0.04)+sw*0.03, -0.3, sw2*0.03-0.01);
      vec3 p2 = vec3(uCenter.x + sideS*(0.08+sp*0.12) + sin(T*0.4+sd*9.0)*0.04, uFloor+0.06+0.03*sw2, uCenter.z+sw*0.04);
      float hem = 0.3 + sp*0.95;        // pooled hem radius
      float a2 = ang + 0.25*sin(T*0.2+sd*6.0);
      vec3 p3 = vec3(uCenter.x + cos(a2)*hem, uFloor+0.003, uCenter.z + sin(a2)*hem*0.85);
      vec3 p = bez(r,p1,p2,p3,t); float env=sin(3.14159*t)*(1.0-t);
      float wrap = (0.04 + 0.05*sp) * smoothstep(0.0, 0.25, t) * (1.0 - smoothstep(0.75, 1.0, t));
      float ph = t*(6.0+sp*5.0) - T*0.7 + sd*20.0;
      p.x += env*sin(t*(5.0+sp*4.0) - T*0.8 + sd*20.0)*0.03 + wrap*sin(ph);
      p.z += env*cos(t*4.0 - T*0.6 + sd*11.0)*0.03 + wrap*cos(ph);   // spirals around the legs on the way down
      { vec2 cd = normalize((cameraPosition - r).xz + vec2(1e-4, 0.0)); vec2 rel = (p - r).xz; float fw = dot(rel, cd), lat = abs(rel.x*cd.y - rel.y*cd.x);
        float band = smoothstep(uFloor+uShinLo, uFloor+uShinLo+0.07, p.y) * (1.0 - smoothstep(uFloor+uH*0.40, uFloor+uH*0.46, p.y));
        float m = band * (1.0 - smoothstep(0.12, 0.21, lat)); p.xz += cd * (mix(fw, min(fw, -0.08), m) - fw); }   /* r7: strands that fall across the camera side of the shins (walk f60) are eased behind the legs; floor pool (y < 5 cm) and knees up untouched */
      p.y = max(p.y, uFloor+0.003);
      return p;
    } else if (k < 1.5) {     // hair wisp: lifts off the head, drifts out and falls a little
      float len = (0.25 + sp*0.55) * uHairLen;
      vec3 p1, p2, p3;
      if (uHairLen > 1.0) {   // long hair: drops close to the head, then falls straight down over back/shoulders, swaying gently
        float lift = 0.07 + sp*0.05;
        p1 = r + out2*0.03 + vec3(0.0, -len*0.15, 0.0);
        p2 = r + out2*lift + vec3(sw*0.012, -len*0.55, sw2*0.012);
        p3 = r + out2*(lift + 0.02) + vec3(sin(T*0.35+sd*5.0)*0.025, -len, cos(T*0.3+sd*3.0)*0.02);
      } else {
        p1 = r + out2*0.035 + vec3(0.0, 0.01, 0.0);
        p2 = r + out2*(0.06+sp*0.08) + vec3(sw*0.05, -len*0.5, sw2*0.05);
        p3 = r + out2*(0.1+sp*0.16)*uHairLen + vec3(sin(T*0.3+sd*5.0)*0.1, -len, cos(T*0.27+sd*3.0)*0.08);
      }
      vec3 p = bez(r,p1,p2,p3,t);
      p += vec3(sin(t*6.0 - T*0.9 + sd*40.0), 0.0, cos(t*5.0 - T*0.7 + sd*21.0))*(uHairLen > 1.0 ? 0.008 : 0.02)*t;
      return p;
    } else {                  // feature ribbon: wide loop that rises and swirls around her down to the floor
      // Dominant sweep: one long lopsided arc (not a full loop), mostly to one side, rising then falling away.
      // v6: curling S-curve. Angle advances ~0.85 turn (wraps behind her and comes forward again),
      // while the radius breathes in and out, so the projected curve reads as an S, not a ring.
      float dir = fract(sd*3.7) > 0.35 ? 1.0 : -1.0;
      float turns = 0.75 + fract(sd*5.3)*0.2;
      float th = ang + dir*(t*turns*6.2832 + 0.35*sin(t*6.2832) + 0.12*sin(T*0.15+sd*4.0));
      float rad = 0.12 + (0.38 + sp*0.25)*t + 0.16*sin(3.14159*t*1.5 + sd)*t;
      // v7: rise first (wrapping up her body), then spiral down to the floor.
      float y = mix(r.y, uFloor + 0.01, smoothstep(0.35, 1.0, t)) + (0.18 + 0.1*fract(sd*9.1))*sin(3.14159*min(t/0.5,1.0))
              + 0.05*sin(t*9.0 + sd*5.0 - T*0.3)*(1.0-t);
      vec3 helix = vec3(uCenter.x + cos(th)*rad*1.1, y, uCenter.z + sin(th)*rad*0.8);
      helix.x += sin(t*5.0 - T*0.5 + sd*7.0)*0.03*t;
      vec3 q = mix(r, helix, smoothstep(0.0, 0.12, t));
      // v8: keep sweeps out of the face. Above the chin line, near the head, push them behind it.
      float headBand = smoothstep(uFloor + uH*0.78, uFloor + uH*0.82, q.y) * (1.0 - smoothstep(0.12, 0.22, abs(q.x - uCenter.x)));
      q.z = mix(q.z, min(q.z, uCenter.z - 0.16), headBand);
      float frontB = (1.0 - smoothstep(0.16, 0.3, abs(q.x - uCenter.x))) * smoothstep(0.0, 0.2, t); q.z = mix(q.z, min(q.z, uCenter.z - 0.12), frontB);   // v13: no sweeps across the front of her body
      if (uSwirlMax > 0.0) { float top = uFloor + uH*uSwirlMax; if (q.y > top) q.y = top + (q.y - top)*0.15; }   // keep swirls below the head
      return q;
    }
  }
  void main(){
    vec3 r = skinPoint(position, sIdx, sW);
    float t = u;
    vec3 p = path(r, t), pa = path(r, max(t-0.01,0.0)), pb = path(r, min(t+0.01,1.0));
    // Screen-space facing: offset perpendicular to the projected tangent, so the strip always faces the camera.
    vec4 c0 = projectionMatrix*viewMatrix*vec4(p,1.0);
    vec4 ca = projectionMatrix*viewMatrix*vec4(pa,1.0), cb = projectionMatrix*viewMatrix*vec4(pb,1.0);
    float aspect = projectionMatrix[1][1]/projectionMatrix[0][0];
    vec2 d = (cb.xy/cb.w - ca.xy/ca.w)*vec2(aspect,1.0);
    vec2 nrm = length(d) > 1e-6 ? normalize(vec2(-d.y, d.x)) : vec2(1.0,0.0);
    float wTaper = kind.x > 1.5 ? sin(3.14159*clamp(t*1.05,0.0,1.0))*0.8+0.2 : (kind.x > 0.5 ? (1.0-t*0.85) : 0.5+2.2*t*t);
    c0.xy += vec2(nrm.x/aspect, nrm.y) * side * prm.z * wTaper * projectionMatrix[1][1];
    gl_Position = c0;
    vUv = vec2(t, side*0.5+0.5); vSeed = prm.x; vBright = prm.w; vKind = kind.x;
    { // keep the front of the stomach clear: swirls fade out where they'd cross it (reads as passing behind her)
      float band = smoothstep(uFloor + uH*0.5, uFloor + uH*0.54, p.y) * (1.0 - smoothstep(uFloor + uH*0.68, uFloor + uH*0.72, p.y));
      float overlap = 1.0 - smoothstep(0.1, 0.17, abs(p.x - uCenter.x));
      if (kind.x > 1.5) vBright *= 1.0 - band*overlap;
    }
    if (kind.x > 1.5) { // vr2: the wide swirls also fade where they cross an arm on screen (they cut across her left arm at 0:13); reads as passing behind it
      vec2 q = c0.xy/c0.w*vec2(aspect,1.0); float dm = 9.0;
      for (int j=0;j<2;j++) for (int i=0;i<3;i++) { vec3 PA = uArm[j*3+min(i,2)], PB = i<2 ? uArm[j*3+i+1] : uArm[j*3+2] + (uArm[j*3+2]-uArm[j*3+1])*0.4; vec4 A = projectionMatrix*viewMatrix*vec4(PA,1.0), B = projectionMatrix*viewMatrix*vec4(PB,1.0);   /* i=2: the hand, ~40% of a forearm past the wrist */
        vec2 a2 = A.xy/A.w*vec2(aspect,1.0), b2 = B.xy/B.w*vec2(aspect,1.0), ab = b2-a2; float h = clamp(dot(q-a2,ab)/max(dot(ab,ab),1e-6),0.0,1.0); dm = min(dm, length(q-a2-ab*h)); }
      vBright *= mix(0.12, 1.0, smoothstep(0.035, 0.09, dm));
    }
  }`;
const RIBBON_FS = /* glsl */`
  uniform float uTime; uniform vec3 uA; uniform vec3 uB;
  varying vec2 vUv; varying float vSeed; varying float vBright; varying float vKind;
  void main(){
    float t=vUv.x, across=vUv.y; float edge=1.0-abs(across*2.0-1.0);
    float a;
    if (vKind > 1.5) {        // wide ribbon = a bundle of fine threads with soft body
      float fib = 0.0;
      for (int i=0;i<4;i++){ float fi=float(i); float c=0.5+0.38*sin(t*(9.0+fi*3.0)+vSeed*50.0+fi*1.7 - uTime*0.3);
        fib += smoothstep(0.06,0.0,abs(across-c)); }
      a = (pow(edge,2.0)*0.22 + fib*0.55) * smoothstep(0.0,0.08,t) * smoothstep(1.0,0.75,t);
    } else {
      a = pow(edge,1.6) * smoothstep(0.0,0.06,t) * (vKind > 0.5 ? smoothstep(1.0,0.4,t) : mix(1.0,0.3,t*t));
    }
    float flow = 0.55 + 0.45*sin(t*13.0 - uTime*1.1 - vSeed*40.0);
    a *= flow * vBright;
    gl_FragColor = vec4(mix(uB, uA, 0.25+0.6*t)*a*1.5, a);
  }`;
function makeRibbons(roots, ref, floorY, center, h) {
  const SEG = 96, n = roots.length, V2 = n * SEG * 2;
  const pos = new Float32Array(V2 * 3), u = new Float32Array(V2), side = new Float32Array(V2),
    si = new Float32Array(V2 * 4), sw = new Float32Array(V2 * 4), prm = new Float32Array(V2 * 4), kind = new Float32Array(V2 * 2), index = [];
  roots.forEach((r, s) => {
    const seed = Math.random(), K = r.kind;
    const width = K === 2 ? 0.05 + Math.random() * 0.03 : K === 1 ? (r.flyaway ? 0.0025 : 0.002 + Math.random() * 0.004) : (0.003 + Math.pow(Math.random(), 2) * 0.012) * (LOOK.dressWidth ?? 1);
    const bright = K === 0 ? (0.35 + Math.pow(Math.random(), 1.5) * 1.1) * (LOOK.dressBright ?? 1) : K === 2 ? 1.1 + Math.random() * 0.3 : r.flyaway ? 1.2 : 0.35 + Math.pow(Math.random(), 1.5) * 1.1;
    const FEAT = [0.15, -0.45, 0.55, 2.7];   // lopsided: three sweeps start toward her right side, one to the left
    const spread = r.flyaway ? 1.4 + Math.random() * 0.5 : Math.random();
    const ang = K === 2 ? FEAT[r.fi % FEAT.length] + (Math.random() - 0.5) * 0.3 : Math.random() * Math.PI * 2;
    for (let k = 0; k < SEG; k++) for (let e = 0; e < 2; e++) {
      const v = (s * SEG + k) * 2 + e;
      pos.set([r.p.x, r.p.y, r.p.z], v * 3); u[v] = k / (SEG - 1); side[v] = e ? 1 : -1;
      si.set(r.si, v * 4); sw.set(r.sw, v * 4); prm.set([seed, spread, width, bright], v * 4); kind.set([K, ang], v * 2);
    }
    for (let k = 1; k < SEG; k++) { const v = (s * SEG + k) * 2; index.push(v - 2, v - 1, v, v - 1, v + 1, v); }
  });
  const g = new THREE.BufferGeometry();
  for (const [name, arr, sz] of [['position', pos, 3], ['u', u, 1], ['side', side, 1], ['sIdx', si, 4], ['sW', sw, 4], ['prm', prm, 4], ['kind', kind, 2]])
    g.setAttribute(name, new THREE.BufferAttribute(arr, sz));
  g.setIndex(index);
  const m = new THREE.ShaderMaterial({
    uniforms: { uTime: uFlow, uA: { value: V(LOOK.violet) }, uB: { value: V(LOOK.lilac) }, uFloor: { value: floorY }, uShinLo: { value: 0.02 },
      uCenter: { value: center }, uH: { value: h }, uHairLen: { value: LOOK.hairLen ?? 1 }, uSwirlMax: { value: LOOK.swirlMaxY ?? 0 }, uArm: uArmPts, ...skinUniforms(ref) },
    vertexShader: RIBBON_VS, fragmentShader: RIBBON_FS,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
  });
  const mesh = new THREE.Mesh(g, m); mesh.frustumCulled = false; mesh.renderOrder = 3; return mesh;
}

// ---------- floor: dotted concentric rings + radial lines ----------
const FLO = { o: { value: new THREE.Vector2() }, o2: { value: new THREE.Vector2() }, k: { value: 0 }, ph: { value: 0 }, idle: 0 };   // v12d
function makeFloor(y) {
  const m = new THREE.ShaderMaterial({
    uniforms: { uTime, uFX, uA: { value: V(LOOK.violet) }, uB: { value: V(LOOK.lilac) }, uO: FLO.o, uO2: FLO.o2, uK: FLO.k, uPh: FLO.ph },
    vertexShader: `varying vec2 vP; varying vec2 vW; void main(){ vP=position.xy; vW=(modelMatrix*vec4(position,1.0)).xz; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}`,
    fragmentShader: `uniform float uTime; uniform vec4 uFX; uniform vec3 uA; uniform vec3 uB; uniform vec2 uO; uniform vec2 uO2; uniform float uK; uniform float uPh; varying vec2 vP; varying vec2 vW;
      float rg(vec2 o){ vec2 d=vW-o; d.y=-d.y; float r=length(d*vec2(1.0,1.15)); float x=r*9.0-uPh; float w=fwidth(x)*1.1;
        return smoothstep(w,0.0,abs(fract(x)-0.5))*(0.6+0.4*sin(atan(d.y,d.x)*3.0 + r*4.0 - uTime*0.3)); }
      void main(){ float r=length(vP*vec2(1.0,1.15));
        /* v12d: ring lines are world-locked (centred on uO, crossfading to uO2), only the light pool follows her, so planted feet never slide against them */
        float ring=mix(rg(uO),rg(uO2),uK); float wob=1.0;
        float fall=exp(-r*0.9)*smoothstep(0.08,0.35,r);
        float a=ring*fall*wob*0.35 + exp(-r*r*10.0)*0.12*(1.0-0.9*clamp(uFX.y,0.0,1.0));   /* v14: the light pool rides with her, so while she walks it fades (it read as the floor sliding under the planted feet) */
        gl_FragColor=vec4(mix(uA,uB,0.3)*a,1.0);}`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, extensions: { derivatives: true },
  });
  const f = new THREE.Mesh(new THREE.PlaneGeometry(14, 14), m);
  f.rotation.x = -Math.PI / 2; f.position.y = y; return f;
}

// ---------- background galaxy swirl ----------
function makeGalaxy() {
  const n = 22000, pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
  const A = V(LOOK.violet), B = V(LOOK.lilac), W = new THREE.Color(1, 1, 1), c = new THREE.Color();
  for (let i = 0; i < n; i++) {
    const arm = i % 3, r = Math.pow(Math.random(), 1.6) * 9 + 0.3;
    const ang = arm * 2.094 + r * 0.55 + (Math.random() - 0.5) * (0.9 / (1 + r * 0.2));
    pos[3*i] = Math.cos(ang) * r; pos[3*i+1] = Math.sin(ang) * r; pos[3*i+2] = (Math.random() - 0.5) * 0.6;
    c.copy(A).lerp(B, Math.random() * 0.6).lerp(W, Math.max(0, 0.6 - r * 0.15)); c.multiplyScalar(0.05 + Math.random() * 0.16);
    col.set([c.r, c.g, c.b], 3 * i);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  const m = new THREE.PointsMaterial({ size: 0.03, vertexColors: true, transparent: true,
    depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true });
  // round soft sprites (plain PointsMaterial draws squares, which bloom into square halos)
  m.onBeforeCompile = (sh) => { sh.fragmentShader = sh.fragmentShader.replace('#include <color_fragment>',
    '#include <color_fragment>\n float dq = length(gl_PointCoord - 0.5); if (dq > 0.5) discard; diffuseColor.rgb *= smoothstep(0.5, 0.0, dq);'); };
  return new THREE.Points(g, m);
}

// ---------- procedural idle for rigs without clips ----------
function proceduralIdle(root) {
  // GLTFLoader strips '.' from node names (Shldr.L -> ShldrL), so match both.
  const bone = (n) => root.getObjectByName(n) || root.getObjectByName(n.replace(/\./g, ''));
  const rest = new Map(); root.traverse((o) => o.isBone && rest.set(o, o.quaternion.clone()));
  // Bring T/A-pose arms down once, in world space, so it works whatever the bone axes are.
  for (const [sh, fa, side] of [['Shldr.L', 'ForeArm.L', 1], ['Shldr.R', 'ForeArm.R', -1],
                                ['CC_Base_L_Upperarm', 'CC_Base_L_Forearm', 1], ['CC_Base_R_Upperarm', 'CC_Base_R_Forearm', -1]]) {
    const s = bone(sh), f = bone(fa); if (!s || !f) continue;
    root.updateMatrixWorld(true);
    const a = s.getWorldPosition(new THREE.Vector3()), b = f.getWorldPosition(new THREE.Vector3());
    const from = b.sub(a).normalize();
    const to = new THREE.Vector3(Math.sign(from.x || side) * 0.22, -1, 0.05).normalize();
    const dq = new THREE.Quaternion().setFromUnitVectors(from, to);
    const pw = s.parent.getWorldQuaternion(new THREE.Quaternion()), bw = s.getWorldQuaternion(new THREE.Quaternion());
    s.quaternion.copy(pw.clone().invert().multiply(dq).multiply(bw));
    rest.set(s, s.quaternion.clone());
  }
  if (LOOK.handPose) {   // pass 14: palms turned a little forward, fingers relaxed and fanned (once, at rest; idle/talking never touch these bones)
    const W = (b) => b.getWorldPosition(new THREE.Vector3());
    const turn = (b, axis, ang) => { root.updateMatrixWorld(true); const pw = b.parent.getWorldQuaternion(new THREE.Quaternion());
      const w = pw.clone().multiply(b.quaternion).premultiply(new THREE.Quaternion().setFromAxisAngle(axis, ang)); b.quaternion.copy(pw.invert().multiply(w)); rest.set(b, b.quaternion.clone()); };
    // try +ang and -ang, keep whichever scores higher (bone axes differ per side, so signs are measured, not assumed)
    const best = (b, axis, ang, score) => { const q0 = b.quaternion.clone(); turn(b, axis, ang); root.updateMatrixWorld(true); const s1 = score();
      b.quaternion.copy(q0); turn(b, axis, -ang); root.updateMatrixWorld(true); if (score() < s1) { b.quaternion.copy(q0); turn(b, axis, ang); } root.updateMatrixWorld(true); };
    const P = LOOK.handPose;
    for (const S of ['L', 'R']) {
      const b = (n) => bone('CC_Base_' + S + '_' + n); if (!b('Hand') || !b('Index1')) continue;
      root.updateMatrixWorld(true);
      const fa = b('Forearm'), H = W(b('Hand')), tw = H.clone().sub(W(fa)).normalize();
      // palms forward: the thumb swings outward (away from the body) as the forearm turns
      best(fa, tw, P.twist, () => Math.abs(W(b('Thumb3')).x) + 0.5 * W(b('Thumb3')).z);
      root.updateMatrixWorld(true);
      const h = W(b('Hand')), across = W(b('Index1')).sub(W(b('Pinky1'))).normalize(), down = W(b('Mid1')).sub(h).normalize();
      const nrm = new THREE.Vector3().crossVectors(across, down).normalize();
      if (nrm.dot(W(b('Thumb3')).sub(h)) < 0) nrm.negate();                 // palm side = the side the thumb sits on
      // fan: index away from middle, pinky away from ring, ring a little; measured per side
      for (const [f, nb, a] of [['Index1', 'Mid3', P.spread], ['Ring1', 'Mid3', P.spread * 0.35], ['Pinky1', 'Ring3', P.spread * 1.1]])
        best(b(f), nrm, a, () => W(b(f.replace('1', '3'))).distanceTo(W(b(nb))));
      // relaxed curl: a little more toward the pinky, tips move toward the palm side
      for (const [f, k] of [['Index', 0.8], ['Mid', 1.0], ['Ring', 1.15], ['Pinky', 1.3]]) for (const seg of ['1', '2', '3'])
        best(b(f + seg), across, P.curl * k * (seg === '1' ? 0.6 : 1), () => W(b(f + '3')).clone().sub(h).dot(nrm));
    }
  }
  const chest = bone('chest') || bone('CC_Base_Spine02'), head = bone('head') || bone('CC_Base_Head'),
    neck = bone('neck') || bone('CC_Base_NeckTwist01'), jaw = bone('lowerJaw') || bone('CC_Base_JawRoot');
  // Jaw opens about the world X axis, expressed in the jaw's local frame (bone axes differ between rigs).
  root.updateMatrixWorld(true);
  const jawAxis = jaw ? new THREE.Vector3(1, 0, 0).applyQuaternion(jaw.getWorldQuaternion(new THREE.Quaternion()).invert()) : null;
  const jq = new THREE.Quaternion();
  const e = new THREE.Euler(), q = new THREE.Quaternion();
  return (t) => {
    const think = state.mode === 'thinking' ? 1 : 0;
    const set = (b, x, y, z) => { if (!b) return; q.setFromEuler(e.set(x, y, z)); b.quaternion.copy(rest.get(b)).multiply(q); };
    set(chest, Math.sin(t * 1.3) * 0.015, 0, 0);
    set(neck, Math.sin(t * 0.5) * 0.02, Math.sin(t * 0.31) * 0.05, think * 0.06);
    set(head, Math.sin(t * 0.7) * 0.02 - think * 0.06, Math.sin(t * 0.43) * 0.06, Math.sin(t * 0.37) * 0.02);
    if (jaw) jaw.quaternion.copy(rest.get(jaw)).multiply(jq.setFromAxisAngle(jawAxis, (state.mode === 'talking' ? state.level : 0) * (face.visemes.length ? 0.12 : 0.18) * (0.6 + 0.4 * Math.abs(Math.sin(t * 9)))));
  };
}

// ---------- baked concavity: Laplacian along the normal, diffused to body-feature scale ----------
function bakeCavity(geo, ITER = 40, HP = 80, NAME = 'aCav', PCT = 0.9) {
  const P = geo.attributes.position, N = geo.attributes.normal, n = P.count;
  // weld split vertices by position so seams don't break the stencil
  const key = new Map(), id = new Int32Array(n); let m = 0;
  for (let i = 0; i < n; i++) { const k = `${P.getX(i).toFixed(4)},${P.getY(i).toFixed(4)},${P.getZ(i).toFixed(4)}`;
    let j = key.get(k); if (j === undefined) { j = m++; key.set(k, j); } id[i] = j; }
  const pos = new Float32Array(m * 3), nor = new Float32Array(m * 3);
  for (let i = 0; i < n; i++) { const j = id[i]; pos[3*j] = P.getX(i); pos[3*j+1] = P.getY(i); pos[3*j+2] = P.getZ(i);
    nor[3*j] += N.getX(i); nor[3*j+1] += N.getY(i); nor[3*j+2] += N.getZ(i); }
  const nb = Array.from({ length: m }, () => new Set()), idx = geo.index ? geo.index.array : null, T = idx ? idx.length : n;
  for (let t = 0; t < T; t += 3) { const a = id[idx ? idx[t] : t], b = id[idx ? idx[t+1] : t+1], c = id[idx ? idx[t+2] : t+2];
    nb[a].add(b).add(c); nb[b].add(a).add(c); nb[c].add(a).add(b); }
  // smoothed positions (several Laplacian passes) -> concavity = how far the smoothed surface sits outside the real one
  let sp = pos.slice();
  for (let it = 0; it < ITER; it++) { const nx = new Float32Array(m * 3);
    for (let j = 0; j < m; j++) { let x = 0, y = 0, z = 0, k = 0; for (const q of nb[j]) { x += sp[3*q]; y += sp[3*q+1]; z += sp[3*q+2]; k++; }
      if (!k) { nx.set(sp.subarray(3*j, 3*j+3), 3*j); continue; } nx[3*j] = (sp[3*j] + x / k) / 2; nx[3*j+1] = (sp[3*j+1] + y / k) / 2; nx[3*j+2] = (sp[3*j+2] + z / k) / 2; }
    sp = nx; }
  const cav = new Float32Array(m);
  for (let j = 0; j < m; j++) { const l = Math.hypot(nor[3*j], nor[3*j+1], nor[3*j+2]) || 1;
    cav[j] = ((sp[3*j]-pos[3*j])*nor[3*j] + (sp[3*j+1]-pos[3*j+1])*nor[3*j+1] + (sp[3*j+2]-pos[3*j+2])*nor[3*j+2]) / l; }
  // high-pass: remove the broad shrink bias (whole limbs read convex) so only local hollows/ridges remain
  let base = cav.slice();
  for (let it = 0; it < HP; it++) { const nx = new Float32Array(m);
    for (let j = 0; j < m; j++) { let x = 0, k = 0; for (const q of nb[j]) { x += base[q]; k++; } nx[j] = k ? (base[j] + x / k) / 2 : base[j]; }
    base = nx; }
  for (let j = 0; j < m; j++) cav[j] -= base[j];
  const sorted = Array.from(cav).map(Math.abs).sort((a, b) => a - b), s95 = sorted[Math.floor(m * PCT)] || 1;
  const out = new Float32Array(n); for (let i = 0; i < n; i++) out[i] = Math.max(-1, Math.min(1, cav[id[i]] / s95));
  geo.setAttribute(NAME, new THREE.BufferAttribute(out, 1));
}

// ---------- load ----------
let mixer = null, idleFn = null, animator = null;
const galaxy = makeGalaxy(); galaxy.renderOrder = 7; galaxy.position.set(0, 1.4, -9); galaxy.rotation.x = -0.35; scene.add(galaxy);
const partOf = (o) => { const n = (o.name + ' ' + (o.parent ? o.parent.name : '')).toLowerCase();
  return n.includes('hair') ? 'hair' : n.includes('dress') ? 'dress' : 'other'; };

function onModel(gltf) {
  const root = gltf.scene; scene.add(root); window.__root = root;   // test hook (morph checks)
  root.updateMatrixWorld(true);
  if (!gltf.animations.length) idleFn = proceduralIdle(root);   // arms down before measuring
  root.updateMatrixWorld(true);
  const skinned = [];
  root.traverse((o) => { if (o.isSkinnedMesh) skinned.push(o); });
  for (const o of skinned) { o.skeleton.update(); if (!o.skeleton.boneTexture) o.skeleton.computeBoneTexture(); }
  const box = new THREE.Box3().setFromObject(root, true), size = box.getSize(new THREE.Vector3());
  const report = { meshes: 0, skinned: skinned.length, verts: 0, bones: skinned[0] ? skinned[0].skeleton.bones.length : 0,
    anims: gltf.animations.map((a) => a.name), size: size.toArray().map((x) => +x.toFixed(3)) };
  const ref = skinned[0];
  // GPU particles/ribbons use ref's skeleton for every source mesh: valid when all meshes share one skin.
  report.sharedSkin = skinned.every((o) => o.skeleton.bones.length === ref.skeleton.bones.length
    && o.bindMatrix.equals(ref.bindMatrix) && o.matrixWorld.equals(ref.matrixWorld)
    && o.skeleton.bones.every((b, i) => b === ref.skeleton.bones[i]));
  root.traverse((o) => {
    if (!o.isMesh) return; report.meshes++; report.verts += o.geometry.attributes.position.count;
    if (params.has('orig')) return;   // debug: original materials
    // Hide the original textures entirely; the exact shape stays as a dark violet occluder.
    const orig = Array.isArray(o.material) ? o.material[0] : o.material;
    const isHair = partOf(o) === 'hair', inMouth = /teeth|tongue/i.test(o.name + ' ' + (o.parent ? o.parent.name : ''));
    const isCornea = /cornea/i.test(orig && orig.name || '');
    const cardAlpha = !isCornea && (isHair || (orig && orig.transparent)) && orig && orig.map ? orig.map : null;   // hair/brow/lash cards: keep only their cut-out alpha
    // Body interior is drawn opaque first (writes depth), so hair and ribbons behind her head never show through the face.
    o.material = new THREE.MeshBasicMaterial({ color: V(LOOK.interior), transparent: !!cardAlpha, opacity: 1,
      ...(cardAlpha ? (isHair
        ? { color: V(LOOK.violet).multiplyScalar(0.45), alphaMap: cardAlpha, alphaTest: 0.45, transparent: false, opacity: 1, depthWrite: true, side: THREE.DoubleSide }   // cut-out hair volume, writes depth
        : { alphaMap: cardAlpha, alphaTest: 0.3, opacity: 0.6, depthWrite: false }) : {}) });
    if (cardAlpha) { o.material.onBeforeCompile = (sh) => { sh.fragmentShader = sh.fragmentShader.replace('#include <alphamap_fragment>', 'diffuseColor.a *= texture2D( alphaMap, vAlphaMapUv ).a;'); }; }
    o.renderOrder = cardAlpha && !isHair ? 1 : 0;
    if (!cardAlpha && LOOK.bodyForm) o.material.onBeforeCompile = (sh) => {   // see-through body: interior fill only from the neck up (keeps face occluding hair behind)
      sh.uniforms.uNeckY = shellNeck; sh.uniforms.uFace = FACE;
      sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying float vWy; varying float vWx;').replace('#include <project_vertex>', '#include <project_vertex>\nvWy = (modelMatrix * vec4(transformed,1.0)).y; vWx = (modelMatrix * vec4(transformed,1.0)).x;');
      sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nvarying float vWy; varying float vWx; uniform float uNeckY; uniform vec4 uFace;').replace('void main() {', 'void main() {\n float nA = smoothstep(uNeckY - 0.03, uNeckY + 0.05, vWy) * (1.0 - smoothstep(0.055, 0.085, abs(vWx - uFace.x)) * (1.0 - smoothstep(uNeckY - 0.02, uNeckY + 0.06, vWy))); if (nA < 0.03) discard;').replace('#include <opaque_fragment>', 'diffuseColor.a = nA;\n#include <opaque_fragment>');   // pass 8: solid head (p5), wide height fade down the neck
      };
    if (!cardAlpha && LOOK.bodyForm) {   // pass 8: solid face again (hides hair behind it); blended so the neck fades instead of a hard cut
      o.material.transparent = true; o.material.depthWrite = true; o.renderOrder = -1;
      if (inMouth) o.material.colorWrite = false;   // teeth/inner mouth: depth only
    };
    if (o.isSkinnedMesh) o.frustumCulled = false;   // three keeps a SkinnedMesh's bounds from its first pose; walking/gestures then culled her fill and face pass
    if (isCornea) o.visible = false;   // clear cornea layer: no fill, no glow (eyeball below stays)
    if (o.isSkinnedMesh && !inMouth && !isCornea) {
      if (!o.geometry.attributes.aCav) { if (!cardAlpha && o.geometry.attributes.normal) { bakeCavity(o.geometry); bakeCavity(o.geometry, 3, 12, 'aCavF', 0.97); } else { const z = new Float32Array(o.geometry.attributes.position.count); o.geometry.setAttribute('aCav', new THREE.BufferAttribute(z, 1)); o.geometry.setAttribute('aCavF', new THREE.BufferAttribute(z, 1)); } }
      if (!o.geometry.attributes.aHand && o.geometry.attributes.skinIndex) {   // pass 14: hand mask from skin weights
        const si = o.geometry.attributes.skinIndex, sw = o.geometry.attributes.skinWeight, hv = new Float32Array(si.count);
        const isH = o.skeleton.bones.map((b) => /_(Hand|Thumb\d|Index\d|Mid\d|Ring\d|Pinky\d)$/.test(b.name));
        for (let i = 0; i < si.count; i++) for (let k = 0; k < 4; k++) if (isH[si.getComponent(i, k)]) hv[i] += sw.getComponent(i, k);
        o.geometry.setAttribute('aHand', new THREE.BufferAttribute(hv, 1)); }
      if (!o.geometry.attributes.aWr && o.geometry.attributes.skinIndex) {   // r8: wrist proximity in bind pose (distance to the _Hand bone, normalised by forearm length)
        const P = o.geometry.attributes.position, wv = new Float32Array(P.count), bs = o.skeleton.bones, inv = o.skeleton.boneInverses;
        const bp = (i) => new THREE.Vector3().setFromMatrixPosition(inv[i].clone().invert());
        const v = new THREE.Vector3(), hs = [];
        bs.forEach((b, i) => { if (/_Hand$/.test(b.name)) { const f = bs.findIndex((c) => c === b.parent); const h = bp(i); let L = 0.25; if (f >= 0) { const fp = bp(f); L = Math.max(h.distanceTo(fp), 1e-4); if (/Twist/.test(bs[f].name) && bs[f].parent) { const g = bs.indexOf(bs[f].parent); if (g >= 0) L = Math.max(L, h.distanceTo(bp(g))); } } hs.push([h, L]); } });
        for (let i = 0; i < P.count; i++) { v.fromBufferAttribute(P, i).applyMatrix4(o.bindMatrix); let m = 0; for (const [h, L] of hs) { const d = v.distanceTo(h) / L; m = Math.max(m, 1 - THREE.MathUtils.smoothstep(d, 0.10, 0.5)); } wv[i] = m; }
        o.geometry.setAttribute('aWr', new THREE.BufferAttribute(wv, 1)); }
      if (!o.geometry.attributes.aElb && o.geometry.attributes.skinIndex) {   // v13: arm-only vertices get dual-quaternion skinning (elbow volume)
        const si = o.geometry.attributes.skinIndex, sw = o.geometry.attributes.skinWeight, ev = new Float32Array(si.count);
        const isA = o.skeleton.bones.map((b) => /_(Upperarm|UpperarmTwist\d+|Forearm|ForearmTwist\d+|Elbow\w*)$/.test(b.name));
        for (let i = 0; i < si.count; i++) { let w = 0; for (let k = 0; k < 4; k++) if (isA[si.getComponent(i, k)]) w += sw.getComponent(i, k); ev[i] = Math.max(0, Math.min(1, (w - 0.9) / 0.09)); ev[i] = ev[i] * ev[i] * (3 - 2 * ev[i]); }
        o.geometry.setAttribute('aElb', new THREE.BufferAttribute(ev, 1)); }
      const shell = new THREE.SkinnedMesh(o.geometry, shellMaterial(cardAlpha, !!cardAlpha && !isHair, /Std_Eye_/i.test(orig && orig.name || '')));   // same geometry, same skeleton
      if (isHair) shell.material.side = THREE.DoubleSide;
      shell.bind(o.skeleton, o.bindMatrix); shell.renderOrder = 2; shell.frustumCulled = false;
      if (!cardAlpha && !isHair) { const occ = new THREE.SkinnedMesh(o.geometry, new THREE.MeshBasicMaterial({ colorWrite: false, transparent: true, depthWrite: true })); occ.bind(o.skeleton, o.bindMatrix); occ.renderOrder = 6; occ.frustumCulled = false; o.parent.add(occ); }   // pass 11: depth-only body, drawn just before the galaxy so its dust clumps don't show through the stomach
      if (o.morphTargetInfluences) { shell.morphTargetInfluences = o.morphTargetInfluences; shell.morphTargetDictionary = o.morphTargetDictionary; }
      o.parent.add(shell); shell.position.copy(o.position); shell.quaternion.copy(o.quaternion); shell.scale.copy(o.scale);
    }
  });
  const h = size.y, cx = (box.min.x + box.max.x) / 2, cz = (box.min.z + box.max.z) / 2;
  const view = params.get('view') || 'full';
  if (view === 'torso') { camera.position.set(cx, box.min.y + h * 0.62, h * 0.9); camera.lookAt(cx, box.min.y + h * 0.6, cz); }
  else if (view === '34') { camera.position.set(cx + h * 1.4, box.min.y + h * 0.55, cz + h * 1.9); camera.lookAt(cx, box.min.y + h * 0.48, cz); }
  else if (view === 'stomach') { camera.position.set(cx, box.min.y + h * 0.6, cz + h * 0.3); camera.lookAt(cx, box.min.y + h * 0.6, cz); }
  else if (view === 'side') { camera.position.set(cx + h * 0.4, box.min.y + h * 0.95, cz + h * 0.32); camera.lookAt(cx, box.min.y + h * 0.92, cz); }
  else if (view === 'mid') { camera.position.set(cx, box.min.y + h * 0.79, cz + h * 0.82); camera.lookAt(cx, box.min.y + h * 0.785, cz); }
  else if (view === 'face') { camera.position.set(cx, box.min.y + h * 0.93, h * 0.55); camera.lookAt(cx, box.min.y + h * 0.92, cz); }
  else { FIT.box = box.clone(); fitFull(); }
  window.__cam = camera;   // test hook: inspection renders move the camera directly

  if (gltf.animations.length) {
    mixer = new THREE.AnimationMixer(root);
    const clip = gltf.animations.find((a) => /idle/i.test(a.name)) || gltf.animations[0];
    mixer.clipAction(clip).play(); report.playing = clip.name;
  } else report.playing = 'procedural (no clips in GLB)';

  if (params.get('hide')) { const re = new RegExp(params.get('hide'), 'i'); root.traverse((o) => { if (o.isMesh && re.test(o.name + ' ' + o.parent.name)) o.visible = false; }); }
  { const w = (n) => { const b = root.getObjectByName(n); return b ? b.getWorldPosition(new THREE.Vector3()).toArray().map((x) => +x.toFixed(3)) : null; };
    report.bonesAt = { head: w('CC_Base_Head'), eyeL: w('CC_Base_L_Eye'), hip: w('CC_Base_Hip') }; }
  { const e1 = root.getObjectByName('CC_Base_L_Eye'), e2 = root.getObjectByName('CC_Base_R_Eye');
    if (e1 && e2) { const m = e1.getWorldPosition(new THREE.Vector3()).add(e2.getWorldPosition(new THREE.Vector3())).multiplyScalar(0.5); FACE.value.set(m.x, m.y, m.z, 1); } }
  { const k = LOOK.eyeScale ?? 1; for (const n of ['CC_Base_L_Eye', 'CC_Base_R_Eye']) { const b = root.getObjectByName(n); if (b) b.scale.multiplyScalar(k); } }   // pass 13: eyeballs scaled about the eye-bone pivots
  report.meshNames = []; root.traverse((o) => o.isMesh && report.meshNames.push(o.name + '<' + o.parent.name + '>' + (o.material.alphaMap ? '*' : '')));
  { let top = -1e9, bot = 1e9; for (const o of skinned) { o.geometry.computeBoundingBox(); top = Math.max(top, o.geometry.boundingBox.max.y); bot = Math.min(bot, o.geometry.boundingBox.min.y); }
    shellNeck.value = box.min.y + h * 0.855;
    { // navel: deepest coarse-cavity vertex on the front midline of the stomach
      const hipB = root.getObjectByName('CC_Base_Hip'), hy = hipB ? hipB.getWorldPosition(new THREE.Vector3()).y : box.min.y + h * 0.52;
      let best = -1e9; const v = new THREE.Vector3();
      for (const o of skinned) { const c = o.geometry.attributes.aCav, P = o.geometry.attributes.position; if (!c || /hair|eye|teeth|tongue/i.test(o.name)) continue;
        for (let i = 0; i < P.count; i++) { o.getVertexPosition(i, v).applyMatrix4(o.matrixWorld);
          if (v.y < hy || v.y > hy + 0.25 || Math.abs(v.x - cx) > 0.02 || v.z < cz) continue;
          if (c.getX(i) > best) { best = c.getX(i); NAVEL.value.set(v.x, v.y, v.z, 0.0065); } } }
      report.navel = NAVEL.value.toArray().map((x) => +x.toFixed(3)).concat([+hy.toFixed(3), +cz.toFixed(3)]);
    }
    const hip = root.getObjectByName('CC_Base_Hip'); HIPY.value = hip ? hip.getWorldPosition(new THREE.Vector3()).y : box.min.y + h * 0.52; }   // world space
  const floorY = box.min.y, center = new THREE.Vector3(cx, floorY, cz);
  const hair = skinned.filter((o) => partOf(o) === 'hair'), dress = skinned.filter((o) => partOf(o) === 'dress');
  const notHair = skinned.filter((o) => partOf(o) !== 'hair');
  // Hair is many stacked cards; area sampling would pile stars on the head, so it gets a small share.
  // Keep the face calm: few stars above the neck line.
  const starSrc = [...sampleSurface(notHair, Math.round(LOOK.particles * 0.95)).filter((s) => { const q = skinnedNow(s, new THREE.Vector3());
      const y = (q.y - floorY) / Math.max(0.1, shellNeck.value - floorY); return q.y < shellNeck.value ? Math.random() < 1.0 - 0.7 * Math.pow(Math.min(1, Math.max(0, y)), 0.8) : Math.random() < 0.15; }),   // v13: thinning going up
                   ...sampleSurface(hair.length ? hair : skinned, Math.round(LOOK.particles * 0.01))];
  { const ss = makeSurfaceStars(starSrc, ref); scene.add(ss); herLayers.push(ss); }
  { const au = makeAura(center, h); scene.add(au); links.aura = au; herLayers.push(au); }   // v10 walk: aura follows her travel
  report.fx = (makeAetherFX(notHair, ref, floorY, h, scene) || {}).counts || 'off';   // v11 animated aether
  const pick = (meshes, k, test) => sampleSurface(meshes.length ? meshes : skinned, k * 8)
    .filter((s) => test(skinnedNow(s, new THREE.Vector3()))).slice(0, k);
  // long hair: roots binned by angle around the head so strands leave both sides and the back evenly (never the face)
  const evenAround = (meshes, k) => {
    const hc = new THREE.Vector3(FACE.value.x, FACE.value.y, FACE.value.z - 0.08), bins = Array.from({ length: 24 }, () => []);
    for (const s of sampleSurface(meshes.length ? meshes : skinned, k * 40)) {
      const p = skinnedNow(s, new THREE.Vector3());
      if (p.y < FACE.value.y - 0.06 || p.y > box.max.y - h * 0.03) continue;
      const a = Math.atan2(p.x - hc.x, -(p.z - hc.z));   // 0 = back, ±pi = face
      if (Math.abs(a) > 2.2) continue;
      bins[Math.min(23, Math.floor((a + 2.2) / 4.4 * 24))].push(s);
    }
    const out = []; for (let i = 0; out.length < k && i < k; i++) for (const b of bins) if (b[i] && out.length < k) out.push(b[i]);
    return out;
  };
  const roots = [
    ...pick(dress, LOOK.dressRibbons, LOOK.hemFromLegs ? (p) => p.y < floorY + h * 0.56 && p.y > floorY + h * 0.1 && Math.abs(p.x - cx) < 0.16   // hips + thighs only
      : (p) => p.y < floorY + h * 0.6 && p.y > floorY + h * 0.25).map((s) => ({ ...s, kind: 0 })),
    ...(LOOK.hairLen > 1 ? evenAround(hair, LOOK.hairWisps) : pick(hair, LOOK.hairWisps, (p) => p.y > box.max.y - h * 0.12)).map((s) => ({ ...s, kind: 1 })),
    ...pick(hair, LOOK.flyaways, (p) => p.y > box.max.y - h * 0.08 && Math.abs(p.x - cx) > 0.04).map((s) => ({ ...s, kind: 1, flyaway: true })),
    // Feature swirls leave from shoulders, waist and hips.
    // v7: sweeps start two at the shoulders, two at the hips
    ...[...(LOOK.noHeadSwirls ? [] : pick(notHair, 60, (p) => p.y > floorY + h * 0.78 && p.y < floorY + h * 0.83 && Math.abs(p.x - cx) > 0.1).slice(0, 2)),
        ...pick(notHair, 60, (p) => p.y > floorY + h * 0.47 && p.y < floorY + h * 0.55 && Math.abs(p.x - cx) > 0.08).slice(0, Math.max(0, LOOK.featureRibbons - (LOOK.noHeadSwirls ? 0 : 2)))]
      .map((s, fi) => ({ ...s, kind: 2, fi })),
  ];
  { const rb = makeRibbons(roots, ref, floorY, center, h); scene.add(rb); herLayers.push(rb); }
  { const fl = makeFloor(floorY + 0.001); scene.add(fl); links.floorRing = fl; }   // v10 walk: the ring disc follows her
  report.ribbons = { dress: roots.filter((r) => r.kind === 0).length, hair: roots.filter((r) => r.kind === 1).length, feature: roots.filter((r) => r.kind === 2).length };
  // ---- face: CC viseme + blink morphs on every mesh that has them (body, brows, teeth, tongue) ----
  const VIS = ['V_Open', 'V_Wide', 'V_Tight_O', 'V_Explosive', 'V_Lip_Open', 'V_Dental_Lip', 'V_Affricate'];
  root.traverse((o) => {
    const d = o.morphTargetDictionary; if (!d || o.material.type === 'ShaderMaterial') return;
    face.visemes.push({ inf: o.morphTargetInfluences, dict: d, vis: VIS.map((n) => d[n]),
      blink: ['Eye_Blink_L', 'Eye_Blink_R', 'Eye_Blink'].map((n) => d[n]).filter((i) => i !== undefined) });
  });
  report.morphMeshes = face.visemes.length;
  report.mapped = { visemes: VIS.filter((n) => face.visemes.some((f) => f.vis[VIS.indexOf(n)] !== undefined)),
    blink: [...new Set(face.visemes.flatMap((f) => f.blink.length ? ['Eye_Blink_L/R'] : []))] };
  if (!mixer) {   // anim: motion layer (breath, sway, gaze, blinks, expressions, states)
    animator = createAnimator(THREE, root, face, uAnim, { links });
    window.avatar = animator.api;
    animator.api.setTint = (deg) => window.aether.setTint(+deg || 0);   // v11: tint on the avatar API too
    window.aether.setState = (m) => animator.api.setState(m); window.aether.setLevel = (v) => animator.api.setLevel(v);
  }
  window.__report = report;
  status.remove();
  root.traverse((o) => { if (o.isMesh || o.isPoints) o.frustumCulled = false; });   // v10 walk (walk-copy fix): bounding spheres are cached at the origin, so once she walks off it the hair occluder got culled (white head flare)
  links.U = { FACE, NAVEL, HIPY, rest: { face: FACE.value.clone(), navel: NAVEL.value.clone(), hipY: HIPY.value } };   // v10 walk: world-space look anchors, moved with her by anim.js
  revealOn(root); herLayers.forEach(revealOn);   // v12
  if (animator) { animator.api.materialize = (d) => startAppear(1, d); animator.api.dissolve = (d) => startAppear(0, d);
    Object.defineProperty(animator.api, 'appear', { get: () => appear.a }); }
  window.__ready = true;
  console.info('[avatar] scene ready ms=' + Math.round(performance.now() - GLB_T0));
}
const loader = new GLTFLoader();
const GLB_T0 = performance.now();
const failed = (err) => { console.error('[avatar] glb failed ' + err); status.textContent = 'GLB load failed: ' + err; window.__error = String(err); };
const PRIMARY = params.get('glb') || GLB_PATH;   // ?glb= override for testing the fallback
const BASE_LOOK = { ...LOOK };
const useLook = (path) => { Object.assign(LOOK, BASE_LOOK); for (const [k, v] of Object.entries(MODEL_LOOK)) if (path.includes(k)) Object.assign(LOOK, v); };
loader.load(PRIMARY, (g) => { console.info('[avatar] glb loaded ms=' + Math.round(performance.now() - GLB_T0)); window.__model = PRIMARY; useLook(PRIMARY); onModel(g); }, undefined, (err) => {
  console.warn('[avatar] glb primary failed, using fallback ' + err);
  loader.load(FALLBACK_GLB_PATH, (g) => { window.__model = FALLBACK_GLB_PATH; useLook(FALLBACK_GLB_PATH); onModel(g); }, undefined, failed);
});

// ---------- post ----------
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), LOOK.bloom.strength, LOOK.bloom.radius, LOOK.bloom.threshold);
composer.addPass(bloom); composer.addPass(new OutputPass());
// v11: room tint, same HSV hue pass as the app (?hue= degrees, setTint at runtime); off at 0, so the untinted scene is unchanged
const tint = (() => { const rnd = Math.random; Math.random = () => 0.5; const p = new ShaderPass({
  uniforms: { tDiffuse: { value: null }, uHue: { value: 0 } }, vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
  fragmentShader: `uniform sampler2D tDiffuse; uniform float uHue; varying vec2 vUv; void main(){ vec4 c = texture2D(tDiffuse, vUv);
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0); vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r)); float d = q.x - min(q.w, q.y);
    vec3 h = vec3(fract(abs(q.z + (q.w - q.y) / (6.0 * d + 1e-10)) + uHue), d / (q.x + 1e-10), q.x);
    vec3 rgb = h.z * mix(vec3(1.0), clamp(abs(fract(h.xxx + vec3(1.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0) - 1.0, 0.0, 1.0), h.y);
    gl_FragColor = vec4(rgb, c.a); }` }); Math.random = rnd; return p; })();
window.aether.setTint = (deg) => { tint.uniforms.uHue.value = (((+deg || 0) % 360) + 360) % 360 / 360; tint.enabled = !!(+deg); };
window.aether.setTint(params.get('hue'));
composer.addPass(tint);
// Built with Math.random parked: its material UUID must not shift the ?freeze seed (A/B renders).
if (TRANSPARENT) { const rnd = Math.random; Math.random = () => 0.5; composer.addPass(new ShaderPass({ uniforms: { tDiffuse: { value: null } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
  // Light becomes alpha. The galaxy dust and bloom haze reach every pixel, so without the
  // edge fade the frame border showed as a faint box over the room; glow and rings now thin
  // out to nothing in a soft oval before the edge, with no straight border anywhere.
  // Her own bright threads inside the oval keep full strength; only the faint haze fades.
  fragmentShader: 'uniform sampler2D tDiffuse; varying vec2 vUv; void main(){ vec3 c = texture2D(tDiffuse, vUv).rgb;'
    + ' float e = 1.0 - smoothstep(0.45, 0.98, length((vUv - 0.5) * 2.0));'
    + ' e = mix(e, 1.0, smoothstep(0.2, 0.6, max(c.r, max(c.g, c.b))) * smoothstep(0.0, 0.3, e));'
    + ' c *= e; gl_FragColor = vec4(c, max(c.r, max(c.g, c.b))); }' })); Math.random = rnd; }


// Follow the view's size every frame, not only on 'resize': the dock can resize the view while
// it is hidden, and a missed event left the canvas at its old size, clipped by the dock edge.
const _sz = new THREE.Vector2();
function fitView() { renderer.getSize(_sz); if (_sz.x === innerWidth && _sz.y === innerHeight) return;
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); fitFull();
  renderer.setSize(innerWidth, innerHeight); composer.setSize(innerWidth, innerHeight);
  console.info('[avatar] canvas resize size=' + innerWidth + 'x' + innerHeight); }
addEventListener('resize', fitView);

// Talking: level 0..1 drives a slow cycle through CC visemes (crossfaded). Blinking: random 2-6 s, ~150 ms.
let visT = 0, visLvl = 0;
function updateFace(t, dt) {
  if (!face.visemes.length) return;
  const talking = state.mode === 'talking';
  visLvl += ((talking ? state.level : 0) - visLvl) * Math.min(1, dt * 18);
  visT += dt * (5 + 4 * visLvl);                       // ~5-9 viseme changes per second
  if (t > face.blinkAt && face.blinkT < 0) face.blinkT = 0;
  let blink = 0;
  if (face.blinkT >= 0) { face.blinkT += dt; const x = face.blinkT / 0.16; blink = x < 1 ? Math.sin(Math.PI * x) : 0;
    if (x >= 1) { face.blinkT = -1; face.blinkAt = t + 2 + Math.random() * 4 + (Math.random() < 0.15 ? -1.8 : 0); } }
  if (face.hold !== undefined) blink = face.hold;
  for (const f of face.visemes) {
    const n = f.vis.length, k = Math.floor(visT) % n, fr = visT % 1;
    f.vis.forEach((idx, i) => { if (idx === undefined) return;
      const w = i === k ? 1 - fr * fr : i === (k + 1) % n ? fr * fr : 0;
      f.inf[idx] = w * visLvl * (i === 0 ? 1.0 : 0.8); });
    for (const b of f.blink) f.inf[b] = blink;
  }
}
const clock = new THREE.Clock();
const FREEZE = new URLSearchParams(location.search).has('freeze') ? +new URLSearchParams(location.search).get('freeze') : null;   // test hook: fixed time so A/B renders match
const ft = []; window.__frameMs = () => ft.length ? ft.reduce((a, b) => a + b) / ft.length : null;
function frame(dt) {
  const t0 = performance.now();
  fitView();
  uTime.value += dt;
  let flow = 1;
  if (animator && FREEZE === null) flow = animator.update(dt);
  else { if (mixer) mixer.update(dt); if (idleFn) idleFn(uTime.value); updateFace(uTime.value, dt); }
  uFlow.value += dt * flow;
  if (appear.t < 1) { appear.t = Math.min(1, appear.t + dt / appear.dur); const e = appear.t * appear.t * (3 - 2 * appear.t); appear.a = appear.from + (appear.to - appear.from) * e; }   // v12
  uApp.value = appear.a; uAppL.value = appear.t >= 1 ? appear.to : appear.from + (appear.to - appear.from) * appear.t; if (appear.to !== appear.from) uRvDir.value = appear.to > appear.from ? 1 : -1; renderer.getDrawingBufferSize(uRes.value);
  if (window.__root) { const AB = armBones || (armBones = ['L_Upperarm','L_Forearm','L_Hand','R_Upperarm','R_Forearm','R_Hand'].map((n) => window.__root.getObjectByName('CC_Base_' + n))); AB.forEach((b, i) => b && b.getWorldPosition(uArmPts.value[i])); }   // vr2
  if (window.__cam) { const v = new THREE.Vector3(uRing.value.x, shellNeck.value, uRing.value.z).project(window.__cam); uNeckS.value = Math.min(1, Math.max(0.05, (v.y + 1) / 2)); }   // v12b
  { const A = animator && animator.api, lv = A ? (A.level || 0) : 0, wk = A ? (A.walkW || 0) : 0;   // v11: aether reacts to speaking and walking (smoothed)
    uFX.value.x += (lv - uFX.value.x) * Math.min(1, dt * 3); uFX.value.y += (wk - uFX.value.y) * Math.min(1, dt * 3);
    if (links.floorRing) uRing.value.set(links.floorRing.position.x, 0, links.floorRing.position.z); }
  if (links.floorRing) {   // v12d: ring drift stops while walking; after she settles, the pattern crossfades (never slides) to recentre on her
    const P = links.floorRing.position, wph = animator && animator.api ? animator.api.walkPhase : 0, still = !wph && uFX.value.y < 0.02;
    FLO.ph.value += dt * 0.35 * Math.max(0, 1 - uFX.value.y * 4) * (still ? 1 : 0);
    FLO.idle = still ? FLO.idle + dt : 0;
    if (FLO.k.value === 0 && FLO.idle > 0.8 && Math.hypot(FLO.o.value.x - P.x, FLO.o.value.y - P.z) > 0.001) FLO.o2.value.set(P.x, P.z), FLO.k.value = 1e-6;
    if (FLO.k.value > 0) { FLO.k.value = Math.min(1, FLO.k.value + dt / 1.5); if (FLO.k.value >= 1) { FLO.o.value.copy(FLO.o2.value); FLO.k.value = 0; } } }
  if (FREEZE !== null) uTime.value = uFlow.value = FREEZE;
  galaxy.rotation.z = uTime.value * 0.03;
  composer.render();
  ft.push(performance.now() - t0); if (ft.length > 120) ft.shift();
}
renderer.setAnimationLoop(() => { const dt = Math.min(clock.getDelta(), 0.1); if (window.__ready) frame(dt); });
