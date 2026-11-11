VARYING vec4 vCol;
VARYING float vU;
void MAIN() {
    float wave = 0.35 + 0.65 * pow(0.5 + 0.5 * sin(vU * waveK + wavePh), 3.0);
    float s = gain * (0.25 + vU * 0.75) * wave;
    if (waveK < 0.01)
        s = gain;
    FRAGCOLOR = vec4(vCol.rgb * s, 1.0);
}
