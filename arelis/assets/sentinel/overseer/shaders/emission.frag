// Unshaded emission. Properties: tint, gain, litArc (tools ring), dim.
// Additive blend is set in QML for filaments and rings; seams are opaque.
VARYING vec4 vCol;
VARYING float vU;

void MAIN() {
    float arc = 0.0;
    if (litArc.y > 0.0) {
        float d = fract(vU - litArc.x);
        arc = step(d, litArc.y) * litArc.z * (1.0 - d / litArc.y);
    }
    FRAGCOLOR = vec4(vCol.rgb * tint * (vCol.a * gain + arc) * dim, 1.0);
}
