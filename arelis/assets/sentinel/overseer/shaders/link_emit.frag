
VARYING vec3 vCol;
void MAIN() {
    FRAGCOLOR = vec4(vCol * gain, 1.0);
}
