// Fresnel orb shell plus a faint body term so the inside reads as glass.
// Unshaded, additive, no depth write, NoCulling (set in QML).
// Properties: shellColor (linear), energy, shellPower, shellGain, shellBody, impact.
VARYING vec3 vN;
VARYING vec3 vW;

void MAIN() {
    vec3 V = normalize(CAMERA_POSITION - vW);
    float nv = clamp(abs(dot(normalize(vN), V)), 0.0, 1.0);
    float rim = pow(1.0 - nv, shellPower);
    float ring = 0.0;
    if (impact.w > 0.0 && impact.w < 1.0) {
        float d = acos(clamp(dot(normalize(vN), normalize(impact.xyz)), -1.0, 1.0));
        ring = smoothstep(0.06, 0.0, abs(d - impact.w * 0.9)) * (1.0 - impact.w) * 3.0;
    }
    FRAGCOLOR = vec4(shellColor * ((rim * shellGain + nv * shellBody) * energy + ring), 1.0);
}
