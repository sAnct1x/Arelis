#define modelMatrix MODEL_MATRIX
#define viewMatrix VIEW_MATRIX
#define projectionMatrix PROJECTION_MATRIX
#define modelViewMatrix (VIEW_MATRIX * MODEL_MATRIX)
#define cameraPosition CAMERA_POSITION
#define texture2D texture
#define gl_FragColor FRAGCOLOR
#define gl_FragCoord FRAGCOORD
#define glTFTex(s, uv) texture(s, vec2((uv).x, 1.0 - (uv).y))


  
            
          
VARYING vec2 vUv2;

  
VARYING vec3 vN;
 
VARYING vec3 vV;
 
VARYING vec3 vW;
 
VARYING vec3 vO;
 
VARYING float vCav;
 
VARYING float vCavF;
 
VARYING float vHand;
 
VARYING float vWr;

  
  vec3 hash3(vec3 p){ p=vec3(dot(p,vec3(127.1,311.7,74.7)),dot(p,vec3(269.5,183.3,246.1)),dot(p,vec3(113.5,271.9,124.6)));
    return -1.0+2.0*fract(sin(p)*43758.5453123); }
  float noise(vec3 p){ vec3 i=floor(p), f=fract(p); vec3 u=f*f*(3.0-2.0*f);
    return mix(mix(mix(dot(hash3(i),f),dot(hash3(i+vec3(1,0,0)),f-vec3(1,0,0)),u.x),
                   mix(dot(hash3(i+vec3(0,1,0)),f-vec3(0,1,0)),dot(hash3(i+vec3(1,1,0)),f-vec3(1,1,0)),u.x),u.y),
               mix(mix(dot(hash3(i+vec3(0,0,1)),f-vec3(0,0,1)),dot(hash3(i+vec3(1,0,1)),f-vec3(1,0,1)),u.x),
                   mix(dot(hash3(i+vec3(0,1,1)),f-vec3(0,1,1)),dot(hash3(i+vec3(1,1,1)),f-vec3(1,1,1)),u.x),u.y),u.z); }
  float thread(float x){ float d=abs(fract(x)-0.5); float w=fwidth(x)*0.7; return smoothstep(w,0.0,d); }
  void main_rv(){
    float ndv = abs(dot(normalize(vN), normalize(vV)));
    float rim = pow(1.0 - ndv, 2.4); rim *= uRimGain;
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
    float glow = uGlow*mix(0.65 + 0.35*patchy, 1.25, calm)*(0.6 + 0.4*(1.0-ndv)); glow *= mix(1.0, uHeadGlow, smoothstep(uNeckY - 0.02, uNeckY + 0.06, vW.y));
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
      float ca = glTFTex(uAlphaMap, vUv2).a; if (ca < 0.1) discard;
      col = mix(uB, vec3(0.92,0.86,1.0), 0.3) * ca * 1.1; a = ca * 0.8;
    } else if (uHair > 0.5) {   // hair cards: alpha from the card texture, soft glow instead of hard rim/threads
      float ca = glTFTex(uAlphaMap, vUv2).a; if (ca < 0.08) discard;
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
  }
    
  float rvH(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float rvN(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
    return mix(mix(rvH(i), rvH(i+vec2(1,0)), f.x), mix(rvH(i+vec2(0,1)), rvH(i+vec2(1,1)), f.x), f.y); }
  float revealT(){ vec2 q=gl_FragCoord.xy/uRes; float n=0.6*rvN(gl_FragCoord.xy/14.0)+0.4*rvN(gl_FragCoord.xy/4.0);
    float yy=min(q.y, uNeckS)/max(uNeckS,0.05); float hd=smoothstep(uNeckS-0.01, uNeckS+0.03, q.y); n=mix(n, 0.5+0.17*uRvDir+0.25*(rvN(gl_FragCoord.xy/40.0)-0.5), hd);   /* v12f: the head follows the neck and shoulders in both directions (arrives after them, leaves after them) */ return clamp(yy*0.3+0.7*n,0.0,1.0); }   /* v12e: the head fades as one soft piece at the shoulders' mean pace (no blotches) */   /* head shares the shoulders' threshold */
  float rvHead(){ float lo=uRvDir>0.0?0.50:0.48, hi=uRvDir>0.0?1.0:0.96;   /* vr3: dissolve head left after the body (floating head at f65-75); window raised from 0.30-0.84 */ float x=clamp((uAppL-lo)/(hi-lo),0.0,1.0); return x*x*(3.0-2.0*x); }   /* vr2: the whole head/hair fades as one piece on its own ~1.2-1.5 s smootherstep window of the appear clock (was a 0.5 R sweep: 17->77 luminance in ~20 frames, read as a pop); arrives after the shoulders, leaves after them */
  float revealM(){ float R=uAppL*2.8-0.9; float t=revealT(); float hd=smoothstep(uNeckS-0.01, uNeckS+0.03, gl_FragCoord.y/uRes.y); return mix(smoothstep(t, t+0.9, R), rvHead(), hd); }   /* vr2: body front 0.9 R wide (was 0.4) = ~0.8-1.2 s per pixel at the 3.6 s pace */
  float revealD(){ float R=uAppL*2.8-0.9; float t=revealT(); float hd=smoothstep(uNeckS-0.01, uNeckS+0.03, gl_FragCoord.y/uRes.y); return mix(smoothstep(t-0.3, t+0.35, R), rvHead(), hd); }   /* vr2: solid layers dither in over most of the glow ramp (and on the head the same curve as its glow), so the solid surface itself fades rather than appearing behind the glow */

void aether_main(){ float m_rv=revealM();  m_rv *= mix(1.0, sqrt(m_rv), smoothstep(uNeckS-0.06, uNeckS+0.06, gl_FragCoord.y/uRes.y)); if (m_rv < 0.01) discard; main_rv(); gl_FragColor *= m_rv; }

void MAIN() { aether_main(); if (any(isnan(FRAGCOLOR)) || any(isinf(FRAGCOLOR))) discard; }
