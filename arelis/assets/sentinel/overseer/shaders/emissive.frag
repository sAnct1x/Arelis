void MAIN() {
    float surge = 0.88 + 0.24 * sin(uTime * 4.4);
    vec3 hotCore = mix(uRole.rgb, vec3(1.0, 0.9, 0.96), 0.28 * surge);
    FRAGCOLOR = vec4(hotCore * (uStrength * surge), 1.0);
}
