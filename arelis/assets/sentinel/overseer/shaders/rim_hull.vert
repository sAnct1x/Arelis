// Pass C hull / links. COLOR_0.rgb is linear base tone, .a is rim strength k.
// INSTANCE_COLOR is caste colour (sRGB, converted here). INSTANCE_DATA = (dim, eyeGain, threatMix, unitIndex).
VARYING vec4 vTone;
VARYING vec3 vCaste;
VARYING float vDim;
VARYING float vWear;

void MAIN() {
    vTone = COLOR;
    vCaste = pow(max(INSTANCE_COLOR.rgb, vec3(0.0)), vec3(2.2));
    vDim = INSTANCE_DATA.x;
    vWear = UV0.x;
}
