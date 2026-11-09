void MAIN() {
    vec3 n = normalize(VAR_WORLD_NORMAL);
    vec3 v = normalize(VIEW_VECTOR);
    float fres = pow(1.0 - clamp(dot(n, v), 0.0, 1.0), 2.2);
    BASE_COLOR = uHull;
    METALNESS = 0.75;
    ROUGHNESS = 0.25;
    CLEARCOAT_AMOUNT = 0.6;
    CLEARCOAT_ROUGHNESS = 0.08;
    EMISSIVE_COLOR = uRole.rgb * fres * uRimK;
}
