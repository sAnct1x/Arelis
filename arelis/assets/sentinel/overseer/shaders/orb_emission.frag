// Unshaded emission for filaments, rings and beads: shared emission
// times vComp (min-width light compensation) and vBack (back-half dim).
// Additive One/One, NeverDepthDraw. Properties: tint, gain, litArc, dim.
VARYING vec4 vCol;
VARYING float vU;
VARYING float vComp;
VARYING float vBack;

void MAIN() {
    float arc = 0.0;
    if (litArc.y > 0.0) {
        float d = fract(vU - litArc.x);
        arc = step(d, litArc.y) * litArc.z * (1.0 - d / litArc.y);
    }
    FRAGCOLOR = vec4(vCol.rgb * tint * (vCol.a * gain + arc) * dim * vComp * vBack, 1.0);
}
