// Pass E tentacle fragment, Unshaded LOD2 ribbon (fake cylinder, one pass).
VARYING vec3 vN;
VARYING vec3 vW;
VARYING vec4 vC;
VARYING vec3 vCaste;
VARYING float vSide;
void MAIN()
{
    vec3 V = normalize(CAMERA_POSITION - vW);
    vec3 alb = mix(baseMetal, clawMetal, vC.y);
    float x = clamp(vSide, -1.0, 1.0);
    float c = sqrt(1.0 - 0.81 * x * x);
    vec3 side = normalize(cross(V, cross(normalize(vN), V)) + 1e-5);
    vec3 n = normalize(V * c + side * 0.9 * x);
    vec3 col = vec3(0.0);
    col += alb * max(dot(n, keyDir), 0.0) * 1.0 * ribbonLight + 0.12 * pow(max(dot(n, normalize(keyDir + V)), 0.0), 24.0) * ribbonLight;
    col += alb * max(dot(n, fillDir), 0.0) * 0.35 * ribbonLight;
    float rim = (1.0 - c) / 0.564 * rimGain * 0.32;
    float slit = vC.x * vC.x * vC.x * slitGain * (1.0 - vC.y);
    FRAGCOLOR = vec4(col + vCaste * (rim + slit) * vC.w, 1.0);
}
