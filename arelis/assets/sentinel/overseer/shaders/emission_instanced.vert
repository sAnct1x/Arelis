// Instanced emission vertex: unit seams.
// POSITION is left to Qt so instances use INSTANCE_MODELVIEWPROJECTION_MATRIX.
VARYING vec4 vCol;
VARYING float vU;
VARYING vec3 vCaste;

void MAIN() {
    vCol = COLOR;
    vU = UV0.x;
    vCaste = pow(max(INSTANCE_COLOR.rgb, vec3(0.0)), vec3(2.2));
}
