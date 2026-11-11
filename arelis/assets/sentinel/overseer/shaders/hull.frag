void MAIN() {
    vec3 n = normalize(VAR_WORLD_NORMAL);
    vec3 v = normalize(VIEW_VECTOR);
    float ndotv = clamp(dot(n, v), 0.0, 1.0);
    float fres = pow(1.0 - ndotv, 2.4);
    float razor = pow(1.0 - ndotv, 5.5);
    float rib = 0.5 + 0.5 * sin(dot(VAR_WORLD_POSITION, vec3(14.0, 9.0, 14.0)));
    float oilPhase = (1.0 - ndotv) * 6.28318 + uTime * 0.65;
    vec3 oilTint = vec3(
        0.5 + 0.5 * sin(oilPhase),
        0.5 + 0.5 * sin(oilPhase + 2.094),
        0.5 + 0.5 * sin(oilPhase + 4.188)
    );
    // Hull #40345f, lit as a dielectric. The old near-mirror metal had no
    // environment to reflect, so it rendered almost black.
    vec3 hull = uHull.rgb * mix(0.8, 1.0, rib);
    vec3 irid = mix(hull, uRole.rgb * 0.3 + oilTint * 0.08, fres * 0.45);
    float bioPulse = 0.9 + 0.1 * sin(uTime * 3.4 + dot(VAR_WORLD_POSITION, vec3(1.4, 2.1, 1.4)));
    BASE_COLOR = vec4(irid, 1.0);
    METALNESS = 0.15;
    ROUGHNESS = mix(0.38, 0.55, rib);
    CLEARCOAT_AMOUNT = 0.92;
    CLEARCOAT_ROUGHNESS = 0.3;
    // Caste fresnel rim (uRimK 0.85) plus a little hull self-light so the
    // shadow side is never flat black. Capped under the glow threshold.
    float rim = min(1.0, fres * 1.15 + razor * 0.85);
    EMISSIVE_COLOR = uRole.rgb * (rim * uRimK * bioPulse) + uHull.rgb * 0.35;
}
