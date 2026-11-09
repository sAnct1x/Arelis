void MAIN() {
    vec3 deformed = VERTEX;
    float tail = 1.0 - smoothstep(-0.55, 0.15, deformed.x);
    float phase = INSTANCE_DATA.x + uTime;
    float limp = clamp(INSTANCE_DATA.z, 0.0, 1.0);
    float amp = 0.16 * tail * mix(1.0, 0.25, limp);
    deformed.y += sin(deformed.x * 5.5 + phase) * amp;
    deformed.z += cos(deformed.x * 4.2 + phase * 1.7) * amp * 0.7;
    POSITION = INSTANCE_MODELVIEWPROJECTION_MATRIX * vec4(deformed, 1.0);
}
