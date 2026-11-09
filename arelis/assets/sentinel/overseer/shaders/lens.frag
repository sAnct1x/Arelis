void MAIN() {
    float scan = 0.92 + 0.26 * sin(uTime * 6.2) * cos(uTime * 2.3);
    vec3 ocular = mix(uRole.rgb, vec3(1.0, 0.16, 0.30), 0.38);
    vec3 hotCluster = mix(ocular, vec3(1.0, 0.88, 0.92), 0.34 * scan);
    FRAGCOLOR = vec4(hotCluster * (uStrength * 1.38 * scan), 1.0);
}
