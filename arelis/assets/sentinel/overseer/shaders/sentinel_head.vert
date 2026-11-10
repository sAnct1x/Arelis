// Pass E: instanced sentinel head, one draw per LOD for every caste.
// Eyes and caste seam are merged into the head mesh (UV0.y part id).
// Balsam unflips the glTF V, so UV0.y is 0 hull, 1 lens, 2 seam, 3 barrel.
// color = eye colour (sRGB instance colour, decoded below); customData = (caste.rgb linear, eyeMul).
VARYING vec3 vTone;
VARYING float vEm;
VARYING float vPart;
VARYING vec3 vEye;
VARYING vec4 vCaste;
void MAIN()
{
    vTone = COLOR.rgb;
    vEm = COLOR.a;
    vPart = UV0.y;
    // Instance colour is sRGB; the stub expected linear.
    vEye = pow(max(INSTANCE_COLOR.rgb, vec3(0.0)), vec3(2.2));
    vCaste = INSTANCE_DATA;
    // Do not assign VERTEX: Qt then skips the default POSITION.
    POSITION = INSTANCE_MODELVIEWPROJECTION_MATRIX * vec4(VERTEX, 1.0);
}
