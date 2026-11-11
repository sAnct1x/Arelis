// Unshaded emission for the combined ring and bead draw. Same light
// model as orb_emission.frag; litArc applies only to the tools ring
// (vArc > 0.5).
VARYING vec4 vCol;
VARYING float vU;
VARYING float vComp;
VARYING float vBack;
VARYING float vGain;
VARYING float vArc;

void MAIN() {
    float arc = 0.0;
    if (vArc > 0.5 && litArc.y > 0.0) {
        float d = fract(vU - litArc.x);
        arc = step(d, litArc.y) * litArc.z * (1.0 - d / litArc.y);
    }
    FRAGCOLOR = vec4(vCol.rgb * tint * (vGain + arc) * dim * vComp * vBack, 1.0);
}
