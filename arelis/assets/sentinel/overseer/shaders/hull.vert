void MAIN() {
    vec3 p = VERTEX;
    float tail = 1.0 - smoothstep(-0.55, 0.15, p.x);
    float phase = INSTANCE_DATA.x + uTime;
    float limp = clamp(INSTANCE_DATA.z, 0.0, 1.0);
    float amp = 0.16 * tail * mix(1.0, 0.25, limp);
    p.y += sin(p.x * 5.5 + phase) * amp;
    p.z += cos(p.x * 4.2 + phase * 1.7) * amp * 0.7;
    VERTEX = p;
}
