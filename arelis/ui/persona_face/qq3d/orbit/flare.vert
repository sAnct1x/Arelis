// A node's flare when its packet arrives (spec fix 1): a halo bloom (r 40 and 110, mockup px)
// and one ring opening from r 30 to 115 as it fades over about 1 s. One quad per node.
layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec2 vQ;        // mockup px from the node
layout(location = 1) out vec4 vFlare;    // boost, ring radius, ring alpha, ring width

const float N = 7.0;   // the six crown tiles and the reality tile

void main() {
    float col = floor(qt_MultiTexCoord0.x * (4.0 * N - 1.0) + 0.5);
    float i = floor(col / 4.0);
    float kk = col - i * 4.0;
    vec2 corner = vec2(kk == 0.0 ? -1.0 : 1.0, qt_MultiTexCoord0.y * 2.0 - 1.0);
    if (kk >= 2.0) corner.y = -1.0;
    if (kk == 3.0) { i += 1.0; corner.x = -1.0; }
    int j = i < 6.0 ? int(i) : 10;   // 10: the minor limb that reaches the reality tile
    float ph = packetPhase(j);
    float e = (ph - 0.82) * TREE_LOOP;   // seconds since the packet reached the node
    float boost = e < 0.0 ? exp(-(e / 0.22) * (e / 0.22)) : exp(-e / 0.6);
    float q = clamp(e / 1.0, 0.0, 1.0);
    float ringA = e >= 0.0 && e < 1.0 ? 0.75 * pow(1.0 - q, 1.6) : 0.0;
    float rr = 30.0 + 85.0 * (1.0 - (1.0 - q) * (1.0 - q));
    float on = treeOn * (ringScale >= 1.0 ? 1.0 : 0.0) * (j == 10 && reality.x < 0.0 ? 0.0 : 1.0);
    float reach = (boost * on > 0.01 || ringA * on > 0.01) ? 300.0 : 0.0;
    vQ = corner * reach;
    vFlare = vec4(boost * on, rr, ringA * on, 3.0 + 5.0 * q);
    gl_Position = qt_Matrix * vec4(limbTarget(j) + corner * reach * treeK(), 0.0, 1.0);
}
