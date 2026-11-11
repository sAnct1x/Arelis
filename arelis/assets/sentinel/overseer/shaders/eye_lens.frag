// Unshaded eye: hot core facing the camera, caste halo at the rim.
// Properties: eyeStrength (4.46 LOD2, 2.48 LOD1/0), coreWhite (0.55).
VARYING vec3 vEye;
VARYING float vGain;
VARYING vec3 vN;
VARYING vec3 vW;

void MAIN() {
    vec3 V = normalize(CAMERA_POSITION - vW);
    float facing = clamp(dot(normalize(vN), V), 0.0, 1.0);
    vec3 core = mix(vEye, vec3(1.0), coreWhite);
    vec3 c = mix(vEye, core, pow(facing, 1.5));
    FRAGCOLOR = vec4(c * eyeStrength * vGain, 1.0);
}
