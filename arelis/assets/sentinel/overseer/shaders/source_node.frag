// source_emissive: COLOR_0 masks pick the part (1,0,0) edges, (0,1,0) halo, (0,0,1) core.
// Properties: nodeColor (linear), lit (0.15 idle, 1.0 busy).
VARYING vec4 vCol;
VARYING float vU;
VARYING float vLit;

void MAIN() {
    vec3 coreCol = mix(nodeColor, vec3(0.86, 0.96, 1.0), step(0.5, vLit));
    float k = pow(clamp(vLit, 0.0, 1.5), 1.45);
    float s = k * (vCol.r * 6.0 + vCol.g * 3.1 + vCol.b * 16.0);
    vec3 c = mix(nodeColor, coreCol, vCol.b);
    FRAGCOLOR = vec4(c * s, 1.0);
}
