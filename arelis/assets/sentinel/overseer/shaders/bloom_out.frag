// Hable filmic curve as ExtendedSceneEnvironment runs it (exposure bias 2,
// white 1), then linear to sRGB, then a soft shoulder above uKnee so
// highlights roll off instead of clipping to a flat 255.
vec3 filmic(vec3 x) {
    const float A = 0.88, B = 0.6, C = 0.1, D = 0.2, E = 0.01, F = 0.3;
    const float W = ((A + C * B) + D * E) / ((A + B) + D * F) - E / F;
    vec3 y = ((x * (A * x + C * B) + D * E) / (x * (A * x + B) + D * F)) - E / F;
    y = clamp(y / W, vec3(0.0), vec3(1.0));
    return mix(1.055 * pow(y, vec3(1.0 / 2.4)) - 0.055, 12.92 * y, lessThan(y, vec3(0.0031308)));
}

vec3 shoulder(vec3 v) {
    vec3 t = max(v - vec3(uKnee), vec3(0.0));
    vec3 s = vec3(uKnee) + (1.0 - uKnee) * (vec3(1.0) - exp(-t / (1.0 - uKnee)));
    return mix(v, s, step(vec3(uKnee), v));
}

// Last pass: the Filmic tonemap of the scene (the scene environment runs
// none) plus the tonemapped bloom on top, as ExtendedSceneEnvironment's
// additive glow does, then the shoulder.
void MAIN() {
    vec4 c = texture(INPUT, INPUT_UV);
    vec3 color = filmic(c.rgb * uExposure);
    if (uLevels > 0.5)
        color += texture(glowSum, INPUT_UV).rgb;
    FRAGCOLOR = vec4(shoulder(color), c.a);
}
