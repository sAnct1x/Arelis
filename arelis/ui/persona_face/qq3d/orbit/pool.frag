// The floor pool (pool.vert): soft broken haze, a clearer core band, drifting patches, and a
// warm swell where a packet runs along the floor from her feet to the root.
layout(location = 0) in vec2 vP;
layout(location = 0) out vec4 fragColor;

float pn(float x, float a) {  // a smooth wander, about -1..1
    return 0.55 * sin(x * 0.0061 + a) + 0.3 * sin(x * 0.0173 + 2.0 * a + 1.7) + 0.15 * sin(x * 0.041 - a);
}

void main() {
    float k = treeK();
    float ph = TAU * flow / TREE_LOOP;
    float xm = (vP.x / k);
    float cx = (feet.x + tree.x) * 0.5;
    float hx = max(abs(feet.x - tree.x) * 0.5 + 120.0 * k, 60.0 * k);
    float yc = tree.y + 10.0 * k * sin(xm * 0.006 + 1.3);
    float hz = pn(xm, 0.4);
    float dx = (vP.x - cx) / hx;
    float hy = (58.0 + 20.0 * hz) * k;
    float dy = (vP.y - yc) / hy;
    float pool = exp(-(dx * dx * dx * dx) - dy * dy);
    float dyc = (vP.y - yc - 4.0 * k) / ((20.0 + 8.0 * hz) * k);
    float core = exp(-(dx * dx * dx * dx) * 1.2 - dyc * dyc);
    float br = clamp(0.55 + 0.35 * hz + 0.25 * pn(xm, 3.1) * sin(ph + xm * 0.004), 0.1, 1.2);
    // packets on the floor stretch: head at share r of the route, the floor its first lf
    float pp = 0.0;
    float lf = length(tree.xy - feet) * 1.05;
    float sx = clamp((vP.x - feet.x) / (tree.x - feet.x + 1e-3), 0.0, 1.0);
    for (int j = 0; j < 6; ++j) {
        float u = limbU(j);
        float tot = lf + trunkLen() * u + length(limbTarget(j) - trunkAt(u)) * 1.15;
        float g = packetPhase(j);
        float fadeIn = smoothstep(0.0, 0.03, g);
        float e = (sx * lf / tot - packetHead(j)) * tot / k;
        pp += fadeIn * (e > 0.0 ? exp(-(e / 60.0) * (e / 60.0)) : exp(e / 150.0));
    }
    float on = treeOn * (ringScale >= 1.0 ? 1.0 : ringScale);
    // the brightest part sits under the root, where the trunk's fibers splay over the floor
    float rx = (vP.x - tree.x) / (170.0 * k);
    float root = exp(-rx * rx - dy * dy * 1.4);
    float a = (pool * 0.9 + core * 0.7 + root * 0.9) * br * (0.65 + 0.45 * pp) * 0.8 * on;
    vec3 rgb = gold.rgb * 0.75 + ice.rgb * 0.3 + coreColor.rgb * 0.12 * core;
    fragColor = vec4(rgb * a, 0.0) * qt_Opacity;
}
