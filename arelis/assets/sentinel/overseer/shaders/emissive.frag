VARYING float vCover;

void MAIN() {
    // Threads and seams thinner than a pixel are dropped, and fade from the
    // caste colour to the hull colour as they approach one pixel wide. They
    // stay under the glow threshold.
    if (vCover < 0.02)
        discard;
    float surge = 0.88 + 0.24 * sin(uTime * 4.4);
    vec3 thread = mix(uHull.rgb, uRole.rgb * (uStrength * surge), vCover);
    FRAGCOLOR = vec4(thread, 1.0);
}
