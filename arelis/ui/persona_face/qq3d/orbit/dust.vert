// The 1100 grains, one quad each. GridMesh (4 * N - 1) x 1: per grain the columns are its
// left edge, its right edge, its top-right corner again and the next grain's top-left, so
// the cells between grains have no area. Grain attributes are hashed from the index with the
// distributions FilamentField.__init__ draws; their drift is a function of dustClock.
layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec2 vQ;        // px from the grain centre
layout(location = 1) out vec4 vRgbGlow;  // rgb, opacity
layout(location = 2) out vec3 vOrb;      // halo, core, pin radii

const float N = 1100.0;

float h(float i, float k) {
    return fract(sin(i * 12.9898 + k * 78.233) * 43758.5453);
}

void main() {
    float col = floor(qt_MultiTexCoord0.x * (4.0 * N - 1.0) + 0.5);
    float i = floor(col / 4.0);
    float k = col - i * 4.0;
    vec2 corner = vec2(k == 0.0 ? -1.0 : 1.0, qt_MultiTexCoord0.y * 2.0 - 1.0);
    if (k >= 2.0) corner.y = -1.0;
    if (k == 3.0) { i += 1.0; corner.x = -1.0; }

    float size0 = 0.5 + pow(h(i, 1.0), 2.2) * 3.6;
    float spread = size0 > 2.4 ? 0.28 : 0.46;
    float t0 = 0.5 + (h(i, 2.0) * 2.0 - 1.0) * spread;
    float s = (h(i, 3.0) * 2.0 - 1.0) * 1.15;
    float z = pow(h(i, 4.0), 1.7);
    float life0 = h(i, 5.0);
    float strandI = mod(i, 4.0);
    bool hot = h(i, 6.0) < 0.14;

    // Drift along the current; past 0.96 a grain comes back in at 0.08 with life 0.
    float rate = (0.012 + speed * 0.028) * (0.5 + z);
    float adv = dustClock * (0.5 + z);
    float t = t0 + adv;
    float life;
    if (t <= 0.96) {
        life = life0 + adv / max(rate, 1e-4) * 0.16;
    } else {
        t = 0.08 + mod(t - 0.96, 0.88);
        life = (t - 0.08) / max(rate, 1e-4) * 0.16;
    }

    vec2 p = pathPoint(t, strandI);
    float fade = min(min(edgeFade(p.x), pathFade(t)), min(1.0, life * 2.2));
    float along = words != 0.0 ? max(0.0, 1.0 - abs(t - speakHead) / 0.07) : 0.0;
    vec4 e = curEllipse();
    vec2 nd = p - e.xy;
    float nl = length(nd);
    if (nl == 0.0) nl = 1.0;
    float off = s * 18.0;
    float sway = sin(time * 0.55 + life * 7.0 + z * 5.0);
    vec2 c = vec2(p.x + nd.x / nl * off + sway * (1.6 + size0 * 0.6),
                  p.y + nd.y / nl * off + cos(time * 0.4 + t * 10.0) * (1.2 + size0 * 0.6));
    // Idle under the orbit tree: the grains leave the ring and hang round the tree as its
    // sparkle (orbit_v11b's spark field), drifting and twinkling on flow.
    if (treeOn > 0.0) {
        float g1 = h(i, 7.0) + h(i, 8.0) + h(i, 9.0) - 1.5;
        float g2 = h(i, 10.0) + h(i, 11.0) + h(i, 12.0) - 1.5;
        vec2 sc = vec2(tree.z + g1 * 0.55 * view.y,
                       h(i, 13.0) < 0.6 ? view.y * 0.29 + g2 * 0.33 * view.y
                                        : view.y * (0.06 + 0.9 * h(i, 14.0)));
        sc += vec2(sin(flow * 0.21 + life0 * 9.0), cos(flow * 0.17 + z * 7.0)) * (3.0 + size0);
        float tw = 0.55 + 0.45 * sin(TAU * (flow / TREE_LOOP * (1.0 + floor(h(i, 15.0) * 2.0)) + h(i, 16.0)));
        c = mix(c, sc, treeOn);
        fade = mix(fade, 0.6 * edgeFade(sc.x) * tw * step(2.0, sc.y) * step(sc.y, view.y - 2.0), treeOn);
    }
    vec3 rgb = (hot || size0 > 2.8) ? coreColor.rgb : tone(t);
    float glow = (0.34 + z * 0.52 + pulseT * 0.22 + along * 0.7) * fade;
    if (hot) glow = min(1.35, glow * 1.85);
    // The baked stamp's own rounding (_orb_key): integer halo and core, a 0.85 pin or none.
    float halo = max(2.0, floor(size0 * (hot ? 3.8 : 2.6) + 0.5));
    float core = floor(size0 * (hot ? 0.70 : 0.48) + 0.5);
    float pin = (hot || size0 > 2.6 || size0 > 1.4) ? 0.85 : 0.0;
    float reach = halo + 2.0;
    if (fade < 0.14) reach = 0.0;  // a grain Python would skip: a zero quad
    vQ = corner * reach;
    vRgbGlow = vec4(rgb, clamp(glow, 0.0, 1.0));
    vOrb = vec3(halo, core, pin);
    gl_Position = qt_Matrix * vec4(c + corner * reach, 0.0, 1.0);
}
