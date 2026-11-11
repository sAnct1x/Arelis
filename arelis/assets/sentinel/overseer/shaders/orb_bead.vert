// Instanced bead vertex for memory and tool beads. Unit seams keep
// emission_instanced.vert. Multiplies COLOR by INSTANCE_COLOR so each
// bead uses its instance tint, and applies back-half dim. Min-size
// compensation arrives in INSTANCE_DATA.x as (r / pushed r)^2.
// POSITION is left to Qt so instances use INSTANCE_MODELVIEWPROJECTION_MATRIX.
VARYING vec4 vCol;
VARYING float vU;
VARYING float vComp;
VARYING float vBack;

void MAIN() {
    vec3 w = (INSTANCE_MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
    vec3 c = (INSTANCE_MODEL_MATRIX * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
    float ringR = max(length(c - orbCentre), 0.5);
    vBack = mix(1.0, backGain, smoothstep(-0.3, 0.3, dot(c - orbCentre, CAMERA_DIRECTION) / ringR));
    vComp = INSTANCE_DATA.x > 0.0 ? INSTANCE_DATA.x : 1.0;
    vCol = COLOR * INSTANCE_COLOR;
    vU = UV0.x;
}
