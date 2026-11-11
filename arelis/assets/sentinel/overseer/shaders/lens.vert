VARYING vec3 vEye;

void MAIN() {
    // Eye colour is per instance: caste colour, #2fc4ff while a Harvester
    // fetches, red only while a unit is engaged on a real threat.
    vEye = INSTANCE_COLOR.rgb;
    // The eye sits in a socket about 0.45 units behind the hull's front lip
    // and is 0.08 units across at LOD2, so from the overview it was hidden by
    // its own hull and under one pixel: the bloom had nothing to catch. Grow
    // it about its centre to at least uEyeMinPx on screen (zero change up
    // close) and bias its depth by the socket depth so it reads through its
    // own face. The bias is under one unit length, so it never shows through
    // a neighbour.
    vec3 c = vec3(1.215, 0.0, 0.0);
    float unitScale = length(INSTANCE_MODEL_MATRIX[0].xyz);
    vec4 centreClip = INSTANCE_MODELVIEWPROJECTION_MATRIX * vec4(c, 1.0);
    float pxPerUnit = PROJECTION_MATRIX[1][1] * 0.5 * uViewportH / max(centreClip.w, 0.001);
    float want = uEyeMinPx / max(pxPerUnit * unitScale, 0.0001);
    POSITION = INSTANCE_MODELVIEWPROJECTION_MATRIX * vec4(VERTEX, 1.0);
    // The projection is linear in homogeneous space, so growing in clip space
    // about the centre is exact and the mesh itself is never rewritten.
    POSITION = centreClip + (POSITION - centreClip) * max(1.0, want / 0.08);
    POSITION.z += PROJECTION_MATRIX[2][2] * 0.6 * unitScale;
}
