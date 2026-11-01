// UnrealBloomPass step 1 (three LuminosityHighPassShader): keep pixels whose Rec.709 luma
// passes the threshold. Luma, not the max channel Quick 3D glow uses, so violet and blue
// (low green) stay under it and the whiter rim goes over.
void MAIN() {
    vec4 t = texture(INPUT, INPUT_UV);
    float v = dot(t.rgb, vec3(0.2126729, 0.7151522, 0.0721750));
    FRAGCOLOR = vec4(t.rgb * smoothstep(threshold, threshold + 0.01, v), 1.0);
}
