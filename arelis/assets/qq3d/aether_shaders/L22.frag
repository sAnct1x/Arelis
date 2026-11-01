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
void MAIN() { FRAGCOLOR = vec4(uColor, 1.0); }
