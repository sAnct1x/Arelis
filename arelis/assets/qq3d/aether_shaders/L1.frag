#define modelMatrix MODEL_MATRIX
#define viewMatrix VIEW_MATRIX
#define projectionMatrix PROJECTION_MATRIX
#define modelViewMatrix (VIEW_MATRIX * MODEL_MATRIX)
#define cameraPosition CAMERA_POSITION
#define texture2D texture
#define gl_FragColor FRAGCOLOR
#define gl_FragCoord FRAGCOORD
#define glTFTex(s, uv) texture(s, vec2((uv).x, 1.0 - (uv).y))
VARYING vec2 vUv; VARYING vec3 vWp;
void MAIN() {
  float nA = smoothstep(uNeckY - 0.03, uNeckY + 0.05, vWp.y) * (1.0 - smoothstep(0.055, 0.085, abs(vWp.x - uFace.x)) * (1.0 - smoothstep(uNeckY - 0.02, uNeckY + 0.06, vWp.y)));
  if (nA < 0.03) discard;
  FRAGCOLOR = vec4(uColor * nA, 1.0);
}
