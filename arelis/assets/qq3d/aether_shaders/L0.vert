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
VARYING vec3 vC;
VARYING vec2 vPc;

void MAIN() { vC = COLOR.rgb; vec4 mv = VIEW_MATRIX * MODEL_MATRIX * vec4(VERTEX, 1.0);
  POSITION = PROJECTION_MATRIX * mv; vPc = UV1 + 0.5; POSITION.xy += UV1 * (uSize * (uScale / -mv.z)) * 2.0 / uVp * POSITION.w; }
