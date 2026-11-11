// Instanced source emissive. INSTANCE_DATA.x is lit (0.15 idle, 1.0 busy).
VARYING vec4 vCol;
VARYING float vU;
VARYING float vLit;

void MAIN() {
    vCol = COLOR;
    vU = UV0.x;
    vLit = INSTANCE_DATA.x;
}
