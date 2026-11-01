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
float seed;
vec4 sIdx;
vec4 sW;
vec3 position;

     
  
  
        
        
VARYING float vS;
 
VARYING float vTw;

      
VARYING vec2 vPc;

void MAIN() { seed = UV0.x; sIdx = vec4(JOINTS); sW = WEIGHTS; position = VERTEX; vS=seed;
        vec3 p = skinPoint(position, sIdx, sW);
        float ph=fract(seed*7.13+uTime*0.06);
        p += normalize(vec3(sin(seed*40.0),0.7,cos(seed*31.0)))*ph*0.03;
        vTw = (0.45+0.55*sin(uTime*(1.2+seed*3.0)+seed*60.0)) * (1.0-ph*0.8);
        float big=step(0.9,seed);
        vec4 mv=viewMatrix*vec4(p,1.0); gl_Position=projectionMatrix*mv;
        float att=3.0/-mv.z;
        vPc = UV1 + 0.5; POSITION.xy += UV1 * ((0.9+1.1*seed)*uPx*att + big*uPx*max(2.4*att, 2.0)) * 2.0 / uVp * POSITION.w; vTw*=0.6+big*0.6;  POSITION.z = mix(NEAR_CLIP_VALUE, 1.0, 1e-3) * POSITION.w; }