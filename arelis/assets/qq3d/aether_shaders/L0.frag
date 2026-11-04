#define modelMatrix MODEL_MATRIX
#define viewMatrix VIEW_MATRIX
#define projectionMatrix PROJECTION_MATRIX
#define modelViewMatrix (VIEW_MATRIX * MODEL_MATRIX)
#define cameraPosition CAMERA_POSITION
#define texture2D texture
#define gl_FragColor FRAGCOLOR
#define gl_FragCoord FRAGCOORD
#define glTFTex(s, uv) texture(s, vec2((uv).x, 1.0 - (uv).y))
VARYING vec3 vC;
VARYING vec2 vPc;

void MAIN() { float dq = length(vPc - 0.5); if (dq > 0.5) discard;
  FRAGCOLOR = vec4(vC * smoothstep(0.5, 0.0, dq), 1.0); }
