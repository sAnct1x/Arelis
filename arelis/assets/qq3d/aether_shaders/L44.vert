#define modelMatrix MODEL_MATRIX
#define viewMatrix VIEW_MATRIX
#define projectionMatrix PROJECTION_MATRIX
#define modelViewMatrix (VIEW_MATRIX * MODEL_MATRIX)
#define cameraPosition CAMERA_POSITION
#define texture2D texture
#define gl_Position POSITION
// aether.js skinPoint: bindM and the bone inverse live in the Skin's inverse bind poses, so the
// bone transform maps the bind-space point straight to world space (uModel * bindMInv is identity).
vec3 skinPoint(vec3 p, vec4 si, vec4 sw) { vec4 b = vec4(p, 1.0);
  vec4 s = BONE_TRANSFORMS[int(si.x)] * b * sw.x + BONE_TRANSFORMS[int(si.y)] * b * sw.y
         + BONE_TRANSFORMS[int(si.z)] * b * sw.z + BONE_TRANSFORMS[int(si.w)] * b * sw.w;
  return s.xyz; }
float u;
float side;
vec4 sIdx;
vec4 sW;
vec4 prm;
vec2 kind;
vec3 position;
vec3 uArmAt(int k) { if (k == 0) return uArm0; if (k == 1) return uArm1; if (k == 2) return uArm2; if (k == 3) return uArm3; if (k == 4) return uArm4; if (k == 5) return uArm5; return uArm0; }

  
     
  
  
     
      // x seed, y spread, z width, w brightness
     // x kind, y base angle
         
  
VARYING vec2 vUv;
 
VARYING float vSeed;
 
VARYING float vBright;
 
VARYING float vKind;

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
  
void MAIN() { u = UV0.x; side = UV0.y; sIdx = vec4(JOINTS); sW = WEIGHTS; prm = COLOR; kind = UV1; position = VERTEX;
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
      for (int j=0;j<2;j++) for (int i=0;i<3;i++) { vec3 PA = uArmAt(j*3+min(i,2)), PB = i<2 ? uArmAt(j*3+i+1) : uArmAt(j*3+2) + (uArmAt(j*3+2)-uArmAt(j*3+1))*0.4; vec4 A = projectionMatrix*viewMatrix*vec4(PA,1.0), B = projectionMatrix*viewMatrix*vec4(PB,1.0);   /* i=2: the hand, ~40% of a forearm past the wrist */
        vec2 a2 = A.xy/A.w*vec2(aspect,1.0), b2 = B.xy/B.w*vec2(aspect,1.0), ab = b2-a2; float h = clamp(dot(q-a2,ab)/max(dot(ab,ab),1e-6),0.0,1.0); dm = min(dm, length(q-a2-ab*h)); }
      vBright *= mix(0.12, 1.0, smoothstep(0.035, 0.09, dm));
    }
  }