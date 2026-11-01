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
vec4 sIdx;
vec4 sW;
vec4 fx;
vec3 position;

  vec3 hash3(vec3 p){ p=vec3(dot(p,vec3(127.1,311.7,74.7)),dot(p,vec3(269.5,183.3,246.1)),dot(p,vec3(113.5,271.9,124.6)));
    return -1.0+2.0*fract(sin(p)*43758.5453123); }
  float noise(vec3 p){ vec3 i=floor(p), f=fract(p); vec3 u=f*f*(3.0-2.0*f);
    return mix(mix(mix(dot(hash3(i),f),dot(hash3(i+vec3(1,0,0)),f-vec3(1,0,0)),u.x),
                   mix(dot(hash3(i+vec3(0,1,0)),f-vec3(0,1,0)),dot(hash3(i+vec3(1,1,0)),f-vec3(1,1,0)),u.x),u.y),
               mix(mix(dot(hash3(i+vec3(0,0,1)),f-vec3(0,0,1)),dot(hash3(i+vec3(1,0,1)),f-vec3(1,0,1)),u.x),
                   mix(dot(hash3(i+vec3(0,1,1)),f-vec3(0,1,1)),dot(hash3(i+vec3(1,1,1)),f-vec3(1,1,1)),u.x),u.y),u.z); }
  vec3 pot(vec3 p){ return vec3(noise(p), noise(p+vec3(31.4,7.1,2.9)), noise(p+vec3(-9.3,17.7,41.1))); }
  vec3 curl(vec3 p){ const float e=0.12; vec3 dx=vec3(e,0,0), dy=vec3(0,e,0), dz=vec3(0,0,e);
    vec3 a=pot(p+dy)-pot(p-dy), b=pot(p+dz)-pot(p-dz), c=pot(p+dx)-pot(p-dx);
    return vec3(a.z-b.y, b.x-c.z, c.y-a.x)/(2.0*e); }
     
  
  
             
VARYING float vA;
 
VARYING float vC;

        
    
VARYING vec2 vPc;

void MAIN() { sIdx = vec4(JOINTS); sW = WEIGHTS; fx = COLOR; position = VERTEX; vec3 b=skinPoint(position,sIdx,sW), bn=skinPoint(position+fx.xyz*0.03,sIdx,sW); vec3 n=normalize(bn-b);
      float br=0.5+0.5*sin(uTime*1.25 + fx.w*0.6);   // ~5 s breath
      vec3 p=b + n*(0.012+0.008*br);   /* v13: no per-point radial jitter */
      vec3 vd=normalize(cameraPosition-p); float rim=pow(1.0-abs(dot(n,vd)),3.0);
      float band=0.35+0.65*pow(0.5+0.5*sin(p.y*5.0 - uTime*0.55 + 1.7*sin(uTime*0.13)),3.0);
      vA=rim*band*(0.6+0.45*br+0.5*uFX.x)*uGain*smoothstep(0.55,0.95,uApp) * (1.0 - smoothstep(uNeck - 0.06, uNeck + 0.02, p.y));
      vC=0.8+0.5*band;
      vec4 mv=viewMatrix*vec4(p,1.0); gl_Position=projectionMatrix*mv; vPc = UV1 + 0.5; POSITION.xy += UV1 * ((2.2+1.2*fx.w)*uPx*(3.0/-mv.z)) * 2.0 / uVp * POSITION.w;  POSITION.z = mix(NEAR_CLIP_VALUE, 1.0, 1e-3) * POSITION.w; }