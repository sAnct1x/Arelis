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
  // only where the neck fill above leaves her see-through: the head is already solid, and laying
  // the colour over it would only veil the eyes and brows drawn before this pass
  float nA = smoothstep(uNeckY - 0.03, uNeckY + 0.05, vWp.y) * (1.0 - smoothstep(0.055, 0.085, abs(vWp.x - uFace.x)) * (1.0 - smoothstep(uNeckY - 0.02, uNeckY + 0.06, vWp.y)));
  float a = uSkinOpacity * (1.0 - nA);
  if (a < 0.003) discard;
  FRAGCOLOR = vec4(uColor, a);
}
