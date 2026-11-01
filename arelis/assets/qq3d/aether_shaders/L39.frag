#define modelMatrix MODEL_MATRIX
#define viewMatrix VIEW_MATRIX
#define projectionMatrix PROJECTION_MATRIX
#define modelViewMatrix (VIEW_MATRIX * MODEL_MATRIX)
#define cameraPosition CAMERA_POSITION
#define texture2D texture
#define gl_FragColor FRAGCOLOR
#define gl_FragCoord FRAGCOORD
#define glTFTex(s, uv) texture(s, vec2((uv).x, 1.0 - (uv).y))


     
VARYING float vA;
 
VARYING float vC;

  
void aether_main(){ vec2 e=min(gl_FragCoord.xy, uRes-gl_FragCoord.xy); float edge=smoothstep(0.0, 0.09*uRes.y, min(e.x,e.y));   // v11b: fade near the frame edge (no bright border pixels)
    vec2 q=vPc-0.5; float d=length(q); if(d>0.5) discard;
    float s=exp(-d*d*18.0); float a=min(s*vA,1.0)*edge;
    gl_FragColor=vec4(mix(mix(uA,uB,clamp(vC,0.0,1.0)),vec3(0.86,0.8,1.0),clamp(vC-1.0,0.0,1.0))*a*1.5,a); }
VARYING vec2 vPc;

void MAIN() { aether_main(); if (any(isnan(FRAGCOLOR)) || any(isinf(FRAGCOLOR))) discard; }
