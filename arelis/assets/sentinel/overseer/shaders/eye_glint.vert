VARYING vec4 vCol;
VARYING float vRho;
void MAIN() {
    vec3 w = (INSTANCE_MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
    vec3 c = (INSTANCE_MODEL_MATRIX * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
    vec3 off = w - c;
    off -= CAMERA_DIRECTION * dot(off, CAMERA_DIRECTION);
    float rad = max(length(vec3(INSTANCE_MODEL_MATRIX[0].x, INSTANCE_MODEL_MATRIX[1].x, INSTANCE_MODEL_MATRIX[2].x)), 1e-4);
    vRho = length(off) / rad;
    vCol = INSTANCE_COLOR;
    // INSTANCE_DATA.x is min-px compensation (bead convention).
    float comp = INSTANCE_DATA.x > 0.0 ? INSTANCE_DATA.x : 1.0;
    vCol.rgb *= comp;
    POSITION = INSTANCE_MODELVIEWPROJECTION_MATRIX * vec4(VERTEX, 1.0);
}
