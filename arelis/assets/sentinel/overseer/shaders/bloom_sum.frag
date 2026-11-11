// Hable filmic curve as ExtendedSceneEnvironment runs it (exposure bias 2,
// white 1), then linear to sRGB.
vec3 filmic(vec3 x) {
    const float A = 0.88, B = 0.6, C = 0.1, D = 0.2, E = 0.01, F = 0.3;
    const float W = ((A + C * B) + D * E) / ((A + B) + D * F) - E / F;
    vec3 y = ((x * (A * x + C * B) + D * E) / (x * (A * x + B) + D * F)) - E / F;
    y = clamp(y / W, vec3(0.0), vec3(1.0));
    return mix(1.055 * pow(y, vec3(1.0 / 2.4)) - 0.055, 12.92 * y, lessThan(y, vec3(0.0031308)));
}

// Half size: the bloom levels summed and tonemapped once, so the full-size
// pass reads one glow texel instead of three and tonemaps only the scene.
void MAIN() {
    vec3 glow = texture(INPUT, INPUT_UV).rgb;
    if (uLevels > 1.5)
        glow += texture(glow2, INPUT_UV).rgb;
    if (uLevels > 2.5)
        glow += texture(glow3, INPUT_UV).rgb;
    FRAGCOLOR = vec4(filmic(glow * uIntensity), 1.0);
}
