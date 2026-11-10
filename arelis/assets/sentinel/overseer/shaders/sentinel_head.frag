// Pass E head + merged eyes + caste seam. Shaded.
// eyeGain LOD0 1.35, LOD1 1.40, LOD2 1.60; seamGain 0.45 / 0.50 / 1.00; rimGain 0.06 / 0.10 / 0.20.
VARYING vec3 vTone;
VARYING float vEm;
VARYING float vPart;
VARYING vec3 vEye;
VARYING vec4 vCaste;
void MAIN()
{
    float lens = step(abs(vPart - 1.0), 0.3);
    float seam = step(abs(vPart - 2.0), 0.3);
    // Groove tone is already #15171b. A floor keeps plate joins from
    // reading as sky if a 1 px crack opens between overlapping bands.
    vec3 tone = max(vTone, vec3(0.06, 0.065, 0.07));
    BASE_COLOR = vec4(mix(tone, vec3(0.01, 0.01, 0.012), lens), 1.0);
    METALNESS = 0.5 * (1.0 - lens);
    ROUGHNESS = 0.52 - 0.42 * lens;
    vec3 V = normalize(CAMERA_POSITION - VAR_WORLD_POSITION);
    float facing = 1.0 - abs(dot(normalize(VAR_WORLD_NORMAL), V));
    vec3 eye = vEye * (0.02 + 0.98 * vEm * vEm * vEm) * lens * eyeGain * vCaste.a;
    vec3 caste = vCaste.rgb * (pow(facing, 3.0) * rimGain * (1.0 - lens) + vEm * seam * seamGain);
    EMISSIVE_COLOR = eye + caste;
}
