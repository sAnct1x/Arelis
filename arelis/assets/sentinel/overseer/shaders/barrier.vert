VARYING vec3 vWorld;
VARYING vec3 vNrm;
VARYING vec3 vView;

void MAIN() {
    vec4 wp = MODEL_MATRIX * vec4(VERTEX, 1.0);
    vWorld = wp.xyz;
    vNrm = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
    vView = CAMERA_POSITION - vWorld;
    POSITION = MODELVIEWPROJECTION_MATRIX * vec4(VERTEX, 1.0);
}
