// Instanced emission vertex: unit seams and orb beads.
// POSITION is left to Qt so instances use INSTANCE_MODELVIEWPROJECTION_MATRIX.
VARYING vec4 vCol;
VARYING float vU;

void MAIN() {
    vCol = COLOR;
    vU = UV0.x;
}
