// The floor pool (pool.vert): it wells up under her feet and runs out to the tree's root, in
// slow swells away from her, with a warm swell where a packet runs along the floor.
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
        float tot = routeTot(j);
        float g = packetPhase(j);
        float fadeIn = smoothstep(0.0, 0.03, g);
        float e = (sx * lf / tot - packetHead(j)) * tot / k;
        pp += fadeIn * (e > 0.0 ? exp(-(e / 60.0) * (e / 60.0)) : exp(e / 150.0));
    }
    float on = treeOn * (ringScale >= 1.0 ? 1.0 : ringScale);
    // The light wells up out of her: the brightest part is under her feet, and it runs out
    // along the floor to the root, thinning, in slow swells that travel away from her.
    float fx = (vP.x - feet.x) / (150.0 * k);
    float src = exp(-fx * fx - dy * dy * 1.2);
    float rx = (vP.x - tree.x) / (170.0 * k);
    float root = exp(-rx * rx - dy * dy * 1.4);
    float swell = 0.75 + 0.25 * sin(TAU * (ph / TAU - sx * 1.5));
    float lean = mix(1.0, 0.55, sx);   // full at her feet, thinner at the root
    float a = (pool * 0.8 * lean * swell + core * 0.7 * lean + src * 1.25 + root * 0.45)
            * br * (0.65 + 0.45 * pp) * 0.8 * on;
    vec3 rgb = gold.rgb * 0.75 + ice.rgb * 0.3 + coreColor.rgb * 0.12 * core;
    fragColor = vec4(rgb * a, 0.0) * qt_Opacity;
}
