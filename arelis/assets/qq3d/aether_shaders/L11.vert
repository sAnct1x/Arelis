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
VARYING vec2 vUv; VARYING vec3 vWp;
void MAIN() { vec3 MORPHED_VERTEX = VERTEX; for (int k = 0; k < 20; k++) MORPHED_VERTEX += MORPH_WEIGHTS[k] * (MORPH_POSITION(k) - VERTEX);
  mat4 S = BONE_TRANSFORMS[JOINTS.x] * WEIGHTS.x + BONE_TRANSFORMS[JOINTS.y] * WEIGHTS.y
         + BONE_TRANSFORMS[JOINTS.z] * WEIGHTS.z + BONE_TRANSFORMS[JOINTS.w] * WEIGHTS.w;
  // vWp feeds the neck cut (FILL_FRAG neck/skin), so it is the bind-pose point, not the posed one:
  // a world-space cut stays put while her head moves, and looking down took the chin and lower
  // face under uNeckY, so that fill was discarded and her eyes, teeth and hair showed through
  vec4 w = S * vec4(MORPHED_VERTEX, 1.0); vUv = UV0; vWp = MORPHED_VERTEX;
  w.xyz += normalize(w.xyz - CAMERA_POSITION) * uPush;   // occluders sit behind the shells
  // same expression as SHELL_VERT: the shells draw over these fills at the same depth (three's
  // LessEqual), and VIEWPROJECTION * w rounds differently, so the shells z-fought them in specks
  vec4 mv = VIEW_MATRIX * w;
  POSITION = PROJECTION_MATRIX * mv;
}
