void MAIN() {
    vec3 deformed = VERTEX;
    float tail = 1.0 - smoothstep(-0.55, 0.15, deformed.x);
    float speed = max(INSTANCE_DATA.w, 0.05);
    float phase = INSTANCE_DATA.x + uTime * speed;
    float claw = clamp(INSTANCE_DATA.y, 0.0, 1.0);
    float limp = clamp(INSTANCE_DATA.z, 0.0, 1.0);
    float amp = 0.16 * tail * mix(1.0, 0.25, limp);
    // Idle sways gently; busy units reach and curl harder (speed from real state).
    amp *= mix(0.7, 1.45, clamp((speed - 0.4) / 2.1, 0.0, 1.0));
    deformed.y += sin(deformed.x * 5.5 + phase) * amp;
    deformed.z += cos(deformed.x * 4.2 + phase * 1.7) * amp * 0.7;
    float fore = smoothstep(0.12, 0.52, deformed.x) * (1.0 - limp * 0.8);
    float flare = fore * max(0.0, claw - 0.22) * (0.42 + 0.09 * sin(phase * 3.6));
    deformed.y += deformed.y * flare;
    deformed.z += deformed.z * flare * 1.18;
    deformed.x += fore * max(0.0, claw - 0.45) * 0.08;
    POSITION = INSTANCE_MODELVIEWPROJECTION_MATRIX * vec4(deformed, 1.0);
}
