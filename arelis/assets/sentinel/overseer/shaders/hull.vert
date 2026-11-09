void MAIN() {
    vec3 p = VERTEX;
    float tail = 1.0 - smoothstep(-0.55, 0.15, p.x);
    float phase = INSTANCE_DATA.x + uTime;
    float claw = clamp(INSTANCE_DATA.y, 0.0, 1.0);
    float limp = clamp(INSTANCE_DATA.z, 0.0, 1.0);
    float amp = 0.16 * tail * mix(1.0, 0.25, limp);
    p.y += sin(p.x * 5.5 + phase) * amp;
    p.z += cos(p.x * 4.2 + phase * 1.7) * amp * 0.7;
    float fore = smoothstep(0.12, 0.52, p.x) * (1.0 - limp * 0.8);
    float flare = fore * max(0.0, claw - 0.22) * (0.42 + 0.09 * sin(phase * 3.6));
    p.y += p.y * flare;
    p.z += p.z * flare * 1.18;
    p.x += fore * max(0.0, claw - 0.45) * 0.08;
    VERTEX = p;
}
