VARYING vec2 vUv;
VARYING vec3 vTint;

void MAIN() {
    // Soft round point, well under the glow threshold: the sky never blooms.
    float a = 1.0 - smoothstep(0.55, 1.0, length(vUv));
    FRAGCOLOR = vec4(vTint * (0.6 * a), a);
}
