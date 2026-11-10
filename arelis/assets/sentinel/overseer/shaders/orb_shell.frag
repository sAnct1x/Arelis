// Fresnel orb shell, unshaded, additive, no depth write (set in QML).
// Properties: shellColor (linear), energy, shellPower, shellGain, impact.
VARYING vec3 vN;
VARYING vec3 vW;

void MAIN() {
    vec3 V = normalize(CAMERA_POSITION - vW);
    float rim = pow(1.0 - clamp(abs(dot(normalize(vN), V)), 0.0, 1.0), shellPower);
    float ring = 0.0;
    if (impact.w > 0.0 && impact.w < 1.0) {
        float d = acos(clamp(dot(normalize(vN), normalize(impact.xyz)), -1.0, 1.0));
        ring = smoothstep(0.06, 0.0, abs(d - impact.w * 0.9)) * (1.0 - impact.w) * 3.0;
    }
    FRAGCOLOR = vec4(shellColor * (rim * shellGain * energy + ring), 1.0);
}
