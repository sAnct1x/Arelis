// Pass E tentacle fragment, Shaded (LOD0/1). Gunmetal metal, caste slit/rim emission.
VARYING vec3 vN;
VARYING vec3 vW;
VARYING vec4 vC;       // slit, claw, rim k, dim
VARYING vec3 vCaste;
VARYING float vSide;
void MAIN()
{
    vec3 V = normalize(CAMERA_POSITION - vW);
    vec3 alb = mix(baseMetal, clawMetal, vC.y);
    BASE_COLOR = vec4(alb, 1.0);
    METALNESS = 0.75;
    ROUGHNESS = 0.40;
    float facing = 1.0 - abs(dot(normalize(vN), V));
    EMISSIVE_COLOR = vCaste * (pow(facing, 3.0) * rimGain + vC.x * slitGain * (1.0 - vC.y)) * vC.w;
}
