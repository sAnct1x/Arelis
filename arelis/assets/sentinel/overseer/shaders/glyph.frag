VARYING vec2 vUv;
VARYING float vAlpha;
VARYING vec3 vTint;

void MAIN() {
    float a = texture(uAtlas, vUv).a * vAlpha;
    FRAGCOLOR = vec4(vTint * a * 1.6, a);
}
