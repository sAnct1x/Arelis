// The tree's light packets as clear travelling dots (Vela's note 3), drawn with dust.frag.
// Each of the 11 limbs has a packet: a bright head and 5 smaller dots trailing it, from her
// feet along the floor, up the trunk, out the limb (staggered, one loop each). Each of the
// 36 twigs carries a small dot with 2 trailing, running out to its curl on its own phase.
// GridMesh (4 * N - 1) x 1, one quad per dot, as dust.vert.
layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec2 vQ;
layout(location = 1) out vec4 vRgbGlow;
layout(location = 2) out vec3 vOrb;

const float N = 11.0 * 6.0 + 36.0 * 3.0;

void main() {
    float col = floor(qt_MultiTexCoord0.x * (4.0 * N - 1.0) + 0.5);
    float i = floor(col / 4.0);
    float kk = col - i * 4.0;
    vec2 corner = vec2(kk == 0.0 ? -1.0 : 1.0, qt_MultiTexCoord0.y * 2.0 - 1.0);
    if (kk >= 2.0) corner.y = -1.0;
    if (kk == 3.0) { i += 1.0; corner.x = -1.0; }

    float k = treeK();
    vec2 c;
    float glow, halo, core, pin;
    bool lock = false;
    if (i < 66.0) {
        int j = int(floor(i / 6.0));
        float q = mod(i, 6.0);            // 0 the head, 1..5 the trail
        float ph = packetPhase(j);
        float lf = length(tree.xy - feet) * 1.05;
        float u = limbU(j);
        float tot = lf + trunkLen() * u + length(limbTarget(j) - trunkAt(u)) * 1.15;
        float r = packetHead(j) - q * 8.0 * k / max(tot, 1.0);
        float limbFrom;
        c = routeAt(j, clamp(r, 0.0, 1.0), limbFrom);
        float fade = smoothstep(0.0, 0.03, ph) * (1.0 - smoothstep(0.79, 0.82, ph))
                   * step(0.0, r) * step(r, 1.0);
        float amp = j < 6 ? 1.0 : 0.6;
        glow = amp * fade * (q == 0.0 ? 1.0 : 0.8 * exp(-q * 0.35));
        float sz = q == 0.0 ? 1.0 : 0.75 - q * 0.1;
        halo = max(2.0, floor((j < 6 ? 16.0 : 12.0) * sz * max(k * 1.6, 0.7) + 0.5));
        core = max(1.0, floor((j < 6 ? 4.5 : 3.5) * sz * max(k * 1.6, 0.7) + 0.5));
        pin = q < 2.0 ? 0.85 : 0.0;
        lock = j < 6 && r > limbFrom + (1.0 - limbFrom) * 0.86;
    } else {
        float t = floor((i - 66.0) / 3.0);
        float q = mod(i - 66.0, 3.0);
        float ph = fract(th(t, 21.0) + flow / TREE_LOOP);
        float r = ph / 0.55 - q * 0.03;   // runs out in the first 55% of its loop
        c = twigAt(t, clamp(r, 0.0, 0.98));
        float fade = smoothstep(0.0, 0.08, r) * (1.0 - smoothstep(0.85, 0.98, r))
                   * step(0.0, r) * step(r, 1.0);
        glow = fade * (q == 0.0 ? 1.0 : 0.6 / q);
        halo = max(2.0, floor((q == 0.0 ? 10.0 : 6.0) * max(k * 1.6, 0.7) + 0.5));
        core = max(1.0, floor((q == 0.0 ? 3.0 : 1.8) * max(k * 1.6, 0.7) + 0.5));
        pin = q == 0.0 ? 0.85 : 0.0;
    }
    if (!lock) c = treeSway(c);
    glow *= treeOn * (ringScale >= 1.0 ? 1.0 : 0.0);
    float reach = halo + 2.0;
    if (glow < 0.01) reach = 0.0;
    vQ = corner * reach;
    vRgbGlow = vec4(mix(ice.rgb, coreColor.rgb, 0.6), clamp(glow, 0.0, 1.0));
    vOrb = vec3(halo, core, pin);
    gl_Position = qt_Matrix * vec4(c + corner * reach, 0.0, 1.0);
}
