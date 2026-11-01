#define modelMatrix MODEL_MATRIX
#define viewMatrix VIEW_MATRIX
#define projectionMatrix PROJECTION_MATRIX
#define modelViewMatrix (VIEW_MATRIX * MODEL_MATRIX)
#define cameraPosition CAMERA_POSITION
#define texture2D texture
#define gl_Position POSITION
#define gl_Position POSITION
vec3 position;

VARYING vec2 vP;
 
VARYING vec2 vW;
 
void MAIN() { position = VERTEX; vP=position.xy; vW=(modelMatrix*vec4(position,1.0)).xz; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}