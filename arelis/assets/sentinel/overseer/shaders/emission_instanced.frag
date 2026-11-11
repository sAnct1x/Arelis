// Instanced unit seams. Caste colour arrives as vCaste from INSTANCE_COLOR
// so every caste can share one draw at a given lod. Mesh COLOR stays the
// authored seam tone; gain / litArc / dim are unchanged.
VARYING vec4 vCol;
VARYING float vU;
VARYING vec3 vCaste;

void MAIN() {
    float arc = 0.0;
    if (litArc.y > 0.0) {
        float d = fract(vU - litArc.x);
        arc = step(d, litArc.y) * litArc.z * (1.0 - d / litArc.y);
    }
    FRAGCOLOR = vec4(vCol.rgb * vCaste * (vCol.a * gain + arc) * dim, 1.0);
}
