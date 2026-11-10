VARYING vec3 vEye;

void MAIN() {
    // HDR emission just over the glow threshold: the core keeps its caste
    // hue and the bloom halo carries it outward.
    float scan = 0.94 + 0.06 * sin(uTime * 6.2) * cos(uTime * 2.3);
    vec3 hotCluster = mix(vEye, vec3(1.0), 0.12);
    FRAGCOLOR = vec4(hotCluster * (uStrength * scan), 1.0);
}
