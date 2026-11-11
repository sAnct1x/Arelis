// Pass E tentacle fragment v2 (fix-c05bb78), LOD0/1, UNSHADED with unitLight(). Gunmetal links, caste slit, caste rim.
VARYING vec3 vN;
VARYING vec3 vW;
VARYING vec4 vC;       // slit, claw, rim k, dim
VARYING vec3 vCaste;
VARYING float vSide;

// Unit lighting (fix-c05bb78): the two scene directional lights (key 1.0, fill 0.35, OverseerView.qml DirectionalLights)
// + sky/ground ambient + Blinn-Phong spec with Schlick fresnel + neutral edge light. Unshaded, so the scene fog is
// replaced by unitFog x the scene fog ramp (depth 40..110 m, density 0.6, colour #120a1d).
vec3 unitLight(vec3 alb, vec3 N, vec3 V, float metal, float rough, float cav) {
    vec3 F0 = mix(vec3(0.04), alb * 2.2 + vec3(0.06), metal);
    float shin = mix(180.0, 10.0, rough);
    vec3 col = alb * mix(ambGround, ambSky, 0.5 + 0.5 * N.y) * cav;
    vec3 Ls[2]; Ls[0] = normalize(keyDir); Ls[1] = normalize(fillDir);
    float Is[2]; Is[0] = keyGain; Is[1] = fillGain;
    for (int i = 0; i < 2; i++) {
        float nl = max(dot(N, Ls[i]), 0.0);
        vec3 H = normalize(Ls[i] + V);
        float nh = max(dot(N, H), 0.0);
        vec3 F = F0 + (1.0 - F0) * pow(1.0 - max(dot(H, V), 0.0), 5.0);
        col += Is[i] * (alb * (1.0 - metal) * nl + F * pow(nh, shin) * (shin + 8.0) / 25.13 * nl * specGain);
    }
    float facing = 1.0 - abs(dot(N, V));
    col += (alb + vec3(0.03)) * pow(facing, 4.0) * edgeGain;
    return col;
}
vec3 unitFogMix(vec3 col, vec3 W) {
    float d = length(CAMERA_POSITION - W);
    float f = unitFog * 0.6 * clamp((d - 40.0) / 70.0, 0.0, 1.0);
    return mix(col, vec3(0.0060, 0.0030, 0.0123), f);
}

void MAIN()
{
    vec3 V = normalize(CAMERA_POSITION - vW);
    vec3 N = normalize(vN);
    if (dot(N, V) < 0.0) N = -N;
    vec3 alb = mix(baseMetal, clawMetal, vC.y);
    float facing = 1.0 - abs(dot(N, V));
    vec3 col = unitLight(alb, N, V, tentMetal, tentRough, 1.0);
    vec3 em = vCaste * (pow(facing, 3.0) * rimGain + vC.x * vC.x * vC.x * slitGain * (1.0 - vC.y));
    FRAGCOLOR = vec4((unitFogMix(col, vW) + em) * vC.w, 1.0);
}
