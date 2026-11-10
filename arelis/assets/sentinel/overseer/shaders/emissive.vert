void MAIN() {
    vec3 deformed = VERTEX;
    float speed = max(INSTANCE_DATA.w, 0.05);
    float phase = INSTANCE_DATA.x + uTime * speed;
    // INSTANCE_DATA.y packs claw + 2*reach + 8*previous reach + 32*limp (whole numbers
    // above the claw fraction); INSTANCE_DATA.z is the sceneTime the reach count changed.
    float packed = max(INSTANCE_DATA.y, 0.0);
    float limpBit = floor(packed / 32.0);
    packed -= limpBit * 32.0;
    float prevReach = floor(packed / 8.0);
    packed -= prevReach * 8.0;
    float reachPairs = floor(packed / 2.0);
    float claw = clamp(packed - reachPairs * 2.0, 0.0, 1.0);
    float limp = clamp(limpBit, 0.0, 1.0);
    // Tentacles leave the thorax at x = -2.63 and run about 4.3 m back.
    vec3 rest = VERTEX;
    float along = clamp((-2.63 - rest.x) / 4.3, 0.0, 1.0);
    float ease = clamp((uTime - INSTANCE_DATA.z) / 0.4, 0.0, 1.0);
    ease = 1.0 - (1.0 - ease) * (1.0 - ease) * (1.0 - ease);
    float wantA = mix(step(0.5, prevReach), step(0.5, reachPairs), ease);
    float wantB = mix(step(1.5, prevReach), step(1.5, reachPairs), ease);
    float wantC = mix(step(2.5, prevReach), step(2.5, reachPairs), ease);
    // Most units have no open fetch: skip the slot search and the hinge, which
    // leave the vertex where it is when no front pair reaches.
    float reachW = 0.0;
    vec2 hingeDir = vec2(1.0, 0.0);
    if (max(wantA, max(wantB, wantC)) * (1.0 - limp) > 0.0) {
        // Snap to the tentacle this vertex belongs to (uTentacles per LOD, first at 0.3 rad)
        // so every vertex of one tentacle gets the same reach.
        float around = atan((rest.y + 0.34 * along * along) / 0.35, -rest.z / 0.405);
        float slotStep = 6.2831853 / max(uTentacles, 1.0);
        float slotAngle = 0.3 + floor((around - 0.3) / slotStep + 0.5) * slotStep;
        vec2 dir = vec2(sin(slotAngle), -cos(slotAngle));
        // Front pairs (mirrored left and right): upper sides, upper inner, lower sides.
        // Smooth angular windows keep the field continuous, so links never tear.
        float lateral = dir.y < 0.0 ? -1.0 : 1.0;
        vec2 centerA = vec2(0.423, 0.906 * lateral);
        vec2 centerB = vec2(0.866, 0.5 * lateral);
        vec2 centerC = vec2(-0.423, 0.906 * lateral);
        float pairA = smoothstep(0.92, 0.97, dot(dir, centerA));
        float pairB = smoothstep(0.92, 0.97, dot(dir, centerB));
        float pairC = smoothstep(0.92, 0.97, dot(dir, centerC));
        reachW = max(pairA * wantA, max(pairB * wantB, pairC * wantC)) * (1.0 - limp);
        // Hinge on the pair's centre line so a whole tentacle swings as one piece.
        hingeDir = centerA * pairA * wantA + centerB * pairB * wantB + centerC * pairC * wantC;
        hingeDir = length(hingeDir) > 0.0001 ? normalize(hingeDir) : dir;
    }
    float tail = 1.0 - smoothstep(-0.55, 0.15, deformed.x);
    float amp = 0.16 * tail * mix(1.0, 0.25, limp);
    // Idle sways gently; busy units reach and curl harder (speed from real state).
    amp *= mix(0.7, 1.45, clamp((speed - 0.4) / 2.1, 0.0, 1.0));
    amp *= 1.0 - 0.6 * reachW;
    deformed.y += sin(deformed.x * 5.5 + phase) * amp;
    deformed.z += cos(deformed.x * 4.2 + phase * 1.7) * amp * 0.7;
    float fore = smoothstep(0.12, 0.52, deformed.x) * (1.0 - limp * 0.8);
    float flare = fore * max(0.0, claw - 0.22) * (0.42 + 0.09 * sin(phase * 3.6));
    deformed.y += deformed.y * flare;
    deformed.z += deformed.z * flare * 1.18;
    deformed.x += fore * max(0.0, claw - 0.45) * 0.08;
    // Curl: tips coil around the body axis, 0.4 idle up to 1.0 busy, breathing with the wave.
    float curl = mix(0.4, 1.0, clamp((speed - 0.55) / 1.25, 0.0, 1.0)) * mix(1.0, 0.3, limp);
    float coil = curl * 1.3 * along * along * (0.8 + 0.2 * sin(phase * 0.5)) * (1.0 - reachW);
    float cc = cos(coil);
    float sc = sin(coil);
    deformed.yz = vec2(deformed.y * cc - deformed.z * sc, deformed.y * sc + deformed.z * cc);
    // Reach: swing the tentacle out over a hinge on the hull and forward toward the target.
    if (reachW > 0.0) {
        float bend = reachW * (1.7 + 1.35 * along) * smoothstep(0.0, 0.25, along);
        vec3 er = vec3(0.0, hingeDir.x, hingeDir.y);
        vec3 hinge = vec3(-2.63, 0.0, 0.0) + er * 0.8;
        vec3 q = deformed - hinge;
        float qa = q.x;
        float qb = dot(q, er);
        vec3 qc = q - vec3(qa, 0.0, 0.0) - er * qb;
        float cb = cos(bend);
        float sb = sin(bend);
        deformed = hinge + vec3(qa * cb + qb * sb, 0.0, 0.0) + er * (-qa * sb + qb * cb) + qc;
    }
    POSITION = INSTANCE_MODELVIEWPROJECTION_MATRIX * vec4(deformed, 1.0);
}
