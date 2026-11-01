#define modelMatrix MODEL_MATRIX
#define viewMatrix VIEW_MATRIX
#define projectionMatrix PROJECTION_MATRIX
#define modelViewMatrix (VIEW_MATRIX * MODEL_MATRIX)
#define cameraPosition CAMERA_POSITION
#define texture2D texture
#define gl_Position POSITION
#define gl_Position POSITION
float seed;
vec3 position;

       
        
VARYING float vS;
 
VARYING float vTw;

      
VARYING vec2 vPc;

void MAIN() { seed = UV0.x; position = VERTEX; vS=seed;
        vec3 p = (modelMatrix*vec4(position,1.0)).xyz;
        float ph=fract(seed*7.13+uTime*0.06);
        p += normalize(vec3(sin(seed*40.0),0.7,cos(seed*31.0)))*ph*0.12;
        vTw = (0.45+0.55*sin(uTime*(1.2+seed*3.0)+seed*60.0)) * (1.0-ph*0.8);
        float big=step(0.9,seed);
        vec4 mv=viewMatrix*vec4(p,1.0); gl_Position=projectionMatrix*mv;
        float att=3.0/-mv.z;
        vPc = UV1 + 0.5; POSITION.xy += UV1 * ((0.9+1.1*seed)*uPx*att + big*uPx*max(2.0*att, 2.0)) * 2.0 / uVp * POSITION.w; vTw*=0.6+big*0.6; }