// Pass E head v2 (fix-c05bb78). Instanced, one draw per LOD for every caste.
// Instance colour MUST be white: Qt multiplies COLOR by INSTANCE_COLOR and a Shaded material's BASE_COLOR by COLOR.
// COLOR = albedo (baked cavity) + emissive mask; UV0 = (eye id / 32, part 0 hull 1 lens 2 seam 3 barrel).
// INSTANCE_DATA = (eye colour rgb LINEAR, eyeMul).
VARYING vec3 vTone;
VARYING float vEm;
VARYING float vPart;
VARYING vec3 vEye;
VARYING float vEyeMul;
VARYING vec3 vN;
VARYING vec3 vW;
const vec4 EYE[21] = vec4[21](
    vec4(0.9996, 0.0300, 0.0000, 0.1250),
    vec4(0.9701, -0.1100, 0.3750, 0.1050),
    vec4(0.9701, -0.1100, -0.3750, 0.1050),
    vec4(0.9635, 0.2357, -0.2109, 0.0620),
    vec4(0.9694, 0.0300, -0.4219, 0.0620),
    vec4(0.9772, -0.1757, -0.2109, 0.0620),
    vec4(0.9772, -0.1757, 0.2109, 0.0620),
    vec4(0.9694, 0.0300, 0.4219, 0.0620),
    vec4(0.9635, 0.2357, 0.2109, 0.0620),
    vec4(0.9716, 0.2200, 0.1500, 0.0380),
    vec4(0.9716, 0.2200, -0.1500, 0.0380),
    vec4(0.9605, 0.1700, 0.3750, 0.0380),
    vec4(0.9605, 0.1700, -0.3750, 0.0380),
    vec4(0.9650, -0.2500, 0.1250, 0.0380),
    vec4(0.9650, -0.2500, -0.1250, 0.0380),
    vec4(0.9373, 0.0500, 0.5750, 0.0380),
    vec4(0.9373, 0.0500, -0.5750, 0.0380),
    vec4(0.9165, -0.2700, 0.4500, 0.0380),
    vec4(0.9165, -0.2700, -0.4500, 0.0380),
    vec4(0.9516, 0.3000, 0.0000, 0.0380),
    vec4(0.9437, -0.3200, 0.0000, 0.0380)
);
void MAIN()
{
    vTone = COLOR.rgb;
    vEm = COLOR.a;
    vPart = UV0.y;
    vEye = INSTANCE_DATA.rgb;
    vEyeMul = INSTANCE_DATA.a;
    vec3 P = VERTEX;
    // Minimum eye size: grow each lens + barrel about its face point until its radius covers eyeMinPx.
    if (abs(UV0.y - 1.0) < 0.3 || abs(UV0.y - 3.0) < 0.3) {
        vec4 e = EYE[clamp(int(UV0.x * 32.0 + 0.5), 0, 20)];
        vec4 c = INSTANCE_MODELVIEWPROJECTION_MATRIX * vec4(e.xyz, 1.0);
        float sc = length(INSTANCE_MODEL_MATRIX[0].xyz);
        float rPx = e.w * eyeRadiusMul * sc * PROJECTION_MATRIX[1][1] * 0.5 * uViewportH / max(c.w, 0.25);
        float k = clamp(eyeMinPx / max(rPx, 1e-3), 1.0, 2.4);
        P = e.xyz + (P - e.xyz) * k;
    }
    vN = normalize(mat3(INSTANCE_MODEL_MATRIX) * NORMAL);
    vW = (INSTANCE_MODEL_MATRIX * vec4(P, 1.0)).xyz;
    // Do not assign VERTEX: Qt then skips the default POSITION.
    POSITION = INSTANCE_MODELVIEWPROJECTION_MATRIX * vec4(P, 1.0);
}
