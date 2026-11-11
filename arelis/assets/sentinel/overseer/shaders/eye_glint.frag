VARYING vec4 vCol;
VARYING float vRho;
void MAIN() {
    float g = exp(-vRho * vRho);
    FRAGCOLOR = vec4(vCol.rgb * g, 1.0);
}
