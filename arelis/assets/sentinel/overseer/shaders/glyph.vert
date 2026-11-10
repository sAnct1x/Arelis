VARYING vec2 vUv;
VARYING float vAlpha;
VARYING vec3 vTint;

void MAIN() {
    // One instanced quad per glyph. The instance sits on its source node; the
    // arc to the core, the flow and the fade are evaluated here from uTime.
    // INSTANCE_DATA: x = glyph slot in its lane, y = trail birth (sceneTime),
    // z = atlas cell (ASCII - 32), w = lane + 2 * lane length.
    vec3 S = (INSTANCE_MODEL_MATRIX * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
    vec3 E = vec3(0.0, 0.4, 0.0);
    vec3 C = vec3(S.x * 0.5, max(S.y, 0.5) + 2.6, S.z * 0.5);
    float arcLen = length(C - S) + length(E - C);
    vec3 right = vec3(VIEW_MATRIX[0][0], VIEW_MATRIX[1][0], VIEW_MATRIX[2][0]);
    vec3 up = vec3(VIEW_MATRIX[0][1], VIEW_MATRIX[1][1], VIEW_MATRIX[2][1]);
    float lane = mod(INSTANCE_DATA.w, 2.0);
    float laneLen = floor(INSTANCE_DATA.w / 2.0);
    // Keep the words reading left to right on screen whichever way the trail flies.
    float slot = dot(E - S, right) > 0.0 ? laneLen - 1.0 - INSTANCE_DATA.x : INSTANCE_DATA.x;
    float age = uTime - INSTANCE_DATA.y;
    float spacing = 0.34;
    // Every letter keeps flying along the arc and dives into the core: the head
    // arrives 2.5 s after the result lands, the rest follow at the same speed
    // and dim as they enter the orb. Nothing stops in the sky.
    float t = (age * arcLen / 2.5 - slot * spacing) / arcLen;
    float live = step(0.0, t) * step(t, 1.0) * step(0.0, age);
    float fade = (1.0 - smoothstep(0.93, 1.0, t)) * (1.0 - smoothstep(4.4, 5.0, age));
    float tail = mix(1.0, 0.25, clamp(slot / 30.0, 0.0, 1.0));
    vAlpha = live * fade * tail * (slot < 0.5 ? 1.35 : 1.0);
    float u = 1.0 - clamp(t, 0.0, 1.0);
    float tc = clamp(t, 0.0, 1.0);
    vec3 P = u * u * S + 2.0 * u * tc * C + tc * tc * E;
    P -= up * (0.62 * lane);
    // Same world size for every source's text.
    float size = 0.5 * step(0.001, vAlpha);
    vec3 world = P + (right * VERTEX.x + up * VERTEX.y) * (size / 100.0);
    POSITION = VIEWPROJECTION_MATRIX * vec4(world, 1.0);
    float cell = INSTANCE_DATA.z;
    float col = mod(cell, 16.0);
    float row = floor(cell / 16.0);
    vUv = vec2((col + VERTEX.x / 100.0 + 0.5) / 16.0, (row + 0.5 - VERTEX.y / 100.0) / 6.0);
    vTint = INSTANCE_COLOR.rgb;
}
