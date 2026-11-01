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
    vec3 rgb = c.rgb + strength * b * a;
    if (keyAlpha < 0.5) {
        FRAGCOLOR = vec4(rgb, c.a);
        return;
    }
    // Over a see-through clear (the app window): the look is made on black, so key the black
    // out. Alpha is the brightest channel after the sRGB encode the linear tonemap applies next,
    // so the output stays valid premultiplied colour (rgb <= alpha) and lands on the room like
    // it lands on v14k's black: glow and bloom add light, the dark floor plane lets the room through.
    // Keeping c.a gave rgb over alpha 0 (bloom outside her, hidden floor), which the window's
    // premultiplied composite turned into white blowout and blocky cyan fringes.
    vec3 lit = clamp(rgb, 0.0, 1.0);
    float m = max(lit.r, max(lit.g, lit.b));
    float enc = m <= 0.0031308 ? 12.92 * m : 1.055 * pow(m, 1.0 / 2.4) - 0.055;
    // The view is a band in the window: fade its inner (left) edge so the floor and threads
    // do not stop on a hard line. Scaling rgb and alpha together keeps it premultiplied.
    float edge = smoothstep(0.0, 0.12, INPUT_UV.x);
    FRAGCOLOR = vec4(lit, clamp(enc, 0.0, 1.0)) * edge;
}
