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
    vec3 obsidian = uHull.rgb * mix(0.28, 0.46, rib);
    vec3 irid = mix(obsidian, uRole.rgb * 0.26 + oilTint * 0.12, fres * 0.68);
    float bioPulse = 0.84 + 0.16 * sin(uTime * 3.4 + dot(VAR_WORLD_POSITION, vec3(1.4, 2.1, 1.4)));
    BASE_COLOR = vec4(irid, uHull.a);
    METALNESS = mix(0.88, 0.96, 1.0 - rib);
    ROUGHNESS = mix(0.09, 0.21, rib);
    CLEARCOAT_AMOUNT = 0.92;
    CLEARCOAT_ROUGHNESS = 0.035;
    EMISSIVE_COLOR = (uRole.rgb * (fres * 1.15 + razor * 0.85) + oilTint * razor * 0.22) * uRimK * bioPulse;
}
