// UnrealBloomPass steps 3 and 4: weighted sum of the 5 mips (lerpBloomFactor), added onto the scene.
// three adds it with AdditiveBlending (src * srcAlpha) into a half float target, where the
// alpha is not clamped: the composite alpha is strength * sum of the factors (0.85 * 3.0 = 2.55
// for v14k), so the bloom lands about 2.5 times brighter than its rgb alone.
float lf(float f) { return mix(f, 1.2 - f, radius); }
void MAIN() {
    vec3 b = lf(1.0) * texture(m1, INPUT_UV).rgb + lf(0.8) * texture(m2, INPUT_UV).rgb
           + lf(0.6) * texture(m3, INPUT_UV).rgb + lf(0.4) * texture(m4, INPUT_UV).rgb
           + lf(0.2) * texture(m5, INPUT_UV).rgb;
    float a = strength * (lf(1.0) + lf(0.8) + lf(0.6) + lf(0.4) + lf(0.2));
    vec4 c = texture(INPUT, INPUT_UV);
    FRAGCOLOR = vec4(c.rgb + strength * b * a, c.a);
}
