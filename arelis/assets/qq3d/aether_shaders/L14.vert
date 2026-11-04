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
VARYING vec3 vN; VARYING vec3 vV; VARYING vec3 vW; VARYING vec3 vO; VARYING vec2 vUv2;
VARYING float vCav; VARYING float vCavF; VARYING float vHand; VARYING float vWr;
void MAIN() { vec3 MORPHED_VERTEX = VERTEX; for (int k = 0; k < 13; k++) MORPHED_VERTEX += MORPH_WEIGHTS[k] * (MORPH_POSITION(k) - VERTEX);
  vO = MORPHED_VERTEX; vUv2 = UV0; vCav = UV1.x; vCavF = UV1.y; vHand = TANGENT.x; vWr = TANGENT.y;
  mat4 S = BONE_TRANSFORMS[JOINTS.x] * WEIGHTS.x + BONE_TRANSFORMS[JOINTS.y] * WEIGHTS.y
         + BONE_TRANSFORMS[JOINTS.z] * WEIGHTS.z + BONE_TRANSFORMS[JOINTS.w] * WEIGHTS.w;
  vec4 w = S * vec4(MORPHED_VERTEX, 1.0);
  vec4 mv = VIEW_MATRIX * w;
  vN = normalize(mat3(VIEW_MATRIX) * (mat3(S) * NORMAL)); vV = normalize(-mv.xyz);
  vW = w.xyz;
  POSITION = PROJECTION_MATRIX * mv;
}
