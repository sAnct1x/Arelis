// Eye lenses. Model nodes are identity, so INSTANCE_MODEL_MATRIX is the world
// transform; multiplying by MODEL_MATRIX is a no-op and either order matches.
VARYING vec3 vEye;
VARYING float vGain;
VARYING vec3 vN;
VARYING vec3 vW;

void MAIN() {
    vEye = pow(max(INSTANCE_COLOR.rgb, vec3(0.0)), vec3(2.2));
    vGain = INSTANCE_DATA.y * INSTANCE_DATA.x;
    vN = normalize((INSTANCE_MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
    vW = (INSTANCE_MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
    POSITION = INSTANCE_MODELVIEWPROJECTION_MATRIX * vec4(VERTEX, 1.0);
}
