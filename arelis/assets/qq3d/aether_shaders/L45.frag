#define modelMatrix MODEL_MATRIX
#define viewMatrix VIEW_MATRIX
#define projectionMatrix PROJECTION_MATRIX
#define modelViewMatrix (VIEW_MATRIX * MODEL_MATRIX)
#define cameraPosition CAMERA_POSITION
#define texture2D texture
#define gl_FragColor FRAGCOLOR
#define gl_FragCoord FRAGCOORD
#define glTFTex(s, uv) texture(s, vec2((uv).x, 1.0 - (uv).y))

        
VARYING vec2 vP;
 
VARYING vec2 vW;

      float rg(vec2 o){ vec2 d=vW-o; d.y=-d.y; float r=length(d*vec2(1.0,1.15)); float x=r*9.0-uPh; float w=fwidth(x)*1.1;
        return smoothstep(w,0.0,abs(fract(x)-0.5))*(0.6+0.4*sin(atan(d.y,d.x)*3.0 + r*4.0 - uTime*0.3)); }
      
void aether_main(){ float r=length(vP*vec2(1.0,1.15));
        /* v12d: ring lines are world-locked (centred on uO, crossfading to uO2), only the light pool follows her, so planted feet never slide against them */
        float ring=mix(rg(uO),rg(uO2),uK); float wob=1.0;
        float fall=exp(-r*0.9)*smoothstep(0.08,0.35,r);
        float a=ring*fall*wob*0.35 + exp(-r*r*10.0)*0.12*(1.0-0.9*clamp(uFX.y,0.0,1.0));   /* v14: the light pool rides with her, so while she walks it fades (it read as the floor sliding under the planted feet) */
        gl_FragColor=vec4(mix(uA,uB,0.3)*a,1.0);}
void MAIN() { aether_main(); if (any(isnan(FRAGCOLOR)) || any(isinf(FRAGCOLOR))) discard; }
