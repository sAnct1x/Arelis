VARYING vec3 vN;
VARYING vec3 vW;

void MAIN() {
    vN = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
    vW = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
    POSITION = MODELVIEWPROJECTION_MATRIX * vec4(VERTEX, 1.0);
}
