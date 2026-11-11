// Shaded rim hull. Properties: rimGain, rimPower, metal, rough, wearGain, lipGain.
// wearGain and lipGain are set only on unit_hull_lod1; other meshes store other data in UV0.x.
// UV0.x 0..1 = edge wear; values above 1 are the front-lip highlight (lip = UV0.x - 1).
VARYING vec4 vTone;
VARYING vec3 vCaste;
VARYING float vDim;
VARYING float vWear;

void MAIN() {
    BASE_COLOR = vec4(vTone.rgb, 1.0);
    float w = clamp(vWear, 0.0, 1.0) * wearGain;
    float lip = max(vWear - 1.0, 0.0) * wearGain;
    METALNESS = mix(metal, 0.3, w);
    ROUGHNESS = mix(rough, 0.22, w);
    vec3 n = normalize(VAR_WORLD_NORMAL);
    vec3 v = normalize(VIEW_VECTOR);
    float facing = 1.0 - clamp(dot(n, v), 0.0, 1.0);
    // Caste rim stays under the bloom threshold so hulls never bloom.
    EMISSIVE_COLOR = vCaste * pow(facing, rimPower) * vTone.a * rimGain * vDim
                   + vTone.rgb * (0.18 * w + lipGain * lip) * vDim;
}
