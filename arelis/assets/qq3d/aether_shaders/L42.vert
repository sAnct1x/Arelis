#define modelMatrix MODEL_MATRIX
#define viewMatrix VIEW_MATRIX
#define projectionMatrix PROJECTION_MATRIX
#define modelViewMatrix (VIEW_MATRIX * MODEL_MATRIX)
#define cameraPosition CAMERA_POSITION
#define texture2D texture
#define gl_Position POSITION
#define gl_Position POSITION
vec4 fx;
vec3 position;

  vec3 hash3(vec3 p){ p=vec3(dot(p,vec3(127.1,311.7,74.7)),dot(p,vec3(269.5,183.3,246.1)),dot(p,vec3(113.5,271.9,124.6)));
    return -1.0+2.0*fract(sin(p)*43758.5453123); }
  float noise(vec3 p){ vec3 i=floor(p), f=fract(p); vec3 u=f*f*(3.0-2.0*f);
    return mix(mix(mix(dot(hash3(i),f),dot(hash3(i+vec3(1,0,0)),f-vec3(1,0,0)),u.x),
                   mix(dot(hash3(i+vec3(0,1,0)),f-vec3(0,1,0)),dot(hash3(i+vec3(1,1,0)),f-vec3(1,1,0)),u.x),u.y),
               mix(mix(dot(hash3(i+vec3(0,0,1)),f-vec3(0,0,1)),dot(hash3(i+vec3(1,0,1)),f-vec3(1,0,1)),u.x),
                   mix(dot(hash3(i+vec3(0,1,1)),f-vec3(0,1,1)),dot(hash3(i+vec3(1,1,1)),f-vec3(1,1,1)),u.x),u.y),u.z); }
  vec3 pot(vec3 p){ return vec3(noise(p), noise(p+vec3(31.4,7.1,2.9)), noise(p+vec3(-9.3,17.7,41.1))); }
  vec3 curl(vec3 p){ const float e=0.12; vec3 dx=vec3(e,0,0), dy=vec3(0,e,0), dz=vec3(0,0,e);
    vec3 a=pot(p+dy)-pot(p-dy), b=pot(p+dz)-pot(p-dz), c=pot(p+dx)-pot(p-dx);
    return vec3(a.z-b.y, b.x-c.z, c.y-a.x)/(2.0*e); }
             
VARYING float vA;
 
VARYING float vC;

      
    
VARYING vec2 vPc;

void MAIN() { fx = COLOR; position = VERTEX; float L=9.5+6.5*fx.y, ph=fract(fx.x+uTime/L);   /* vr3: slower rise (was 7+5) */
      float a=position.x + ph*(0.8+0.6*fx.z)*(fx.w<0.5?1.0:-1.0), r=position.y*(1.0+0.35*ph);
      vec3 p=vec3(uRing.x+cos(a)*r, position.z + ph*1.385*(0.45+0.55*fx.z), uRing.z+sin(a)*r*0.85);
      p += curl(p*1.2+vec3(0.0,-uTime*0.06,fx.w*7.0))*0.06*ph;
      p.z -= uFX.y*0.8*ph;
      float col=smoothstep(0.22,0.4,length(p.xz-uRing.xz));   // keep clear of her body column
      vA=pow(sin(3.14159*ph),1.5)*(1.2+1.2*fx.w)*mix(1.0,col,smoothstep(1.015,1.477,p.y))*(1.0-smoothstep(1.145,1.569,p.y))*(0.9+0.3*uFX.x)*uGain*smoothstep(0.3,0.9,uApp);
      vC=0.3+0.9*fx.z;
      vec4 mv=viewMatrix*vec4(p,1.0); gl_Position=projectionMatrix*mv; vPc = UV1 + 0.5; POSITION.xy += UV1 * ((3.4+4.2*fx.w)*uPx*(3.0/-mv.z)) * 2.0 / uVp * POSITION.w;  POSITION.z = mix(NEAR_CLIP_VALUE, 1.0, 1e-3) * POSITION.w; }