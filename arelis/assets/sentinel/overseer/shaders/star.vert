VARYING vec2 vUv;
VARYING vec3 vTint;

void MAIN() {
    // Non-instanced starfield: VERTEX is the rest position plus a 1 cm
    // corner offset so the triangles have area; UV0 is the clip-space
    // corner in -1..1; UV1.x is the size at a 2560 px wide view (1 to
    // 3 px); UV1.y is the layer parallax rate. Layers turn about the
    // hive Y axis at different rates so they slide past each other.
    vec3 localOrigin = VERTEX - vec3(UV0.x, UV0.y, 0.0) * 0.01;
    vec3 origin = (MODEL_MATRIX * vec4(localOrigin, 1.0)).xyz;
    float ang = uStarDrift * UV1.y;
    float c = cos(ang), s = sin(ang);
    origin = vec3(origin.x * c + origin.z * s, origin.y, -origin.x * s + origin.z * c);
    vec4 clip = VIEWPROJECTION_MATRIX * vec4(origin, 1.0);
    // A star near or behind the camera plane (w ~ 0) would expand into a
    // screen-filling quad. Hide it instead.
    if (abs(clip.w) < 0.25) {
        POSITION = vec4(0.0, 0.0, -2.0, 1.0);
        vUv = vec2(0.0);
        vTint = vec3(0.0);
        return;
    }
    float px = max(1.0, UV1.x * uViewportW / 2560.0);
    vUv = UV0;
    clip.xy += vUv * vec2(px / uViewportW, px / uViewportH) * clip.w;
    POSITION = clip;
    vTint = COLOR.rgb;
}
