VARYING vec2 vUv;
VARYING vec3 vTint;

void MAIN() {
    // One instanced quad per star, sized in screen pixels. INSTANCE_DATA.x is
    // the size at a 2560 px wide view (1 to 3 px); a smaller view keeps 1 px.
    vec4 clip = INSTANCE_MODELVIEWPROJECTION_MATRIX * vec4(0.0, 0.0, 0.0, 1.0);
    float px = max(1.0, INSTANCE_DATA.x * uViewportW / 2560.0);
    vUv = VERTEX.xy / 50.0;
    clip.xy += vUv * vec2(px / uViewportW, px / uViewportH) * clip.w;
    POSITION = clip;
    vTint = INSTANCE_COLOR.rgb;
}
