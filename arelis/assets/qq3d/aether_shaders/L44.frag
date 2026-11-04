#define modelMatrix MODEL_MATRIX
#define viewMatrix VIEW_MATRIX
#define projectionMatrix PROJECTION_MATRIX
#define modelViewMatrix (VIEW_MATRIX * MODEL_MATRIX)
#define cameraPosition CAMERA_POSITION
#define texture2D texture
#define gl_FragColor FRAGCOLOR
#define gl_FragCoord FRAGCOORD
#define glTFTex(s, uv) texture(s, vec2((uv).x, 1.0 - (uv).y))


    
  
VARYING vec2 vUv;
 
VARYING float vSeed;
 
VARYING float vBright;
 
VARYING float vKind;

  void main_rv(){
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
