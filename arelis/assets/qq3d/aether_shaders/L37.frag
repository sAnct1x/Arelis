#define modelMatrix MODEL_MATRIX
#define viewMatrix VIEW_MATRIX
#define projectionMatrix PROJECTION_MATRIX
#define modelViewMatrix (VIEW_MATRIX * MODEL_MATRIX)
#define cameraPosition CAMERA_POSITION
#define texture2D texture
#define gl_FragColor FRAGCOLOR
#define gl_FragCoord FRAGCOORD
#define glTFTex(s, uv) texture(s, vec2((uv).x, 1.0 - (uv).y))


    
VARYING float vS;
 
VARYING float vTw;

  void main_rv(){ vec2 q=vPc-0.5; float d=length(q); if(d>0.5) discard;
    float core=smoothstep(0.5,0.25,d); float halo=0.0;
    float big=step(0.9,vS);
    float spike=0.0;
    // big stars: gaussian-like falloff and lower peak, so bloom spreads a round glow instead of a square sprite edge
    float soft=exp(-d*d*28.0);
    core=mix(core, soft, big);
    float a=core*vTw*mix(1.0, 0.55, big);
    gl_FragColor=vec4(mix(uA,vec3(0.88,0.82,1.0),clamp(core*0.7+big*0.2,0.0,1.0))*a*1.6,a); }
    
  float rvH(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float rvN(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
    return mix(mix(rvH(i), rvH(i+vec2(1,0)), f.x), mix(rvH(i+vec2(0,1)), rvH(i+vec2(1,1)), f.x), f.y); }
  float revealT(){ vec2 q=gl_FragCoord.xy/uRes; float n=0.6*rvN(gl_FragCoord.xy/14.0)+0.4*rvN(gl_FragCoord.xy/4.0);
    float yy=min(q.y, uNeckS)/max(uNeckS,0.05); float hd=smoothstep(uNeckS-0.01, uNeckS+0.03, q.y); n=mix(n, 0.5+0.17*uRvDir+0.25*(rvN(gl_FragCoord.xy/40.0)-0.5), hd);   /* v12f: the head follows the neck and shoulders in both directions (arrives after them, leaves after them) */ return clamp(yy*0.3+0.7*n,0.0,1.0); }   /* v12e: the head fades as one soft piece at the shoulders' mean pace (no blotches) */   /* head shares the shoulders' threshold */
  float rvHead(){ float lo=uRvDir>0.0?0.50:0.48, hi=uRvDir>0.0?1.0:0.96;   /* vr3: dissolve head left after the body (floating head at f65-75); window raised from 0.30-0.84 */ float x=clamp((uAppL-lo)/(hi-lo),0.0,1.0); return x*x*(3.0-2.0*x); }   /* vr2: the whole head/hair fades as one piece on its own ~1.2-1.5 s smootherstep window of the appear clock (was a 0.5 R sweep: 17->77 luminance in ~20 frames, read as a pop); arrives after the shoulders, leaves after them */
  float revealM(){ float R=uAppL*2.8-0.9; float t=revealT(); float hd=smoothstep(uNeckS-0.01, uNeckS+0.03, gl_FragCoord.y/uRes.y); return mix(smoothstep(t, t+0.9, R), rvHead(), hd); }   /* vr2: body front 0.9 R wide (was 0.4) = ~0.8-1.2 s per pixel at the 3.6 s pace */
  float revealD(){ float R=uAppL*2.8-0.9; float t=revealT(); float hd=smoothstep(uNeckS-0.01, uNeckS+0.03, gl_FragCoord.y/uRes.y); return mix(smoothstep(t-0.3, t+0.35, R), rvHead(), hd); }   /* vr2: solid layers dither in over most of the glow ramp (and on the head the same curve as its glow), so the solid surface itself fades rather than appearing behind the glow */

void aether_main(){ float m_rv=revealM();  m_rv *= mix(1.0, sqrt(m_rv), smoothstep(uNeckS-0.06, uNeckS+0.06, gl_FragCoord.y/uRes.y)); if (m_rv < 0.01) discard; main_rv(); gl_FragColor *= m_rv; }

VARYING vec2 vPc;

void MAIN() { aether_main(); if (any(isnan(FRAGCOLOR)) || any(isinf(FRAGCOLOR))) discard; }
